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
from datetime import datetime, timezone
import traceback
import re
from firebase_admin import auth as firebase_auth

from .commands.base import Pipeline, CommandFactory
from .commands.intent_detector import detect_intents, MultilingualIntentDetector
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
    content_id: Optional[str] = None
    message: str
    model: Optional[str] = "grok-2-1212"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    stream: bool = True


class CommandResult(BaseModel):
    type: str
    content: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class MultiIntentResponse(BaseModel):
    conversation_id: str
    message_id: str
    detected_intents: List[str]
    results: List[CommandResult]
    content: str


class CreateConversationRequest(BaseModel):
    content_id: str
    title: Optional[str] = None
    model: Optional[str] = "grok-2-1212"


class Conversation(BaseModel):
    id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime
    content_id: Optional[str] = None
    user_id: str
    message_count: int = 0


class GetOrCreateConversationRequest(BaseModel):
    content_id: str
    model_id: Optional[str] = "grok-2-1212"
    title: Optional[str] = None
    

async def get_or_create_conversation(content_id: str, user_id: str, model_id: str, title: str, db: Database):
    """Get or create a conversation with database-level uniqueness"""
    try:
        # First check if the content exists in mo_content
        content_check_query = "SELECT uuid FROM mo_content WHERE uuid = :uuid"
        content_exists = await db.fetch_one(query=content_check_query, values={"uuid": content_id})
        
        if not content_exists:
            logger.warning(f"Content ID {content_id} does not exist in mo_content table")
            # Try to create content entry automatically
            try:
                # Create a new content entry
                route = f"auto-{uuid.uuid4().hex[:8]}"  # Generate unique route
                content_insert = """
                INSERT INTO mo_content 
                (uuid, firebase_uid, name, description, route, status) 
                VALUES 
                (:uuid, :firebase_uid, :name, :description, :route, 'draft')
                ON CONFLICT (uuid) DO NOTHING
                RETURNING uuid
                """
                
                content_values = {
                    "uuid": content_id,
                    "firebase_uid": user_id,
                    "name": f"Auto-created Content {content_id[:8]}",
                    "description": "Automatically created content for conversation",
                    "route": route
                }
                
                content_result = await db.fetch_one(content_insert, content_values)
                if content_result:
                    logger.info(f"Created missing content entry: {content_id}")
                else:
                    logger.warning(f"Failed to create content entry for {content_id}")
            except Exception as content_error:
                logger.error(f"Error creating content entry: {str(content_error)}")
                # Continue anyway - the transaction below will fail if content doesn't exist
        
        async with db.transaction():
            # Try to get an existing conversation
            query = """
            SELECT id FROM mo_llm_conversations 
            WHERE content_id = :content_id AND user_id = :user_id
            """
            existing = await db.fetch_one(query=query, values={"content_id": content_id, "user_id": user_id})

            if existing:
                logger.info(
                    f"Found existing conversation {existing['id']} for content {content_id}, user {user_id}")
                return existing["id"]

            # Create new conversation if none exists
            new_id = str(uuid.uuid4())
            insert_query = """
            INSERT INTO mo_llm_conversations 
            (id, user_id, content_id, model_id, title)
            VALUES (:id, :user_id, :content_id, :model_id, :title)
            RETURNING id
            """
            values = {
                "id": new_id,
                "user_id": user_id,
                "content_id": content_id,
                "model_id": model_id,
                "title": title or f"Conversation about {content_id}"
            }

            result = await db.fetch_one(query=insert_query, values=values)
            logger.info(
                f"Created new conversation {result['id']} for content {content_id}, user {user_id}")
            return result["id"]
    except Exception as e:
        logger.error(f"Error in get_or_create_conversation: {str(e)}")
        # If there was an error, try to get again (might be a concurrent insert)
        query = """
        SELECT id FROM mo_llm_conversations 
        WHERE content_id = :content_id AND user_id = :user_id
        """
        existing = await db.fetch_one(query=query, values={"content_id": content_id, "user_id": user_id})

        if existing:
            logger.info(f"Recovered conversation {existing['id']} after error")
            return existing["id"]

        # If recovery failed, re-raise
        raise



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


