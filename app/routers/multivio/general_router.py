# # general_router.py - General knowledge assistant implementation using OpenAI client library
# from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
# from fastapi.responses import StreamingResponse, JSONResponse
# from app.dependencies import get_current_user, get_database
# from databases import Database
# from typing import List, Dict, Any, Optional, Union, Literal
# from pydantic import BaseModel, Field, validator
# import uuid
# import json
# import os
# import logging
# import asyncio
# from datetime import datetime, timezone
# from openai import OpenAI, AsyncOpenAI
# import httpx
# import requests
# import re

# # Update logging configuration
# logging.basicConfig(
#     level=logging.DEBUG,  # Set to DEBUG for more detailed logs
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )

# logger = logging.getLogger(__name__)

# # Initialize router
# router = APIRouter()

# # Load environment variables
# GROK_API_KEY = os.getenv("XAI_API_KEY")  # Using existing XAI_API_KEY env var
# GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# # Model constants
# DEFAULT_GROK_MODEL = "grok-3-mini-beta"
# AVAILABLE_MODELS = [
#     "grok-2-1212", 
#     "grok-2-vision-1212", 
#     "grok-3-mini-beta", 
#     "grok-3-mini-fast-beta"
# ]

# # General knowledge system prompt
# DEFAULT_SYSTEM_PROMPT = """
# # SYSTEM PROMPT - Multivio General Assistant

# You are a helpful, knowledgeable assistant for Multivio users. You can help with a wide range of topics including programming, research, writing, data analysis, and general knowledge questions.

# ## CAPABILITIES
# - Answering factual questions
# - Providing detailed explanations
# - Assisting with coding and technical problems 
# - Writing and content creation (except social media)
# - Data analysis and interpretation
# - Learning and educational assistance

# ## RESPONSE PRINCIPLES
# 1. Be accurate, helpful, and concise
# 2. When unsure, acknowledge limitations
# 3. Provide complete, well-structured answers
# 4. Stay focused on the user's actual question
# 5. Use examples when they help clarify concepts

# If a user specifically asks for social media content creation help, politely let them know you can assist with general questions, but for specialized social media content support, they should use Multivio's social media tools instead.
# """

# # Request/Response Models


# class Message(BaseModel):
#     role: str
#     content: str
#     name: Optional[str] = None
#     function_call: Optional[Dict[str, Any]] = None


# class ChatMessage(BaseModel):
#     role: str
#     content: str
#     name: Optional[str] = None
#     function_call: Optional[Dict[str, Any]] = None
#     timestamp: Optional[datetime] = None
#     id: Optional[str] = None


# class ImageContent(BaseModel):
#     type: Literal["image_url", "text"]
#     text: Optional[str] = None
#     image_url: Optional[Dict[str, str]] = None


# class VisionMessage(BaseModel):
#     role: str
#     content: Union[str, List[ImageContent]]


# class FunctionDefinition(BaseModel):
#     name: str
#     description: str
#     parameters: Dict[str, Any]


# class ChatRequest(BaseModel):
#     conversation_id: Optional[str] = None
#     chat_id: Optional[str] = None
#     message: str
#     model: str = DEFAULT_GROK_MODEL
#     system_prompt: Optional[str] = None
#     temperature: Optional[float] = 0.7
#     max_tokens: Optional[int] = 2048
#     stream: bool = True
#     functions: Optional[List[str]] = None


# class VisionRequest(BaseModel):
#     conversation_id: Optional[str] = None
#     messages: List[VisionMessage]
#     model: str = "grok-2-vision-1212"
#     system_prompt: Optional[str] = None
#     max_tokens: Optional[int] = 2048
#     stream: bool = True


# class ConversationRequest(BaseModel):
#     title: Optional[str] = None


# class FunctionCallRequest(BaseModel):
#     name: str
#     arguments: Dict[str, Any]
#     conversation_id: Optional[str] = None
#     message_id: Optional[str] = None


# class ConversationResponse(BaseModel):
#     id: str
#     title: str
#     model: str
#     created_at: datetime
#     updated_at: datetime
#     message_count: int
#     last_message: Optional[str] = None


# class MessageResponse(BaseModel):
#     id: str
#     role: str
#     content: str
#     created_at: datetime
#     function_call: Optional[Dict[str, Any]] = None

# # Minimal function registry for compatibility


# class FunctionRegistry:
#     def __init__(self):
#         self.functions = {}
#         self._register_default_functions()

#     def _register_default_functions(self):
#         # Register get_current_time function for compatibility
#         self.register(
#             name="get_current_time",
#             description="Get the current server time",
#             parameters={
#                 "type": "object",
#                 "properties": {},
#                 "required": []
#             },
#             handler=self._get_current_time
#         )

#     async def _get_current_time(self) -> str:
#         return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#     def register(self, name, description, parameters, handler):
#         """Register a function with its schema and handler"""
#         self.functions[name] = {
#             "name": name,
#             "description": description,
#             "parameters": parameters,
#             "handler": handler
#         }

#     def get_functions(self, function_names=None):
#         """Get function schemas for specified functions or all if None"""
#         if function_names is None:
#             return [
#                 {"name": f["name"], "description": f["description"],
#                     "parameters": f["parameters"]}
#                 for f in self.functions.values()
#             ]

#         result = []
#         for name in function_names:
#             if name in self.functions:
#                 f = self.functions[name]
#                 result.append({
#                     "name": f["name"],
#                     "description": f["description"],
#                     "parameters": f["parameters"]
#                 })

