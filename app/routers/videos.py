"""
Video Processing Router

Endpoints for video-specific operations:
  - POST /api/v1/videos/slideshow — Create Ken Burns slideshow from images

Uses the same job queue pattern as compose.py: inserts a DB row with
status='queued', background worker picks it up and processes via FFmpeg.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
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

from app.utils.database import get_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("agdoc.videos")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Router (API-key secured for Next.js backend calls)
# ---------------------------------------------------------------------------
public_router = APIRouter(
    prefix="/api/v1/videos",
    tags=["videos"],
)

# ---------------------------------------------------------------------------
# Database + R2 setup
# ---------------------------------------------------------------------------
db_admin = get_db(admin_access=True)

R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "cdn.multivio.com")

r2_client = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# Worker config
WORKER_POLL_INTERVAL = 5
_worker_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_api_key(request: Request) -> None:
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=503, detail="Service not configured")
    key = request.headers.get("x-api-key")
    if key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def _download_file(url: str, dest: str) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                    f.write(chunk)
    logger.info("Downloaded %s -> %s", url, dest)


async def _upload_to_r2(data: bytes, key: str, content_type: str) -> str:
    r2_client.put_object(Bucket=R2_BUCKET_NAME, Key=key, Body=data, ContentType=content_type)
    cdn_url = f"https://{CDN_DOMAIN}/{key}"
    logger.info("Uploaded to R2: %s (%d bytes)", cdn_url, len(data))
    return cdn_url


# ---------------------------------------------------------------------------
# Ken Burns FFmpeg builder
# ---------------------------------------------------------------------------

KEN_BURNS_EFFECTS = {
    "zoom_in":   "zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
    "zoom_out":  "zoompan=z='if(eq(on,1),1.5,max(zoom-0.0015,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
    "pan_left":  "zoompan=z='1.2':x='if(eq(on,1),0,min(x+2,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
    "pan_right": "zoompan=z='1.2':x='if(eq(on,1),iw-iw/zoom,max(x-2,0))':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
    "none":      "zoompan=z='1.0':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
}


def _build_slideshow_command(
    slides: List[Dict[str, Any]],
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    transition_duration: float = 0.5,
    audio_path: Optional[str] = None,
) -> List[str]:
    """
    Build an FFmpeg command for a Ken Burns slideshow.

    Each slide gets a zoompan filter, then they're concatenated with
    crossfade transitions.
    """
    inputs: List[str] = []
    filter_parts: List[str] = []
    n = len(slides)

    for i, slide in enumerate(slides):
        local_path = slide["local_path"]
        duration = float(slide.get("duration", 5))
        effect = slide.get("effect", "zoom_in")
        frames = int(duration * fps)

        inputs.extend(["-loop", "1", "-t", str(duration), "-framerate", str(fps), "-i", local_path])

        # Apply Ken Burns effect
        zp_template = KEN_BURNS_EFFECTS.get(effect, KEN_BURNS_EFFECTS["zoom_in"])
        zp_filter = zp_template.format(frames=frames, w=width, h=height, fps=fps)

        # Scale input to target, apply zoompan, ensure format
        filter_parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"{zp_filter},"
            f"setpts=PTS-STARTPTS,format=yuva420p[v{i}]"
        )

    # Apply crossfade transitions between consecutive slides
    if n == 1:
        filter_parts.append(f"[v0]format=yuv420p[outv]")
    else:
        # Chain crossfades: v0 xfade v1 -> tmp0, tmp0 xfade v2 -> tmp1, ...
        td = transition_duration
        prev = "v0"
        for i in range(1, n):
            offset = sum(float(slides[j].get("duration", 5)) for j in range(i)) - td * i
            offset = max(0, offset)
            out_label = "outv" if i == n - 1 else f"xf{i}"
            out_fmt = f",format=yuv420p" if i == n - 1 else ""
            filter_parts.append(
                f"[{prev}][v{i}]xfade=transition=fade:duration={td}:offset={offset}{out_fmt}[{out_label}]"
            )
            prev = out_label

    filter_complex = ";\n".join(filter_parts)

    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", filter_complex, "-map", "[outv]"]

    # Audio
    if audio_path:
        total_dur = sum(float(s.get("duration", 5)) for s in slides) - transition_duration * max(0, n - 1)
        cmd.extend(["-i", audio_path, "-map", f"{n}:a", "-c:a", "aac", "-b:a", "128k", "-t", str(total_dur)])
    else:
        # Generate silence
        total_dur = sum(float(s.get("duration", 5)) for s in slides) - transition_duration * max(0, n - 1)
        cmd.extend([
            "-f", "lavfi", "-t", str(total_dur), "-i", f"anullsrc=r=44100:cl=stereo",
            "-map", f"{n}:a", "-c:a", "aac", "-shortest",
        ])

    cmd.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        output_path,
    ])

    return cmd


# ---------------------------------------------------------------------------
# Job processing
# ---------------------------------------------------------------------------

async def _process_slideshow_job(job_id: str) -> None:
    supabase = None
    temp_dir = None
    start_ts = time.monotonic()

    try:
        supabase = get_db(admin_access=True)()

        # Read job
        job_resp = supabase.table("video_jobs").select("*").eq("id", job_id).single().execute()
        if not job_resp.data:
            logger.error("Slideshow job %s not found", job_id)
            return
        job = job_resp.data
        params = job.get("params") or {}

        slides_input = params.get("slides", [])
        width = int(params.get("width", 1080))
        height = int(params.get("height", 1920))
        fps = int(params.get("fps", 30))
        transition_duration = float(params.get("transition_duration", 0.5))
        audio_url = params.get("audio_url")
        user_id = job["user_id"]

        if not slides_input or len(slides_input) < 2:
            raise ValueError("Need at least 2 slides")

        # Download images
        temp_dir = tempfile.mkdtemp(prefix="agdoc_slideshow_")
        _update_job(supabase, job_id, 5, "downloading")

        for i, slide in enumerate(slides_input):
            url = slide["url"]
            ext = ".jpg"
            if "png" in url.lower():
                ext = ".png"
            elif "webp" in url.lower():
                ext = ".webp"
            local = os.path.join(temp_dir, f"slide_{i}{ext}")
            await _download_file(url, local)
            slide["local_path"] = local
            _update_job(supabase, job_id, 5 + int(25 * (i + 1) / len(slides_input)), "downloading")

        # Download audio if provided
        audio_path = None
        if audio_url:
            audio_path = os.path.join(temp_dir, "audio.mp3")
            await _download_file(audio_url, audio_path)

        # Build + run FFmpeg
        _update_job(supabase, job_id, 35, "rendering")
        output_path = os.path.join(temp_dir, f"slideshow-{job_id}.mp4")

        cmd = _build_slideshow_command(
            slides_input, output_path, width, height, fps, transition_duration, audio_path
        )
        logger.info("Slideshow job %s: running ffmpeg with %d slides", job_id, len(slides_input))
        logger.debug("FFmpeg cmd: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")
            logger.error("FFmpeg failed (rc=%d): %s", proc.returncode, err[-2000:])
            raise RuntimeError(f"FFmpeg failed: {err[-500:]}")

        # Upload to R2
        _update_job(supabase, job_id, 80, "uploading")
        r2_key = f"{user_id}/generated/videos/slideshow-{job_id}.mp4"
        with open(output_path, "rb") as f:
            content = f.read()
        output_url = await _upload_to_r2(content, r2_key, "video/mp4")

        # Get duration
        duration = await _get_duration(output_path)

        # Mark completed
        elapsed = time.monotonic() - start_ts
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("video_jobs").update({
            "status": "completed",
            "progress": 100,
            "output_url": output_url,
            "download_url": output_url,
            "duration_seconds": duration,
            "file_size_bytes": len(content),
            "processing_time_seconds": round(elapsed, 2),
            "completed_at": now_iso,
            "updated_at": now_iso,
        }).eq("id", job_id).execute()

        logger.info("Slideshow job %s: completed in %.1fs → %s", job_id, elapsed, output_url)

    except Exception as exc:
        logger.exception("Slideshow job %s failed: %s", job_id, exc)
        if supabase:
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                supabase.table("video_jobs").update({
                    "status": "failed",
                    "error": str(exc)[:2000],
                    "completed_at": now_iso,
                    "updated_at": now_iso,
                }).eq("id", job_id).execute()
            except Exception:
                pass
    finally:
        if temp_dir:
            try:
                for f in os.listdir(temp_dir):
                    try:
                        os.unlink(os.path.join(temp_dir, f))
                    except OSError:
                        pass
                os.rmdir(temp_dir)
            except Exception:
                pass


async def _get_duration(path: str) -> Optional[float]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return None


def _update_job(supabase, job_id: str, progress: int, stage: str):
    try:
        supabase.table("video_jobs").update({
            "progress": progress,
            "progress_stage": stage,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("Failed to update video job %s: %s", job_id, exc)


# ---------------------------------------------------------------------------
# Worker loop (same pattern as compose.py)
# ---------------------------------------------------------------------------

async def _worker_loop() -> None:
    logger.info("Video worker started")
    await asyncio.sleep(3)

    while True:
        try:
            supabase = get_db(admin_access=True)()

            # Claim oldest queued video_job
            result = (
                supabase.table("video_jobs")
                .select("id,job_type")
                .eq("status", "queued")
                .order("created_at")
                .limit(1)
                .execute()
            )

            if result.data:
                job = result.data[0]
                job_id = job["id"]
                job_type = job.get("job_type", "slideshow")

                # Claim it
                claim = (
                    supabase.table("video_jobs")
                    .update({
                        "status": "processing",
                        "progress": 0,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                    .eq("id", job_id)
                    .eq("status", "queued")
                    .execute()
                )

                if claim.data:
                    logger.info("Claimed video job %s (type=%s)", job_id, job_type)
                    if job_type == "slideshow":
                        await _process_slideshow_job(job_id)
                    else:
                        logger.warning("Unknown job type: %s", job_type)
                    continue

            await asyncio.sleep(WORKER_POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("Video worker shutting down")
            break
        except Exception as exc:
            logger.error("Video worker error: %s", exc)
            await asyncio.sleep(WORKER_POLL_INTERVAL)


def start_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())
        logger.info("Video worker task created")


def stop_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@public_router.post("/slideshow")
async def create_slideshow(
    request: Request,
    supabase=Depends(db_admin),
):
    """
    Create a Ken Burns slideshow video from multiple images.

    Request body:
    {
        "slides": [
            {"url": "https://...", "duration": 5, "effect": "zoom_in"},
            {"url": "https://...", "duration": 5, "effect": "pan_left"},
        ],
        "transition": {"type": "crossfade", "duration": 0.5},
        "audio_url": "https://..." (optional),
        "output": {"width": 1080, "height": 1920, "fps": 30},
        "user_id": "uuid" (optional, for R2 path)
    }

    Returns: {"job_id": "uuid", "status": "queued"}
    """
    _verify_api_key(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    slides = body.get("slides", [])
    if not slides or len(slides) < 2:
        raise HTTPException(status_code=400, detail="At least 2 slides required")
    if len(slides) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 slides")

    for i, s in enumerate(slides):
        if not s.get("url"):
            raise HTTPException(status_code=400, detail=f"Slide {i} missing url")

    transition = body.get("transition", {})
    output = body.get("output", {})
    user_id = body.get("user_id", "anonymous")
    audio_url = body.get("audio_url")

    job_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        row = {
            "id": job_id,
            "user_id": user_id,
            "job_type": "slideshow",
            "status": "queued",
            "progress": 0,
            "params": {
                "slides": slides,
                "width": output.get("width", 1080),
                "height": output.get("height", 1920),
                "fps": output.get("fps", 30),
                "transition_duration": transition.get("duration", 0.5),
                "audio_url": audio_url,
            },
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        result = supabase.table("video_jobs").insert(row).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create job")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("DB insert failed for slideshow job: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("Queued slideshow job %s: %d slides", job_id, len(slides))
    return {"job_id": job_id, "status": "queued"}


@public_router.get("/jobs/{job_id}")
async def get_video_job(
    job_id: str,
    request: Request,
    supabase=Depends(db_admin),
):
    """Get status of a video processing job."""
    _verify_api_key(request)

    result = supabase.table("video_jobs").select("*").eq("id", job_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")

    job = result.data[0]
    return {
        "job_id": job["id"],
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "progress_stage": job.get("progress_stage"),
        "output_url": job.get("output_url"),
        "download_url": job.get("download_url"),
        "error": job.get("error"),
        "duration_seconds": job.get("duration_seconds"),
        "file_size_bytes": job.get("file_size_bytes"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }
