"""
Pipeline Router - Implements the Pipeline and Command pattern for multi-intent processing.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request, Header, Cookie
from fastapi.responses import StreamingResponse, JSONResponse
from app.dependencies import get_current_user, get_database
from app.utils.idempotency import idempotent
from databases import Database
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, validator
import uuid
import json
import os
import logging
import asyncio
import httpx
from datetime import datetime, timezone
import traceback
import re
from firebase_admin import auth as firebase_auth

from .commands.base import Pipeline, CommandFactory
# from .commands.intent_detector import detect_intents, MultilingualIntentDetector
from .commands.intent_detector_v2 import predict_intents
# Import commands to register them with the factory - hiding web search and puppeteer
# from .commands.web_search_command import WebSearchCommand
# from .commands.puppeteer_command import PuppeteerCommand
from .commands.image_generation_command import ImageGenerationCommand
from .commands.social_media_command import SocialMediaCommand
from .commands.general_knowledge_command import GeneralKnowledgeCommand
from .commands.conversation_command import ConversationCommand
from .commands.calculation_command import CalculationCommand


# Configure logging
logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter()

# Models for request/response


class ChatMessage(BaseModel):
    role: str
    content: str


class MultiIntentChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    chat_id: Optional[str] = None
    message: str
    model: Optional[str] = "grok-3-mini-beta"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    stream: bool = True
    reasoning_effort: Optional[str] = "high"
    
    model_config = {
        'protected_namespaces': ()
    }


# Add enhanced request model
class StreamChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    chat_id: Optional[str] = None
    content_name: Optional[str] = None
    message: str
    message_type: str = "text"  # "text", "image", "social", "reasoning"
    stream: bool = True
    options: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    model_config = {
        'protected_namespaces': (),
        'json_schema_extra': {
            "example": {
                "conversation_id": "optional-for-existing-chats",
                "chat_id": "optional-content-id",
                "content_name": "New Chat Title",
                "message": "Hello, how can you help me today?",
                "message_type": "text",
                "options": {
                    "perform_web_search": False,
                    "image_model": None,
                    "social_platforms": None,
                    "reasoning_model": None,
                    "unfiltered": False
                }
            }
        }
    }


class CommandResult(BaseModel):
    type: str
    content: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    
    model_config = {
        'protected_namespaces': ()
    }


class MultiIntentResponse(BaseModel):
    conversation_id: str
    message_id: str
    detected_intents: List[str]
    results: List[CommandResult]
    content: str
    
    model_config = {
        'protected_namespaces': ()
    }


class CreateConversationRequest(BaseModel):
    chat_id: str
    title: Optional[str] = None
    model: Optional[str] = "grok-2-1212"
    
    model_config = {
        'protected_namespaces': ()
    }


class Conversation(BaseModel):
    id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime
    chat_id: Optional[str] = None
    user_id: str
    message_count: int = 0
    
    model_config = {
        'protected_namespaces': ()
    }


class GetOrCreateConversationRequest(BaseModel):
    chat_id: str
    model_id: Optional[str] = "grok-2-1212"
    title: Optional[str] = None
    
    model_config = {
        'protected_namespaces': ()
    }
    

async def get_or_create_conversation(chat_id: str, user_id: str, model_id: str, title: str, db: Database):
    """Get or create a conversation with database-level uniqueness"""
    logger.info(f"get_or_create_conversation starting: chat_id={chat_id}, user_id={user_id}, model_id={model_id}, title={title}")
    try:
        # First check if the content exists in mo_chat
        content_check_query = "SELECT uuid FROM mo_chat WHERE uuid = :uuid"
        content_exists = await db.fetch_one(query=content_check_query, values={"uuid": chat_id})
        
        if not content_exists:
            logger.warning(f"Content ID {chat_id} does not exist in mo_chat table")
            # Try to create content entry automatically
            try:
                # Create a new content entry
                route = f"auto-{uuid.uuid4().hex[:8]}"  # Generate unique route
                content_insert = """
                INSERT INTO mo_chat 
                (uuid, firebase_uid, name, description, route, status) 
                VALUES 
                (:uuid, :firebase_uid, :name, :description, :route, 'draft')
                ON CONFLICT (uuid) DO NOTHING
                RETURNING uuid
                """
                
                content_values = {
                    "uuid": chat_id,
                    "firebase_uid": user_id,
                    "name": f"Auto-created Content {chat_id[:8]}",
                    "description": "Automatically created content for conversation",
                    "route": route
                }
                
                content_result = await db.fetch_one(content_insert, content_values)
                if content_result:
                    logger.info(f"Created missing content entry: {chat_id}")
                else:
                    logger.warning(f"Failed to create content entry for {chat_id}")
            except Exception as content_error:
                logger.error(f"Error creating content entry: {str(content_error)}")
                # Continue anyway - the transaction below will fail if content doesn't exist
        
        async with db.transaction():
            # Try to get an existing conversation
            query = """
            SELECT id FROM mo_llm_conversations 
            WHERE chat_id = :chat_id AND user_id = :user_id
            """
            existing = await db.fetch_one(query=query, values={"chat_id": chat_id, "user_id": user_id})

            if existing:
                logger.info(
                    f"Found existing conversation {existing['id']} for content {chat_id}, user {user_id}")
                return existing["id"]

            # Create new conversation if none exists
            new_id = str(uuid.uuid4())
            insert_query = """
            INSERT INTO mo_llm_conversations 
            (id, user_id, chat_id, model_id, title)
            VALUES (:id, :user_id, :chat_id, :model_id, :title)
            RETURNING id
            """
            values = {
                "id": new_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "model_id": model_id,
                "title": title or f"Conversation about {chat_id}"
            }

            result = await db.fetch_one(query=insert_query, values=values)
            logger.info(
                f"Created new conversation {result['id']} for content {chat_id}, user {user_id}")
            return result["id"]
    except Exception as e:
        logger.error(f"Error in get_or_create_conversation: {str(e)}")
        # If there was an error, try to get again (might be a concurrent insert)
        query = """
        SELECT id FROM mo_llm_conversations 
        WHERE chat_id = :chat_id AND user_id = :user_id
        """
        existing = await db.fetch_one(query=query, values={"chat_id": chat_id, "user_id": user_id})

        if existing:
            logger.info(f"Recovered conversation {existing['id']} after error")
            return existing["id"]

        # If recovery failed, re-raise
        raise


# Add helper functions
async def create_new_content(db: Database, user_id: str, content_name: str) -> str:
    """Create new content and return its ID, checks first if similar content exists"""
    # First check if the user already has content with a similar name
    similarity_query = """
    SELECT uuid FROM mo_chat 
    WHERE firebase_uid = :user_id AND name = :content_name
    LIMIT 1
    """
    
    existing = await db.fetch_one(
        query=similarity_query,
        values={
            "user_id": user_id,
            "content_name": content_name
        }
    )
    
    if existing:
        logger.info(f"Found existing content with same name: {existing['uuid']}")
        return str(existing["uuid"])
    
    # Create new content if none exists
    chat_id = str(uuid.uuid4())
    route = f"auto-{uuid.uuid4().hex[:8]}"  # Generate unique route
    
    query = """
    INSERT INTO mo_chat 
    (uuid, firebase_uid, name, description, route, status) 
    VALUES 
    (:uuid, :firebase_uid, :name, :description, :route, 'draft')
    RETURNING uuid
    """
    
    values = {
        "uuid": chat_id,
        "firebase_uid": user_id,
        "name": content_name or "New Chat",
        "description": "Conversation content",
        "route": route
    }
    
    try:
        result = await db.fetch_one(query=query, values=values)
        return str(result["uuid"])
    except Exception as e:
        # If insertion fails, try to find the content again (race condition)
        logger.warning(f"Error creating content, checking if it exists: {str(e)}")
        existing = await db.fetch_one(
            query=similarity_query,
            values={
                "user_id": user_id,
                "content_name": content_name
            }
        )
        
        if existing:
            return str(existing["uuid"])
        else:
            # If still not found, try to create with a slightly modified name
            modified_name = f"{content_name} {datetime.now().strftime('%H:%M:%S')}"
            chat_id = str(uuid.uuid4())
            
            values["uuid"] = chat_id
            values["name"] = modified_name
            values["route"] = f"auto-{uuid.uuid4().hex[:8]}"
            
            result = await db.fetch_one(query=query, values=values)
            return str(result["uuid"])

async def create_new_conversation(db: Database, user_id: str, chat_id: Optional[str] = None, model_id: str = "grok-3-mini-beta", title: Optional[str] = None) -> str:
    """Create new conversation and return its ID, or return existing ID if one exists"""
    
    # First check if a conversation already exists for this user and content
    if chat_id:
        check_query = """
        SELECT id FROM mo_llm_conversations
        WHERE user_id = :user_id AND chat_id = :chat_id
        ORDER BY created_at DESC LIMIT 1
        """
        
        existing = await db.fetch_one(
            query=check_query,
            values={
                "user_id": user_id,
                "chat_id": chat_id
            }
        )
        
        if existing:
            logger.info(f"Reusing existing conversation {existing['id']} for content {chat_id} and user {user_id}")
            return str(existing["id"])
    
    # If no existing conversation or no chat_id, create a new one
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    query = """
    INSERT INTO mo_llm_conversations (
        id, user_id, title, model_id, created_at, updated_at, chat_id
    ) VALUES (
        :id, :user_id, :title, :model, :created_at, :updated_at, :chat_id
    ) RETURNING id
    """

    values = {
        "id": conversation_id,
        "user_id": user_id,
        "title": title or "New Conversation",
        "model": model_id,
        "created_at": now,
        "updated_at": now,
        "chat_id": chat_id
    }

    result = await db.fetch_one(query=query, values=values)
    return str(result["id"])


async def get_user(request: Request, db: Database = Depends(get_database)):
    """Get current user, or fallback to creating a temporary valid user"""
    try:
        # Try to extract Authorization header
        authorization = request.headers.get("Authorization")

        # If we have an Authorization header, use the standard get_current_user
        if authorization and authorization.startswith("Bearer ") and authorization.split("Bearer ")[1] not in ["null", "undefined", ""]:
            from app.dependencies import get_current_user
            try:
                return await get_current_user(authorization=authorization, db=db)
            except Exception as e:
                logger.error(
                    f"Error using standard get_current_user: {str(e)}")
                # Fall through to our fallback

        # Check if user is already in the session
        session_user = request.session.get("user")
        if session_user:
            return session_user

        # If there's a token cookie, try that
        token = request.cookies.get("token")
        if token and token not in ["null", "undefined", ""]:
            try:
                decoded_token = firebase_auth.verify_id_token(
                    token, check_revoked=True)
                uid = decoded_token['uid']
                firebase_user = firebase_auth.get_user(uid)

                # Check the database
                query = "SELECT id, email, username FROM mo_user_info WHERE id = :uid"
                user = await db.fetch_one(query=query, values={"uid": uid})

                if user:
                    user_dict = dict(user)
                    user_dict['uid'] = uid
                    # Store in session for future use
                    request.session["user"] = user_dict
                    return user_dict
            except Exception as e:
                logger.error(f"Error with token cookie: {str(e)}")
                # Fall through to our fallback

        # Last resort: find a valid existing user
        try:
            # Get the first active user from the database as a fallback
            query = """
            SELECT id, email, username 
            FROM mo_user_info 
            WHERE is_active = true 
            LIMIT 1
            """
            user = await db.fetch_one(query=query)

            if user:
                user_dict = dict(user)
                user_dict['uid'] = user_dict['id']  # Ensure uid is set
                # Store in session for future use
                request.session["user"] = user_dict
                logger.warning(f"Using fallback user: {user_dict['id']}")
                return user_dict
        except Exception as e:
            logger.error(f"Error finding fallback user: {str(e)}")

        # If we got here, we couldn't find any valid user
        raise HTTPException(
            status_code=401,
            detail="Authentication failed and no fallback user available"
        )

    except Exception as e:
        logger.error(f"Error in get_user: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=401, detail="Authentication failed")


async def create_conversation(db: Database, user_id: str, title: str = None, chat_id: Optional[str] = None, model: str = "grok-2-1212"):
    """Create a new conversation"""
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Default title if none provided
    if not title:
        title = "Multi-Intent Conversation"

    # First check if the user exists in mo_user_info
    check_query = "SELECT id FROM mo_user_info WHERE id = :user_id"
    user_exists = await db.fetch_one(query=check_query, values={"user_id": user_id})

    if not user_exists:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create conversation: User {user_id} does not exist in the database"
        )

    query = """
    INSERT INTO mo_llm_conversations (
        id, user_id, title, model_id, created_at, updated_at, chat_id
    ) VALUES (
        :id, :user_id, :title, :model, :created_at, :updated_at, :chat_id
    ) RETURNING id
    """

    values = {
        "id": conversation_id,
        "user_id": user_id,
        "title": title,
        "model": model,
        "created_at": now,
        "updated_at": now,
        "chat_id": chat_id
    }

    await db.execute(query=query, values=values)
    return conversation_id


async def get_conversation_by_id(db: Database, conversation_id: str):
    """Get a conversation by ID"""
    query = """
    SELECT 
        id, user_id, title, model_id as model, 
        created_at, updated_at, chat_id,
        (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count
    FROM mo_llm_conversations 
    WHERE id = :conversation_id
    """

    result = await db.fetch_one(query=query, values={"conversation_id": conversation_id})
    if not result:
        return None

    return dict(result)


async def get_conversation_by_content_id(db: Database, chat_id: str, user_id: str):
    """Get a conversation by content ID"""
    query = """
    SELECT 
        id, user_id, title, model_id as model, 
        created_at, updated_at, chat_id,
        (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count
    FROM mo_llm_conversations 
    WHERE chat_id = :chat_id
    AND user_id = :user_id
    ORDER BY created_at DESC
    LIMIT 1
    """

    result = await db.fetch_one(
        query=query,
        values={
            "chat_id": chat_id,
            "user_id": user_id
        }
    )
    return dict(result) if result else None


async def format_pipeline_response(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format the final response from pipeline context.
    """
    response = {
        "conversation_id": context.get("conversation_id"),
        "detected_intents": list(context.get("intents", {}).keys()),
        "results": context.get("results", [])
    }

    # Add content from general knowledge if available
    if "general_knowledge_content" in context:
        response["content"] = context["general_knowledge_content"]
    else:
        # Combine results from different commands
        content_sections = []
        for result in context.get("results", []):
            if result.get("type") == "image_generation" and result.get("prompt"):
                content_sections.append(
                    f"## Image Generation\n\nI've generated an image based on: '{result.get('prompt')}'")
            elif result.get("type") == "social_media" and result.get("content"):
                platforms = result.get("platforms", [])
                content_sections.append(
                    f"## Social Media Content for {', '.join(platforms)}\n\n{result.get('content')}")
            elif result.get("type") == "calculation" and result.get("content"):
                content_sections.append(result.get("content"))

        response["content"] = "\n\n".join(
            content_sections) or "I processed your request but couldn't generate a meaningful response."

    return response


async def process_streaming_response(context: Dict[str, Any]):
    """
    Process the pipeline response for streaming with a consistent format.
    All intent types (image_generation, social_media, etc.) will follow the same pattern.
    Fixed to stream chunks in real-time as they arrive instead of collecting all first.
    """
    logger.info(
        f"__stream__chat Starting streaming response processing for context: {context.get('conversation_id')}")
        
    # Initialize image tracking variables
    image_generation_tasks = []
    has_image_generation = False
    db = context.get("db")
    
    # Check if we have any image generation tasks
    for result in context.get("results", []):
        if result.get("type") == "image_generation":
            has_image_generation = True
            if not result.get("image_url"):  # Only track non-reused images
                image_generation_tasks.append({
                    "task_id": result.get("task_id"),
                    "prompt": result.get("prompt"),
                    "completed": False
                })

    # First yield initialization information if we have new IDs
    if context.get("conversation_id") or context.get("chat_id"):
        init_message = {
            "type": "initialization",
            "data": {
                "conversation_id": context.get("conversation_id"),
                "chat_id": context.get("chat_id"),
                # Add this line to include message_id
                "message_id": context.get("message_id")
            }
        }
        logger.info(
            f"__stream__shit Sending initialization message: {init_message}")
        yield f"data: {json.dumps(init_message)}\n\n"
        await asyncio.sleep(0.05)

    # Yield detected intents
    intents_message = {
        "type": "intents",
        "data": {
            "intents": list(context.get("intents", {}).keys())
        }
    }
    logger.info(
        f"__stream__shit Sending intents: {intents_message['data']['intents']}")
    yield f"data: {json.dumps(intents_message)}\n\n"
    await asyncio.sleep(0.05)
    
    # Direct handling for image generation mode
    image_generation_mode = context.get("image_generation_mode", False) or context.get("message_type") == "image"
    
    # Track which results have been processed
    processed_results = []

    # Process each result individually with consistent structure
    for result in context.get("results", []):
        result_type = result.get("type", "unknown")

        # Skip general_knowledge as it will be part of the content stream
        if result_type == "general_knowledge":
            continue

        # Create a standardized result message
        result_message = {
            "type": result_type,
            "result_type": result_type,  # For backward compatibility
            "result": result,            # For backward compatibility
            "data": result
        }

        # Special handling for image generation to indicate polling is needed
        if result_type == "image_generation":
            # Check if we already have an image URL (from reused image)
            if "image_url" in result and result["image_url"]:
                result_message["status"] = "completed"
                # Make sure the image URL is prominently available
                result_message["image_url"] = result["image_url"]
                result_message["data"]["image_url"] = result["image_url"]
                result_message["result"]["image_url"] = result["image_url"]
                # Include image_id if available
                if "image_id" in result:
                    result_message["image_id"] = result["image_id"]
                    result_message["data"]["image_id"] = result["image_id"]
                    result_message["result"]["image_id"] = result["image_id"]
                # Include reused flag if this is a reused image
                if result.get("reused"):
                    result_message["reused"] = True
                    result_message["data"]["reused"] = True
                    result_message["result"]["reused"] = True
                    
                # For image generation mode, emit an image_ready event directly
                if image_generation_mode:
                    image_ready_event = {
                        "type": "image_ready",
                        "data": {
                            "task_id": result.get("task_id"),
                            "image_url": result["image_url"],
                            "image_id": result.get("image_id"),
                            "prompt": result.get("prompt")
                        }
                    }
                    yield f"data: {json.dumps(image_ready_event)}\n\n"
                    await asyncio.sleep(0.05)
            else:
                # No image URL yet, set needs_polling
                result_message["status"] = "needs_polling"
                
                # Get poll endpoint with fallback
                poll_endpoint = result.get("poll_endpoint") or f"/api/v1/media/image-status/{result.get('task_id')}"
                
                # Add consistency check for poll_endpoint
                if not poll_endpoint.startswith("/"):
                    poll_endpoint = f"/{poll_endpoint}"
                    
                result_message["poll_endpoint"] = poll_endpoint
                
                # Include additional info about prompt
                if "prompt" in result:
                    result_message["prompt"] = result["prompt"]
                
                # For image generation mode, emit an image_generating event directly
                if image_generation_mode:
                    image_generating_event = {
                        "type": "image_generating",
                        "data": {
                            "task_id": result.get("task_id"),
                            "prompt": result.get("prompt")
                        }
                    }
                    yield f"data: {json.dumps(image_generating_event)}\n\n"
                    await asyncio.sleep(0.05)
        else:
            result_message["status"] = "complete"

        # Add current command info for backward compatibility
        if "current_command" in context:
            result_message["current_command"] = context["current_command"]

        # Send result information
        yield f"data: {json.dumps(result_message)}\n\n"
        await asyncio.sleep(0.05)

        # Send a completion signal for this specific result (backward compatibility)
        yield f"data: {json.dumps({'result_complete': result_type})}\n\n"
        await asyncio.sleep(0.05)

        # Add to processed results
        processed_results.append(result_type)

    # Check if we have a streaming generator from general_knowledge_command
    if "_streaming_generator" in context and context["_streaming_generator"]:
        # Initialize variables
        content_chunks = []
        reasoning_chunks = []
        has_sent_reasoning_start = False
        has_sent_content_start = False
        content_complete = False
        chunk_count = 0

        try:
            # Stream chunks in real-time as they arrive
            logger.info(
                f"__stream__shit Starting real-time streaming of generator output")

            async for chunk in context["_streaming_generator"]:
                chunk_count += 1
                chunk_type = chunk.get("type", "content")

                # Process different chunk types in real-time
                if chunk_type == "reasoning":
                    reasoning_text = chunk.get("content", "")
                    reasoning_chunks.append(reasoning_text)

                    # Send reasoning start signal if first reasoning chunk
                    if not has_sent_reasoning_start:
                        logger.info(
                            f"__stream__shit Starting reasoning content streaming")
                        yield f"data: {json.dumps({'type': 'reasoning_start', 'data': {'content_type': 'reasoning'}})}\n\n"
                        await asyncio.sleep(0.02)
                        has_sent_reasoning_start = True

                    # Send reasoning chunk immediately
                    reasoning_msg = {
                        "type": "reasoning_content",
                        "data": {
                            "reasoning": reasoning_text
                        }
                    }
                    
                    # Only log occasionally to avoid flooding logs
                    if chunk_count == 1 or chunk_count % 100 == 0 or len(reasoning_text) > 100:
                        logger.info(
                            f"__stream__shit Streaming reasoning chunk #{chunk_count} - length {len(reasoning_text)}")
                    yield f"data: {json.dumps(reasoning_msg)}\n\n"
                    await asyncio.sleep(0.01)

                elif chunk_type == "content":
                    content_text = chunk.get("content", "")
                    content_chunks.append(content_text)

                    # Send content start signal if first content chunk
                    if not has_sent_content_start:
                        logger.info(
                            f"__stream__shit Starting to stream content in real-time")
                        # Signal for backward compatibility
                        yield f"data: {json.dumps({'content_start': True})}\n\n"
                        # Signal in new format
                        yield f"data: {json.dumps({'type': 'content_start', 'data': {'content_type': 'text'}})}\n\n"
                        await asyncio.sleep(0.02)
                        has_sent_content_start = True

                    # Stream content chunk immediately
                    if content_text:
                        if chunk_count == 1 or chunk_count % 100 == 0 or len(content_text) > 100:
                            logger.info(
                                f"__stream__shit Streaming content chunk #{chunk_count} - length {len(content_text)}")
                        yield f"data: {json.dumps({'content': content_text, 'type': 'content', 'data': {'text': content_text}})}\n\n"
                        await asyncio.sleep(0.01)

                elif chunk_type == "image_generation":
                    # Handle image generation status updates
                    status = chunk.get("status", "unknown")
                    task_id = chunk.get("task_id", "")
                    logger.info(f"__stream__shit Received image generation status: {status} for task {task_id}")
                    
                    if status == "generating":
                        # Send image_generating event
                        image_generating_event = {
                            "type": "image_generating",
                            "data": {
                                "task_id": chunk.get("task_id"),
                                "prompt": chunk.get("prompt")
                            }
                        }
                        yield f"data: {json.dumps(image_generating_event)}\n\n"
                        logger.info(f"__stream__shit Sent image_generating event for task {task_id}")
                    
                    elif status == "completed":
                        # Send image_ready event
                        image_ready_event = {
                            "type": "image_ready",
                            "data": {
                                "task_id": chunk.get("task_id"),
                                "image_url": chunk.get("image_url"),
                                "image_id": chunk.get("image_id"),
                                "prompt": chunk.get("prompt")
                            }
                        }
                        yield f"data: {json.dumps(image_ready_event)}\n\n"
                        logger.info(f"__stream__shit Sent image_ready event for task {task_id}")
                        
                        # Also send a backward compatibility event
                        compat_event = {
                            "image_generation_complete": True,
                            "image_url": chunk.get("image_url"),
                            "task_id": chunk.get("task_id")
                        }
                        yield f"data: {json.dumps(compat_event)}\n\n"
                    
                    elif status == "failed":
                        # Send image_failed event
                        image_failed_event = {
                            "type": "image_failed",
                            "data": {
                                "task_id": chunk.get("task_id"),
                                "error": chunk.get("error", "Unknown error occurred")
                            }
                        }
                        yield f"data: {json.dumps(image_failed_event)}\n\n"
                        logger.info(f"__stream__shit Sent image_failed event for task {task_id}")
                    
                    await asyncio.sleep(0.02)

                elif chunk_type == "completion":
                    content_complete = True
                    logger.info(
                        f"__stream__shit Received completion signal: content_length={chunk.get('content_length', 0)}, reasoning_length={chunk.get('reasoning_length', 0)}")

                    # Signal end of content if needed
                    if has_sent_content_start:
                        logger.info(
                            f"__stream__shit Content streaming complete, signaling content_end")
                        yield f"data: {json.dumps({'type': 'content_end', 'data': {'content_type': 'text'}})}\n\n"
                        await asyncio.sleep(0.02)

                    # Signal end of reasoning if needed
                    if has_sent_reasoning_start:
                        logger.info(
                            f"__stream__shit Reasoning streaming complete, signaling reasoning_end")
                        yield f"data: {json.dumps({'type': 'reasoning_end', 'data': {'content_type': 'reasoning'}})}\n\n"
                        await asyncio.sleep(0.02)

                        # Send reasoning available signal for backward compatibility
                        combined_reasoning = "".join(reasoning_chunks)
                        reasoning_available_msg = {
                            "type": "reasoning_available",
                            "data": {
                                "timestamp": datetime.now().isoformat(),
                                "content_length": len(combined_reasoning)
                            }
                        }
                        logger.info(
                            f"__stream__shit Sending reasoning_available signal for completion")
                        yield f"data: {json.dumps(reasoning_available_msg)}\n\n"
                        await asyncio.sleep(0.02)

                elif chunk_type == "error":
                    logger.error(
                        f"__stream__shit Error in streaming generator: {chunk.get('error', 'Unknown error')}")
                    yield f"data: {json.dumps({'error': chunk.get('error', 'Unknown error'), 'type': 'error'})}\n\n"

            # If we get here with no explicit completion, we're still complete
            if not content_complete:
                # End content if we had content
                if has_sent_content_start:
                    logger.info(
                        f"__stream__shit Implicit content completion, signaling content_end")
                    yield f"data: {json.dumps({'type': 'content_end', 'data': {'content_type': 'text'}})}\n\n"
                    await asyncio.sleep(0.02)

                # End reasoning if we had reasoning
                if has_sent_reasoning_start:
                    logger.info(
                        f"__stream__shit Implicit reasoning completion, signaling reasoning_end")
                    yield f"data: {json.dumps({'type': 'reasoning_end', 'data': {'content_type': 'reasoning'}})}\n\n"
                    await asyncio.sleep(0.02)

            # Store in database if conversation_id is provided
            conversation_id = context.get("conversation_id")
            db = context.get("db")
            if conversation_id and db:
                message_id = context.get("message_id", str(uuid.uuid4()))
                now = datetime.now(timezone.utc)
                combined_content = "".join(content_chunks)

                # Create metadata with reasoning content if available
                metadata = {
                    "type": "general_knowledge",
                    "multi_intent": len(context.get("results", [])) > 1
                }

                # Include reasoning content in metadata if available
                if reasoning_chunks:
                    metadata["reasoning_content"] = "".join(reasoning_chunks)

                # Check if we need to create a new message or update an existing one
                check_query = """
                SELECT id FROM mo_llm_messages
                WHERE conversation_id = :conversation_id
                AND created_at > now() - interval '30 seconds'
                AND role = 'assistant'
                ORDER BY created_at DESC
                LIMIT 1
                """

                existing_message = await db.fetch_one(
                    query=check_query,
                    values={"conversation_id": conversation_id}
                )

                if existing_message:
                    # Update existing message
                    logger.info(f"__stream__shit Updating existing message {existing_message['id']}")
                    message_id = existing_message["id"]
                    await db.execute(
                        """
                        UPDATE mo_llm_messages
                        SET content = :content, metadata = :metadata
                        WHERE id = :id
                        """,
                        {
                            "id": message_id,
                            "content": combined_content,
                            "metadata": json.dumps(metadata)
                        }
                    )
                    logger.info(
                        f"Updated existing message {message_id} with complete content")
                else:
                    # Create new message
                    logger.info(f"__stream__shit Creating new message {message_id}")
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
                            "content": combined_content,
                            "created_at": now,
                            "metadata": json.dumps(metadata)
                        }
                    )
                    logger.info(
                        f"Created new message {message_id} with complete content")

                # Store message_id in context
                context["message_id"] = message_id

        except Exception as e:
            logger.error(
                f"__stream__shit Error processing streaming generator: {str(e)}")
            yield f"data: {json.dumps({'error': str(e), 'type': 'error'})}\n\n"

        # Add general_knowledge to processed results
        processed_results.append("general_knowledge")

    # Fallback for older implementation - stream pre-collected content if no streaming generator
    # (Keep the existing fallback code for backward compatibility)
    elif "general_knowledge_content" in context:
        content = context["general_knowledge_content"]
        # Stream in chunks
        chunk_size = 100

        # Signal start of content (backward compatibility)
        logger.info(
            f"__stream__shit Starting to stream content, total length: {len(content)}")
        yield f"data: {json.dumps({'content_start': True})}\n\n"

        # Signal start of content (new format)
        yield f"data: {json.dumps({'type': 'content_start', 'data': {'content_type': 'text'}})}\n\n"
        await asyncio.sleep(0.02)

        for i in range(0, len(content), chunk_size):
            chunk = content[i:i+chunk_size]
            logger.info(
                f"__stream__shit Sending content chunk {i//chunk_size + 1}/{(len(content)+chunk_size-1)//chunk_size}: '{chunk[:20]}...'")
            # Both old and new format for compatibility
            yield f"data: {json.dumps({'content': chunk, 'type': 'content', 'data': {'text': chunk}})}\n\n"
            # Small delay for natural streaming effect
            await asyncio.sleep(0.02)

        # Signal end of content
        logger.info(
            f"__stream__shit Content streaming complete, signaling content_end")
        yield f"data: {json.dumps({'type': 'content_end', 'data': {'content_type': 'text'}})}\n\n"
        await asyncio.sleep(0.02)

        # Check if we have reasoning content to send
        if "reasoning_content" in context and context["reasoning_content"]:
            reasoning_content = context["reasoning_content"]

            # Send reasoning content in a special message
            reasoning_msg = {
                "type": "reasoning_content",
                "data": {
                    "reasoning": reasoning_content
                }
            }
            logger.info(
                f"__stream__shit Sending reasoning content to client ({len(reasoning_content)} chars) - sample: '{reasoning_content[:50]}...'")
            yield f"data: {json.dumps(reasoning_msg)}\n\n"
            await asyncio.sleep(0.05)

            # Send additional reasoning availability signal to ensure client notice
            reasoning_available_msg = {
                "type": "reasoning_available",
                "data": {
                    "timestamp": datetime.now().isoformat(),
                    "content_length": len(reasoning_content)
                }
            }
            logger.info(
                f"__stream__shit Sending reasoning_available signal as backup")
            yield f"data: {json.dumps(reasoning_available_msg)}\n\n"
            await asyncio.sleep(0.05)

        # Add general_knowledge to processed results
        processed_results.append("general_knowledge")

    # Send a final summary message with all completed results
    polling_required = any(result.get("type") == "image_generation" and
                         not result.get("image_url") for result in context.get("results", []))
    
    # Include pending image tasks in the summary
    pending_image_tasks = []
    for result in context.get("results", []):
        if result.get("type") == "image_generation" and not result.get("image_url"):
            pending_image_tasks.append({
                "task_id": result.get("task_id"),
                "prompt": result.get("prompt"),
                "poll_endpoint": result.get("poll_endpoint", f"/api/v1/pipeline/image-status/{result.get('task_id')}")
            })
    
    summary = {
        "type": "summary",
        "summary": {  # For backward compatibility
            "completed_results": processed_results,
            "all_complete": True,
            "polling_required": polling_required,
            "pending_image_tasks": pending_image_tasks
        },
        "data": {
            "completed_results": processed_results,
            "all_complete": True,
            "polling_required": polling_required,
            "pending_image_tasks": pending_image_tasks
        }
    }
    logger.info(f"__stream__chat Sending summary message: {processed_results}")
    yield f"data: {json.dumps(summary)}\n\n"
        
    # If we have pending image tasks, keep the stream alive and check for updates
    last_poll_time = datetime.now(timezone.utc)
    max_wait_time = 120  # Increase wait time to 120 seconds for images
    polling_interval = 2  # Poll every 2 seconds
    sent_polling_notification = False
    
    # If we have image tasks, notify client about continuous polling
    if image_generation_tasks:
        polling_time = datetime.now()
        polling_notification = {
            "type": "polling_required",
            "data": {
                "task_ids": [task["task_id"] for task in image_generation_tasks],
                "message": "Image generation in progress, client should continue polling",
                "poll_endpoint": "/api/v1/pipeline/image-status/{task_id}"
            }
        }
        yield f"data: {json.dumps(polling_notification)}\n\n"
        sent_polling_notification = True
        logger.info(f"⏱️ TIMING: Sending polling notification at {polling_time.isoformat()}")
        logger.info(f"__stream__chat Sent polling notification for image tasks: {[task['task_id'] for task in image_generation_tasks]}")
    
    while image_generation_tasks and (datetime.now(timezone.utc) - last_poll_time).total_seconds() < max_wait_time:
        # Poll for image status at specified interval
        await asyncio.sleep(polling_interval)
        
        # Check each pending task
        for task in image_generation_tasks:
            if task["completed"]:
                continue
                
            task_id = task["task_id"]
            
            try:
                # Query the task status
                query = """
                SELECT status, result, error FROM mo_ai_tasks 
                WHERE id = :task_id
                """
                
                task_status = await db.fetch_one(query=query, values={"task_id": task_id})
                    
                if task_status:
                    # Commented out noisy log message
                    # logger.info(f"__stream__shit Checking image task {task_id}: status={task_status['status']}")
                    
                    if task_status["status"] == "completed" and task_status["result"]:
                        # Parse the result JSON
                        result_data = json.loads(task_status["result"])
                        
                        # Get the image data
                        if "images" in result_data and result_data["images"]:
                            image = result_data["images"][0]
                            image_url = image.get("url")
                            image_id = image.get("id")
                                
                            # Send image_ready event
                            image_ready_event = {
                                "type": "image_ready",
                                "data": {
                                    "task_id": task_id,
                                    "image_url": image_url,
                                    "image_id": image_id,
                                    "prompt": task["prompt"]
                                }
                            }
                            yield f"data: {json.dumps(image_ready_event)}\n\n"
                            logger.info(f"__stream__shit Sent image_ready event for task {task_id}")
                            
                            # Also send a backward compatibility event
                            compat_event = {
                                "image_generation_complete": True,
                                "image_url": image_url,
                                "task_id": task_id
                            }
                            yield f"data: {json.dumps(compat_event)}\n\n"
                                
                            # Mark task as completed
                            task["completed"] = True
                            last_poll_time = datetime.now(timezone.utc)  # Reset the timer when we find a completed image
                                
                            # Update message in database with image URL
                            message_id = context.get("message_id")
                            conversation_id = context.get("conversation_id")
                            
                            if message_id and conversation_id and db:
                                try:
                                    # Check if message exists
                                    check_query = "SELECT id FROM mo_llm_messages WHERE id = :id AND conversation_id = :conversation_id"
                                    message_exists = await db.fetch_one(
                                        query=check_query,
                                        values={
                                            "id": message_id,
                                            "conversation_id": conversation_id
                                        }
                                    )
                                        
                                    if message_exists:
                                        # Create updated metadata with image info
                                        metadata_query = "SELECT metadata FROM mo_llm_messages WHERE id = :id"
                                        metadata_result = await db.fetch_one(
                                            query=metadata_query,
                                            values={"id": message_id}
                                        )
                                        
                                        metadata = {}
                                        if metadata_result and metadata_result["metadata"]:
                                            try:
                                                metadata = json.loads(metadata_result["metadata"])
                                            except:
                                                pass
                                                    
                                        # Update with image information
                                        metadata["image_url"] = image_url
                                        metadata["image_id"] = image_id
                                        metadata["image_task_id"] = task_id
                                        metadata["image_prompt"] = task["prompt"]
                                        metadata["image_status"] = "completed"
                                        
                                        # Update the message
                                        logger.info(f"__stream__shit Updating message {message_id} with image URL {image_url}")
                                        update_query = """
                                        UPDATE mo_llm_messages 
                                        SET image_url = :image_url, 
                                            metadata = :metadata
                                        WHERE id = :id
                                        """
                                            
                                        await db.execute(
                                            query=update_query,
                                            values={
                                                "id": message_id,
                                                "image_url": image_url,
                                                "metadata": json.dumps(metadata)
                                            }
                                        )
                                        
                                        logger.info(f"__stream__shit Updated message {message_id} with image URL {image_url}")
                                except Exception as e:
                                    logger.error(f"__stream__shit Error updating message with image: {str(e)}")
                    
                    elif task_status["status"] == "failed":
                        # Send image_failed event
                        image_failed_event = {
                            "type": "image_failed",
                            "data": {
                                "task_id": task_id,
                                "error": task_status.get("error", "Unknown error")
                            }
                        }
                        yield f"data: {json.dumps(image_failed_event)}\n\n"
                        logger.info(f"__stream__shit Sent image_failed event for task {task_id}")
                        
                        # Mark task as completed (failed is still completed)
                        task["completed"] = True
            except Exception as e:
                logger.error(f"__stream__shit Error polling image task {task_id}: {str(e)}")
        
        # Break if all tasks are completed
        if all(task["completed"] for task in image_generation_tasks):
            logger.info("__stream__shit All image tasks completed, ending polling")
            break
    
    # Send updated summary if we had image tasks
    if image_generation_tasks:
        updated_summary = {
            "type": "summary",
            "summary": {
                "completed_results": processed_results,
                "all_complete": True,
                "polling_required": any(not task["completed"] for task in image_generation_tasks)
            },
            "data": {
                "completed_results": processed_results,
                "all_complete": True,
                "polling_required": any(not task["completed"] for task in image_generation_tasks)
            }
        }
        logger.info(f"__stream__chat Sending final summary after image polling")
        yield f"data: {json.dumps(updated_summary)}\n\n"

    # End the stream
    logger.info(f"__stream__chat Sending final [DONE] marker")
    yield "data: [DONE]\n\n"


