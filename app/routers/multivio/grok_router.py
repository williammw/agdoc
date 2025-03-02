from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, JSONResponse
from app.dependencies import get_current_user, get_database
from databases import Database
from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field, validator
import uuid
import json
import os
import httpx
import logging
import asyncio
from datetime import datetime, timezone

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter()

# Load environment variables
GROK_API_KEY = os.getenv("XAI_API_KEY")  # Using existing XAI_API_KEY env var
GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# Model constants
DEFAULT_GROK_MODEL = "grok-2-1212"
AVAILABLE_MODELS = ["grok-2-1212", "grok-2-vision-1212"]

# Default system prompt
DEFAULT_SYSTEM_PROMPT = """
You are a helpful assistant.
For generated content, you should use markdown format.
For LaTeX, you should use the following format:
```latex
{latex code}
For generating tables, please structure the response in this exact format:
{markdown table}
"""
class Message(BaseModel):
  role: str
  content: str
  name: Optional[str] = None
  function_call: Optional[Dict[str, Any]] = None

class ImageContent(BaseModel):
  type: Literal["image_url", "text"]
  text: Optional[str] = None
  image_url: Optional[Dict[str, str]] = None
class VisionMessage(BaseModel):
  role: str
  content: Union[str, List[ImageContent]]

class FunctionDefinition(BaseModel):
  name: str
  description: str
  parameters: Dict[str, Any]


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    content_id: Optional[str] = None
    message: str
    model: str = DEFAULT_GROK_MODEL
    system_prompt: Optional[str] = None
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048
    stream: bool = True
    functions: Optional[List[str]] = None

class VisionRequest(BaseModel):
  conversation_id: Optional[str] = None
  messages: List[VisionMessage]
  model: str = "grok-2-vision-1212"
  system_prompt: Optional[str] = None
  max_tokens: Optional[int] = 2048
  stream: bool = True

class ConversationRequest(BaseModel):
  title: Optional[str] = None

class FunctionCallRequest(BaseModel):
  name: str
  arguments: Dict[str, Any]
  conversation_id: Optional[str] = None
  message_id: Optional[str] = None

class ConversationResponse(BaseModel):
  id: str
  id: str
  title: str
  model: str
  created_at: datetime
  updated_at: datetime
  message_count: int
  last_message: Optional[str] = None

class MessageResponse(BaseModel):
  id: str
  role: str
  content: str
  created_at: datetime
  function_call: Optional[Dict[str, Any]] = None


def validate_model(cls, v):
    if v not in AVAILABLE_MODELS:
        raise ValueError(f"Model must be one of {AVAILABLE_MODELS}")
    return v