async def create_conversation(db: Database, user_id: str, title: str = None, content_id: Optional[str] = None, model: str = "grok-2-1212"):
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
        id, user_id, title, model_id, created_at, updated_at, content_id
    ) VALUES (
        :id, :user_id, :title, :model, :created_at, :updated_at, :content_id
    ) RETURNING id
    """

    values = {
        "id": conversation_id,
        "user_id": user_id,
        "title": title,
        "model": model,
        "created_at": now,
        "updated_at": now,
        "content_id": content_id
    }

    await db.execute(query=query, values=values)
    return conversation_id


async def get_conversation_by_id(db: Database, conversation_id: str):
    """Get a conversation by ID"""
    query = """
    SELECT 
        id, user_id, title, model_id as model, 
        created_at, updated_at, content_id,
        (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count
    FROM mo_llm_conversations 
    WHERE id = :conversation_id
    """

    result = await db.fetch_one(query=query, values={"conversation_id": conversation_id})
    if not result:
        return None

    return dict(result)


async def get_conversation_by_content_id(db: Database, content_id: str, user_id: str):
    """Get a conversation by content ID"""
    query = """
    SELECT 
        id, user_id, title, model_id as model, 
        created_at, updated_at, content_id,
        (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count
    FROM mo_llm_conversations 
    WHERE content_id = :content_id
    AND user_id = :user_id
    ORDER BY created_at DESC
    LIMIT 1
    """

    result = await db.fetch_one(
        query=query,
        values={
            "content_id": content_id,
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
    Process the pipeline response for streaming.
    """
    # First yield detected intents
    intents_message = {
        "detected_intents": list(context.get("intents", {}).keys())
    }
    yield f"data: {json.dumps(intents_message)}\n\n"

    # Process each result individually with proper type signaling
    for result in context.get("results", []):
        # Skip general_knowledge as it will be part of the content stream
        if result.get("type") == "general_knowledge":
            continue

        # Create a properly formatted result message with result_type field
        result_message = {
            "result_type": result.get("type"),
            "result": result
        }

        # Add current command info
        if "current_command" in context:
            result_message["current_command"] = context["current_command"]
        
        

        # Send each result with clear completion marker
        yield f"data: {json.dumps(result_message)}\n\n"
        # Add a small delay to ensure frontend processes each message
        await asyncio.sleep(0.05)
        
        # Send a completion signal for this specific result
        yield f"data: {json.dumps({'result_complete': result.get('type')})}\n\n"
        await asyncio.sleep(0.05)

    # Finally stream the content if available
    if "general_knowledge_content" in context:
        content = context["general_knowledge_content"]
        # Stream in chunks
        chunk_size = 100
        
        # Signal start of content
        yield f"data: {json.dumps({'content_start': True})}\n\n"
        
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i+chunk_size]
            yield f"data: {json.dumps({'content': chunk})}\n\n"
            # Small delay for natural streaming effect
            await asyncio.sleep(0.02)
    
    # Send a final summary message with all completed results
    summary = {
        "summary": {
            "completed_results": [r.get("type") for r in context.get("results", []) if r.get("type") != "general_knowledge"],
            "all_complete": True
        }
    }
    yield f"data: {json.dumps(summary)}\n\n"

    # End the stream
    yield "data: [DONE]\n\n"


async def process_multi_intent_request(
    request: MultiIntentChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict,
    db: Database
) -> Dict[str, Any]:
    """
    Process a multi-intent request using the pipeline pattern.
    """
    # Log the user for debugging
    logger.info(
        f"Processing request for user: {current_user.get('id', current_user.get('uid', 'unknown'))}")

    # Detect intents in the message
    intents = detect_intents(request.message)
    
    # Filter out low-confidence intents for logging
    significant_intents = {k: v for k, v in intents.items() if v["confidence"] > 0.3}
    
    # Filter out web_search and puppeteer intents
    if "web_search" in significant_intents:
        del significant_intents["web_search"]
    if "puppeteer" in significant_intents:
        del significant_intents["puppeteer"]
    
    logger.info(f"Detected intents: {list(significant_intents.keys())}")

    # Create or get conversation
    conversation_id = request.conversation_id
    if not conversation_id:
        title = f"Multi-Intent: {request.message[:30]}..." if len(
            request.message) > 30 else request.message
        conversation_id = await create_conversation(
            db=db,
            user_id=current_user.get('id', current_user.get('uid')),
            title=title,
            content_id=request.content_id
        )

    # Store user message in database
    user_message_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

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
            "metadata": json.dumps({"multi_intent": True, "detected_intents": list(significant_intents.keys())})
        }
    )

    # Create initial context
    context = {
        "message": request.message,
        "conversation_id": conversation_id,
        "user_id": current_user.get('id', current_user.get('uid')),
        "db": db,
        "background_tasks": background_tasks,
        "current_user": current_user,
        "intents": significant_intents,
        "model": request.model,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens
    }

    # Create pipeline based on intents
    pipeline = Pipeline(name="MultiIntentPipeline")

    # REMOVED web search and puppeteer commands    

    # Initialize skip_general_knowledge flag
    skip_general_knowledge = False

    # REMOVED web search and puppeteer commands

    # Calculation command for math operations
    if "calculation" in significant_intents:
        pipeline.add_command(CommandFactory.create("calculation"))

    # Image generation next (if present)
    if "image_generation" in significant_intents:
        pipeline.add_command(CommandFactory.create("image_generation"))
        # Skip general knowledge for image generation requests
        skip_general_knowledge = True
        logger.info(
            f"Skipping general_knowledge because image_generation intent was detected")

    # Social media content generation next
    if "social_media" in significant_intents:
        pipeline.add_command(CommandFactory.create("social_media"))
        # Skip general knowledge for social media requests
        skip_general_knowledge = True
        logger.info(
            f"Skipping general_knowledge because social_media intent was detected")

    # Add conversation command for simple chats/greetings
    if "conversation" in significant_intents:
        pipeline.add_command(CommandFactory.create("conversation"))
        # ALWAYS add general knowledge command when conversation intent is detected
        # since conversation command doesn't generate text itself
        pipeline.add_command(CommandFactory.create("general_knowledge"))
    else:
        # Only add general knowledge if we haven't decided to skip it
        if not skip_general_knowledge and significant_intents.get("general_knowledge", {}).get("confidence", 0) > 0.3:
            pipeline.add_command(CommandFactory.create("general_knowledge"))

    # Execute the pipeline
    result_context = await pipeline.execute(context)

    # Return the context for further processing
    return result_context

