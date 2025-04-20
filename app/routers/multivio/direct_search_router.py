
import logging
import os
import json
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from app.dependencies import get_current_user, get_database
from databases import Database
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import httpx
from app.routers.multivio.brave_search_router import perform_web_search, format_web_results_for_llm
import uuid

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["direct-search"])

class WebSearchRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    chat_id: Optional[str] = None

class WebSearchResponse(BaseModel):
    success: bool
    query: str
    results: Optional[Dict[str, Any]] = None
    formatted_results: Optional[str] = None
    error: Optional[str] = None

@router.post("/search", response_model=WebSearchResponse)
async def direct_web_search(
    request: WebSearchRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Direct web search endpoint that bypasses the regular chat flow.
    Useful for debugging and ensuring web search works.
    """
    try:
        logger.info(f"=== DIRECT WEB SEARCH for query: '{request.query}' ===")
        
        # Check if Brave API key is configured
        brave_api_key = os.getenv("BRAVE_API_KEY")
        logger.info(f"Brave API key configured: {bool(brave_api_key)}")
        
        # Perform the search
        search_results = await perform_web_search(request.query)
        
        # Format the results for human readability
        formatted_results = format_web_results_for_llm(search_results)
        
        logger.info(f"Web search completed successfully with {len(formatted_results)} characters")
        
        # Return the successful response
        return WebSearchResponse(
            success=True,
            query=request.query,
            results=search_results,
            formatted_results=formatted_results
        )
        
    except Exception as e:
        logger.error(f"Error in direct web search: {str(e)}")
        
        # Return error response
        return WebSearchResponse(
            success=False,
            query=request.query,
            error=str(e)
        )

@router.post("/chat")
async def direct_search_chat(
    request: WebSearchRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """A direct endpoint for using web search in chat, bypassing the complex intent detection."""
    try:
        logger.info("=================== DIRECT SEARCH CHAT INVOKED ====================")
        logger.info(f"Query: '{request.query}'")
        logger.info(f"Conversation ID: {request.conversation_id}")
        logger.info(f"Content ID: {request.chat_id}")
        
        # Force web search 
        search_results = await perform_web_search(request.query)
        formatted_results = format_web_results_for_llm(search_results)
        
        # Build system prompt with search results
        search_instruction = f"""
# WEB SEARCH RESULTS

I've performed a web search for "{request.query}" and found the following results:

{formatted_results}

When answering the user's question:
1. Use these search results to provide up-to-date information
2. Cite specific sources from the results when appropriate
3. If the search results don't provide enough information, clearly state this and use your general knowledge
4. Synthesize information from multiple sources if relevant
"""
        
        # For streaming response
        from app.routers.multivio.general_router import call_together_api_stream
        
        # Create a message list - simpler than the complex logic in smart_router
        messages = [
            {"role": "system", "content": search_instruction},
            {"role": "user", "content": request.query}
        ]
        
        # Get conversation ID or create a new one
        conversation_id = request.conversation_id
        if not conversation_id:
            # Generate a new conversation ID
            conversation_id = str(uuid.uuid4())
            # Create the conversation
            await db.execute(
                """
                INSERT INTO mo_llm_conversations (id, title, model, created_at, updated_at, user_id)
                VALUES (:id, :title, :model, :created_at, :updated_at, :user_id)
                """,
                {
                    "id": conversation_id,
                    "title": f"Web search: {request.query[:30]}",
                    "model": "mixtral-8x7b",
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                    "user_id": current_user["uid"]
                }
            )
        
        # Log the user message
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
                "content": request.query,
                "created_at": datetime.now(timezone.utc)
            }
        )
        
        # Record that this was a web search
        assistant_message_id = str(uuid.uuid4())
        
        # Create the assistant message (will be updated as the response is streamed)
        await db.execute(
            """
            INSERT INTO mo_llm_messages (id, conversation_id, role, content, created_at, metadata)
            VALUES (:id, :conversation_id, :role, :content, :created_at, :metadata)
            """,
            {
                "id": assistant_message_id,
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": "Generating response based on web search results...",
                "created_at": datetime.now(timezone.utc),
                "metadata": json.dumps({
                    "web_search": True,
                    "query": request.query
                })
            }
        )
        
        # Stream the response
        return await call_together_api_stream(
            messages=messages,
            stream=True,
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            user_id=current_user["uid"],
            db=db
        )
        
    except Exception as e:
        logger.error(f"Error in direct search chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