class GrokClient:
  def __init__(self, api_key: str):
    self.api_key = api_key
    self.base_url = GROK_API_BASE_URL
    self.headers = {
      "Authorization": f"Bearer {api_key}",
      "Content-Type": "application/json"
    }

  async def chat(self, request: ChatRequest) -> StreamingResponse:
    async with httpx.AsyncClient() as client:
      response = await client.post(
        f"{self.base_url}/chat",
        headers=self.headers, 
        json=request.model_dump()
      )
      return response.json()

  async def create_completion(self, messages: List[Dict[str, Any]], model: str,
                              functions: Optional[List[Dict[str, Any]]]=None,
                              temperature: float=0.7,
                              max_tokens: int=2048,
                              stream: bool=False) -> Dict[str, Any]:
        """Create a completion with Grok API"""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }

        if functions:
            payload["functions"] = functions

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload
            )

            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Grok API error: {error_data}")
                raise HTTPException(status_code=response.status_code,
                                  detail=error_data.get("error", {}).get("message", "Grok API error"))

            return response.json()

  async def stream_completion(self, messages: List[Dict[str, Any]], model: str,
                              functions: Optional[List[Dict[str, Any]]]=None,
                              temperature: float=0.7,
                              max_tokens: int=2048):
        """Stream a completion from Grok API"""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }

        if functions:
            payload["functions"] = functions

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload
            ) as response:
                if response.status_code != 200:
                    error_content = await response.aread()
                    try:
                        error_data = json.loads(error_content)
                        error_message = error_data.get("error", {}).get("message", "Grok API error")
                    except:
                        error_message = f"Grok API error: Status {response.status_code}"

                    logger.error(error_message)
                    raise HTTPException(status_code=response.status_code, detail=error_message)

                buffer = ""
                async for chunk in response.aiter_text():
                    if chunk.startswith("data: "):
                        data_str = chunk[6:]
                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                if "delta" in data["choices"][0] and "content" in data["choices"][0]["delta"]:
                                    content = data["choices"][0]["delta"]["content"]
                                    buffer += content
                                    yield f"data: {json.dumps({'v': content})}\n\n"
                                elif "function_call" in data["choices"][0].get("delta", {}):
                                    function_data = data["choices"][0]["delta"]["function_call"]
                                    yield json.dumps({
                                        "type": "function_call",
                                        "function_call": function_data
                                    })
                        except json.JSONDecodeError:
                            logger.error(f"Error parsing chunk: {chunk}")
                        except Exception as e:
                            logger.error(f"Error processing chunk: {str(e)}")

class FunctionRegistry:
  def __init__(self):
    self.functions = {}
    self._register_default_functions()

  def _register_default_functions(self):
    self.functions["get_current_time"] = self._get_current_time

  async def _get_current_time(self) -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _register_default_functions(self):
    """Register default system functions"""
    # Weather function
    self.register(
        name="get_weather",
        description="Get current weather in a location",
        parameters={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
            },
            "required": ["location"]
        },
        handler=self._get_weather
    )
    
    # Calculator function
    self.register(
        name="calculate",
        description="Perform a mathematical calculation",
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Mathematical expression to evaluate"}
            },
            "required": ["expression"]
        },
        handler=self._calculate
    )
    
    # Search function
    self.register(
        name="search_web",
        description="Search the web for information",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results to return"}
            },
            "required": ["query"]
        },
        handler=self._search_web
    )

def register(self, name, description, parameters, handler):
    """Register a function with its schema and handler"""
    self.functions[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler
    }

def get_functions(self, function_names=None):
    """Get function schemas for specified functions or all if None"""
    if function_names is None:
        return [
            {"name": f["name"], "description": f["description"], "parameters": f["parameters"]}
            for f in self.functions.values()
        ]
    
    result = []
    for name in function_names:
        if name in self.functions:
            f = self.functions[name]
            result.append({
                "name": f["name"],
                "description": f["description"],
                "parameters": f["parameters"]
            })
    
    return result

async def execute(self, name, arguments):
    """Execute a registered function with the provided arguments"""
    if name not in self.functions:
        raise ValueError(f"Function {name} not found")
    
    handler = self.functions[name]["handler"]
    try:
        return await handler(**arguments)
    except Exception as e:
        logger.error(f"Error executing function {name}: {str(e)}")
        return {"error": str(e)}

# Default function implementations
async def _get_weather(self, location, unit="celsius"):
    """Mock weather function - replace with actual API call"""
    await asyncio.sleep(1)  # Simulate API call
    temp = 22 if unit == "celsius" else 72
    return {
        "location": location,
        "temperature": temp,
        "unit": unit,
        "condition": "Sunny",
        "humidity": 65,
        "wind_speed": 10
    }

async def _calculate(self, expression):
    """Simple calculator function"""
    try:
        # This is a simplified approach and not secure for production
        # In a real app, use a math library like 'sympy' for safe evaluation
        result = eval(expression)
        return {
            "expression": expression,
            "result": result
        }
    except Exception as e:
        return {
            "expression": expression,
            "error": str(e)
        }

