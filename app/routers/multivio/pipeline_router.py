"""
Pipeline Router - Implements the Pipeline and Command pattern for multi-intent processing.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
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

async def create_conversation(db: Database, user_id: str, title: str = None, content_id: Optional[str] = None):
    """Create a new conversation"""
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # Default title if none provided
    if not title:
        title = "Multi-Intent Conversation"

    query = """
    INSERT INTO mo_llm_conversations (
        id, user_id, title, model_id, created_at, updated_at, content_id
    ) VALUES (
        :id, :user_id, :title, 'grok-2-1212', :created_at, :updated_at, :content_id
    ) RETURNING id
    """

    values = {
        "id": conversation_id,
        "user_id": user_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "content_id": content_id
    }

    await db.execute(query=query, values=values)
    return conversation_id

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
                content_sections.append("## Web Search Results\n\nI searched the web and found relevant information for your query.")
            elif result.get("type") == "image_generation" and result.get("prompt"):
                content_sections.append(f"## Image Generation\n\nI've generated an image based on: '{result.get('prompt')}'")
            elif result.get("type") == "social_media" and result.get("content"):
                platforms = result.get("platforms", [])
                content_sections.append(f"## Social Media Content for {', '.join(platforms)}\n\n{result.get('content')}")
            elif result.get("type") == "puppeteer" and result.get("url"):
                content_sections.append(f"## Website Content from {result.get('url')}\n\nI've visited the website and extracted information.")
        
        response["content"] = "\n\n".join(content_sections) or "I processed your request but couldn't generate a meaningful response."
    
    return response

async def process_streaming_response(context: Dict[str, Any]):
    """
    Process the pipeline response for streaming.
    """
    # First yield detected intents
    intents_message = {
        "intents": list(context.get("intents", {}).keys())
    }
    yield f"data: {json.dumps(intents_message)}\n\n"
    
    # Process each result
    for result in context.get("results", []):
        # Skip general_knowledge as it will be part of the content stream
        if result.get("type") == "general_knowledge":
            continue
            
        result_message = {
            "result_type": result.get("type")
        }
        
        # Add type-specific data
        if result.get("type") == "image_generation":
            result_message["image_generation"] = {
                "task_id": result.get("task_id"),
                "prompt": result.get("prompt"),
                "status": result.get("status")
            }
        elif result.get("type") == "puppeteer":
            result_message["puppeteer"] = {
                "url": result.get("url"),
                "title": result.get("title"),
                "screenshot": result.get("screenshot")
            }
            
        yield f"data: {json.dumps(result_message)}\n\n"
    
    # Finally stream the content if available
    if "general_knowledge_content" in context:
        content = context["general_knowledge_content"]
        # Stream in chunks
        chunk_size = 100
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i+chunk_size]
            yield f"data: {json.dumps({'v': chunk})}\n\n"
            await asyncio.sleep(0.02)  # Small delay for natural streaming effect
    
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
    # Detect intents in the message
    intents = detect_intents(request.message)
    logger.info(f"Detected intents: {list(intents.keys())}")
    
    # Create or get conversation
    conversation_id = request.conversation_id
    if not conversation_id:
        title = f"Multi-Intent: {request.message[:30]}..." if len(request.message) > 30 else request.message
        conversation_id = await create_conversation(
            db=db,
            user_id=current_user["uid"],
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
            "metadata": json.dumps({"multi_intent": True, "detected_intents": list(intents.keys())})
        }
    )
    
    # Create initial context
    context = {
        "message": request.message,
        "conversation_id": conversation_id,
        "user_id": current_user["uid"],
        "db": db,
        "background_tasks": background_tasks,
        "current_user": current_user,
        "intents": intents,
        "model": request.model,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens
    }
    
    # Create pipeline based on intents
    pipeline = Pipeline(name="MultiIntentPipeline")
    
    # Add commands based on detected intents in appropriate order
    # Web search and puppeteer first as they provide context for other commands
    if "web_search" in intents or "local_search" in intents:
        pipeline.add_command(CommandFactory.create("web_search"))
    
    if "puppeteer" in intents:
        pipeline.add_command(CommandFactory.create("puppeteer"))
    
    # Image generation next (if present)
    if "image_generation" in intents:
        pipeline.add_command(CommandFactory.create("image_generation"))
    
    # Social media content generation next
    if "social_media" in intents:
        pipeline.add_command(CommandFactory.create("social_media"))
    
    # Always add general knowledge as fallback
    pipeline.add_command(CommandFactory.create("general_knowledge"))
    
    # Execute the pipeline
    result_context = await pipeline.execute(context)
    
    # Return the context for further processing
    return result_context

@router.post("/chat")
async def multi_intent_chat(
    request: MultiIntentChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
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
        
        # Create message ID
        message_id = str(uuid.uuid4())
        response_data["message_id"] = message_id
        
        return response_data
        
    except Exception as e:
        logger.error(f"Error in multi_intent_chat: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/stream")
async def stream_multi_intent_chat(
    request: MultiIntentChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Stream a multi-intent chat response.
    """
    try:
        # Process the request
        result_context = await process_multi_intent_request(request, background_tasks, current_user, db)
        
        # Return streaming response
        return StreamingResponse(
            process_streaming_response(result_context),
            media_type="text/event-stream"
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
