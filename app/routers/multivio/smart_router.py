from app.routers.multivio.brave_search_router import perform_web_search, perform_local_search, format_web_results_for_llm, format_local_results_for_llm
from app.routers.multivio.puppeteer_router import execute_puppeteer_function
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
import traceback

# Special override to force web search for all requests
FORCE_WEB_SEARCH = True

# Import the functionality from grok, together, and general routers with explicit naming
from app.routers.multivio.grok_router import router as grok_router, stream_chat_api as grok_stream_chat
from app.routers.multivio.general_router import router as general_router, stream_chat_api as general_stream_chat, DEFAULT_SYSTEM_PROMPT
from app.routers.multivio.together_router import call_together_api, generate_image_task


# IMPORTANT NOTE ABOUT CONVERSATION CONTEXT:
# When routing requests between different handlers (grok_router, general_router, etc.),
# always preserve the conversation_id to maintain context. Each handler should respect
# the provided conversation_id rather than creating a new one if one is supplied.
# This prevents issues with image generation and other asynchronous tasks trying to
# update messages in the wrong conversation.

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
    # Add this new field for explicit web search request
    perform_web_search: Optional[bool] = False

    # Add validation method to ensure we can access the perform_web_search field
    def get_web_search_flag(self) -> bool:
        """Safely get the web search flag value"""
        return self.perform_web_search if self.perform_web_search is not None else False
        
    # Allow dictionary representation for debugging
    def dict(self, *args, **kwargs):
        result = super().dict(*args, **kwargs)
        return result

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


# Add these patterns to detect browser automation intents
PUPPETEER_PATTERNS = [
    r"(?i)browse\s+(to|the|site)",
    r"(?i)navigate\s+to",
    r"(?i)go\s+to\s+(the\s+)?(website|site|page)",
    r"(?i)visit\s+(the\s+)?(website|site|page)",
    r"(?i)open\s+(the\s+)?(website|site|page)",
    r"(?i)take\s+a\s+screenshot",
    r"(?i)capture\s+(the\s+)?(screen|page)",
    r"(?i)click\s+on",
    r"(?i)interact\s+with",
    r"(?i)fill\s+(in|out)",
    r"(?i)type\s+into",
    r"(?i)scrape\s+(the|this)",
    r"(?i)extract\s+(content|data)",
]


# Update the detect_intent function to include web search intent
def detect_intent(message: str) -> str:
    """Detect the intent from the user message."""
    # Check for puppeteer/browser automation intent
    for pattern in PUPPETEER_PATTERNS:
        if re.search(pattern, message):
            return "puppeteer"
        
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