# async def process_message_with_pipeline(config: Dict[str, Any]):
#     """Process message through pipeline and yield formatted chunks"""
#     # Extract request parameters
#     message_type = config.get("message_type", "text")
#     options = config.get("options", {})
#     conversation_id = config.get("conversation_id")
#     db = config.get("db")
#     logger.info(f"Processing message with pipeline: {config}")
#     # Configure message processing based on message type and options
#     if message_type == "image":
#         # For image generation requests
#         config["intents"] = {"image_generation": {"confidence": 1.0}}
#     elif message_type == "social":
#         # For social media content requests
#         config["intents"] = {"social_media": {"confidence": 1.0}}
#         if options.get("social_platforms"):
#             config["social_platforms"] = options["social_platforms"]
#     elif message_type == "reasoning":
#         # For reasoning-focused requests
#         config["reasoning_effort"] = "high"
#         if options.get("reasoning_model"):
#             config["model"] = options["reasoning_model"]

#     # Always detect intents for text messages
#     if message_type == "text":
#         # intents = detect_intents(config["message"])
#         raw_probs = await predict_intents(config["message"])
#         intents = {k: {"confidence": v} for k, v in raw_probs.items()}
#         # Filter out low-confidence intents
#         significant_intents = {k: v for k,
#                                v in intents.items() if v["confidence"] > 0.3}
#         config["intents"] = significant_intents
        