#         return result

#     def get_openai_tools(self, function_names=None):
#         """Get functions in OpenAI tools format"""
#         functions = self.get_functions(function_names)
#         tools = []

#         for func in functions:
#             tools.append({
#                 "type": "function",
#                 "function": {
#                     "name": func["name"],
#                     "description": func["description"],
#                     "parameters": func["parameters"]
#                 }
#             })

#         return tools

#     async def execute(self, name, arguments):
#         """Execute a registered function with the provided arguments"""
#         if name not in self.functions:
#             raise ValueError(f"Function {name} not found")

#         handler = self.functions[name]["handler"]
#         try:
#             return await handler(**arguments)
#         except Exception as e:
#             logger.error(f"Error executing function {name}: {str(e)}")
#             return {"error": str(e)}

# # Database Helper Functions


# async def get_conversation(db: Database, conversation_id: str, user_id: str):
#     """Get a conversation by ID"""
#     query = """
#     SELECT
#         id, title, model_id as model,
#         created_at, updated_at,
#         (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
#         (SELECT content FROM mo_llm_messages
#         WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
#         ORDER BY created_at DESC LIMIT 1) as last_message
#     FROM mo_llm_conversations
#     WHERE id = :conversation_id AND user_id = :user_id
#     """
#     result = await db.fetch_one(query=query, values={"conversation_id": conversation_id, "user_id": user_id})
#     if not result:
#         raise HTTPException(status_code=404, detail="Conversation not found")
#     return dict(result)


# async def get_conversation_messages(db: Database, conversation_id: str, user_id: str):
#     """Get messages for a conversation"""
#     # First verify the conversation belongs to the user
#     conversation_query = """
#     SELECT id FROM mo_llm_conversations
#     WHERE id = :conversation_id AND user_id = :user_id
#     """
#     conversation = await db.fetch_one(
#         query=conversation_query,
#         values={"conversation_id": conversation_id, "user_id": user_id}
#     )

#     if not conversation:
#         raise HTTPException(status_code=404, detail="Conversation not found")

#     # Get the messages
#     messages_query = """
#     SELECT
#         id, role, content, created_at, function_call
#     FROM mo_llm_messages
#     WHERE conversation_id = :conversation_id
#     ORDER BY created_at
#     """
#     messages = await db.fetch_all(query=messages_query, values={"conversation_id": conversation_id})
#     return [dict(msg) for msg in messages]


# async def create_conversation(db: Database, user_id: str, model: str, title: Optional[str] = None, chat_id: Optional[str] = None):
#     """Create a new conversation"""
#     conversation_id = str(uuid.uuid4())
#     now = datetime.now(timezone.utc)

#     query = """
#     INSERT INTO mo_llm_conversations (
#         id, user_id, title, model_id, created_at, updated_at, chat_id
#     ) VALUES (
#         :id, :user_id, :title, :model, :created_at, :updated_at, :chat_id
#     ) RETURNING id
#     """

#     values = {
#         "id": conversation_id,
#         "user_id": user_id,
#         "title": title or "New Conversation",
#         "model": model,
#         "created_at": now,
#         "updated_at": now,
#         "chat_id": chat_id
#     }

#     await db.execute(query=query, values=values)
#     return conversation_id


# async def add_message(db: Database, conversation_id: str, role: str, content: str,
#                       function_call: Optional[Dict[str, Any]] = None):
#     """Add a message to a conversation"""
#     message_id = str(uuid.uuid4())
#     now = datetime.now(timezone.utc)

#     query = """
#     INSERT INTO mo_llm_messages (
#         id, conversation_id, role, content, created_at, function_call
#     ) VALUES (
#         :id, :conversation_id, :role, :content, :created_at, :function_call
#     ) RETURNING id
#     """

#     values = {
#         "id": message_id,
#         "conversation_id": conversation_id,
#         "role": role,
#         "content": content,
#         "created_at": now,
#         "function_call": json.dumps(function_call) if function_call else None
#     }

#     await db.execute(query=query, values=values)

#     # Update conversation timestamp
#     update_query = """
#     UPDATE mo_llm_conversations
#     SET updated_at = :updated_at
#     WHERE id = :conversation_id
#     """

#     await db.execute(
#         query=update_query,
#         values={"conversation_id": conversation_id, "updated_at": now}
#     )

#     return message_id


# async def store_function_call(db: Database, message_id: str, function_name: str, arguments: Dict[str, Any], result: Optional[Dict[str, Any]] = None):
#     """Store a function call and result"""
#     function_call_id = str(uuid.uuid4())
#     now = datetime.now(timezone.utc)

#     query = """
#     INSERT INTO mo_llm_function_calls (
#         id, message_id, function_name, arguments, result, status, created_at, completed_at
#     ) VALUES (
#         :id, :message_id, :function_name, :arguments, :result, :status, :created_at, :completed_at
#     ) RETURNING id
#     """

#     values = {
#         "id": function_call_id,
#         "message_id": message_id,
#         "function_name": function_name,
#         "arguments": json.dumps(arguments),
#         "result": json.dumps(result) if result else None,
#         "status": "completed" if result else "pending",
#         "created_at": now,
#         "completed_at": now if result else None
#     }

#     await db.execute(query=query, values=values)
#     return function_call_id


