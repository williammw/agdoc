# import logging
# import os
# import json
# import re
# import traceback
# from typing import Optional, List, Dict, Any, Union
# from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
# from fastapi.responses import StreamingResponse, JSONResponse
# from app.dependencies import get_current_user, get_database
# from databases import Database
# from pydantic import BaseModel, Field
# from datetime import datetime, timezone
# import uuid
# import httpx

# # Import necessary modules from other routers
# from app.routers.multivio.brave_search_router import perform_web_search, format_web_results_for_llm
# from app.routers.multivio.general_router import router as general_router, stream_chat_api as general_stream_chat, DEFAULT_SYSTEM_PROMPT
# from app.routers.multivio.general_router import ChatRequest as GeneralChatRequest
# from app.routers.multivio.general_router import ChatMessage as GeneralChatMessage

# # Setup router and logger
# router = APIRouter(tags=["websearch"])
# logger = logging.getLogger(__name__)

# # Import the necessary models from smart_router
# class ChatMessage(BaseModel):
#     role: str
#     content: str

# class ChatRequest(BaseModel):
#     messages: Optional[List[ChatMessage]] = []
#     model: Optional[str] = "grok-3-mini-beta"
#     temperature: Optional[float] = 0.7
#     max_tokens: Optional[int] = 1000
#     message: Optional[str] = None
#     system_prompt: Optional[str] = None
#     conversation_id: Optional[str] = None
#     content_id: Optional[str] = None
#     stream: bool = True
#     perform_web_search: Optional[bool] = False
#     reasoning_effort: Optional[str] = "high"

# @router.post("/search/stream")
# async def websearch_stream(
#     request: ChatRequest,
#     background_tasks: BackgroundTasks,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """
#     Dedicated endpoint for web search that always performs a search 
#     regardless of intent detection or other factors.
#     """
#     logger.warning("!!! DEDICATED WEB SEARCH ENDPOINT INVOKED !!!")
    
#     try:
#         # Get the user message
#         user_message = ""
#         if hasattr(request, 'message') and request.message:
#             user_message = request.message
#         else:
#             user_message = next((msg.content for msg in reversed(request.messages)
#                                 if msg.role.lower() == "user"), "")

#         logger.info(f"Processing web search for: '{user_message}'")

#         if not user_message:
#             return StreamingResponse(
#                 content=iter(["No user message found"]),
#                 media_type="text/plain"
#             )

#         # Always do web search for this endpoint
#         try:
#             # Perform web search
#             logger.info("PERFORMING WEB SEARCH - NO INTENT DETECTION")
#             search_results = await perform_web_search(user_message)
#             formatted_results = format_web_results_for_llm(search_results)
            
#             if not formatted_results:
#                 logger.error("Web search returned no results")
#                 formatted_results = "No search results found. I'll answer based on my general knowledge."
            
#             logger.info(f"Web search completed with {len(formatted_results)} chars of results")
            
#             # Build system prompt with search results
#             search_instruction = f"""
# # WEB SEARCH RESULTS

# I've performed a web search for "{user_message}" and found the following results:

# {formatted_results}

# When answering the user's question:
# 1. Use these search results to provide up-to-date information
# 2. Cite specific sources from the results when appropriate
# 3. If the search results don't provide enough information, clearly state this and use your general knowledge
# 4. Synthesize information from multiple sources if relevant
# """
            
#             # Get conversation ID or create a new one
#             conversation_id = getattr(request, 'conversation_id', None)
            
#             # Get user message ID for tracking
#             user_message_id = str(uuid.uuid4())
#             # Log the message to the conversation if it exists
#             if conversation_id:
#                 try:
#                     await db.execute(
#                         """
#                         INSERT INTO mo_llm_messages (id, conversation_id, role, content, created_at)
#                         VALUES (:id, :conversation_id, :role, :content, :created_at)
#                         """,
#                         {
#                             "id": user_message_id,
#                             "conversation_id": conversation_id,
#                             "role": "user",
#                             "content": user_message,
#                             "created_at": datetime.now(timezone.utc)
#                         }
#                     )
                    
#                     # Record the search system prompt
#                     search_msg_id = str(uuid.uuid4())
#                     await db.execute(
#                         """
#                         INSERT INTO mo_llm_messages (id, conversation_id, role, content, created_at, metadata)
#                         VALUES (:id, :conversation_id, :role, :content, :created_at, :metadata)
#                         """,
#                         {
#                             "id": search_msg_id,
#                             "conversation_id": conversation_id,
#                             "role": "system",
#                             "content": "Web search results included as context.",
#                             "created_at": datetime.now(timezone.utc),
#                             "metadata": json.dumps({"web_search": True, "query": user_message})
#                         }
#                     )
#                 except Exception as db_error:
#                     logger.error(f"Error recording messages: {str(db_error)}")
            
#             # Build a modified request with search results
#             modified_messages = [
#                 GeneralChatMessage(role="system", content=search_instruction),
#                 GeneralChatMessage(role="user", content=user_message)
#             ]
            
#             modified_request = GeneralChatRequest(
#                 messages=modified_messages,
#                 conversation_id=conversation_id,
#                 content_id=getattr(request, 'content_id', None),
#                 message=user_message,
#                 stream=True
#             )
            
#             # Use general_stream_chat with the enhanced messages
#             logger.info("Forwarding to general_stream_chat with search results")
#             return await general_stream_chat(modified_request, current_user, db)
            
#         except Exception as search_error:
#             logger.error(f"Error during web search: {str(search_error)}")
#             logger.error(f"Traceback: {traceback.format_exc()}")
            
#             # Forward to general knowledge as fallback, but add a note about the search failure
#             fallback_messages = [
#                 GeneralChatMessage(role="system", content=f"Note: The user requested a web search for '{user_message}' but the search failed. Answer based on your general knowledge."),
#                 GeneralChatMessage(role="user", content=user_message)
#             ]
            
#             fallback_request = GeneralChatRequest(
#                 messages=fallback_messages,
#                 conversation_id=getattr(request, 'conversation_id', None),
#                 content_id=getattr(request, 'content_id', None),
#                 message=user_message,
#                 stream=True
#             )
            
#             logger.info("Falling back to general_stream_chat after search failure")
#             return await general_stream_chat(fallback_request, current_user, db)
            
#     except Exception as e:
#         logger.error(f"Critical error in websearch_stream: {str(e)}")
#         logger.error(traceback.format_exc())
#         return StreamingResponse(
#             content=iter([f"Error: {str(e)}"]),
#             media_type="text/plain"
#         )
