from datetime import datetime
import subprocess
import uuid
from celery import Celery
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, HTTPException, Header, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.responses import JSONResponse
import boto3
import os
import logging
from app.dependencies import get_current_user
from app.firebase_admin_config import verify_token

router = APIRouter()
# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3_client = boto3.client('s3',
  endpoint_url=os.getenv('R2_ENDPOINT_URL'),
  aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
  aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
  region_name='weur'
)
bucket_name = 'umami'

# Update this if your ffmpeg path is different "",
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "/usr/bin/ffmpeg")

# Celery setup
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
celery_app = Celery('tasks', broker=REDIS_URL)

class ConvertRequest(BaseModel):
  filename: str

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConvertRequest(BaseModel):
  file_key: str
  unique_id: str

async def convert_video_task(input_path: str, output_path: str):
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

# Function to generate a presigned URL
def generate_presigned_url(file_key: str, expires_in: int = 3600) -> str:
  try:
    presigned_url = s3_client.generate_presigned_url(
      'get_object',
      Params={'Bucket': bucket_name, 'Key': file_key},
      ExpiresIn=expires_in  # Time in seconds for the URL to expire
    )
    return presigned_url
  except Exception as e:
    raise HTTPException(status_code=500, detail="Error generating URL")

# FastAPI endpoint that converts the Cloudflare R2 media URL to a presigned URL
@router.get("/convert-url/")
async def convert_url(file_key: str, expires_in: int = 3600):
  """
  Convert a Cloudflare R2 media file key into a presigned URL with an expiration time.
  Also return the original file key and the corresponding MP4 file key.
  """
  
  try:
    presigned_url = generate_presigned_url(file_key, expires_in)
    
    # Assuming the file_key follows the pattern: "{user_id}/videos/{timestamp}_{unique_id}.{extension}"
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

