# live_stream_router.py
from fastapi import HTTPException
from fastapi import APIRouter, HTTPException, Depends, Header
import psutil
import shutil
from app.dependencies import get_current_user, get_database, verify_token
from databases import Database
from pydantic import BaseModel
import httpx
import os
import asyncio
import subprocess
import logging
import shutil
import urllib.request
import tarfile
router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')


class StreamCreate(BaseModel):
    name: str


@router.post("/create-stream")
async def create_stream(stream: StreamCreate, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/stream/live_inputs",
                headers={
                    "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"meta": {"name": stream.name}}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Cloudflare API error: {e.response.text}")

    stream_data = response.json()['result']
    print(stream_data)
    return {
        "stream_key": stream_data['uid'],
        "rtmps_url": stream_data['rtmps']['url'],
        "stream_id": stream_data['uid']
    }


@router.get("/stream/{stream_id}")
async def get_stream(stream_id: str, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/stream/live_inputs/{stream_id}",
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Stream not found")
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Cloudflare API error: {e.response.text}")

    return response.json()['result']


@router.post("/start-stream/{stream_id}")
async def start_stream(
    stream_id: str,
    database: Database = Depends(get_database),
    authorization: str = Header(...)
):
    print(f"Current working directory: {os.getcwd()}")
    print(f"PATH: {os.environ.get('PATH')}")

    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        print("FFmpeg not found. Installing...")
        ffmpeg_path = await install_ffmpeg()

    print(f"FFmpeg path: {ffmpeg_path}")

    try:
        # Simple command to test FFmpeg
        result = subprocess.run(
            [ffmpeg_path, '-version'], capture_output=True, text=True)
        print(f"FFmpeg version: {result.stdout}")
    except Exception as e:
        print(f"Error running FFmpeg: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to run FFmpeg: {str(e)}")

    # For now, let's just return success if FFmpeg runs without error
    return {"message": "FFmpeg test successful"}


async def install_ffmpeg():
    ffmpeg_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    ffmpeg_tar = "ffmpeg-release-amd64-static.tar.xz"

    # Download FFmpeg
    urllib.request.urlretrieve(ffmpeg_url, ffmpeg_tar)

    # Extract FFmpeg
    with tarfile.open(ffmpeg_tar, "r:xz") as tar:
        tar.extractall()

    # Find the extracted directory
    ffmpeg_dir = next(d for d in os.listdir() if d.startswith(
        "ffmpeg-") and d.endswith("-amd64-static"))

    # Move FFmpeg to a permanent location
    os.makedirs(os.path.expanduser("~/bin"), exist_ok=True)
    shutil.move(os.path.join(ffmpeg_dir, "ffmpeg"),
                os.path.expanduser("~/bin/ffmpeg"))

    # Clean up
    os.remove(ffmpeg_tar)
    shutil.rmtree(ffmpeg_dir)

    # Update PATH
    os.environ["PATH"] = f"{os.path.expanduser('~/bin')}:{os.environ['PATH']}"

    return os.path.expanduser("~/bin/ffmpeg")

async def log_ffmpeg_output(process):
    while True:
        line = await process.stderr.readline()
        if not line:
            break
        logger.info(f"FFmpeg: {line.decode().strip()}")

    await process.wait()
    logger.info(f"FFmpeg process ended with return code: {process.returncode}")


@router.post("/stop-stream/{stream_id}")
async def stop_stream(
    stream_id: str,
    database: Database = Depends(get_database),
    authorization: str = Header(...)
):
    try:
        token = authorization.split(" ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    try:
        # Fetch the process ID from the database
        query = "SELECT process_id FROM livestreams WHERE cloudflare_id = :stream_id AND user_id = :user_id"
        values = {"stream_id": stream_id, "user_id": user_id}
        result = await database.fetch_one(query=query, values=values)

        if not result or not result['process_id']:
            raise HTTPException(
                status_code=404, detail="Stream process not found")

        process_id = result['process_id']

        try:
            process = psutil.Process(process_id)
            process.terminate()

            # Update the database to clear the process_id and set status to 'stopped'
            update_query = """
            UPDATE livestreams
            SET process_id = NULL, status = 'stopped'
            WHERE cloudflare_id = :stream_id AND user_id = :user_id
            """
            await database.execute(query=update_query, values=values)

            return {"message": "Stream stopped"}
        except psutil.NoSuchProcess:
            # If the process is not found, just update the database
            update_query = """
            UPDATE livestreams
            SET process_id = NULL, status = 'stopped'
            WHERE cloudflare_id = :stream_id AND user_id = :user_id
            """
            await database.execute(query=update_query, values=values)
            return {"message": "Stream process not found, database updated"}
    except Exception as e:
        logger.error(f"Failed to stop stream: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to stop stream: {str(e)}")
