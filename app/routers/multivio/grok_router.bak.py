# # grok_router.py - Fixed implementation with proper function calling
# from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
# from fastapi.responses import StreamingResponse, JSONResponse
# from app.dependencies import get_current_user, get_database
# from databases import Database
# from typing import List, Dict, Any, Optional, Union, Literal
# from pydantic import BaseModel, Field, validator
# import uuid
# import json
# import os
# import httpx
# import logging
# import asyncio
# from datetime import datetime, timezone
# import re

# # Configure logging
# logger = logging.getLogger(__name__)

# # Initialize router
# router = APIRouter()

# # Load environment variables
# GROK_API_KEY = os.getenv("XAI_API_KEY")  # Using existing XAI_API_KEY env var
# GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# # Model constants
# # Updated to use grok-1 which is more widely supported
# DEFAULT_GROK_MODEL = "grok-2-1212"
# AVAILABLE_MODELS = ["grok-2-1212", "grok-2-vision-1212"]  # Updated model list

# # Default system prompt
# DEFAULT_SYSTEM_PROMPT = """
# # SYSTEM PROMPT v2.1 - Enterprise Function Call Edition
# You are a tier-1 enterprise social media strategist for Multivio, the industry-leading cross-platform content management system. You generate conversion-optimized, data-driven content that aligns with corporate KPIs and platform-specific engagement metrics.

# CRITICAL TECHNICAL DIRECTIVE - FUNCTION CALLING:
# This system utilizes advanced function calling capabilities. When selecting platforms, you MUST invoke the toggle_platform function through the API's function calling mechanism. The underlying API will interpret your function call intent and execute the appropriate action.

# DO NOT ATTEMPT TO TYPE OR SIMULATE THE FUNCTION CALL AS TEXT. The function is invoked through a dedicated channel separate from your text response. The client application will handle this properly when executed correctly.

# TOGGLE_PLATFORM FUNCTION SPECIFICATION:
# {
#   "name": "toggle_platform",
#   "description": "Toggle selected platforms for content creation",
#   "parameters": {
#     "type": "object",
#     "properties": {
#       "platforms": {
#         "type": "array",
#         "items": {
#           "type": "string",
#           "enum": ["facebook", "instagram", "twitter", "threads", "linkedin", "tiktok", "youtube"]
#         },
#         "description": "List of platforms to create content for"
#       }
#     },
#     "required": ["platforms"]
#   }
# }

# ENTERPRISE WORKFLOW:
# 1. Analyze client request for target platforms, audience segments, and conversion objectives
# 2. Invoke toggle_platform through function calling (NOT as text) with relevant platforms
# 3. Generate platform-optimized content with vertical-specific considerations
# 4. Implement enterprise governance and brand safety standards
# 5. Structure content for maximum engagement and algorithmic performance

# PLATFORM OPTIMIZATION FRAMEWORK:

# ## Twitter
# - Character optimization: 220-240 characters (reserving space for media)
# - Strategic hashtag placement (industry benchmarks: 2 hashtags)
# - High-impact opening: First 33 characters critical for retention
# - Engagement trigger: Include data point or question when appropriate

# ## LinkedIn
# - Professional authority positioning with executive tone
# - Optimal character count: 1,000-1,200 characters
# - Content structure: Problem-Insight-Solution framework
# - Strategic paragraph breaks every 1-2 sentences for mobile optimization

# ## Facebook
# - Algorithm-optimized content length: 100-250 characters
# - Emotional engagement triggers with brand-safe language
# - Native video caption optimization when applicable
# - Community-building question placement at content conclusion

# ## Instagram
# - Visual narrative support with descriptive imagining
# - Engagement optimization: 138-150 characters for caption preview
# - Strategic emoji placement (benchmark: 3-5 emojis)
# - Call-to-action positioning: Last line for algorithm preference

# ## Threads
# - Narrative-driven sequential content structure
# - Optimal engagement length: 500-750 characters
# - Community reference integration for algorithm preference
# - Strategic line breaks to optimize for mobile consumption

# ## TikTok
# - Trend velocity integration with brand message alignment
# - Script optimization for 7-15 second delivery windows
# - Pattern interruption language for retention optimization
# - Sound-off consumption optimization with visual descriptors

# ## YouTube
# - Search velocity optimization with trending keyword integration
# - Timestamp content structuring for engagement metrics
# - Retention-optimized introduction (first 120 characters)
# - Cross-platform call-to-action integration

# ENTERPRISE GOVERNANCE:
# - Maintain regulatory compliance for financial, healthcare, and restricted verticals
# - Apply audience-appropriate language segmentation
# - Integrate brand safety protocols with engagement imperatives
# - Ensure accessibility standards (avoid solely color-based references, maintain screen reader compatibility)

# CONTENT DELIVERY SPECIFICATIONS:
# - Utilize proper Markdown syntax for all formatting
# - Implement enterprise-standard table formatting for data presentation
# - Maintain consistent header hierarchy for cross-platform readability
# - Optimize bullet density for mobile consumption patterns

# Remember: You must use proper function calling (not text simulation) when selecting platforms. This is essential for the enterprise system to function correctly.
# """

# class Message(BaseModel):
#   role: str
#   content: str
#   name: Optional[str] = None
#   function_call: Optional[Dict[str, Any]] = None


# class ImageContent(BaseModel):
#   type: Literal["image_url", "text"]
#   text: Optional[str] = None
#   image_url: Optional[Dict[str, str]] = None


# class VisionMessage(BaseModel):
#   role: str
#   content: Union[str, List[ImageContent]]


# class FunctionDefinition(BaseModel):
#   name: str
#   description: str
#   parameters: Dict[str, Any]


# class ChatRequest(BaseModel):
#     conversation_id: Optional[str] = None
#     content_id: Optional[str] = None
#     message: str
#     model: str = DEFAULT_GROK_MODEL
#     system_prompt: Optional[str] = None
#     temperature: Optional[float] = 0.7
#     max_tokens: Optional[int] = 2048
#     stream: bool = True
#     functions: Optional[List[str]] = None


