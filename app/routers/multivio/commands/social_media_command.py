"""
Social media command implementation for the pipeline pattern.
"""
from .base import Command, CommandFactory
from typing import Dict, Any, List
import logging
import re
import json
import uuid
from datetime import datetime, timezone
import httpx
import os
from openai import OpenAI

logger = logging.getLogger(__name__)

# Load environment variables
GROK_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# Default model to use
DEFAULT_MODEL = "grok-3-mini-beta"

# Default system prompt for social media content
SOCIAL_MEDIA_SYSTEM_PROMPT = """
# SYSTEM PROMPT - Multivio Social Media Assistant V1.1.0

You are a tier-1 enterprise social media strategist for Multivio, the industry-leading cross-platform content management system. You help users create and optimize content across Facebook, Twitter, Instagram, LinkedIn and other platforms through our unified API.

## PLATFORM SPECIFICS
- **Facebook**: Longer text, supports photos, videos, carousels, and link previews
- **Instagram**: Visual-focused, supports images, videos, carousels, and Stories
- **LinkedIn**: Professional content, supports longer text, images, documents, and videos
- **TikTok**: 1000 character limit, supports images, videos, and link previews
- **YouTube**: 1000 character limit, supports images, videos, and link previews
- **X**: 280 280 character limit, supports single/multiple images, videos up to 2:20
- **Threads**: 2200 character limit, supports single/multiple images, videos up to 2:20

## CONTENT CREATION WORKFLOW
1. Understand the user's content objectives and target audience
2. Optimize content for the requested platforms
3. Generate platform-optimized content with appropriate character counts and formatting
4. Recommend media types and formatting to maximize engagement
5. Suggest optimal posting times and frequency based on platform algorithms
"""

