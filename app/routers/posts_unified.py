from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
import json
from datetime import datetime, timezone
from app.dependencies.auth import get_current_user
from app.utils.database import get_db

# Helper function to safely parse JSON strings
def safe_json_parse(value, default):
    """Safely parse JSON strings to Python objects"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    elif value is None:
        return default
    else:
        return value

# Helper function to transform database post data
def transform_post_data(post):
    """Transform post data from database to API response format"""
    return {
        **post,
        'universal_metadata': safe_json_parse(post.get('universal_metadata'), {}),
        'platform_content': safe_json_parse(post.get('platform_content'), {}),
        'platforms': safe_json_parse(post.get('platforms'), []),
        'media_files': safe_json_parse(post.get('media_files'), []),
    }

router = APIRouter(
    prefix="/api/v1/posts",
    tags=["posts-unified"],
    dependencies=[Depends(get_current_user)]
)

# Create database dependency with admin access
db_admin = get_db(admin_access=True)

# Pydantic models for the unified posts API
from pydantic import BaseModel, Field

class PostBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content_mode: str = Field(default="universal")

class PostCreate(PostBase):
    universal_content: Optional[str] = ""
    universal_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    platform_content: Optional[Dict[str, Any]] = Field(default_factory=dict)
    platforms: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    media_files: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    schedule_date: Optional[datetime] = None

class PostUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content_mode: Optional[str] = None
    universal_content: Optional[str] = None
    universal_metadata: Optional[Dict[str, Any]] = None
    platform_content: Optional[Dict[str, Any]] = None
    platforms: Optional[List[Dict[str, Any]]] = None
    media_files: Optional[List[Dict[str, Any]]] = None
    schedule_date: Optional[datetime] = None
    status: Optional[str] = None

class PostResponse(PostBase):
    id: UUID
    user_id: int
    universal_content: str
    universal_metadata: Dict[str, Any]
    platform_content: Dict[str, Any]
    platforms: List[Dict[str, Any]]
    media_files: List[Dict[str, Any]]
    schedule_date: Optional[datetime]
    status: str
    created_at: datetime
    updated_at: datetime

class PublishRequest(BaseModel):
    immediate: bool = Field(default=True)
    schedule_for: Optional[datetime] = None

class PublishResponse(BaseModel):
    success: bool
    message: str
    published_count: int = 0
    scheduled_count: int = 0
    errors: List[str] = Field(default_factory=list)

# Posts endpoints - unified single-table approach
@router.get("/", response_model=List[PostResponse])
async def get_posts(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Get all posts for the current user - SINGLE API CALL"""
    try:
        query = db.table('posts').select('*').eq('user_id', current_user["id"])
        
        if status:
            query = query.eq('status', status)
        
        query = query.order('created_at', desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        
        # Transform the data to ensure proper JSON structure
        posts = [transform_post_data(post) for post in response.data]
        
        return posts
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch posts: {str(e)}"
        )

@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: UUID,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Get a specific post by ID"""
    try:
        response = db.table('posts').select('*').eq('id', str(post_id)).eq('user_id', current_user["id"]).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Post not found")
        
        post = response.data[0]
        transformed_post = transform_post_data(post)
        
        return transformed_post
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch post: {str(e)}"
        )

@router.post("/", response_model=PostResponse)
async def create_post(
    post_data: PostCreate,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Create a new post - SINGLE API CALL"""
    try:
        insert_data = {
            "user_id": current_user["id"],
            "name": post_data.name,
            "content_mode": post_data.content_mode,
            "universal_content": post_data.universal_content,
            "universal_metadata": post_data.universal_metadata,
            "platform_content": post_data.platform_content,
            "platforms": post_data.platforms,
            "media_files": post_data.media_files,
            "schedule_date": post_data.schedule_date.isoformat() if post_data.schedule_date else None,
            "status": "draft"
        }
        
        response = db.table('posts').insert(insert_data).execute()
        if response.data:
            post = response.data[0]
            return transform_post_data(post)
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create post"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create post: {str(e)}"
        )

