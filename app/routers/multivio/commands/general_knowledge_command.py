"""
General knowledge command implementation for the pipeline pattern.
This serves as the fallback command to process queries with general knowledge.
"""
from .base import Command, CommandFactory
from typing import Dict, Any, AsyncGenerator
import logging
import re
import json
from datetime import datetime, timezone
import uuid
import httpx
import os
import asyncio
from openai import OpenAI

logger = logging.getLogger(__name__)

# Load environment variables
GROK_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# Default model to use
DEFAULT_MODEL = "grok-3-mini-beta"

# Default system prompt for general knowledge
DEFAULT_SYSTEM_PROMPT = """
# SYSTEM PROMPT - Multivio General Assistant V1.1.0

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

        logger.info(
            f"GeneralKnowledgeCommand executing with message: '{message}'")

        if not GROK_API_KEY:
            error_msg = "GROK_API_KEY not configured, cannot generate general knowledge response"
            logger.error(error_msg)
            context["errors"] = context.get(
                "errors", []) + [{"command": self.name, "error": error_msg}]
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
                        logger.info(
                            f"Added content context to prompt: Content name '{content_name}'")
                    else:
                        logger.warning(
                            f"Content with ID {content_id} not found in database")
                except Exception as e:
                    logger.error(f"Error fetching content info: {str(e)}")

            # Add all system prompts from other commands
            if "system_prompts" in context and context["system_prompts"]:
                for prompt_data in context["system_prompts"]:
                    system_prompt += f"\n\n{prompt_data['content']}"

            # Initialize OpenAI client
            client = OpenAI(
                api_key=GROK_API_KEY,
                base_url=GROK_API_BASE_URL
            )

            # Prepare messages
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]

            # Prepare parameters for the API call
            params = {
                "model": context.get("model", DEFAULT_MODEL),
                "messages": messages,
                "temperature": context.get("temperature", 0.7),
                "max_tokens": context.get("max_tokens", 2048),
                "stream": True  # Enable streaming for chunked responses
            }

            # Add reasoning_effort for grok-3 models if specified in context
            model = params["model"]
            if model.startswith("grok-3"):
                reasoning_effort = context.get("reasoning_effort", "high")
                params["reasoning_effort"] = reasoning_effort
                logger.info(
                    f"Using reasoning_effort={reasoning_effort} for {model}")

            # Set up streaming generator
            context["_streaming_generator"] = self._stream_response(
                client=client,
                params=params,
                context=context
            )

            # Initialize empty content and reasoning
            context["general_knowledge_content"] = ""
            context["reasoning_content"] = ""

            # Add an empty result to the results collection
            # This will be updated by the streaming process
            context["results"].append({
                "type": "general_knowledge",
                "content": ""
            })

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

    async def _stream_response(self, client, params, context) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream the API response chunks as they arrive.
        This is an async generator that yields chunks as they come in.
        """
        try:
            # Call the API with streaming enabled
            logger.info(
                f"__stream__shit Calling {params['model']} API for general knowledge with streaming")
            stream = client.chat.completions.create(**params)

            # Initialize collector variables
            content_collector = ""
            reasoning_collector = ""
            chunk_count = 0

            # Stream each chunk as it arrives
            for chunk in stream:
                chunk_count += 1

                # Handle content chunks
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content is not None:
                    content_chunk = chunk.choices[0].delta.content
                    content_collector += content_chunk

                    # Update the context with the current accumulated content
                    context["general_knowledge_content"] = content_collector

                    # Update the result in the results collection
                    for result in context["results"]:
                        if result["type"] == "general_knowledge":
                            result["content"] = content_collector

                    # Log occasionally or for larger chunks
                    if chunk_count % 100 == 0 or len(content_chunk) > 20:
                        logger.info(
                            f"__stream__shit Received content chunk #{chunk_count}: '{content_chunk[:20]}...'")

                    # Yield the chunk for streaming to client
                    yield {
                        "type": "content",
                        "content": content_chunk,
                        "chunk_number": chunk_count
                    }

                    # Small delay to control streaming pace
                    await asyncio.sleep(0.01)

                # Handle reasoning content chunks
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content is not None:
                    reasoning_chunk = chunk.choices[0].delta.reasoning_content
                    reasoning_collector += reasoning_chunk

                    # Update the context with the current accumulated reasoning
                    context["reasoning_content"] = reasoning_collector
                    # Log occasionally or for larger chunks
                    if chunk_count % 100 == 0 or len(reasoning_chunk) > 20:
                        logger.info(
                            f"__stream__shit Received reasoning chunk: '{reasoning_chunk[:20]}...'")

                    # Also yield reasoning chunks, but with a different type
                    yield {
                        "type": "reasoning",
                        "content": reasoning_chunk,
                        "chunk_number": chunk_count
                    }

                    # Small delay to control streaming pace
                    await asyncio.sleep(0.01)

            # Log completion
            logger.info(
                f"__stream__shit Streaming complete. Received {chunk_count} chunks, content length: {len(content_collector)}, reasoning length: {len(reasoning_collector)}")

            # If we have no reasoning content from streaming, try a fallback
            if not reasoning_collector:
                try:
                    # Make a non-streaming request to get reasoning content
                    nonstream_params = params.copy()
                    # Explicitly disable streaming
                    nonstream_params["stream"] = False

                    # Make a separate non-streaming call just to get reasoning content
                    logger.info(
                        f"__stream__shit No reasoning from stream, making separate call to get reasoning content")
                    completion = client.chat.completions.create(
                        **nonstream_params)

                    # Try to extract reasoning content
                    if hasattr(completion.choices[0].message, 'reasoning_content'):
                        reasoning = completion.choices[0].message.reasoning_content
                        logger.info(
                            f"__stream__shit Successfully extracted reasoning content from non-streaming call ({len(reasoning)} chars)")
                        context["reasoning_content"] = reasoning

                        # Also yield the reasoning content
                        yield {
                            "type": "reasoning",
                            "content": reasoning,
                            "chunk_number": -1,  # Special marker for fallback reasoning
                            "fallback": True
                        }
                    else:
                        logger.warning(
                            f"__stream__shit Fallback call didn't return reasoning content either")
                except Exception as fallback_error:
                    logger.error(
                        f"Error in fallback reasoning content extraction: {str(fallback_error)}")
                    # Continue without reasoning content

            # Store in database if conversation_id is provided
            conversation_id = context.get("conversation_id")
            db = context.get("db")
            if conversation_id and db:
                message_id = context.get("message_id", str(uuid.uuid4()))
                now = datetime.now(timezone.utc)

                # Create metadata with reasoning content if available
                metadata = {
                    "type": "general_knowledge",
                    "multi_intent": len(context.get("results", [])) > 1
                }

                # Include reasoning content in metadata if available
                if reasoning_collector:
                    metadata["reasoning_content"] = reasoning_collector

                # Check if we need to create a new message or update an existing one
                check_query = """
                SELECT id FROM mo_llm_messages
                WHERE conversation_id = :conversation_id
                AND created_at > now() - interval '30 seconds'
                AND role = 'assistant'
                ORDER BY created_at DESC
                LIMIT 1
                """

                existing_message = await db.fetch_one(
                    query=check_query,
                    values={"conversation_id": conversation_id}
                )

                if existing_message:
                    # Update existing message
                    message_id = existing_message["id"]
                    await db.execute(
                        """
                        UPDATE mo_llm_messages
                        SET content = :content, metadata = :metadata
                        WHERE id = :id
                        """,
                        {
                            "id": message_id,
                            "content": content_collector,
                            "metadata": json.dumps(metadata)
                        }
                    )
                    logger.info(
                        f"Updated existing message {message_id} with complete content")
                else:
                    # Create new message
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
                            "content": content_collector,
                            "created_at": now,
                            "metadata": json.dumps(metadata)
                        }
                    )
                    logger.info(
                        f"Created new message {message_id} with complete content")

                # Store message_id in context
                context["message_id"] = message_id

                # Signal completion with a special marker
                yield {
                    "type": "completion",
                    "content_length": len(content_collector),
                    "reasoning_length": len(reasoning_collector),
                    "message_id": message_id
                }

        except Exception as e:
            logger.error(f"Error in _stream_response: {str(e)}")
            # Yield error information
            yield {
                "type": "error",
                "error": str(e)
            }