# class VisionRequest(BaseModel):
#   conversation_id: Optional[str] = None
#   messages: List[VisionMessage]
#   model: str = "grok-2-vision-1212"
#   system_prompt: Optional[str] = None
#   max_tokens: Optional[int] = 2048
#   stream: bool = True


# class ConversationRequest(BaseModel):
#   title: Optional[str] = None


# class FunctionCallRequest(BaseModel):
#   name: str
#   arguments: Dict[str, Any]
#   conversation_id: Optional[str] = None
#   message_id: Optional[str] = None


# class ConversationResponse(BaseModel):
#   id: str
#   title: str
#   model: str
#   created_at: datetime
#   updated_at: datetime
#   message_count: int
#   last_message: Optional[str] = None


# class MessageResponse(BaseModel):
#   id: str
#   role: str
#   content: str
#   created_at: datetime
#   function_call: Optional[Dict[str, Any]] = None


# def validate_model(cls, v):
#     if v not in AVAILABLE_MODELS:
#         raise ValueError(f"Model must be one of {AVAILABLE_MODELS}")
#     return v


# class GrokClient:
#   def __init__(self, api_key: str):
#     self.api_key = api_key
#     self.base_url = GROK_API_BASE_URL
#     self.headers = {
#         "Authorization": f"Bearer {api_key}",
#         "Content-Type": "application/json"
#     }

#   async def chat(self, request: ChatRequest) -> StreamingResponse:
#     # Create a modified request without functions parameter
#     request_data = request.model_dump()
#     if 'functions' in request_data:
#       logger.info(
#           f"Removing functions from request: {request_data['functions']}")
#       del request_data['functions']

#     async with httpx.AsyncClient() as client:
#       response = await client.post(
#           f"{self.base_url}/chat",
#           headers=self.headers,
#           json=request_data
#       )

#       if response.status_code != 200:
#         try:
#           # First try to decode as text
#           response_text = await response.text()
#           try:
#             # Then try to parse as JSON
#             error_data = json.loads(response_text)
#             error_message = error_data.get(
#                 "error", {}).get("message", "Grok API error")
#             logger.error(f"Grok API error: {error_data}")
#           except json.JSONDecodeError:
#             # Handle case where response is not valid JSON
#             logger.error(f"Non-JSON error response: {response_text}")
#             error_message = f"Grok API error: Status {response.status_code}"
#         except Exception as e:
#           error_message = f"Grok API error: Status {response.status_code}"
#           logger.error(f"Error parsing error response: {str(e)}")

#         raise HTTPException(
#             status_code=response.status_code, detail=error_message)

#       return response.json()

#   async def create_completion(self, messages: List[Dict[str, Any]], model: str,
#                               functions: Optional[List[Dict[str, Any]]] = None,
#                               temperature: float = 0.7,
#                               max_tokens: int = 2048,
#                               stream: bool = False) -> Dict[str, Any]:
#     """Create a completion with Grok API"""
#     # Ensure model is valid
#     if model not in AVAILABLE_MODELS:
#         logger.warning(
#             f"Model {model} not in available models list, using default {DEFAULT_GROK_MODEL}")
#         model = DEFAULT_GROK_MODEL

#     # Ensure temperature is within valid range (0.0 to 1.0)
#     temperature = max(0.0, min(1.0, temperature))

#     # Ensure max_tokens is reasonable
#     max_tokens = max(1, min(4096, max_tokens))

#     # Validate messages format
#     validated_messages = []
#     for msg in messages:
#         if not isinstance(msg, dict):
#             logger.warning(f"Invalid message format: {msg}")
#             continue

#         role = msg.get("role")
#         content = msg.get("content")

#         if not role or not isinstance(role, str) or role not in ["system", "user", "assistant", "function"]:
#             logger.warning(f"Invalid message role: {role}")
#             continue

#         if content is None:
#             content = ""

#         validated_msg = {"role": role, "content": content}

#         # Add function_call if present
#         if "function_call" in msg and msg["function_call"]:
#             validated_msg["function_call"] = msg["function_call"]

#         validated_messages.append(validated_msg)

#     # Ensure we have at least one message
#     if not validated_messages:
#         logger.error("No valid messages to send to API")
#         raise HTTPException(
#             status_code=400, detail="No valid messages to send to API")

#     payload = {
#         "model": model,
#         "messages": validated_messages,
#         "temperature": temperature,
#         "max_tokens": max_tokens,
#         "stream": stream
#     }

#     # Add tools to the payload in the correct format for x.ai API
#     if functions:
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
#         payload["tools"] = tools
#         # Use auto by default, which lets the model decide whether to call functions
#         payload["tool_choice"] = "auto"
#         logger.info(f"Added {len(tools)} tools to the payload")

#     logger.info(f"Sending payload to API: {json.dumps(payload, default=str)}")
#     async with httpx.AsyncClient(timeout=60.0) as client:
#         response = await client.post(
#             f"{self.base_url}/chat/completions",
#             headers=self.headers,
#             json=payload
#         )

#         if response.status_code != 200:
#             try:
#                 # First try to decode as text
#                 response_text = await response.text()
#                 try:
#                     # Then try to parse as JSON
#                     error_data = json.loads(response_text)
#                     error_message = error_data.get(
#                         "error", {}).get("message", "Grok API error")
#                     logger.error(f"Grok API error: {error_data}")
#                 except json.JSONDecodeError:
#                     # Handle case where response is not valid JSON
#                     logger.error(f"Non-JSON error response: {response_text}")
#                     error_message = f"Grok API error: Status {response.status_code}"
#             except Exception as e:
#                 logger.error(f"Error parsing error response: {str(e)}")
#                 error_message = f"Grok API error: Status {response.status_code}"

