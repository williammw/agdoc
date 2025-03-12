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


# IMPORTANT NOTE ABOUT CONVERSATION CONTEXT:
# When routing requests between different handlers (grok_router, general_router, etc.),
# always preserve the conversation_id to maintain context. Each handler should respect
# the provided conversation_id rather than creating a new one if one is supplied.
# This prevents issues with image generation and other asynchronous tasks trying to
# update messages in the wrong conversation.

# Import the functionality from grok, together, and general routers
# Import the functionality from grok, together, and general routers with explicit naming
from app.routers.multivio.grok_router import router as grok_router, stream_chat_api as grok_stream_chat
from app.routers.multivio.general_router import router as general_router, stream_chat_api as general_stream_chat, DEFAULT_SYSTEM_PROMPT
from app.routers.multivio.together_router import call_together_api, generate_image_task
from app.routers.multivio.brave_search_router import perform_web_search, perform_local_search, format_web_results_for_llm, format_local_results_for_llm



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
    model: Optional[str] = "grok-2-1212"
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
# Search patterns
SEARCH_PATTERNS = [
    r"(?i)search\s+for",
    r"(?i)search\s+the\s+(web|internet)\s+for",
    r"(?i)find\s+information\s+(about|on)",
    r"(?i)look\s+up",
    r"(?i)find\s+(me\s+)?(some\s+)?information",
    r"(?i)what\s+are\s+the\s+latest",
    r"(?i)tell\s+me\s+about\s+recent"
]

LOCAL_SEARCH_PATTERNS = [
    r"(?i)near\s+me",
    r"(?i)nearby",
    r"(?i)in\s+(my|this)\s+area",
    r"(?i)close\s+to",
    r"(?i)restaurants\s+in",
    r"(?i)businesses\s+in",
    r"(?i)places\s+in"
]

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

# Add these patterns to your intent detection patterns
SEARCH_PATTERNS = [
    r"(?i)search\s+for",
    r"(?i)find\s+information\s+(about|on)",
    r"(?i)look\s+up",
    r"(?i)search\s+the\s+(web|internet)\s+for",
    r"(?i)find\s+(me\s+)?(some\s+)?information",
    r"(?i)what\s+(is|are|was|were)",
    r"(?i)tell\s+me\s+about",
    r"(?i)where\s+(is|can\s+I\s+find)",
    r"(?i)how\s+(to|do|does|can|could)",
    r"(?i)(latest|recent)\s+news\s+(about|on)",
    r"(?i)who\s+(is|was)",
    r"(?i)when\s+(is|was|did)",
    r"(?i)why\s+(is|are|do|does)",
]

LOCAL_SEARCH_PATTERNS = [
    r"(?i)near\s+me",
    r"(?i)nearby",
    r"(?i)in\s+(my|this)\s+area",
    r"(?i)close\s+to",
    r"(?i)within\s+\d+\s+(miles|kilometers)",
    r"(?i)restaurants\s+in",
    r"(?i)stores\s+in",
    r"(?i)services\s+in",
    r"(?i)find\s+a\s+(place|restaurant|store|hotel)",
]


# Update the detect_intent function to include web search intent
def detect_intent(message: str) -> str:
    """Detect the intent from the user message."""
    # Check for image generation intent
    for pattern in IMAGE_PATTERNS:
        if re.search(pattern, message):
            return "image_generation"

    # Check for local search intent (which is a subset of search)
    for pattern in LOCAL_SEARCH_PATTERNS:
        if re.search(pattern, message):
            return "local_search"

    # Check for web search intent
    for pattern in SEARCH_PATTERNS:
        if re.search(pattern, message):
            return "web_search"

    # Check for social media intent
    for pattern in SOCIAL_MEDIA_PATTERNS:
        if re.search(pattern, message):
            return "social_media"

    # Default to general knowledge
    return "general_knowledge"


