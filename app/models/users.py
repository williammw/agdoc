from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user model with common fields"""
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    display_name: Optional[str] = None
    work_description: Optional[str] = None
    bio: Optional[str] = None


class UserCreate(UserBase):
    """Model for creating a new user"""
    firebase_uid: str
    email_verified: bool = False
    auth_provider: str = "email"


class UserUpdate(BaseModel):
    """Model for updating user data"""
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email_verified: Optional[bool] = None
    display_name: Optional[str] = None
    work_description: Optional[str] = None
    bio: Optional[str] = None


class UserInDB(UserBase):
    """User model as stored in the database"""
    id: int
    firebase_uid: str
    email_verified: bool = False
    auth_provider: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True


class UserResponse(UserBase):
    """User model for API responses"""
    id: int
    email_verified: bool = False
    is_active: bool = True
    auth_provider: str
    
    class Config:
        orm_mode = True


class UserInfoBase(BaseModel):
    """Base model for user account info"""
    plan_type: str = "free"
    monthly_post_quota: int = 10
    remaining_posts: int = 10


class UserInfoCreate(UserInfoBase):
    """Model for creating user info"""
    user_id: int


class UserInfoUpdate(BaseModel):
    """Model for updating user info"""
    plan_type: Optional[str] = None
    monthly_post_quota: Optional[int] = None
    remaining_posts: Optional[int] = None


class UserInfoInDB(UserInfoBase):
    """User info model as stored in the database"""
    id: int
    user_id: int
    last_quota_reset: datetime
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True


class UserInfoResponse(UserInfoBase):
    """User info model for API responses"""
    id: int
    last_quota_reset: datetime
    
    class Config:
        orm_mode = True


class UserWithInfo(UserResponse):
    """User model with account info included"""
    user_info: Optional[UserInfoResponse] = None 