from fastapi import APIRouter, FastAPI, Request, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from typing_extensions import Annotated
import shutil
import httpx
from starlette.responses import Response
from starlette.responses import StreamingResponse
import os
import requests
from pydub import AudioSegment
from app.dependencies import get_database
import io 
router = APIRouter()

load_dotenv()

client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
)

@router.get("/")
async def greeting():
    return {"message": "Wrapper of openai API"}


@router.post("/text_to_speech/")
async def text_to_speech(request: Request):
    try:
        body = await request.json()
    except JSONDecodeError:
        raise HTTPException(
            status_code=400, detail="Invalid or missing JSON body")

    input_text = body.get("text")
    if not input_text:
        raise HTTPException(status_code=400, detail="No text provided")

    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=input_text
        )

        # Stream the binary content directly
        return StreamingResponse(io.BytesIO(response.content), media_type="audio/mpeg")

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate speech: {str(e)}")