async def _search_web(self, query, num_results=3):
    """Mock search function - replace with actual search API"""
    await asyncio.sleep(1)  # Simulate API call
    return {
        "query": query,
        "results": [
            {"title": f"Result {i+1} for {query}", "url": f"https://example.com/result{i+1}"} 
            for i in range(min(num_results, 5))
        ]
    }


function_registry = FunctionRegistry()

async def get_conversation(db: Database, conversation_id: str, user_id: str):
    """Get a conversation by ID"""
    query = """
    SELECT
        id, title, model_id as model,
        created_at, updated_at,
        (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
        (SELECT content FROM mo_llm_messages
        WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
        ORDER BY created_at DESC LIMIT 1) as last_message
    FROM mo_llm_conversations
    WHERE id = :conversation_id AND user_id = :user_id
    """
    result = await db.fetch_one(query=query, values={"conversation_id": conversation_id, "user_id": user_id})
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return dict(result)

async def get_conversation_messages(db: Database, conversation_id: str, user_id: str):
    """Get messages for a conversation"""
    # First verify the conversation belongs to the user
    conversation_query = """
    SELECT id FROM mo_llm_conversations
    WHERE id = :conversation_id AND user_id = :user_id
    """
    conversation = await db.fetch_one(
        query=conversation_query,
        values={"conversation_id": conversation_id, "user_id": user_id}
    )

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get the messages
    messages_query = """
    SELECT 
        id, role, content, created_at, function_call 
    FROM mo_llm_messages 
    WHERE conversation_id = :conversation_id 
    ORDER BY created_at
    """
    messages = await db.fetch_all(query=messages_query, values={"conversation_id": conversation_id})
    return [dict(msg) for msg in messages]


async def create_conversation(db: Database, user_id: str, model: str, title: Optional[str] = None, content_id: Optional[str] = None):
    """Create a new conversation"""
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

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
        "title": title or "New Conversation",
        "model": model,
        "created_at": now,
        "updated_at": now,
        "content_id": content_id
    }

    await db.execute(query=query, values=values)
    return conversation_id

async def add_message(db: Database, conversation_id: str, role: str, content: str,
                     function_call: Optional[Dict[str, Any]] = None):
    """Add a message to a conversation"""
    message_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    query = """
    INSERT INTO mo_llm_messages (
        id, conversation_id, role, content, created_at, function_call
    ) VALUES (
        :id, :conversation_id, :role, :content, :created_at, :function_call
    ) RETURNING id
    """

    values = {
        "id": message_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "created_at": now,
        "function_call": json.dumps(function_call) if function_call else None
    }

    await db.execute(query=query, values=values)

    # Update conversation timestamp
    update_query = """
    UPDATE mo_llm_conversations 
    SET updated_at = :updated_at 
    WHERE id = :conversation_id
    """

    await db.execute(
        query=update_query,
        values={"conversation_id": conversation_id, "updated_at": now}
    )

    return message_id

async def store_function_call(db: Database, message_id: str, function_name: str,
                            arguments: Dict[str, Any], result: Optional[Dict[str, Any]] = None):
    """Store a function call and result"""
    function_call_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    query = """
    INSERT INTO mo_llm_function_calls (
        id, message_id, function_name, arguments, result, status, created_at, completed_at
    ) VALUES (
        :id, :message_id, :function_name, :arguments, :result, :status, :created_at, :completed_at
    ) RETURNING id
    """

    values = {
        "id": function_call_id,
        "message_id": message_id,
        "function_name": function_name,
        "arguments": json.dumps(arguments),
        "result": json.dumps(result) if result else None,
        "status": "completed" if result else "pending",
        "created_at": now,
        "completed_at": now if result else None
    }

    await db.execute(query=query, values=values)
    return function_call_id