# Extract URL from puppeteer messages
def extract_url(message: str) -> str:
    """Extract URL from messages with browser automation intent"""
    url_pattern = r'https?://[^\s>)"]+|www\.[^\s>)"]+\.[^\s>)"]+|[a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+(/\S*)?'
    match = re.search(url_pattern, message)
    if match:
        url = match.group(0)
        # Add protocol if needed
        if url.startswith('www.'):
            url = 'https://' + url
        return url
    return None



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
            
            return query

    # If no prefix found, use the entire text
    return cleaned_message


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
    """Streaming chat endpoint that routes requests based on detected intent or explicit web search flag."""
    # CRITICAL TEST - If you see this, the code is being executed
    logger.warning(
        "!!!!!!!!!!!!!!! SMART ROUTER STREAM CHAT FUNCTION RUNNING WITH UPDATED CODE !!!!!!!!!!!!!!!")
    try:
        # CRITICAL LOGGING: Print the entire request details
        logger.info(
            "========================= CHAT STREAM REQUEST ==========================")
        logger.info(f"Request type: {type(request)}")
        # Try to extract all fields
        try:
            as_dict = request.dict() if hasattr(request, 'dict') else {
                "unable_to_get_dict": True}
            logger.info(f"Request as dict: {as_dict}")
        except Exception as e:
            logger.info(f"Error getting request dict: {str(e)}")

        # Specifically look for perform_web_search
        try:
            web_search_flag = getattr(request, 'perform_web_search', None)
            logger.info(
                f"Direct attribute access - perform_web_search: {web_search_flag}")
        except Exception as e:
            logger.info(f"Error getting web_search_flag attribute: {str(e)}")

        # Look for perform_browser_navigation flag
        try:
            browser_flag = getattr(request, 'perform_browser_navigation', None)
            logger.info(
                f"Direct attribute access - perform_browser_navigation: {browser_flag}")
        except Exception as e:
            logger.info(f"Error getting browser_flag attribute: {str(e)}")

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

        # Check for explicit web search flag from the frontend
        # First try to extract it directly from request.__dict__
        perform_web_search = False
        try:
            if hasattr(request, '__dict__') and 'perform_web_search' in request.__dict__:
                perform_web_search = request.__dict__['perform_web_search']
                logger.info(
                    f"Web search flag from __dict__: {perform_web_search}")
            elif hasattr(request, 'perform_web_search'):
                perform_web_search = request.perform_web_search
                logger.info(
                    f"Web search flag from attribute: {perform_web_search}")
            else:
                # Try to get the dict representation of the request
                req_dict = request.dict() if hasattr(request, 'dict') else {}
                perform_web_search = req_dict.get('perform_web_search', False)
                logger.info(f"Web search flag from dict: {perform_web_search}")
        except Exception as e:
            logger.error(f"Error getting web search flag: {str(e)}")
            perform_web_search = False

        # Check for explicit browser navigation flag
        perform_browser_navigation = False
        try:
            if hasattr(request, '__dict__') and 'perform_browser_navigation' in request.__dict__:
                perform_browser_navigation = request.__dict__[
                    'perform_browser_navigation']
                logger.info(
                    f"Browser navigation flag from __dict__: {perform_browser_navigation}")
            elif hasattr(request, 'perform_browser_navigation'):
                perform_browser_navigation = request.perform_browser_navigation
                logger.info(
                    f"Browser navigation flag from attribute: {perform_browser_navigation}")
            else:
                # Try to get the dict representation of the request
                req_dict = request.dict() if hasattr(request, 'dict') else {}
                perform_browser_navigation = req_dict.get(
                    'perform_browser_navigation', False)
                logger.info(
                    f"Browser navigation flag from dict: {perform_browser_navigation}")
        except Exception as e:
            logger.error(f"Error getting browser navigation flag: {str(e)}")
            perform_browser_navigation = False

        # Force-enable web search if the message explicitly contains search keywords
        if not perform_web_search and ('search' in user_message.lower() or 'find' in user_message.lower()):
            logger.info(
                f"Forcing web search based on message content: '{user_message}'")
            perform_web_search = True

        # Check for puppeteer intent based on keywords
        puppeteer_keywords = ['browse to', 'navigate to', 'go to',
                              'visit', 'open website', 'take a screenshot', 'capture screen']
        detected_puppeteer = any(keyword in user_message.lower()
                                 for keyword in puppeteer_keywords)
        if detected_puppeteer and not perform_browser_navigation:
            logger.info(
                f"Detected puppeteer intent based on message content: '{user_message}'")
            perform_browser_navigation = True

        logger.info(f"FINAL web search flag: {perform_web_search}")
        logger.info(
            f"FINAL browser navigation flag: {perform_browser_navigation}")

        # Web search specific logging
        logger.info(
            "================== WEB SEARCH DECISION LOGIC ==================")
        logger.info(f"FORCE_WEB_SEARCH global flag: {FORCE_WEB_SEARCH}")
        logger.info(
            f"getattr request.perform_web_search: {getattr(request, 'perform_web_search', False)}")

        # Puppeteer specific logging
        logger.info(
            "================== BROWSER NAVIGATION DECISION LOGIC ==================")
        logger.info(
            f"getattr request.perform_browser_navigation: {getattr(request, 'perform_browser_navigation', False)}")
        logger.info(f"Detected puppeteer intent: {detected_puppeteer}")

        # URL extraction for puppeteer
        target_url = None
        if perform_browser_navigation:
            # Try to extract URL from message
            url_pattern = r'https?://[^\s>)"]+|www\.[^\s>)"]+\.[^\s>)"]+|[a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+\.[a-zA-Z0-9]{2,6}(/\S*)?'
            url_match = re.search(url_pattern, user_message)
            if url_match:
                target_url = url_match.group(0)
                # Add protocol if needed
                if target_url.startswith('www.'):
                    target_url = 'https://' + target_url
                elif not target_url.startswith(('http://', 'https://')):
                    target_url = 'https://' + target_url
                logger.info(
                    f"Extracted URL for browser navigation: {target_url}")
            else:
                logger.info(
                    "No URL found in message, will attempt domain extraction")
                # Try to extract domain/website name
                domain_pattern = r'\b(?:browse to|navigate to|go to|visit|open)\s+(?:the\s+)?(?:website\s+)?([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(?:\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})*(?:\.[a-zA-Z]{2,})+)'
                domain_match = re.search(
                    domain_pattern, user_message, re.IGNORECASE)
                if domain_match:
                    target_url = "https://" + domain_match.group(1)
                    logger.info(
                        f"Extracted domain for browser navigation: {target_url}")
                else:
                    # Try to find any word that looks like a domain
                    domain_words_pattern = r'\b([a-zA-Z0-9][-a-zA-Z0-9]{0,62}\.(?:com|org|net|edu|gov|io|app|ai|co|me|info|biz))\b'
                    domain_words_match = re.search(
                        domain_words_pattern, user_message)
                    if domain_words_match:
                        target_url = "https://" + domain_words_match.group(1)
                        logger.info(f"Found domain-like word: {target_url}")

        # Determine intent and perform web search if needed
        try:
            # First, check if we need to do browser navigation with puppeteer
            if perform_browser_navigation and target_url:
                logger.info(f"Performing browser navigation to: {target_url}")

                try:
                    # Import the execute_puppeteer_function helper
                    from app.routers.multivio.puppeteer_router import execute_puppeteer_function

                    # Navigate to the URL
                    logger.info(f"Navigating to URL: {target_url}")
                    navigation_result = execute_puppeteer_function(
                        "puppeteer_navigate", url=target_url)

                    # Take a screenshot
                    screenshot_name = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    screenshot_result = execute_puppeteer_function(
                        "puppeteer_screenshot", name=screenshot_name)

                    # Extract page content using JavaScript
                    content_script = """
                        function getMainContent() {
                            // Try to find main content
                            const selectors = ['main', 'article', '#content', '.content', '.main-content'];
                            for (const selector of selectors) {
                                const element = document.querySelector(selector);
                                if (element) return element.innerText;
                            }
                            // Fall back to body text
                            return document.body.innerText;
                        }
                        return getMainContent();
                    """
                    page_content = execute_puppeteer_function(
                        "puppeteer_evaluate", script=content_script)

                    # Try to get the page title
                    title_script = "document.title"
                    page_title = execute_puppeteer_function(
                        "puppeteer_evaluate", script=title_script)

                    # Trim content if it's too large
                    if page_content and len(page_content) > 8000:
                        page_content = page_content[:8000] + \
                            "... [content truncated]"

                    # Create an enhanced prompt with the extracted content
                    puppeteer_context = f"""
                        # WEB PAGE CONTENT

                        I've navigated to {target_url} and found the following:

                        Title: {page_title or 'Unknown Title'}

                        Content:
                        {page_content or "No content could be extracted from this page."}

                        I've also taken a screenshot named '{screenshot_name}'.

                        When answering the user's question:
                        1. Use the content from this page to provide information
                        2. Describe what I found on the page
                        3. If the content doesn't address their question completely, clearly state this
                        """
                    # Get conversation ID or create a new one
                    conversation_id = getattr(request, 'conversation_id', None)

                    # Log the message to the conversation if it exists
                    if conversation_id:
                        try:
                            # Log user message
                            user_message_id = str(uuid.uuid4())
                            await db.execute(
                                """
                                INSERT INTO mo_llm_messages (id, conversation_id, role, content, created_at)
                                VALUES (:id, :conversation_id, :role, :content, :created_at)
                                """,
                                {
                                    "id": user_message_id,
                                    "conversation_id": conversation_id,
                                    "role": "user",
                                    "content": user_message,
                                    "created_at": datetime.now(timezone.utc)
                                }
                            )

                            # Record the puppeteer system message
                            puppeteer_msg_id = str(uuid.uuid4())
                            await db.execute(
                                """
                                INSERT INTO mo_llm_messages (id, conversation_id, role, content, created_at, metadata)
                                VALUES (:id, :conversation_id, :role, :content, :created_at, :metadata)
                                """,
                                {
                                    "id": puppeteer_msg_id,
                                    "conversation_id": conversation_id,
                                    "role": "system",
                                    "content": puppeteer_context,
                                    "created_at": datetime.now(timezone.utc),
                                    "metadata": json.dumps({
                                        "puppeteer_navigation": True,
                                        "url": target_url,
                                        "screenshot": screenshot_name
                                    })
                                }
                            )
                        except Exception as db_error:
                            logger.error(
                                f"Error recording puppeteer messages: {str(db_error)}")

                    # Build a modified request for general_stream_chat
                    modified_request_data = {
                        "conversation_id": conversation_id,
                        "content_id": getattr(request, 'content_id', None),
                        "message": user_message,
                        "stream": True,
                        "system_prompt": puppeteer_context  # Pass the puppeteer context as system prompt
                    }

                    # Convert to the GeneralChatRequest format
                    from app.routers.multivio.general_router import ChatRequest as GeneralChatRequest
                    modified_request = GeneralChatRequest(
                        **modified_request_data)

                    # Use general_stream_chat with the enhanced request
                    return await general_stream_chat(modified_request, current_user, db)

                except Exception as puppeteer_error:
                    logger.error(
                        f"Error during browser navigation: {str(puppeteer_error)}")
                    logger.error(traceback.format_exc())
                    # Fall back to web search if navigation fails
                    logger.info(
                        "Falling back to web search after puppeteer failure")
                    perform_web_search = True

            # If FORCE_WEB_SEARCH is enabled or the request explicitly asks for web search
            if FORCE_WEB_SEARCH or perform_web_search:
                logger.info(f"Web search enabled for: '{user_message}'")

                # Perform web search directly here
                logger.info("PERFORMING DIRECT WEB SEARCH INLINE")
                # Use the imported function, not the variable
                from app.routers.multivio.brave_search_router import perform_web_search as search_function
                search_results = await search_function(user_message)
                formatted_results = format_web_results_for_llm(search_results)

                if formatted_results:
                    logger.info(
                        f"Successfully got {len(formatted_results)} chars of search results")

                    # Build system prompt with search results
                    search_instruction = f"""
                        # WEB SEARCH RESULTS

                        I've performed a web search for "{user_message}" and found the following results:

                        {formatted_results}

                        When answering the user's question:
                        1. Use these search results to provide up-to-date information
                        2. Cite specific sources from the results when appropriate
                        3. If the search results don't provide enough information, clearly state this and use your general knowledge
                        4. Synthesize information from multiple sources if relevant
                        """

                    # Create a message list with search results
                    system_prompt = getattr(
                        request, 'system_prompt', DEFAULT_SYSTEM_PROMPT)
                    messages = [
                        {"role": "system", "content": search_instruction},
                        {"role": "user", "content": user_message}
                    ]

                    # Get conversation ID or create a new one
                    conversation_id = getattr(request, 'conversation_id', None)

                    # Use the general router with our enhanced messages
                    logger.info(
                        "ROUTING TO GENERAL KNOWLEDGE WITH SEARCH RESULTS")

                    # Get user message ID for tracking
                    user_message_id = str(uuid.uuid4())
                    # Log the message to the conversation if it exists
                    if conversation_id:
                        try:
                            await db.execute(
                                """
                                INSERT INTO mo_llm_messages (id, conversation_id, role, content, created_at)
                                VALUES (:id, :conversation_id, :role, :content, :created_at)
                                """,
                                {
                                    "id": user_message_id,
                                    "conversation_id": conversation_id,
                                    "role": "user",
                                    "content": user_message,
                                    "created_at": datetime.now(timezone.utc)
                                }
                            )

                            # Record the search system prompt with full results
                            search_msg_id = str(uuid.uuid4())
                            await db.execute(
                                """
                                INSERT INTO mo_llm_messages (id, conversation_id, role, content, created_at, metadata)
                                VALUES (:id, :conversation_id, :role, :content, :created_at, :metadata)
                                """,
                                {
                                    "id": search_msg_id,
                                    "conversation_id": conversation_id,
                                    "role": "system",
                                    "content": search_instruction,  # Store the FULL search results in content
                                    "created_at": datetime.now(timezone.utc),
                                    "metadata": json.dumps({"web_search": True, "query": user_message})
                                }
                            )
                        except Exception as db_error:
                            logger.error(
                                f"Error recording messages: {str(db_error)}")

                    # Build a modified request for general_stream_chat
                    modified_request_data = {
                        "conversation_id": conversation_id,
                        "content_id": getattr(request, 'content_id', None),
                        "message": user_message,
                        "stream": True,
                        # Pass the search instruction as system prompt
                        "system_prompt": search_instruction
                    }

                    # Convert to the GeneralChatRequest format
                    from app.routers.multivio.general_router import ChatRequest as GeneralChatRequest
                    modified_request = GeneralChatRequest(
                        **modified_request_data)

                    # Use general_stream_chat with the enhanced request
                    return await general_stream_chat(modified_request, current_user, db)
                else:
                    logger.error(
                        "Web search returned no results, falling back to general knowledge")
                    return await general_stream_chat(request, current_user, db)
            else:
                # Detect intent based on message content
                intent = detect_intent(user_message)
                logger.info(
                    f">>> Smart router detected intent: {intent} for message: '{user_message}'")

                # Route based on detected intent
                if intent == "image_generation":
                    # For image generation, don't stream but return a special response
                    # Extract image prompt
                    prompt = extract_image_prompt(user_message)

                    # Image generation code
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

                elif intent == "puppeteer":
                    # Handle puppeteer intent if not already handled by the explicit flag
                    logger.info(
                        "Detected puppeteer intent but no URL was found earlier")

                    # Try one more time to extract a URL or domain
                    domain_pattern = r'(?:about|for|of|from)\s+([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(?:\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})*(?:\.[a-zA-Z]{2,})+)'
                    domain_match = re.search(
                        domain_pattern, user_message, re.IGNORECASE)

                    if domain_match:
                        extracted_domain = "https://" + domain_match.group(1)
                        logger.info(
                            f"Found domain in secondary extraction: {extracted_domain}")

                        # Recursively call this function with the extracted domain but avoid infinite loop
                        temp_request = copy.deepcopy(request)
                        if hasattr(temp_request, '__dict__'):
                            temp_request.__dict__[
                                'perform_browser_navigation'] = True

                        # Modify the message to include the extracted URL to ensure it's found
                        if hasattr(temp_request, 'message'):
                            temp_request.message = f"{user_message} {extracted_domain}"
                        elif hasattr(temp_request, 'messages') and temp_request.messages:
                            for i in range(len(temp_request.messages)):
                                if temp_request.messages[i].role.lower() == "user":
                                    temp_request.messages[i].content = f"{temp_request.messages[i].content} {extracted_domain}"
                                    break

                        return await stream_chat(temp_request, background_tasks, current_user, db)
                    else:
                        # If we still can't find a URL, perform a web search instead
                        logger.info(
                            "No URL found for puppeteer intent, falling back to web search")
                        temp_request = copy.deepcopy(request)
                        if hasattr(temp_request, '__dict__'):
                            temp_request.__dict__['perform_web_search'] = True

                        return await stream_chat(temp_request, background_tasks, current_user, db)

                elif intent == "social_media":
                    # IMPORTANT: Explicitly use the grok_router's stream_chat_api
                    logger.info(
                        "Routing to social media handler (grok_router)")
                    return await grok_stream_chat(request, current_user, db)

                else:  # general_knowledge or any other intent
                    # IMPORTANT: Explicitly use the general_router's stream_chat_api
                    logger.info(
                        "Routing to general knowledge handler (general_router)")
                    return await general_stream_chat(request, current_user, db)
        except Exception as e:
            logger.error(f"Error in handling web search decision: {str(e)}")
            logger.error(traceback.format_exc())
            # Fall back to general knowledge
            return await general_stream_chat(request, current_user, db)

    except Exception as e:
        logger.error(f"Error in stream chat: {str(e)}")
        logger.error(traceback.format_exc())
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