#             raise HTTPException(
#                 status_code=response.status_code, detail=error_message)

#         return response.json()

#   async def stream_completion(self, messages: List[Dict[str, Any]], model: str,
#                               functions: Optional[List[Dict[str, Any]]] = None,
#                               temperature: float = 0.7,
#                               max_tokens: int = 2048):
#     """Stream a completion from Grok API with proper tool handling"""
#     # Ensure model is valid
#     if model not in AVAILABLE_MODELS:
#         logger.warning(
#             f"Model {model} not in available models list, using default {DEFAULT_GROK_MODEL}")
#         model = DEFAULT_GROK_MODEL

#     # Ensure temperature is within valid range (0.0 to 1.0)
#     temperature = max(0.0, min(1.0, temperature))

#     # Ensure max_tokens is reasonable
#     max_tokens = max(1, min(4096, max_tokens))

#     # Validate messages format
#     validated_messages = []
#     for msg in messages:
#         if not isinstance(msg, dict):
#             logger.warning(f"Invalid message format: {msg}")
#             continue

#         role = msg.get("role")
#         content = msg.get("content")

#         if not role or not isinstance(role, str) or role not in ["system", "user", "assistant", "function"]:
#             logger.warning(f"Invalid message role: {role}")
#             continue

#         # Ensure content is never None and is a non-empty string for user and assistant roles
#         if content is None:
#             content = ""

#         # Skip empty messages for user and assistant roles (but allow empty function messages)
#         if role in ["user", "assistant"] and (not content or content.strip() == ""):
#             logger.warning(f"Skipping empty {role} message")
#             continue

#         validated_msg = {"role": role, "content": content}

#         # Add function_call if present
#         if "function_call" in msg and msg["function_call"]:
#             validated_msg["function_call"] = msg["function_call"]

#         validated_messages.append(validated_msg)

#     # Ensure we have at least one message
#     if not validated_messages:
#         logger.error("No valid messages to send to API")
#         raise HTTPException(
#             status_code=400, detail="No valid messages to send to API")

#     # Initialize payload and tracking variables
#     payload = {
#         "model": model,
#         "messages": validated_messages,
#         "temperature": temperature,
#         "max_tokens": max_tokens,
#         "stream": True
#     }

#     # Add tools to the payload in the correct format for x.ai API
#     if functions:
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
#         payload["tools"] = tools
#         # Use auto by default, which lets the model decide whether to call functions
#         payload["tool_choice"] = "auto"
#         logger.info(f"Added {len(tools)} tools to the streaming payload")

#     try:
#         async with httpx.AsyncClient(timeout=300.0) as client:
#             logger.info(
#                 f"Sending stream request to {self.base_url}/chat/completions")
#             async with client.stream(
#                 "POST",
#                 f"{self.base_url}/chat/completions",
#                 headers=self.headers,
#                 json=payload
#             ) as response:
#                 if response.status_code != 200:
#                     error_content = await response.aread()
#                     logger.error(f"Raw error response: {error_content}")
#                     try:
#                         error_content_str = error_content.decode(
#                             'utf-8', errors='replace')
#                         error_data = json.loads(error_content_str)
#                         error_message = error_data.get(
#                             "error", {}).get("message", "Grok API error")
#                         logger.error(
#                             f"Full error response: {error_content_str}")
#                     except Exception as e:
#                         logger.error(f"Error parsing error response: {str(e)}")
#                         error_message = f"Grok API error: Status {response.status_code}"
#                     raise HTTPException(
#                         status_code=response.status_code, detail=error_message)

#                 # Use a buffer to collect partial chunks
#                 buffer = ""

#                 async for raw_chunk in response.aiter_text():
#                     buffer += raw_chunk

#                     # Process complete lines in the buffer
#                     lines = buffer.split('\n')
#                     # Keep the last line which might be incomplete
#                     buffer = lines.pop() if lines else ""

#                     for line in lines:
#                         line = line.strip()
#                         if not line:
#                             continue

#                         # Handle [DONE] marker - special case, don't try to parse as JSON
#                         if line == "data: [DONE]":
#                             logger.info("Received [DONE] marker")
#                             yield "data: [DONE]\n\n"
#                             continue

#                         # Only process data: lines
#                         if not line.startswith("data: "):
#                             continue

#                         # Extract the JSON part
#                         data_str = line[6:]

#                         # Another check for [DONE] marker
#                         if data_str.strip() == "[DONE]":
#                             logger.info("Received [DONE] marker in data")
#                             yield "data: [DONE]\n\n"
#                             continue

#                         try:
#                             data = json.loads(data_str)

#                             # Skip metadata chunks without content delta
#                             if "choices" not in data or not data["choices"]:
#                                 continue

#                             delta = data["choices"][0].get("delta", {})

#                             # Handle content
#                             if "content" in delta:
#                                 content = delta["content"]
#                                 yield f"data: {json.dumps({'v': content})}\n\n"

#                             # Handle tool calls - the key part for function calling
#                             if "tool_calls" in delta:
#                                 tool_calls = delta["tool_calls"]
#                                 for tool_call in tool_calls:
#                                     if tool_call.get("type") == "function":
#                                         function_data = tool_call.get(
#                                             "function", {})
#                                         if function_data:
#                                             # Prepare the function call format for the frontend
#                                             function_call = {
#                                                 "name": function_data.get("name", ""),
#                                                 "arguments": function_data.get("arguments", "{}")
#                                             }
#                                             # Send the function call to the frontend
#                                             yield f"data: {json.dumps({'function_call': function_call})}\n\n"
#                                             logger.info(
#                                                 f"Sent function call: {function_call}")

#                         except json.JSONDecodeError:
#                             logger.warning(
#                                 f"Could not parse as JSON: {data_str}")
#                             # Don't try to parse [DONE] as JSON
#                             if data_str.strip() == "[DONE]":
#                                 logger.info(
#                                     "Received [DONE] marker after JSON parse error")
#                                 yield "data: [DONE]\n\n"

