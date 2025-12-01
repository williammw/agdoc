from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
import json
from datetime import datetime, timedelta
from app.dependencies.auth import get_current_user
from app.utils.database import get_db
from app.models.content import (
    PostGroup, PostGroupCreate, PostGroupUpdate, PostGroupWithDrafts,
    PostDraft, PostDraftCreate, PostDraftUpdate,
    PublishedPost, PublishedPostCreate,
    MediaFile, MediaFileCreate, MediaFileUpdate,
    ScheduledJob, ScheduledJobCreate,
    PublishRequest, PublishResponse,
    SaveDraftRequest, SaveDraftResponse,
    BulkPostDraftCreate, BulkPostDraftUpdate,
    PostStatus, JobStatus, ProcessingStatus
)

router = APIRouter(
    prefix="/api/v1/content",
    tags=["content"],
    dependencies=[Depends(get_current_user)]
)

# Create database dependency with admin access
db_admin = get_db(admin_access=True)

# Post Groups endpoints
@router.get("/groups", response_model=List[PostGroupWithDrafts])
async def get_post_groups(
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Get all post groups for the current user with their drafts"""
    try:
        # Get post groups
        groups_query = """
            SELECT id, user_id, name, content_mode, created_at, updated_at
            FROM post_groups 
            WHERE user_id = $1 
            ORDER BY created_at DESC
        """
        groups_rows = await db.fetch(groups_query, current_user["user_id"])
        
        groups = []
        for group_row in groups_rows:
            # Get drafts for this group
            drafts_query = """
                SELECT id, post_group_id, user_id, platform, account_id, account_key,
                       content, hashtags, mentions, media_ids, youtube_title, 
                       youtube_description, youtube_tags, location, link,
                       schedule_date, schedule_time, timezone, status,
                       created_at, updated_at
                FROM post_drafts 
                WHERE post_group_id = $1 
                ORDER BY created_at ASC
            """
            drafts_rows = await db.fetch(drafts_query, group_row["id"])
            
            drafts = [PostDraft(**dict(draft_row)) for draft_row in drafts_rows]
            group_with_drafts = PostGroupWithDrafts(**dict(group_row), drafts=drafts)
            groups.append(group_with_drafts)
        
        return groups
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch post groups: {str(e)}"
        )

@router.post("/groups", response_model=PostGroup)
async def create_post_group(
    group_data: PostGroupCreate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Create a new post group"""
    try:
        query = """
            INSERT INTO post_groups (user_id, name, content_mode)
            VALUES ($1, $2, $3)
            RETURNING id, user_id, name, content_mode, created_at, updated_at
        """
        row = await db.fetchrow(
            query, 
            current_user["user_id"], 
            group_data.name, 
            group_data.content_mode
        )
        return PostGroup(**dict(row))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create post group: {str(e)}"
        )

