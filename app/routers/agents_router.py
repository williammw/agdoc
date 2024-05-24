#agents_router.py
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, UploadFile, File, Query
from fastapi import APIRouter, Request, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.responses import StreamingResponse, HTMLResponse
from dotenv import load_dotenv
from openai import OpenAI
import os
from io import BytesIO
import base64
import io
from pydub import AudioSegment
from pydantic import BaseModel
from typing import List
import asyncio
import shutil
from typing import Dict
from app.dependencies import get_current_user, verify_token
import json

router = APIRouter()
load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


@router.get("/")
async def greeting():
    return {"message": "Wrapper of OpenAI API"}


@router.post("/text_to_speech_pipeline/")
async def text_to_speech_pipeline(request: Request, user = Depends(get_current_user)):
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

# Endpoint for text to speech pipeline stream


class StreamRequest(BaseModel):
    text: str
    token: str


@router.post("/generate_stream_url/")
async def generate_stream_url(data: StreamRequest):
    user = verify_token(data.token)  # Verifying the token
    text = data.text
    if not text:
        raise HTTPException(status_code=400, detail="No input text provided")

    # Generate the stream URL
    # Replace with your logic to generate the stream ID
    stream_id = "generated_stream_id"
    stream_url = f"/api/v1/agents/text_to_speech_pipeline_stream/{stream_id}"

    return {"stream_url": stream_url}

# Function to generate audio (to be called after receiving the complete text)


def generate_audio(complete_text: str):
    tts_response = client.audio.speech.create(
        model="tts-1",
        input=complete_text,
        voice="nova",
        response_format="mp3"
    )
    audio_data = tts_response.content
    audio_base64 = base64.b64encode(audio_data).decode("utf-8")
    return audio_base64


@router.get("/text_to_speech_pipeline_stream/{stream_id}")
async def text_to_speech_pipeline_stream(stream_id: str, token: str = Query(...), text: str = Query(...)):
    user = verify_token(token)

    if not user:
        raise HTTPException(status_code=403, detail="Invalid token")

    async def event_generator(text):
        try:
            completion = client.chat.completions.create(
                model="gpt-3.5-turbo-0301",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant, you are going to respond in markdown format."},
                    {"role": "user", "content": text}
                ],
                stream=True
            )

            complete_text = ""
            chat_id = stream_id
            for chunk in completion:
                delta = chunk.choices[0].delta
                if delta.content is not None:
                    complete_text += delta.content
                    response_json = {
                        "message": {
                            "id": str(chunk.id),  # Ensure chunk.id is a string
                            "created": str(chunk.created), # Ensure created is a string
                            "role": delta.role if delta.role else "assistant",
                            "finish_reason": chunk.choices[0].finish_reason if chunk.choices[0].finish_reason else "incomplete",
                            "content": delta.content,
                        },
                        "chat_id": chat_id,
                        "model": chunk.model,
                        "object": chunk.object,
                    }
                    # Convert dictionary to a JSON string
                    response_str = json.dumps(response_json)
                    yield f"data: {response_str}\n\n"
                    await asyncio.sleep(0.05)

            if chunk.choices[0].finish_reason == 'stop':
                audio_base64 = generate_audio(complete_text)
                yield f"data: [AUDIO]{audio_base64}\n\n"

        except Exception as e:
            yield f"data: Error: {str(e)}\n\n"

    return StreamingResponse(event_generator(text), media_type="text/event-stream")



# Other endpoints and functions here...

@router.post("/upload-audio/")
async def create_upload_file(audio_file: UploadFile = File(...), user=Depends(get_current_user)):
    temp_file_path = f"temp_{audio_file.filename}"
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(audio_file.file, buffer)

    transcript, word_timestamps = await transcribe_audio(temp_file_path)
    os.remove(temp_file_path)  # Cleanup the uploaded file

    transcript_file_name = "transcript_output.txt"
    save_transcript_to_file(transcript, transcript_file_name)

    return {"transcript": transcript, "word_timestamps": word_timestamps}

async def transcribe_audio(file_path):
    audio = AudioSegment.from_file(file_path)
    segment_duration = 30 * 1000  # 30 seconds
    num_segments = len(audio) // segment_duration + \
        (len(audio) % segment_duration > 0)
    full_transcript = ""
    word_timestamps = []

    for i in range(num_segments):
        start_time = i * segment_duration
        end_time = min(start_time + segment_duration, len(audio))
        segment = audio[start_time:end_time]
        segment_file = f"temp_segment_{i}.mp3"
        segment.export(segment_file, format="mp3")

        with open(segment_file, "rb") as file:
            transcript =  client.audio.transcriptions.create(
                model="whisper-1",
                file=file,
                response_format="verbose_json",
                timestamp_granularities=["word"]
            )
            print(transcript)
            # TODO:
            '''
            Transcription(text="Program still has some issues. The recording icons keep showing on the 
            Chrome and I don't know how to stop it", task='transcribe', language='english', duration=10.380000114440918, 
            words=[{'word': 'Program', 'start': 0.5400000214576721, 'end': 1.2400000095367432}, 
            {'word': 'still', 'start': 1.2400000095367432, 'end': 1.559999942779541}, 
            {'word': 'has', 'start': 1.559999942779541, 'end': 1.7599999904632568}, 
            {'word': 'some', 'start': 1.7599999904632568, 'end': 2.140000104904175}, 
            {'word': 'issues', 'start': 2.140000104904175, 'end': 2.5999999046325684}, 
            {'word': 'The', 'start': 3.640000104904175, 'end': 4.71999979019165}, 
            {'word': 'recording', 'start': 4.71999979019165, 'end': 5.420000076293945}, 
            {'word': 'icons', 'start': 5.420000076293945, 'end': 6.039999961853027}, 
            {'word': 'keep', 'start': 6.039999961853027, 'end': 6.880000114440918}, 
            {'word': 'showing', 'start': 6.880000114440918, 'end': 7.599999904632568},
            {'word': 'on', 'start': 7.599999904632568, 'end': 8.020000457763672}, 
            {'word': 'the', 'start': 8.020000457763672, 'end': 8.260000228881836}, 
            {'word': 'Chrome', 'start': 8.260000228881836, 'end': 8.65999984741211}, 
            {'word': 'and', 'start': 8.65999984741211, 'end': 8.819999694824219}, 
            {'word': 'I', 'start': 8.819999694824219, 'end': 8.979999542236328}, 
            {'word': "don't", 'start': 8.979999542236328, 'end': 9.100000381469727}, 
            {'word': 'know', 'start': 9.100000381469727, 'end': 9.239999771118164}, 
            {'word': 'how', 'start': 9.239999771118164, 'end': 9.420000076293945}, {'word': 'to', 'start': 9.420000076293945, 'end': 9.640000343322754}, {'word': 'stop', 'start': 9.640000343322754, 'end': 9.880000114440918}, {'word': 'it', 'start': 9.880000114440918, 'end': 10.039999961853027}])
            '''
            # Append the text to full_transcript
            full_transcript += transcript.text + " "

            # Collect word-level timestamps
            word_timestamps.extend(transcript.words)

        os.remove(segment_file)

    return full_transcript, word_timestamps


def save_transcript_to_file(transcript, file_name):
    with open(file_name, 'w', encoding='utf-8') as file:
        file.write(transcript)