#                 # Process any remaining buffer
#                 if buffer:
#                     line = buffer.strip()
#                     if line == "data: [DONE]":
#                         logger.info(
#                             "Received [DONE] marker in remaining buffer")
#                         yield "data: [DONE]\n\n"

#     except Exception as e:
#         logger.error(f"Stream error: {str(e)}")
#         try:
#             yield f"data: {json.dumps({'error': str(e)})}\n\n"
#             # Always send DONE marker even after error
#             yield "data: [DONE]\n\n"
#         except:
#             pass


# class FunctionRegistry:
#   def __init__(self):
#     self.functions = {}
#     self._register_default_functions()

#   def _register_default_functions(self):
#     # Register toggle_platform function
#     self.register(
#         name="toggle_platform",
#         description="Toggle selected platforms for content creation",
#         parameters={
#             "type": "object",
#             "properties": {
#                 "platforms": {
#                     "type": "array",
#                     "items": {
#                         "type": "string",
#                         "enum": ["facebook", "instagram", "twitter", "threads", "linkedin", "tiktok", "youtube"]
#                     },
#                     "description": "List of platforms to create content for"
#                 }
#             },
#             "required": ["platforms"]
#         },
#         handler=self._toggle_platform
#     )

#     # Register get_current_time function
#     self.register(
#         name="get_current_time",
#         description="Get the current server time",
#         parameters={
#             "type": "object",
#             "properties": {},
#             "required": []
#         },
#         handler=self._get_current_time
#     )

#   async def _get_current_time(self) -> str:
#     return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#   async def _toggle_platform(self, platforms):
#     """Handle platform toggling"""
#     logger.info(f"Platform toggle function called with: {platforms}")

#     if not platforms or not isinstance(platforms, list):
#       logger.warning(f"Invalid platforms format received: {platforms}")
#       platforms = []

#     return {
#         "platforms": platforms,
#         "status": "toggled",
#         "message": f"Selected platforms: {', '.join(platforms)}"
#     }

#   def register(self, name, description, parameters, handler):
#     """Register a function with its schema and handler"""
#     self.functions[name] = {
#         "name": name,
#         "description": description,
#         "parameters": parameters,
#         "handler": handler
#     }

#   def get_functions(self, function_names=None):
#     """Get function schemas for specified functions or all if None"""
#     if function_names is None:
#         return [
#             {"name": f["name"], "description": f["description"],
#              "parameters": f["parameters"]}
#             for f in self.functions.values()
#         ]

#     result = []
#     for name in function_names:
#         if name in self.functions:
#             f = self.functions[name]
#             result.append({
#                 "name": f["name"],
#                 "description": f["description"],
#                 "parameters": f["parameters"]
#             })

#     return result

#   async def execute(self, name, arguments):
#     """Execute a registered function with the provided arguments"""
#     if name not in self.functions:
#         raise ValueError(f"Function {name} not found")

#     handler = self.functions[name]["handler"]
#     try:
#         return await handler(**arguments)
#     except Exception as e:
#         logger.error(f"Error executing function {name}: {str(e)}")
#         return {"error": str(e)}


# # Create function registry instance
# function_registry = FunctionRegistry()


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


# async def create_conversation(db: Database, user_id: str, model: str, title: Optional[str] = None, content_id: Optional[str] = None):
#     """Create a new conversation"""
#     conversation_id = str(uuid.uuid4())
#     now = datetime.now(timezone.utc)

#     query = """
#     INSERT INTO mo_llm_conversations (
#         id, user_id, title, model_id, created_at, updated_at, content_id
#     ) VALUES (
#         :id, :user_id, :title, :model, :created_at, :updated_at, :content_id
#     ) RETURNING id
#     """

#     values = {
#         "id": conversation_id,
#         "user_id": user_id,
#         "title": title or "New Conversation",
#         "model": model,
#         "created_at": now,
#         "updated_at": now,
#         "content_id": content_id
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


# async def store_function_call(db: Database, message_id: str, function_name: str,
#                               arguments: Dict[str, Any], result: Optional[Dict[str, Any]] = None):
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

#     # Add system prompt if provided
#     if system_prompt:
#         formatted_messages.append({
#             "role": "system",
#             "content": system_prompt
#         })
#     else:
#         formatted_messages.append({
#             "role": "system",
#             "content": DEFAULT_SYSTEM_PROMPT
#         })

#     # Process each message
#     for i, msg in enumerate(messages):
#         # Log message details for debugging
#         logger.info(
#             f"Processing message {i}: role={msg['role']}, content_type={type(msg['content'])}, content_length={len(msg['content'] or '')}")

#         # Check for empty content
#         if not msg["content"] or msg["content"].strip() == "":
#             logger.warning(
#                 f"Message {i} has empty content, role={msg['role']}")
#             # Skip empty user/assistant messages to prevent API errors
#             if msg["role"] in ["user", "assistant"] and not msg["function_call"]:
#                 logger.warning(f"Skipping empty {msg['role']} message")
#                 continue

#         message_dict = {
#             "role": msg["role"],
#             "content": msg["content"] or ""
#         }

#         # Add function call if present
#         if msg["function_call"]:
#             function_call = json.loads(msg["function_call"])
#             message_dict["function_call"] = function_call
#             logger.info(
#                 f"Message {i} has function_call: {function_call.get('name')}")

#         formatted_messages.append(message_dict)

#     # Final validation
#     if not any(msg.get("role") == "user" for msg in formatted_messages):
#         logger.error("No user messages found in conversation history")

#     return formatted_messages


# async def process_function_call(db: Database, conversation_id: str, function_call_data: Dict[str, Any]):
#     """Process a function call from Grok"""
#     function_name = function_call_data.get("name", "")
#     arguments_str = function_call_data.get("arguments", "{}")

