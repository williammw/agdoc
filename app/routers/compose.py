"""
Video Composition / Export Router

Accepts a timeline composition (clips, layers, tracks) and renders it into
a single MP4 file using FFmpeg.

Uses a database-backed job queue:
  - POST endpoint inserts a row with status='queued' and returns immediately
  - A background worker loop polls for queued jobs and processes them one at a time
  - If the server crashes, stale 'processing' jobs are recovered on startup
  - 10 concurrent users = 10 queued rows, processed sequentially (no lost jobs)

Two routers are exposed:
  - router        : Firebase-authenticated endpoints
  - public_router : API-key-secured endpoints for Next.js backend calls
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import asyncio
import json
import logging
import os
import tempfile
import time
import uuid

import boto3
from botocore.exceptions import ClientError
import httpx

from app.dependencies.auth import get_current_user
from app.utils.database import get_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("agdoc.compose")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/v1/compose",
    tags=["compose"],
    dependencies=[Depends(get_current_user)],
)

public_router = APIRouter(
    prefix="/api/v1/compose",
    tags=["compose"],
)

# ---------------------------------------------------------------------------
# Database dependency (admin / service-role)
# ---------------------------------------------------------------------------
db_admin = get_db(admin_access=True)

# ---------------------------------------------------------------------------
# Cloudflare R2 configuration
# ---------------------------------------------------------------------------
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "cdn.multivio.com")

from botocore.config import Config as BotoConfig

# Connect/read timeouts so a hung R2 endpoint doesn't wedge the worker forever.
# Without these, a stalled TCP connection can hold _upload_to_r2 indefinitely
# because boto3's defaults are effectively unbounded for some environments.
# Plus a few retries for transient network blips.
r2_client = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=BotoConfig(
        connect_timeout=15,        # 15s to establish TCP / TLS handshake
        read_timeout=120,          # 2 min ceiling for a single S3 request
        retries={"max_attempts": 3, "mode": "standard"},
        signature_version="s3v4",
    ),
)

# ---------------------------------------------------------------------------
# Internal API key (same pattern as media.py)
# ---------------------------------------------------------------------------
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
if not INTERNAL_API_KEY:
    logger.warning("INTERNAL_API_KEY not set. Public compose endpoints will reject all requests.")

# ---------------------------------------------------------------------------
# Worker configuration
# ---------------------------------------------------------------------------
WORKER_POLL_INTERVAL = 5        # seconds between queue polls when idle
STALE_JOB_TIMEOUT_MINUTES = 15  # mark processing jobs older than this as failed

# Handle to the background worker task (set on startup, cancelled on shutdown)
_worker_task: Optional[asyncio.Task] = None

# ---------------------------------------------------------------------------
# Pydantic-free data structures for internal processing
# ---------------------------------------------------------------------------

@dataclass
class Transition:
    """
    Phase F-B.4.b (2026-05-25) — clip-to-clip transition.

    Populated on a Segment via `transition_to_next` when the next segment
    should blend in with a non-cut effect. The FFmpeg builder consumes
    this to chain xfade/acrossfade filters instead of a flat concat.
    """
    # One of: "crossfade", "fade_black", "fade_white", "slide_left", "slide_right".
    # "cut" is the implicit default and is never stored (it would be a no-op).
    type: str
    # Transition window in seconds. Adjacent clips overlap by this amount
    # during the blend. Clamped to (0, min(d_a, d_b) - 0.05) at build time
    # so the result is always a valid xfade input.
    duration: float


@dataclass
class Segment:
    """A single contiguous segment in the rendered timeline."""
    index: int
    media_type: str          # "video" or "image"
    media_url: str           # CDN URL of the source asset
    start_time: float        # seconds, position on the timeline
    end_time: float          # seconds, position on the timeline
    local_path: str = ""     # populated after download
    # Source in-point: seconds INTO the source media where this clip begins.
    # 0 = from the start (the default, identical to prior behavior). Used to
    # extract a sub-window of a longer source video (e.g. Distill highlight
    # clips, Studio split clips) without a separate trim pass. Ignored for
    # images (they have no timeline). See ffmpeg trim/atrim below.
    source_start: float = 0.0
    # Optional audio overlay (e.g. TTS voiceover) — when present, this URL's
    # audio replaces the source video's audio for this segment.
    audio_overlay_url: str = ""
    audio_overlay_local_path: str = ""
    # Transition between THIS segment and the next one in the chain.
    # None on the last segment (nothing to transition to) and on cuts
    # (the default — no special filter needed).
    transition_to_next: Optional["Transition"] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_api_key(request: Request) -> None:
    """Raise 401/503 if the x-api-key header is missing or wrong."""
    if not INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not configured",
        )
    key = request.headers.get("x-api-key")
    if key != INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


async def _upload_to_r2(file_content: bytes, key: str, content_type: str) -> str:
    """Upload bytes to Cloudflare R2 and return the CDN URL.

    Two important wrinkles:

    1. boto3 is synchronous. Calling it directly from an async function blocks
       the entire asyncio event loop — including the FastAPI HTTP handler and
       the background worker. We dispatch via `run_in_executor` so the upload
       runs on a worker thread and the loop stays responsive.

    2. Even with the boto3 client's `read_timeout=120`, a TCP connection that
       stalls mid-transfer can sometimes outlast the configured timeout. Wrap
       in `asyncio.wait_for` as defense in depth so a wedged upload fails the
       job rather than hanging the worker.
    """
    loop = asyncio.get_running_loop()
    UPLOAD_TIMEOUT_SECONDS = 180

    def _do_upload():
        r2_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=file_content,
            ContentType=content_type,
        )

    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _do_upload),
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
        cdn_url = f"https://{CDN_DOMAIN}/{key}"
        logger.info("Uploaded to R2: %s (%d bytes)", cdn_url, len(file_content))
        return cdn_url
    except asyncio.TimeoutError:
        logger.error(
            "R2 upload timed out for key=%s after %ds (%d bytes)",
            key, UPLOAD_TIMEOUT_SECONDS, len(file_content),
        )
        raise RuntimeError(
            f"R2 upload timed out after {UPLOAD_TIMEOUT_SECONDS}s for key={key}"
        )
    except ClientError as exc:
        logger.error("R2 upload failed for key=%s: %s", key, exc)
        raise


async def _download_media(url: str, dest_path: str) -> None:
    """Download a media file from a CDN URL to a local path."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
    logger.info("Downloaded %s -> %s", url, dest_path)