# ADDED NEW ENDPOINTS FOR CONVERSATION MANAGEMENT


# Legacy endpoint - but use new implementation internally for safety
@router.post("/conversation")
async def create_conversation(
    request: GetOrCreateConversationRequest,
    idempotency_key: Optional[str] = Header(None),
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Create a new conversation - using the get-or-create pattern internally"""
    # Reuse the idempotent endpoint to avoid duplicates
    return await get_or_create_conversation_endpoint(request, idempotency_key, db, current_user)


@router.post("/conversation/get-or-create")
@idempotent("get_or_create_conversation")
async def get_or_create_conversation_endpoint(
    request: GetOrCreateConversationRequest,
    idempotency_key: Optional[str] = Header(None),
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Get an existing conversation or create a new one with idempotency support"""
    user_id = current_user.get("uid")
    if not user_id:
        logger.warning("Using fallback user: qbrm9IljDFdmGPVlw3ri3eLMVIA2")
        user_id = "qbrm9IljDFdmGPVlw3ri3eLMVIA2"

    conversation_id = await get_or_create_conversation(
        request.content_id, user_id, request.model_id, request.title, db
    )

    return {"id": conversation_id, "content_id": request.content_id, "user_id": user_id}


# Endpoint removed - consolidated into get_conversation_by_content

# Get a conversation by content ID
@router.get("/conversation/by-content/{content_id}")
async def get_conversation_by_content(
    content_id: str,
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Get a conversation by content ID with all associated messages"""
    try:
        logger.info(f"Content ID endpoint called for: {content_id}")
        
        # Get user ID
        user_id = current_user.get("uid")
        
        logger.info(f"Getting conversation and messages for content {content_id}, user {user_id}")

        # Updated query to fetch conversations and messages in one request
        query = """
        SELECT c.id as conversation_id, c.user_id, c.content_id, c.model_id, c.title, 
               c.created_at as conversation_created_at, c.updated_at, c.metadata as conversation_metadata,
               m.id as message_id, m.role, m.content as message_content, 
               m.created_at as message_created_at, m.function_call, 
               m.metadata as message_metadata, m.image_url, m.image_metadata
        FROM mo_llm_conversations c
        LEFT JOIN mo_llm_messages m ON c.id = m.conversation_id
        WHERE c.content_id = :content_id AND c.user_id = :user_id
        ORDER BY c.created_at DESC, m.created_at ASC
        """
        results = await db.fetch_all(query=query, values={"content_id": content_id, "user_id": user_id})

        if not results:
            logger.info(f"No existing conversation found for content {content_id}")
            return {"conversation": None, "messages": [], "found": False}

        # Extract conversation details from the first row
        first_row = dict(results[0]) if results else {}
        conversation = {
            "id": first_row.get("conversation_id"),
            "user_id": first_row.get("user_id"),
            "content_id": first_row.get("content_id"),
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

        logger.info(f"Found conversation with {len(messages)} messages for content {content_id}")
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
    request: MultiIntentChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Stream a multi-intent chat response.
    """
    try:
        # Process the request
        result_context = await process_multi_intent_request(request, background_tasks, current_user, db)
        
        # Store results in DB before streaming
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Create assistant message record
        response_content = ""
        # Extract content from general knowledge if available
        if "general_knowledge_content" in result_context:
            response_content = result_context["general_knowledge_content"]
        
        # Create metadata with all results for later retrieval
        metadata = {
            "multi_intent": True,
            "detected_intents": [intent for intent in result_context.get("intents", {}).keys() 
                               if result_context["intents"][intent]["confidence"] > 0.3],
            "results": result_context.get("results", []),
            "message_id": message_id
        }
        
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
            
            # Update the message_id in the context
            result_context["message_id"] = message_id
        else:
            # Use existing message ID
            result_context["message_id"] = existing_message["id"]
            logger.info(f"Using existing message: {existing_message['id']}")

        # Return streaming response with proper headers to prevent caching
        return StreamingResponse(
            process_streaming_response(result_context),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )

    except Exception as e:
        logger.error(f"Error in stream_multi_intent_chat: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
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
    return {
        "message": "Debug endpoint reached",
        "task_id": task_id,
        "endpoint": "/api/v1/pipeline/debug-image-status/{task_id}",
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
                "conversation_by_content": "/api/v1/pipeline/conversation/by-content/{content_id}",
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
        
        # 1. Check for orphaned conversations (content_id doesn't exist in mo_content)
        orphaned_query = """
        SELECT c.id, c.content_id, c.user_id 
        FROM mo_llm_conversations c
        LEFT JOIN mo_content m ON c.content_id = m.uuid
        WHERE m.uuid IS NULL AND c.content_id IS NOT NULL
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
                    content_id = row['content_id']
                    user_id = row['user_id']
                    
                    try:
                        # Create a new content entry
                        route = f"repair-{uuid.uuid4().hex[:8]}"  # Generate unique route
                        content_insert = """
                        INSERT INTO mo_content 
                        (uuid, firebase_uid, name, description, route, status) 
                        VALUES 
                        (:uuid, :firebase_uid, :name, :description, :route, 'draft')
                        ON CONFLICT (uuid) DO NOTHING
                        RETURNING uuid
                        """
                        
                        content_values = {
                            "uuid": content_id,
                            "firebase_uid": user_id,
                            "name": f"Repaired Content {content_id[:8]}",
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
        FROM mo_content
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
                        UPDATE mo_content
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
            (SELECT COUNT(*) FROM mo_content) AS content_count,
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


@router.get("/message/{message_id}")
@router.get("/image-status/{task_id}")
async def get_image_status(
    task_id: str,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """
    Get the status of an image generation task.
    """
    logger.info(f"Received request for image status, task_id: {task_id}")
    try:
        # Query the task table for the task
        query = """
        SELECT id, type, parameters, status, result, error, 
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE id = :task_id
        """
        
        logger.info(f"Executing DB query for task_id: {task_id}")
        task = await db.fetch_one(
            query=query,
            values={
                "task_id": task_id
            }
        )
        
        if not task:
            logger.warning(f"Task not found: {task_id}")
            raise HTTPException(status_code=404, detail="Image generation task not found")
        
        task_dict = dict(task)
        logger.info(f"Found task with status: {task_dict['status']}")
        
        if task_dict["status"] == "completed" and task_dict["result"]:
            # Parse the result JSON
            result_data = json.loads(task_dict["result"])
            
            # Get the first image from the result
            image = result_data.get("images", [])[0] if result_data.get("images") else None
            
            if image:
                logger.info(f"Returning completed image: {image['id']}")
                return {
                    "status": "completed",
                    "image_url": image["url"],
                    "image_id": image["id"],
                    "prompt": image["prompt"],
                    "model": image["model"],
                    "created_at": task_dict["created_at"].isoformat() if task_dict["created_at"] else None,
                    "completed_at": task_dict["completed_at"].isoformat() if task_dict["completed_at"] else None
                }
            else:
                # Result exists but no images found
                logger.warning(f"Task {task_id} completed but no images found")
                return {
                    "status": "failed",
                    "error": "No images found in completed result"
                }
                
        elif task_dict["status"] == "failed":
            logger.warning(f"Task {task_id} failed: {task_dict.get('error', 'Unknown error')}")
            return {
                "status": "failed",
                "error": task_dict.get("error", "Unknown error occurred during image generation")
            }
        else:
            # Still processing
            logger.info(f"Task {task_id} is still processing")
            return {
                "status": "processing",
                "message": "Image generation is still in progress"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting image status: {str(e)}")
        logger.error(traceback.format_exc())
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
