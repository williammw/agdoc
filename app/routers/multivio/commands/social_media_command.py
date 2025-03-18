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

logger = logging.getLogger(__name__)

# Load environment variables
GROK_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# Default system prompt for social media content
SOCIAL_MEDIA_SYSTEM_PROMPT = """
# SYSTEM PROMPT - Multivio Social Media Assistant

You are a tier-1 enterprise social media strategist for Multivio, the industry-leading cross-platform content management system. You help users create and optimize content across Facebook, Twitter, Instagram, LinkedIn and other platforms through our unified API.

## PLATFORM SPECIFICS
- **Twitter**: 280 character limit, supports single/multiple images, videos up to 2:20
- **Facebook**: Longer text, supports photos, videos, carousels, and link previews
- **Instagram**: Visual-focused, supports images, videos, carousels, and Stories
- **LinkedIn**: Professional content, supports longer text, images, documents, and videos

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
            # Prepare request data
            request_data = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "model": "grok-2-1212",
                "temperature": 0.7,
                "max_tokens": 2048
            }
            
            # Call Grok API to generate content
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
                    raise Exception(f"Failed to generate social media content: {error_message}")
                
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
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
