import os
import json
import time
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, Optional, List
from datetime import datetime

import httpx
from fastapi import HTTPException

from app.models.ai import (
    AITransformRequest, 
    AIGenerateRequest,
    AITransformResponse,
    AIGenerateResponse,
    AIStreamChunk,
    AIContentSuggestion,
    GrokModel,
    ContentTransformationType,
    PlatformType,
    ContentTone,
    GrokMessage,
    GrokRequest
)

logger = logging.getLogger(__name__)


class GrokAPIService:
    """Service for interacting with Grok API"""
    
    def __init__(self):
        self.api_key = os.getenv("GROK_API_KEY")
        self.base_url = "https://api.x.ai/v1"
        self.timeout = 60.0
        
        if not self.api_key:
            logger.warning("GROK_API_KEY not found in environment variables")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Grok API requests"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    async def _make_request(
        self, 
        endpoint: str, 
        data: Dict[str, Any], 
        stream: bool = False
    ) -> httpx.Response:
        """Make HTTP request to Grok API"""
        if not self.api_key:
            raise HTTPException(
                status_code=500,
                detail="Grok API key not configured"
            )
        
        url = f"{self.base_url}/{endpoint}"
        headers = self._get_headers()
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                if stream:
                    return await client.stream("POST", url, headers=headers, json=data)
                else:
                    return await client.post(url, headers=headers, json=data)
            except httpx.TimeoutException:
                raise HTTPException(
                    status_code=504,
                    detail="Request to Grok API timed out"
                )
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Error connecting to Grok API: {str(e)}"
                )
    
    def _get_platform_specific_prompt(
        self, 
        platform: Optional[PlatformType], 
        base_prompt: str
    ) -> str:
        """Get platform-specific optimization instructions"""
        if not platform:
            return base_prompt
        
        platform_guidelines = {
            PlatformType.TWITTER: """
Platform: Twitter/X
- Keep content under 280 characters for tweets
- Use engaging hooks in the first line
- Include relevant hashtags (2-3 max)
- Use line breaks for readability
- Consider thread format for longer content
""",
            PlatformType.LINKEDIN: """
Platform: LinkedIn
- Professional tone preferred
- Can be longer form (up to 3000 characters)
- Use industry-relevant keywords
- Include professional insights
- End with engaging questions or calls to action
""",
            PlatformType.FACEBOOK: """
Platform: Facebook
- Conversational and engaging tone
- Moderate length (100-300 words ideal)
- Use emojis sparingly but effectively
- Include calls to action
- Optimize for community engagement
""",
            PlatformType.INSTAGRAM: """
Platform: Instagram
- Visual-first content approach
- Use line breaks and emojis
- Include relevant hashtags (up to 30)
- Engaging captions that complement visuals
- Stories should be casual and authentic
""",
            PlatformType.THREADS: """
Platform: Threads
- Similar to Twitter but can be longer
- Conversational tone
- Good for discussions and replies
- Keep initial posts concise but engaging
""",
            PlatformType.YOUTUBE: """
Platform: YouTube
- Focus on video descriptions and titles
- SEO-optimized keywords
- Include timestamps if applicable
- Clear calls to action (subscribe, like, comment)
- Detailed descriptions help with discovery
""",
            PlatformType.TIKTOK: """
Platform: TikTok
- Short, punchy content
- Trend-aware language
- Include popular hashtags
- Call-to-action for engagement
- Video description should complement the visual content
"""
        }
        
        return f"{base_prompt}\n\n{platform_guidelines.get(platform, '')}"
    
    def _build_transform_prompt(self, request: AITransformRequest) -> List[GrokMessage]:
        """Build prompt for content transformation"""
        system_prompt = "You are an expert content strategist and social media specialist. Transform the given content according to the specified requirements while maintaining the core message and ensuring high engagement potential."
        
        transformation_instructions = {
            ContentTransformationType.PLATFORM_OPTIMIZE: "Optimize this content specifically for the target platform's format, audience, and best practices.",
            ContentTransformationType.TONE_ADJUST: f"Adjust the tone of this content to be more {request.target_tone.value if request.target_tone else 'engaging'}.",
            ContentTransformationType.LENGTH_ADJUST: f"Adjust the length of this content to approximately {request.target_length} characters." if request.target_length else "Adjust the content length as appropriate.",
            ContentTransformationType.HASHTAG_SUGGEST: "Add relevant and trending hashtags to this content.",
            ContentTransformationType.REWRITE: "Completely rewrite this content with the same core message but fresh language and structure.",
            ContentTransformationType.SUMMARIZE: "Create a concise summary of this content while keeping the key points.",
            ContentTransformationType.EXPAND: "Expand this content with additional relevant details, examples, or insights."
        }
        
        user_prompt = f"""
Transform the following content:

Original Content: "{request.content}"

Transformation Type: {transformation_instructions[request.transformation_type]}

Requirements:
- Target Platform: {request.target_platform.value if request.target_platform else 'General'}
- Target Tone: {request.target_tone.value if request.target_tone else 'Appropriate for platform'}
- Target Length: {f'{request.target_length} characters' if request.target_length else 'Optimal for platform'}

Additional Instructions: {request.additional_instructions or 'None'}

Please provide:
1. The transformed content
2. Brief reasoning for the changes made
3. Any additional suggestions for optimization

Format your response as JSON with the following structure:
{{
    "transformed_content": "...",
    "reasoning": "...",
    "suggestions": [
        {{"content": "...", "confidence": 0.9, "reasoning": "..."}}
    ]
}}
"""
        
        user_prompt = self._get_platform_specific_prompt(request.target_platform, user_prompt)
        
        return [
            GrokMessage(role="system", content=system_prompt),
            GrokMessage(role="user", content=user_prompt)
        ]
    
    def _build_generate_prompt(self, request: AIGenerateRequest) -> List[GrokMessage]:
        """Build prompt for content generation"""
        system_prompt = "You are a creative content strategist and social media expert. Generate engaging, original content based on the given requirements. Ensure the content is authentic, valuable, and optimized for engagement."
        
        user_prompt = f"""
Generate content based on the following requirements:

Prompt: "{request.prompt}"
Topic: {request.topic or 'As specified in prompt'}
Target Platform: {request.target_platform.value if request.target_platform else 'General'}
Content Tone: {request.content_tone.value if request.content_tone else 'Appropriate for platform'}
Target Length: {f'{request.target_length} characters' if request.target_length else 'Optimal for platform'}
Include Hashtags: {'Yes' if request.include_hashtags else 'No'}
Include Call to Action: {'Yes' if request.include_call_to_action else 'No'}
Additional Context: {request.context or 'None'}

Please provide:
1. Original, engaging content that fulfills the requirements
2. Reasoning for the creative choices made
3. Alternative suggestions or variations
4. Relevant hashtags (if requested)

Format your response as JSON with the following structure:
{{
    "generated_content": "...",
    "reasoning": "...",
    "hashtags": ["...", "..."],
    "suggestions": [
        {{"content": "...", "confidence": 0.9, "reasoning": "..."}}
    ]
}}
"""
        
        user_prompt = self._get_platform_specific_prompt(request.target_platform, user_prompt)
        
        return [
            GrokMessage(role="system", content=system_prompt),
            GrokMessage(role="user", content=user_prompt)
        ]
    
    def _get_model_config(self, model: GrokModel) -> Dict[str, Any]:
        """Get configuration for specific Grok model"""
        configs = {
            GrokModel.GROK_4: {
                "max_tokens": 4000,
                "temperature": 0.7,
                "top_p": 0.9
            },
            GrokModel.GROK_3_MINI: {
                "max_tokens": 2000,
                "temperature": 0.7,
                "top_p": 0.9
            },
            GrokModel.GROK_BETA: {
                "max_tokens": 3000,
                "temperature": 0.8,
                "top_p": 0.95
            },
            GrokModel.GROK_2: {
                "max_tokens": 3000,
                "temperature": 0.7,
                "top_p": 0.9
            },
            GrokModel.GROK_2_MINI: {
                "max_tokens": 1500,
                "temperature": 0.7,
                "top_p": 0.9
            }
        }
        return configs.get(model, configs[GrokModel.GROK_3_MINI])
    
    def _parse_ai_response(self, response_text: str) -> Dict[str, Any]:
        """Parse AI response and extract structured data"""
        try:
            # Try to find JSON in the response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                return json.loads(json_str)
            else:
                # Fallback: treat entire response as content
                return {
                    "transformed_content": response_text,
                    "generated_content": response_text,
                    "reasoning": "Direct response from AI model",
                    "suggestions": []
                }
        except json.JSONDecodeError:
            # Fallback for malformed JSON
            return {
                "transformed_content": response_text,
                "generated_content": response_text,
                "reasoning": "Could not parse structured response",
                "suggestions": []
            }
    
    def _count_words(self, text: str) -> int:
        """Count words in text"""
        return len(text.split())
    
    async def transform_content(self, request: AITransformRequest) -> AITransformResponse:
        """Transform content using Grok API"""
        start_time = time.time()
        
        try:
            messages = self._build_transform_prompt(request)
            model_config = self._get_model_config(request.model)
            
            grok_request = GrokRequest(
                model=request.model.value,
                messages=messages,
                **model_config,
                stream=False
            )
            
            response = await self._make_request(
                "chat/completions",
                grok_request.dict(),
                stream=False
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Grok API error: {response.text}"
                )
            
            response_data = response.json()
            ai_content = response_data["choices"][0]["message"]["content"]
            parsed_response = self._parse_ai_response(ai_content)
            
            processing_time = time.time() - start_time
            transformed_content = parsed_response.get("transformed_content", ai_content)
            
            suggestions = []
            for suggestion_data in parsed_response.get("suggestions", []):
                suggestions.append(AIContentSuggestion(
                    content=suggestion_data.get("content", ""),
                    confidence=suggestion_data.get("confidence", 0.5),
                    reasoning=suggestion_data.get("reasoning")
                ))
            
            return AITransformResponse(
                original_content=request.content,
                transformed_content=transformed_content,
                transformation_type=request.transformation_type,
                target_platform=request.target_platform,
                target_tone=request.target_tone,
                suggestions=suggestions,
                reasoning=parsed_response.get("reasoning"),
                model_used=request.model,
                processing_time=processing_time,
                character_count=len(transformed_content),
                word_count=self._count_words(transformed_content)
            )
            
        except Exception as e:
            logger.error(f"Error in transform_content: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error transforming content: {str(e)}"
            )
    
    async def generate_content(self, request: AIGenerateRequest) -> AIGenerateResponse:
        """Generate content using Grok API"""
        start_time = time.time()
        
        try:
            messages = self._build_generate_prompt(request)
            model_config = self._get_model_config(request.model)
            
            grok_request = GrokRequest(
                model=request.model.value,
                messages=messages,
                **model_config,
                stream=False
            )
            
            response = await self._make_request(
                "chat/completions",
                grok_request.dict(),
                stream=False
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Grok API error: {response.text}"
                )
            
            response_data = response.json()
            ai_content = response_data["choices"][0]["message"]["content"]
            parsed_response = self._parse_ai_response(ai_content)
            
            processing_time = time.time() - start_time
            generated_content = parsed_response.get("generated_content", ai_content)
            
            suggestions = []
            for suggestion_data in parsed_response.get("suggestions", []):
                suggestions.append(AIContentSuggestion(
                    content=suggestion_data.get("content", ""),
                    confidence=suggestion_data.get("confidence", 0.5),
                    reasoning=suggestion_data.get("reasoning")
                ))
            
            return AIGenerateResponse(
                generated_content=generated_content,
                prompt_used=request.prompt,
                target_platform=request.target_platform,
                content_tone=request.content_tone,
                suggestions=suggestions,
                hashtags=parsed_response.get("hashtags", []),
                reasoning=parsed_response.get("reasoning"),
                model_used=request.model,
                processing_time=processing_time,
                character_count=len(generated_content),
                word_count=self._count_words(generated_content)
            )
            
        except Exception as e:
            logger.error(f"Error in generate_content: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error generating content: {str(e)}"
            )
    
    async def stream_transform_content(
        self, 
        request: AITransformRequest
    ) -> AsyncGenerator[AIStreamChunk, None]:
        """Stream content transformation using Grok API"""
        try:
            messages = self._build_transform_prompt(request)
            model_config = self._get_model_config(request.model)
            
            grok_request = GrokRequest(
                model=request.model.value,
                messages=messages,
                **model_config,
                stream=True
            )
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=grok_request.dict()
                ) as response:
                    
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=f"Grok API streaming error: {error_text.decode()}"
                        )
                    
                    chunk_counter = 0
                    accumulated_content = ""
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            chunk_data = line[6:]  # Remove "data: " prefix
                            
                            if chunk_data == "[DONE]":
                                yield AIStreamChunk(
                                    chunk_id=f"chunk_{chunk_counter}",
                                    content="",
                                    is_complete=True,
                                    metadata={"total_content": accumulated_content}
                                )
                                break
                            
                            try:
                                chunk_json = json.loads(chunk_data)
                                delta = chunk_json["choices"][0]["delta"]
                                
                                if "content" in delta:
                                    content = delta["content"]
                                    accumulated_content += content
                                    
                                    yield AIStreamChunk(
                                        chunk_id=f"chunk_{chunk_counter}",
                                        content=content,
                                        is_complete=False
                                    )
                                    
                                    chunk_counter += 1
                                    
                            except (json.JSONDecodeError, KeyError) as e:
                                logger.warning(f"Error parsing streaming chunk: {e}")
                                continue
                    
        except Exception as e:
            logger.error(f"Error in stream_transform_content: {str(e)}")
            yield AIStreamChunk(
                chunk_id="error",
                content=f"Error: {str(e)}",
                is_complete=True,
                metadata={"error": True}
            )
    
    async def stream_generate_content(
        self, 
        request: AIGenerateRequest
    ) -> AsyncGenerator[AIStreamChunk, None]:
        """Stream content generation using Grok API"""
        try:
            messages = self._build_generate_prompt(request)
            model_config = self._get_model_config(request.model)
            
            grok_request = GrokRequest(
                model=request.model.value,
                messages=messages,
                **model_config,
                stream=True
            )
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=grok_request.dict()
                ) as response:
                    
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=f"Grok API streaming error: {error_text.decode()}"
                        )
                    
                    chunk_counter = 0
                    accumulated_content = ""
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            chunk_data = line[6:]  # Remove "data: " prefix
                            
                            if chunk_data == "[DONE]":
                                yield AIStreamChunk(
                                    chunk_id=f"chunk_{chunk_counter}",
                                    content="",
                                    is_complete=True,
                                    metadata={"total_content": accumulated_content}
                                )
                                break
                            
                            try:
                                chunk_json = json.loads(chunk_data)
                                delta = chunk_json["choices"][0]["delta"]
                                
                                if "content" in delta:
                                    content = delta["content"]
                                    accumulated_content += content
                                    
                                    yield AIStreamChunk(
                                        chunk_id=f"chunk_{chunk_counter}",
                                        content=content,
                                        is_complete=False
                                    )
                                    
                                    chunk_counter += 1
                                    
                            except (json.JSONDecodeError, KeyError) as e:
                                logger.warning(f"Error parsing streaming chunk: {e}")
                                continue
                    
        except Exception as e:
            logger.error(f"Error in stream_generate_content: {str(e)}")
            yield AIStreamChunk(
                chunk_id="error",
                content=f"Error: {str(e)}",
                is_complete=True,
                metadata={"error": True}
            )


# Global service instance
grok_service = GrokAPIService()