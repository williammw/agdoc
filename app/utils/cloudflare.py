import boto3
import os
from fastapi import UploadFile
from botocore.exceptions import ClientError
import uuid
from urllib.parse import urlparse


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

    # Generate a unique filename
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{user_id}/{uuid.uuid4()}{file_extension}"

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
