from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class GrokModel(str, Enum):
    """Available Grok models"""
    GROK_4 = "grok-4"
    GROK_3_MINI = "grok-3-mini"
    GROK_BETA = "grok-beta"
    GROK_2 = "grok-2-1212"
    GROK_2_MINI = "grok-2-mini-1212"


class ContentTransformationType(str, Enum):
    """Types of content transformation"""
    PLATFORM_OPTIMIZE = "platform_optimize"
    TONE_ADJUST = "tone_adjust"
    LENGTH_ADJUST = "length_adjust"
    HASHTAG_SUGGEST = "hashtag_suggest"
    REWRITE = "rewrite"
    SUMMARIZE = "summarize"
    EXPAND = "expand"


class PlatformType(str, Enum):
    """Supported social media platforms"""
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    THREADS = "threads"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"


class ContentTone(str, Enum):
    """Content tone options"""
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    FRIENDLY = "friendly"
    HUMOROUS = "humorous"
    INSPIRATIONAL = "inspirational"
    EDUCATIONAL = "educational"
    PROMOTIONAL = "promotional"


# Request Models
class AITransformRequest(BaseModel):
    """Request model for content transformation"""
    content: str = Field(..., min_length=1, max_length=5000, description="Content to transform")
    transformation_type: ContentTransformationType = Field(..., description="Type of transformation to apply")
    target_platform: Optional[PlatformType] = Field(None, description="Target platform for optimization")
    target_tone: Optional[ContentTone] = Field(None, description="Target tone for the content")
    target_length: Optional[int] = Field(None, ge=10, le=5000, description="Target length in characters")
    additional_instructions: Optional[str] = Field(None, max_length=500, description="Additional transformation instructions")
    model: GrokModel = Field(default=GrokModel.GROK_3_MINI, description="Grok model to use")
    stream: bool = Field(default=False, description="Whether to stream the response")


class AIGenerateRequest(BaseModel):
    """Request model for content generation"""
    prompt: str = Field(..., min_length=1, max_length=1000, description="Prompt for content generation")
    topic: Optional[str] = Field(None, max_length=200, description="Topic or subject for the content")
    target_platform: Optional[PlatformType] = Field(None, description="Target platform for the content")
    content_tone: Optional[ContentTone] = Field(None, description="Desired tone for the content")
    target_length: Optional[int] = Field(None, ge=10, le=5000, description="Target length in characters")
    include_hashtags: bool = Field(default=False, description="Whether to include relevant hashtags")
    include_call_to_action: bool = Field(default=False, description="Whether to include a call to action")
    context: Optional[str] = Field(None, max_length=500, description="Additional context for generation")
    model: GrokModel = Field(default=GrokModel.GROK_3_MINI, description="Grok model to use")
    stream: bool = Field(default=False, description="Whether to stream the response")


# Response Models
class AIContentSuggestion(BaseModel):
    """Single content suggestion"""
    content: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AITransformResponse(BaseModel):
    """Response model for content transformation"""
    original_content: str
    transformed_content: str
    transformation_type: ContentTransformationType
    target_platform: Optional[PlatformType] = None
    target_tone: Optional[ContentTone] = None
    suggestions: Optional[List[AIContentSuggestion]] = None
    reasoning: Optional[str] = None
    model_used: GrokModel
    processing_time: float
    character_count: int
    word_count: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIGenerateResponse(BaseModel):
    """Response model for content generation"""
    generated_content: str
    prompt_used: str
    target_platform: Optional[PlatformType] = None
    content_tone: Optional[ContentTone] = None
    suggestions: Optional[List[AIContentSuggestion]] = None
    hashtags: Optional[List[str]] = None
    reasoning: Optional[str] = None
    model_used: GrokModel
    processing_time: float
    character_count: int
    word_count: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIStreamChunk(BaseModel):
    """Model for streaming response chunks"""
    chunk_id: str
    content: str
    is_complete: bool = False
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AIErrorResponse(BaseModel):
    """Error response model"""
    error: str
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Internal Models for Grok API
class GrokMessage(BaseModel):
    """Message model for Grok API"""
    role: Literal["system", "user", "assistant"]
    content: str


class GrokRequest(BaseModel):
    """Internal model for Grok API requests"""
    model: str
    messages: List[GrokMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: bool = False


class GrokResponse(BaseModel):
    """Internal model for Grok API responses"""
    id: str
    object: str
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Optional[Dict[str, Any]] = None


class GrokStreamResponse(BaseModel):
    """Internal model for Grok API streaming responses"""
    id: str
    object: str
    created: int
    model: str
    choices: List[Dict[str, Any]]