# async def prepare_conversation_messages(db: Database, conversation_id: str, system_prompt: Optional[str] = None):
#     """Prepare messages for a conversation to send to Grok"""
#     messages = await db.fetch_all(
#         query="SELECT role, content, function_call FROM mo_llm_messages WHERE conversation_id = :conversation_id ORDER BY created_at",
#         values={"conversation_id": conversation_id}
#     )

#     logger.info(
#         f"Found {len(messages)} messages for conversation {conversation_id}")

#     formatted_messages = []

#     # Add system prompt if provided - Log which prompt is being used
#     if system_prompt:
#         logger.info(f"Using provided system prompt: '{system_prompt[:50]}...'")
#         formatted_messages.append({
#             "role": "system",
#             "content": system_prompt
#         })
#     else:
#         # Before adding the default system prompt, check if there's already a system message with search results
#         has_search_results = False
#         for msg in messages:
#             msg_dict = dict(msg)
#             if msg_dict["role"] == "system" and msg_dict["content"] and ("I've performed a web search" in msg_dict["content"] or "WEB SEARCH RESULTS" in msg_dict["content"]):
#                 has_search_results = True
#                 logger.info(
#                     "Found existing search results system message - keeping it")
#                 break

#         if not has_search_results:
#             logger.info(
#                 f"Using DEFAULT_SYSTEM_PROMPT: '{DEFAULT_SYSTEM_PROMPT[:50]}...'")
#             formatted_messages.append({
#                 "role": "system",
#                 "content": DEFAULT_SYSTEM_PROMPT
#             })
#         else:
#             # If we have search results, they're already in the message list
#             logger.info(
#                 "Found existing search results system message - keeping it")

#     # Process each message
#     for i, msg in enumerate(messages):
#         # Convert Record to dict to work with it
#         msg_dict = dict(msg)

#         # Check for empty content
#         if not msg_dict["content"] or msg_dict["content"].strip() == "":
#             logger.warning(
#                 f"Message {i} has empty content, role={msg_dict['role']}")
#             # Skip empty user/assistant messages to prevent API errors
#             if msg_dict["role"] in ["user", "assistant"] and not msg_dict["function_call"]:
#                 logger.warning(f"Skipping empty {msg_dict['role']} message")
#                 continue
#             # For empty messages with function calls, provide a placeholder content
#             content = " "  # OpenAI requires non-empty content
#         else:
#             content = msg_dict["content"]

#         message_dict = {
#             "role": msg_dict["role"],
#             "content": content
#         }

#         # Add function call if present
#         if msg_dict["function_call"]:
#             function_call = json.loads(msg_dict["function_call"])
#             message_dict["function_call"] = function_call
#             logger.info(
#                 f"Message {i} has function_call: {function_call.get('name')}")

#         formatted_messages.append(message_dict)

#     # Final validation to ensure no empty messages
#     formatted_messages = [
#         msg for msg in formatted_messages if msg["content"].strip() != ""]

#     # Log the final message list
#     logger.info(f"Prepared {len(formatted_messages)} messages for API call")

#     return formatted_messages


# async def process_function_call(db: Database, conversation_id: str, function_call_data: Dict[str, Any]):
#     """Process a function call from Grok"""
#     function_name = function_call_data.get("name", "")
#     arguments_data = function_call_data.get("arguments", "{}")

#     # Handle both string and dict arguments
#     if isinstance(arguments_data, str):
#         try:
#             arguments = json.loads(arguments_data)
#         except json.JSONDecodeError:
#             logger.error(f"Invalid JSON in arguments: {arguments_data}")
#             arguments = {}
#     else:
#         # Already a dictionary
#         arguments = arguments_data

#     # Store function call message
#     message_id = await add_message(
#         db=db,
#         conversation_id=conversation_id,
#         role="assistant",
#         content="",  # Empty content for function call messages
#         function_call={"name": function_name, "arguments": arguments}
#     )

#     # Execute the function
#     function_registry = FunctionRegistry()
#     result = await function_registry.execute(function_name, arguments)

#     # Store function result
#     await store_function_call(
#         db=db,
#         message_id=message_id,
#         function_name=function_name,
#         arguments=arguments,
#         result=result
#     )

#     # Add function result as a message
#     await add_message(
#         db=db,
#         conversation_id=conversation_id,
#         role="function",
#         content=json.dumps(result),
#         function_call=None
#     )

#     return {
#         "message_id": message_id,
#         "function_name": function_name,
#         "arguments": arguments,
#         "result": result
#     }

# # OpenAI Client for Grok


# class GrokOpenAIClient:
#     def __init__(self, api_key: str):
#         self.client = OpenAI(
#             api_key=api_key,
#             base_url=GROK_API_BASE_URL
#         )
#         self.async_client = AsyncOpenAI(
#             api_key=api_key,
#             base_url=GROK_API_BASE_URL
#         )

#     def validate_model(self, model):
#         if model not in AVAILABLE_MODELS:
#             logger.warning(
#                 f"Model {model} not in available models list, using default {DEFAULT_GROK_MODEL}")
#             return DEFAULT_GROK_MODEL
#         return model

#     async def create_streaming_completion_async(self, messages, model, tools=None, temperature=0.7, max_tokens=2048, reasoning_effort=None):
#         """Create a streaming completion with Grok API asynchronously"""
#         model = self.validate_model(model)
        
#         # Set up parameters for API call
#         params = {
#             "model": model,
#             "messages": messages,
#             "temperature": temperature,
#             "max_tokens": max_tokens,
#             "stream": True
#         }
        
