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
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
import av
import uuid
from datetime import datetime
import platform

router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')

# Constants for FFmpeg
FFMPEG_INPUT_METHOD = os.getenv('FFMPEG_INPUT_METHOD', 'auto')
FFMPEG_VIDEO_INPUT = os.getenv('FFMPEG_VIDEO_INPUT', 'default')
FFMPEG_AUDIO_INPUT = os.getenv('FFMPEG_AUDIO_INPUT', 'default')


class StreamCreate(BaseModel):
    name: str


class WebRTCOffer(BaseModel):
    streamId: str
    offer: dict


def get_ffmpeg_input_args():
    system = platform.system().lower()

    if FFMPEG_INPUT_METHOD == 'auto':
        if system == 'darwin':  # macOS
            return ['-f', 'avfoundation', '-i', '0:0']
        elif system == 'linux':
            return ['-f', 'v4l2', '-i', '/dev/video0', '-f', 'alsa', '-i', 'default']
        elif system == 'windows':
            return ['-f', 'dshow', '-i', 'video=Integrated Camera:audio=Microphone Array']
    elif FFMPEG_INPUT_METHOD == 'custom':
        return ['-f', FFMPEG_VIDEO_INPUT, '-i', FFMPEG_AUDIO_INPUT]

    # Fallback to test pattern with audio tone
    return ['-f', 'lavfi', '-i', 'testsrc=size=1280x720:rate=30', '-f', 'lavfi', '-i', 'anullsrc']


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

    query = """
    INSERT INTO livestreams (
        id, user_id, stream_key, rtmps_url, cloudflare_id, status, created_at, webrtc_url
    ) VALUES (
        :id, :user_id, :stream_key, :rtmps_url, :cloudflare_id, :status, :created_at, :webrtc_url
    )
    """

    values = {
        "id": str(uuid.uuid4()),
        "user_id": current_user['uid'],
        "stream_key": stream_data['rtmps']['streamKey'],
        "rtmps_url": stream_data['rtmps']['url'],
        "cloudflare_id": stream_data['uid'],
        "status": 'created',
        "created_at": datetime.now(),
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


@router.post("/webrtc-offer")
async def handle_webrtc_offer(offer: WebRTCOffer, current_user: dict = Depends(get_current_user), database: Database = Depends(get_database)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    pc = RTCPeerConnection()
    relay = MediaRelay()

    @pc.on("track")
    def on_track(track):
        if track.kind == "video":
            pc.addTrack(relay.subscribe(track))
        elif track.kind == "audio":
            pc.addTrack(relay.subscribe(track))

    # Set the remote description
    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer.offer["sdp"], type=offer.offer["type"]))

    # Create an answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # Start the RTMP stream to Cloudflare
    asyncio.create_task(start_rtmp_stream(pc, offer.streamId, database))

    return {"answer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}}


async def start_rtmp_stream(pc: RTCPeerConnection, stream_id: str, database: Database):
    query = "SELECT rtmps_url, stream_key FROM livestreams WHERE id = :stream_id"
    values = {"stream_id": stream_id}
    result = await database.fetch_one(query=query, values=values)

    if not result:
        logger.error(f"Stream not found for ID: {stream_id}")
        return

    rtmp_url = f"{result['rtmps_url']}{result['stream_key']}"

    ffmpeg_command = [
        'ffmpeg',
        '-i', 'pipe:0',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-tune', 'zerolatency',
        '-b:v', '6000k',
        '-maxrate', '6000k',
        '-bufsize', '12000k',
        '-g', '60',  # GOP size of 2 seconds at 30 fps
        '-keyint_min', '60',
        '-sc_threshold', '0',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-f', 'flv',
        rtmp_url
    ]

    process = await asyncio.create_subprocess_exec(
        *ffmpeg_command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    try:
        while True:
            frame = await pc.recv()
            if isinstance(frame, av.VideoFrame):
                packet = frame.to_ndarray().tobytes()
                if process.stdin:
                    process.stdin.write(packet)
                    await process.stdin.drain()
    except Exception as e:
        logger.error(f"Error in RTMP stream: {str(e)}")
    finally:
        if process.stdin:
            process.stdin.close()
        await process.wait()


@router.post("/stop-stream/{stream_id}")
async def stop_stream(
    stream_id: str,
    database: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    query = "SELECT process_id FROM livestreams WHERE id = :stream_id AND user_id = :user_id"
    values = {"stream_id": stream_id, "user_id": current_user['uid']}
    result = await database.fetch_one(query=query, values=values)

    if not result:
        raise HTTPException(status_code=404, detail="Stream not found")

    process_id = result['process_id']

    if process_id:
        try:
            process = await asyncio.create_subprocess_shell(f"kill {process_id}")
            await process.wait()
        except Exception as e:
            logger.error(f"Failed to stop FFmpeg process: {str(e)}")

    update_query = """
    UPDATE livestreams
    SET process_id = NULL, status = 'stopped'
    WHERE id = :stream_id AND user_id = :user_id
    """
    await database.execute(query=update_query, values=values)

    return {"message": "Stream stopped successfully"}

# Additional endpoints (e.g., for managing streams, getting stream status) can be added here