#         # Update message_type based on detected intents
#         if "image_generation" in significant_intents and significant_intents["image_generation"]["confidence"] > 0.5:
#             logger.info(f"Updating message_type from 'text' to 'image' based on intent detection")
#             config["message_type"] = "image"
#             message_type = "image"  # Update local variable too
#         elif "social_media" in significant_intents and significant_intents["social_media"]["confidence"] > 0.5:
#             logger.info(f"Updating message_type from 'text' to 'social' based on intent detection")
#             config["message_type"] = "social"
#             message_type = "social"  # Update local variable too

#     # Handle web search option
#     if options.get("perform_web_search"):
#         # This would integrate with your web search command
#         pass

#     # Create pipeline based on intents and message type
#     pipeline = Pipeline(name="MultiIntentPipeline")

#     # Add commands based on message type and intents
#     intents_dict = config.get("intents", {})

#     # For calculation
#     if "calculation" in intents_dict:
#         pipeline.add_command(CommandFactory.create("calculation"))

#     # For image generation
#     if message_type == "image" or "image_generation" in intents_dict:
#         logger.info(f"__stream__shit Adding image generation command")
#         image_command = CommandFactory.create("image_generation")
#         if options.get("image_model"):
#             # Set model in command config
#             image_command.set_option("model", options["image_model"])
#         pipeline.add_command(image_command)

