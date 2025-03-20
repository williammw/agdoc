"""
Pipeline Router - Implements the Pipeline and Command pattern for multi-intent processing.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request, Header, Cookie
from fastapi.responses import StreamingResponse, JSONResponse
from app.dependencies import get_current_user, get_database
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
from .commands.intent_detector import detect_intents
# Import commands to register them with the factory
from .commands.web_search_command import WebSearchCommand
from .commands.image_generation_command import ImageGenerationCommand
from .commands.social_media_command import SocialMediaCommand
from .commands.puppeteer_command import PuppeteerCommand
from .commands.general_knowledge_command import GeneralKnowledgeCommand

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

# Custom authentication function that uses the existing get_current_user from dependencies


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
            if result.get("type") == "web_search" and result.get("content"):
                content_sections.append(
                    "## Web Search Results\n\nI searched the web and found relevant information for your query.")
            elif result.get("type") == "image_generation" and result.get("prompt"):
                content_sections.append(
                    f"## Image Generation\n\nI've generated an image based on: '{result.get('prompt')}'")
            elif result.get("type") == "social_media" and result.get("content"):
                platforms = result.get("platforms", [])
                content_sections.append(
                    f"## Social Media Content for {', '.join(platforms)}\n\n{result.get('content')}")
            elif result.get("type") == "puppeteer" and result.get("url"):
                content_sections.append(
                    f"## Website Content from {result.get('url')}\n\nI've visited the website and extracted information.")

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

    # Add commands based on detected intents in appropriate order
    # Web search and puppeteer first as they provide context for other commands
    if "web_search" in significant_intents or "local_search" in significant_intents:
        pipeline.add_command(CommandFactory.create("web_search"))

    if "puppeteer" in significant_intents:
        pipeline.add_command(CommandFactory.create("puppeteer"))

    # Image generation next (if present)
    if "image_generation" in significant_intents:
        pipeline.add_command(CommandFactory.create("image_generation"))

    # Social media content generation next
    if "social_media" in significant_intents:
        pipeline.add_command(CommandFactory.create("social_media"))

    # Calculate total confidence of specialized commands
    specialized_intents = [intent_type for intent_type in significant_intents.keys() 
                          if intent_type != "general_knowledge"]
    specialized_confidences = [significant_intents[intent_type]["confidence"] for intent_type in specialized_intents]
    
    # Only add general knowledge if confidence is above threshold
    # This now relies on the smarter confidence calculation in detect_intents
    if significant_intents.get("general_knowledge", {}).get("confidence", 0) > 0.3:
        pipeline.add_command(CommandFactory.create("general_knowledge"))

    # Execute the pipeline
    result_context = await pipeline.execute(context)

    # Return the context for further processing
    return result_context

# ADDED NEW ENDPOINTS FOR CONVERSATION MANAGEMENT


@router.post("/conversation", response_model=Dict[str, Any])
async def create_new_conversation(
    request: CreateConversationRequest,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """Create a new pipeline conversation"""
    try:
        # Log user info for debugging
        logger.info(
            f"Creating conversation for content {request.content_id} with user {current_user}")

        # Use the correct user ID field
        user_id = current_user.get('id', current_user.get('uid'))
        if not user_id:
            raise HTTPException(
                status_code=400, detail="No valid user ID found")

        # Verify user exists in database
        check_query = "SELECT id FROM mo_user_info WHERE id = :user_id"
        user_exists = await db.fetch_one(query=check_query, values={"user_id": user_id})

        if not user_exists:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot create conversation: User {user_id} does not exist in the database"
            )

        conversation_id = await create_conversation(
            db=db,
            user_id=user_id,
            title=request.title,
            content_id=request.content_id,
            model=request.model
        )

        conversation = await get_conversation_by_id(db, conversation_id)

        return {"conversation": conversation, "success": True}
    except Exception as e:
        logger.error(f"Error creating conversation: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/by-content/{content_id}")
async def get_conversation_for_content(
    content_id: str,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """Get a conversation for a specific content ID"""
    try:
        # Use the correct user ID field
        user_id = current_user.get('id', current_user.get('uid'))
        if not user_id:
            raise HTTPException(
                status_code=400, detail="No valid user ID found")

        # Log authentication information
        logger.info(
            f"Fetching conversation for content {content_id}, user {user_id}")

        conversation = await get_conversation_by_content_id(db, content_id, user_id)

        if not conversation:
            # Return empty response instead of 404
            logger.info(
                f"No existing conversation found for content {content_id}")
            return {"conversation": None, "messages": []}

        logger.info(
            f"Found conversation {conversation['id']} for content {content_id}")

        # Get messages for this conversation
        messages_query = """
        SELECT id, role, content, created_at, function_call
        FROM mo_llm_messages
        WHERE conversation_id = :conversation_id
        ORDER BY created_at
        """
        messages = await db.fetch_all(
            query=messages_query,
            values={"conversation_id": conversation['id']}
        )

        return {
            "conversation": conversation,
            "messages": [dict(msg) for msg in messages]
        }
    except Exception as e:
        logger.error(
            f"Error getting conversation for content {content_id}: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_user),
    db: Database = Depends(get_database)
):
    """Get a conversation by ID"""
    try:
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

        return {"conversation": conversation}
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
    return {"commands": commands}


@router.get("/message/{message_id}")
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
