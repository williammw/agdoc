import boto3
import os
from fastapi import UploadFile, HTTPException
from botocore.exceptions import ClientError
import uuid
from urllib.parse import urlparse
from datetime import datetime
import tempfile


def get_r2_client():
    return boto3.client(
        's3',
        endpoint_url=os.getenv('R2_ENDPOINT_URL'),
        aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
        region_name='weur'  # R2 doesn't use regions, but this is required
    )


async def upload_to_r2(file: UploadFile, user_id: str):
    r2_client = get_r2_client()
    bucket_name = os.getenv('R2_BUCKET_NAME')
    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")

    # Generate a unique filename
    file_extension = os.path.splitext(file.filename)[1]
    # unique_filename = f"{user_id}/{uuid.uuid4()}{file_extension}"
    unique_filename = f"media/{year}/{month}/{day}/{uuid.uuid4()}{file_extension}"

    try:
        # Upload file to R2
        r2_client.upload_fileobj(
            file.file,
            bucket_name,
            unique_filename,
            ExtraArgs={"ContentType": file.content_type}
        )

        # Construct the URL for the uploaded file
        file_url = f"https://{os.getenv('R2_DEV_URL')}/{unique_filename}"

        return {"url": file_url}
    except ClientError as e:
        print(f"Error uploading file to R2: {e}")
        raise


def extract_file_key_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    # The path starts with a leading slash, so we remove it
    return parsed_url.path.lstrip('/')


async def delete_file_from_r2(file_url: str):
    r2 = get_r2_client()
    file_key = extract_file_key_from_url(file_url)
    try:
        r2.delete_object(Bucket=os.getenv('R2_BUCKET_NAME'), Key=file_key)
        print(f"File {file_key} deleted successfully from R2")
    except ClientError as e:
        print(f"Error deleting file {file_key} from R2: {str(e)}")
        raise


async def up_to_r2(
    file: UploadFile,
    user_id: str,
    database,
    image_type: str = None  # 'avatar', 'cover', or None for post media
):
    r2_client = get_r2_client()
    bucket_name = os.getenv('R2_BUCKET_NAME')

    # Validate file type
    allowed_mime_types = ['image/jpeg', 'image/png', 'image/webp', 'image/svg+xml', 'image/bmp', 'image/tiff', 'image/x-icon', 'image/vnd.microsoft.icon', 'image/vnd.wap.wbmp', 'image/apng', 'image/gif', 'video/mp4', 'video/mpeg']
    mime_type = file.content_type
    if mime_type not in allowed_mime_types:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # Generate common components
    now = datetime.now()
    year, month, day = now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")
    asset_id = str(uuid.uuid4())
    file_extension = os.path.splitext(file.filename)[1]

    # Determine file path and variants based on image_type
    if image_type in ['avatar', 'cover']:
        base_path = f"profile/{year}/{month}/{day}/{asset_id}"
        variants = ['original', 'thumbnail', 'optimized']
    else:
        base_path = f"media/{year}/{month}/{day}/{asset_id}"
        variants = ['original', 'optimized', 'thumbnail'] if mime_type.startswith('image/') else ['original', '720p', 'thumbnail'] if mime_type.startswith('video/') else ['original']

    uploaded_files = []

    # Create a temporary file
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        content = await file.read()
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        for variant in variants:
            file_key = f"{base_path}/{variant}{file_extension}"
            content_type = file.content_type

            # Open the temporary file for each variant
            with open(temp_file_path, 'rb') as file_to_upload:
                try:
                    # Upload file to R2
                    r2_client.upload_fileobj(
                        file_to_upload,
                        bucket_name,
                        file_key,
                        ExtraArgs={"ContentType": content_type, "ACL": "public-read"}
                    )

                    # Construct the file URL
                    file_url = f"https://{os.getenv('R2_DEV_URL')}/{file_key.replace('/', '%2F')}"

                    uploaded_files.append({
                        "variant": variant,
                        "url": file_url,
                        "file_key": file_key,
                    })

                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Could not upload the {variant} variant to Cloudflare R2: {str(e)}"
                    )

        # Insert new record or update existing one for each variant
        for uploaded_file in uploaded_files:
            query = """
            INSERT INTO cloudflare_r2_data (filename, url, content_type, r2_object_key, user_id, is_public, variant)
            VALUES (:filename, :url, :content_type, :r2_object_key, :user_id, :is_public, :variant)
            ON CONFLICT (r2_object_key) 
            DO UPDATE SET 
                filename = EXCLUDED.filename,
                url = EXCLUDED.url,
                content_type = EXCLUDED.content_type,
                user_id = EXCLUDED.user_id,
                is_public = EXCLUDED.is_public,
                variant = EXCLUDED.variant
            RETURNING id
            """
            values = {
                "filename": os.path.basename(uploaded_file['file_key']),
                "url": uploaded_file['url'],
                "content_type": file.content_type,
                "r2_object_key": uploaded_file['file_key'],
                "user_id": user_id,
                "is_public": False,  # Default to private
                "variant": uploaded_file['variant']
            }

            try:
                result = await database.fetch_one(query=query, values=values)
                if not result:
                    raise HTTPException(
                        status_code=500, detail=f"Failed to insert or update metadata for {uploaded_file['variant']} variant in the database")
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to insert or update metadata for {uploaded_file['variant']} variant in the database: {str(exc)}"
                )

    finally:
        # Clean up the temporary file
        os.unlink(temp_file_path)

    return {
        "message": "Files uploaded to Cloudflare R2 and metadata saved successfully",
        "files": uploaded_files
    }
