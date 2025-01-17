from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class OAuthState(BaseModel):
    state: str
    platform: str
    user_id: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SocialAccount(BaseModel):
    id: str
    user_id: str
    platform: str
    platform_account_id: str
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    profile_image_url: Optional[str] = None
    access_token: str
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    account_type: str = "personal"
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SocialPost(BaseModel):
    id: str
    user_id: str
    account_id: str
    platform: str
    content: str
    media_urls: Optional[List[str]] = None
    platform_post_id: Optional[str] = None
    status: str = "draft"  # draft, scheduled, published, failed
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PostMetadata(BaseModel):
    post_id: str
    key: str
    value: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Request/Response models for API endpoints


class OAuthInitResponse(BaseModel):
    auth_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class OAuthCallbackResponse(BaseModel):
    success: bool
    account: Optional[SocialAccount] = None
    error: Optional[str] = None


class CreatePostRequest(BaseModel):
    account_id: str
    content: str
    media_urls: Optional[List[str]] = None
    scheduled_at: Optional[datetime] = None
    metadata: Optional[dict] = None


class CreatePostResponse(BaseModel):
    success: bool
    post: Optional[SocialPost] = None
    error: Optional[str] = None