#     try:
#         arguments = json.loads(arguments_str)
#     except json.JSONDecodeError:
#         arguments = {}

#     # Store function call message
#     message_id = await add_message(
#         db=db,
#         conversation_id=conversation_id,
#         role="assistant",
#         content="",  # Empty content for function call messages
#         function_call={"name": function_name, "arguments": arguments}
#     )

#     # Execute the function
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


# async def stream_chat_response(db: Database, conversation_id: str, user_id: str,
#                                request: ChatRequest, grok_client: GrokClient):
#     """Generate streaming response from Grok"""
#     # Get conversation and verify it belongs to user
#     await get_conversation(db, conversation_id, user_id)

#     # Get conversation history
#     conversation_messages = await prepare_conversation_messages(
#         db=db,
#         conversation_id=conversation_id,
#         system_prompt=request.system_prompt
#     )

#     # Log the conversation messages for debugging
#     logger.info(f"Total conversation messages: {len(conversation_messages)}")
#     for i, msg in enumerate(conversation_messages):
#         logger.info(
#             f"Message {i}: role={msg.get('role')}, content_length={len(msg.get('content', ''))}")
#         # Log first two and last two messages
#         if i < 2 or i >= len(conversation_messages) - 2:
#             logger.info(
#                 f"Message {i} content: {msg.get('content', '')[:100]}...")

#     # Prepare function definitions if needed
#     function_definitions = None
#     if request.functions:
#         function_definitions = function_registry.get_functions(
#             request.functions)
#         logger.info(f"Using functions: {request.functions}")
#         logger.info(
#             f"Function definitions: {[f['name'] for f in function_definitions]}")

#     # Initialize response tracking
#     full_response = ""
#     current_function_call = None
#     function_call_detected = False

#     try:
#         logger.info(
#             f"Starting stream_completion with model={request.model}, temperature={request.temperature}, max_tokens={request.max_tokens}")
#         # Stream response from Grok
#         async for chunk in grok_client.stream_completion(
#             messages=conversation_messages,
#             model=request.model,
#             functions=function_definitions,
#             temperature=request.temperature,
#             max_tokens=request.max_tokens
#         ):
#             try:
#                 # Pass the chunk directly to the client
#                 yield chunk

#                 # Process chunk for database storage
#                 if chunk.startswith('data: '):
#                     try:
#                         data = json.loads(chunk[6:])

#                         # Handle content chunks
#                         if 'v' in data:
#                             content_chunk = data['v']
#                             full_response += content_chunk

#                         # Handle function calls
#                         elif 'function_call' in data:
#                             function_call_detected = True
#                             current_function_call = data['function_call']
#                             logger.info(
#                                 f"Function call detected: {current_function_call['name']}")
#                     except Exception as e:
#                         logger.error(f"Error processing chunk: {e}")

#             except ConnectionResetError:
#                 logger.warning("Client disconnected during streaming")
#                 break
#             except asyncio.CancelledError:
#                 logger.warning("Stream was cancelled")
#                 break
#             except Exception as e:
#                 logger.error(f"Error yielding chunk: {str(e)}")
#                 break

#         # Process function call if detected
#         if function_call_detected and current_function_call:
#             try:
#                 logger.info(
#                     f"Processing function call: {current_function_call}")

#                 # Process the function call
#                 function_name = current_function_call.get("name")
#                 if function_name == "toggle_platform":
#                     try:
#                         # Parse arguments
#                         args = json.loads(
#                             current_function_call.get("arguments", "{}"))
#                         platforms = args.get("platforms", [])

#                         if platforms:
#                             logger.info(
#                                 f"Processing toggle_platform with platforms: {platforms}")

#                             # Execute the function
#                             result = await function_registry.execute("toggle_platform", {"platforms": platforms})
#                             logger.info(f"Function result: {result}")

#                             # Store function call and result
#                             message_id = await add_message(
#                                 db=db,
#                                 conversation_id=conversation_id,
#                                 role="assistant",
#                                 content="",
#                                 function_call=current_function_call
#                             )

#                             await store_function_call(
#                                 db=db,
#                                 message_id=message_id,
#                                 function_name="toggle_platform",
#                                 arguments={"platforms": platforms},
#                                 result=result
#                             )

#                             # Add function result as a message
#                             await add_message(
#                                 db=db,
#                                 conversation_id=conversation_id,
#                                 role="function",
#                                 content=json.dumps(result)
#                             )
#                     except Exception as e:
#                         logger.error(
#                             f"Error processing toggle_platform function: {e}")
#             except Exception as e:
#                 logger.error(f"Error processing function call: {e}")

#         # Store the complete response if we have content
#         if full_response:
#             try:
#                 await add_message(
#                     db=db,
#                     conversation_id=conversation_id,
#                     role="assistant",
#                     content=full_response
#                 )
#             except Exception as e:
#                 logger.error(f"Error storing response: {str(e)}")

#         # Add final marker
#         try:
#             yield "data: [DONE]\n\n"
#         except Exception as e:
#             logger.error(f"Error sending final marker: {str(e)}")

#     except asyncio.CancelledError:
#         logger.warning("Stream was cancelled by client")
#     except Exception as e:
#         logger.error(f"Error in stream_chat_response: {str(e)}")
#         # Try to send an error message to the client
#         try:
#             yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
#             yield "data: [DONE]\n\n"
#         except Exception:
#             pass


# async def stream_vision_response(db: Database, conversation_id: str, user_id: str,
#                                  request: VisionRequest, grok_client: GrokClient):
#     """Generate streaming response from Grok for vision requests"""
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

#     # Initialize Grok client with API key
#     if not GROK_API_KEY:
#         raise HTTPException(
#             status_code=500, detail="Grok API key not configured")

#     # Ensure model is valid
#     model = request.model
#     if model not in AVAILABLE_MODELS:
#         logger.warning(
#             f"Vision model {model} not in available models list, using grok-2-vision")
#         model = "grok-2-vision"  # Default vision model

