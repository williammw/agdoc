from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
import json
from datetime import datetime, timedelta
from app.dependencies.auth import get_current_user
from app.utils.database import get_db

router = APIRouter(
    prefix="/api/v1/content",
    tags=["content"],
    dependencies=[Depends(get_current_user)]
)

# Create database dependency with admin access
db_admin = get_db(admin_access=True)

# Simple data models for request/response
from pydantic import BaseModel, Field

class PostGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content_mode: str = Field(default="universal")

class PostGroupCreate(PostGroupBase):
    pass

class PostGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content_mode: Optional[str] = None

class PostGroup(PostGroupBase):
    id: UUID
    user_id: int
    created_at: datetime
    updated_at: datetime

class PostDraftRequest(BaseModel):
    group_name: str
    content_mode: str = "universal"
    universal_content: Optional[str] = None
    universal_metadata: Dict[str, Any] = Field(default_factory=dict)
    account_specific_content: Dict[str, Any] = Field(default_factory=dict)
    selected_platforms: List[Dict[str, Any]] = Field(default_factory=list)
    media_files: List[Dict[str, Any]] = Field(default_factory=list)
    schedule_date: Optional[datetime] = None

class PublishRequest(BaseModel):
    group_name: str
    immediate: bool = Field(default=True)

class PublishResponse(BaseModel):
    success: bool
    message: str
    published_count: int = 0
    scheduled_count: int = 0
    errors: List[str] = Field(default_factory=list)

# Post Groups endpoints
@router.get("/groups")
async def get_post_groups(
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Get all post groups for the current user"""
    try:
        response = db.table('post_groups').select('*').eq('user_id', current_user["id"]).order('created_at', desc=True).execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch post groups: {str(e)}"
        )

@router.post("/groups")
async def create_post_group(
    group_data: PostGroupCreate,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Create a new post group"""
    try:
        insert_data = {
            "user_id": current_user["id"],
            "name": group_data.name,
            "content_mode": group_data.content_mode
        }
        
        response = db.table('post_groups').insert(insert_data).execute()
        if response.data:
            return {"success": True, "data": response.data[0]}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create post group"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create post group: {str(e)}"
        )