#         # Add tools if provided
#         if tools:
#             params["tools"] = tools
        
#         # Add reasoning_effort if model is grok-3
#         if model.startswith("grok-3") and reasoning_effort:
#             params["reasoning_effort"] = reasoning_effort
            
#         # Create the streaming completion asynchronously
#         stream = await self.async_client.chat.completions.create(**params)

#         return stream

#     async def create_completion_async(self, messages, model, tools=None, temperature=0.7, max_tokens=2048, reasoning_effort=None):
#         """Create a non-streaming completion with Grok API asynchronously"""
#         model = self.validate_model(model)
        
#         # Set up parameters for API call
#         params = {
#             "model": model,
#             "messages": messages,
#             "temperature": temperature,
#             "max_tokens": max_tokens
#         }
        
#         # Add tools if provided
#         if tools:
#             params["tools"] = tools
            
#         # Add reasoning_effort if model is grok-3
#         if model.startswith("grok-3") and reasoning_effort:
#             params["reasoning_effort"] = reasoning_effort

#         completion = await self.async_client.chat.completions.create(**params)

#         return completion


# # Create function registry instance
# function_registry = FunctionRegistry()


# async def process_streaming_response(stream, db, conversation_id):
#     """Process a streaming response"""
#     full_response = ""
#     function_call_detected = False
#     current_function_call = None

#     try:
#         chunk_count = 0
#         async for chunk in stream:
#             chunk_count += 1

#             # Process the content if available
#             if hasattr(chunk.choices[0].delta, "content") and chunk.choices[0].delta.content is not None:
#                 content = chunk.choices[0].delta.content
#                 if content:
#                     # Log the raw content for debugging
#                     logger.debug(f"Raw chunk content: {repr(content)}")

#                     # Check for potentially problematic angle brackets that might cause truncation
#                     if '<' in content:
#                         logger.warning(
#                             f"Detected potential HTML/XML in content: {repr(content)}")
#                         # Replace angle brackets with parentheses to prevent truncation
#                         safe_content = content.replace(
#                             '<', '(').replace('>', ')')
#                         full_response += safe_content
#                         yield f"data: {json.dumps({'v': safe_content})}\n\n"
#                     else:
#                         full_response += content
#                         yield f"data: {json.dumps({'v': content})}\n\n"

#             # Process function calls via official mechanism
#             if hasattr(chunk.choices[0].delta, "tool_calls") and chunk.choices[0].delta.tool_calls:
#                 tool_calls = chunk.choices[0].delta.tool_calls
#                 for tool_call in tool_calls:
#                     if tool_call.function:
#                         function_call_detected = True

#                         # Initialize or update function name
#                         if not current_function_call:
#                             current_function_call = {
#                                 "name": tool_call.function.name or "",
#                                 "arguments": tool_call.function.arguments or ""
#                             }
#                         else:
#                             if tool_call.function.name:
#                                 current_function_call["name"] = tool_call.function.name
#                             if tool_call.function.arguments:
#                                 current_function_call["arguments"] += tool_call.function.arguments

#                         # Send function call data to client
#                         if current_function_call["name"]:
#                             yield f"data: {json.dumps({'function_call': current_function_call})}\n\n"

#     except Exception as e:
#         logger.error(f"Error in streaming response: {str(e)}", exc_info=True)
#         yield f"data: {json.dumps({'error': str(e)})}\n\n"

#     logger.info(
#         f"Completed streaming {chunk_count} chunks, processing full response")
#     logger.info(f"Final response length: {len(full_response)}")

#     # Process function call if detected
#     if function_call_detected and current_function_call and current_function_call["name"]:
#         try:
#             logger.info(f"Processing function call: {current_function_call}")

#             # Parse arguments if needed
#             arguments = current_function_call["arguments"]
#             if isinstance(arguments, str):
#                 try:
#                     arguments = json.loads(arguments)
#                 except json.JSONDecodeError:
#                     logger.error(f"Failed to parse arguments: {arguments}")
#                     arguments = {}

#             # Process the function call
#             await process_function_call(
#                 db=db,
#                 conversation_id=conversation_id,
#                 function_call_data={
#                     "name": current_function_call["name"],
#                     "arguments": arguments
#                 }
#             )
#         except Exception as e:
#             logger.error(
#                 f"Error processing function call: {str(e)}", exc_info=True)

#     # Store the complete response if we have content
#     if full_response:
#         try:
#             await add_message(
#                 db=db,
#                 conversation_id=conversation_id,
#                 role="assistant",
#                 content=full_response
#             )
#         except Exception as e:
#             logger.error(f"Error storing response: {str(e)}")

#     # Final DONE marker
#     yield "data: [DONE]\n\n"


# async def stream_chat_response(db: Database, conversation_id: str, user_id: str, request: ChatRequest):
#     """Generate streaming response from Grok"""
#     if not GROK_API_KEY:
#         raise HTTPException(
#             status_code=500, detail="Grok API key not configured")

#     # Get conversation and verify it belongs to user
#     await get_conversation(db, conversation_id, user_id)

#     # Validate message is not empty
#     if not request.message or request.message.strip() == "":
#         logger.error("Empty message provided to stream_chat_response")
#         yield f"data: {json.dumps({'v': 'Error: Empty message provided'})}\n\n"
#         yield "data: [DONE]\n\n"
#         return

#     # Log the message being processed
#     logger.info(
#         f"Processing message: '{request.message}' for conversation {conversation_id}")