@router.patch("/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: UUID,
    post_data: PostUpdate,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Update a post - SINGLE API CALL with partial updates"""
    try:
        # Build update data only with provided fields
        update_data = {}
        
        if post_data.name is not None:
            update_data["name"] = post_data.name
        if post_data.content_mode is not None:
            update_data["content_mode"] = post_data.content_mode
        if post_data.universal_content is not None:
            update_data["universal_content"] = post_data.universal_content
        if post_data.universal_metadata is not None:
            update_data["universal_metadata"] = post_data.universal_metadata
        if post_data.platform_content is not None:
            update_data["platform_content"] = post_data.platform_content
        if post_data.platforms is not None:
            update_data["platforms"] = post_data.platforms
        if post_data.media_files is not None:
            update_data["media_files"] = post_data.media_files
        if post_data.schedule_date is not None:
            update_data["schedule_date"] = post_data.schedule_date.isoformat()
        if post_data.status is not None:
            update_data["status"] = post_data.status
        
        if not update_data:
            # No updates provided, just return current post
            return await get_post(post_id, current_user, db)
        
        response = db.table('posts').update(update_data).eq('id', str(post_id)).eq('user_id', current_user["id"]).execute()
        
        if response.data:
            post = response.data[0]
            return transform_post_data(post)
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update post: {str(e)}"
        )

@router.delete("/{post_id}")
async def delete_post(
    post_id: UUID,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Delete a post"""
    try:
        db.table('posts').delete().eq('id', str(post_id)).eq('user_id', current_user["id"]).execute()
        return {"success": True, "message": "Post deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete post: {str(e)}"
        )

@router.post("/{post_id}/publish", response_model=PublishResponse)
async def publish_post(
    post_id: UUID,
    publish_data: PublishRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Publish a post - for now this is a mock implementation"""
    try:
        # Get the post
        post = await get_post(post_id, current_user, db)
        
        if not post:
            return PublishResponse(
                success=False,
                message="Post not found",
                errors=["Post not found"]
            )
        
        if not post.platforms:
            return PublishResponse(
                success=False,
                message="No platforms selected for publishing",
                errors=["No platforms configured"]
            )
        
        # Mock publishing logic
        try:
            if publish_data.immediate:
                # Update post status to published
                await update_post(
                    post_id, 
                    PostUpdate(status="published"), 
                    current_user, 
                    db
                )
                
                return PublishResponse(
                    success=True,
                    message=f"Post published successfully to {len(post.platforms)} platform(s)",
                    published_count=len(post.platforms)
                )
            else:
                # Update post status to scheduled
                schedule_date = publish_data.schedule_for or datetime.now(timezone.utc)
                await update_post(
                    post_id, 
                    PostUpdate(status="scheduled", schedule_date=schedule_date), 
                    current_user, 
                    db
                )
                
                return PublishResponse(
                    success=True,
                    message=f"Post scheduled successfully for {len(post.platforms)} platform(s)",
                    scheduled_count=len(post.platforms)
                )
                
        except Exception as e:
            return PublishResponse(
                success=False,
                message="Publishing failed",
                errors=[str(e)]
            )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish post: {str(e)}"
        )

# Bulk operations for better performance
@router.patch("/bulk", response_model=List[PostResponse])
async def bulk_update_posts(
    updates: Dict[str, PostUpdate],  # post_id -> update data
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Bulk update multiple posts - useful for batch operations"""
    try:
        updated_posts = []
        for post_id, update_data in updates.items():
            try:
                updated_post = await update_post(UUID(post_id), update_data, current_user, db)
                updated_posts.append(updated_post)
            except Exception as e:
                # Continue with other updates, log the error
                print(f"Failed to update post {post_id}: {e}")
        
        return updated_posts
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk update failed: {str(e)}"
        )

# Statistics endpoint
@router.get("/stats/summary")
async def get_posts_summary(
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Get summary statistics about user's posts"""
    try:
        # Get count by status
        response = db.table('posts').select('status').eq('user_id', current_user["id"]).execute()
        
        stats = {
            'total': len(response.data),
            'draft': 0,
            'scheduled': 0,
            'published': 0,
            'failed': 0
        }
        
        for post in response.data:
            status_val = post.get('status', 'draft')
            if status_val in stats:
                stats[status_val] += 1
        
        return {"success": True, "data": stats}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch stats: {str(e)}"
        )