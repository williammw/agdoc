from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date, time
from uuid import UUID
from enum import Enum

class ContentMode(str, Enum):
    UNIVERSAL = "universal"
    SPECIFIC = "specific"

class PostStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class FileType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"

class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# Base models
class PostGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content_mode: ContentMode = ContentMode.UNIVERSAL

class PostGroupCreate(PostGroupBase):
    pass

class PostGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content_mode: Optional[ContentMode] = None

class PostGroup(PostGroupBase):
    id: UUID
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Post Draft models
class PostDraftBase(BaseModel):
    platform: str = Field(..., min_length=1, max_length=50)
    account_id: Optional[UUID] = None
    account_key: Optional[str] = Field(None, max_length=100)
    content: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    mentions: List[str] = Field(default_factory=list)
    media_ids: List[str] = Field(default_factory=list)
    youtube_title: Optional[str] = Field(None, max_length=100)
    youtube_description: Optional[str] = None
    youtube_tags: List[str] = Field(default_factory=list)
    location: Optional[str] = Field(None, max_length=255)
    link: Optional[str] = Field(None, max_length=500)
    schedule_date: Optional[date] = None
    schedule_time: Optional[time] = None
    timezone: str = Field(default="UTC", max_length=50)

class PostDraftCreate(PostDraftBase):
    post_group_id: UUID

class PostDraftUpdate(BaseModel):
    platform: Optional[str] = Field(None, min_length=1, max_length=50)
    account_id: Optional[UUID] = None
    account_key: Optional[str] = Field(None, max_length=100)
    content: Optional[str] = None
    hashtags: Optional[List[str]] = None
    mentions: Optional[List[str]] = None
    media_ids: Optional[List[str]] = None
    youtube_title: Optional[str] = Field(None, max_length=100)
    youtube_description: Optional[str] = None
    youtube_tags: Optional[List[str]] = None
    location: Optional[str] = Field(None, max_length=255)
    link: Optional[str] = Field(None, max_length=500)
    schedule_date: Optional[date] = None
    schedule_time: Optional[time] = None
    timezone: Optional[str] = Field(None, max_length=50)
    status: Optional[PostStatus] = None

class PostDraft(PostDraftBase):
    id: UUID
    post_group_id: UUID
    user_id: int
    status: PostStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Published Post models
class PublishedPostBase(BaseModel):
    platform: str = Field(..., min_length=1, max_length=50)
    account_id: Optional[UUID] = None
    content_snapshot: Dict[str, Any]
    platform_post_id: Optional[str] = Field(None, max_length=255)
    platform_url: Optional[str] = Field(None, max_length=500)
    platform_response: Optional[Dict[str, Any]] = None
    engagement_stats: Dict[str, Any] = Field(default_factory=dict)

class PublishedPostCreate(PublishedPostBase):
    post_draft_id: Optional[UUID] = None
    post_group_id: UUID

class PublishedPost(PublishedPostBase):
    id: UUID
    post_draft_id: Optional[UUID]
    post_group_id: UUID
    user_id: int
    published_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Media File models
class MediaFileBase(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    original_name: str = Field(..., min_length=1, max_length=255)
    file_type: FileType
    file_size: int = Field(..., gt=0)
    mime_type: str = Field(..., min_length=1, max_length=100)
    storage_path: str = Field(..., min_length=1, max_length=500)
    storage_url: Optional[str] = Field(None, max_length=500)
    platform_compatibility: List[str] = Field(default_factory=list)
    width: Optional[int] = Field(None, gt=0)
    height: Optional[int] = Field(None, gt=0)
    duration: Optional[int] = Field(None, gt=0)
    thumbnail_url: Optional[str] = Field(None, max_length=500)

class MediaFileCreate(MediaFileBase):
    pass

class MediaFileUpdate(BaseModel):
    processing_status: Optional[ProcessingStatus] = None
    storage_url: Optional[str] = Field(None, max_length=500)
    width: Optional[int] = Field(None, gt=0)
    height: Optional[int] = Field(None, gt=0)
    duration: Optional[int] = Field(None, gt=0)
    thumbnail_url: Optional[str] = Field(None, max_length=500)

class MediaFile(MediaFileBase):
    id: UUID
    user_id: int
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Scheduled Job models
class ScheduledJobBase(BaseModel):
    job_type: str = Field(default="publish_post", max_length=50)
    scheduled_for: datetime
    max_attempts: int = Field(default=3, gt=0)

class ScheduledJobCreate(ScheduledJobBase):
    post_draft_id: UUID

class ScheduledJob(ScheduledJobBase):
    id: UUID
    post_draft_id: UUID
    user_id: int
    status: JobStatus
    attempts: int
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Complex request/response models
class PostGroupWithDrafts(PostGroup):
    drafts: List[PostDraft] = Field(default_factory=list)

class PublishRequest(BaseModel):
    post_group_id: UUID
    immediate: bool = Field(default=True)
    schedule_for: Optional[datetime] = None

class PublishResponse(BaseModel):
    success: bool
    message: str
    published_posts: List[UUID] = Field(default_factory=list)
    scheduled_jobs: List[UUID] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

class SaveDraftRequest(BaseModel):
    post_group_id: UUID
    drafts: List[PostDraftCreate]

class SaveDraftResponse(BaseModel):
    success: bool
    message: str
    saved_drafts: List[UUID] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

# Bulk operations
class BulkPostDraftCreate(BaseModel):
    post_group_id: UUID
    drafts: List[PostDraftCreate]

class BulkPostDraftUpdate(BaseModel):
    updates: Dict[UUID, PostDraftUpdate]  # draft_id -> update data