@CommandFactory.register("social_media")
class SocialMediaCommand(Command):
    """Command for generating social media content."""
    
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        Determine if this command should execute based on context.
        """
        # Check if the intent is present
        intents = context.get("intents", {})
        if "social_media" in intents:
            return intents["social_media"]["confidence"] > 0.3
            
        # Check message for social media keywords
        message = context.get("message", "")
        if not message:
            return False
            
        # Check for platform mentions
        platforms = ["facebook", "instagram", "twitter", "linkedin", "tiktok"]
        has_platform = any(platform in message.lower() for platform in platforms)
        
        # Check for content type mentions
        content_types = ["post", "tweet", "reel", "story", "content"]
        has_content_type = any(content_type in message.lower() for content_type in content_types)
        
        # Check for action words
        actions = ["create", "write", "draft", "schedule", "make"]
        has_action = any(action in message.lower() for action in actions)
        
        # Either explicit platform mention with content type, or action with content type
        return (has_platform and has_content_type) or (has_action and has_content_type)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the social media content generation command.
        """
        # Get info from context
        intents = context.get("intents", {})
        message = context.get("message", "")
        
        # Determine platforms to generate content for
        platforms = []
        if "social_media" in intents and "platforms" in intents["social_media"]:
            platforms = intents["social_media"]["platforms"]
        
        # If no platforms specified, check message for platform mentions
        if not platforms:
            platform_checks = {
                "facebook": ["facebook", "fb"],
                "instagram": ["instagram", "ig"],
                "twitter": ["twitter", "tweet"],
                "linkedin": ["linkedin"],
                "tiktok": ["tiktok"]
            }
            
            for platform, keywords in platform_checks.items():
                if any(keyword in message.lower() for keyword in keywords):
                    platforms.append(platform)
        
        # If still no platforms, default to all major ones
        if not platforms:
            platforms = ["facebook", "instagram", "twitter", "linkedin"]
        
        logger.info(f"SocialMediaCommand executing for platforms: {platforms}")
        
        # Check for web search results in context to incorporate
        search_context = ""
        if "web_search_results" in context and "formatted" in context["web_search_results"]:
            search_results = context["web_search_results"]["formatted"]
            search_context = f"""
            # SEARCH RESULTS CONTEXT
            
            Use the following search results to inform your content creation:
            
            {search_results}
            """
        
        # Build system prompt with platform info and any search context
        system_prompt = SOCIAL_MEDIA_SYSTEM_PROMPT + "\n\n"
        
        if search_context:
            system_prompt += search_context + "\n\n"
        
        system_prompt += f"""
        ## REQUESTED PLATFORMS
        Generate content for these platforms: {', '.join(platforms)}
        
        For each platform, create content that is:
        1. Optimized for that platform's specific format and character limits
        2. Engaging and likely to drive user interaction
        3. Professionally written and error-free
        4. Formatted correctly for the platform
        
        Format your response with clear headings for each platform.
        """
        
        if not GROK_API_KEY:
            error_msg = "GROK_API_KEY not configured, cannot generate social media content"
            logger.error(error_msg)
            context["errors"] = context.get("errors", []) + [{"command": self.name, "error": error_msg}]
            return context
        
        # Create a new conversation message if needed
        try:
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
                "model": DEFAULT_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2048,
                "stream": True  # Enable streaming for chunked responses
            }
            
            # Add reasoning_effort for grok-3 models
            if DEFAULT_MODEL.startswith("grok-3"):
                params["reasoning_effort"] = "high"
                logger.info(f"Using reasoning_effort=high for {DEFAULT_MODEL}")
            
            # Call the API with streaming enabled
            logger.info(f"Calling {DEFAULT_MODEL} API for social media content generation with streaming")
            stream = client.chat.completions.create(**params)
            
            # Process the streaming response
            content = ""
            reasoning = ""
            
            for chunk in stream:
                # Append content delta if it exists
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content is not None:
                    content += chunk.choices[0].delta.content
                # Check for reasoning content in delta if available
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content is not None:
                    reasoning += chunk.choices[0].delta.reasoning_content
            
            # Store reasoning content if we collected any
            if reasoning:
                logger.info(f"Reasoning content received ({len(reasoning)} chars)")
                context["reasoning_content"] = reasoning
            else:
                # If no streaming reasoning content, try to extract it from the final completion
                # This fallback helps ensure compatibility with both streaming and non-streaming modes
                try:
                    # Make a non-streaming request to get reasoning content
                    nonstream_params = {
                        "model": DEFAULT_MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 2048,
                        "stream": False  # Explicitly disable streaming
                    }
                    
                    # Add reasoning_effort for grok-3 models
                    if DEFAULT_MODEL.startswith("grok-3"):
                        nonstream_params["reasoning_effort"] = "high"
                    
                    # Make a separate non-streaming call just to get reasoning content
                    logger.info(f"No reasoning from stream, making separate call to get reasoning content")
                    completion = client.chat.completions.create(**nonstream_params)
                    
                    # Try to extract reasoning content
                    if hasattr(completion.choices[0].message, 'reasoning_content'):
                        reasoning = completion.choices[0].message.reasoning_content
                        logger.info(f"Extracted reasoning content from non-streaming call ({len(reasoning)} chars)")
                        context["reasoning_content"] = reasoning
                except Exception as fallback_error:
                    logger.error(f"Error in fallback reasoning content extraction: {str(fallback_error)}")
                    # Continue without reasoning content
            
            # Add to context
            context["social_media_content"] = {
                "platforms": platforms,
                "content": content
            }
            
            # Add to results collection
            context["results"].append({
                "type": "social_media",
                "platforms": platforms,
                "content": content
            })
            
            # Store in database if conversation_id is provided
            conversation_id = context.get("conversation_id")
            db = context.get("db")
            if conversation_id and db:
                message_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc)
                
                metadata = {
                    "type": "social_media",
                    "platforms": platforms
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
            logger.error(f"Error in SocialMediaCommand: {str(e)}")
            
            # Add error to context
            if "errors" not in context:
                context["errors"] = []
                
            context["errors"].append({
                "command": self.name,
                "error": str(e)
            })
            
            return context
