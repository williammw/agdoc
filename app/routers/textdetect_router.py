from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from transformers import BertTokenizer, BertModel, GPT2LMHeadModel, GPT2Tokenizer
import torch
import joblib
import re
import os

# Define the router
router = APIRouter()

# Load models and tokenizer
bert_tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
bert_model = BertModel.from_pretrained('bert-base-uncased')
gpt2_tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
gpt2_model = GPT2LMHeadModel.from_pretrained('gpt2')

# Load the pre-trained classifier
classifier_path = os.path.join(
    os.path.dirname(__file__), '../ML/classifier.pkl')
classifier = joblib.load(classifier_path)

# Function to extract features using BERT


def extract_features(text, tokenizer, model):
    inputs = tokenizer(text, return_tensors='pt',
                       padding=True, truncation=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state.mean(dim=1).squeeze().numpy()

# Request and response models


class TextRequest(BaseModel):
    text: str


class DetectionResponse(BaseModel):
    result: str


class HumanizeResponse(BaseModel):
    humanized_text: str

# AI text detection endpoint


@router.post("/detect", response_model=DetectionResponse)
async def detect_ai_text(request: TextRequest):
    try:
        features = extract_features(request.text, bert_tokenizer, bert_model)
        prediction = classifier.predict([features])
        result = 'AI-Generated' if prediction == 1 else 'Human-Written'
        return DetectionResponse(result=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Function to humanize AI-generated text


def replace_with_synonyms(text):
    # Placeholder function for synonym replacement
    words = text.split()
    synonyms = {
        "quick": "fast",
        "brown": "dark",
        "fox": "canine",
        # Add more synonyms as needed
    }
    new_text = " ".join([synonyms.get(word, word) for word in words])
    return new_text


def adjust_sentence_structure(text):
    # Placeholder function to adjust sentence structure
    sentences = re.split(r'(?<=[.!?]) +', text)
    adjusted_text = []
    for sentence in sentences:
        if len(sentence.split()) < 5 and adjusted_text:
            adjusted_text[-1] += ' ' + sentence
        else:
            adjusted_text.append(sentence)
    return ' '.join(adjusted_text)


def add_human_phrases(text):
    # Placeholder function to add human-like phrases
    phrases = [
        "you know,", "interestingly,", "in my opinion,", "it seems that"
    ]
    words = text.split()
    for i in range(0, len(words), 10):
        if i + 10 < len(words):
            words.insert(i, phrases[i % len(phrases)])
    return ' '.join(words)

# Humanize AI text endpoint


@router.post("/humanize", response_model=HumanizeResponse)
async def humanize_ai_text(request: TextRequest):
    try:
        text = request.text
        enhanced_text = replace_with_synonyms(text)
        structured_text = adjust_sentence_structure(enhanced_text)
        humanized_text = add_human_phrases(structured_text)
        return HumanizeResponse(humanized_text=humanized_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
