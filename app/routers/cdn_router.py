from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from dotenv import load_dotenv
from databases import Database
from app.dependencies import get_database  # Adjust the import path as necessary
import httpx
import os
# Assuming this is your model for image metadata
# from app.models.models import ImageMetadata


router = APIRouter()


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
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code, detail="Could not upload the image to Cloudflare")

    image_data = response.json()

    # Correctly extracting the URL from the Cloudflare response
    url = image_data.get("result", {}).get("variants", [])[
        0] if image_data.get("result", {}).get("variants") else None
    if not url:
        raise HTTPException(
            status_code=500, detail="URL not returned from Cloudflare")

    # Proceed with database insertion
    query = """
    INSERT INTO image_metadata (filename, url, content_type, cloudflare_id)
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
