# cnd_router.py
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from databases import Database
from app.dependencies import get_database
import boto3
import httpx
import os

router = APIRouter()

# Initialize the boto3 client for Cloudflare R2
r2_client = boto3.client(
    's3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name='weur'
)


@router.post("/upload-image-cloudflare/")
async def upload_to_cloudflare(file: UploadFile = File(...), database: Database = Depends(get_database)):
    headers = {
        "Authorization": f"Bearer {os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')}",
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/images/v1"

    files = {
        'file': (file.filename, await file.read(), file.content_type),
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, files=files)
        response.raise_for_status()

    image_data = response.json()

    try:
        url = image_data.get("result", {}).get("variants", [])[0]
    except IndexError:
        raise HTTPException(
            status_code=500, detail="URL not returned from Cloudflare")

    query = """
    INSERT INTO cloudflare_images (filename, url, content_type, cloudflare_id)
    VALUES (:filename, :url, :content_type, :cloudflare_id)
    """
    values = {
        "filename": file.filename,
        "url": url,
        "content_type": file.content_type,
        "cloudflare_id": image_data.get("result", {}).get("id"),
    }

    await database.execute(query=query, values=values)

    return {"message": "Image uploaded and metadata saved successfully", "data": image_data}


@router.post("/upload-image-r2/")
async def upload_to_r2(file: UploadFile = File(...), database: Database = Depends(get_database)):
    bucket_name = os.getenv('R2_BUCKET_NAME')

    # Generate a unique file name to avoid conflicts
    # Ensure this is unique if necessary, e.g., by appending a timestamp or UUID
    file_key = f"images/{file.filename}"

    try:
        # Upload file to R2
        r2_client.upload_fileobj(
            file.file,
            bucket_name,
            file_key,
            ExtraArgs={"ContentType": file.content_type}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not upload the image to Cloudflare R2: {str(e)}"
        )

    # Construct the file URL
    file_url = f"{os.getenv('R2_ENDPOINT_URL')}/{bucket_name}/{file_key}"

    # Proceed with database insertion
    query = """
    INSERT INTO cloudflare_r2_data (filename, url, content_type, r2_object_key)
    VALUES (:filename, :url, :content_type, :r2_object_key)
    """
    values = {
        "filename": file.filename,
        "url": file_url,
        "content_type": file.content_type,
        "r2_object_key": file_key  # Ensure this is correctly passed
    }

    try:
        await database.execute(query=query, values=values)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to insert metadata into the database: {str(exc)}"
        )

    return {"message": "Image uploaded to Cloudflare R2 and metadata saved successfully", "url": file_url}
