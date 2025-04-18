"""
intent_detector_v2.py – drop‑in replacement for intent detection
---------------------------------------------------------------
This module implements a **hybrid multi‑label detector** that combines:

1. Fast deterministic rules for critical patterns (cheap regex / keyword‑match).
2. A light‑weight multilingual transformer encoder (Sentence‑Transformers) feeding a
   scikit‑learn One‑Vs‑Rest LogisticRegression head trained on your labelled data.
3. Optional zero‑shot fallback (Grok / OpenAI) when confidence is low.

It exposes a single async function `predict_intents(text: str) -> Dict[str, float]`
returning probabilities (0‑1) for every registered intent.  A calibration JSON sets
per‑intent thresholds – no magic numbers in code.

USAGE (pipeline_router.py):
--------------------------
```python
from app.detectors.intent_detector_v2 import predict_intents

intents = await predict_intents(message)
```

This file should live in `app/detectors/intent_detector_v2.py` and be imported from
`pipeline_router.py` instead of the old `detect_intents` helper.

The old `intent_detector.py` can remain for legacy routes until you complete A/B tests.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, List

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.multioutput import ClassifierChain
import joblib

#############################
# configuration & constants #
#############################
THIS_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_NAME = os.getenv(
    "INTENT_ENCODER", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CLASSIFIER_PATH = Path(
    os.getenv("INTENT_CLASSIFIER_HEAD", THIS_DIR / "intent_head.pkl"))
CALIBRATION_PATH = Path(
    os.getenv("INTENT_THRESHOLDS", THIS_DIR / "intent_thresholds.json"))

# deterministic quick‑rules – compiled once
RULE_PATTERNS: Dict[str, List[str]] = {
    "image_generation": [r"\b(generate|create|draw|make)\b.*\b(image|picture|photo)\b"],
    "calculation":       [r"[0-9]+\s*[+\-*/^]\s*[0-9]+", r"\bwhat(?:'s| is)\b.*\b([0-9]+).*\?"],
    "social_media":      [r"\b(post|publish|tweet|share|thread)\b"],
}
RULE_REGEX = {intent: [re.compile(p, re.IGNORECASE) for p in pats]
              for intent, pats in RULE_PATTERNS.items()}

#############################
# lazy singletons           #
#############################
_ENCODER: SentenceTransformer | None = None
_CLASSIFIER: ClassifierChain | None = None
_MLB: MultiLabelBinarizer | None = None
_THRESHOLDS: Dict[str, float] | None = None
_SINGLETON_LOCK = asyncio.Lock()


async def _load():
    """Load heavy resources once per process."""
    global _ENCODER, _CLASSIFIER, _MLB, _THRESHOLDS
    async with _SINGLETON_LOCK:
        if _ENCODER is None:
            _ENCODER = SentenceTransformer(DEFAULT_MODEL_NAME)
        if _CLASSIFIER is None:
            if not CLASSIFIER_PATH.exists():
                raise FileNotFoundError(
                    f"Classifier head not found: {CLASSIFIER_PATH}")
            _CLASSIFIER = joblib.load(CLASSIFIER_PATH)
            _MLB = _CLASSIFIER.classes_  # stored inside the chain
        if _THRESHOLDS is None:
            if CALIBRATION_PATH.exists():
                _THRESHOLDS = json.loads(CALIBRATION_PATH.read_text())
            else:
                # fallback – default 0.5 for every intent
                _THRESHOLDS = {cls: 0.5 for cls in _CLASSIFIER.classes_}

########################
# public predict API   #
########################


async def predict_intents(text: str) -> Dict[str, float]:
    """Return {intent: probability} after fusing rule + ML scores."""
    text = text.strip()
    if not text:
        return {}

    # 1) quick rule engine – if any rule matches, emit 1.0 directly
    rule_hits: Dict[str, float] = {}
    for intent, patterns in RULE_REGEX.items():
        if any(p.search(text) for p in patterns):
            rule_hits[intent] = 1.0

    # 2) ML classifier – embed → logits → sigmoid → probs
    await _load()
    assert _ENCODER and _CLASSIFIER  # for mypy
    embeddings = _ENCODER.encode(
        [text], convert_to_numpy=True, normalize_embeddings=True)
    logits = _CLASSIFIER.predict_proba(embeddings)[0]  # shape (num_intents,)
    ml_probs = {cls: float(prob)
                for cls, prob in zip(_CLASSIFIER.classes_, logits)}

    # 3) fuse: rule‑wins else ML prob
    fused: Dict[str, float] = {**ml_probs, **
                               rule_hits}  # rule overwrites if exists

    # 4) apply thresholds
    final = {intent: prob for intent, prob in fused.items() if prob >=
             _THRESHOLDS.get(intent, 0.5)}
    return final

########################
# optional: low confidence → zero‑shot fallback
########################

ZERO_SHOT_PROVIDER = os.getenv(
    "ZERO_SHOT_PROVIDER")  # "grok" | "openai" | None
ZERO_SHOT_API_KEY = os.getenv("ZERO_SHOT_API_KEY")
LOW_CONF_THRESHOLD = float(os.getenv("LOW_CONF_THRESHOLD", 0.25))


async def _zero_shot_fallback(text: str, intents: List[str]) -> Dict[str, float]:
    """Ask large model to classify when existing detectors are unsure."""
    if not ZERO_SHOT_PROVIDER or not ZERO_SHOT_API_KEY:
        return {}
    # build prompt
    prompt = (
        "You are an intent classifier. The possible intents are: " +
        ", ".join(intents) + ".\n"
        "Return a JSON dict with intent names as keys and probabilities (0‑1).\n"
        f"Text: {text!r}"
    )
    # note: real implementation would call Grok/OpenAI here – placeholder below
    # response = await call_llm(prompt)
    response = "{}"  # TODO
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {}


async def predict_intents_with_fallback(text: str) -> Dict[str, float]:
    """Same as predict_intents but asks a zero‑shot model when everything is low‑confidence."""
    probs = await predict_intents(text)
    if probs or not ZERO_SHOT_PROVIDER:
        return probs

    # all below threshold – escalate
    await _load()
    zsf = await _zero_shot_fallback(text, list(_CLASSIFIER.classes_))
    return zsf