#     # For social media
#     if message_type == "social" or "social_media" in intents_dict:
#         social_command = CommandFactory.create("social_media")
#         if options.get("social_platforms"):
#             # Set platforms in command config
#             social_command.set_option("platforms", options["social_platforms"])
#         pipeline.add_command(social_command)

#     # For conversation/general knowledge
#     if message_type in ["text", "reasoning"] or "conversation" in intents_dict:
#         if "conversation" in intents_dict:
#             pipeline.add_command(CommandFactory.create("conversation"))

#         # Add general knowledge command for text responses
#         if message_type != "image" and message_type != "social":
#             pipeline.add_command(CommandFactory.create("general_knowledge"))

#     # Execute the pipeline
#     result_context = await pipeline.execute(config)

#     # Generate a message ID if not already in the context
#     if "message_id" not in result_context:
#         result_context["message_id"] = str(uuid.uuid4())

#     # Stream the response
#     try:
#         async for chunk in process_streaming_response(result_context):
#             yield chunk

#         # No need to update message in the database here as that's now handled
#         # directly in the streaming generator from GeneralKnowledgeCommand
#     except Exception as e:
#         logger.error(
#             f"Error in process_message_with_pipeline streaming: {str(e)}")
#         # Still yield the error so the client knows something went wrong
#         yield f"data: {json.dumps({'error': str(e), 'type': 'error'})}\n\n"
#         yield "data: [DONE]\n\n"


# async def process_multi_intent_request(
#     request: MultiIntentChatRequest,
#     background_tasks: BackgroundTasks,
#     current_user: dict,
#     db: Database
# ) -> Dict[str, Any]:
#     logger.info(f"process_multi_intent_request starting: chat_id={request.chat_id}, conversation_id={request.conversation_id}")
    
#     # If we have a chat_id, try to fetch content info
#     if request.chat_id:
#         try:
#             content_query = "SELECT id, name, description FROM mo_chat WHERE uuid = :chat_id"
#             content = await db.fetch_one(content_query, {"chat_id": request.chat_id})
#             if content:
#                 logger.info(f"Found content for request: ID={content['id']}, Name='{content['name']}'")
#         except Exception as e:
#             logger.error(f"Error fetching content info: {str(e)}")
#             # Continue processing even if this fails
#     """
#     Process a multi-intent request using the pipeline pattern.
#     """
#     # Log the user for debugging
#     logger.info(
#         f"Processing request for user: {current_user.get('id', current_user.get('uid', 'unknown'))}")

#     # Detect intents in the message
#     # intents = detect_intents(request.message)
#     # v2 pending to release
#     raw_probs = await predict_intents(request.message)
#     intents = {k: {"confidence": v} for k, v in raw_probs.items()}
    
#     # Filter out low-confidence intents for logging
#     significant_intents = {k: v for k, v in intents.items() if v["confidence"] > 0.3}
    
#     # Filter out web_search and puppeteer intents
#     if "web_search" in significant_intents:
#         del significant_intents["web_search"]
#     if "puppeteer" in significant_intents:
#         del significant_intents["puppeteer"]
    
#     logger.info(f"Detected intents: {list(significant_intents.keys())}")

#     # Create or get conversation
#     conversation_id = request.conversation_id
#     if not conversation_id:
#         title = f"Multi-Intent: {request.message[:30]}..." if len(
#             request.message) > 30 else request.message
#         conversation_id = await create_conversation(
#             db=db,
#             user_id=current_user.get('id', current_user.get('uid')),
#             title=title,
#             chat_id=request.chat_id
#         )

#     # Store user message in database
#     user_message_id = str(uuid.uuid4())
#     now = datetime.now(timezone.utc)
#     logger.info(f"__stream__shit Storing user message {user_message_id} in database")
#     await db.execute(
#         """
#         INSERT INTO mo_llm_messages (
#             id, conversation_id, role, content, created_at, metadata
#         ) VALUES (
#             :id, :conversation_id, :role, :content, :created_at, :metadata
#         )
#         """,
#         {
#             "id": user_message_id,
#             "conversation_id": conversation_id,
#             "role": "user",
#             "content": request.message,
#             "created_at": now,
#             "metadata": json.dumps({"multi_intent": True, "detected_intents": list(significant_intents.keys())})
#         }
#     )

#     # Create initial context
#     context = {
#         "message": request.message,
#         "conversation_id": conversation_id,
#         "chat_id": request.chat_id,  # Explicitly include chat_id 
#         "user_id": current_user.get('id', current_user.get('uid')),
#         "db": db,
#         "background_tasks": background_tasks,
#         "current_user": current_user,
#         "intents": significant_intents,
#         "model": request.model,
#         "temperature": request.temperature,
#         "max_tokens": request.max_tokens,
#         "reasoning_effort": request.reasoning_effort,
#         "results": []  # Ensure results list is always initialized
#     }
    
#     # Log the chat_id we're using
#     logger.info(f"Processing message with chat_id: {request.chat_id}")

#     # Create pipeline based on intents
#     pipeline = Pipeline(name="MultiIntentPipeline")

#     # REMOVED web search and puppeteer commands    

#     # Initialize skip_general_knowledge flag
#     skip_general_knowledge = False

#     # REMOVED web search and puppeteer commands

#     # Calculation command for math operations
#     if "calculation" in significant_intents:
#         pipeline.add_command(CommandFactory.create("calculation"))

#     # Image generation next (if present)
#     if "image_generation" in significant_intents:
#         pipeline.add_command(CommandFactory.create("image_generation"))
#         # Skip general knowledge for image generation requests
#         skip_general_knowledge = True
#         logger.info(
#             f"Skipping general_knowledge because image_generation intent was detected")

#     # Social media content generation next
#     if "social_media" in significant_intents:
#         pipeline.add_command(CommandFactory.create("social_media"))
#         # Skip general knowledge for social media requests
#         skip_general_knowledge = True
#         logger.info(
#             f"Skipping general_knowledge because social_media intent was detected")

#     # Add conversation command for simple chats/greetings
#     if "conversation" in significant_intents:
#         pipeline.add_command(CommandFactory.create("conversation"))
#         # ALWAYS add general knowledge command when conversation intent is detected
#         # since conversation command doesn't generate text itself
#         pipeline.add_command(CommandFactory.create("general_knowledge"))
#     else:
#         # Only add general knowledge if we haven't decided to skip it
#         if not skip_general_knowledge and significant_intents.get("general_knowledge", {}).get("confidence", 0) > 0.3:
#             pipeline.add_command(CommandFactory.create("general_knowledge"))

#     # Execute the pipeline
#     result_context = await pipeline.execute(context)

#     # Return the context for further processing
#     return result_context

# ADDED NEW ENDPOINTS FOR CONVERSATION MANAGEMENT

