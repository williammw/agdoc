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
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceServer, RTCConfiguration, RTCIceCandidate, MediaStreamTrack
import uuid
from datetime import datetime
import platform
import av

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


peer_connections = {}


@router.post("/offer")
async def handle_offer(offer: dict, current_user: dict = Depends(get_current_user), database: Database = Depends(get_database)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    if 'sdp' not in offer or 'type' not in offer:
        raise HTTPException(status_code=400, detail="Invalid offer format")

    # Create a new RTCPeerConnection with the correct ice server format
    config = RTCConfiguration(
        iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
    )
    pc = RTCPeerConnection(configuration=config)

    # Store the peer connection in the dictionary
    peer_connections[current_user['uid']] = pc

    @pc.on("track")
    async def on_track(track):
        logger.info(f"Received track: {track.kind}")
        if track.kind == "video":
            # Start streaming to Cloudflare here
            logger.info("Starting stream to Cloudflare")
            asyncio.create_task(stream_to_cloudflare(
                current_user['uid'], track, database))
        elif track.kind == "audio":
            # For now, we're not handling audio. You can add audio support later if needed.
            logger.info("Received audio track, but not processing it yet.")

    # Set the remote description with the offer
    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer['sdp'], type=offer['type']))

    # Create an answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return JSONResponse(content={"answer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}})


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




async def stream_to_cloudflare(user_id: str, track: MediaStreamTrack, database: Database):
    logger.info(f"Streaming to Cloudflare for user {user_id}")
    query = "SELECT rtmps_url, stream_key FROM livestreams WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 1"
    result = await database.fetch_one(query=query, values={"user_id": user_id})

    if not result:
        logger.error(f"No stream found for user {user_id}")
        return

    rtmps_url = result['rtmps_url']
    stream_key = result['stream_key']
    full_rtmps_url = f"{rtmps_url}{stream_key}"
    logger.info(f"Streaming to URL: {full_rtmps_url}")

    command = [
        'ffmpeg',
        '-f', 'rawvideo',
        '-pix_fmt', 'yuv420p',
        '-s', '640x480',  # Adjust this to match your video resolution
        '-r', '30',  # Adjust this to match your frame rate
        '-i', 'pipe:0',
        '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-b:v', '2500k',
        '-maxrate', '2500k',
        '-bufsize', '5000k',
        '-pix_fmt', 'yuv420p',
        '-g', '60',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-f', 'flv',
        full_rtmps_url
    ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    try:
        frame_count = 0
        while True:
            try:
                frame = await track.recv()
                frame_count += 1
                if frame_count % 100 == 0:
                    logger.info(f"Processed {frame_count} frames for user {user_id}")

                if process.stdin.is_closing():
                    logger.info("FFmpeg process stdin is closing")
                    break

                # Convert the frame to the correct format
                if isinstance(frame, av.VideoFrame):
                    img = frame.to_ndarray(format="yuv420p")
                    logger.debug(f"Frame shape: {img.shape}, dtype: {img.dtype}")
                    process.stdin.write(img.tobytes())
                    logger.debug(f"Wrote frame {frame_count} to FFmpeg")
                elif isinstance(frame, av.AudioFrame):
                    # If you want to add audio support later, you can handle it here
                    pass

                await process.stdin.drain()

            except asyncio.CancelledError:
                logger.info(f"Streaming cancelled for user {user_id}")
                break
            except Exception as e:
                logger.error(f"Error processing frame: {str(e)}")
                break
    except BrokenPipeError:
        logger.error(f"Broken pipe error for user {user_id}. FFmpeg process may have terminated.")
    except Exception as e:
        logger.error(f"Error in stream_to_cloudflare: {str(e)}")
    finally:
        if process.stdin:
            process.stdin.close()
        await process.wait()
        stdout, stderr = await process.communicate()
        logger.info(f"FFmpeg process finished. Exit code: {process.returncode}")
        logger.info(f"FFmpeg stdout: {stdout.decode()}")
        logger.error(f"FFmpeg stderr: {stderr.decode()}")

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
    try:
        token = authorization.split(" ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    # Update the stream status to 'live'
    update_query = """
    UPDATE livestreams
    SET status = 'live'
    WHERE id = :stream_id AND user_id = :user_id
    """
    update_values = {"stream_id": stream_id, "user_id": user_id}
    await database.execute(query=update_query, values=update_values)

    return {"message": "Stream marked as live"}


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

    # Update the database to set status to 'stopped'
    update_query = """
    UPDATE livestreams
    SET status = 'stopped'
    WHERE id = :stream_id AND user_id = :user_id
    """
    values = {"stream_id": stream_id, "user_id": user_id}
    await database.execute(query=update_query, values=values)

    # Close the peer connection if it exists
    pc = peer_connections.get(user_id)
    if pc:
        await pc.close()
        del peer_connections[user_id]

    return {"message": "Stream stopped"}


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


async def check_cloudflare_stream_status(stream_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/stream/live_inputs/{stream_id}",
            headers={
                "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        return response.json()['result']


@router.get("/check-stream-status/{stream_id}")
async def get_stream_status(stream_id: str, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    status = await check_cloudflare_stream_status(stream_id)
    return {"status": status}