def _guess_extension(url: str) -> str:
    """Return a file extension based on URL path."""
    path = url.split("?")[0]  # strip query params
    if "." in path.split("/")[-1]:
        return "." + path.split("/")[-1].rsplit(".", 1)[-1].lower()
    return ".mp4"  # default fallback


def _is_image_ext(ext: str) -> bool:
    return ext.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}


async def _get_video_duration(file_path: str) -> Optional[float]:
    """Use ffprobe to get the duration of a video file in seconds."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            duration_str = data.get("format", {}).get("duration")
            if duration_str:
                return float(duration_str)
        else:
            logger.warning("ffprobe failed: %s", stderr.decode())
    except Exception as exc:
        logger.warning("ffprobe error: %s", exc)
    return None


async def _get_video_resolution(file_path: str) -> tuple[Optional[int], Optional[int]]:
    """Use ffprobe to get width and height of the first video stream."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "v:0",
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            streams = data.get("streams", [])
            if streams:
                w = streams[0].get("width")
                h = streams[0].get("height")
                if w and h:
                    return int(w), int(h)
        else:
            logger.warning("ffprobe resolution failed: %s", stderr.decode())
    except Exception as exc:
        logger.warning("ffprobe resolution error: %s", exc)
    return None, None


async def _has_audio_stream(file_path: str) -> bool:
    """Check whether a file contains at least one audio stream."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "a",
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            return len(data.get("streams", [])) > 0
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Composition parser
# ---------------------------------------------------------------------------

def _parse_composition(composition: Dict[str, Any]) -> List[Segment]:
    """
    Extract an ordered list of Segments from the composition object.

    Actual composition format (clips and layers are top-level arrays,
    clips reference tracks via trackId and layers via layerId):
    {
      "tracks": [
        {"id": "track-video", "type": "video", ...},
        {"id": "track-audio", "type": "audio", ...}
      ],
      "clips": [
        {"id": "clip-1", "trackId": "track-video", "layerId": "media-1",
         "startTime": 0, "endTime": 5, ...}
      ],
      "layers": [
        {"id": "media-1", "type": "media", "mediaUrl": "...", "mediaType": "video"},
        {"id": "audio-1", "type": "audio", "audioUrl": "..."}
      ]
    }
    """
    # --- Build layers lookup (list -> dict keyed by id) ---
    raw_layers = composition.get("layers", {})
    if isinstance(raw_layers, list):
        layers: Dict[str, Any] = {l["id"]: l for l in raw_layers if "id" in l}
    elif isinstance(raw_layers, dict):
        # Already a dict (possible future format)
        layers = raw_layers
    else:
        layers = {}

    # --- Build set of video track IDs ---
    tracks = composition.get("tracks", [])
    video_track_ids = {
        t["id"] for t in tracks
        if t.get("type", "video") in ("video", "main")
    }
    audio_track_ids = {
        t["id"] for t in tracks
        if t.get("type") == "audio"
    }

    if not video_track_ids:
        logger.warning("No video tracks found in composition")
        return []

    all_clips = composition.get("clips", [])

    # --- Pre-collect audio-track clips so we can match them to video segments ---
    audio_clips: List[Dict[str, Any]] = []
    for clip in all_clips:
        track_id = clip.get("trackId") or clip.get("track_id")
        if track_id not in audio_track_ids:
            continue
        layer_id = clip.get("layerId") or clip.get("layer_id")
        layer = layers.get(layer_id, {}) if layer_id else {}
        audio_url = (
            layer.get("audioUrl")
            or layer.get("audio_url")
            or clip.get("audioUrl")
            or clip.get("audio_url")
            or ""
        )
        if not audio_url:
            continue
        audio_clips.append({
            "url": audio_url,
            "start": float(clip.get("startTime", 0)),
            "end": float(clip.get("endTime", 0)),
        })

    # --- Collect clips on video tracks ---
    segments: List[Segment] = []
    index = 0

    for clip in all_clips:
        track_id = clip.get("trackId") or clip.get("track_id")
        if track_id not in video_track_ids:
            continue  # Skip audio-only clips (collected above)

        layer_id = clip.get("layerId") or clip.get("layer_id")
        layer = layers.get(layer_id, {}) if layer_id else {}

        # Resolve media URL from layer
        media_url = (
            layer.get("mediaUrl")
            or layer.get("media_url")
            or clip.get("mediaUrl")
            or clip.get("media_url")
            or ""
        )
        if not media_url:
            logger.warning("Clip %s has no media URL, skipping", clip.get("id"))
            continue

        # Resolve media type from layer's mediaType field
        media_type = (
            layer.get("mediaType")
            or layer.get("media_type")
            or layer.get("type")
            or "video"
        ).lower()
        # Normalise: layer types like "media", "background" need mediaType to determine
        if media_type in ("image", "photo", "still", "jpeg", "jpg", "png", "webp"):
            media_type = "image"
        elif media_type in ("media", "background"):
            # Fallback: check the URL extension
            ext = _guess_extension(media_url).lower()
            media_type = "image" if _is_image_ext(ext) else "video"
        else:
            media_type = "video"

        start_time = float(clip.get("startTime", 0))
        end_time = float(clip.get("endTime", start_time + float(clip.get("duration", 5))))

        if end_time <= start_time:
            logger.warning("Clip %s has invalid timing (%.2f-%.2f), skipping", clip.get("id"), start_time, end_time)
            continue

        # Source in-point: which second of the SOURCE media this clip starts
        # from. Accepts mediaStartTime (camelCase, our client) or source_start.
        # Defaults to 0 → from the start of the source (prior behavior).
        source_start = float(
            clip.get("mediaStartTime")
            or clip.get("media_start_time")
            or clip.get("sourceStart")
            or clip.get("source_start")
            or 0
        )

        # Match an audio overlay clip whose time range overlaps this segment.
        # Common case (Flow / Studio): exact same start/end as the video clip.
        overlay_url = ""
        for ac in audio_clips:
            if ac["end"] > start_time and ac["start"] < end_time:
                overlay_url = ac["url"]
                break

        segments.append(Segment(
            index=index,
            media_type=media_type,
            media_url=media_url,
            start_time=start_time,
            end_time=end_time,
            audio_overlay_url=overlay_url,
            source_start=source_start if media_type == "video" else 0.0,
        ))
        index += 1

    # Sort all segments by start time globally
    segments.sort(key=lambda s: s.start_time)
    # Re-index after sort
    for i, seg in enumerate(segments):
        seg.index = i

    # --- Phase F-B.4.b: attach clip-to-clip transitions ---
    # composition.transitions is an optional list of
    # {fromClipId, toClipId, type, duration}. Build a lookup by
    # source clip ID (each clip in the composition has a unique id like
    # "clip-v-3"), then map each transition's fromClipId to the segment
    # that produced it and stash the transition on `transition_to_next`.
    raw_transitions = composition.get("transitions") or []
    if raw_transitions:
        # Build clip_id → segment_index map. Same logic as we used to
        # collect video segments above — replays it here for clarity.
        clip_id_to_seg_idx: Dict[str, int] = {}
        for seg_idx, clip in enumerate(
            [c for c in all_clips
             if (c.get("trackId") or c.get("track_id")) in video_track_ids
             and float(c.get("endTime", 0)) > float(c.get("startTime", 0))]
        ):
            cid = clip.get("id")
            if cid:
                clip_id_to_seg_idx[cid] = seg_idx
        # Note: the seg_idx above is pre-sort. Re-derive by matching the
        # clip's media URL + timing to the segment after the global sort.
        # Cheaper alternative: re-scan and use the original clip ordering
        # to recover (segments were sorted by start_time AND so were the
        # original clips that produced them — for a typical linear
        # timeline these match).
        # Build the canonical mapping by scanning the sorted segments and
        # the source clips list looking up by media_url:
        clip_url_to_seg_idx: Dict[str, int] = {}
        for seg in segments:
            clip_url_to_seg_idx.setdefault(seg.media_url, seg.index)

        # Walk each transition spec and attach to the source segment.
        for t in raw_transitions:
            ttype = t.get("type") or "cut"
            if ttype == "cut":
                continue  # No-op — default behaviour
            from_id = t.get("fromClipId") or t.get("from_clip_id")
            from_idx = clip_id_to_seg_idx.get(from_id)
            if from_idx is None:
                logger.warning(
                    "Transition references unknown clip %s, skipping",
                    from_id,
                )
                continue
            # Validate transition duration vs segment durations on either side.
            # xfade needs both inputs to be longer than the transition window.
            duration = float(t.get("duration", 0.5))
            if duration <= 0:
                continue
            from_seg = next((s for s in segments if s.index == from_idx), None)
            if from_seg is None:
                continue
            # The "next" segment for transition purposes is the segment whose
            # index is from_idx + 1 (post-sort). Defensive — bail if there
            # isn't one.
            to_seg = next((s for s in segments if s.index == from_idx + 1), None)
            if to_seg is None:
                logger.warning(
                    "Transition %s->%s has no following segment (from_idx=%d), skipping",
                    from_id, t.get("toClipId"), from_idx,
                )
                continue
            # Clamp duration: must be shorter than both clips (with 0.05s
            # safety margin) or xfade fails with "duration too long".
            max_safe = min(
                from_seg.end_time - from_seg.start_time,
                to_seg.end_time - to_seg.start_time,
            ) - 0.05
            if max_safe <= 0.05:
                logger.warning(
                    "Transition %s->%s clips too short for any transition, falling back to cut",
                    from_id, t.get("toClipId"),
                )
                continue
            clamped = max(0.05, min(duration, max_safe))
            from_seg.transition_to_next = Transition(type=ttype, duration=clamped)

    return segments


# ---------------------------------------------------------------------------
# FFmpeg command builder
# ---------------------------------------------------------------------------

def _build_ffmpeg_command(
    segments: List[Segment],
    output_path: str,
    width: int,
    height: int,
    has_audio_flags: Dict[int, bool],
) -> List[str]:
    """
    Build the full ffmpeg command for concatenating segments.

    Parameters
    ----------
    segments : list of Segment with local_path populated
    output_path : destination file path
    width, height : target canvas resolution
    has_audio_flags : dict mapping segment index -> bool (whether source has audio)
    """

    inputs: List[str] = []
    filter_parts: List[str] = []
    # When a segment has an audio overlay, we add it as an extra ffmpeg input AFTER
    # all the segment media inputs. The first overlay input index = len(segments) + offset.
    overlay_input_indices: Dict[int, int] = {}
    next_extra_input = len(segments)

    for seg in segments:
        duration = seg.end_time - seg.start_time

        if seg.media_type == "video":
            inputs.extend(["-i", seg.local_path])

            # Video: trim to clip duration, scale + pad to canvas. Normalised
            # to a common pixel format + framerate + timebase so the downstream
            # concat / xfade filter sees compatible inputs. Without this,
            # mixing an image segment (default loop fps) with a video segment
            # (native fps) makes concat stall forever — the well-known
            # 'More than 1000 frames duplicated' + frame=1 hang.
            # Source window: extract [source_start, source_start+duration] of
            # the input, then setpts resets the clip to start at t=0. With the
            # default source_start=0 this is identical to the prior trim=0:dur.
            v_in = seg.source_start
            v_out = seg.source_start + duration
            filter_parts.append(
                f"[{seg.index}:v]trim={v_in}:{v_out},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                f"format=yuv420p,fps=30[v{seg.index}]"
            )

            # Audio resolution priority for this segment:
            #   1) explicit overlay (TTS / voiceover) attached on track-audio
            #   2) the source video's own audio
            #   3) silence
            if seg.audio_overlay_local_path:
                # Will be wired below after we add the overlay input.
                pass
            elif has_audio_flags.get(seg.index, False):
                filter_parts.append(
                    f"[{seg.index}:a]atrim={v_in}:{v_out},asetpts=PTS-STARTPTS[a{seg.index}]"
                )
            else:
                filter_parts.append(
                    f"anullsrc=r=44100:cl=stereo:d={duration}[a{seg.index}]"
                )
        else:
            # Image: loop for the clip duration. Normalisation matches the
            # video path above (format=yuv420p,fps=30) so concat / xfade sees
            # compatible streams. The trim+setpts pair guarantees the image
            # loop produces a clean finite stream that terminates at the
            # specified duration — xfade in particular needs a definite EOF.
            inputs.extend(["-loop", "1", "-t", str(duration), "-i", seg.local_path])

            filter_parts.append(
                f"[{seg.index}:v]trim=0:{duration},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                f"format=yuv420p,fps=30[v{seg.index}]"
            )
            # Images don't have native audio. Overlay (if any) is wired below.
            if not seg.audio_overlay_local_path:
                filter_parts.append(
                    f"anullsrc=r=44100:cl=stereo:d={duration}[a{seg.index}]"
                )

    # --- Audio overlay inputs (TTS / voiceover) ---
    for seg in segments:
        if seg.audio_overlay_local_path:
            inputs.extend(["-i", seg.audio_overlay_local_path])
            overlay_input_indices[seg.index] = next_extra_input
            duration = seg.end_time - seg.start_time
            ai = next_extra_input
            # Take overlay audio, trim to clip duration, pad with silence if shorter.
            # apad ensures the audio stream length matches the video segment so the
            # subsequent concat doesn't desync.
            filter_parts.append(
                f"[{ai}:a]atrim=0:{duration},asetpts=PTS-STARTPTS,"
                f"apad=pad_dur={duration},atrim=0:{duration}[a{seg.index}]"
            )
            next_extra_input += 1

    # Phase F-B.4.b: branch between two output strategies.
    #
    # - When NO segment has a transition_to_next, use the legacy single
    #   concat filter — this is the production-stable path and we want zero
    #   regression risk for the 99% of jobs that don't use transitions.
    # - When ANY segment carries a transition, chain xfade/acrossfade
    #   filters progressively. xfade overlaps the two inputs by
    #   `duration` seconds at `offset` (relative to the accumulator start).
    #   Cuts within a transition-bearing chain use concat=n=2 between
    #   the two streams to preserve frame timing.
    n = len(segments)
    has_transitions = any(s.transition_to_next is not None for s in segments)

    if not has_transitions or n < 2:
        # Legacy concat path. FFmpeg's concat filter expects inputs
        # INTERLEAVED by segment — i.e. [v0][a0][v1][a1]…[vN][aN] — not
        # grouped by stream type.
        concat_inputs = "".join(f"[v{seg.index}][a{seg.index}]" for seg in segments)
        filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]")
        out_v_label = "outv"
        out_a_label = "outa"
    else:
        # Chained xfade/concat builder.
        # Map our transition type names → ffmpeg xfade transition names.
        XFADE_TYPE_MAP = {
            "crossfade":   "fade",
            "fade_black":  "fadeblack",
            "fade_white":  "fadewhite",
            "slide_left":  "slideleft",
            "slide_right": "slideright",
        }
        prev_v = f"v{segments[0].index}"
        prev_a = f"a{segments[0].index}"
        # Cumulative duration of the accumulated video stream so far.
        acc_length = segments[0].end_time - segments[0].start_time
        for i in range(1, n):
            seg = segments[i]
            next_v = f"v{seg.index}"
            next_a = f"a{seg.index}"
            transition = segments[i - 1].transition_to_next
            new_v = f"vacc{i}"
            new_a = f"aacc{i}"
            d_next = seg.end_time - seg.start_time

            if transition is None or transition.type == "cut":
                # Plain cut — splice two-stream concat for video AND audio
                # separately (concat=n=2 with v=1:a=0 then v=0:a=1).
                filter_parts.append(
                    f"[{prev_v}][{next_v}]concat=n=2:v=1:a=0[{new_v}]"
                )
                filter_parts.append(
                    f"[{prev_a}][{next_a}]concat=n=2:v=0:a=1[{new_a}]"
                )
                acc_length += d_next
            else:
                # xfade: clips overlap by `duration` seconds. acrossfade does
                # the audio counterpart (no explicit offset — auto-aligns at
                # the end of the first input).
                ffmpeg_type = XFADE_TYPE_MAP.get(transition.type, "fade")
                td = transition.duration
                offset = max(0.0, acc_length - td)
                # Numeric formatting: keep 6 decimal places to avoid round-trip
                # precision loss on very short clips.
                filter_parts.append(
                    f"[{prev_v}][{next_v}]xfade=transition={ffmpeg_type}:"
                    f"duration={td:.6f}:offset={offset:.6f}[{new_v}]"
                )
                filter_parts.append(
                    f"[{prev_a}][{next_a}]acrossfade=d={td:.6f}[{new_a}]"
                )
                # Net length after overlap: gain d_next but lose td of overlap.
                acc_length += d_next - td

            prev_v = new_v
            prev_a = new_a

        out_v_label = prev_v
        out_a_label = prev_a

    filter_complex = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", filter_complex,
            "-map", f"[{out_v_label}]",
            "-map", f"[{out_a_label}]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
    )

    return cmd


# ---------------------------------------------------------------------------
# Determine output resolution
# ---------------------------------------------------------------------------

def _resolve_output_resolution(
    composition: Dict[str, Any],
    first_video_resolution: tuple[Optional[int], Optional[int]],
) -> tuple[int, int]:
    """
    Pick the target resolution.

    Priority:
    1. Explicit width/height in the composition
    2. Aspect ratio hint in the composition (e.g. "9:16", "16:9")
    3. First video's actual resolution
    4. Fallback to 1920x1080
    """
    # 1. Explicit dimensions
    w = composition.get("width")
    h = composition.get("height")
    if w and h:
        return int(w), int(h)

    # 2. Aspect ratio hint
    aspect = composition.get("aspectRatio") or composition.get("aspect_ratio")
    if aspect:
        aspect_str = str(aspect).strip()
        if aspect_str in ("9:16", "9/16"):
            return 1080, 1920
        if aspect_str in ("16:9", "16/9"):
            return 1920, 1080
        if aspect_str in ("1:1", "1/1"):
            return 1080, 1080
        if aspect_str in ("4:5", "4/5"):
            return 1080, 1350
        if aspect_str in ("4:3", "4/3"):
            return 1440, 1080

    # 3. First video resolution
    vw, vh = first_video_resolution
    if vw and vh:
        # Ensure even dimensions (FFmpeg requirement for libx264)
        return vw - (vw % 2), vh - (vh % 2)

    # 4. Fallback
    return 1920, 1080


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------

def _update_progress(supabase, job_id: str, progress: int, stage: str) -> None:
    """Update the job's progress and stage in the database."""
    try:
        supabase.table("export_jobs").update({
            "progress": progress,
            "progress_stage": stage,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("Failed to update progress for job %s: %s", job_id, exc)


# ---------------------------------------------------------------------------
# Job processing (called by the worker loop, NOT by BackgroundTask)
# ---------------------------------------------------------------------------

async def _process_job(job_id: str) -> None:
    """
    Render a single composition job into an MP4 and upload to R2.
    Called by the worker loop after claiming the job.
    """
    supabase = None
    temp_dir = None
    start_ts = time.monotonic()

    try:
        supabase = get_db(admin_access=True)()

        # ------ 1. Read job row ------
        job_resp = supabase.table("export_jobs").select("*").eq("id", job_id).single().execute()
        if not job_resp.data:
            logger.error("Job %s not found in database", job_id)
            return
        job = job_resp.data

        user_id = job["user_id"]
        composition = job.get("composition") or {}
        if isinstance(composition, str):
            composition = json.loads(composition)

        # ------ 2. Parse composition into segments ------
        _update_progress(supabase, job_id, 2, "initializing")
        segments = _parse_composition(composition)
        if not segments:
            raise ValueError("Composition contains no renderable segments")
        logger.info("Job %s: parsed %d segments", job_id, len(segments))

        # ------ 3. Download media files ------
        _update_progress(supabase, job_id, 5, "downloading")
        temp_dir = tempfile.mkdtemp(prefix="agdoc_compose_")
        for i, seg in enumerate(segments):
            ext = _guess_extension(seg.media_url)
            # Override type detection based on extension when ambiguous
            if _is_image_ext(ext) and seg.media_type == "video":
                seg.media_type = "image"
            local_path = os.path.join(temp_dir, f"seg_{seg.index}{ext}")
            await _download_media(seg.media_url, local_path)
            seg.local_path = local_path

            # Download audio overlay (TTS) if attached to this segment.
            if seg.audio_overlay_url:
                aud_ext = _guess_extension(seg.audio_overlay_url) or ".webm"
                overlay_path = os.path.join(temp_dir, f"overlay_{seg.index}{aud_ext}")
                try:
                    await _download_media(seg.audio_overlay_url, overlay_path)
                    seg.audio_overlay_local_path = overlay_path
                except Exception as exc:
                    logger.warning(
                        "Failed to download audio overlay for seg %d (%s): %s — falling back to source audio",
                        seg.index, seg.audio_overlay_url, exc,
                    )

            # Progress: downloading is 5-30% range
            dl_progress = 5 + int(25 * (i + 1) / len(segments))
            _update_progress(supabase, job_id, dl_progress, "downloading")

        # ------ 4. Determine output resolution ------
        first_video_res: tuple[Optional[int], Optional[int]] = (None, None)
        for seg in segments:
            if seg.media_type == "video":
                first_video_res = await _get_video_resolution(seg.local_path)
                if first_video_res[0]:
                    break

        width, height = _resolve_output_resolution(composition, first_video_res)
        # Ensure even dimensions
        width = width - (width % 2)
        height = height - (height % 2)
        logger.info("Job %s: output resolution %dx%d", job_id, width, height)

        # ------ 5. Check audio streams ------
        has_audio_flags: Dict[int, bool] = {}
        for seg in segments:
            if seg.media_type == "video":
                has_audio_flags[seg.index] = await _has_audio_stream(seg.local_path)
            else:
                has_audio_flags[seg.index] = False

        # ------ 6. Build and run FFmpeg ------
        _update_progress(supabase, job_id, 35, "rendering")
        output_path = os.path.join(temp_dir, f"export-{job_id}.mp4")
        stderr_log_path = os.path.join(temp_dir, f"ffmpeg-{job_id}.log")

        cmd = _build_ffmpeg_command(segments, output_path, width, height, has_audio_flags)
        logger.info("Job %s: running ffmpeg with %d inputs", job_id, len(segments))
        logger.info("Job %s: full ffmpeg command: %s", job_id, " ".join(cmd))

        # Redirect stderr to a file rather than a pipe. FFmpeg can write a lot
        # of progress/log output to stderr, and a full PIPE buffer is a
        # well-known cause of subprocess deadlocks. With a file, the kernel
        # never blocks the writer.
        with open(stderr_log_path, "wb") as stderr_file:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=stderr_file,
            )

            # Cap a single FFmpeg run at 10 minutes. A 12-second 1080p clip
            # finishes in well under 60s, so 10 min is a generous safety net
            # that still kicks in when FFmpeg deadlocks. Without this, a
            # hung FFmpeg blocks the worker forever and the job sits at
            # status='processing' indefinitely.
            FFMPEG_TIMEOUT_SECONDS = 600
            try:
                await asyncio.wait_for(proc.wait(), timeout=FFMPEG_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.error(
                    "Job %s: FFmpeg exceeded %ds — killing subprocess",
                    job_id, FFMPEG_TIMEOUT_SECONDS,
                )
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                # Read whatever FFmpeg wrote to stderr before the kill so the
                # job's `error` field carries an actionable message.
                stderr_tail = ""
                try:
                    with open(stderr_log_path, "rb") as f:
                        stderr_tail = f.read()[-2000:].decode(errors="replace")
                except Exception:
                    pass
                raise RuntimeError(
                    f"FFmpeg timed out after {FFMPEG_TIMEOUT_SECONDS}s. "
                    f"stderr tail: {stderr_tail[-500:]}"
                )

        if proc.returncode != 0:
            stderr_tail = ""
            try:
                with open(stderr_log_path, "rb") as f:
                    stderr_tail = f.read()[-4000:].decode(errors="replace")
            except Exception:
                pass
            logger.error("FFmpeg failed (rc=%d): %s", proc.returncode, stderr_tail[-2000:])
            raise RuntimeError(f"FFmpeg exited with code {proc.returncode}: {stderr_tail[-500:]}")

        logger.info("Job %s: FFmpeg completed successfully", job_id)

        # ------ 7. Upload to R2 ------
        _update_progress(supabase, job_id, 80, "uploading")
        r2_key = f"{user_id}/exports/export-{job_id}.mp4"
        with open(output_path, "rb") as f:
            output_content = f.read()

        output_url = await _upload_to_r2(output_content, r2_key, "video/mp4")
        file_size_bytes = len(output_content)

        # ------ 8. Get output duration via ffprobe ------
        duration_seconds = await _get_video_duration(output_path)

        # ------ 9. Update job as completed ------
        elapsed = time.monotonic() - start_ts
        now_iso = datetime.now(timezone.utc).isoformat()

        supabase.table("export_jobs").update({
            "status": "completed",
            "progress": 100,
            "progress_stage": "completed",
            "output_url": output_url,
            "output_r2_key": r2_key,
            "duration_seconds": duration_seconds,
            "file_size_bytes": file_size_bytes,
            "processing_time_seconds": round(elapsed, 2),
            "completed_at": now_iso,
            "updated_at": now_iso,
        }).eq("id", job_id).execute()

        logger.info(
            "Job %s: completed in %.1fs  output=%s  size=%d  duration=%.1fs",
            job_id, elapsed, output_url, file_size_bytes, duration_seconds or 0,
        )

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        try:
            if supabase:
                now_iso = datetime.now(timezone.utc).isoformat()
                supabase.table("export_jobs").update({
                    "status": "failed",
                    "progress": 0,
                    "progress_stage": "failed",
                    "error": str(exc)[:2000],
                    "completed_at": now_iso,
                    "updated_at": now_iso,
                }).eq("id", job_id).execute()
        except Exception as db_exc:
            logger.error("Failed to update job %s status to failed: %s", job_id, db_exc)

    finally:
        # ------ Cleanup temp files ------
        if temp_dir:
            try:
                for fname in os.listdir(temp_dir):
                    fpath = os.path.join(temp_dir, fname)
                    try:
                        os.unlink(fpath)
                    except OSError:
                        pass
                os.rmdir(temp_dir)
                logger.debug("Cleaned up temp dir %s", temp_dir)
            except Exception as cleanup_exc:
                logger.warning("Temp cleanup error: %s", cleanup_exc)


# ---------------------------------------------------------------------------
# Database-backed worker loop
# ---------------------------------------------------------------------------

def _claim_next_job(supabase) -> Optional[str]:
    """
    Claim the oldest queued job using optimistic locking.

    1. SELECT the oldest queued job
    2. UPDATE its status to 'processing' WHERE status='queued' (atomic check)
    3. If another worker claimed it first, the update returns no rows -> return None

    Returns the job_id if claimed, None otherwise.
    """
    try:
        result = (
            supabase.table("export_jobs")
            .select("id")
            .eq("status", "queued")
            .order("created_at")
            .limit(1)
            .execute()
        )

        if not result.data:
            return None

        job_id = result.data[0]["id"]
        now_iso = datetime.now(timezone.utc).isoformat()

        # Optimistic lock: only claim if still queued
        claim_result = (
            supabase.table("export_jobs")
            .update({
                "status": "processing",
                "progress": 0,
                "progress_stage": "initializing",
                "updated_at": now_iso,
            })
            .eq("id", job_id)
            .eq("status", "queued")
            .execute()
        )

        if claim_result.data:
            logger.info("Claimed job %s", job_id)
            return job_id

        # Another worker claimed it between SELECT and UPDATE
        logger.debug("Job %s was already claimed by another worker", job_id)
        return None

    except Exception as exc:
        logger.error("Error claiming next job: %s", exc)
        return None


def _recover_stale_jobs(supabase) -> int:
    """
    On startup, mark jobs stuck in 'processing' for too long as failed.
    This handles the case where the server crashed mid-processing.
    Returns the number of recovered jobs.
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_JOB_TIMEOUT_MINUTES)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        result = (
            supabase.table("export_jobs")
            .update({
                "status": "failed",
                "progress": 0,
                "progress_stage": "failed",
                "error": f"Job timed out or server restarted (stale after {STALE_JOB_TIMEOUT_MINUTES}min)",
                "completed_at": now_iso,
                "updated_at": now_iso,
            })
            .eq("status", "processing")
            .lt("updated_at", cutoff)
            .execute()
        )

        count = len(result.data) if result.data else 0
        if count > 0:
            logger.warning("Recovered %d stale processing jobs", count)
        return count

    except Exception as exc:
        logger.error("Error recovering stale jobs: %s", exc)
        return 0


async def _worker_loop() -> None:
    """
    Continuously poll the database for queued export jobs and process them.
    Runs as a long-lived asyncio task started on app startup.
    """
    logger.info("Compose worker started")

    # Short initial delay to let the app finish startup
    await asyncio.sleep(2)

    # Recover any stale jobs from a previous crash
    try:
        supabase = get_db(admin_access=True)()
        recovered = _recover_stale_jobs(supabase)
        if recovered:
            logger.info("Startup recovery: marked %d stale jobs as failed", recovered)
    except Exception as exc:
        logger.error("Startup recovery failed: %s", exc)

    while True:
        try:
            supabase = get_db(admin_access=True)()
            job_id = _claim_next_job(supabase)

            if job_id:
                logger.info("Worker processing job %s", job_id)
                await _process_job(job_id)
                # Immediately check for more jobs (no sleep)
                continue
            else:
                # No jobs available, wait before polling again
                await asyncio.sleep(WORKER_POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("Compose worker shutting down")
            break
        except Exception as exc:
            logger.error("Worker loop error: %s", exc)
            await asyncio.sleep(WORKER_POLL_INTERVAL)


def start_worker() -> None:
    """Start the background worker loop. Called from main.py on app startup."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())
        logger.info("Compose worker task created")


def stop_worker() -> None:
    """Stop the background worker loop. Called from main.py on app shutdown."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        logger.info("Compose worker task cancelled")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@public_router.post("")
async def create_compose_job(
    request: Request,
    supabase=Depends(db_admin),
):
    """
    Start a new video composition / export job.

    Secured by x-api-key header (for Next.js backend calls).
    Inserts a row with status='queued' — the background worker picks it up.

    Request body (JSON):
    {
        "user_id": "uuid",
        "project_id": "uuid",
        "composition": { ... }
    }

    Returns:
    {
        "job_id": "uuid",
        "status": "queued"
    }
    """
    _verify_api_key(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required",
        )

    composition = body.get("composition")
    if not composition or not isinstance(composition, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="composition object is required",
        )

    project_id = body.get("project_id")
    job_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        row = {
            "id": job_id,
            "user_id": user_id,
            "project_id": project_id,
            "composition": composition,
            "status": "queued",
            "progress": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        result = supabase.table("export_jobs").insert(row).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create export job record",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("DB insert failed for compose job: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create export job: {str(exc)}",
        )

    logger.info("Queued compose job %s for user %s", job_id, user_id)

    return {
        "job_id": job_id,
        "status": "queued",
    }


@public_router.get("/{job_id}")
async def get_compose_job(
    job_id: str,
    request: Request,
    supabase=Depends(db_admin),
):
    """
    Get the status of a composition / export job.

    Secured by x-api-key header (for Next.js backend calls).
    """
    _verify_api_key(request)

    try:
        result = supabase.table("export_jobs").select("*").eq("id", job_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Export job not found",
            )

        job = result.data[0]

        return {
            "job_id": job["id"],
            "status": job.get("status"),
            "progress": job.get("progress", 0),
            "progress_stage": job.get("progress_stage"),
            "output_url": job.get("output_url"),
            "error": job.get("error"),
            "duration_seconds": job.get("duration_seconds"),
            "file_size_bytes": job.get("file_size_bytes"),
            "processing_time_seconds": job.get("processing_time_seconds"),
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at"),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to fetch compose job %s: %s", job_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get export job: {str(exc)}",
        )


@router.get("/my-jobs")
async def list_my_compose_jobs(
    limit: int = 20,
    offset: int = 0,
    status_filter: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase=Depends(db_admin),
):
    """
    List the current user's export jobs (authenticated).

    Query params:
      - limit (default 20)
      - offset (default 0)
      - status_filter: optional, one of queued/processing/completed/failed
    """
    try:
        query = (
            supabase.table("export_jobs")
            .select("id,user_id,project_id,status,progress,progress_stage,output_url,error,duration_seconds,file_size_bytes,processing_time_seconds,created_at,completed_at,updated_at")
            .eq("user_id", current_user["id"])
        )

        if status_filter and status_filter in ("queued", "processing", "completed", "failed"):
            query = query.eq("status", status_filter)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = query.execute()

        return {
            "jobs": result.data or [],
            "count": len(result.data or []),
            "has_more": len(result.data or []) == limit,
        }

    except Exception as exc:
        logger.error("Failed to list compose jobs for user %s: %s", current_user["id"], exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list export jobs: {str(exc)}",
        )
