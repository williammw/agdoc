"""
General knowledge command implementation for the pipeline pattern.
This serves as the fallback command to process queries with general knowledge.
"""
from .base import Command, CommandFactory
from typing import Dict, Any
import logging
import re
import json
from datetime import datetime, timezone
import uuid
import httpx
import os

logger = logging.getLogger(__name__)

# Load environment variables
GROK_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# Default system prompt for general knowledge
DEFAULT_SYSTEM_PROMPT = """
# SYSTEM PROMPT - Multivio General Assistant

You are a helpful, knowledgeable assistant for Multivio users. You can help with a wide range of topics including programming, research, writing, data analysis, and general knowledge questions.

## CAPABILITIES
- Answering factual questions
- Providing detailed explanations
- Assisting with coding and technical problems 
- Writing and content creation (except social media)
- Data analysis and interpretation
- Learning and educational assistance

## RESPONSE PRINCIPLES
1. Be accurate, helpful, and concise
2. When unsure, acknowledge limitations
3. Provide complete, well-structured answers
4. Stay focused on the user's actual question
5. Use examples when they help clarify concepts
"""

@CommandFactory.register("general_knowledge")
class GeneralKnowledgeCommand(Command):
    """Command for general knowledge responses. Acts as a fallback."""
    
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        This command always returns True as it's the fallback.
        It processes any query with general knowledge if no other
        command has provided a full response.
        """
        return True
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the general knowledge command.
        """
        message = context.get("message", "")
        
        logger.info(f"GeneralKnowledgeCommand executing with message: '{message}'")
        
        if not GROK_API_KEY:
            error_msg = "GROK_API_KEY not configured, cannot generate general knowledge response"
            logger.error(error_msg)
            context["errors"] = context.get("errors", []) + [{"command": self.name, "error": error_msg}]
            return context
        
        try:
            # Build the final system prompt combining results from other commands
            system_prompt = DEFAULT_SYSTEM_PROMPT
            
            # Add content information if available
            content_id = context.get("content_id")
            db = context.get("db")
            if content_id and db:
                try:
                    # Query to get content name by content_id
                    query = "SELECT name, description FROM mo_content WHERE uuid = :content_id"
                    content_info = await db.fetch_one(query=query, values={"content_id": content_id})
                    
                    if content_info:
                        content_name = content_info["name"]
                        content_description = content_info["description"] or ""
                        
                        # Add content context to the system prompt
                        content_prompt = f"""
## CONTENT CONTEXT
The user is working on content titled: "{content_name}"
{f'Description: {content_description}' if content_description else ''}

Keep this content topic in mind when responding to their question.
"""
                        system_prompt += "\n\n" + content_prompt
                        logger.info(f"Added content context to prompt: Content name '{content_name}'")
                    else:
                        logger.warning(f"Content with ID {content_id} not found in database")
                except Exception as e:
                    logger.error(f"Error fetching content info: {str(e)}")
            
            # Add all system prompts from other commands
            if "system_prompts" in context and context["system_prompts"]:
                for prompt_data in context["system_prompts"]:
                    system_prompt += f"\n\n{prompt_data['content']}"
            
            # Prepare the request
            request_data = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "model": "grok-2-1212",
                "temperature": 0.7,
                "max_tokens": 2048
            }
            
            # Call the API
            headers = {
                "x-api-key": GROK_API_KEY,
                "Content-Type": "application/json"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{GROK_API_BASE_URL}/chat/completions",
                    headers=headers,
                    json=request_data,
                    timeout=60.0
                )
                
                if response.status_code != 200:
                    error_data = response.json() if response.content else {"error": "Unknown error"}
                    error_message = error_data.get("error", {}).get("message", "API call failed")
                    logger.error(f"Grok API error: {error_message}")
                    raise Exception(f"Failed to generate response: {error_message}")
                
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # Add to context
                context["general_knowledge_content"] = content
                
                # Add to results collection
                context["results"].append({
                    "type": "general_knowledge",
                    "content": content
                })
                
                # Store in database if conversation_id is provided
                conversation_id = context.get("conversation_id")
                db = context.get("db")
                if conversation_id and db:
                    message_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc)
                    
                    metadata = {
                        "type": "general_knowledge",
                        "multi_intent": len(context.get("results", [])) > 1
                    }
                    
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
                            "content": content,
                            "created_at": now,
                            "metadata": json.dumps(metadata)
                        }
                    )
                
                return context
                
        except Exception as e:
            logger.error(f"Error in GeneralKnowledgeCommand: {str(e)}")
            
            # Add error to context
            if "errors" not in context:
                context["errors"] = []
                
            context["errors"].append({
                "command": self.name,
                "error": str(e)
            })
            
            return context