#     # Ensure max_tokens is reasonable
#     max_tokens = max(1, min(4096, request.max_tokens))

#     # Create payload for vision request
#     payload = {
#         "model": model,
#         "messages": vision_messages,
#         "max_tokens": max_tokens,
#         "stream": True
#     }

#     # Optional: Add tools if vision model supports function calling
#     # This depends on whether the vision model supports the same tool format
#     tools = function_registry.get_functions(["toggle_platform"])
#     if tools:
#         formatted_tools = []
#         for func in tools:
#             formatted_tools.append({
#                 "type": "function",
#                 "function": {
#                     "name": func["name"],
#                     "description": func["description"],
#                     "parameters": func["parameters"]
#                 }
#             })
#         payload["tools"] = formatted_tools
#         payload["tool_choice"] = "auto"
#         logger.info(
#             f"Added {len(formatted_tools)} tools to the vision payload")

#     # Log the payload for debugging (excluding large image data)
#     debug_payload = payload.copy()
#     for msg in debug_payload.get("messages", []):
#         if isinstance(msg.get("content"), list):
#             for item in msg.get("content", []):
#                 if item.get("type") == "image_url" and "image_url" in item:
#                     item["image_url"] = {"url": "[IMAGE DATA REDACTED]"}
#     logger.info(
#         f"Sending vision payload to API: {json.dumps(debug_payload, default=str)}")

#     # Stream the response
#     async with httpx.AsyncClient(timeout=300.0) as client:
#         async with client.stream(
#             "POST",
#             f"{GROK_API_BASE_URL}/chat/completions",
#             headers={
#                 "Authorization": f"Bearer {GROK_API_KEY}",
#                 "Content-Type": "application/json"
#             },
#             json=payload
#         ) as response:
#             if response.status_code != 200:
#                 error_content = await response.aread()
#                 try:
#                     error_content_str = error_content.decode(
#                         'utf-8', errors='replace')
#                     try:
#                         error_data = json.loads(error_content_str)
#                         error_message = error_data.get(
#                             "error", {}).get("message", "Grok API error")
#                         logger.error(
#                             f"Full error response: {error_content_str}")
#                     except json.JSONDecodeError:
#                         logger.error(
#                             f"Non-JSON error response: {error_content_str}")
#                         error_message = f"Grok API error: Status {response.status_code}"
#                 except Exception as e:
#                     logger.error(f"Error parsing error response: {str(e)}")
#                     error_message = f"Grok API error: Status {response.status_code}"

#                 logger.error(error_message)
#                 raise HTTPException(
#                     status_code=response.status_code, detail=error_message)

#             # Stream response chunks
#             full_response = ""
#             function_call_detected = False
#             buffer = ""

#             async for chunk in response.aiter_text():
#                 buffer += chunk
#                 lines = buffer.split("\n")
#                 buffer = lines.pop() if lines else ""

#                 for line in lines:
#                     line = line.strip()
#                     if not line:
#                         continue

#                     # Handle [DONE] marker
#                     if line == "data: [DONE]":
#                         yield "data: [DONE]\n\n"
#                         continue

#                     # Process data lines
#                     if line.startswith("data: "):
#                         data_str = line[6:]
#                         if data_str.strip() == "[DONE]":
#                             yield "data: [DONE]\n\n"
#                             continue

#                         try:
#                             data = json.loads(data_str)

#                             # Handle content chunks
#                             if "choices" in data and data["choices"] and "delta" in data["choices"][0]:
#                                 delta = data["choices"][0]["delta"]

#                                 # Handle content
#                                 if "content" in delta:
#                                     content = delta["content"]
#                                     full_response += content
#                                     yield f"data: {json.dumps({'v': content})}\n\n"

#                                 # Handle tool calls - important for function calling in vision models
#                                 if "tool_calls" in delta:
#                                     tool_calls = delta["tool_calls"]
#                                     for tool_call in tool_calls:
#                                         if tool_call.get("type") == "function":
#                                             function_data = tool_call.get(
#                                                 "function", {})
#                                             if function_data:
#                                                 function_call_detected = True
#                                                 function_call = {
#                                                     "name": function_data.get("name", ""),
#                                                     "arguments": function_data.get("arguments", "{}")
#                                                 }
#                                                 yield f"data: {json.dumps({'function_call': function_call})}\n\n"
#                                                 logger.info(
#                                                     f"Function call detected in vision: {function_call}")

#                                                 # For toggle_platform function, process it immediately
#                                                 if function_call["name"] == "toggle_platform":
#                                                     try:
#                                                         args = json.loads(
#                                                             function_call["arguments"])
#                                                         platforms = args.get(
#                                                             "platforms", [])
#                                                         if platforms and conversation_id:
#                                                             # Store and process the function call
#                                                             await process_function_call(
#                                                                 db=db,
#                                                                 conversation_id=conversation_id,
#                                                                 function_call_data=function_call
#                                                             )
#                                                     except Exception as e:
#                                                         logger.error(
#                                                             f"Error processing vision function call: {e}")
#                         except json.JSONDecodeError:
#                             logger.error(f"Error parsing vision chunk: {line}")
#                         except Exception as e:
#                             logger.error(f"Error processing vision chunk: {e}")

#             # Process any remaining buffer
#             if buffer:
#                 if buffer.strip() == "data: [DONE]":
#                     yield "data: [DONE]\n\n"

#             # Store the complete response if we have a conversation ID
#             if conversation_id and full_response:
#                 # If we don't have an existing conversation, create one
#                 if not await db.fetch_one(
#                     "SELECT id FROM mo_llm_conversations WHERE id = :id AND user_id = :user_id",
#                     {"id": conversation_id, "user_id": user_id}
#                 ):
#                     await create_conversation(
#                         db=db,
#                         user_id=user_id,
#                         model=request.model,
#                         title="Vision Conversation"
#                     )