# remove polling
async def process_message_with_pipeline(config: Dict[str, Any]):
    """Process message through pipeline and yield formatted chunks"""
    # Extract request parameters
    message_type = config.get("message_type", "text")
    options = config.get("options", {})
    conversation_id = config.get("conversation_id")
    db = config.get("db")

    # Add debug logging
    logger.info(f"ENHANCED processing message with pipeline: {config}")
    logger.info(
        f"MESSAGE TYPE: {message_type}, CONVERSATION_ID: {conversation_id}")

    # Configure message processing based on message type and options
    if message_type == "image":
        # For image generation requests
        config["intents"] = {"image_generation": {"confidence": 1.0}}
        # Set image generation mode flag
        config["image_generation_mode"] = True
        logger.info("Setting image_generation_mode=True for image request")
    elif message_type == "social":
        # For social media content requests
        config["intents"] = {"social_media": {"confidence": 1.0}}
        if options.get("social_platforms"):
            config["social_platforms"] = options["social_platforms"]
    elif message_type == "reasoning":
        # For reasoning-focused requests
        config["reasoning_effort"] = "high"
        if options.get("reasoning_model"):
            config["model"] = options["reasoning_model"]

    # Always detect intents for text messages
    if message_type == "text":
        # intents = detect_intents(config["message"])
        raw_probs = await predict_intents(config["message"])
        intents = {k: {"confidence": v} for k, v in raw_probs.items()}
        # Filter out low-confidence intents
        significant_intents = {k: v for k,
                               v in intents.items() if v["confidence"] > 0.3}
        config["intents"] = significant_intents

        # Update message_type based on detected intents
        if "image_generation" in significant_intents and significant_intents["image_generation"]["confidence"] > 0.5:
            logger.info(
                f"Updating message_type from 'text' to 'image' based on intent detection")
            config["message_type"] = "image"
            message_type = "image"  # Update local variable too
            # Set image generation mode flag
            config["image_generation_mode"] = True
            logger.info(
                "Setting image_generation_mode=True based on intent detection")
        elif "social_media" in significant_intents and significant_intents["social_media"]["confidence"] > 0.5:
            logger.info(
                f"Updating message_type from 'text' to 'social' based on intent detection")
            config["message_type"] = "social"
            message_type = "social"  # Update local variable too

    # Create pipeline based on intents and message type
    pipeline = Pipeline(name="MultiIntentPipeline")

    # Add commands based on message type and intents
    intents_dict = config.get("intents", {})

    # For calculation
    if "calculation" in intents_dict:
        pipeline.add_command(CommandFactory.create("calculation"))

    # For image generation - ENHANCED LOGGING
    if message_type == "image" or "image_generation" in intents_dict:
        logger.info(f"__ENHANCED_PIPELINE__ Adding image generation command")
        image_command = CommandFactory.create("image_generation")
        if options.get("image_model"):
            # Set model in command config
            image_command.set_option("model", options["image_model"])
        pipeline.add_command(image_command)

        # Make sure we're recording this is an image generation specifically
        config["is_image_generation"] = True

        # Add assistant message_id to config if it exists
        if "message_id" in config:
            logger.info(
                f"__ENHANCED_PIPELINE__ Using existing message_id {config['message_id']} for image")
        else:
            config["message_id"] = str(uuid.uuid4())
            logger.info(
                f"__ENHANCED_PIPELINE__ Generated new message_id {config['message_id']} for image")

    # For social media
    if message_type == "social" or "social_media" in intents_dict:
        social_command = CommandFactory.create("social_media")
        if options.get("social_platforms"):
            # Set platforms in command config
            social_command.set_option("platforms", options["social_platforms"])
        pipeline.add_command(social_command)

    # For conversation/general knowledge
    if message_type in ["text", "reasoning"] or "conversation" in intents_dict:
        if "conversation" in intents_dict:
            pipeline.add_command(CommandFactory.create("conversation"))

        # Add general knowledge command for text responses
        if message_type != "image" and message_type != "social":
            pipeline.add_command(CommandFactory.create("general_knowledge"))

    # Execute the pipeline with additional logging
    logger.info(
        f"__ENHANCED_PIPELINE__ Executing pipeline for {message_type} message")
    result_context = await pipeline.execute(config)
    logger.info(
        f"__ENHANCED_PIPELINE__ Pipeline execution completed, results: {len(result_context.get('results', []))}")

    # Generate a message ID if not already in the context
    if "message_id" not in result_context:
        result_context["message_id"] = str(uuid.uuid4())
        logger.info(
            f"__ENHANCED_PIPELINE__ Generated message_id {result_context['message_id']} after pipeline execution")

    # For image generation, verify we have the task_id in the message_id mapping
    if config.get("is_image_generation", False):
        for result in result_context.get("results", []):
            if result.get("type") == "image_generation":
                logger.info(
                    f"__ENHANCED_PIPELINE__ Image generation result: {result}")
                image_task_id = result.get("task_id")
                if image_task_id:
                    logger.info(
                        f"__ENHANCED_PIPELINE__ Image task_id {image_task_id} is associated with message_id {result_context['message_id']}")
                else:
                    logger.warning(
                        f"__ENHANCED_PIPELINE__ Image generation result missing task_id")

    # Stream the response with enhanced error handling
    try:
        logger.info(
            f"__ENHANCED_PIPELINE__ Starting to stream response for message_id {result_context['message_id']}")
        async for chunk in process_streaming_response(result_context):
            yield chunk

        logger.info(
            f"__ENHANCED_PIPELINE__ Completed streaming response for message_id {result_context['message_id']}")
    except Exception as e:
        logger.error(
            f"__ENHANCED_PIPELINE__ Error in process_message_with_pipeline streaming: {str(e)}")
        logger.error(traceback.format_exc())  # Add stack trace
        # Still yield the error so the client knows something went wrong
        yield f"data: {json.dumps({'error': str(e), 'type': 'error'})}\n\n"
        yield "data: [DONE]\n\n"