#     # Get conversation history
#     system_prompt = getattr(request, 'system_prompt', None)
#     conversation_messages = await prepare_conversation_messages(
#         db=db,
#         conversation_id=conversation_id,
#         system_prompt=system_prompt
#     )

#     # Add the current user message to conversation_messages
#     conversation_messages.append({
#         "role": "user",
#         "content": request.message
#     })

#     # Log the number of messages being sent to API
#     logger.info(f"Sending {len(conversation_messages)} messages to OpenAI API")

#     # We'll enable minimal tools for compatibility but not focus on them
#     tools = function_registry.get_openai_tools(["get_current_time"])

#     # Initialize Grok client
#     grok_client = GrokOpenAIClient(GROK_API_KEY)

#     try:
#         # Get streaming response with minimal tools
#         stream = await grok_client.create_streaming_completion_async(
#             messages=conversation_messages,
#             model=grok_client.validate_model(request.model),
#             tools=tools,
#             temperature=request.temperature,
#             max_tokens=request.max_tokens
#         )
#     except Exception as e:
#         logger.error(f"Error calling OpenAI API: {str(e)}", exc_info=True)
#         yield f"data: {json.dumps({'v': f'Error: {str(e)}'})}\n\n"
#         yield "data: [DONE]\n\n"
#         return

#     # Process and return the streaming response
#     async for chunk in process_streaming_response(stream, db, conversation_id):
#         yield chunk


# async def stream_vision_response(db: Database, conversation_id: str, user_id: str, request: VisionRequest):
#     """Generate streaming response from Grok for vision requests"""
#     if not GROK_API_KEY:
#         raise HTTPException(
#             status_code=500, detail="Grok API key not configured")

#     # Process vision messages for the API
#     vision_messages = []

#     # Add system prompt
#     if request.system_prompt:
#         vision_messages.append({
#             "role": "system",
#             "content": request.system_prompt
#         })
#     else:
#         vision_messages.append({
#             "role": "system",
#             "content": DEFAULT_SYSTEM_PROMPT
#         })

#     # Add user messages with images
#     for msg in request.messages:
#         if msg.role == "user":
#             vision_messages.append({
#                 "role": msg.role,
#                 "content": msg.content
#             })

#     # Prepare minimal tools if vision model supports function calling
#     tools = function_registry.get_openai_tools(["get_current_time"])

#     # Initialize Grok client
#     grok_client = GrokOpenAIClient(GROK_API_KEY)

#     # Get streaming response
#     stream = await grok_client.create_streaming_completion_async(
#         messages=vision_messages,
#         model=request.model,
#         tools=tools,
#         temperature=0.7,
#         max_tokens=request.max_tokens
#     )

#     # Process and return the streaming response
#     return process_streaming_response(stream, db, conversation_id)

# # API Endpoints


# @router.get("/models")
# async def get_models():
#     """Get available Grok models"""
#     return {"models": AVAILABLE_MODELS}


# @router.get("/functions")
# async def get_available_functions():
#     """Get available functions for Grok"""
#     functions = function_registry.get_functions()
#     return {"functions": functions}


# @router.post("/functions/call")
# async def call_function(
#     request: FunctionCallRequest,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Execute a function call directly"""
#     try:
#         # Execute the function
#         result = await function_registry.execute(request.name, request.arguments)

#         # If conversation and message ID are provided, store the function call
#         if request.conversation_id and request.message_id:
#             await store_function_call(
#                 db=db,
#                 message_id=request.message_id,
#                 function_name=request.name,
#                 arguments=request.arguments,
#                 result=result
#             )

#             # Add function message to conversation
#             await add_message(
#                 db=db,
#                 conversation_id=request.conversation_id,
#                 role="function",
#                 content=json.dumps(result)
#             )

#         return {
#             "success": True,
#             "function_name": request.name,
#             "result": result
#         }
#     except Exception as e:
#         logger.error(f"Error calling function: {str(e)}")
#         raise HTTPException(status_code=400, detail=str(e))


# @router.get("/conversations")
# async def list_conversations(
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database),
#     chat_id: Optional[str] = None
# ):
#     """List all conversations for a user, optionally filtered by chat_id"""
#     query_values = {"user_id": current_user["uid"]}

#     if chat_id:
#         query = """
#         SELECT
#             id, title, model_id as model,
#             created_at, updated_at, chat_id,
#             (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
#             (SELECT content FROM mo_llm_messages
#             WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
#             ORDER BY created_at DESC LIMIT 1) as last_message
#         FROM mo_llm_conversations
#         WHERE user_id = :user_id AND chat_id = :chat_id
#         ORDER BY updated_at DESC
#         """
#         query_values["chat_id"] = chat_id
#     else:
#         query = """
#         SELECT
#             id, title, model_id as model,
#             created_at, updated_at, chat_id,
#             (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
#             (SELECT content FROM mo_llm_messages
#             WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
#             ORDER BY created_at DESC LIMIT 1) as last_message
#         FROM mo_llm_conversations
#         WHERE user_id = :user_id
#         ORDER BY updated_at DESC
#         """

#     conversations = await db.fetch_all(query=query, values=query_values)
#     return {"conversations": [dict(conv) for conv in conversations]}


# @router.get("/conversations/{conversation_id}")
# async def get_conversation_details(
#     conversation_id: str,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Get details of a specific conversation"""
#     conversation = await get_conversation(db, conversation_id, current_user["uid"])
#     messages = await get_conversation_messages(db, conversation_id, current_user["uid"])

