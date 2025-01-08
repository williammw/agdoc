from pydantic import BaseModel, EmailStr, Json, constr
from typing import Optional, Dict, Any
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    plan_type: str = 'free'
    company_name: Optional[str] = None
    company_size: Optional[str] = None
    industry: Optional[str] = None
    language_preference: str = 'en'
    timezone: str = 'UTC'

class UserCreate(UserBase):
    id: str  # Firebase UID

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    timezone: Optional[str] = None
    notification_preferences: Optional[Dict] = None
    firebase_display_name: Optional[str] = None
    firebase_photo_url: Optional[str] = None
    is_email_verified: Optional[bool] = None

class UserPlanUpdate(BaseModel):
    plan_type: str
    plan_valid_until: datetime
    monthly_post_quota: int
    subscription_id: Optional[str] = None
    payment_method: Optional[Dict[str, Any]] = None
    billing_address: Optional[Dict[str, Any]] = None

class UserInfo(UserBase):
    id: str
    plan_valid_until: Optional[datetime] = None
    monthly_post_quota: int
    remaining_posts: int
    quota_reset_date: Optional[datetime] = None
    notification_preferences: Dict[str, bool]
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None
    is_active: bool
    is_verified: bool
    subscription_id: Optional[str] = None
    firebase_display_name: Optional[str] = None
    firebase_photo_url: Optional[str] = None
    is_email_verified: Optional[bool] = None

    class Config:
        orm_mode = True