# Get a conversation by content ID
@router.get("/conversation/by-content/{chat_id}")
async def get_conversation_by_content(
    chat_id: str,
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Get a conversation by content ID with all associated messages"""
    try:
        logger.info(f"Content ID endpoint called for: {chat_id}")
        
        # Get user ID
        user_id = current_user.get("uid")
        
        logger.info(f"Getting conversation and messages for content {chat_id}, user {user_id}")

        # Updated query to fetch conversations and messages in one request
        query = """
        SELECT c.id as conversation_id, c.user_id, c.chat_id, c.model_id, c.title, 
               c.created_at as conversation_created_at, c.updated_at, c.metadata as conversation_metadata,
               m.id as message_id, m.role, m.content as message_content, 
               m.created_at as message_created_at, m.function_call, 
               m.metadata as message_metadata, m.image_url, m.image_metadata
        FROM mo_llm_conversations c
        LEFT JOIN mo_llm_messages m ON c.id = m.conversation_id
        WHERE c.chat_id = :chat_id AND c.user_id = :user_id
        ORDER BY c.created_at DESC, m.created_at ASC
        """
        results = await db.fetch_all(query=query, values={"chat_id": chat_id, "user_id": user_id})

        if not results:
            logger.info(f"No existing conversation found for content {chat_id}")
            return {"conversation": None, "messages": [], "found": False}

        # Extract conversation details from the first row
        first_row = dict(results[0]) if results else {}
        conversation = {
            "id": first_row.get("conversation_id"),
            "user_id": first_row.get("user_id"),
            "chat_id": first_row.get("chat_id"),
            "model_id": first_row.get("model_id"),
            "title": first_row.get("title"),
            "created_at": first_row.get("conversation_created_at"),
            "updated_at": first_row.get("updated_at"),
            "metadata": first_row.get("conversation_metadata")
        } if first_row else None

        # Extract all messages
        messages = []
        for row in results:
            if row["message_id"]:
                message = {
                    "id": row["message_id"],
                    "role": row["role"],
                    "content": row["message_content"],
                    "created_at": row["message_created_at"],
                    "function_call": row["function_call"],
                    "metadata": row["message_metadata"],
                    "image_url": row["image_url"],
                    "image_metadata": row["image_metadata"]
                }
                
                # Process metadata and function_call if they're JSON strings
                for field in ["metadata", "function_call"]:
                    if message.get(field) and isinstance(message[field], str):
                        try:
                            message[field] = json.loads(message[field])
                        except json.JSONDecodeError:
                            pass  # Keep as string if can't parse
                            
                messages.append(message)

        logger.info(f"Found conversation with {len(messages)} messages for content {chat_id}")
        return {
            "conversation": conversation,
            "messages": messages,
            "found": True,
            "cached": False  # Indicate this is a fresh response
        }
    except Exception as e:
        logger.error(f"Error in get_conversation_by_content: {str(e)}")
        logger.error(traceback.format_exc())
        # Return the error message for debugging
        return JSONResponse(
            status_code=500, 
            content={
                "error": f"Error retrieving conversation: {str(e)}",
                "trace": traceback.format_exc()
            }
        )

class BulkChatIdsRequest(BaseModel):
    chat_ids: List[str]
    
    model_config = {
        'protected_namespaces': ()
    }

@router.post("/conversations/bulk")
async def get_conversations_bulk(
    request: BulkChatIdsRequest,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """Get conversations and messages for multiple chat IDs in a single request"""
    try:
        # Get user ID
        user_id = current_user.get("uid")
        
        if not request.chat_ids:
            return {"conversations": {}, "found": False}
            
        logger.info(f"Fetching bulk conversations for {len(request.chat_ids)} chat IDs")
        
        # Single SQL query to get all conversations and their messages
        # Using a WITH clause for cleaner SQL
        query = """
        WITH conversations AS (
            SELECT c.id, c.user_id, c.chat_id, c.model_id, c.title, 
                  c.created_at, c.updated_at, c.metadata
            FROM mo_llm_conversations c
            WHERE c.chat_id = ANY(:chat_ids) 
            AND c.user_id = :user_id
            ORDER BY c.created_at DESC
        )
        SELECT 
            c.id as conversation_id, c.user_id, c.chat_id, c.model_id, c.title,
            c.created_at as conversation_created_at, c.updated_at, c.metadata as conversation_metadata,
            m.id as message_id, m.role, m.content as message_content,
            m.created_at as message_created_at, m.function_call,
            m.metadata as message_metadata, m.image_url, m.image_metadata
        FROM conversations c
        LEFT JOIN mo_llm_messages m ON c.id = m.conversation_id
        ORDER BY c.created_at DESC, m.created_at ASC
        """
        
        results = await db.fetch_all(
            query=query, 
            values={
                "chat_ids": request.chat_ids,
                "user_id": user_id
            }
        )
        
        if not results:
            return {"conversations": {}, "found": False}
            
        # Organize results by chat_id
        organized_data = {}
        
        for row in results:
            chat_id = row["chat_id"]
            conversation_id = row["conversation_id"]
            
            # Initialize conversation data if not exists
            if chat_id not in organized_data:
                organized_data[chat_id] = {
                    "conversation": {
                        "id": conversation_id,
                        "user_id": row["user_id"],
                        "chat_id": chat_id,
                        "model_id": row["model_id"],
                        "title": row["title"],
                        "created_at": row["conversation_created_at"],
                        "updated_at": row["updated_at"],
                        "metadata": row["conversation_metadata"]
                    },
                    "messages": []
                }
            
            # Add message data if it exists
            if row["message_id"]:
                message = {
                    "id": row["message_id"],
                    "role": row["role"],
                    "content": row["message_content"],
                    "created_at": row["message_created_at"],
                    "function_call": row["function_call"],
                    "metadata": row["message_metadata"],
                    "image_url": row["image_url"],
                    "image_metadata": row["image_metadata"]
                }
                
                # Process metadata and function_call as JSON if they're strings
                for field in ["metadata", "function_call"]:
                    if message[field] and isinstance(message[field], str):
                        try:
                            message[field] = json.loads(message[field])
                        except json.JSONDecodeError:
                            pass
                
                organized_data[chat_id]["messages"].append(message)
        
        return {
            "conversations": organized_data,
            "found": True,
            "cached": False
        }
        
    except Exception as e:
        logger.error(f"Error in get_conversations_bulk: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500, 
            content={
                "error": f"Error retrieving bulk conversations: {str(e)}",
                "trace": traceback.format_exc()
            }
        )


@router.get("/conversation/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database),
    _request_id: str = Header(None, alias="X-Request-ID")  # Add request tracking
):
    """Get a conversation by ID"""
    try:
        # Log request with unique ID for debugging
        request_id = _request_id or f"auto-{uuid.uuid4().hex[:8]}"
        logger.info(f"[{request_id}] Getting conversation: {conversation_id}")
        
        # Use cached value if available (simple in-memory cache)
        cache_key = f"conversation:{conversation_id}:{current_user.get('id', current_user.get('uid'))}"
        # Note: In a real implementation, you would use Redis or another distributed cache
        
        conversation = await get_conversation_by_id(db, conversation_id)

        if not conversation:
            raise HTTPException(
                status_code=404, detail="Conversation not found")

        # Use the correct user ID field
        user_id = current_user.get('id', current_user.get('uid'))
        if not user_id:
            raise HTTPException(
                status_code=400, detail="No valid user ID found")

        if conversation["user_id"] != user_id:
            raise HTTPException(
                status_code=403, detail="You don't have permission to access this conversation")

        # Get messages for this conversation with optimized query
        messages_query = """
        SELECT id, role, content, created_at, function_call, metadata, image_url, image_metadata
        FROM mo_llm_messages
        WHERE conversation_id = :conversation_id
        ORDER BY created_at
        """ 
        messages = await db.fetch_all(
            query=messages_query,
            values={"conversation_id": conversation_id}
        )

        # Convert records to dictionaries
        messages_list = [dict(msg) for msg in messages]
        
        # Process metadata for each message if present
        for msg in messages_list:
            if msg.get("metadata") and isinstance(msg["metadata"], str):
                try:
                    msg["metadata"] = json.loads(msg["metadata"])
                except json.JSONDecodeError:
                    pass  # Keep as string if can't parse
                    
            if msg.get("function_call") and isinstance(msg["function_call"], str):
                try:
                    msg["function_call"] = json.loads(msg["function_call"])
                except json.JSONDecodeError:
                    pass  # Keep as string if can't parse
        
        # Add cache headers to response
        response_data = {
            "conversation": conversation,
            "messages": messages_list,
            "cached": False,  # Indicate this is a fresh response
            "request_id": request_id
        }
        
        logger.info(f"[{request_id}] Successfully retrieved conversation with {len(messages_list)} messages")
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def multi_intent_chat(
    request: MultiIntentChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
) -> MultiIntentResponse:
    """
    Process a chat request with potential multiple intents.
    """
    try:
        # Process the request
        result_context = await process_multi_intent_request(request, background_tasks, current_user, db)

        # Format the response
        response_data = await format_pipeline_response(result_context)

        # Create message ID and timestamp
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        response_data["message_id"] = message_id

        # Extract content for database storage
        response_content = response_data.get("content", "")
        
        # Create metadata for storage
        metadata = {
            "multi_intent": True,
            "detected_intents": [intent for intent in result_context.get("intents", {}).keys() 
                               if result_context["intents"][intent]["confidence"] > 0.3],
            "results": result_context.get("results", []),
            "message_id": message_id
        }
        
        # Add reasoning content to metadata if available
        if "reasoning_content" in result_context:
            metadata["reasoning_content"] = result_context["reasoning_content"]
            logger.info(f"Including reasoning content in message metadata")
        
        # Check if this message already exists to prevent duplicates
        check_query = """
        SELECT id FROM mo_llm_messages
        WHERE conversation_id = :conversation_id
        AND created_at > now() - interval '5 seconds'
        AND role = 'assistant'
        """
        
        existing_message = await db.fetch_one(
            query=check_query,
            values={"conversation_id": result_context["conversation_id"]}
        )
        
        # Only insert if no recent message exists
        logger.info(f"__stream__shit Checking if message {message_id} exists")
        if not existing_message:
            # Store the assistant message
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
                    "conversation_id": result_context["conversation_id"],
                    "role": "assistant",
                    "content": response_content,
                    "created_at": now,
                    "metadata": json.dumps(metadata)
                }
            )
        else:
            # Use existing message ID
            message_id = existing_message["id"]
            response_data["message_id"] = message_id
            logger.info(f"Using existing message: {message_id}")

        return response_data

    except Exception as e:
        logger.error(f"Error in multi_intent_chat: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def stream_multi_intent_chat(
    request: StreamChatRequest,  # Using the new enhanced request model
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Stream a chat response with enhanced options and payload support.
    Handles content/conversation creation and message processing in a unified API.
    chat_id means the sidebar chat id
    conversation_id hold what model was used
    message_id is the actual message by user input or generated by the model
    """
    try:
        user_id = current_user.get('id', current_user.get('uid'))
        logger.info(f"Received stream request: type={request.message_type}, chat_id={request.chat_id}, conversation_id={request.conversation_id}")
        
        # Skip processing if there's no message
        if not request.message or request.message.strip() == "":
            logger.info(f"Skipping empty message")
            return JSONResponse(
                status_code=200,
                content={"message": "No message to process", "skipped": True}
            )

        # Check if we need to create new chat or conversation
        chat_id = request.chat_id
        conversation_id = request.conversation_id
        
        # If we have a chat_id but no conversation_id, create a new conversation in the existing content
        if chat_id and not conversation_id:
            logger.info(f"Creating new conversation thread in existing content {chat_id}")
            try:
                conversation_id = await create_new_conversation(
                    db=db,
                    user_id=user_id,
                    chat_id=chat_id,
                    title=request.content_name or "New Thread"
                )
                logger.info(f"Created new conversation {conversation_id} for existing content {chat_id}")
            except Exception as e:
                # If creation fails, try to find existing conversation
                logger.error(f"Error creating conversation: {str(e)}")
                
                # Try to get existing conversation for this content
                query = """
                SELECT id FROM mo_llm_conversations
                WHERE chat_id = :chat_id AND user_id = :user_id
                ORDER BY created_at DESC LIMIT 1
                """
                
                existing = await db.fetch_one(
                    query=query,
                    values={
                        "chat_id": chat_id,
                        "user_id": user_id
                    }
                )
                
                if existing:
                    conversation_id = existing["id"]
                    logger.info(f"Using existing conversation {conversation_id} for chat {chat_id}")
                else:
                    # If still no conversation found, raise error
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to create or find conversation for content {chat_id}"
                    )
        # If we have neither chat_id nor conversation_id, create both (completely new chat)
        elif not chat_id and not conversation_id:
            logger.info("Creating new content and conversation for completely new chat")
            try:
                # Create new content first
                chat_id = await create_new_content(
                    db=db, 
                    user_id=user_id, 
                    content_name=request.content_name or "New Chat"
                )
                
                # Create new conversation for the content
                conversation_id = await create_new_conversation(
                    db=db,
                    user_id=user_id,
                    chat_id=chat_id,
                    title=request.content_name or "New Chat"
                )
                
                logger.info(f"Created new content {chat_id} and conversation {conversation_id}")
            except Exception as e:
                logger.error(f"Error creating content and conversation: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create new chat: {str(e)}"
                )
        # If we have neither or missing chat_id, return error
        elif not chat_id and conversation_id:
            # Look up the chat_id from the conversation
            conversation = await get_conversation_by_id(db, conversation_id)
            if conversation and conversation.get("chat_id"):
                chat_id = conversation["chat_id"]
                logger.info(f"Retrieved chat_id {chat_id} from conversation {conversation_id}")
            else:
                logger.error("Conversation has no chat_id and none was provided")
                return JSONResponse(
                    status_code=400,
                    content={"error": "Conversation has no chat_id and none was provided"}
                )
        
        # Store user message in database
        user_message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Create metadata with message type and options
        user_metadata = {
            "message_type": request.message_type,
            "options": request.options,
            "multi_intent": True
        }
        
        # Store the user message
        logger.info(f"__stream__shit Storing user message {user_message_id} in database")
        await db.execute(
            """
            INSERT INTO mo_llm_messages (
                id, conversation_id, role, content, created_at, metadata
            ) VALUES (
                :id, :conversation_id, :role, :content, :created_at, :metadata
            )
            """,
            {
                "id": user_message_id,
                "conversation_id": conversation_id,
                "role": "user",
                "content": request.message,
                "created_at": now,
                "metadata": json.dumps(user_metadata)
            }
        )
        
        # Create the processing configuration
        config = {
        "message": request.message,
        "message_type": request.message_type,
        "options": request.options or {},
        "conversation_id": conversation_id,
        "chat_id": chat_id,
        "user_id": user_id,
        "db": db,
        "background_tasks": background_tasks,
        "current_user": current_user,
        "results": [],
        "image_generation_mode": request.message_type == "image"  # Flag for special handling of image generation
        }
        
        # Create assistant message placeholder
        assistant_message_id = str(uuid.uuid4())
        
        # Create metadata with reasoning model indicator if applicable
        metadata = {
            "message_type": request.message_type,
            "streaming": True,
            "options": request.options
        }
        
        # Add reasoning model info if specified
        if request.message_type == "reasoning" or (request.options and request.options.get("reasoning_model")):
            metadata["reasoning_enabled"] = True
            metadata["reasoning_model"] = request.options.get("reasoning_model") if request.options else None
            logger.info(f"Created message with reasoning_enabled=True")
        
        # We'll update this with content later
        logger.info(f"__stream__shit Storing assistant message {assistant_message_id} in database")
        await db.execute(
            """
            INSERT INTO mo_llm_messages (
                id, conversation_id, role, content, created_at, metadata
            ) VALUES (
                :id, :conversation_id, :role, :content, :created_at, :metadata
            )
            """,
            {
                "id": assistant_message_id,
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": "",  # Empty initially, will be updated when streaming finishes
                "created_at": now,
                "metadata": json.dumps(metadata)
            }
        )
        
        # CRITICAL: Add the message_id to the config to ensure it's used throughout the pipeline
        config["message_id"] = assistant_message_id
        logger.info(f"__stream__critical Added assistant_message_id {assistant_message_id} to pipeline config")
        
        # Return streaming response
        return StreamingResponse(
            process_message_with_pipeline(config),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform, no-store, must-revalidate",
                "X-Accel-Buffering": "no",  # Important for Nginx
                "Connection": "keep-alive",
                "Pragma": "no-cache",
                "Expires": "0",
                "Transfer-Encoding": "chunked"  # Add this to force chunked transfer
            }
        )

    except Exception as e:
        logger.error(f"Error in stream_multi_intent_chat: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Attempt to recover in case this was a race condition
        if "duplicate key value" in str(e) and "unique_user_content" in str(e):
            # This is likely a race condition where another request created the same conversation
            try:
                # Extract the chat_id from the error message
                error_msg = str(e)
                match = re.search(r"Key \(user_id, chat_id\)=\((.*?), (.*?)\)", error_msg)
                
                if match and len(match.groups()) == 2:
                    user_id_from_error = match.group(1)
                    content_id_from_error = match.group(2)
                    
                    logger.info(f"Attempting to recover from race condition for content {content_id_from_error}")
                    
                    # Find the existing conversation
                    query = """
                    SELECT id FROM mo_llm_conversations
                    WHERE user_id = :user_id AND chat_id = :chat_id
                    ORDER BY created_at DESC LIMIT 1
                    """
                    
                    existing = await db.fetch_one(
                        query=query,
                        values={
                            "user_id": user_id_from_error,
                            "chat_id": content_id_from_error
                        }
                    )
                    
                    if existing:
                        # Return a more user-friendly message
                        return JSONResponse(
                            status_code=409,  # Conflict
                            content={
                                "message": "This conversation already exists",
                                "conversation_id": existing["id"],
                                "chat_id": content_id_from_error,
                                "error_type": "duplicate_conversation"
                            }
                        )
            except Exception as recovery_error:
                logger.error(f"Error in recovery attempt: {str(recovery_error)}")
        
        # If we couldn't recover, return a general error
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "error_type": "general_error"}
        )




@router.get("/commands")
async def list_available_commands():
    """
    List all registered commands in the system.
    """
    commands = CommandFactory.get_available_commands()
    
    # Filter out web_search and puppeteer commands
    if "web_search" in commands:
        commands.remove("web_search")
    if "puppeteer" in commands:
        commands.remove("puppeteer")
        
    return {"commands": commands}


