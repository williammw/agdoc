from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from app.dependencies import get_current_user, get_database
from databases import Database
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
import os
import httpx
import logging
# Add streaming support
from fastapi.responses import StreamingResponse
import json
import re
from datetime import datetime, timezone
import uuid
import asyncio

# Import the functionality from grok and together routers
from app.routers.multivio.grok_router import router as grok_router, stream_chat_api
from app.routers.multivio.together_router import call_together_api, generate_image_task

router = APIRouter(tags=["smart"])
logger = logging.getLogger(__name__)

# Environment variables
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")

# Models for request/response
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = "grok-1"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    message: Optional[str] = None  # Added for compatibility with frontend
    conversation_id: Optional[str] = None  # Add conversation_id field
    content_id: Optional[str] = None  # Add content_id field
    stream: bool = True  # Add stream field

class ImageGenerationResult(BaseModel):
    type: str = "image"
    task_id: str
    status: str = "processing"

class TextGenerationResult(BaseModel):
    type: str = "text"
    content: str
    
class ErrorResult(BaseModel):
    type: str = "error"
    error: str

class SmartResponse(BaseModel):
    result: Union[ImageGenerationResult, TextGenerationResult, ErrorResult]
    detected_intent: str


# Intent detection patterns
IMAGE_PATTERNS = [
    r"(?i)create\s+(?:an\s+)?image",  # More general pattern without "of"
    r"(?i)generate\s+(?:an\s+)?image", 
    r"(?i)show\s+(?:me\s+)?(?:an\s+)?image",
    r"(?i)make\s+(?:an\s+)?image",
    r"(?i)draw\s+(?:an\s+)?image",
    r"(?i)create\s+(?:a\s+)?picture",
    r"(?i)generate\s+(?:a\s+)?picture",
    r"(?i)visualize",
    r"(?i)illustrate",
    r"(?i)image\s+of",  # Even more general pattern
    r"(?i)picture\s+of",
]

# Helper function to detect intent
def detect_intent(message: str) -> str:
    """Detect the intent from the user message."""
    # Check for image generation intent
    for pattern in IMAGE_PATTERNS:
        if re.search(pattern, message):
            return "image_generation"
    
    # Default to text generation
    return "text_generation"

# Helper function to extract image prompt
def extract_image_prompt(message: str) -> str:
    """Extract the actual image prompt from the user message."""
    for pattern in IMAGE_PATTERNS:
        match = re.search(pattern, message)
        if match:
            # Extract everything after the pattern
            prompt_start = match.end()
            return message[prompt_start:].strip()
    
    # If no pattern matches, return the original message
    return message