#     return {
#         "conversation": conversation,
#         "messages": messages
#     }


# @router.post("/conversations")
# async def create_new_conversation(
#     request: ConversationRequest,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Create a new conversation"""
#     conversation_id = await create_conversation(
#         db=db,
#         user_id=current_user["uid"],
#         model=DEFAULT_GROK_MODEL,
#         title=request.title
#     )

#     conversation = await get_conversation(db, conversation_id, current_user["uid"])
#     return conversation


# @router.delete("/conversations/{conversation_id}")
# async def delete_conversation(
#     conversation_id: str,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Delete a conversation"""
#     # First verify the conversation belongs to the user
#     conversation = await get_conversation(db, conversation_id, current_user["uid"])

#     # Delete the conversation
#     await db.execute(
#         "DELETE FROM mo_llm_conversations WHERE id = :id",
#         {"id": conversation_id}
#     )

#     return {"success": True, "message": "Conversation deleted"}


# def sanitize_message(message: str) -> str:
#     """
#     Sanitize a message to remove potentially problematic content
#     that might cause API errors.
#     """
#     if not message:
#         return ""

#     # Log original message length
#     logger.debug(f"Sanitizing message of length {len(message)}")

#     # Replace problematic characters
#     sanitized = message

#     # Remove any null bytes
#     sanitized = sanitized.replace('\0', '')

#     # Replace any control characters except newlines and tabs
#     sanitized = ''.join(ch if ch in ['\n', '\t', '\r'] or ord(
#         ch) >= 32 else ' ' for ch in sanitized)

#     # Trim excessive whitespace
#     sanitized = ' '.join(sanitized.split())

#     # Log if changes were made
#     if sanitized != message:
#         logger.info(
#             f"Message was sanitized. Original length: {len(message)}, new length: {len(sanitized)}")

#     return sanitized


# @router.post("/chat")
# async def chat_completion(
#     request: ChatRequest,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Send a message and get a response from Grok"""
#     # Initialize Grok client
#     if not GROK_API_KEY:
#         raise HTTPException(
#             status_code=500, detail="Grok API key not configured")

#     # Check if message is empty or None
#     if not request.message or request.message.strip() == "":
#         logger.error("Empty message received in chat request")
#         raise HTTPException(status_code=400, detail="Message cannot be empty")

#     # Sanitize the message
#     original_message = request.message
#     request.message = sanitize_message(request.message)
#     if not request.message:
#         logger.error("Message became empty after sanitization")
#         raise HTTPException(
#             status_code=400, detail="Message cannot be empty after sanitization")

#     grok_client = GrokOpenAIClient(GROK_API_KEY)

#     # Get or create conversation
#     conversation_id = request.conversation_id
#     if not conversation_id:
#         # Create a new conversation
#         conversation_id = await create_conversation(
#             db=db,
#             user_id=current_user["uid"],
#             model=request.model,
#             title=None,  # We'll update this later based on first message
#             chat_id=request.chat_id
#         )
#     else:
#         # Verify conversation exists and belongs to user
#         await get_conversation(db, conversation_id, current_user["uid"])

#     # Add user message to conversation - store the original message
#     await add_message(
#         db=db,
#         conversation_id=conversation_id,
#         role="user",
#         content=original_message
#     )

#     # Update conversation title if it's new
#     if not request.conversation_id:
#         # Use first few words of message as title
#         title_words = request.message.split()[:5]
#         title = " ".join(title_words) + "..."

#         await db.execute(
#             "UPDATE mo_llm_conversations SET title = :title WHERE id = :id",
#             {"id": conversation_id, "title": title}
#         )

#     # If streaming is requested, return a streaming response
#     if request.stream:
#         async def event_generator():
#             async for chunk in stream_chat_response(
#                 db=db,
#                 conversation_id=conversation_id,
#                 user_id=current_user["uid"],
#                 request=request
#             ):
#                 yield chunk

#         return StreamingResponse(
#             event_generator(),
#             media_type="text/event-stream"
#         )
#     else:
#         # For non-streaming responses, get complete response
#         conversation_messages = await prepare_conversation_messages(
#             db=db,
#             conversation_id=conversation_id,
#             system_prompt=request.system_prompt
#         )

#         # Add the current user message
#         conversation_messages.append({
#             "role": "user",
#             "content": request.message
#         })

#         # Add basic tools for compatibility
#         tools = function_registry.get_openai_tools(["get_current_time"])

#         # Get completion from Grok
#         try:
#             completion = await grok_client.create_completion_async(
#                 messages=conversation_messages,
#                 model=request.model,
#                 tools=tools,
#                 temperature=request.temperature,
#                 max_tokens=request.max_tokens
#             )

#             # Extract response
#             response_message = completion.choices[0].message
#             content = response_message.content or ""

#             # Process official function calls if any
#             function_result = None
#             if response_message.tool_calls:
#                 for tool_call in response_message.tool_calls:
#                     if tool_call.type == "function":
#                         function_data = tool_call.function

#                         if function_data:
#                             function_name = function_data.name
#                             function_args_str = function_data.arguments

#                             try:
#                                 function_args = json.loads(function_args_str)
#                             except json.JSONDecodeError:
#                                 function_args = {}

#                             # Create function call data
#                             function_call_data = {
#                                 "name": function_name,
#                                 "arguments": function_args
#                             }

