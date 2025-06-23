from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
import json
import logging
from datetime import datetime, timezone
from app.dependencies.auth import get_current_user
from app.utils.database import get_db

logger = logging.getLogger(__name__)

try:
    from app.services.platform_publisher import PlatformPublisher, PublishStatus
    logger.info("Successfully imported PlatformPublisher")
except ImportError as e:
    logger.error(f"Failed to import PlatformPublisher: {e}")
    PlatformPublisher = None
    PublishStatus = None

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
    failed_count: int = 0
    errors: List[str] = Field(default_factory=list)
    platform_results: List[Dict[str, Any]] = Field(default_factory=list)

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
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Publish a post to social media platforms"""
    try:
        # Debug: Log current user info
        logger.warning(f"🚀 PUBLISH ENDPOINT CALLED - Publishing post {post_id} for user: {current_user}")
        print(f"🚀 PUBLISH ENDPOINT CALLED - Publishing post {post_id}")
        
        # Get the post
        post = await get_post(post_id, current_user, db)
        
        if not post:
            return PublishResponse(
                success=False,
                message="Post not found",
                errors=["Post not found"]
            )
        
        # Debug: Log the post data to understand its structure
        logger.warning(f"📄 Retrieved post data keys: {list(post.keys()) if isinstance(post, dict) else 'Not a dict'}")
        logger.warning(f"📱 Post platforms: {post.get('platforms', [])}")
        logger.warning(f"📁 Post media_files: {post.get('media_files', [])}")
        logger.warning(f"📝 Post content_mode: {post.get('content_mode', 'NOT FOUND')}")
        
        platforms = post.get('platforms', [])
        if not platforms:
            return PublishResponse(
                success=False,
                message="No platforms selected for publishing",
                errors=["No platforms configured"]
            )
        
        # Check if this is immediate or scheduled publishing
        if publish_data.immediate:
            # Immediate publishing
            return await _publish_immediately(post_id, post, current_user, db)
        else:
            # Scheduled publishing
            schedule_date = publish_data.schedule_for or datetime.now(timezone.utc)
            return await _schedule_post(post_id, post, schedule_date, current_user, db, background_tasks)
                
    except Exception as e:
        logger.error(f"Error in publish_post: {str(e)}")
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

# Helper functions for publishing

async def _publish_immediately(
    post_id: UUID, 
    post: dict, 
    current_user: dict, 
    db
) -> PublishResponse:
    """Handle immediate publishing to all platforms"""
    try:
        # Update post status to publishing
        await update_post(
            post_id, 
            PostUpdate(status="publishing"), 
            current_user, 
            db
        )
        
        # Get platforms from the post dict
        platforms = post.get('platforms', [])
        if not platforms:
            return PublishResponse(
                success=False,
                message="No platforms configured for this post",
                errors=["No platforms found in post data"]
            )
        
        # Initialize publishing results tracking
        await _create_publishing_results_records(post_id, platforms, db)
        
        # Check if PlatformPublisher is available
        if PlatformPublisher is None:
            logger.error("PlatformPublisher not available - import failed")
            return PublishResponse(
                success=False,
                message="Publishing service not available",
                errors=["Platform publisher import failed"]
            )
        
        # Initialize platform publisher
        logger.warning(f"🔧 Initializing PlatformPublisher...")
        publisher = PlatformPublisher()
        
        # Prepare content data for publishing
        content_data = {
            'content_mode': post.get('content_mode', 'universal'),
            'universal_content': post.get('universal_content', ''),
            'universal_metadata': post.get('universal_metadata', {}),
            'platform_content': post.get('platform_content', {}),
            'media_files': post.get('media_files', [])
        }
        
        logger.warning(f"📤 About to publish to {len(platforms)} platforms")
        logger.warning(f"📤 Content data: content_mode={content_data['content_mode']}")
        logger.warning(f"📤 Media files count: {len(content_data['media_files'])}")
        logger.warning(f"📤 Media files: {content_data['media_files']}")
        
        # Publish to all platforms
        results = await publisher.publish_to_platforms(
            current_user["id"], 
            platforms, 
            content_data
        )
        
        # Process results and update database
        published_count = 0
        failed_count = 0
        errors = []
        platform_results = []
        
        for result in results:
            platform_results.append({
                "platform": result.platform,
                "status": result.status.value,
                "platform_post_id": result.platform_post_id,
                "error_message": result.error_message
            })
            
            if result.status == PublishStatus.SUCCESS:
                published_count += 1
                await _update_publishing_result(
                    post_id, result.platform, "success", 
                    result.platform_post_id, None, result.metadata, db
                )
            else:
                failed_count += 1
                errors.append(f"{result.platform}: {result.error_message}")
                await _update_publishing_result(
                    post_id, result.platform, "failed", 
                    None, result.error_message, result.metadata, db
                )
        
        # Update final post status
        if published_count > 0 and failed_count == 0:
            final_status = "published"
        elif published_count > 0 and failed_count > 0:
            final_status = "published"  # Partial success still counts as published
        else:
            final_status = "failed"
        
        await update_post(
            post_id, 
            PostUpdate(status=final_status), 
            current_user, 
            db
        )
        
        success = published_count > 0
        message = f"Published to {published_count}/{len(platforms)} platforms"
        if failed_count > 0:
            message += f", {failed_count} failed"
        
        return PublishResponse(
            success=success,
            message=message,
            published_count=published_count,
            failed_count=failed_count,
            errors=errors,
            platform_results=platform_results
        )
        
    except Exception as e:
        logger.error(f"Error in immediate publishing: {str(e)}")
        # Update post status to failed
        await update_post(
            post_id, 
            PostUpdate(status="failed"), 
            current_user, 
            db
        )
        
        return PublishResponse(
            success=False,
            message="Publishing failed",
            errors=[str(e)]
        )

async def _schedule_post(
    post_id: UUID, 
    post: dict, 
    schedule_date: datetime, 
    current_user: dict, 
    db,
    background_tasks: BackgroundTasks
) -> PublishResponse:
    """Handle scheduled publishing"""
    try:
        # Update post status and schedule date
        await update_post(
            post_id, 
            PostUpdate(status="scheduled", schedule_date=schedule_date), 
            current_user, 
            db
        )
        
        # Get platforms from the post dict
        platforms = post.get('platforms', [])
        platform_count = len(platforms)
        
        # Create scheduled post record
        scheduled_data = {
            "post_id": str(post_id),
            "user_id": current_user["id"],
            "scheduled_for": schedule_date.isoformat(),
            "status": "pending"
        }
        
        db.table('scheduled_posts').insert(scheduled_data).execute()
        
        # Add background task to process scheduled posts
        background_tasks.add_task(_process_scheduled_posts)
        
        return PublishResponse(
            success=True,
            message=f"Post scheduled for {schedule_date.strftime('%Y-%m-%d %H:%M UTC')} on {platform_count} platform(s)",
            scheduled_count=platform_count
        )
        
    except Exception as e:
        logger.error(f"Error in scheduled publishing: {str(e)}")
        return PublishResponse(
            success=False,
            message="Scheduling failed",
            errors=[str(e)]
        )

async def _create_publishing_results_records(post_id: UUID, platforms: List[Dict[str, Any]], db):
    """Create initial publishing result records"""
    try:
        records = []
        logger.info(f"Creating publishing records for {len(platforms)} platforms")
        
        for platform in platforms:
            logger.info(f"Processing platform: {platform}")
            records.append({
                "post_id": str(post_id),
                "platform": platform.get("provider", "unknown"),
                "platform_account_id": platform.get("accountId", "unknown"),
                "status": "pending"
            })
        
        if records:
            logger.info(f"Inserting {len(records)} publishing result records")
            result = db.table('post_publishing_results').insert(records).execute()
            logger.info(f"Insert result: {result}")
            
    except Exception as e:
        logger.error(f"Error creating publishing result records: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

async def _update_publishing_result(
    post_id: UUID, 
    platform: str, 
    status: str, 
    platform_post_id: Optional[str],
    error_message: Optional[str],
    metadata: Optional[Dict[str, Any]],
    db
):
    """Update publishing result record"""
    try:
        update_data = {
            "status": status,
            "platform_post_id": platform_post_id,
            "error_message": error_message,
            "metadata": metadata or {},
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        if status == "success":
            update_data["published_at"] = datetime.now(timezone.utc).isoformat()
        
        db.table('post_publishing_results').update(update_data).eq(
            'post_id', str(post_id)
        ).eq('platform', platform).execute()
        
    except Exception as e:
        logger.error(f"Error updating publishing result: {str(e)}")

async def _process_scheduled_posts():
    """Background task to process scheduled posts"""
    try:
        from app.services.scheduler import process_scheduled_posts
        await process_scheduled_posts()
    except Exception as e:
        logger.error(f"Error in background task: {str(e)}")

# Publishing status endpoint
@router.get("/{post_id}/publishing-status")
async def get_publishing_status(
    post_id: UUID,
    current_user: dict = Depends(get_current_user),
    db = Depends(db_admin)
):
    """Get detailed publishing status for a post"""
    try:
        # Get publishing results
        response = db.table('post_publishing_results').select('*').eq(
            'post_id', str(post_id)
        ).execute()
        
        return {
            "success": True,
            "post_id": str(post_id),
            "platform_results": response.data
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch publishing status: {str(e)}"
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
            'publishing': 0,
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