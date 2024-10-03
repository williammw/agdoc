from datetime import date, datetime
from typing import Optional, List, Union
from pydantic import BaseModel, EmailStr
from pydantic import BaseModel, constr, HttpUrl


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


class PostResponse(BaseModel):
    id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    user_id: str
    user: UserResponse


class SharedPostResponse(BaseModel):
    id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    user_id: str
    user: UserResponse

    class Config:
        from_attributes = True



class CommentResponse(BaseModel):
    id: str
    content: str
    created_at: datetime
    updated_at: datetime
    user_id: str
    user: UserResponse

    class Config:
        from_attributes = True

class VideoResponse(BaseModel):
    id: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    user_id: str
    user: UserResponse


class SharedVideoResponse(VideoResponse):
    class Config:
        from_attributes = True

class VideoWithCommentsResponse(VideoResponse):
    comments: List[CommentResponse]


class ImageResponse(BaseModel):
    id: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    user_id: str
    user: UserResponse

    class Config:
        from_attributes = True

class ImageWithCommentsResponse(ImageResponse):
    comments: List[CommentResponse]


class FolderResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    user_id: str
    user: UserResponse




class AssetResponse(BaseModel):
    id: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    asset_type: str  # Add this field to distinguish between different asset types

    class Config:
        from_attributes = True

# Add this new class to represent different types of assets
class UnionAssetResponse(BaseModel):
    asset: Union[PostResponse, VideoResponse, ImageResponse]

    class Config:
        from_attributes = True


class FolderWithAssetsResponse(FolderResponse):
    assets: List[AssetResponse]


class PostWithCommentsResponse(PostResponse):
    comments: List[CommentResponse]


class SharedPostCreate(BaseModel):
    # Add the fields you need for creating a shared post
    original_post_id: int
    # Add other fields as necessary


class PostCreate(BaseModel):
    content: constr(max_length=5000)  # type: ignore # Limit content length


class MediaItem(BaseModel):
    id: int
    media_url: str
    media_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[float] = None
    cloudflare_info: Optional[dict] = None
    status: str
    task_id: Optional[str] = None






class User(BaseModel):
    username: str
    avatar_url: Optional[str] = None


class PostResponse(BaseModel):
    id: str
    user_id: str
    content: str
    privacy_setting: str
    created_at: datetime
    updated_at: datetime
    status: str
    media: List[MediaItem]

    class Config:
        # orm_mode = True
        from_attributes = True
        # json_encoders = {
        #     datetime: lambda v: v.isoformat()
        # }


class ReportCreate(BaseModel):
    reported_id: str
    content_type: str  # 'post', 'comment', or 'user'
    reason: str


class ReportResponse(BaseModel):
    id: str
    reporter_id: str
    reported_id: str
    content_type: str
    reason: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserInteraction(BaseModel):
    post_id: str
    interaction_count: int

class UserInteractionResponse(BaseModel):
    post_id: str
    interaction_count: int

class PostResponseWithMedia(PostResponse):
    media: List[MediaItem]

    class Config:
        from_attributes = True

