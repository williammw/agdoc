from datetime import datetime
import subprocess
import uuid
from fastapi import APIRouter, FastAPI, File, HTTPException, Header, UploadFile
from fastapi.responses import FileResponse
from starlette.responses import JSONResponse
import boto3
import os

from app.firebase_admin_config import verify_token

router = APIRouter()

s3_client = boto3.client('s3',
                          endpoint_url=os.getenv('R2_ENDPOINT_URL'),
                          aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                          aws_secret_access_key=os.getenv(
                              'R2_SECRET_ACCESS_KEY'),
                          region_name='weur'
                          )
bucket_name = 'umami'


# Update this if your ffmpeg path is different "",
FFMPEG_PATH = "/opt/homebrew/bin/ffmpeg"


@router.post("/convert")
async def convert_video(filename: str):
    input_filename = f"/tmp/{uuid.uuid4()}.webm"
    output_filename = f"/tmp/{uuid.uuid4()}.mp4"

    # Download the WebM file from Cloudflare R2
    try:
        s3_client.download_file(bucket_name, filename, input_filename)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to download file from storage: {e}")

    # Construct the ffmpeg command to convert WebM to MP4
    command = [
        FFMPEG_PATH,
        "-i", input_filename,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-strict", "experimental",
        output_filename
    ]

    # Execute the ffmpeg command
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        os.remove(input_filename)  # Clean up the input file
        raise HTTPException(
            status_code=500, detail=f"Video conversion failed: {e}")

    # Clean up the input file after conversion
    os.remove(input_filename)

    # Ensure output file exists before sending response
    if not os.path.exists(output_filename):
        raise HTTPException(
            status_code=500, detail="Output file not found after conversion")

    # Upload the converted file back to Cloudflare R2
    try:
        converted_file_key = filename.replace('.webm', '.mp4')
        s3_client.upload_file(output_filename, bucket_name, converted_file_key, ExtraArgs={
                              "ContentType": "video/mp4", "ACL": "public-read"})
        file_url = f"https://{os.getenv('R2_DEV_URL')}/{converted_file_key.replace('/', '%2F')}"
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to upload converted file: {e}")
    finally:
        os.remove(output_filename)  # Clean up the output file after upload

    return JSONResponse({"file_url": file_url})


@router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    authorization: str = Header(...),
):
    token = authorization.split(" ")[1]
    decoded_token = verify_token(token)
    user_id = decoded_token['uid']

    if file.content_type != "video/webm":
        raise HTTPException(
            status_code=400, detail="Only WebM files are supported")

    try:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{timestamp}_{unique_id}{file_extension}"

        folder = f"{user_id}/videos"
        # Generate a unique filename for the upload
        filename = f"{uuid.uuid4()}.webm"
        file_key = f"{folder}/{unique_filename}"

        # Upload the file to R2 (or save it locally if desired)
        s3_client.upload_fileobj(
            file.file,
            bucket_name,
            file_key,
            ExtraArgs={"ContentType": file.content_type, "ACL": "public-read"}
        )

        file_url = f"https://{os.getenv('R2_DEV_URL')}/{file_key.replace('/', '%2F')}"

        return JSONResponse({"file_url": file_url, "filename": filename})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")
