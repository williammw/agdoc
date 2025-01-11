from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4

class ContentBase(BaseModel):
    name: str
    description: Optional[str] = None
    route: str
    status: str = "draft"

class ContentCreate(ContentBase):
    pass

class ContentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    route: Optional[str] = None
    status: Optional[str] = None

class ContentVersion(BaseModel):
    content_data: Dict[str, Any]
    version: int = 1

class ContentResponse(ContentBase):
    id: int
    uuid: UUID
    firebase_uid: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 