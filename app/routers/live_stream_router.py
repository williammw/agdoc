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

def get_ffmpeg_input_args():
    system = platform.system().lower()
    
    if FFMPEG_INPUT_METHOD == 'auto':
        if system == 'darwin':  # macOS
            return [
                '-f', 'avfoundation',
                '-framerate', '30',
                '-video_size', '1280x720',  # Adjust as needed
                '-i', '0:0',  # '0' is usually the default camera, '1' is usually the default mic
                '-pix_fmt', 'yuv420p'
            ]
        elif system == 'linux':
            # Check if we're running in a server environment (e.g., DigitalOcean)
            if not os.path.exists('/dev/video0'):
                # Use test sources for both video and audio
                return [
                    '-f', 'lavfi', '-i', 'testsrc=size=1280x720:rate=30',
                    '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo'
                ]
            else:
                return ['-f', 'v4l2', '-i', '/dev/video0', '-f', 'alsa', '-i', 'default']
        elif system == 'windows':
            return ['-f', 'dshow', '-i', 'video=Integrated Camera:audio=Microphone Array']
    elif FFMPEG_INPUT_METHOD == 'custom':
        return ['-f', FFMPEG_VIDEO_INPUT, '-i', FFMPEG_AUDIO_INPUT]
    
    # Fallback to test pattern with audio tone
    return [
        '-f', 'lavfi', '-i', 'testsrc=size=480x270:rate=30',
        '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=44100'
    ]


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


peer_connections = {}


@router.post("/offer")
async def handle_offer(offer: dict, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    if 'sdp' not in offer or 'type' not in offer:
        raise HTTPException(status_code=400, detail="Invalid offer format")

    # Create a new RTCPeerConnection
    pc = RTCPeerConnection()
    #thing changes
    # Store the peer connection in the dictionary
    peer_connections[current_user['id']] = pc

    # Set the remote description with the offer 
    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer['sdp'], type=offer['type']))

    # Create an answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return JSONResponse(content={"answer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}})


@router.post("/ice-candidate")
async def handle_ice_candidate(candidate: dict, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    if 'candidate' not in candidate:
        raise HTTPException(status_code=400, detail="Invalid candidate format")

    pc = peer_connections.get(current_user['id'])
    if not pc:
        raise HTTPException(
            status_code=404, detail="Peer connection not found")

    # Add the ICE candidate to the peer connection
    try:
        await pc.addIceCandidate(RTCIceCandidate(candidate=candidate['candidate']))
    except Exception as e:
        logger.error(f"Failed to add ICE candidate: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to add ICE candidate")

    return JSONResponse(content={"status": "ok"})



@router.post("/start-stream/{stream_id}")
async def start_stream(
    stream_id: str,
    database: Database = Depends(get_database),
    authorization: str = Header(...)
):
    logger.info(f"Received request to start stream: {stream_id}")

    try:
        token = authorization.split(" ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
        logger.info(f"Authenticated user: {user_id}")
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    query = "SELECT rtmps_url, stream_key FROM livestreams WHERE id = :stream_id AND user_id = :user_id"
    values = {"stream_id": stream_id, "user_id": user_id}
    logger.info(f"Executing query: {query} with values: {values}")
    result = await database.fetch_one(query=query, values=values)

    if not result:
        logger.error(
            f"Stream not found for ID: {stream_id} and user ID: {user_id}")
        raise HTTPException(status_code=404, detail="Stream not found")

    rtmps_url = result['rtmps_url']
    stream_key = result['stream_key']
    logger.info(
        f"Retrieved stream info: RTMPS URL: {rtmps_url}, Stream Key: {stream_key}")

    full_rtmps_url = f"{rtmps_url}{stream_key}"
    logger.info(f"Full RTMPS URL: {full_rtmps_url}")

    ffmpeg_input_args = get_ffmpeg_input_args()
    
    ffmpeg_command = [
        'ffmpeg',
        '-itsoffset', '0.5',  # Adjust this value as needed (in seconds)
        *ffmpeg_input_args,
        '-use_wallclock_as_timestamps', '1',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-tune', 'zerolatency',
        '-b:v', '2000k',
        '-maxrate', '2500k',
        '-bufsize', '2500k',
        '-vf', 'scale=480:270,fps=30',
        '-pix_fmt', 'yuv420p',
        '-g', '60',
        '-keyint_min', '60',
        '-sc_threshold', '0',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-vsync', '1',
        '-async', '1',
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
        logger.info(f"FFmpeg process started with PID: {process.pid}")
    except Exception as ffmpeg_error:
        logger.error(f"Failed to start FFmpeg process: {str(ffmpeg_error)}")
        raise HTTPException(
            status_code=500, detail="Failed to start FFmpeg process")

    try:
        update_query = """
        UPDATE livestreams
        SET process_id = :process_id, status = 'live'
        WHERE id = :stream_id AND user_id = :user_id
        """
        update_values = {"process_id": process.pid,
                         "stream_id": stream_id, "user_id": user_id}
        logger.info(
            f"Updating database with query: {update_query} and values: {update_values}")
        await database.execute(query=update_query, values=update_values)
    except Exception as db_error:
        logger.error(f"Failed to update database: {str(db_error)}")
        raise HTTPException(
            status_code=500, detail="Failed to update stream status in database")

    asyncio.create_task(log_ffmpeg_output(process))

    return {"message": "Stream started with optimized 720p settings", "process_id": process.pid}


async def log_ffmpeg_output(process):
    log_file = f"ffmpeg_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(log_file, 'w') as f:
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            log_line = f"FFmpeg: {line.decode().strip()}"
            logger.info(log_line)
            f.write(log_line + '\n')

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
        query = "SELECT process_id FROM livestreams WHERE id = :stream_id AND user_id = :user_id"
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
            WHERE id = :stream_id AND user_id = :user_id
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