@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Streaming chat endpoint that can detect and handle image generation requests."""
    try:
        # Get the user message - check both message and messages array
        user_message = ""
        
        if hasattr(request, 'message') and request.message:
            # Direct message field (sent by frontend)
            user_message = request.message
        else:
            # Get the last user message from messages array
            user_message = next((msg.content for msg in reversed(request.messages) 
                                if msg.role.lower() == "user"), "")
        
        logger.info(f"Processing message in stream_chat: '{user_message}'")
        
        if not user_message:
            return StreamingResponse(
                content=iter(["No user message found"]),
                media_type="text/plain"
            )
        
        # Detect intent
        intent = detect_intent(user_message)
        
        if intent == "image_generation":
            # For image generation, don't stream but return a special response
            # Extract image prompt
            prompt = extract_image_prompt(user_message)
            
            # Create a task ID
            task_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            
            # Prepare request data for together.ai
            api_data = {
                "prompt": prompt,
                "model": "flux",
                "n": 1,  # Generate one image for chat
                "disable_safety_checker": True  # Add safety checker option
            }
            
            # Store the task in the database
            query = """
            INSERT INTO mo_ai_tasks (
                id, type, parameters, status, created_by, created_at, updated_at
            ) VALUES (
                :id, :type, :parameters, :status, :created_by, :created_at, :updated_at
            )
            """
            
            values = {
                "id": task_id,
                "type": "image_generation",
                "parameters": json.dumps({
                    "prompt": prompt,
                    "model": "flux",
                    "num_images": 1,
                    "disable_safety_checker": True
                }),
                "status": "processing",
                "created_by": current_user["uid"],
                "created_at": now,
                "updated_at": now
            }
            
            await db.execute(query=query, values=values)
            
            # Start background task
            background_tasks.add_task(
                generate_image_task,
                task_id,
                api_data,
                current_user["uid"],
                None,  # No folder_id for chat-based images
                db
            )
            
            # Return a special message that can be interpreted by the frontend
            response_data = {
                "is_image_request": True,
                "task_id": task_id,
                "message": "Generating image of " + prompt
            }
            
            return StreamingResponse(
                content=iter([json.dumps(response_data)]),
                media_type="application/json"
            )
        
        else:  # text_generation - forward to Grok API
            # Extract message from request.messages if needed
            if hasattr(request, 'messages') and len(request.messages) > 0:
                # Get the most recent user message
                for msg in reversed(request.messages):
                    if msg.role.lower() == "user":
                        # Create a new ChatRequest with all required fields
                        request_with_message = ChatRequest(
                            messages=request.messages,
                            message=msg.content,
                            model=request.model if hasattr(request, 'model') else "grok-1",
                            temperature=request.temperature if hasattr(request, 'temperature') else 0.7,
                            max_tokens=request.max_tokens if hasattr(request, 'max_tokens') else 1000,
                            stream=True,
                            conversation_id=getattr(request, 'conversation_id', None),
                            content_id=getattr(request, 'content_id', None)
                        )
                        return await stream_chat_api(request_with_message, current_user, db)
        
        return await stream_chat_api(request, current_user, db)
        
    except Exception as e:
        logger.error(f"Error in stream chat: {str(e)}")
        return StreamingResponse(
            content=iter([f"Error: {str(e)}"]),
            media_type="text/plain"
        )

@router.post("/chat", response_model=SmartResponse)
async def smart_chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Smart chat endpoint that detects intent and routes to appropriate service."""
    try:
        # Get the user message - check both message and messages array
        user_message = ""
        
        if hasattr(request, 'message') and request.message:
            # Direct message field (sent by frontend)
            user_message = request.message
        else:
            # Get the last user message from messages array
            user_message = next((msg.content for msg in reversed(request.messages) 
                                if msg.role.lower() == "user"), "")
        
        if not user_message:
            return SmartResponse(
                detected_intent="unknown",
                result=ErrorResult(error="No user message found")
            )
        
        # Detect intent
        intent = detect_intent(user_message)
        
        if intent == "image_generation":
            # Extract image prompt
            prompt = extract_image_prompt(user_message)
            
            # Create a task ID
            task_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            
            # Prepare request data for together.ai
            api_data = {
                "prompt": prompt,
                "model": "flux",
                "n": 1  # Generate one image for chat
            }
            
            # Store the task in the database
            query = """
            INSERT INTO mo_ai_tasks (
                id, type, parameters, status, created_by, created_at, updated_at
            ) VALUES (
                :id, :type, :parameters, :status, :created_by, :created_at, :updated_at
            )
            """
            
            values = {
                "id": task_id,
                "type": "image_generation",
                "parameters": json.dumps({
                    "prompt": prompt,
                    "model": "flux",
                    "num_images": 1,
                    "disable_safety_checker": True
                }),
                "status": "processing",
                "created_by": current_user["uid"],
                "created_at": now,
                "updated_at": now
            }
            
            await db.execute(query=query, values=values)
            
            # Start background task
            background_tasks.add_task(
                generate_image_task,
                task_id,
                api_data,
                current_user["uid"],
                None,  # No folder_id for chat-based images
                db
            )
            
            return SmartResponse(
                detected_intent="image_generation",
                result=ImageGenerationResult(
                    task_id=task_id,
                    status="processing"
                )
            )
        
        else:  # text_generation
            # Forward to Grok API
            headers = {
                "x-api-key": GROK_API_KEY,
                "Content-Type": "application/json"
            }
            
            grok_request = {
                "messages": request.messages,
                "model": request.model,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers=headers,
                    json=grok_request,
                    timeout=60.0
                )
                
                if response.status_code != 200:
                    error_data = response.json() if response.content else {"error": "Unknown error"}
                    error_message = error_data.get("error", {}).get("message", "API call failed")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=error_message
                    )
                
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                return SmartResponse(
                    detected_intent="text_generation",
                    result=TextGenerationResult(
                        content=content
                    )
                )
    
    except Exception as e:
        logger.error(f"Error in smart chat: {str(e)}")
        return SmartResponse(
            detected_intent="error",
            result=ErrorResult(
                error=str(e)
            )
        )

