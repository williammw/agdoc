import os
from typing import List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
import time
from openai import RateLimitError

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_OLD")
client = OpenAI(
    api_key=OPENAI_API_KEY,
    # base_url="https://api.x.ai/v1",
)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]


@router.post("/chat/stream")
async def stream_chat(request: ChatRequest):
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                stream=True
            )

            def generate():
                for chunk in stream:
                    if chunk.choices[0].delta.content is not None:
                        yield f"data: {chunk.choices[0].delta.content}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream"
            )

        except RateLimitError:
            if attempt == max_retries - 1:
                raise HTTPException(
                    status_code=429, 
                    detail="Rate limit exceeded. Please try again later."
                )
            time.sleep(retry_delay * (attempt + 1))
            continue
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat(request: ChatRequest):
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": m.role, "content": m.content}
                        for m in request.messages],
            )
            return {"response": response.choices[0].message.content}

        except RateLimitError:
            if attempt == max_retries - 1:
                raise HTTPException(
                    status_code=429, 
                    detail="Rate limit exceeded. Please try again later."
                )
            time.sleep(retry_delay * (attempt + 1))
            continue
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def root():
    return {"message": "Hello World"}