async def prepare_conversation_messages(db: Database, conversation_id: str,
system_prompt: Optional[str] = None):
    """Prepare messages for a conversation to send to Grok"""
    messages = await db.fetch_all(
    query="SELECT role, content, function_call FROM mo_llm_messages WHERE conversation_id = :conversation_id ORDER BY created_at",
    values={"conversation_id": conversation_id}
    )

    formatted_messages = []

    # Add system prompt if provided
    if system_prompt:
        formatted_messages.append({
            "role": "system", 
            "content": system_prompt
        })
    else:
        formatted_messages.append({
            "role": "system", 
            "content": DEFAULT_SYSTEM_PROMPT
        })

    # Process each message
    for msg in messages:
        message_dict = {
            "role": msg["role"],
            "content": msg["content"] or ""
        }
        
        # Add function call if present
        if msg["function_call"]:
            function_call = json.loads(msg["function_call"])
            message_dict["function_call"] = function_call
        
        formatted_messages.append(message_dict)

    return formatted_messages

async def process_function_call(db: Database, conversation_id: str, function_call_data: Dict[str, Any]):
    """Process a function call from Grok"""
    function_name = function_call_data.get("name", "")
    arguments_str = function_call_data.get("arguments", "{}")

    try:
        arguments = json.loads(arguments_str)
    except json.JSONDecodeError:
        arguments = {}

    # Store function call message
    message_id = await add_message(
        db=db,
        conversation_id=conversation_id,
        role="assistant",
        content="",  # Empty content for function call messages
        function_call={"name": function_name, "arguments": arguments}
    )

    # Execute the function
    result = await function_registry.execute(function_name, arguments)

    # Store function result
    await store_function_call(
        db=db,
        message_id=message_id,
        function_name=function_name,
        arguments=arguments,
        result=result
    )

    # Add function result as a message
    await add_message(
        db=db,
        conversation_id=conversation_id,
        role="function",
        content=json.dumps(result),
        function_call=None
    )

    return {
        "message_id": message_id,
        "function_name": function_name,
        "arguments": arguments,
        "result": result
    }

async def stream_chat_response(db: Database, conversation_id: str, user_id: str,
request: ChatRequest, grok_client: GrokClient):
    """Generate streaming response from Grok"""
    # Get conversation and verify it belongs to user
    await get_conversation(db, conversation_id, user_id)
    # Get conversation history
    conversation_messages = await prepare_conversation_messages(
        db=db, 
        conversation_id=conversation_id,
        system_prompt=request.system_prompt
    )

    # Prepare function definitions if needed
    function_definitions = None
    if request.functions:
        function_definitions = function_registry.get_functions(request.functions)

    # Initialize response tracking
    full_response = ""
    current_function_call = None

    # Stream response from Grok
    async for chunk in grok_client.stream_completion(
        messages=conversation_messages,
        model=request.model,
        functions=function_definitions,
        temperature=request.temperature,
        max_tokens=request.max_tokens
    ):
        yield chunk
        
        # Extract content for storing later
        if chunk.startswith('data: '):
            try:
                data = json.loads(chunk[6:])
                if 'v' in data:
                    full_response += data['v']
            except Exception:
                pass

    # Store the complete response if we have content
    if full_response:
        await add_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content=full_response
        )

    # Add final marker
    yield "data: [DONE]\n\n"