@router.post("/generate-image-from-text")
async def generate_image_from_text(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Dedicated endpoint for generating images from text"""
    try:
        # Extract the user message
        user_message = ""
        if hasattr(request, 'message') and request.message:
            user_message = request.message
        else:
            user_message = next((msg.content for msg in reversed(request.messages) 
                               if msg.role.lower() == "user"), "")
        
        if not user_message:
            return JSONResponse(
                status_code=400, 
                content={"error": "No text prompt provided"}
            )
        
        # Create a task ID
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Use the entire message as the prompt (don't try to extract)
        prompt = user_message
        
        # Prepare request data for together.ai
        api_data = {
            "prompt": prompt,
            "model": "flux",
            "n": 1,  # Generate one image for chat
            "disable_safety_checker": True  # Add safety checker option
        }
        
        # Store the task in the database
        query = """
        INSERT INTO mo_ai_tasks (
            id, type, parameters, status, created_by, created_at, updated_at
        ) VALUES (
            :id, :type, :parameters, :status, :created_by, :created_at, :updated_at
        )
        """
        
        values = {
            "id": task_id,
            "type": "image_generation",
            "parameters": json.dumps({
                "prompt": prompt,
                "model": "flux",
                "num_images": 1,
            }),
            "status": "processing",
            "created_by": current_user["uid"],
            "created_at": now,
            "updated_at": now
        }
        
        await db.execute(query=query, values=values)
        
        # Start background task
        background_tasks.add_task(
            generate_image_task,
            task_id,
            api_data,
            current_user["uid"],
            None,  # No folder_id for chat-based images
            db
        )
        
        # Record the message in conversation if conversation_id is provided
        conversation_id = getattr(request, 'conversation_id', None)
        if conversation_id:
            try:
                # Add user message
                await db.execute(
                    """
                    INSERT INTO mo_llm_messages (
                        id, conversation_id, role, content, created_at
                    ) VALUES (
                        :id, :conversation_id, :role, :content, :created_at
                    )
                    """,
                    {
                        "id": str(uuid.uuid4()),
                        "conversation_id": conversation_id,
                        "role": "user",
                        "content": user_message,
                        "created_at": now
                    }
                )
                
                # Add assistant message (placeholder)
                await db.execute(
                    """
                    INSERT INTO mo_llm_messages (
                        id, conversation_id, role, content, created_at
                    ) VALUES (
                        :id, :conversation_id, :role, :content, :created_at
                    )
                    """,
                    {
                        "id": str(uuid.uuid4()),
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": f"Generating image for: {prompt}...",
                        "created_at": now
                    }
                )
            except Exception as e:
                logger.error(f"Error recording messages: {str(e)}")
                # Continue even if message recording fails
        
        return JSONResponse({
            "is_image_request": True,
            "task_id": task_id,
            "message": "Generating image from text"
        })
        
    except Exception as e:
        logger.error(f"Error generating image: {str(e)}")
        return JSONResponse(
            status_code=500, 
            content={"error": f"Image generation failed: {str(e)}"}
        )

@router.get("/chat/task/{task_id}")
async def get_generation_task_status(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Check the status of a generation task."""
    try:
        query = """
        SELECT id, type, parameters, status, result, error, 
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE id = :task_id AND created_by = :user_id
        """
        
        task = await db.fetch_one(
            query=query,
            values={
                "task_id": task_id,
                "user_id": current_user["uid"]
            }
        )
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task_dict = dict(task)
        
        if task_dict["status"] == "completed" and task_dict["result"]:
            # Parse the result JSON
            result_data = json.loads(task_dict["result"])
            return {
                "status": "completed",
                "result": result_data,
            }
        elif task_dict["status"] == "failed":
            return {
                "status": "failed",
                "error": task_dict.get("error", "Unknown error")
            }
        else:
            # Still processing
            return {
                "status": task_dict["status"]
            }
            
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
