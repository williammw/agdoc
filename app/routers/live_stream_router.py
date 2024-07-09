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
    
    # Add these diagnostic prints
    print(f"Current working directory: {os.getcwd()}")
    print(f"PATH: {os.environ.get('PATH')}")
    print(f"FFmpeg location: {shutil.which('ffmpeg')}")
    ffmpeg_path = "/layers/digitalocean_apt/apt/usr/bin/ffmpeg"
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


    try:
        token = authorization.split(" ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    try:
        query = "SELECT rtmps_url, stream_key FROM livestreams WHERE cloudflare_id = :stream_id AND user_id = :user_id"
        values = {"stream_id": stream_id, "user_id": user_id}
        result = await database.fetch_one(query=query, values=values)

        if not result:
            logger.error(
                f"Stream not found for ID: {stream_id} and user ID: {user_id}")
            raise HTTPException(status_code=404, detail="Stream not found")

        rtmps_url = result['rtmps_url']
        stream_key = result['stream_key']

        full_rtmps_url = f"{rtmps_url}{stream_key}"

        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path:
            ffmpeg_path = "/layers/digitalocean_apt/apt/usr/bin/ffmpeg"

        print(f"FFmpeg path: {ffmpeg_path}")

        return {"message": "FFmpeg test successful"}


        ffmpeg_command = [
            ffmpeg_path,
            '-f', 'lavfi',
            '-i', 'anullsrc',
            '-f', 'lavfi',
            '-i', 'testsrc=size=640x360:rate=30',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-tune', 'zerolatency',
            '-b:v', '3500k',
            '-maxrate', '3500k',
            '-bufsize', '7000k',
            '-pix_fmt', 'yuv420p',
            '-crf', '18',
            '-g', '60',
            '-keyint_min', '60',
            '-sc_threshold', '0',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-ar', '44100',
            '-f', 'flv',
            full_rtmps_url
        ]

        logger.info(f"Executing FFmpeg command: {' '.join(ffmpeg_command)}")

        try:
          process = await asyncio.create_subprocess_exec(
              *ffmpeg_command,
              stdout=asyncio.subprocess.PIPE,
              stderr=asyncio.subprocess.PIPE
          )
        except Exception as e:
          print(f"Error creating subprocess: {str(e)}")
          raise HTTPException(status_code=500, detail=f"Failed to start FFmpeg process: {str(e)}")

        logger.info(f"FFmpeg process started with PID: {process.pid}")

        try:
            update_query = """
            UPDATE livestreams
            SET process_id = :process_id, status = 'live'
            WHERE cloudflare_id = :stream_id AND user_id = :user_id
            """
            update_values = {"process_id": process.pid,
                             "stream_id": stream_id, "user_id": user_id}
            await database.execute(query=update_query, values=update_values)
        except Exception as db_error:
            logger.warning(
                f"Failed to update process_id in database: {str(db_error)}")

        asyncio.create_task(log_ffmpeg_output(process))

        return {"message": "Stream started with optimized 720p settings", "process_id": process.pid}
    except Exception as e:
        logger.error(f"Failed to start stream: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to start stream: {str(e)}")


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