# Replace the extract_search_query function with this improved version
def extract_search_query(message: str) -> str:
    """Extract the search query from the message with improved handling"""
    # Define search prefixes with their exact forms
    search_prefixes = [
        {"prefix": "search the internet for", "include_for": False},
        {"prefix": "search the web for", "include_for": False},
        {"prefix": "search for", "include_for": False},
        {"prefix": "find information about", "include_for": True},
        {"prefix": "find information on", "include_for": True},
        {"prefix": "look up", "include_for": True},
        {"prefix": "find me information about", "include_for": False},
        {"prefix": "find some information on", "include_for": True},
        {"prefix": "tell me about", "include_for": True},
    ]

    # Clean up the message - remove any trailing brackets or punctuation
    cleaned_message = re.sub(r'[\[\]\(\)\{\}]$', '', message).strip()
    lower_text = cleaned_message.lower()

    for prefix_data in search_prefixes:
        prefix = prefix_data["prefix"]
        if prefix in lower_text:
            # Extract everything after the prefix
            query_start = lower_text.find(prefix) + len(prefix)

            # If the prefix is followed by "me ", skip it unless include_for is True
            if not prefix_data["include_for"] and lower_text[query_start:].strip().startswith("me "):
                query_start += 3  # Skip "me "

            query = cleaned_message[query_start:].strip()

            # Remove trailing punctuation
            query = re.sub(r'[.!?]+$', '', query).strip()

            # If query is just "me" or empty after cleaning, use the original message
            if not query or query.lower() == "me":
                # Remove the search prefix from the original message
                original_start = message.lower().find(prefix) + len(prefix)
                return message[original_start:].strip()

            return query

    # If no prefix found, use the entire text
    return cleaned_message


def extract_location(message: str) -> Optional[str]:
    """Extract location from a local search message"""
    location_patterns = [
        r"(?i)in\s+([A-Za-z\s]+)",
        r"(?i)near\s+([A-Za-z\s]+)",
        r"(?i)around\s+([A-Za-z\s]+)",
        r"(?i)close\s+to\s+([A-Za-z\s]+)",
    ]

    for pattern in location_patterns:
        match = re.search(pattern, message)
        if match:
            location = match.group(1).strip()
            # Filter out common non-location words
            non_locations = ["me", "here", "there", "my area", "this area"]
            if location.lower() not in non_locations:
                return location

    return None


