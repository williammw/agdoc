from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from uuid import UUID as PyUUID
from sqlalchemy.ext.declarative import declarative_base

# Create SQLAlchemy base class
Base = declarative_base()

class SocialConnection(Base):
    __tablename__ = "social_connections"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String, nullable=False)
    provider_account_id = Column(String, nullable=False)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class SocialConnectionCreate(BaseModel):
    provider: str
    provider_account_id: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None 