#                 # Store the assistant response
#                 await add_message(
#                     db=db,
#                     conversation_id=conversation_id,
#                     role="assistant",
#                     content=full_response
#                 )


# @router.get("/models")
# async def get_models():
#     """Get available Grok models"""
#     return {
#         "models": [
#             {"id": "grok-2-1212", "name": "Grok 2",
#              "description": "Advanced language model with general capabilities"},
#             {"id": "grok-2-vision-1212", "name": "Grok 2 Vision",
#              "description": "Vision-enhanced model for image understanding"}
#         ]
#     }


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
#     content_id: Optional[str] = None
# ):
#     """List all conversations for a user, optionally filtered by content_id"""
#     query_values = {"user_id": current_user["uid"]}

#     if content_id:
#         query = """
#         SELECT
#             id, title, model_id as model,
#             created_at, updated_at, content_id,
#             (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
#             (SELECT content FROM mo_llm_messages
#             WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
#             ORDER BY created_at DESC LIMIT 1) as last_message
#         FROM mo_llm_conversations
#         WHERE user_id = :user_id AND content_id = :content_id
#         ORDER BY updated_at DESC
#         """
#         query_values["content_id"] = content_id
#     else:
#         query = """
#         SELECT
#             id, title, model_id as model,
#             created_at, updated_at, content_id,
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

#     grok_client = GrokClient(GROK_API_KEY)

#     # Get or create conversation
#     conversation_id = request.conversation_id
#     if not conversation_id:
#         # Create a new conversation
#         conversation_id = await create_conversation(
#             db=db,
#             user_id=current_user["uid"],
#             model=request.model,
#             title=None,  # We'll update this later based on first message
#             content_id=request.content_id
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
#         return StreamingResponse(
#             stream_chat_response(
#                 db=db,
#                 conversation_id=conversation_id,
#                 user_id=current_user["uid"],
#                 request=request,
#                 grok_client=grok_client
#             ),
#             media_type="text/event-stream"
#         )
#     else:
#         # For non-streaming responses, get complete response
#         conversation_messages = await prepare_conversation_messages(
#             db=db,
#             conversation_id=conversation_id,
#             system_prompt=request.system_prompt
#         )

#         # Prepare function definitions if needed
#         function_definitions = None
#         if request.functions:
#             function_definitions = function_registry.get_functions(
#                 request.functions)
#             logger.info(f"Using functions: {request.functions}")
            

#         # Get completion from Grok
#         completion = await grok_client.create_completion(
#             messages=conversation_messages,
#             model=request.model,
#             functions=function_definitions,
#             temperature=request.temperature,
#             max_tokens=request.max_tokens,
#             stream=False
#         )

#         # Extract response
#         response_message = completion["choices"][0]["message"]
#         content = response_message.get("content", "")

#         # Check for tool calls (function calls in the x.ai format)
#         tool_calls = None
#         function_result = None

#         if "tool_calls" in response_message:
#             tool_calls = response_message["tool_calls"]

#             # Process each tool call
#             for tool_call in tool_calls:
#                 if tool_call.get("type") == "function":
#                     function_data = tool_call.get("function", {})
#                     if function_data:
#                         function_name = function_data.get("name", "")
#                         function_args = function_data.get("arguments", "{}")

#                         # Create a function call data structure for our system
#                         function_call_data = {
#                             "name": function_name,
#                             "arguments": function_args
#                         }

#                         # Process the function call
#                         function_result = await process_function_call(
#                             db=db,
#                             conversation_id=conversation_id,
#                             function_call_data=function_call_data
#                         )

#                         # If needed, get a new completion with the function result
#                         conversation_messages = await prepare_conversation_messages(
#                             db=db,
#                             conversation_id=conversation_id,
#                             system_prompt=request.system_prompt
#                         )

#                         completion = await grok_client.create_completion(
#                             messages=conversation_messages,
#                             model=request.model,
#                             functions=function_definitions,
#                             temperature=request.temperature,
#                             max_tokens=request.max_tokens,
#                             stream=False
#                         )

#                         # Extract final response
#                         response_message = completion["choices"][0]["message"]
#                         content = response_message.get("content", "")

#         # Store assistant response
#         message_id = await add_message(
#             db=db,
#             conversation_id=conversation_id,
#             role="assistant",
#             content=content,
#             function_call=function_result["function_call"] if function_result else None
#         )

#         # Return response
#         return {
#             "conversation_id": conversation_id,
#             "message_id": message_id,
#             "content": content,
#             "function_call": function_result
#         }


# @router.post("/chat/stream")
# async def stream_chat_get(
#     request: ChatRequest,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Stream a chat response via GET for EventSource compatibility"""
#     # Sanitize the message
#     if request.message:
#         original_message = request.message
#         request.message = sanitize_message(request.message)
#         if not request.message:
#             logger.error("Message became empty after sanitization")
#             raise HTTPException(
#                 status_code=400, detail="Message cannot be empty after sanitization")

#     # Initialize Grok client
#     if not GROK_API_KEY:
#         raise HTTPException(
#             status_code=500, detail="Grok API key not configured")

#     grok_client = GrokClient(GROK_API_KEY)

#     # Get or create conversation
#     conv_id = request.conversation_id
#     if not conv_id:
#         # Create a new conversation
#         conv_id = await create_conversation(
#             db=db,
#             user_id=current_user["uid"],
#             model=request.model,
#             title=None
#         )
#     else:
#         # Verify conversation exists and belongs to user
#         await get_conversation(db, conv_id, current_user["uid"])

#     # Add user message to conversation - store the original message if available
#     await add_message(
#         db=db,
#         conversation_id=conv_id,
#         role="user",
#         content=original_message if 'original_message' in locals() else request.message
#     )

