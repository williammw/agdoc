from datetime import datetime
import subprocess
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Header, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import boto3
import os
import logging
from app.dependencies import get_current_user, get_database
from app.firebase_admin_config import verify_token
from databases import Database
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
import json
router = APIRouter()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3_client = boto3.client('s3',
                        endpoint_url=os.getenv('R2_ENDPOINT_URL'),
                        aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                        aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
                        region_name='weur')
bucket_name = 'umami'

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "/usr/bin/ffmpeg")

class ConvertRequest(BaseModel):
    file_key: str
    unique_id: str

def convert_video_task(input_path: str, output_path: str):
    command = [
        FFMPEG_PATH,
        "-i", input_path,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-strict", "experimental",
        output_path
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info(f"FFmpeg stdout: {result.stdout}")
        logger.info(f"FFmpeg stderr: {result.stderr}")
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion failed: {str(e)}")
        logger.error(f"FFmpeg stderr: {e.stderr}")
        raise Exception(f"Video conversion failed: {str(e)}")

def generate_presigned_url(file_key: str, expires_in: int = 3600) -> str:
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': file_key},
            ExpiresIn=expires_in
        )
        return presigned_url
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error generating URL")

@router.get("/convert-url/")
async def convert_url(file_key: str, expires_in: int = 3600):
    try:
        presigned_url = generate_presigned_url(file_key, expires_in)
        parts = file_key.split('/')
        filename = parts[-1]
        folder = '/'.join(parts[:-1])
        name, extension = os.path.splitext(filename)
        mp4_filename = f"{name}.mp4"
        mp4_file_key = f"{folder}/{mp4_filename}"
        return {
            "presigned_url": presigned_url,
            "original_file_key": file_key,
            "mp4_file_key": mp4_file_key
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# async def process_video(db: Database, task_id: str, original_file_key: str, mp4_file_key: str, thumbnail_file_key: str):
#     logger.info(f"Starting process_video for task {task_id}")
#     try:
#         # Download the original file
#         input_path = f"/tmp/{os.path.basename(original_file_key)}"
#         logger.info(f"Downloading original file: {original_file_key} to {input_path}")
#         await asyncio.to_thread(s3_client.download_file, bucket_name, original_file_key, input_path)
#         logger.info("Original file downloaded successfully")

#         # Convert to MP4
#         output_path = f"/tmp/{os.path.basename(mp4_file_key)}"
#         logger.info(f"Converting video to MP4: {input_path} -> {output_path}")
#         await asyncio.to_thread(convert_video_task, input_path, output_path)
#         logger.info("Video conversion completed")

#         # Generate thumbnail
#         thumbnail_path = f"/tmp/{os.path.basename(thumbnail_file_key)}"
#         logger.info(f"Generating thumbnail: {output_path} -> {thumbnail_path}")
#         thumbnail_command = [
#             FFMPEG_PATH,
#             "-i", output_path,
#             "-ss", "00:00:01",
#             "-vframes", "1",
#             "-vf", "scale=320:-1",
#             thumbnail_path
#         ]
#         await asyncio.create_subprocess_exec(*thumbnail_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
#         logger.info("Thumbnail generated successfully")

#         # Upload MP4 and thumbnail to R2
#         logger.info(f"Uploading MP4 file to R2: {mp4_file_key}")
#         await asyncio.to_thread(s3_client.upload_file, output_path, bucket_name, mp4_file_key,
#                                 ExtraArgs={"ContentType": "video/mp4", "ACL": "public-read"})
#         logger.info(f"Uploading thumbnail to R2: {thumbnail_file_key}")
#         await asyncio.to_thread(s3_client.upload_file, thumbnail_path, bucket_name, thumbnail_file_key,
#                                 ExtraArgs={"ContentType": "image/jpeg", "ACL": "public-read"})

#         # Update task status to completed
#         logger.info(f"Updating task status to completed: {task_id}")
#         query = """
#         UPDATE process_tasks 
#         SET status = :status, progress = :progress, result_url = :result_url 
#         WHERE id = :task_id
#         """
#         values = {
#             "status": "completed",
#             "progress": 100,
#             "result_url": f"https://{os.getenv('R2_DEV_URL')}/{mp4_file_key}",
#             "task_id": task_id
#         }
#         await db.execute(query, values)

#         # Clean up temporary files
#         logger.info("Cleaning up temporary files")
#         os.remove(input_path)
#         os.remove(output_path)
#         os.remove(thumbnail_path)

#         logger.info(f"Video processing completed for task {task_id}")
#     except Exception as e:
#         logger.error(f"Video processing failed for task {task_id}: {str(e)}")
#         # Update task status to failed
#         query = """
#         UPDATE process_tasks 
#         SET status = :status, error_message = :error_message 
#         WHERE id = :task_id
#         """
#         values = {
#             "status": "failed",
#             "error_message": str(e),
#             "task_id": task_id
#         }
#         await db.execute(query, values)

# @router.post("/upload-and-convert")``
async def upload_and_convert_video(
    db: Database,
    task_id: str,
    original_file_key: str,
    mp4_file_key: str,
    thumbnail_file_key: str
):
    logger.info(f"Starting upload_and_convert_video for task {task_id}")
    try:
        # Download the original file
        input_path = f"/tmp/{os.path.basename(original_file_key)}"
        logger.info(f"Downloading original file: {original_file_key} to {input_path}")
        await asyncio.to_thread(s3_client.download_file, bucket_name, original_file_key, input_path)
        logger.info("Original file downloaded successfully")

        # Convert to MP4
        output_path = f"/tmp/{os.path.basename(mp4_file_key)}"
        logger.info(f"Converting video to MP4: {input_path} -> {output_path}")
        
        # Use ffprobe to get video information
        probe_command = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input_path
        ]
        probe_result = await asyncio.create_subprocess_exec(*probe_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await probe_result.communicate()
        video_info = json.loads(stdout)

        # Determine video codec
        video_codec = next((stream['codec_name'] for stream in video_info['streams'] if stream['codec_type'] == 'video'), None)

        # Prepare FFmpeg command based on input format
        ffmpeg_command = [
            FFMPEG_PATH,
            "-i", input_path,
            "-c:v", "libx264",  # Always use H.264 for video
            "-preset", "medium",  # Balanced preset for speed/quality
            "-crf", "23",  # Constant Rate Factor for quality (lower is better, 23 is default)
            "-c:a", "aac",  # Use AAC for audio
            "-b:a", "128k",  # Audio bitrate
            "-movflags", "+faststart",  # Optimize for web playback
            "-y",  # Overwrite output file if it exists
            output_path
        ]

        # If input is already H.264, we can use copy mode for faster processing
        if video_codec == 'h264':
            ffmpeg_command[3:5] = ["-c:v", "copy"]

        # Run the FFmpeg command
        convert_process = await asyncio.create_subprocess_exec(*ffmpeg_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await convert_process.communicate()
        
        if convert_process.returncode != 0:
            raise Exception(f"FFmpeg conversion failed: {stderr.decode()}")

        logger.info("Video conversion completed")

        # Generate thumbnail
        thumbnail_path = f"/tmp/{os.path.basename(thumbnail_file_key)}"
        logger.info(f"Generating thumbnail: {output_path} -> {thumbnail_path}")
        thumbnail_command = [
            FFMPEG_PATH,
            "-i", output_path,
            "-ss", "00:00:01",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            thumbnail_path
        ]
        thumbnail_process = await asyncio.create_subprocess_exec(*thumbnail_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await thumbnail_process.communicate()
        logger.info("Thumbnail generated successfully")

        # Upload MP4 and thumbnail to R2
        logger.info(f"Uploading MP4 file to R2: {mp4_file_key}")
        await asyncio.to_thread(s3_client.upload_file, output_path, bucket_name, mp4_file_key,
                                ExtraArgs={"ContentType": "video/mp4", "ACL": "public-read"})
        logger.info(f"Uploading thumbnail to R2: {thumbnail_file_key}")
        await asyncio.to_thread(s3_client.upload_file, thumbnail_path, bucket_name, thumbnail_file_key,
                                ExtraArgs={"ContentType": "image/jpeg", "ACL": "public-read"})

        # Update task status to completed
        logger.info(f"Updating task status to completed: {task_id}")
        task_update_query = """
        UPDATE process_tasks 
        SET status = :status, progress = :progress, result_url = :result_url 
        WHERE id = :task_id
        """
        task_update_values = {
            "status": "completed",
            "progress": 100,
            "result_url": f"https://{os.getenv('R2_DEV_URL')}/{mp4_file_key}",
            "task_id": task_id
        }
        logger.info(f"Executing SQL: {task_update_query}")
        logger.info(f"With values: {task_update_values}")
        await db.execute(task_update_query, task_update_values)

        # Update post_media table
        logger.info(f"Updating post_media for task {task_id}")
        media_update_query = """
        UPDATE post_media 
        SET media_url = :media_url, 
            cloudflare_info = :cloudflare_info,
            status = 'completed'
        WHERE task_id = :task_id
        """
        cloudflare_info = {
            "mp4_url": f"https://{os.getenv('R2_DEV_URL')}/{mp4_file_key}",
            "thumbnail_url": f"https://{os.getenv('R2_DEV_URL')}/{thumbnail_file_key}",
            "original_url": f"https://{os.getenv('R2_DEV_URL')}/{original_file_key}"
        }
        media_update_values = {
            "media_url": f"https://{os.getenv('R2_DEV_URL')}/{mp4_file_key}",
            "cloudflare_info": json.dumps(cloudflare_info),
            "task_id": task_id
        }
        logger.info(f"Executing SQL: {media_update_query}")
        logger.info(f"With values: {media_update_values}")
        result = await db.execute(media_update_query, media_update_values)
        logger.info(f"post_media update result: {result}")

        logger.info(f"Video processing and database updates completed for task {task_id}")
    except Exception as e:
        logger.error(f"Video processing failed for task {task_id}: {str(e)}")
        # Update task status to failed
        error_query = """
        UPDATE process_tasks 
        SET status = :status, error_message = :error_message 
        WHERE id = :task_id
        """
        error_values = {
            "status": "failed",
            "error_message": str(e),
            "task_id": task_id
        }
        logger.info(f"Executing error SQL: {error_query}")
        logger.info(f"With error values: {error_values}")
        await db.execute(error_query, error_values)

        # Also update post_media status to failed
        media_error_query = """
        UPDATE post_media 
        SET status = 'failed'
        WHERE task_id = :task_id
        """
        logger.info(f"Executing media error SQL: {media_error_query}")
        logger.info(f"With media error values: {{'task_id': {task_id}}}")
        await db.execute(media_error_query, {"task_id": task_id})
    finally:
        # Clean up temporary files
        for file_path in [input_path, output_path, thumbnail_path]:
            if os.path.exists(file_path):
                os.remove(file_path)

@router.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    query = "SELECT * FROM process_tasks WHERE id = :task_id"
    task = await db.fetch_one(query, {"task_id": task_id})

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task['id'],
        "status": task['status'],
        "progress": task['progress'],
        "result_url": task['result_url'],
        "error_message": task['error_message']
    }

@router.delete("/delete/{bucket_name}/{prefix}")
async def delete_files_with_prefix(bucket_name: str, prefix: str):
    try:
        objects_to_delete = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

        if 'Contents' not in objects_to_delete:
            return {"message": "No objects found with the given prefix"}

        delete_keys = [{'Key': obj['Key']} for obj in objects_to_delete['Contents']]
        delete_response = s3_client.delete_objects(
            Bucket=bucket_name,
            Delete={'Objects': delete_keys}
        )

        return {"message": "Objects deleted successfully", "deleted_objects": delete_response['Deleted']}

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Error deleting objects: {e}")

@router.delete("/remove-assets/{bucket}/{folder:path}")
async def remove_assets(bucket: str, folder: str):
    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=folder)

        if 'Contents' not in response:
            return {"message": "No objects found in the specified folder"}

        objects_to_delete = [{'Key': obj['Key']} for obj in response['Contents']]
        s3_client.delete_objects(Bucket=bucket, Delete={'Objects': objects_to_delete})

        return {
            "message": f"Successfully deleted {len(objects_to_delete)} objects from folder '{folder}' in bucket '{bucket}'"
        }

    except Exception as e:
        logger.error(f"Error deleting assets: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete assets: {str(e)}")
    

async def long_running_task(task_id: str):
    logger.info(f"Starting long-running task {task_id}")
    for i in range(5):
        logger.info(f"Task {task_id}: Step {i+1}")
        await asyncio.sleep(2)  # Simulate work being done
    logger.info(f"Completed long-running task {task_id}")


@router.post("/test-background-task")
async def test_background_task(background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    logger.info(f"Creating background task: {task_id}")
    background_tasks.add_task(long_running_task, task_id)
    return {"message": f"Background task {task_id} started"}


@router.get("/current-time")
async def get_current_time():
    return {"current_time": time.time()}