#                             # Process the function call
#                             function_result = await process_function_call(
#                                 db=db,
#                                 conversation_id=conversation_id,
#                                 function_call_data=function_call_data
#                             )

#             # Store assistant response
#             message_id = await add_message(
#                 db=db,
#                 conversation_id=conversation_id,
#                 role="assistant",
#                 content=content,
#                 function_call=function_result["function_call"] if function_result else None
#             )

#             # Return response
#             return {
#                 "conversation_id": conversation_id,
#                 "message_id": message_id,
#                 "content": content,
#                 "function_call": function_result
#             }

#         except Exception as e:
#             logger.error(f"Error in non-streaming chat completion: {str(e)}")
#             raise HTTPException(status_code=500, detail=str(e))


# @router.post("/chat/stream")
# async def stream_chat_api(
#     request: ChatRequest,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Stream a chat response via POST for EventSource compatibility"""
#     try:
#         # Add debug logging for this function
#         logger.info(
#             f"general_router.stream_chat_api called with message: '{request.message}'")

#         # Validate request
#         if not request.message or request.message.strip() == "":
#             logger.error("Empty message provided to stream_chat_api")
#             return JSONResponse(
#                 status_code=400,
#                 content={"error": "Message cannot be empty"}
#             )

#         # Check for search results in the messages - if present, keep them
#         has_search_results = False
#         search_system_message = None  # NEW: Variable to store search results content
#         if hasattr(request, 'messages') and request.messages:
#             for msg in request.messages:
#                 if msg.role == "system" and "I've performed a web search" in msg.content:
#                     has_search_results = True
#                     search_system_message = msg.content  # NEW: Save the search results
#                     logger.info(
#                         "Found search results in system message - preserving them")
#                     break

#         # Only force the system prompt if there are no search results
#         if not has_search_results:
#             request.system_prompt = DEFAULT_SYSTEM_PROMPT
#             logger.info(
#                 f"Using general knowledge system prompt: {DEFAULT_SYSTEM_PROMPT[:50]}...")
#         else:
#             # Ensure we don't override the search results
#             request.system_prompt = None
#             logger.info(
#                 "Using search results from smart_router instead of default system prompt")

#         # Ensure we have a valid conversation ID
#         conversation_id = None

#         # Use the existing conversation if provided, otherwise create a new one
#         if request.conversation_id:
#             # Verify the conversation exists and belongs to the user
#             try:
#                 await get_conversation(db, request.conversation_id, current_user["uid"])
#                 logger.info(
#                     f"Using existing conversation {request.conversation_id}")
#                 conversation_id = request.conversation_id
#             except HTTPException as e:
#                 logger.warning(
#                     f"Conversation not found or unauthorized: {str(e)}")
#                 # Create a new conversation if the provided one is invalid
#                 conversation_id = await create_conversation(
#                     db=db,
#                     user_id=current_user["uid"],
#                     model=request.model or DEFAULT_GROK_MODEL,
#                     title="General Knowledge: " +
#                     (request.message[:30] + "..." if len(request.message)
#                      > 30 else request.message),
#                     chat_id=request.chat_id
#                 )
#                 logger.info(
#                     f"Created new conversation {conversation_id} instead of {request.conversation_id}")
#         else:
#             # Create a new conversation if none was provided
#             conversation_id = await create_conversation(
#                 db=db,
#                 user_id=current_user["uid"],
#                 model=request.model or DEFAULT_GROK_MODEL,
#                 title="General Knowledge: " +
#                 (request.message[:30] + "..." if len(request.message)
#                  > 30 else request.message),
#                 chat_id=request.chat_id
#             )
#             logger.info(f"Created new conversation {conversation_id}")

#         # Update the request with the final conversation ID
#         request.conversation_id = conversation_id

#         # Sanitize the message
#         original_message = request.message
#         request.message = sanitize_message(request.message)
#         if not request.message:
#             logger.error("Message became empty after sanitization")
#             return JSONResponse(
#                 status_code=400,
#                 content={"error": "Message cannot be empty after sanitization"}
#             )

#         logger.info(
#             f"Processing message in stream_chat_api: '{request.message}'")

#         # Initialize Grok client
#         if not GROK_API_KEY:
#             return JSONResponse(
#                 status_code=500,
#                 content={"error": "Grok API key not configured"}
#             )

#         # NEW: Store the search results system message in the database if present
#         if has_search_results and search_system_message:
#             await add_message(
#                 db=db,
#                 conversation_id=conversation_id,
#                 role="system",
#                 content=search_system_message
#             )
#             logger.info("Stored search results system message in the database")

#         # Add user message to the conversation
#         await add_message(
#             db=db,
#             conversation_id=conversation_id,
#             role="user",
#             content=original_message
#         )

#         # Update conversation title
#         title_words = request.message.split()[:5]
#         title = "General: " + " ".join(title_words) + "..."

#         await db.execute(
#             "UPDATE mo_llm_conversations SET title = :title WHERE id = :id",
#             {"id": conversation_id, "title": title}
#         )

#         # Return streaming response with the new conversation
#         return StreamingResponse(
#             stream_chat_response(
#                 db=db,
#                 conversation_id=conversation_id,
#                 user_id=current_user["uid"],
#                 request=request
#             ),
#             media_type="text/event-stream"
#         )
#     except Exception as e:
#         logger.error(f"Error in stream_chat_api: {str(e)}", exc_info=True)
#         return JSONResponse(
#             status_code=500,
#             content={"error": f"Internal server error: {str(e)}"}
#         )

