from fastapi import APIRouter, FastAPI, File, UploadFile
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from typing_extensions import Annotated
import shutil



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
