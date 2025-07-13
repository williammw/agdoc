import logging
import json
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.dependencies.auth import get_current_user
from app.models.ai import (
    AITransformRequest,
    AIGenerateRequest,
    AITransformResponse,
    AIGenerateResponse,
    AIStreamChunk,
    AIErrorResponse
)
from app.services.ai_service import grok_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/ai",
    tags=["ai"],
    dependencies=[Depends(get_current_user)]
)


async def stream_response_generator(stream_generator):
    """Generator for streaming responses in Server-Sent Events format"""
    try:
        async for chunk in stream_generator:
            # Format as Server-Sent Events
            chunk_data = chunk.dict()
            yield f"data: {json.dumps(chunk_data)}\n\n"
            
            # End stream if complete
            if chunk.is_complete:
                break
    except Exception as e:
        # Send error chunk
        error_chunk = AIStreamChunk(
            chunk_id="error",
            content=f"Stream error: {str(e)}",
            is_complete=True,
            metadata={"error": True}
        )
        yield f"data: {json.dumps(error_chunk.dict())}\n\n"


@router.post("/transform", response_model=AITransformResponse)
async def transform_content(
    request: AITransformRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Transform existing content using AI
    
    This endpoint uses Grok AI to transform content according to specified parameters:
    - Platform optimization (Twitter, LinkedIn, Facebook, etc.)
    - Tone adjustment (professional, casual, humorous, etc.)
    - Length adjustment
    - Hashtag suggestions
    - Content rewriting
    - Summarization or expansion
    
    Supports both streaming and non-streaming responses.
    """
    try:
        logger.info(f"User {current_user.get('id')} requesting content transformation")
        
        # Check if streaming is requested
        if request.stream:
            # Return streaming response
            stream_generator = grok_service.stream_transform_content(request)
            
            return StreamingResponse(
                stream_response_generator(stream_generator),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream",
                }
            )
        else:
            # Return complete response
            result = await grok_service.transform_content(request)
            logger.info(f"Content transformation completed for user {current_user.get('id')}")
            return result
            
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error in transform_content endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to transform content: {str(e)}"
        )


@router.post("/generate", response_model=AIGenerateResponse)
async def generate_content(
    request: AIGenerateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Generate new content using AI
    
    This endpoint uses Grok AI to generate original content based on:
    - User prompts and topics
    - Target platform optimization
    - Desired tone and style
    - Length requirements
    - Hashtag inclusion
    - Call-to-action integration
    
    Supports both streaming and non-streaming responses.
    """
    try:
        logger.info(f"User {current_user.get('id')} requesting content generation")
        
        # Check if streaming is requested
        if request.stream:
            # Return streaming response
            stream_generator = grok_service.stream_generate_content(request)
            
            return StreamingResponse(
                stream_response_generator(stream_generator),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream",
                }
            )
        else:
            # Return complete response
            result = await grok_service.generate_content(request)
            logger.info(f"Content generation completed for user {current_user.get('id')}")
            return result
            
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error in generate_content endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate content: {str(e)}"
        )


