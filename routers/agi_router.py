from fastapi import APIRouter, FastAPI, File, UploadFile
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from typing_extensions import Annotated
import shutil
import httpx



router = APIRouter()

import os
load_dotenv()

client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
)


@router.get("/")
async def greeting():
    return {"message": "Hello from Agi API!"}

@router.get("/getApi")
async def getApi():
    return {os.getenv('TEST_API')}


@router.post("/files/")
async def create_file(file: Annotated[bytes, File()]):
    return {"file_size": len(file)}


@router.post("/uploadfile/")
async def create_upload_file(file: UploadFile):
    # Define the location to save the file
    file_location = f"./uploaded_files/{file.filename}"
    # Open a new file in write-binary mode and save the uploaded file content
    with open(file_location, "wb") as buffer:
        # Use shutil to copy the file object to the buffer
        shutil.copyfileobj(file.file, buffer)

    return {"filename": file.filename, "location": file_location}


@router.post("/upload-cloudflare/")
async def upload_to_cloudflare(file: UploadFile = File(...)):
    # Assuming you have a function to get a fresh BATCH_TOKEN if needed
    # BATCH_TOKEN = await get_batch_token()

    '''
    $ curl -H "Authorization: Bearer <CLOUDFLARE_API_TOKEN>" \
      "https://api.cloudflare.com/client/v4/accounts/ACCOUNT_ID/images/v1/batch_token"

    {
      "result": {
        "token": "<BATCH_TOKEN>",
        "expiresAt": "2023-08-09T15:33:56.273411222Z"
      },
      "success": true,
      "errors": [],
      "messages": []
    }
    '''


    headers = {
        "Authorization": f"Bearer {os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')}",
        # Additional headers if needed
    }

    url = f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/images/v1"

    # Read file content
    content = await file.read()

    files = {
        'file': (file.filename, content, file.content_type),
    }

    # Using httpx to send the multipart/form-data request
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, files=files)
        if response.status_code != 200:
            raise HTTPException(
                status_code=400, detail="Could not upload the image to Cloudflare")

    return response.json()
