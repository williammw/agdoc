from pydantic import BaseModel, Field, UUID4, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class Folder(BaseModel):
    """Base folder model"""
    id: UUID4
    name: str
    parent_id: Optional[UUID4] = None
    created_by: UUID4
    created_at: datetime
    updated_at: datetime
    file_count: int = 0


class FolderCreate(BaseModel):
    """Model for creating a folder"""
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[UUID4] = None


class FolderUpdate(BaseModel):
    """Model for updating a folder"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    parent_id: Optional[UUID4] = None


class FolderResponse(Folder):
    """Response model for folder operations"""
    pass


class FolderList(BaseModel):
    """Response model for list of folders"""
    folders: List[Folder]
    total: int


class MediaFile(BaseModel):
    """Base media file model"""
    id: UUID4
    name: str
    type: str
    size: int
    url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    folder_id: Optional[UUID4] = None
    metadata: Dict[str, Any] = {}
    usage_count: int = 0
    created_by: UUID4
    created_at: datetime
    updated_at: datetime


class MediaFileCreate(BaseModel):
    """Model for creating a media file"""
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=50)
    size: int = Field(..., gt=0)
    url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = Field(None, gt=0)
    height: Optional[int] = Field(None, gt=0)
    folder_id: Optional[UUID4] = None
    metadata: Dict[str, Any] = {}


class MediaFileUpdate(BaseModel):
    """Model for updating a media file"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    metadata: Optional[Dict[str, Any]] = None


class MediaFileResponse(MediaFile):
    """Response model for media file operations"""
    pass


class MediaFileList(BaseModel):
    """Response model for list of media files"""
    files: List[MediaFile]
    total: int
    page: int
    limit: int


class FileOperation(BaseModel):
    """Model for file operations (move, copy, delete)"""
    file_ids: List[UUID4]
    target_folder_id: Optional[UUID4] = None

    @validator('file_ids')
    def validate_file_ids(cls, v):
        if not v:
            raise ValueError("file_ids cannot be empty")
        if len(v) > 100:  # Limit batch operations to 100 files
            raise ValueError("Cannot operate on more than 100 files at once")
        return v


class SearchFilters(BaseModel):
    """Model for search filters"""
    type: Optional[str] = None
    folder_id: Optional[UUID4] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    min_size: Optional[int] = Field(None, ge=0)
    max_size: Optional[int] = Field(None, ge=0)
    min_usage: Optional[int] = Field(None, ge=0)
    max_usage: Optional[int] = Field(None, ge=0)


class SortOptions(BaseModel):
    """Model for sorting options"""
    field: str = Field(..., pattern="^(name|created_at|size|usage_count)$")
    order: str = Field(..., pattern="^(asc|desc)$")
