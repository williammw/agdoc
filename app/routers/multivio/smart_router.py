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

# Import the functionality from grok, together, and general routers
# Import the functionality from grok, together, and general routers with explicit naming
from app.routers.multivio.grok_router import router as grok_router, stream_chat_api as grok_stream_chat
from app.routers.multivio.general_router import router as general_router, stream_chat_api as general_stream_chat
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
    # Make messages optional with default empty list
    messages: Optional[List[ChatMessage]] = []
    model: Optional[str] = "grok-2-vision-1212"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    message: Optional[str] = None  # Added for compatibility with frontend
    # Add this field to match frontend request
    system_prompt: Optional[str] = None
    conversation_id: Optional[str] = None
    content_id: Optional[str] = None
    stream: bool = True

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


# Social media content patterns
SOCIAL_MEDIA_PATTERNS = [
    # Platform references
    r"(?i)\b(facebook|instagram|twitter|x\.com|threads|linkedin|tiktok|youtube)\b",

    # Content types
    r"(?i)\b(post|tweet|reel|story|caption|video)\b",

    # Actions
    r"(?i)(create|write|draft|schedule)\s+(a|an|my)?\s+(post|tweet|content)",
    r"(?i)social\s+media\s+(content|strategy|post|campaign)",

    # Engagement/metrics references
    r"(?i)(engagement|followers|likes|shares|comments)",

    # Marketing terms
    r"(?i)(hashtag|audience|content\s+calendar|brand\s+voice)",

    # Explicit requests
    r"(?i)help\s+(me|with)\s+(my)?\s+social\s+media",
]