@router.get("/models")
async def list_available_models(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    List available Grok AI models
    
    Returns information about available models, their capabilities,
    and recommended use cases.
    """
    try:
        models_info = {
            "available_models": [
                {
                    "id": "grok-4",
                    "name": "Grok 4",
                    "description": "Latest and most capable model with advanced reasoning",
                    "max_tokens": 4000,
                    "best_for": ["complex transformations", "creative writing", "detailed analysis"],
                    "speed": "moderate"
                },
                {
                    "id": "grok-3-mini",
                    "name": "Grok 3 Mini",
                    "description": "Fast and efficient model for quick tasks",
                    "max_tokens": 2000,
                    "best_for": ["quick transformations", "hashtag generation", "tone adjustment"],
                    "speed": "fast"
                },
                {
                    "id": "grok-beta",
                    "name": "Grok Beta",
                    "description": "Experimental model with cutting-edge features",
                    "max_tokens": 3000,
                    "best_for": ["experimental features", "creative content"],
                    "speed": "moderate"
                },
                {
                    "id": "grok-2-1212",
                    "name": "Grok 2",
                    "description": "Stable and reliable model for production use",
                    "max_tokens": 3000,
                    "best_for": ["professional content", "platform optimization"],
                    "speed": "moderate"
                },
                {
                    "id": "grok-2-mini-1212",
                    "name": "Grok 2 Mini",
                    "description": "Lightweight version of Grok 2",
                    "max_tokens": 1500,
                    "best_for": ["simple transformations", "quick generation"],
                    "speed": "fast"
                }
            ],
            "default_model": "grok-3-mini",
            "recommendation": {
                "for_speed": "grok-3-mini",
                "for_quality": "grok-4",
                "for_balance": "grok-2-1212"
            }
        }
        
        return models_info
        
    except Exception as e:
        logger.error(f"Error in list_available_models endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list models: {str(e)}"
        )


@router.get("/platforms")
async def list_supported_platforms(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    List supported social media platforms
    
    Returns information about supported platforms and their
    specific optimization guidelines.
    """
    try:
        platforms_info = {
            "supported_platforms": [
                {
                    "id": "twitter",
                    "name": "Twitter/X",
                    "character_limit": 280,
                    "best_practices": [
                        "Use engaging hooks",
                        "Include 2-3 relevant hashtags",
                        "Consider thread format for longer content",
                        "Use line breaks for readability"
                    ],
                    "content_types": ["text", "threads", "replies"]
                },
                {
                    "id": "linkedin",
                    "name": "LinkedIn",
                    "character_limit": 3000,
                    "best_practices": [
                        "Professional tone",
                        "Industry-relevant keywords",
                        "Include professional insights",
                        "End with engaging questions"
                    ],
                    "content_types": ["posts", "articles", "professional updates"]
                },
                {
                    "id": "facebook",
                    "name": "Facebook",
                    "character_limit": 63206,
                    "optimal_length": "100-300 words",
                    "best_practices": [
                        "Conversational tone",
                        "Use emojis sparingly",
                        "Include calls to action",
                        "Optimize for community engagement"
                    ],
                    "content_types": ["posts", "stories", "comments"]
                },
                {
                    "id": "instagram",
                    "name": "Instagram",
                    "character_limit": 2200,
                    "best_practices": [
                        "Visual-first approach",
                        "Use line breaks and emojis",
                        "Include up to 30 hashtags",
                        "Engaging captions"
                    ],
                    "content_types": ["posts", "stories", "reels", "captions"]
                },
                {
                    "id": "threads",
                    "name": "Threads",
                    "character_limit": 500,
                    "best_practices": [
                        "Conversational tone",
                        "Good for discussions",
                        "Keep posts concise but engaging",
                        "Thread longer thoughts"
                    ],
                    "content_types": ["posts", "threads", "replies"]
                },
                {
                    "id": "youtube",
                    "name": "YouTube",
                    "character_limit": 5000,
                    "best_practices": [
                        "SEO-optimized keywords",
                        "Include timestamps",
                        "Clear calls to action",
                        "Detailed descriptions"
                    ],
                    "content_types": ["descriptions", "titles", "comments"]
                },
                {
                    "id": "tiktok",
                    "name": "TikTok",
                    "character_limit": 4000,
                    "best_practices": [
                        "Short, punchy content",
                        "Trend-aware language",
                        "Popular hashtags",
                        "Video-complementary text"
                    ],
                    "content_types": ["descriptions", "captions", "comments"]
                }
            ]
        }
        
        return platforms_info
        
    except Exception as e:
        logger.error(f"Error in list_supported_platforms endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list platforms: {str(e)}"
        )


@router.get("/health")
async def ai_service_health(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Check AI service health and configuration
    
    Returns the current status of the AI service including
    API connectivity and configuration status.
    """
    try:
        # Check if API key is configured
        api_key_configured = bool(grok_service.api_key)
        
        service_status = {
            "status": "healthy" if api_key_configured else "configuration_required",
            "api_key_configured": api_key_configured,
            "base_url": grok_service.base_url,
            "timeout": grok_service.timeout,
            "features": {
                "content_transformation": True,
                "content_generation": True,
                "streaming_responses": True,
                "platform_optimization": True,
                "multiple_models": True
            }
        }
        
        if not api_key_configured:
            service_status["message"] = "GROK_API_KEY environment variable not configured"
        
        return service_status
        
    except Exception as e:
        logger.error(f"Error in ai_service_health endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check service health: {str(e)}"
        )


@router.post("/test")
async def test_ai_service(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Test AI service with a simple request
    
    Performs a basic test of the AI service to verify
    it's working correctly with the current configuration.
    """
    try:
        # Create a simple test request
        test_request = AITransformRequest(
            content="Hello world! This is a test message.",
            transformation_type="platform_optimize",
            target_platform="twitter",
            model="grok-3-mini"
        )
        
        # Attempt transformation
        result = await grok_service.transform_content(test_request)
        
        return {
            "status": "success",
            "message": "AI service is working correctly",
            "test_result": {
                "original_content": result.original_content,
                "transformed_content": result.transformed_content,
                "model_used": result.model_used,
                "processing_time": result.processing_time
            }
        }
        
    except Exception as e:
        logger.error(f"Error in test_ai_service endpoint: {str(e)}")
        
        return {
            "status": "error",
            "message": f"AI service test failed: {str(e)}",
            "error_details": {
                "api_key_configured": bool(grok_service.api_key),
                "error_type": type(e).__name__
            }
        }