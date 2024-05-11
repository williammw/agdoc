import base64
from fastapi.responses import JSONResponse
from fastapi import APIRouter, HTTPException, Request
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


router = APIRouter()
# Ensure your OpenAI API key is configured properly in your environment variables
client = OpenAI()


@router.post("/text_to_speech_pipeline/")
async def text_to_speech_pipeline(request: Request):
    data = await request.json()  # Extract JSON payload from the request
    text = data.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="No input text provided")

    try:
        # Generate response text using OpenAI GPT
        gpt_response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[{"role": "user", "content": text}]
        )
        response_text = gpt_response.choices[0].message.content.strip()

        # Convert text to speech
        tts_response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=response_text
        )
        audio_data = tts_response.content
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        # Return both text and audio data
        return JSONResponse(content={
            "text": response_text,
            "audio": f"data:audio/mp3;base64,{audio_base64}"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