@router.get("/debug-image-status/{task_id}")
async def debug_image_status(task_id: str):
    """
    Debug endpoint for image status.
    """
    logger.info(f"Debug image status endpoint called for task: {task_id}")
    endpoint = f"/api/v1/pipeline/debug-image-status/{task_id}"
    
    # Ensure endpoint starts with a slash for consistency
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"
        
    return {
        "message": "Debug endpoint reached",
        "task_id": task_id,
        "endpoint": endpoint,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/image-poll/{task_id}")
async def poll_image_status(
    task_id: str,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Enhanced polling endpoint for image generation status.
    Designed specifically for client-side polling after server-sent events.
    """
    logger.info(f"Poll image status endpoint called for task: {task_id}")
    try:
        # Query the task table for the task
        query = """
        SELECT id, type, parameters, status, result, error, 
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE id = :task_id
        """

        task = await db.fetch_one(
            query=query,
            values={
                "task_id": task_id
            }
        )

        if not task:
            return {
                "status": "not_found",
                "task_id": task_id,
                "message": "Image generation task not found",
                "timestamp": datetime.now().isoformat()
            }

        task_dict = dict(task)
        response = {
            "task_id": task_id,
            "status": task_dict["status"],
            "timestamp": datetime.now().isoformat(),
            "conversation_id": conversation_id,
            "message_id": message_id
        }

        if task_dict["status"] == "completed" and task_dict["result"]:
            # Parse the result JSON
            result_data = json.loads(task_dict["result"])

            # Get the first image from the result
            image = result_data.get("images", [])[0] if result_data.get("images") else None

            if image:
                response.update({
                    "image_url": image["url"],
                    "image_id": image["id"],
                    "prompt": image["prompt"],
                    "created_at": image.get("created_at"),
                    "model": image.get("model")
                })
            else:
                # Result exists but no images found
                response.update({
                    "error": "No images found in completed result"
                })

        elif task_dict["status"] == "failed":
            response.update({
                "error": task_dict.get("error", "Unknown error occurred during image generation")
            })

        # Get progress information if available
        try:
            stages_query = """
            SELECT stage_number, completion_percentage, image_url
            FROM mo_image_stages
            WHERE task_id = :task_id
            ORDER BY stage_number
            """
            
            stages = await db.fetch_all(
                query=stages_query,
                values={"task_id": task_id}
            )
            
            if stages:
                # Find the highest completion percentage stage
                max_stage = max(stages, key=lambda x: x["completion_percentage"] if x["completion_percentage"] is not None else 0)
                response["progress"] = {
                    "percentage": max_stage["completion_percentage"],
                    "stage": max_stage["stage_number"],
                    "preview_url": max_stage["image_url"]
                }
        except Exception as stage_error:
            logger.error(f"Error getting stages: {str(stage_error)}")
            # Don't fail if stages query errors out
            
        # Include message information if we have conversation_id and message_id
        if conversation_id and message_id:
            try:
                message_query = """
                SELECT id, metadata, image_url 
                FROM mo_llm_messages
                WHERE id = :message_id AND conversation_id = :conversation_id
                """
                
                message = await db.fetch_one(
                    query=message_query,
                    values={
                        "message_id": message_id,
                        "conversation_id": conversation_id
                    }
                )
                
                if message:
                    # Extract message info
                    message_dict = dict(message)
                    metadata = {}
                    
                    if message_dict.get("metadata"):
                        try:
                            if isinstance(message_dict["metadata"], str):
                                metadata = json.loads(message_dict["metadata"])
                            else:
                                metadata = message_dict["metadata"]
                        except json.JSONDecodeError:
                            pass  # Invalid JSON in metadata
                            
                    # If message has an image URL, it takes precedence
                    if message_dict.get("image_url") and not response.get("image_url"):
                        response["image_url"] = message_dict["image_url"]
                        response["from_message"] = True
                        
                    # Include metadata image info if available
                    if metadata.get("image_url") and not response.get("image_url"):
                        response["image_url"] = metadata["image_url"]
                        response["image_id"] = metadata.get("image_id")
                        response["from_metadata"] = True
            except Exception as msg_error:
                logger.error(f"Error getting message info: {str(msg_error)}")
                # Don't fail if message query errors out
        
        return response

    except Exception as e:
        logger.error(f"Error in poll_image_status: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "task_id": task_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/image-poll/{task_id}")
async def poll_image_status(
    task_id: str,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Enhanced polling endpoint for image generation status.
    Designed specifically for client-side polling after server-sent events.
    """
    logger.info(f"Poll image status endpoint called for task: {task_id}")
    try:
        # Query the task table for the task
        query = """
        SELECT id, type, parameters, status, result, error, 
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE id = :task_id
        """

        task = await db.fetch_one(
            query=query,
            values={
                "task_id": task_id
            }
        )

        if not task:
            return {
                "status": "not_found",
                "task_id": task_id,
                "message": "Image generation task not found",
                "timestamp": datetime.now().isoformat()
            }

        task_dict = dict(task)
        response = {
            "task_id": task_id,
            "status": task_dict["status"],
            "timestamp": datetime.now().isoformat(),
            "conversation_id": conversation_id,
            "message_id": message_id
        }

        if task_dict["status"] == "completed" and task_dict["result"]:
            # Parse the result JSON
            result_data = json.loads(task_dict["result"])

            # Get the first image from the result
            image = result_data.get("images", [])[0] if result_data.get("images") else None

            if image:
                response.update({
                    "image_url": image["url"],
                    "image_id": image["id"],
                    "prompt": image["prompt"],
                    "created_at": image.get("created_at"),
                    "model": image.get("model")
                })
            else:
                # Result exists but no images found
                response.update({
                    "error": "No images found in completed result"
                })

        elif task_dict["status"] == "failed":
            response.update({
                "error": task_dict.get("error", "Unknown error occurred during image generation")
            })

        # Get progress information if available
        try:
            stages_query = """
            SELECT stage_number, completion_percentage, image_url
            FROM mo_image_stages
            WHERE task_id = :task_id
            ORDER BY stage_number
            """
            
            stages = await db.fetch_all(
                query=stages_query,
                values={"task_id": task_id}
            )
            
            if stages:
                # Find the highest completion percentage stage
                max_stage = max(stages, key=lambda x: x["completion_percentage"] if x["completion_percentage"] is not None else 0)
                response["progress"] = {
                    "percentage": max_stage["completion_percentage"],
                    "stage": max_stage["stage_number"],
                    "preview_url": max_stage["image_url"]
                }
        except Exception as stage_error:
            logger.error(f"Error getting stages: {str(stage_error)}")
            # Don't fail if stages query errors out
            
        # Include message information if we have conversation_id and message_id
        if conversation_id and message_id:
            try:
                message_query = """
                SELECT id, metadata, image_url 
                FROM mo_llm_messages
                WHERE id = :message_id AND conversation_id = :conversation_id
                """
                
                message = await db.fetch_one(
                    query=message_query,
                    values={
                        "message_id": message_id,
                        "conversation_id": conversation_id
                    }
                )
                
                if message:
                    # Extract message info
                    message_dict = dict(message)
                    metadata = {}
                    
                    if message_dict.get("metadata"):
                        try:
                            if isinstance(message_dict["metadata"], str):
                                metadata = json.loads(message_dict["metadata"])
                            else:
                                metadata = message_dict["metadata"]
                        except json.JSONDecodeError:
                            pass  # Invalid JSON in metadata
                            
                    # If message has an image URL, it takes precedence
                    if message_dict.get("image_url") and not response.get("image_url"):
                        response["image_url"] = message_dict["image_url"]
                        response["from_message"] = True
                        
                    # Include metadata image info if available
                    if metadata.get("image_url") and not response.get("image_url"):
                        response["image_url"] = metadata["image_url"]
                        response["image_id"] = metadata.get("image_id")
                        response["from_metadata"] = True
            except Exception as msg_error:
                logger.error(f"Error getting message info: {str(msg_error)}")
                # Don't fail if message query errors out
        
        return response

    except Exception as e:
        logger.error(f"Error in poll_image_status: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "task_id": task_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/api-info")
async def api_info(
    current_user: dict = Depends(get_user)
):
    """Return API info for debugging"""
    try:
        return {
            "status": "ok",
            "version": "1.0.0", 
            "timestamp": datetime.now().isoformat(),
            "user": {
                "id": current_user.get('id', current_user.get('uid')),
                "username": current_user.get('username', 'unknown')
            },
            "endpoints": {
                "conversation_by_content": "/api/v1/pipeline/conversation/by-content/{chat_id}",
                "conversation_by_id": "/api/v1/pipeline/conversation/{conversation_id}"
            },
            "features": {
                "web_search": False,  # Indicate these features are disabled
                "puppeteer": False
            }
        }
    except Exception as e:
        logger.error(f"Error in api_info: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }
        
@router.get("/diagnostics")
async def run_diagnostics(
    repair: bool = False,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Run diagnostics on the conversation system and optionally repair issues.
    """
    try:
        results = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "user_id": current_user.get('id', current_user.get('uid')),
            "issues": [],
            "fixed": []
        }
        
        # 1. Check for orphaned conversations (chat_id doesn't exist in mo_chat)
        orphaned_query = """
        SELECT c.id, c.chat_id, c.user_id 
        FROM mo_llm_conversations c
        LEFT JOIN mo_chat m ON c.chat_id = m.uuid
        WHERE m.uuid IS NULL AND c.chat_id IS NOT NULL
        LIMIT 50
        """
        orphaned = await db.fetch_all(orphaned_query)
        
        if orphaned:
            results["issues"].append({
                "type": "orphaned_conversations",
                "count": len(orphaned),
                "details": [dict(row) for row in orphaned[:5]]  # Show first 5 for sample
            })
            
            # Repair if requested
            if repair:
                fixed_count = 0
                for row in orphaned:
                    chat_id = row['chat_id']
                    user_id = row['user_id']
                    
                    try:
                        # Create a new content entry
                        route = f"repair-{uuid.uuid4().hex[:8]}"  # Generate unique route
                        content_insert = """
                        INSERT INTO mo_chat 
                        (uuid, firebase_uid, name, description, route, status) 
                        VALUES 
                        (:uuid, :firebase_uid, :name, :description, :route, 'draft')
                        ON CONFLICT (uuid) DO NOTHING
                        RETURNING uuid
                        """
                        
                        content_values = {
                            "uuid": chat_id,
                            "firebase_uid": user_id,
                            "name": f"Repaired Content {chat_id[:8]}",
                            "description": "Automatically repaired content for orphaned conversation",
                            "route": route
                        }
                        
                        result = await db.fetch_one(content_insert, content_values)
                        if result:
                            fixed_count += 1
                    except Exception as e:
                        logger.error(f"Error fixing orphaned conversation: {str(e)}")
                
                results["fixed"].append({
                    "type": "orphaned_conversations",
                    "count": fixed_count
                })
        
        # 2. Check for inconsistent content entries
        inconsistent_query = """
        SELECT id, uuid, firebase_uid, name, route 
        FROM mo_chat
        WHERE route IS NULL OR name IS NULL OR firebase_uid IS NULL
        LIMIT 20
        """
        inconsistent = await db.fetch_all(inconsistent_query)
        
        if inconsistent:
            results["issues"].append({
                "type": "inconsistent_content",
                "count": len(inconsistent),
                "details": [dict(row) for row in inconsistent[:5]]  # Show first 5
            })
            
            # Repair if requested
            if repair:
                fixed_count = 0
                for row in inconsistent:
                    try:
                        # Update with valid values
                        update_query = """
                        UPDATE mo_chat
                        SET 
                            name = COALESCE(name, :default_name),
                            route = COALESCE(route, :default_route),
                            firebase_uid = COALESCE(firebase_uid, :default_uid)
                        WHERE id = :id
                        RETURNING id
                        """
                        
                        values = {
                            "id": row["id"],
                            "default_name": f"Fixed Content {row['id']}",
                            "default_route": f"fixed-{uuid.uuid4().hex[:8]}",
                            "default_uid": current_user.get('id', current_user.get('uid')) or row["firebase_uid"] or "qbrm9IljDFdmGPVlw3ri3eLMVIA2"
                        }
                        
                        result = await db.fetch_one(update_query, values)
                        if result:
                            fixed_count += 1
                    except Exception as e:
                        logger.error(f"Error fixing inconsistent content: {str(e)}")
                
                results["fixed"].append({
                    "type": "inconsistent_content",
                    "count": fixed_count
                })
        
        # 3. Check for total counts
        count_query = """
        SELECT 
            (SELECT COUNT(*) FROM mo_chat) AS content_count,
            (SELECT COUNT(*) FROM mo_llm_conversations) AS conversation_count,
            (SELECT COUNT(*) FROM mo_llm_messages) AS message_count
        """
        counts = await db.fetch_one(count_query)
        
        results["counts"] = dict(counts)
        
        return results
    
    except Exception as e:
        logger.error(f"Error in diagnostics: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/image-status/{task_id}")
async def get_image_status(
    task_id: str,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Get the status of an image generation task.
    Updated to use REST-based approach.
    """
    logger.info(f"Received request for image status, task_id: {task_id}")
    try:
        # Determine the media API URL (same server)
        # Use relative URL since we're on the same server
        api_url = f"/api/v1/media/image-status/{task_id}"
        
        # Ensure api_url starts with a slash for consistency
        if not api_url.startswith("/"):
            api_url = f"/{api_url}"
            
        # Get token from current_user for authentication
        token = current_user.get("token", "")
        
        # Make HTTP request to our REST endpoint
        async with httpx.AsyncClient() as client:
            try:
                headers = {"Authorization": f"Bearer {token}"}
                
                # Forward the request to our media endpoint
                response = await client.get(
                    api_url, 
                    headers=headers
                )
                
                if response.status_code == 200:
                    # Success - return the media endpoint response
                    return response.json()
                else:
                    # Request failed
                    return {
                        "status": "failed",
                        "error": f"Status check failed: {response.text}"
                    }
            except Exception as request_error:
                logger.error(f"Error making API request: {str(request_error)}")
                return {
                    "status": "error",
                    "error": f"API request error: {str(request_error)}"
                }
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting image status: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/image/{task_id}")
async def get_image(
    task_id: str,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Get the status of an image generation task.
    Compatibility endpoint for existing client code.
    """
    logger.info(f"Received request for image, task_id: {task_id}")
    try:
        # Query the task table for the task
        query = """
        SELECT id, type, parameters, status, result, error, 
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE id = :task_id
        """

        task = await db.fetch_one(
            query=query,
            values={
                "task_id": task_id
            }
        )

        if not task:
            raise HTTPException(status_code=404, detail="Image task not found")

        task_dict = dict(task)

        if task_dict["status"] == "completed" and task_dict["result"]:
            # Parse the result JSON
            result_data = json.loads(task_dict["result"])

            # Get the first image from the result
            image = result_data.get("images", [])[
                0] if result_data.get("images") else None

            if image:
                # FIX: Return url field that matches what the frontend expects
                return {
                    "status": "completed",
                    # CHANGED: image_url -> url for frontend compatibility
                    "url": image["url"],
                    # Keep this for backward compatibility
                    "image_url": image["url"],
                    "image_id": image["id"],
                    "prompt": image["prompt"],
                    "model": image["model"],
                }
            else:
                # Result exists but no images found
                return {
                    "status": "failed",
                    "error": "No images found in completed result"
                }

        elif task_dict["status"] == "failed":
            return {
                "status": "failed",
                "error": task_dict.get("error", "Unknown error occurred during image generation")
            }
        else:
            # Still processing - return progress information
            return {
                "status": "processing",
                "message": "Image generation is still in progress"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting image: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_message_by_id(
    message_id: str,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Get a specific message with all its results by ID.
    This is useful as a fallback mechanism if streaming fails.
    """
    try:
        # Get the message
        message_query = """
        SELECT id, conversation_id, role, content, created_at, metadata
        FROM mo_llm_messages
        WHERE id = :message_id
        """
        message = await db.fetch_one(
            query=message_query,
            values={"message_id": message_id}
        )
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
            
        # Convert to dict
        message_dict = dict(message)
        
        # Parse metadata if present
        if message_dict.get("metadata"):
            try:
                message_dict["metadata"] = json.loads(message_dict["metadata"])
            except:
                pass
                
        # Get the conversation to check permission
        conversation_id = message_dict["conversation_id"]
        conversation = await get_conversation_by_id(db, conversation_id)
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
            
        # Check user permission
        user_id = current_user.get('id', current_user.get('uid'))
        if conversation["user_id"] != user_id:
            raise HTTPException(
                status_code=403, 
                detail="You don't have permission to access this message"
            )
            
        return {"message": message_dict}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting message: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# Add this endpoint to pipeline_router.py

@router.delete("/conversation/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Delete a conversation by ID and its associated messages"""
    try:
        # First, check if the conversation exists and belongs to the user
        conversation = await get_conversation_by_id(db, conversation_id)

        if not conversation:
            raise HTTPException(
                status_code=404, detail="Conversation not found")

        # Verify ownership
        user_id = current_user.get("uid", current_user.get("id"))
        if conversation["user_id"] != user_id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to delete this conversation"
            )
        logger.info(f"Deleting conversation: {conversation_id}")

        # Transaction to delete messages and conversation
        async with db.transaction():
            # STEP 1: First delete all function calls associated with messages
            delete_function_calls_query = """
            DELETE FROM mo_llm_function_calls
            WHERE message_id IN (
                SELECT id FROM mo_llm_messages 
                WHERE conversation_id = :conversation_id
            )
            """
            await db.execute(
                query=delete_function_calls_query,
                values={"conversation_id": conversation_id}
            )

            # STEP 2: Then delete all messages
            delete_messages_query = """
            DELETE FROM mo_llm_messages
            WHERE conversation_id = :conversation_id
            """
            await db.execute(
                query=delete_messages_query,
                values={"conversation_id": conversation_id}
            )

            # STEP 3: Finally delete the conversation
            delete_conversation_query = """
            DELETE FROM mo_llm_conversations
            WHERE id = :conversation_id
            """
            await db.execute(
                query=delete_conversation_query,
                values={"conversation_id": conversation_id}
            )

            # Optional: Handle content as before
            chat_id = conversation.get("chat_id")
            # ... rest of your content handling code ...
            logger.info(f"Deleted conversation: {conversation_id}")
            logger.info(f"Content ID: {chat_id}")
            # update mo_chat status to 'deleted' - use uuid column, not id
            if chat_id:
                update_content_status_query = """
                UPDATE mo_chat
                SET status = 'deleted'
                WHERE uuid = :chat_id
                """
                await db.execute(
                    query=update_content_status_query,
                    values={"chat_id": chat_id}
                )

        return {
            "success": True,
            "message": "Conversation deleted successfully",
            "conversation_id": conversation_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Failed to delete conversation: {str(e)}")

# Define a new model for the init request


class InitConversationRequest(BaseModel):
    chat_id: str
    title: Optional[str] = None
    model_id: Optional[str] = "grok-3-mini-beta"
    
    model_config = {
        'protected_namespaces': ()
    }


@router.post("/conversation/init")
async def init_conversation(
    request: InitConversationRequest,
    idempotency_key: Optional[str] = Header(None),
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Create a new thread by creating a new content that references the original"""
    user_id = current_user.get("uid")
    original_content_id = request.chat_id

    logger.info(
        f"init_conversation: Creating new thread for original chat_id={original_content_id}, user_id={user_id}")

    try:
        # Get original content details for reference
        orig_content_query = """
        SELECT uuid, name, description, route, status FROM mo_chat 
        WHERE uuid = :uuid
        """
        orig_content = await db.fetch_one(query=orig_content_query, values={"uuid": original_content_id})

        if not orig_content:
            raise HTTPException(
                status_code=404, detail="Original content not found")

        # Generate a UUID for the new content
        new_content_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Get thread count to create a unique name - FIXED QUERY
        # Instead of trying to use complex JSON operations, let's use a simpler approach
        # Look for content items where the metadata contains the parent_content_id
        # Using the JSONB containment operator @>
        count_query = """
        SELECT COUNT(*) as count FROM mo_chat 
        WHERE firebase_uid = :user_id AND 
              (metadata IS NOT NULL AND 
               metadata::jsonb->>'parent_content_id' = :original_content_id)
        """
        count_result = await db.fetch_one(
            query=count_query,
            values={
                "user_id": user_id,
                "original_content_id": original_content_id
            }
        )
        thread_number = (
            count_result["count"] + 2) if count_result and count_result["count"] is not None else 2

        # Create metadata with reference to original content
        metadata = json.dumps({
            "parent_content_id": original_content_id,
            "is_thread": True,
            "thread_number": thread_number,
            "original_name": orig_content["name"]
        })

        # Create a new route
        route = f"thread-{thread_number}-{uuid.uuid4().hex[:8]}"

        # Create a new content entry
        content_insert = """
        INSERT INTO mo_chat 
        (uuid, firebase_uid, name, description, route, status, metadata) 
        VALUES 
        (:uuid, :user_id, :name, :description, :route, :status, :metadata)
        RETURNING uuid, name
        """

        new_title = request.title or f"Thread {thread_number}"
        thread_name = f"{new_title} - {orig_content['name']}"

        content_values = {
            "uuid": new_content_id,
            "user_id": user_id,
            "name": thread_name,
            "description": f"Thread {thread_number} of {orig_content['name']}",
            "route": route,
            "status": orig_content["status"],
            "metadata": metadata
        }

        new_content = await db.fetch_one(query=content_insert, values=content_values)
        if not new_content:
            raise HTTPException(
                status_code=500, detail="Failed to create new content for thread")

        logger.info(
            f"Created new content {new_content_id} for thread {thread_number} of {original_content_id}")

        # Now create a conversation for the new content
        conversation_id = str(uuid.uuid4())

        conversation_insert = """
        INSERT INTO mo_llm_conversations 
        (id, user_id, chat_id, model_id, title, created_at, updated_at) 
        VALUES 
        (:id, :user_id, :chat_id, :model_id, :title, :created_at, :updated_at)
        RETURNING id
        """

        conversation_values = {
            "id": conversation_id,
            "user_id": user_id,
            "chat_id": new_content_id,
            "model_id": request.model_id,
            "title": new_title or f"Thread {thread_number}",
            "created_at": now,
            "updated_at": now
        }

        conversation = await db.fetch_one(query=conversation_insert, values=conversation_values)
        if not conversation:
            raise HTTPException(
                status_code=500, detail="Failed to create conversation for new thread")

        logger.info(
            f"Created new conversation {conversation_id} for content {new_content_id}")

        # Return both the new content and conversation IDs
        return {
            "id": conversation_id,
            "chat_id": new_content_id,
            "content_name": thread_name,
            "thread_number": thread_number,
            "original_content_id": original_content_id,
            "success": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in init_conversation: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Failed to create new thread: {str(e)}")

class SaveMessageRequest(BaseModel):
    message_id: str
    conversation_id: str
    content: str
    role: Optional[str] = "assistant"
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "message_id": "msg_123",
                "conversation_id": "conv_456",
                "content": "Hello, how can I help you?",
                "role": "assistant",
                "metadata": {"source": "api"}
            }
        }
    }

@router.post("/message/save")
async def save_message(
    message_data: SaveMessageRequest,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Explicitly save a message that may have failed to save during streaming"""
    try:
        # First check if message already exists
        check_query = """
        SELECT id FROM mo_llm_messages 
        WHERE id = :message_id
        """
        existing = await db.fetch_one(
            query=check_query, 
            values={"message_id": message_data.message_id}
        )
        
        if existing:
            # Message exists, update it
            update_query = """
            UPDATE mo_llm_messages
            SET content = :content, metadata = :metadata
            WHERE id = :message_id
            RETURNING id
            """
            result = await db.fetch_one(
                query=update_query,
                values={
                    "message_id": message_data.message_id,
                    "content": message_data.content,
                    "metadata": json.dumps(message_data.metadata)
                }
            )
            return {"message": "Message updated", "id": result["id"]}
        else:
            # Message doesn't exist, create it
            insert_query = """
            INSERT INTO mo_llm_messages (
                id, conversation_id, role, content, created_at, metadata
            ) VALUES (
                :message_id, :conversation_id, :role, :content, 
                CURRENT_TIMESTAMP, :metadata
            ) RETURNING id
            """
            result = await db.fetch_one(
                query=insert_query,
                values={
                    "message_id": message_data.message_id,
                    "conversation_id": message_data.conversation_id,
                    "role": message_data.role,
                    "content": message_data.content,
                    "metadata": json.dumps(message_data.metadata)
                }
            )
            return {"message": "Message created", "id": result["id"]}
            
    except Exception as e:
        logger.error(f"Error in save_message: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/message/{message_id}")
async def get_message(
    message_id: str,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get a specific message by ID"""
    try:
        query = """
        SELECT * FROM mo_llm_messages 
        WHERE id = :message_id
        """
        message = await db.fetch_one(
            query=query,
            values={"message_id": message_id}
        )
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
            
        return dict(message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