async def stream_vision_response(db: Database, conversation_id: str, user_id: str,
request: VisionRequest, grok_client: GrokClient):
    """Generate streaming response from Grok for vision requests"""
    # Process vision messages for the API
    vision_messages = []

    # Add system prompt
    if request.system_prompt:
        vision_messages.append({
            "role": "system", 
            "content": request.system_prompt
        })
    else:
        vision_messages.append({
            "role": "system", 
            "content": DEFAULT_SYSTEM_PROMPT
        })

    # Add user messages with images
    for msg in request.messages:
        if msg.role == "user":
            vision_messages.append({
                "role": msg.role,
                "content": msg.content
            })

    # Initialize Grok client with API key
    if not GROK_API_KEY:
        raise HTTPException(status_code=500, detail="Grok API key not configured")

    # Create payload for vision request
    payload = {
        "model": request.model,
        "messages": vision_messages,
        "max_tokens": request.max_tokens,
        "stream": True
    }

    # Stream the response
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            f"{GROK_API_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload
        ) as response:
            if response.status_code != 200:
                error_content = await response.aread()
                try:
                    error_data = json.loads(error_content)
                    error_message = error_data.get("error", {}).get("message", "Grok API error")
                except:
                    error_message = f"Grok Vision API error: Status {response.status_code}"
                
                logger.error(error_message)
                raise HTTPException(status_code=response.status_code, detail=error_message)
            
            # Stream response chunks
            full_response = ""
            async for chunk in response.aiter_text():
                if chunk.startswith("data: "):
                    data_str = chunk[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    
                    try:
                        data = json.loads(data_str)
                        if "choices" in data and len(data["choices"]) > 0:
                            if "delta" in data["choices"][0] and "content" in data["choices"][0]["delta"]:
                                content = data["choices"][0]["delta"]["content"]
                                full_response += content
                                yield f"data: {json.dumps({'v': content})}\n\n"
                    except json.JSONDecodeError:
                        logger.error(f"Error parsing chunk: {chunk}")
                    except Exception as e:
                        logger.error(f"Error processing chunk: {str(e)}")
            
            # Store the response if we have a conversation_id
            if conversation_id and full_response:
                # If we don't have an exist ing conversation, create one
                if not await db.fetch_one(
                    "SELECT id FROM mo_llm_conversations WHERE id = :id AND user_id = :user_id",
                    {"id": conversation_id, "user_id": user_id}
                ):
                    await create_conversation(
                        db=db,
                        user_id=user_id,
                        model=request.model,
                        title="Vision Conversation"
                    )
                
                # Store the response
                await add_message(
                    db=db,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_response
                )
            
            # Send final marker
            yield "data: [DONE]\n\n"

@router.get("/models")
async def get_models():
    """Get available Grok models"""
    return {
        "models": [
            {"id": "grok-2-1212", "name": "Grok 2", "description": "Advanced language model with general capabilities"},
            {"id": "grok-2-vision-1212", "name": "Grok 2 Vision", "description": "Vision-enhanced model for image understanding"}
        ]
    }

@router.get("/functions")
async def get_available_functions():
    """Get available functions for Grok"""
    functions = function_registry.get_functions()
    return {"functions": functions}

@router.post("/functions/call")
async def call_function(
    request: FunctionCallRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Execute a function call directly"""
    try:
        # Execute the function
        result = await function_registry.execute(request.name, request.arguments)

        # If conversation and message ID are provided, store the function call
        if request.conversation_id and request.message_id:
            await store_function_call(
                db=db,
                message_id=request.message_id,
                function_name=request.name,
                arguments=request.arguments,
                result=result
            )
            
            # Add function message to conversation
            await add_message(
                db=db,
                conversation_id=request.conversation_id,
                role="function",
                content=json.dumps(result)
            )
        
        return {
            "success": True,
            "function_name": request.name,
            "result": result
        }
    except Exception as e:
        logger.error(f"Error calling function: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/conversations")
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    content_id: Optional[str] = None
):
    """List all conversations for a user, optionally filtered by content_id"""
    query_values = {"user_id": current_user["uid"]}

    if content_id:
        query = """
        SELECT
            id, title, model_id as model,
            created_at, updated_at, content_id,
            (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
            (SELECT content FROM mo_llm_messages
            WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
            ORDER BY created_at DESC LIMIT 1) as last_message
        FROM mo_llm_conversations
        WHERE user_id = :user_id AND content_id = :content_id
        ORDER BY updated_at DESC
        """
        query_values["content_id"] = content_id
    else:
        query = """
        SELECT
            id, title, model_id as model,
            created_at, updated_at, content_id,
            (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
            (SELECT content FROM mo_llm_messages
            WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
            ORDER BY created_at DESC LIMIT 1) as last_message
        FROM mo_llm_conversations
        WHERE user_id = :user_id
        ORDER BY updated_at DESC
        """

    conversations = await db.fetch_all(query=query, values=query_values)
    return {"conversations": [dict(conv) for conv in conversations]}

@router.get("/conversations/{conversation_id}")
async def get_conversation_details(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get details of a specific conversation"""
    conversation = await get_conversation(db, conversation_id, current_user["uid"])
    messages = await get_conversation_messages(db, conversation_id, current_user["uid"])

    return {
        "conversation": conversation,
        "messages": messages
    }

@router.post("/conversations")
async def create_new_conversation(
    request: ConversationRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Create a new conversation"""
    conversation_id = await create_conversation(
        db=db,
        user_id=current_user["uid"],
        model=DEFAULT_GROK_MODEL,
        title=request.title
    )

    conversation = await get_conversation(db, conversation_id, current_user["uid"])
    return conversation

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Delete a conversation"""
    # First verify the conversation belongs to the user
    conversation = await get_conversation(db, conversation_id, current_user["uid"])

    # Delete the conversation
    await db.execute(
        "DELETE FROM mo_llm_conversations WHERE id = :id",
        {"id": conversation_id}
    )

    return {"success": True, "message": "Conversation deleted"}

@router.post("/chat")
async def chat_completion(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Send a message and get a response from Grok"""
    # Initialize Grok client
    if not GROK_API_KEY:
        raise HTTPException(status_code=500, detail="Grok API key not configured")

    grok_client = GrokClient(GROK_API_KEY)

    # Get or create conversation
    conversation_id = request.conversation_id
    if not conversation_id:
        # Create a new conversation
        conversation_id = await create_conversation(
            db=db,
            user_id=current_user["uid"],
            model=request.model,
            title=None,  # We'll update this later based on first message
            content_id=request.content_id
        )
    else:
        # Verify conversation exists and belongs to user
        await get_conversation(db, conversation_id, current_user["uid"])

    # Add user message to conversation
    await add_message(
        db=db,
        conversation_id=conversation_id,
        role="user",
        content=request.message
    )

    # Update conversation title if it's new
    if not request.conversation_id:
        # Use first few words of message as title
        title_words = request.message.split()[:5]
        title = " ".join(title_words) + "..."
        
        await db.execute(
            "UPDATE mo_llm_conversations SET title = :title WHERE id = :id",
            {"id": conversation_id, "title": title}
        )
    
    # If streaming is requested, return a streaming response
    if request.stream:
        return StreamingResponse(
            stream_chat_response(
                db=db,
                conversation_id=conversation_id,
                user_id=current_user["uid"],
                request=request,
                grok_client=grok_client
            ),
            media_type="text/event-stream"
        )
    else:
        # For non-streaming responses, get complete response
        conversation_messages = await prepare_conversation_messages(
            db=db, 
            conversation_id=conversation_id,
            system_prompt=request.system_prompt
        )
        
        # Prepare function definitions if needed
        function_definitions = None
        if request.functions:
            function_definitions = function_registry.get_functions(request.functions)
        
        # Get completion from Grok
        completion = await grok_client.create_completion(
            messages=conversation_messages,
            model=request.model,
            functions=function_definitions,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False
        )
        
        # Extract response
        response_message = completion["choices"][0]["message"]
        content = response_message.get("content", "")
        
        # Check for function call
        function_call = None
        if "function_call" in response_message:
            function_call = response_message["function_call"]
            
            # Process function call
            function_result = await process_function_call(
                db=db,
                conversation_id=conversation_id,
                function_call_data=function_call
            )
            
            # Get a new completion with the function result
            conversation_messages = await prepare_conversation_messages(
                db=db, 
                conversation_id=conversation_id,
                system_prompt=request.system_prompt
            )
            
            completion = await grok_client.create_completion(
                messages=conversation_messages,
                model=request.model,
                functions=function_definitions,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=False
            )
            
            # Extract final response
            response_message = completion["choices"][0]["message"]
            content = response_message.get("content", "")
        
        # Store assistant response
        message_id = await add_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            function_call=function_call
        )
        
        # Return response
        return {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "content": content,
            "function_call": function_call
        }


@router.post("/chat/stream")
async def stream_chat_get(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Stream a chat response via GET for EventSource compatibility"""
    # Create a ChatRequest object from query parameters
    request = ChatRequest(
        conversation_id=request.conversation_id,
        message=request.message,
        model=request.model,
        system_prompt=request.system_prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=True,
        functions=request.functions
    )

    # Initialize Grok client
    if not GROK_API_KEY:
        raise HTTPException(
            status_code=500, detail="Grok API key not configured")

    grok_client = GrokClient(GROK_API_KEY)

    # Get or create conversation
    conv_id = request.conversation_id
    if not conv_id:
        # Create a new conversation
        conv_id = await create_conversation(
            db=db,
            user_id=current_user["uid"],
            model=request.model,
            title=None
        )
    else:
        # Verify conversation exists and belongs to user
        await get_conversation(db, conv_id, current_user["uid"])

    # Add user message to conversation
    await add_message(
        db=db,
        conversation_id=conv_id,
        role="user",
        content=request.message
    )

    # Update conversation title if it's new
    if not request.conversation_id:
        # Use first few words of message as title
        title_words = request.message.split()[:5]
        title = " ".join(title_words) + "..."

        await db.execute(
            "UPDATE mo_llm_conversations SET title = :title WHERE id = :id",
            {"id": conv_id, "title": title}
        )

    # Return streaming response
    return StreamingResponse(
        stream_chat_response(
            db=db,
            conversation_id=conv_id,
            user_id=current_user["uid"],
            request=request,
            grok_client=grok_client
        ),
        media_type="text/event-stream"
    )

@router.post("/chat/vision")
async def vision_chat(
    request: VisionRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Process a vision chat request"""
    # Initialize Grok client
    if not GROK_API_KEY:
        raise HTTPException(status_code=500, detail="Grok API key not configured")
    
    # Get or create conversation if needed
    conversation_id = request.conversation_id
    if conversation_id:
        # Verify conversation exists and belongs to user
        await get_conversation(db, conversation_id, current_user["uid"])
    else:
        # We'll create the conversation only if needed (in the stream function)
        conversation_id = str(uuid.uuid4())
    
    # Store the user's vision message if there's a conversation ID
    if conversation_id and request.conversation_id:
        # We only store text content for now
        for msg in request.messages:
            if msg.role == "user":
                content = ""
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    # Extract text content from the list
                    text_parts = []
                    for item in msg.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    content = " ".join(text_parts)
                
                if content:
                    await add_message(
                        db=db,
                        conversation_id=conversation_id,
                        role="user",
                        content=content
                    )
    
    # Return streaming response if requested
    if request.stream:
        return StreamingResponse(
            stream_vision_response(
                db=db,
                conversation_id=conversation_id,
                user_id=current_user["uid"],
                request=request,
                grok_client=GrokClient(GROK_API_KEY)
            ),
            media_type="text/event-stream"
        )
    else:
        # For non-streaming responses, directly call Grok Vision API
        # Process vision messages for the API
        vision_messages = []
        
        # Add system prompt
        if request.system_prompt:
            vision_messages.append({
                "role": "system", 
                "content": request.system_prompt
            })
        else:
            vision_messages.append({
                "role": "system", 
                "content": DEFAULT_SYSTEM_PROMPT
            })
        
        # Add user messages with images
        for msg in request.messages:
            if msg.role == "user":
                vision_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Call Grok API
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{GROK_API_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": request.model,
                    "messages": vision_messages,
                    "max_tokens": request.max_tokens
                }
            )
            
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Grok Vision API error: {error_data}")
                raise HTTPException(
                    status_code=response.status_code, 
                    detail=error_data.get("error", {}).get("message", "Grok Vision API error")
                )
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Store the response if there's a conversation ID
            if conversation_id and request.conversation_id:
                await add_message(
                    db=db,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=content
                )
            
            return {"response": content}

# Legacy endpoints for backward compatibility
@router.post("/chat/stream-legacy")
async def stream_chat_legacy(request: dict):
    """Legacy endpoint for streaming chat"""
    try:
        messages = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            *[{"role": m["role"], "content": m["content"]} for m in request.get("messages", [])]
        ]

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{GROK_API_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "grok-2-1212",
                    "messages": messages,
                    "stream": True
                }
            ) as response:
                def generate():
                    buffer = b""
                    for chunk in response.iter_bytes():
                        buffer += chunk
                        if b"data: " in buffer:
                            parts = buffer.split(b"data: ")
                            # Process all complete parts except the last one
                            for part in parts[:-1]:
                                if part.strip():
                                    try:
                                        data = json.loads(part)
                                        if "choices" in data and data["choices"][0].get("delta", {}).get("content"):
                                            content = data["choices"][0]["delta"]["content"]
                                            yield f"data: {json.dumps({'v': content})}\n\n".encode()
                                    except json.JSONDecodeError:
                                        pass
                            
                            # Keep the last part (which might be incomplete)
                            buffer = b"data: " + parts[-1]
                    
                    # Final data marker
                    yield b"data: [DONE]\n\n"

                return StreamingResponse(
                    generate(),
                    media_type="text/event-stream"
                )

    except Exception as e:
        logger.error(f"Error in stream_chat_legacy: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/content/{content_id}/conversation")
async def get_content_conversation(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get or create a conversation for a content item"""
    # Check if content exists and belongs to user
    content_query = """
    SELECT uuid FROM mo_content 
    WHERE uuid = :content_id AND firebase_uid = :user_id
    """
    content = await db.fetch_one(
        query=content_query,
        values={"content_id": content_id, "user_id": current_user["uid"]}
    )
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    # Try to find an existing conversation for this content
    conversation_query = """
    SELECT 
        id, title, model_id as model,
        created_at, updated_at, 
        content_id,
        (SELECT COUNT(*) FROM mo_llm_messages WHERE conversation_id = mo_llm_conversations.id) as message_count,
        (SELECT content FROM mo_llm_messages 
        WHERE conversation_id = mo_llm_conversations.id AND role = 'user'
        ORDER BY created_at DESC LIMIT 1) as last_message
    FROM mo_llm_conversations
    WHERE content_id = :content_id AND user_id = :user_id
    ORDER BY updated_at DESC
    LIMIT 1
    """
    conversation = await db.fetch_one(
        query=conversation_query,
        values={"content_id": content_id, "user_id": current_user["uid"]}
    )

    if conversation:
        # Return existing conversation
        conversation_data = dict(conversation)

        # Get messages for the conversation
        messages_query = """
        SELECT id, role, content, created_at, function_call
        FROM mo_llm_messages
        WHERE conversation_id = :conversation_id
        ORDER BY created_at
        """
        messages = await db.fetch_all(
            query=messages_query,
            values={"conversation_id": conversation_data["id"]}
        )

        return {
            "conversation": conversation_data,
            "messages": [dict(msg) for msg in messages]
        }
    else:
        # Create new conversation for this content
        conversation_id = await create_conversation(
            db=db,
            user_id=current_user["uid"],
            model=DEFAULT_GROK_MODEL,
            title=f"Content Chat",
            content_id=content_id
        )

        # Get the new conversation
        new_conversation = await get_conversation(db, conversation_id, current_user["uid"])

        return {
            "conversation": new_conversation,
            "messages": []
        }