# @router.post("/chat/vision")
# async def vision_chat(
#     request: VisionRequest,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Process a vision chat request"""
#     # Initialize Grok client
#     if not GROK_API_KEY:
#         raise HTTPException(
#             status_code=500, detail="Grok API key not configured")

#     # Get or create conversation if needed
#     conversation_id = request.conversation_id
#     if conversation_id:
#         # Verify conversation exists and belongs to user
#         await get_conversation(db, conversation_id, current_user["uid"])
#     else:
#         # We'll create the conversation only if needed (in the stream function)
#         conversation_id = str(uuid.uuid4())

#     # Store the user's vision message if there's a conversation ID
#     if conversation_id and request.conversation_id:
#         # We only store text content for now
#         for msg in request.messages:
#             if msg.role == "user":
#                 content = ""
#                 if isinstance(msg.content, str):
#                     content = msg.content
#                 elif isinstance(msg.content, list):
#                     # Extract text content from the list
#                     text_parts = []
#                     for item in msg.content:
#                         if isinstance(item, dict) and item.get("type") == "text":
#                             text_parts.append(item.get("text", ""))
#                     content = " ".join(text_parts)

#                 if content:
#                     await add_message(
#                         db=db,
#                         conversation_id=conversation_id,
#                         role="user",
#                         content=content
#                     )

#     # Return streaming response if requested
#     if request.stream:
#         return StreamingResponse(
#             stream_vision_response(
#                 db=db,
#                 conversation_id=conversation_id,
#                 user_id=current_user["uid"],
#                 request=request
#             ),
#             media_type="text/event-stream"
#         )
#     else:
#         # Initialize Grok client
#         grok_client = GrokOpenAIClient(GROK_API_KEY)

#         # Process vision messages for the API
#         vision_messages = []

#         # Add system prompt
#         if request.system_prompt:
#             vision_messages.append({
#                 "role": "system",
#                 "content": request.system_prompt
#             })
#         else:
#             vision_messages.append({
#                 "role": "system",
#                 "content": DEFAULT_SYSTEM_PROMPT
#             })

#         # Add user messages with images
#         for msg in request.messages:
#             if msg.role == "user":
#                 vision_messages.append({
#                     "role": msg.role,
#                     "content": msg.content
#                 })

#         # Add minimal tools for compatibility
#         tools = function_registry.get_openai_tools(["get_current_time"])

#         # Call Grok API
#         try:
#             response = await grok_client.create_completion_async(
#                 messages=vision_messages,
#                 model=request.model,
#                 tools=tools,
#                 temperature=0.7,
#                 max_tokens=request.max_tokens
#             )

#             content = response.choices[0].message.content or ""

#             # Store the response if there's a conversation ID
#             if conversation_id and request.conversation_id:
#                 await add_message(
#                     db=db,
#                     conversation_id=conversation_id,
#                     role="assistant",
#                     content=content
#                 )

#             return {"response": content}

#         except Exception as e:
#             logger.error(f"Vision API error: {str(e)}")
#             raise HTTPException(
#                 status_code=500, detail=f"Vision API error: {str(e)}")


# @router.get("/content/{chat_id}/conversation")
# async def get_content_conversation(
#     chat_id: str,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Get or create a conversation for a content item"""
#     # Check if content exists and belongs to user
#     content_query = """
#     SELECT uuid FROM mo_chat 
#     WHERE uuid = :chat_id AND firebase_uid = :user_id
#     """
#     content = await db.fetch_one(
#         query=content_query,
#         values={"chat_id": chat_id, "user_id": current_user["uid"]}
#     )
#     if not content:
#         raise HTTPException(status_code=404, detail="Content not found")

#     # Try to find an existing conversation for this content
#     conversation_query = """
#     SELECT 
#         id, title, model_id as model, 
#         created_at, updated_at, 
#         chat_id,
#         (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
#         (SELECT content FROM mo_llm_messages 
#         WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
#         ORDER BY created_at DESC LIMIT 1) as last_message
#     FROM mo_llm_conversations
#     WHERE chat_id = :chat_id AND user_id = :user_id
#     ORDER BY updated_at DESC
#     LIMIT 1
#     """
#     conversation = await db.fetch_one(
#         query=conversation_query,
#         values={"chat_id": chat_id, "user_id": current_user["uid"]}
#     )

#     if conversation:
#         # Return existing conversation
#         conversation_data = dict(conversation)

#         # Get messages for the conversation
#         messages_query = """
#         SELECT id, role, content, created_at, function_call, image_url, image_metadata
#         FROM mo_llm_messages
#         WHERE conversation_id = :conversation_id
#         ORDER BY created_at
#         """
#         messages = await db.fetch_all(
#             query=messages_query,
#             values={"conversation_id": conversation_data["id"]}
#         )

#         return {
#             "conversation": conversation_data,
#             "messages": [dict(msg) for msg in messages]
#         }
#     else:
#         # Create new conversation for this content
#         conversation_id = await create_conversation(
#             db=db,
#             user_id=current_user["uid"],
#             model=DEFAULT_GROK_MODEL,
#             title=f"Content Chat",
#             chat_id=chat_id
#         )

#         # Get the new conversation
#         new_conversation = await get_conversation(db, conversation_id, current_user["uid"])

#         return {
#             "conversation": new_conversation,
#             "messages": []
#         }
