from fastapi import APIRouter, HTTPException, Request, FastAPI, UploadFile, File, WebSocket
from fastapi.responses import StreamingResponse, HTMLResponse
from dotenv import load_dotenv
from openai import OpenAI
import os
import base64
import io
from pydub import AudioSegment
from pydantic import BaseModel
from typing import List
import asyncio

router = APIRouter()
load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


@router.get("/")
async def greeting():
    return {"message": "Wrapper of OpenAI API"}


@router.post("/text_to_speech_pipeline/")
async def text_to_speech_pipeline(request: Request):
    data = await request.json()
    text = data.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="No input text provided")

    try:
        # Generate response text using OpenAI GPT
        gpt_response = client.chat.completions.create(
            model="gpt-3.5-turbo-0301",
            messages=[{"role": "user", "content": text}]
        )
        response_text = gpt_response.choices[0].message.content.strip()

        # Convert text to speech
        tts_response = client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=response_text
        )

        audio_data = io.BytesIO(tts_response.content)

        def iterfile():
            yield from audio_data

        return StreamingResponse(iterfile(), media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/text_to_speech_pipeline_stream/")
async def text_to_speech_pipeline_stream(text: str):
    async def event_generator(text):
        try:
            gpt_response = client.chat.completions.create(
                model="gpt-3.5-turbo-0301",
                messages=[{"role": "user", "content": text}]
            )
            response_text = gpt_response.choices[0].message.content.strip()

            # Simulate streaming response
            for i in range(0, len(response_text), 20):
                chunk = response_text[i:i + 20]
                yield f"data: {chunk}\n\n"
                await asyncio.sleep(0.1)  # Simulate delay

            tts_response = client.audio.speech.create(
                model="tts-1",
                voice="nova",
                input=response_text
            )
            audio_data = tts_response.content
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

            yield f"data: [AUDIO]{audio_base64}\n\n"
        except Exception as e:
            yield f"data: Error: {str(e)}\n\n"

    return StreamingResponse(event_generator(text), media_type="text/event-stream")


class Transcript(BaseModel):
    timestamp: str
    text: str


@router.websocket("/transcribe/")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_bytes()
        response = client.audio.transcriptions.create(
            audio_content=data,
            model="whisper-1",
            language="en"
        )

        transcripts = []
        for segment in response["segments"]:
            transcript = Transcript(
                timestamp=segment["timestamp"], text=segment["text"])
            transcripts.append(transcript)

        await websocket.send_json([transcript.dict() for transcript in transcripts])