@router.post("/upload-and-convert")
async def upload_and_convert_video(
    file: UploadFile = File(...),
    authorization: str = Header(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    expires_in: int = 3600  # Default expiration time of 1 hour
):
    logger.info("Starting upload and convert process")
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
        logger.info(f"Authenticated user: {user_id}")
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    try:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())
        original_file_extension = os.path.splitext(file.filename)[1]
        original_filename = f"{timestamp}_{unique_id}{original_file_extension}"
        mp4_filename = f"{timestamp}_{unique_id}.mp4"
        thumbnail_filename = f"{timestamp}_{unique_id}_thumbnail.jpg"
        now = datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        day = now.strftime("%d")

        folder = f"media/{year}/{month}/{day}"
        original_file_key = f"{folder}/{uuid.uuid4()}{original_filename}"
        mp4_file_key = f"{folder}/{uuid.uuid4()}{mp4_filename}"
        thumbnail_file_key = f"{folder}/{uuid.uuid4()}{thumbnail_filename}"

        logger.info(f"Uploading original file to R2: {original_file_key}")
        # Upload the original file to R2
        s3_client.upload_fileobj(
            file.file,
            bucket_name,
            original_file_key,
            ExtraArgs={"ContentType": file.content_type, "ACL": "public-read"}
        )

        original_file_url = f"https://{os.getenv('R2_DEV_URL')}/{original_file_key.replace('/', '%2F')}"

        input_path = f"/tmp/{original_filename}"
        output_path = f"/tmp/{mp4_filename}"
        thumbnail_path = f"/tmp/{thumbnail_filename}"

        logger.info(f"Downloading file from R2: {original_file_key}")
        # Download the original file
        s3_client.download_file(bucket_name, original_file_key, input_path)

        # Convert the file to MP4 if it's not already
        if original_file_extension.lower() != '.mp4':
            logger.info(f"Converting file to MP4: {input_path} -> {output_path}")
            await convert_video_task(input_path, output_path)
        else:
            output_path = input_path

        logger.info(f"Generating thumbnail: {output_path} -> {thumbnail_path}")
        # Generate thumbnail
        thumbnail_command = [
            FFMPEG_PATH,
            "-i", output_path,
            "-ss", "00:00:01",  # Take screenshot at 1 second
            "-vframes", "1",
            "-vf", "scale=320:-1",  # Resize to 320px width, maintain aspect ratio
            thumbnail_path
        ]
        try:
            subprocess.run(thumbnail_command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Thumbnail generation failed: {str(e)}")
            logger.error(f"FFmpeg stderr: {e.stderr}")
            raise Exception(f"Thumbnail generation failed: {str(e)}")

        # Upload the MP4 file (if converted)
        if original_file_extension.lower() != '.mp4':
            logger.info(f"Uploading MP4 file to R2: {mp4_file_key}")
            s3_client.upload_file(
                output_path,
                bucket_name,
                mp4_file_key,
                ExtraArgs={"ContentType": "video/mp4", "ACL": "public-read"}
            )
            mp4_file_url = f"https://{os.getenv('R2_DEV_URL')}/{mp4_file_key.replace('/', '%2F')}"
        else:
            mp4_file_url = original_file_url

        logger.info(f"Uploading thumbnail to R2: {thumbnail_file_key}")
        # Upload the thumbnail
        s3_client.upload_file(
            thumbnail_path,
            bucket_name,
            thumbnail_file_key,
            ExtraArgs={"ContentType": "image/jpeg", "ACL": "public-read"}
        )
        thumbnail_file_url = f"https://{os.getenv('R2_DEV_URL')}/{thumbnail_file_key.replace('/', '%2F')}"

        # Generate presigned URLs
        original_presigned_url = s3_client.generate_presigned_url('get_object',
                                                                Params={'Bucket': bucket_name, 'Key': original_file_key},
                                                                ExpiresIn=expires_in)

        mp4_presigned_url = s3_client.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name, 'Key': mp4_file_key},
                                                            ExpiresIn=expires_in)

        thumbnail_presigned_url = s3_client.generate_presigned_url('get_object',
                                                                Params={'Bucket': bucket_name, 'Key': thumbnail_file_key},
                                                                ExpiresIn=expires_in)

        # Clean up temporary files
        background_tasks.add_task(os.remove, input_path)
        background_tasks.add_task(os.remove, output_path)
        background_tasks.add_task(os.remove, thumbnail_path)

        return JSONResponse({
            "original_file_url": original_file_url,
            "mp4_file_url": mp4_file_url,
            "thumbnail_file_url": thumbnail_file_url,
            "original_presigned_url": original_presigned_url,
            "mp4_presigned_url": mp4_presigned_url,
            "thumbnail_presigned_url": thumbnail_presigned_url,
            "expires_in": expires_in,
            "original_file_key": original_file_key,
            "mp4_file_key": mp4_file_key,
            "thumbnail_file_key": thumbnail_file_key
        })

    except Exception as e:
        logger.error(f"File upload, conversion, and thumbnail generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"File upload, conversion, and thumbnail generation failed: {str(e)}")

@router.delete("/delete/{bucket_name}/{prefix}")
async def delete_files_with_prefix(bucket_name: str, prefix: str):
  try:
    # List all objects with the given prefix
    objects_to_delete = s3_client.list_objects_v2(
      Bucket=bucket_name, Prefix=prefix)

    if 'Contents' not in objects_to_delete:
      return {"message": "No objects found with the given prefix"}

    # Create a list of keys to delete
    delete_keys = [{'Key': obj['Key']}
                  for obj in objects_to_delete['Contents']]

    # Delete all objects under the given prefix
    delete_response = s3_client.delete_objects(
      Bucket=bucket_name,
      Delete={'Objects': delete_keys}
    )

    return {"message": "Objects deleted successfully", "deleted_objects": delete_response['Deleted']}

  except Exception as e:  
    raise HTTPException(
      status_code=404, detail=f"Error deleting objects: {e}")

@router.delete("/remove-assets/{bucket}/{folder:path}")
async def remove_assets(
  bucket: str,
  folder: str,
  # authorization: str = Header(...),
):
  try:
    # Verify token
    # token = authorization.split("Bearer ")[1]
    # decoded_token = verify_token(token)
    # user_id = decoded_token['uid']

    # # Ensure the user can only delete from their own folder
    # if not folder.startswith(f"{user_id}/"):
    #   raise HTTPException(status_code=403, detail="You can only delete your own assets")

    # List all objects in the folder
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=folder)

    if 'Contents' not in response:
      return {"message": "No objects found in the specified folder"}

    # Prepare the list of objects to delete
    objects_to_delete = [{'Key': obj['Key']} for obj in response['Contents']]

    # Delete the objects
    s3_client.delete_objects(
      Bucket=bucket,
      Delete={'Objects': objects_to_delete}
    )

    return {
      "message": f"Successfully deleted {len(objects_to_delete)} objects from folder '{folder}' in bucket '{bucket}'"
    }

  except Exception as e:
    logger.error(f"Error deleting assets: {str(e)}")
    raise HTTPException(status_code=500, detail=f"Failed to delete assets: {str(e)}")