@router.get("/groups/{group_id}", response_model=PostGroupWithDrafts)
async def get_post_group(
    group_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Get a specific post group with its drafts"""
    try:
        # Get the group
        group_query = """
            SELECT id, user_id, name, content_mode, created_at, updated_at
            FROM post_groups 
            WHERE id = $1 AND user_id = $2
        """
        group_row = await db.fetchrow(group_query, group_id, current_user["user_id"])
        
        if not group_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post group not found"
            )
        
        # Get drafts for this group
        drafts_query = """
            SELECT id, post_group_id, user_id, platform, account_id, account_key,
                   content, hashtags, mentions, media_ids, youtube_title, 
                   youtube_description, youtube_tags, location, link,
                   schedule_date, schedule_time, timezone, status,
                   created_at, updated_at
            FROM post_drafts 
            WHERE post_group_id = $1 
            ORDER BY created_at ASC
        """
        drafts_rows = await db.fetch(drafts_query, group_id)
        
        drafts = [PostDraft(**dict(draft_row)) for draft_row in drafts_rows]
        return PostGroupWithDrafts(**dict(group_row), drafts=drafts)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch post group: {str(e)}"
        )

@router.put("/groups/{group_id}", response_model=PostGroup)
async def update_post_group(
    group_id: UUID,
    group_data: PostGroupUpdate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Update a post group"""
    try:
        # Build dynamic update query
        updates = []
        params = [group_id, current_user["user_id"]]
        param_count = 2
        
        if group_data.name is not None:
            param_count += 1
            updates.append(f"name = ${param_count}")
            params.append(group_data.name)
        
        if group_data.content_mode is not None:
            param_count += 1
            updates.append(f"content_mode = ${param_count}")
            params.append(group_data.content_mode)
        
        if not updates:
            # No updates provided, just return the current group
            return await get_post_group(group_id, current_user, db)
        
        query = f"""
            UPDATE post_groups 
            SET {', '.join(updates)}
            WHERE id = $1 AND user_id = $2
            RETURNING id, user_id, name, content_mode, created_at, updated_at
        """
        
        row = await db.fetchrow(query, *params)
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post group not found"
            )
        
        return PostGroup(**dict(row))
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
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Delete a post group and all its drafts"""
    try:
        # Check if group exists and belongs to user
        check_query = """
            SELECT id FROM post_groups 
            WHERE id = $1 AND user_id = $2
        """
        exists = await db.fetchrow(check_query, group_id, current_user["user_id"])
        
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post group not found"
            )
        
        # Delete the group (cascades to drafts)
        delete_query = """
            DELETE FROM post_groups 
            WHERE id = $1 AND user_id = $2
        """
        await db.execute(delete_query, group_id, current_user["user_id"])
        
        return {"message": "Post group deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete post group: {str(e)}"
        )

# Post Drafts endpoints
@router.post("/drafts", response_model=PostDraft)
async def create_draft(
    draft_data: PostDraftCreate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Create a new post draft"""
    try:
        query = """
            INSERT INTO post_drafts (
                post_group_id, user_id, platform, account_id, account_key,
                content, hashtags, mentions, media_ids, youtube_title,
                youtube_description, youtube_tags, location, link,
                schedule_date, schedule_time, timezone
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
            RETURNING id, post_group_id, user_id, platform, account_id, account_key,
                      content, hashtags, mentions, media_ids, youtube_title,
                      youtube_description, youtube_tags, location, link,
                      schedule_date, schedule_time, timezone, status,
                      created_at, updated_at
        """
        
        row = await db.fetchrow(
            query,
            draft_data.post_group_id,
            current_user["user_id"],
            draft_data.platform,
            draft_data.account_id,
            draft_data.account_key,
            draft_data.content,
            json.dumps(draft_data.hashtags),
            json.dumps(draft_data.mentions),
            json.dumps(draft_data.media_ids),
            draft_data.youtube_title,
            draft_data.youtube_description,
            json.dumps(draft_data.youtube_tags),
            draft_data.location,
            draft_data.link,
            draft_data.schedule_date,
            draft_data.schedule_time,
            draft_data.timezone
        )
        
        return PostDraft(**dict(row))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create draft: {str(e)}"
        )

@router.put("/drafts/{draft_id}", response_model=PostDraft)
async def update_draft(
    draft_id: UUID,
    draft_data: PostDraftUpdate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Update a post draft"""
    try:
        # Build dynamic update query
        updates = []
        params = [draft_id, current_user["user_id"]]
        param_count = 2
        
        update_fields = {
            'platform': draft_data.platform,
            'account_id': draft_data.account_id,
            'account_key': draft_data.account_key,
            'content': draft_data.content,
            'youtube_title': draft_data.youtube_title,
            'youtube_description': draft_data.youtube_description,
            'location': draft_data.location,
            'link': draft_data.link,
            'schedule_date': draft_data.schedule_date,
            'schedule_time': draft_data.schedule_time,
            'timezone': draft_data.timezone,
            'status': draft_data.status
        }
        
        for field, value in update_fields.items():
            if value is not None:
                param_count += 1
                updates.append(f"{field} = ${param_count}")
                params.append(value)
        
        # Handle JSON fields
        json_fields = {
            'hashtags': draft_data.hashtags,
            'mentions': draft_data.mentions,
            'media_ids': draft_data.media_ids,
            'youtube_tags': draft_data.youtube_tags
        }
        
        for field, value in json_fields.items():
            if value is not None:
                param_count += 1
                updates.append(f"{field} = ${param_count}")
                params.append(json.dumps(value))
        
        if not updates:
            # No updates provided, return current draft
            query = """
                SELECT id, post_group_id, user_id, platform, account_id, account_key,
                       content, hashtags, mentions, media_ids, youtube_title,
                       youtube_description, youtube_tags, location, link,
                       schedule_date, schedule_time, timezone, status,
                       created_at, updated_at
                FROM post_drafts 
                WHERE id = $1 AND user_id = $2
            """
            row = await db.fetchrow(query, draft_id, current_user["user_id"])
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Draft not found"
                )
            return PostDraft(**dict(row))
        
        query = f"""
            UPDATE post_drafts 
            SET {', '.join(updates)}
            WHERE id = $1 AND user_id = $2
            RETURNING id, post_group_id, user_id, platform, account_id, account_key,
                      content, hashtags, mentions, media_ids, youtube_title,
                      youtube_description, youtube_tags, location, link,
                      schedule_date, schedule_time, timezone, status,
                      created_at, updated_at
        """
        
        row = await db.fetchrow(query, *params)
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft not found"
            )
        
        return PostDraft(**dict(row))
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
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Delete a post draft"""
    try:
        query = """
            DELETE FROM post_drafts 
            WHERE id = $1 AND user_id = $2
        """
        result = await db.execute(query, draft_id, current_user["user_id"])
        
        if result == "DELETE 0":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft not found"
            )
        
        return {"message": "Draft deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete draft: {str(e)}"
        )