# Helper function to detect intent
def detect_intent(message: str) -> str:
    """Detect the intent from the user message."""
    # Check for image generation intent
    for pattern in IMAGE_PATTERNS:
        if re.search(pattern, message):
            return "image_generation"

    # Check for social media intent
    for pattern in SOCIAL_MEDIA_PATTERNS:
        if re.search(pattern, message):
            return "social_media"

    # Default to general knowledge
    return "general_knowledge"

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
    """Streaming chat endpoint that routes requests based on detected intent."""
    try:
        # Add debug logging
        logger.info(
            f"Smart router received streaming request from user: {current_user['uid']}")

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
        logger.info(
            f">>> Smart router detected intent: {intent} for message: '{user_message}'")

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

            # Store message ID for later reference
            message_id = None

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

                    # Check if the table has an image_url column
                    check_image_url_query = """
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'mo_llm_messages' AND column_name = 'image_url'
                    """
                    has_image_url = await db.fetch_one(check_image_url_query)

                    # Add assistant message (placeholder)
                    message_id = str(uuid.uuid4())

                    # Determine columns and values based on schema
                    insert_fields = [
                        "id", "conversation_id", "role", "content", "created_at", "metadata"
                    ]

                    insert_values = {
                        "id": message_id,
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": f"Generating image of {prompt}...",
                        "created_at": now,
                        "metadata": json.dumps({
                            "is_image": True,
                            "image_task_id": task_id,
                            "prompt": prompt,
                            "status": "generating"
                        })
                    }

                    # Add image_url placeholder if the column exists
                    if has_image_url:
                        insert_fields.append("image_url")
                        # Will be updated when image is ready
                        insert_values["image_url"] = "pending"

                    # Build dynamic query
                    fields_str = ", ".join(insert_fields)
                    placeholders_str = ", ".join(
                        [f":{field}" for field in insert_fields])

                    insert_query = f"""
                    INSERT INTO mo_llm_messages (
                        {fields_str}
                    ) VALUES (
                        {placeholders_str}
                    )
                    """

                    await db.execute(query=insert_query, values=insert_values)
                except Exception as e:
                    logger.error(
                        f"Error recording messages in stream chat: {str(e)}")
                    # Continue even if message recording fails

            # Start background task
            background_tasks.add_task(
                generate_image_task,
                task_id,
                api_data,
                current_user["uid"],
                None,  # No folder_id for chat-based images
                db,
                conversation_id,
                message_id
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

        elif intent == "social_media":
            # IMPORTANT: Explicitly use the grok_router's stream_chat_api
            logger.info("Routing to social media handler (grok_router)")
            # Get the most recent user message
            for msg in reversed(request.messages):
                if msg.role.lower() == "user":
                    # Create a new ChatRequest with all required fields
                    request_with_message = ChatRequest(
                        messages=request.messages,
                        message=msg.content,
                        model=request.model if hasattr(
                            request, 'model') else "grok-1",
                        temperature=request.temperature if hasattr(
                            request, 'temperature') else 0.7,
                        max_tokens=request.max_tokens if hasattr(
                            request, 'max_tokens') else 1000,
                        stream=True,
                        conversation_id=getattr(
                            request, 'conversation_id', None),
                        content_id=getattr(request, 'content_id', None)
                    )
                    return await grok_stream_chat(request_with_message, current_user, db)

            return await grok_stream_chat(request, current_user, db)

        else:  # general_knowledge
            # IMPORTANT: Explicitly use the general_router's stream_chat_api
            logger.info(
                "Routing to general knowledge handler (general_router)")
            # Get the most recent user message
            for msg in reversed(request.messages):
                if msg.role.lower() == "user":
                    # Create a new ChatRequest with all required fields
                    request_with_message = ChatRequest(
                        messages=request.messages,
                        message=msg.content,
                        model=request.model if hasattr(
                            request, 'model') else "grok-1",
                        temperature=request.temperature if hasattr(
                            request, 'temperature') else 0.7,
                        max_tokens=request.max_tokens if hasattr(
                            request, 'max_tokens') else 1000,
                        stream=True,
                        conversation_id=getattr(
                            request, 'conversation_id', None),
                        content_id=getattr(request, 'content_id', None)
                    )
                    return await general_stream_chat(request_with_message, current_user, db)

            return await general_stream_chat(request, current_user, db)

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
        logger.info(f"Detected intent in smart_chat: {intent}")

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
                    "negative_prompt": None,
                    "size": "1024x1024",
                    "model": "flux",
                    "num_images": 1,
                    "folder_id": None,
                    "disable_safety_checker": True
                }),
                "status": "processing",
                "created_by": current_user["uid"],
                "created_at": now,
                "updated_at": now
            }

            await db.execute(query=query, values=values)

            # Store message ID for later reference
            message_id = None

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

                    # Check if the table has an image_url column
                    check_image_url_query = """
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'mo_llm_messages' AND column_name = 'image_url'
                    """
                    has_image_url = await db.fetch_one(check_image_url_query)

                    # Add assistant message (placeholder)
                    message_id = str(uuid.uuid4())

                    # Determine columns and values based on schema
                    insert_fields = [
                        "id", "conversation_id", "role", "content", "created_at", "metadata"
                    ]

                    insert_values = {
                        "id": message_id,
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": f"Generating image for: {prompt}...",
                        "created_at": now,
                        "metadata": json.dumps({
                            "is_image": True,
                            "image_task_id": task_id,
                            "prompt": prompt,
                            "status": "generating"
                        })
                    }

                    # Add image_url placeholder if the column exists
                    if has_image_url:
                        insert_fields.append("image_url")
                        # Will be updated when image is ready
                        insert_values["image_url"] = "pending"

                    # Build dynamic query
                    fields_str = ", ".join(insert_fields)
                    placeholders_str = ", ".join(
                        [f":{field}" for field in insert_fields])

                    insert_query = f"""
                    INSERT INTO mo_llm_messages (
                        {fields_str}
                    ) VALUES (
                        {placeholders_str}
                    )
                    """

                    await db.execute(query=insert_query, values=insert_values)
                except Exception as e:
                    logger.error(
                        f"Error recording messages in smart chat: {str(e)}")
                    # Continue even if message recording fails

            # Start background task
            background_tasks.add_task(
                generate_image_task,
                task_id,
                api_data,
                current_user["uid"],
                None,  # No folder_id for chat-based images
                db,
                conversation_id,
                message_id
            )

            return SmartResponse(
                detected_intent="image_generation",
                result=ImageGenerationResult(
                    task_id=task_id,
                    status="processing"
                )
            )

        elif intent == "social_media":
            # Forward to Grok API for social media content
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
                    error_data = response.json() if response.content else {
                        "error": "Unknown error"}
                    error_message = error_data.get("error", {}).get(
                        "message", "API call failed")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=error_message
                    )

                result = response.json()
                content = result.get("choices", [{}])[0].get(
                    "message", {}).get("content", "")

                return SmartResponse(
                    detected_intent="social_media",
                    result=TextGenerationResult(
                        content=content
                    )
                )

        else:  # general_knowledge
            # Forward to Grok API for general knowledge
            headers = {
                "x-api-key": GROK_API_KEY,
                "Content-Type": "application/json"
            }

            # Add the appropriate system prompt for general knowledge
            has_system_message = False
            messages_list = list(request.messages)

            for msg in messages_list:
                if msg.role.lower() == "system":
                    has_system_message = True
                    break

            if not has_system_message:
                # Add general knowledge system prompt from general_router
                from app.routers.multivio.general_router import DEFAULT_SYSTEM_PROMPT
                system_message = ChatMessage(
                    role="system", content=DEFAULT_SYSTEM_PROMPT)
                messages_list.insert(0, system_message)

            grok_request = {
                "messages": messages_list,
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
                    error_data = response.json() if response.content else {
                        "error": "Unknown error"}
                    error_message = error_data.get("error", {}).get(
                        "message", "API call failed")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=error_message
                    )

                result = response.json()
                content = result.get("choices", [{}])[0].get(
                    "message", {}).get("content", "")

                return SmartResponse(
                    detected_intent="general_knowledge",
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

        # Store message ID for later reference
        message_id = None

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
                message_id = str(uuid.uuid4())

                # Check if the table has an image_url column
                check_image_url_query = """
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'mo_llm_messages' AND column_name = 'image_url'
                """
                has_image_url = await db.fetch_one(check_image_url_query)

                if has_image_url:
                    # If image_url column exists, include it in the insert
                    await db.execute(
                        """
                        INSERT INTO mo_llm_messages (
                            id, conversation_id, role, content, created_at, metadata, image_url
                        ) VALUES (
                            :id, :conversation_id, :role, :content, :created_at, :metadata, :image_url
                        )
                        """,
                        {
                            "id": message_id,
                            "conversation_id": conversation_id,
                            "role": "assistant",
                            "content": f"Generating image for: {prompt}...",
                            "created_at": now,
                            "metadata": json.dumps({
                                "is_image": True,
                                "image_task_id": task_id,
                                "prompt": prompt,
                                "status": "generating"
                            }),
                            "image_url": "pending"  # Will be updated when image is ready
                        }
                    )
                else:
                    # Otherwise, use the original columns
                    await db.execute(
                        """
                        INSERT INTO mo_llm_messages (
                            id, conversation_id, role, content, created_at, metadata
                        ) VALUES (
                            :id, :conversation_id, :role, :content, :created_at, :metadata
                        )
                        """,
                        {
                            "id": message_id,
                            "conversation_id": conversation_id,
                            "role": "assistant",
                            "content": f"Generating image for: {prompt}...",
                            "created_at": now,
                            "metadata": json.dumps({
                                "is_image": True,
                                "image_task_id": task_id,
                                "prompt": prompt,
                                "status": "generating"
                            })
                        }
                    )
            except Exception as e:
                logger.error(f"Error recording messages: {str(e)}")
                # Continue even if message recording fails

        # Start background task with message info
        background_tasks.add_task(
            generate_image_task,
            task_id,
            api_data,
            current_user["uid"],
            None,  # No folder_id for chat-based images
            db,
            conversation_id,  # Pass conversation_id
            message_id       # Pass message_id
        )

        # This section has been moved into the code above before starting the background task

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
