from fastapi import APIRouter, FastAPI, Request, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from typing_extensions import Annotated
import shutil
import httpx
from starlette.responses import Response
from openai import OpenAI
import os
import requests
from pydub import AudioSegment



router = APIRouter()


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


@router.post("/get-files-size/")
async def create_file(file: Annotated[bytes, File()]):
    return {"file_size": len(file)}




@router.post("/upload-image-cloudflare/")
async def upload_to_cloudflare(file: UploadFile = File(...)):
    # Assuming you have a function to get a fresh BATCH_TOKEN if needed
    # BATCH_TOKEN = await get_batch_token()
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

    


@router.post("/uploadfile-local/")
async def create_upload_file(file: UploadFile):
    # Define the location to save the file
    file_location = f"./uploaded_files/{file.filename}"
    # Open a new file in write-binary mode and save the uploaded file content
    with open(file_location, "wb") as buffer:
        # Use shutil to copy the file object to the buffer
        shutil.copyfileobj(file.file, buffer)

    return {"filename": file.filename, "location": file_location}


@router.post("/get-upload-url")
async def get_upload_url(file: UploadFile = File(...)):
    file_size = await file.read()
    upload_length = str(len(file_size))
    file.file.seek(0)  # Reset file pointer after reading

    async with httpx.AsyncClient() as client:
        cloudflare_endpoint = f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/stream?direct_user=true"
        headers = {
            "Authorization": f"Bearer {os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')}",
            "Tus-Resumable": "1.0.0",
            "Upload-Length": upload_length,
            # "Upload-Metadata" can be set as needed; here it's omitted for simplicity
        }

        try:
            response = await client.post(cloudflare_endpoint, headers=headers)
            response.raise_for_status()  # Raises exception for 4XX/5XX responses
        except httpx.RequestError as e:
            print(f"An error occurred while requesting {e.request.url!r}.")
            return {"error": f"An error occurred while requesting {e.request.url!r}."}
        except httpx.HTTPStatusError as e:
            print(
                f"Error response {e.response.status_code} while requesting {e.request.url!r}.")
            return {"error": f"Error response {e.response.status_code} while requesting {e.request.url!r}."}

        # Extracting the Location header which contains the upload URL
        upload_url = response.headers.get("Location")

        # Returning the upload URL in the Location header of the response
        return Response(content=upload_url, media_type="text/plain", headers={"Location": upload_url})


@router.patch("/upload-tus-chunk/")
async def upload_tus_chunk(request: Request, file_id: str):
    # This endpoint would need to receive the file ID (or TUS URL) and the chunk
    cloudflare_tus_url = f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/stream/{file_id}"

    # Extract the necessary TUS headers from the incoming request
    tus_headers = {
        "Tus-Resumable": request.headers.get("Tus-Resumable"),
        "Upload-Offset": request.headers.get("Upload-Offset"),
        "Content-Type": "application/offset+octet-stream",
    }

    # Read the incoming chunk
    chunk_data = await request.body()

    # Forward the chunk to Cloudflare using a PATCH request
    async with httpx.AsyncClient() as client:
        response = await client.patch(cloudflare_tus_url, headers=tus_headers, content=chunk_data)
        if response.status_code not in (204, 200):
            raise HTTPException(status_code=response.status_code,
                                detail="Failed to upload chunk to Cloudflare")

    return {"success": True, "message": "Chunk uploaded successfully"}

# do the ASR shit


@router.post("/upload-audio/")
async def create_upload_file(audio_file: UploadFile = File(...)):
    with open(f"temp_{audio_file.filename}", "wb") as buffer:
        shutil.copyfileobj(audio_file.file, buffer)

    transcript = await transcribe_audio(f"temp_{audio_file.filename}")
    # print(transcript)
    os.remove(f"temp_{audio_file.filename}")  # Cleanup the uploaded file

    transcript_file_name = "transcript_output.txt"
    save_transcript_to_file(transcript, transcript_file_name)
    return FileResponse(transcript_file_name, media_type='application/octet-stream', filename=transcript_file_name)


async def transcribe_audio(file_path):
    audio = AudioSegment.from_file(file_path)
    segment_duration = 30 * 1000  # 30 seconds
    num_segments = len(audio) // segment_duration + \
        (len(audio) % segment_duration > 0)
    full_transcript = ""
    for i in range(num_segments):
        start_time = i * segment_duration
        end_time = min(start_time + segment_duration, len(audio))
        segment = audio[start_time:end_time]
        segment_file = f"temp_segment_{i}.mp3"
        segment.export(segment_file, format="mp3")
        with open(segment_file, "rb") as file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=file
            )
            transcribed_text = transcript.text
            # Append the transcript text to the full transcript
            full_transcript += transcribed_text + " "
        os.remove(segment_file)
    return full_transcript


def save_transcript_to_file(transcript, file_name):
    with open(file_name, 'w', encoding='utf-8') as file:
        file.write(transcript)
