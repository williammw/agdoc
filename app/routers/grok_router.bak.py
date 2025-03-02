# import os
# import json
# from typing import List, Optional, Union, Literal, Dict, Any
# from fastapi import APIRouter, HTTPException
# from fastapi.responses import StreamingResponse
# from pydantic import BaseModel
# from openai import OpenAI
# import base64

# router = APIRouter()

# XAI_API_KEY = os.getenv("XAI_API_KEY")
# client = OpenAI(
#     api_key=XAI_API_KEY,
#     base_url="https://api.x.ai/v1",
# )


# class Message(BaseModel):
#     role: str
#     content: str


# class ChatRequest(BaseModel):
#     messages: List[Message]


# SYSTEM_PROMPT = """
# you are helpful assistant.
# for generated content, you should use markdown format.
# for latex, you should use the following format:
# ```latex
# {latex code}
# ```

# for generating tables, please structure the response in this exact format:
# ```markdown-table
# {markdown table}
# ```



# """


# class ImageURL(BaseModel):
#     url: str


# class ImageContent(BaseModel):
#     type: Literal["image_url", "text"]
#     text: Optional[str] = None
#     image_url: Optional[Dict[str, str]] = None


# class VisionMessage(BaseModel):
#     role: str
#     content: Union[str, List[ImageContent]]


# class VisionRequest(BaseModel):
#     messages: List[VisionMessage]
#     model: str = "grok-2-vision-1212"
#     max_tokens: Optional[int] = None


# class ContinuationRequest(BaseModel):
#     previous_response: str
#     original_prompt: str
#     max_attempts: Optional[int] = 3


# @router.post("/chat/stream")
# async def stream_chat(request: ChatRequest):
#     try:
#         messages = [
#             {
#                 "role": "system",
#                 "content": SYSTEM_PROMPT
#             },
#             *[{"role": m.role, "content": m.content} for m in request.messages]
#         ]

#         stream = client.chat.completions.create(
#             model="grok-2-1212",
#             messages=messages,
#             stream=True
#         )

#         # def generate():
#         #     for chunk in stream:
#         #         if chunk.choices[0].delta.content is not None:
#         #             yield f"data: {{'v': {repr(chunk.choices[0].delta.content)}}}\n\n"
#         #     yield "data: [DONE]\n\n"
        
#         def generate():
#             for chunk in stream:
#                 if chunk.choices[0].delta.content is not None:
#                     # Use json.dumps instead of repr
#                     yield f"data: {json.dumps({'v': chunk.choices[0].delta.content})}\n\n"
#             yield "data: [DONE]\n\n"

#         return StreamingResponse(
#             generate(),
#             media_type="text/event-stream"
#         )

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/chat")
# async def chat(request: ChatRequest):
#     try:
#         messages = [
#             {"role": "system", "content": SYSTEM_PROMPT},
#             *[{"role": m.role, "content": m.content} for m in request.messages]
#         ]

#         response = client.chat.completions.create(
#             model="grok-beta",
#             messages=messages,
#         )
        
#         content = response.choices[0].message.content
#         # Check if response seems incomplete (ends with ..., etc.)
#         needs_continuation = (
#             content.rstrip().endswith(('...', '…')) or
#             len(content) >= 4000  # Assuming this is near the token limit
#         )
        
#         return {
#             "response": content,
#             "needs_continuation": needs_continuation
#         }

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/chat/continue")
# async def continue_chat(request: ContinuationRequest):
#     try:
#         continuation_prompt = f"""
# Continue the previous response. Previous response was:
# {request.previous_response}

# Original prompt was:
# {request.original_prompt}

# Please continue where you left off, maintaining the same style and format.
# """
        
#         messages = [
#             {"role": "system", "content": SYSTEM_PROMPT},
#             {"role": "user", "content": continuation_prompt}
#         ]

#         response = client.chat.completions.create(
#             model="grok-beta",
#             messages=messages,
#         )
#         return {"response": response.choices[0].message.content}

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/chat/vision")
# async def vision_chat(request: VisionRequest):
#     try:
#         messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
#         for msg in request.messages:
#             if isinstance(msg.content, list):
#                 processed_content = []
#                 for item in msg.content:
#                     if isinstance(item, dict) and item.get("type") == "image_url":
#                         url = item["image_url"]["url"]
#                         if url.startswith('data:image'):
#                             processed_content.append({
#                                 "type": "image_url",
#                                 "image_url": {"url": url}
#                             })
#                         else:
#                             processed_content.append({
#                                 "type": "image_url",
#                                 "image_url": {"url": url}
#                             })
#                     else:
#                         processed_content.append(item)
#                 messages.append({
#                     "role": msg.role,
#                     "content": processed_content
#                 })
#             else:
#                 messages.append({
#                     "role": msg.role,
#                     "content": msg.content
#                 })

#         response = client.chat.completions.create(
#             model=request.model,
#             messages=messages,
#             max_tokens=request.max_tokens,
#         )
#         return {"response": response.choices[0].message.content}

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/")
# async def root():
#     return {"message": "Hello World"}


# @router.post("/chat/stream-continuous")
# async def stream_chat_continuous(request: ChatRequest):
#     try:
#         messages = [
#             {"role": "system", "content": SYSTEM_PROMPT},
#             *[{"role": m.role, "content": m.content} for m in request.messages]
#         ]

#         async def generate():
#             nonlocal messages
#             max_continuations = 3
#             continuation_count = 0
            
#             while continuation_count < max_continuations:
#                 stream = client.chat.completions.create(
#                     model="grok-beta",
#                     messages=messages,
#                     stream=True
#                 )

#                 current_response = ""
#                 for chunk in stream:
#                     if chunk.choices[0].delta.content is not None:
#                         content = chunk.choices[0].delta.content
#                         current_response += content
#                         yield f"data: {{'v': {repr(content)}}}\n\n"

#                 if not current_response.rstrip().endswith(('...', '…')):
#                     break

#                 # Prepare for continuation
#                 continuation_count += 1
#                 messages.append({"role": "assistant", "content": current_response})
#                 messages.append({
#                     "role": "user",
#                     "content": "Please continue where you left off."
#                 })

#             yield "data: [DONE]\n\n"

#         return StreamingResponse(
#             generate(),
#             media_type="text/event-stream"
#         )

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
