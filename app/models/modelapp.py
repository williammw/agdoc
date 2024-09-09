

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class EmailPasswordRegister(BaseModel):
    email: EmailStr
    password: str
    display_name: Optional[str] = None
    photo_url: Optional[str] = None


class PhoneRegister(BaseModel):
    phone_number: str
    verification_code: str
    display_name: Optional[str] = None
    photo_url: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    photo_url: Optional[str] = None
    disabled: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    username: Optional[str] = None
    email: Optional[str] = None
    auth_provider: str = None
    created_at: datetime
    is_active: bool
    full_name: Optional[str] = None
    bio: Optional[str]
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None
    dob: Optional[date] = None
    cover_image: Optional[str] = None
    status: Optional[str] = None
    last_username_change: Optional[datetime] = None


    class Config:
        from_attributes = True
