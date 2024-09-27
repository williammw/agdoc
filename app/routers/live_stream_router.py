# live_stream_router.py
from fastapi import HTTPException, APIRouter, Depends, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import JSONResponse
from app.dependencies import get_current_user, get_database, verify_token
from databases import Database
from pydantic import BaseModel
import httpx
import os
import asyncio
import logging
import subprocess
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
import psutil
import uuid  # Add this import statement
from datetime import datetime
import platform


router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')

# Add these constants at the top of your file
FFMPEG_INPUT_METHOD = os.getenv('FFMPEG_INPUT_METHOD', 'auto')
FFMPEG_VIDEO_INPUT = os.getenv('FFMPEG_VIDEO_INPUT', 'default')
FFMPEG_AUDIO_INPUT = os.getenv('FFMPEG_AUDIO_INPUT', 'default')

class StreamCreate(BaseModel):
    name: str


@router.post("/create-stream")
async def create_stream(stream: StreamCreate, current_user: dict = Depends(get_current_user), database: Database = Depends(get_database)):
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
                json={
                    "meta": {"name": stream.name},
                    "recording": {"mode": "automatic"},
                    "playback": {"mode": "live"}
                }
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Cloudflare API error: {e.response.text}")

    stream_data = response.json()['result']

    # Insert stream data into the livestreams table
    query = """
    INSERT INTO livestreams (
        id, user_id, stream_key, rtmps_url, cloudflare_id, status, created_at, webrtc_url
    ) VALUES (
        :id, :user_id, :stream_key, :rtmps_url, :cloudflare_id, :status, :created_at, :webrtc_url
    )
    """

    logger.info(f"Inserting stream data into database: {stream_data}")
    values = {
        "id": uuid.uuid4(),
        "user_id": current_user['uid'],
        "stream_key": stream_data['rtmps']['streamKey'],
        "rtmps_url": stream_data['rtmps']['url'],
        "cloudflare_id": stream_data['uid'],
        "status": 'created',
        "created_at": datetime.now(),
        # This might be None if not provided
        "webrtc_url": stream_data.get('webRTC', {}).get('url')
    }

    try:
        await database.execute(query=query, values=values)
    except Exception as e:
        logger.error(f"Failed to insert stream data into database: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to create stream in database")

    return {
        "stream_id": values["id"],
        "cloudflare_id": stream_data['uid'],
        "stream_key": stream_data['rtmps']['streamKey'],
        "rtmps_url": stream_data['rtmps']['url'],
        "webrtc_url": values["webrtc_url"]
    }


@router.post("/start-stream/{stream_id}")
async def start_stream(
    stream_id: str,
    database: Database = Depends(get_database),
    authorization: str = Header(...)
):
    try:
        token = authorization.split(" ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    # Update the stream status to 'live'
    update_query = """
    UPDATE livestreams
    SET status = 'live'
    WHERE id = :stream_id AND user_id = :user_id
    """
    update_values = {"stream_id": stream_id, "user_id": user_id}
    await database.execute(query=update_query, values=update_values)

    return {"message": "Stream marked as live"}

@router.get("/stream-info/{stream_id}")
async def get_stream_info(
    stream_id: str,
    database: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    query = "SELECT rtmps_url, stream_key FROM livestreams WHERE id = :stream_id AND user_id = :user_id"
    values = {"stream_id": stream_id, "user_id": current_user['uid']}
    result = await database.fetch_one(query=query, values=values)

    if not result:
        raise HTTPException(status_code=404, detail="Stream not found")

    return {
        "rtmps_url": result['rtmps_url'],
        "stream_key": result['stream_key']
    }