# Helper function to extract image prompt
# Helper function to extract search query
def extract_search_query(message: str) -> str:
    """Extract the search query from the user message."""
    # Define search prefixes to look for
    search_prefixes = [
        "search the internet for",
        "search the web for",
        "search for",
        "find information about",
        "find information on",
        "look up",
        "tell me about recent",
        "what are the latest"
    ]
    
    # Clean up and lowercase the message
    cleaned_message = message.strip()
    lower_text = cleaned_message.lower()
    
    # Look for each prefix
    for prefix in search_prefixes:
        if prefix in lower_text:
            # Extract everything after the prefix
            query_start = lower_text.find(prefix) + len(prefix)
            query = cleaned_message[query_start:].strip()
            
            # Skip "me" if it's the first word after a search command
            if query.lower().startswith("me "):
                query = query[3:].strip()
                
            # Remove trailing punctuation and brackets
            query = re.sub(r'[.!?\[\]\(\)\{\}]+$', '', query).strip()

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

        # Handle web search intent
        if intent == "web_search" or intent == "local_search":
            try:
                # Extract search query
                search_query = extract_search_query(user_message)
                logger.info(f"Extracted search query: '{search_query}'")
                
                # Perform search based on intent
                try:
                    search_results = None
                    formatted_results = ""
                    
                    if intent == "local_search":
                        # Extract location from query for local search
                        location = extract_location(user_message)
                        logger.info(f"Performing local search with location: '{location}'")
                        search_results = await perform_local_search(search_query, location)
                        formatted_results = format_local_results_for_llm(search_results)
                    else:
                        logger.info(f"Performing web search for: '{search_query}'")
                        search_results = await perform_web_search(search_query)
                        formatted_results = format_web_results_for_llm(search_results)
                    
                    logger.info(f"Received search results: {len(formatted_results)} characters")
                    
                    # Get conversation history if available
                    conversation_id = getattr(request, 'conversation_id', None)
                    conversation_messages = []
                    
                    if conversation_id:
                        try:
                            # Get existing conversation history if this is part of an ongoing conversation
                            query = """
                            SELECT id, role, content, created_at 
                            FROM mo_llm_messages 
                            WHERE conversation_id = :conversation_id 
                            ORDER BY created_at ASC
                            """
                            history = await db.fetch_all(
                                query=query, 
                                values={"conversation_id": conversation_id}
                            )
                            
                            if history:
                                for msg in history:
                                    role = msg["role"]
                                    content = msg["content"]
                                    if content:  # Skip empty messages
                                        conversation_messages.append(ChatMessage(
                                            role=role,
                                            content=content
                                        ))
                                logger.info(f"Retrieved {len(conversation_messages)} messages from conversation history")
                        except Exception as e:
                            logger.error(f"Error retrieving conversation history: {str(e)}")
                            # Continue without history if there's an error
                    
                    # Start with initial messages from the request if no history was found
                    if not conversation_messages and hasattr(request, 'messages'):
                        conversation_messages = list(request.messages)
                    
                    # Create the final messages array with search results inserted
                    messages_with_search = []
                    
                    # If a system prompt is provided, use it as the first message
                    system_prompt = getattr(request, 'system_prompt', None)
                    if system_prompt:
                        messages_with_search.append(ChatMessage(
                            role="system",
                            content=system_prompt
                        ))
                    elif conversation_messages and conversation_messages[0].role.lower() == "system":
                        # Keep the existing system message if available
                        messages_with_search.append(conversation_messages[0])
                        conversation_messages = conversation_messages[1:]  # Remove from conversation messages
                    
                    # Add a specific search instruction as a system message
                    search_instruction = f"""
I've performed a web search for "{search_query}" and found the following results:

{formatted_results}

When answering the user's question:
1. Use these search results to provide up-to-date information
2. Cite specific sources from the results when appropriate
3. If the search results don't provide enough information, clearly state this and use your general knowledge
4. Synthesize information from multiple sources if relevant
"""
                    
                    messages_with_search.append(ChatMessage(
                        role="system",
                        content=search_instruction
                    ))
                    
                    # Add conversation history up to the current user message
                    for msg in conversation_messages:
                        if not (msg.role.lower() == "user" and msg.content.strip() == user_message.strip()):
                            messages_with_search.append(msg)
                    
                    # Finally, add the current user message
                    messages_with_search.append(ChatMessage(
                        role="user",
                        content=user_message
                    ))
                    
                    # Create a modified request with the enhanced messages
                    modified_request = ChatRequest(
                        messages=messages_with_search,
                        model=request.model if hasattr(request, 'model') else "grok-1",
                        temperature=request.temperature if hasattr(request, 'temperature') else 0.7,
                        max_tokens=request.max_tokens if hasattr(request, 'max_tokens') else 1000,
                        stream=True,
                        conversation_id=conversation_id,
                        content_id=getattr(request, 'content_id', None),
                        system_prompt=None,  # Already included in messages
                        message=user_message  # Keep the original message
                    )
                    
                    # Add debug logs
                    logger.info(f"Created modified request with {len(messages_with_search)} messages including search results")
                    message_roles = [msg.role for msg in messages_with_search]
                    logger.info(f"Message roles in order: {message_roles}")
                    
                    # Route to general_router with the enhanced request
                    logger.info("Routing to general knowledge handler with search results")
                    return await general_stream_chat(modified_request, current_user, db)
                    
                except Exception as search_error:
                    logger.error(f"Search error: {str(search_error)}")
                    # If search fails, fall back to general knowledge
                    logger.info("Search failed, falling back to general knowledge")
                    return await general_stream_chat(request, current_user, db)
            
            except Exception as e:
                logger.error(f"Error in web search handling: {str(e)}")
                logger.info("Error in search handling, falling back to general knowledge")
                return await general_stream_chat(request, current_user, db)

        elif intent == "image_generation":
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
                    # IMPORTANT: Always pass the conversation_id to maintain context
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
                        content_id=getattr(request, 'content_id', None),
                        system_prompt=getattr(request, 'system_prompt', None)
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
                    # IMPORTANT: Always pass the conversation_id to maintain context
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
                        content_id=getattr(request, 'content_id', None),
                        system_prompt=getattr(request, 'system_prompt', None)
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