@router.put("/groups/{group_id}")
async def update_post_group(
    group_id: UUID,
    group_data: PostGroupUpdate,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Update a post group"""
    try:
        # Build update data
        update_data = {}
        if group_data.name is not None:
            update_data["name"] = group_data.name
        if group_data.content_mode is not None:
            update_data["content_mode"] = group_data.content_mode
        
        if not update_data:
            # No updates provided
            response = db.table('post_groups').select('*').eq('id', str(group_id)).eq('user_id', current_user["id"]).execute()
            if response.data:
                return {"success": True, "data": response.data[0]}
            else:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post group not found")
        
        response = db.table('post_groups').update(update_data).eq('id', str(group_id)).eq('user_id', current_user["id"]).execute()
        if response.data:
            return {"success": True, "data": response.data[0]}
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post group not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update post group: {str(e)}"
        )

@router.delete("/groups/{group_id}")
async def delete_post_group(
    group_id: UUID,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Delete a post group"""
    try:
        response = db.table('post_groups').delete().eq('id', str(group_id)).eq('user_id', current_user["id"]).execute()
        return {"success": True, "message": "Post group deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete post group: {str(e)}"
        )

# Post Drafts endpoints (working with existing structure)
@router.get("/drafts")
async def get_drafts(
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Get all drafts for the current user"""
    try:
        response = db.table('post_drafts').select('*').eq('user_id', current_user["id"]).order('created_at', desc=True).execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch drafts: {str(e)}"
        )

@router.post("/drafts")
async def save_draft(
    draft_data: PostDraftRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Save a post draft using the existing post_drafts table structure"""
    try:
        insert_data = {
            "user_id": current_user["id"],
            "group_name": draft_data.group_name,
            "content_mode": draft_data.content_mode,
            "universal_content": draft_data.universal_content,
            "universal_metadata": json.dumps(draft_data.universal_metadata),
            "account_specific_content": json.dumps(draft_data.account_specific_content),
            "selected_platforms": json.dumps(draft_data.selected_platforms),
            "media_files": json.dumps(draft_data.media_files),
            "schedule_date": draft_data.schedule_date.isoformat() if draft_data.schedule_date else None,
            "status": "draft"
        }
        
        response = db.table('post_drafts').insert(insert_data).execute()
        if response.data:
            return {"success": True, "data": response.data[0], "message": "Draft saved successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save draft"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save draft: {str(e)}"
        )

@router.put("/drafts/{draft_id}")
async def update_draft(
    draft_id: UUID,
    draft_data: PostDraftRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Update an existing draft"""
    try:
        update_data = {
            "group_name": draft_data.group_name,
            "content_mode": draft_data.content_mode,
            "universal_content": draft_data.universal_content,
            "universal_metadata": json.dumps(draft_data.universal_metadata),
            "account_specific_content": json.dumps(draft_data.account_specific_content),
            "selected_platforms": json.dumps(draft_data.selected_platforms),
            "media_files": json.dumps(draft_data.media_files),
            "schedule_date": draft_data.schedule_date.isoformat() if draft_data.schedule_date else None,
        }
        
        response = db.table('post_drafts').update(update_data).eq('id', str(draft_id)).eq('user_id', current_user["id"]).execute()
        if response.data:
            return {"success": True, "data": response.data[0], "message": "Draft updated successfully"}
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update draft: {str(e)}"
        )

@router.delete("/drafts/{draft_id}")
async def delete_draft(
    draft_id: UUID,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Delete a draft"""
    try:
        response = db.table('post_drafts').delete().eq('id', str(draft_id)).eq('user_id', current_user["id"]).execute()
        return {"success": True, "message": "Draft deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete draft: {str(e)}"
        )

# Publishing endpoints
@router.post("/publish")
async def publish_posts(
    publish_data: PublishRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Publish posts - for now this is a mock implementation"""
    try:
        # Get drafts for the group
        response = db.table('post_drafts').select('*').eq('user_id', current_user["id"]).eq('group_name', publish_data.group_name).eq('status', 'draft').execute()
        
        drafts = response.data
        if not drafts:
            return PublishResponse(
                success=False,
                message="No drafts found for publishing",
                errors=["No drafts in draft status found"]
            )
        
        published_count = 0
        scheduled_count = 0
        errors = []
        
        for draft in drafts:
            try:
                if publish_data.immediate:
                    # Mock immediate publishing
                    # Update draft status to published
                    update_response = db.table('post_drafts').update({"status": "published"}).eq('id', draft['id']).execute()
                    published_count += 1
                else:
                    # Mock scheduled publishing
                    update_response = db.table('post_drafts').update({"status": "scheduled"}).eq('id', draft['id']).execute()
                    scheduled_count += 1
                    
            except Exception as e:
                errors.append(f"Failed to process draft {draft['id']}: {str(e)}")
        
        success = published_count > 0 or scheduled_count > 0
        message = f"Successfully processed {published_count + scheduled_count} posts"
        
        return PublishResponse(
            success=success,
            message=message,
            published_count=published_count,
            scheduled_count=scheduled_count,
            errors=errors
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish posts: {str(e)}"
        )

@router.post("/schedule")
async def schedule_posts(
    publish_data: PublishRequest,
    schedule_for: datetime,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Schedule posts for later publishing"""
    try:
        # Get drafts for the group
        response = db.table('post_drafts').select('*').eq('user_id', current_user["id"]).eq('group_name', publish_data.group_name).eq('status', 'draft').execute()
        
        drafts = response.data
        if not drafts:
            return PublishResponse(
                success=False,
                message="No drafts found for scheduling",
                errors=["No drafts in draft status found"]
            )
        
        scheduled_count = 0
        errors = []
        
        for draft in drafts:
            try:
                # Update draft with schedule info
                update_data = {
                    "status": "scheduled",
                    "schedule_date": schedule_for.isoformat()
                }
                update_response = db.table('post_drafts').update(update_data).eq('id', draft['id']).execute()
                scheduled_count += 1
                    
            except Exception as e:
                errors.append(f"Failed to schedule draft {draft['id']}: {str(e)}")
        
        success = scheduled_count > 0
        message = f"Successfully scheduled {scheduled_count} posts"
        
        return PublishResponse(
            success=success,
            message=message,
            scheduled_count=scheduled_count,
            errors=errors
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to schedule posts: {str(e)}"
        )