# Publishing endpoints
@router.post("/publish", response_model=PublishResponse)
async def publish_posts(
    publish_data: PublishRequest,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Publish or schedule posts from a post group"""
    try:
        # Get the post group and verify ownership
        group_query = """
            SELECT id FROM post_groups 
            WHERE id = $1 AND user_id = $2
        """
        group = await db.fetchrow(group_query, publish_data.post_group_id, current_user["user_id"])
        
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post group not found"
            )
        
        # Get all drafts in the group that are ready to publish
        drafts_query = """
            SELECT id, platform, account_id, account_key, content, hashtags, mentions,
                   media_ids, youtube_title, youtube_description, youtube_tags,
                   location, link, schedule_date, schedule_time, timezone
            FROM post_drafts 
            WHERE post_group_id = $1 AND status = 'draft'
        """
        drafts = await db.fetch(drafts_query, publish_data.post_group_id)
        
        if not drafts:
            return PublishResponse(
                success=False,
                message="No drafts found ready for publishing",
                errors=["No drafts in draft status found"]
            )
        
        published_posts = []
        scheduled_jobs = []
        errors = []
        
        for draft in drafts:
            try:
                if publish_data.immediate:
                    # Immediate publishing
                    # TODO: Implement actual platform publishing logic here
                    # For now, we'll create a published post record
                    
                    content_snapshot = {
                        "content": draft["content"],
                        "hashtags": draft["hashtags"],
                        "mentions": draft["mentions"],
                        "media_ids": draft["media_ids"],
                        "youtube_title": draft["youtube_title"],
                        "youtube_description": draft["youtube_description"],
                        "youtube_tags": draft["youtube_tags"],
                        "location": draft["location"],
                        "link": draft["link"]
                    }
                    
                    # Create published post record
                    publish_query = """
                        INSERT INTO published_posts (
                            post_draft_id, post_group_id, user_id, platform, account_id,
                            content_snapshot, platform_post_id, platform_url
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        RETURNING id
                    """
                    
                    published_id = await db.fetchval(
                        publish_query,
                        draft["id"],
                        publish_data.post_group_id,
                        current_user["user_id"],
                        draft["platform"],
                        draft["account_id"],
                        json.dumps(content_snapshot),
                        f"mock_{uuid.uuid4()}",  # Mock platform post ID
                        f"https://{draft['platform']}.com/post/mock_{uuid.uuid4()}"  # Mock URL
                    )
                    
                    # Update draft status
                    await db.execute(
                        "UPDATE post_drafts SET status = 'published' WHERE id = $1",
                        draft["id"]
                    )
                    
                    published_posts.append(published_id)
                
                else:
                    # Scheduled publishing
                    schedule_time = publish_data.schedule_for or datetime.now() + timedelta(hours=1)
                    
                    # Create scheduled job
                    job_query = """
                        INSERT INTO scheduled_jobs (post_draft_id, user_id, scheduled_for)
                        VALUES ($1, $2, $3)
                        RETURNING id
                    """
                    
                    job_id = await db.fetchval(
                        job_query,
                        draft["id"],
                        current_user["user_id"],
                        schedule_time
                    )
                    
                    # Update draft status
                    await db.execute(
                        "UPDATE post_drafts SET status = 'scheduled' WHERE id = $1",
                        draft["id"]
                    )
                    
                    scheduled_jobs.append(job_id)
                    
            except Exception as e:
                errors.append(f"Failed to process draft {draft['id']}: {str(e)}")
        
        success = len(published_posts) > 0 or len(scheduled_jobs) > 0
        message = "Posts processed successfully" if success else "Failed to process posts"
        
        return PublishResponse(
            success=success,
            message=message,
            published_posts=published_posts,
            scheduled_jobs=scheduled_jobs,
            errors=errors
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish posts: {str(e)}"
        )

@router.post("/save-drafts", response_model=SaveDraftResponse)
async def save_drafts(
    save_data: SaveDraftRequest,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Save multiple drafts for a post group"""
    try:
        # Verify post group exists and belongs to user
        group_query = """
            SELECT id FROM post_groups 
            WHERE id = $1 AND user_id = $2
        """
        group = await db.fetchrow(group_query, save_data.post_group_id, current_user["user_id"])
        
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post group not found"
            )
        
        saved_drafts = []
        errors = []
        
        for draft_data in save_data.drafts:
            try:
                query = """
                    INSERT INTO post_drafts (
                        post_group_id, user_id, platform, account_id, account_key,
                        content, hashtags, mentions, media_ids, youtube_title,
                        youtube_description, youtube_tags, location, link,
                        schedule_date, schedule_time, timezone
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                    RETURNING id
                """
                
                draft_id = await db.fetchval(
                    query,
                    draft_data.post_group_id,
                    current_user["user_id"],
                    draft_data.platform,
                    draft_data.account_id,
                    draft_data.account_key,
                    draft_data.content,
                    json.dumps(draft_data.hashtags),
                    json.dumps(draft_data.mentions),
                    json.dumps(draft_data.media_ids),
                    draft_data.youtube_title,
                    draft_data.youtube_description,
                    json.dumps(draft_data.youtube_tags),
                    draft_data.location,
                    draft_data.link,
                    draft_data.schedule_date,
                    draft_data.schedule_time,
                    draft_data.timezone
                )
                
                saved_drafts.append(draft_id)
                
            except Exception as e:
                errors.append(f"Failed to save draft for platform {draft_data.platform}: {str(e)}")
        
        success = len(saved_drafts) > 0
        message = f"Saved {len(saved_drafts)} drafts successfully" if success else "Failed to save drafts"
        
        return SaveDraftResponse(
            success=success,
            message=message,
            saved_drafts=saved_drafts,
            errors=errors
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save drafts: {str(e)}"
        )

# Published posts endpoints
@router.get("/published", response_model=List[PublishedPost])
async def get_published_posts(
    limit: int = 50,
    offset: int = 0,
    platform: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Get published posts for the current user"""
    try:
        where_clause = "WHERE user_id = $1"
        params = [current_user["user_id"]]
        
        if platform:
            where_clause += " AND platform = $2"
            params.append(platform)
            params.extend([limit, offset])
        else:
            params.extend([limit, offset])
        
        query = f"""
            SELECT id, post_draft_id, post_group_id, user_id, platform, account_id,
                   content_snapshot, platform_post_id, platform_url, platform_response,
                   engagement_stats, published_at, created_at, updated_at
            FROM published_posts 
            {where_clause}
            ORDER BY published_at DESC 
            LIMIT ${len(params)-1} OFFSET ${len(params)}
        """
        
        rows = await db.fetch(query, *params)
        return [PublishedPost(**dict(row)) for row in rows]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch published posts: {str(e)}"
        )

# Scheduled jobs endpoints
@router.get("/scheduled", response_model=List[ScheduledJob])
async def get_scheduled_jobs(
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_database_connection)
):
    """Get scheduled jobs for the current user"""
    try:
        query = """
            SELECT id, post_draft_id, user_id, job_type, scheduled_for, status,
                   attempts, max_attempts, error_message, result,
                   created_at, updated_at
            FROM scheduled_jobs 
            WHERE user_id = $1 AND status IN ('pending', 'processing')
            ORDER BY scheduled_for ASC
        """
        
        rows = await db.fetch(query, current_user["user_id"])
        return [ScheduledJob(**dict(row)) for row in rows]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch scheduled jobs: {str(e)}"
        )