#     # Update conversation title if it's new
#     if not request.conversation_id:
#         # Use first few words of message as title
#         title_words = request.message.split()[:5]
#         title = " ".join(title_words) + "..."

#         await db.execute(
#             "UPDATE mo_llm_conversations SET title = :title WHERE id = :id",
#             {"id": conv_id, "title": title}
#         )

#     # Return streaming response
#     return StreamingResponse(
#         stream_chat_response(
#             db=db,
#             conversation_id=conv_id,
#             user_id=current_user["uid"],
#             request=request,
#             grok_client=grok_client
#         ),
#         media_type="text/event-stream"
#     )


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
#                 request=request,
#                 grok_client=GrokClient(GROK_API_KEY)
#             ),
#             media_type="text/event-stream"
#         )
#     else:
#       # Initialize Grok client with API key
#         grok_client = GrokClient(GROK_API_KEY)

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

#         # Optional: Add tools if vision model supports function calling
#         tools = function_registry.get_functions(["toggle_platform"])
#         if tools:
#             formatted_tools = []
#             for func in tools:
#                 formatted_tools.append({
#                     "type": "function",
#                     "function": {
#                         "name": func["name"],
#                         "description": func["description"],
#                         "parameters": func["parameters"]
#                     }
#                 })

#             # Call Grok API with tools
#             try:
#                 response = await grok_client.create_completion(
#                     messages=vision_messages,
#                     model=request.model,
#                     functions=formatted_tools,
#                     temperature=0.7,
#                     max_tokens=request.max_tokens,
#                     stream=False
#                 )

#                 result_message = response["choices"][0]["message"]
#                 content = result_message.get("content", "")

#                 # Handle any tool calls returned by the model
#                 if "tool_calls" in result_message:
#                     tool_calls = result_message["tool_calls"]
#                     for tool_call in tool_calls:
#                         if tool_call.get("type") == "function":
#                             function_data = tool_call.get("function", {})
#                             if function_data:
#                                 function_name = function_data.get("name", "")
#                                 function_args = function_data.get(
#                                     "arguments", "{}")

#                                 # Process function call (especially toggle_platform)
#                                 if function_name == "toggle_platform" and conversation_id:
#                                     function_call_data = {
#                                         "name": function_name,
#                                         "arguments": function_args
#                                     }

#                                     await process_function_call(
#                                         db=db,
#                                         conversation_id=conversation_id,
#                                         function_call_data=function_call_data
#                                     )

#                 # Store the response if there's a conversation ID
#                 if conversation_id and request.conversation_id:
#                     await add_message(
#                         db=db,
#                         conversation_id=conversation_id,
#                         role="assistant",
#                         content=content
#                     )

#                 return {"response": content}

#             except Exception as e:
#                 logger.error(f"Vision API error: {str(e)}")
#                 raise HTTPException(
#                     status_code=500, detail=f"Vision API error: {str(e)}")

#         # Call Grok API without tools (fallback if tools aren't supported for vision)
#         else:
#             try:
#                 response = await httpx.post(
#                     f"{GROK_API_BASE_URL}/chat/completions",
#                     headers={
#                         "Authorization": f"Bearer {GROK_API_KEY}",
#                         "Content-Type": "application/json"
#                     },
#                     json={
#                         "model": request.model,
#                         "messages": vision_messages,
#                         "max_tokens": request.max_tokens
#                     },
#                     timeout=60.0
#                 )

#                 if response.status_code != 200:
#                     error_data = response.json()
#                     logger.error(f"Grok Vision API error: {error_data}")
#                     raise HTTPException(
#                         status_code=response.status_code,
#                         detail=error_data.get("error", {}).get(
#                             "message", "Grok Vision API error")
#                     )

#                 result = response.json()
#                 content = result["choices"][0]["message"]["content"]

#                 # Store the response if there's a conversation ID
#                 if conversation_id and request.conversation_id:
#                     await add_message(
#                         db=db,
#                         conversation_id=conversation_id,
#                         role="assistant",
#                         content=content
#                     )

#                 return {"response": content}

#             except Exception as e:
#                 logger.error(f"Vision API error: {str(e)}")
#                 raise HTTPException(
#                     status_code=500, detail=f"Vision API error: {str(e)}")


# @router.get("/content/{content_id}/conversation")
# async def get_content_conversation(
#     content_id: str,
#     current_user: dict = Depends(get_current_user),
#     db: Database = Depends(get_database)
# ):
#     """Get or create a conversation for a content item"""
#     # Check if content exists and belongs to user
#     content_query = """
#     SELECT uuid FROM mo_content 
#     WHERE uuid = :content_id AND firebase_uid = :user_id
#     """
#     content = await db.fetch_one(
#         query=content_query,
#         values={"content_id": content_id, "user_id": current_user["uid"]}
#     )
#     if not content:
#         raise HTTPException(status_code=404, detail="Content not found")

#     # Try to find an existing conversation for this content
#     conversation_query = """
#     SELECT 
#         id, title, model_id as model,
#         created_at, updated_at, 
#         content_id,
#         (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
#         (SELECT content FROM mo_llm_messages 
#         WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
#         ORDER BY created_at DESC LIMIT 1) as last_message
#     FROM mo_llm_conversations
#     WHERE content_id = :content_id AND user_id = :user_id
#     ORDER BY updated_at DESC
#     LIMIT 1
#     """
#     conversation = await db.fetch_one(
#         query=conversation_query,
#         values={"content_id": content_id, "user_id": current_user["uid"]}
#     )

#     if conversation:
#         # Return existing conversation
#         conversation_data = dict(conversation)

#         # Get messages for the conversation
#         messages_query = """
#         SELECT id, role, content, created_at, function_call
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
#             content_id=content_id
#         )

#         # Get the new conversation
#         new_conversation = await get_conversation(db, conversation_id, current_user["uid"])

#         return {
#             "conversation": new_conversation,
#             "messages": []
#         }