# Helper function to extract location for local search
def extract_location(message: str) -> Optional[str]:
    """Extract location from a local search query."""
    location_patterns = [
        r"(?i)in\s+([A-Za-z\s]+)",
        r"(?i)near\s+([A-Za-z\s]+)",
        r"(?i)around\s+([A-Za-z\s]+)",
        r"(?i)close\s+to\s+([A-Za-z\s]+)"
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, message)
        if match:
            location = match.group(1).strip()
            # Filter out common non-location words
            non_locations = ["me", "here", "there", "my area", "this area"]
            if location.lower() not in non_locations:
                return location
    
    return None

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

        # Handle web search intent
        if intent == "web_search" or intent == "local_search":
            try:
                # Extract search query
                search_query = extract_search_query(user_message)
                logger.info(f"Extracted search query: '{search_query}'")
                
                # Perform search based on intent
                try:
                    search_results = None
                    formatted_results = ""
                    
                    if intent == "local_search":
                        # Extract location from query for local search
                        location = extract_location(user_message)
                        logger.info(f"Performing local search with location: '{location}'")
                        search_results = await perform_local_search(search_query, location)
                        formatted_results = format_local_results_for_llm(search_results)
                    else:
                        logger.info(f"Performing web search for: '{search_query}'")
                        search_results = await perform_web_search(search_query)
                        formatted_results = format_web_results_for_llm(search_results)
                    
                    logger.info(f"Received search results: {len(formatted_results)} characters")
                    
                    # Get conversation history if available
                    conversation_id = getattr(request, 'conversation_id', None)
                    conversation_messages = []
                    
                    if conversation_id:
                        try:
                            # Get existing conversation history if this is part of an ongoing conversation
                            query = """
                            SELECT id, role, content, created_at 
                            FROM mo_llm_messages 
                            WHERE conversation_id = :conversation_id 
                            ORDER BY created_at ASC
                            """
                            history = await db.fetch_all(
                                query=query, 
                                values={"conversation_id": conversation_id}
                            )
                            
                            if history:
                                for msg in history:
                                    role = msg["role"]
                                    content = msg["content"]
                                    if content:  # Skip empty messages
                                        conversation_messages.append(ChatMessage(
                                            role=role,
                                            content=content
                                        ))
                                logger.info(f"Retrieved {len(conversation_messages)} messages from conversation history")
                        except Exception as e:
                            logger.error(f"Error retrieving conversation history: {str(e)}")
                            # Continue without history if there's an error
                    
                    # Start with initial messages from the request if no history was found
                    if not conversation_messages and hasattr(request, 'messages'):
                        conversation_messages = list(request.messages)
                    
                    # Create the final messages array with search results inserted
                    messages_with_search = []
                    
                    # If a system prompt is provided, use it as the first message
                    system_prompt = getattr(request, 'system_prompt', None)
                    if system_prompt:
                        messages_with_search.append(ChatMessage(
                            role="system",
                            content=system_prompt
                        ))
                    elif conversation_messages and conversation_messages[0].role.lower() == "system":
                        # Keep the existing system message if available
                        messages_with_search.append(conversation_messages[0])
                        conversation_messages = conversation_messages[1:]  # Remove from conversation messages
                    
                    # Add a specific search instruction as a system message
                    search_instruction = f"""
                        I've performed a web search for "{search_query}" and found the following results:

                        {formatted_results}

                        When answering the user's question:
                        1. Use these search results to provide up-to-date information
                        2. Cite specific sources from the results when appropriate
                        3. If the search results don't provide enough information, clearly state this and use your general knowledge
                        4. Synthesize information from multiple sources if relevant
                    """
                    
                    messages_with_search.append(ChatMessage(
                        role="system",
                        content=search_instruction
                    ))
                    
                    # Add conversation history up to the current user message
                    for msg in conversation_messages:
                        if not (msg.role.lower() == "user" and msg.content.strip() == user_message.strip()):
                            messages_with_search.append(msg)
                    
                    # Finally, add the current user message
                    messages_with_search.append(ChatMessage(
                        role="user",
                        content=user_message
                    ))
                    
                    # Create a modified request with the enhanced messages
                    modified_request = ChatRequest(
                        messages=messages_with_search,
                        model=request.model if hasattr(request, 'model') else "grok-1",
                        temperature=request.temperature if hasattr(request, 'temperature') else 0.7,
                        max_tokens=request.max_tokens if hasattr(request, 'max_tokens') else 1000,
                        stream=True,
                        conversation_id=conversation_id,
                        content_id=getattr(request, 'content_id', None),
                        system_prompt=None,  # Already included in messages
                        message=user_message  # Keep the original message
                    )
                    
                    # Add debug logs
                    logger.info(f"Created modified request with {len(messages_with_search)} messages including search results")
                    message_roles = [msg.role for msg in messages_with_search]
                    logger.info(f"Message roles in order: {message_roles}")
                    
                    # Route to general_router with the enhanced request
                    logger.info("Routing to general knowledge handler with search results")
                    return await general_stream_chat(modified_request, current_user, db)
                    
                except Exception as search_error:
                    logger.error(f"Search error: {str(search_error)}")
                    # If search fails, fall back to general knowledge
                    logger.info("Search failed, falling back to general knowledge")
                    return await general_stream_chat(request, current_user, db)
            
            except Exception as e:
                logger.error(f"Error in web search handling: {str(e)}")
                logger.info("Error in search handling, falling back to general knowledge")
                return await general_stream_chat(request, current_user, db)

        elif intent == "image_generation":
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
                    # IMPORTANT: Always pass the conversation_id to maintain context
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
                        content_id=getattr(request, 'content_id', None),
                        system_prompt=getattr(request, 'system_prompt', None)
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
                    # IMPORTANT: Always pass the conversation_id to maintain context
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
                        content_id=getattr(request, 'content_id', None),
                        system_prompt=getattr(request, 'system_prompt', None)
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
