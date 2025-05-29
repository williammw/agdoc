from sqlalchemy import Column, String, ForeignKey, DateTime, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from pydantic import BaseModel, validator
from datetime import datetime, timezone
from typing import Optional, Union, Dict, Any
from uuid import UUID as PyUUID
from sqlalchemy.ext.declarative import declarative_base

# Create SQLAlchemy base class
Base = declarative_base()

class SocialConnection(Base):
    __tablename__ = "social_connections"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String, nullable=False)
    provider_account_id = Column(String, nullable=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)  # Map to 'metadata' column in DB
    account_label = Column(String(255), nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    account_type = Column(String(50), default='personal', nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class SocialConnectionCreate(BaseModel):
    provider: str
    provider_account_id: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[Union[datetime, str]] = None
    profile_metadata: Optional[str] = None  # Field to store complete profile data as JSON string
    account_label: Optional[str] = None
    is_primary: Optional[bool] = False
    account_type: Optional[str] = 'personal'
    
    @validator('expires_at')
    def validate_expires_at(cls, v):
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # Try parsing as Unix timestamp (integer string)
                    return datetime.fromtimestamp(int(v), tz=timezone.utc)
                except (ValueError, TypeError):
                    pass
        return v


class SocialConnectionUpdate(BaseModel):
    """Model for updating social connection data"""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[Union[datetime, str]] = None
    metadata: Optional[Dict[str, Any]] = None  # This is for API compatibility
    account_label: Optional[str] = None
    is_primary: Optional[bool] = None
    account_type: Optional[str] = None
    
    @validator('expires_at')
    def validate_expires_at(cls, v):
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # Try parsing as Unix timestamp (integer string)
                    return datetime.fromtimestamp(int(v), tz=timezone.utc)
                except (ValueError, TypeError):
                    pass
        return v


class SocialConnectionResponse(BaseModel):
    """Model for social connection API responses"""
    id: PyUUID
    user_id: int
    provider: str
    provider_account_id: str
    expires_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None  # This will be populated from metadata_json
    account_label: Optional[str] = None
    is_primary: bool = False
    account_type: str = 'personal'
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True  # Updated from orm_mode for Pydantic v2
        
    @classmethod
    def from_orm(cls, obj):
        # Handle the metadata_json -> metadata conversion
        data = {
            "id": obj.id,
            "user_id": obj.user_id,
            "provider": obj.provider,
            "provider_account_id": obj.provider_account_id,
            "expires_at": obj.expires_at,
            "metadata": obj.metadata_json,  # Map from metadata_json to metadata
            "account_label": obj.account_label,
            "is_primary": obj.is_primary,
            "account_type": obj.account_type,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at
        }
        return cls(**data)


class SocialConnectionWithTokens(SocialConnectionResponse):
    """Model for social connection responses that include decrypted tokens"""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    
    class Config:
        from_attributes = True  # Updated from orm_mode for Pydantic v2 