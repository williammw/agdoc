"""
Enterprise-level Post Scheduling API Router
Handles scheduling, queue management, analytics, and background processing
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import uuid
import json
import logging
from sqlalchemy import and_, or_, desc, func, text
from sqlalchemy.orm import Session

from app.utils.database import get_db
from app.dependencies.auth import get_current_user
from app.services.platform_publisher import PlatformPublisher
from app.utils.timezone import convert_timezone, get_user_timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scheduling", tags=["scheduling"])

# Pydantic Models
class ScheduleRequest(BaseModel):
    post_id: str = Field(..., description="UUID of the post to schedule")
    scheduled_for: datetime = Field(..., description="UTC datetime when to publish")
    timezone: Optional[str] = Field(None, description="User's timezone for reference")

class RescheduleRequest(BaseModel):
    queue_id: str = Field(..., description="UUID of the scheduling queue item")
    new_scheduled_time: datetime = Field(..., description="New UTC datetime when to publish")
    timezone: Optional[str] = Field(None, description="User's timezone for reference")

class CancelScheduleRequest(BaseModel):
    post_id: str = Field(..., description="UUID of the post to cancel scheduling")
    reason: Optional[str] = Field(None, description="Reason for cancellation")

class BulkScheduleRequest(BaseModel):
    post_ids: List[str] = Field(..., description="List of post UUIDs to schedule")
    schedule_times: List[datetime] = Field(..., description="List of UTC datetimes for each post")
    timezone: Optional[str] = Field(None, description="User's timezone for reference")

class SchedulingAnalyticsResponse(BaseModel):
    total_scheduled: int
    total_published: int
    total_failed: int
    success_rate: float
    average_delay_minutes: float
    platform_breakdown: Dict[str, Dict[str, int]]
    recent_failures: List[Dict[str, Any]]

class QueueItem(BaseModel):
    id: str
    post_id: str
    post_name: str
    platforms: List[str]
    scheduled_for: datetime
    status: str
    attempts: int
    last_attempt_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime

class OptimalTimeSlot(BaseModel):
    platform: str
    day_of_week: int  # 0=Monday, 6=Sunday
    hour: int
    engagement_score: float
    timezone: str = "UTC"

# Database Helpers
def get_post_with_user_check(db: Session, post_id: str, user: Dict[str, Any]):
    """Get post and verify user ownership"""
    from app.models.post import Post
    
    post = db.execute(text("""
        SELECT p.*, u.id as user_db_id
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = :post_id AND u.firebase_uid = :firebase_uid
    """), {
        "post_id": post_id,
        "firebase_uid": user.get("firebase_uid")
    }).first()
    
    if not post:
        raise HTTPException(status_code=404, detail="Post not found or access denied")
    
    return post

def get_scheduling_queue_item(db: Session, queue_id: str, user: Dict[str, Any]):
    """Get scheduling queue item and verify user ownership"""
    queue_item = db.execute(text("""
        SELECT sq.*, p.name as post_name, p.platforms, u.id as user_db_id
        FROM scheduling_queue sq
        JOIN posts p ON sq.post_id = p.id
        JOIN users u ON sq.user_id = u.id
        WHERE sq.id = :queue_id AND u.firebase_uid = :firebase_uid
    """), {
        "queue_id": queue_id,
        "firebase_uid": user.get("firebase_uid")
    }).first()
    
    if not queue_item:
        raise HTTPException(status_code=404, detail="Scheduled post not found or access denied")
    
    return queue_item

# API Endpoints

@router.post("/schedule", summary="Schedule a post for publishing")
async def schedule_post(
    request: ScheduleRequest,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Schedule a post for future publishing with enterprise-level validation
    """
    try:
        # Validate post exists and user has access
        post = get_post_with_user_check(db, request.post_id, user)
        
        # Validate schedule time (must be at least 5 minutes in future)
        now = datetime.utcnow()
        min_schedule_time = now + timedelta(minutes=5)
        
        if request.scheduled_for <= min_schedule_time:
            raise HTTPException(
                status_code=400, 
                detail="Schedule time must be at least 5 minutes in the future"
            )
        
        # Maximum 6 months in future
        max_schedule_time = now + timedelta(days=180)
        if request.scheduled_for > max_schedule_time:
            raise HTTPException(
                status_code=400,
                detail="Schedule time cannot be more than 6 months in the future"
            )
        
        # Update post with schedule date
        db.execute(text("""
            UPDATE posts 
            SET schedule_date = :schedule_date, 
                status = 'scheduled',
                updated_at = NOW()
            WHERE id = :post_id
        """), {
            "schedule_date": request.scheduled_for,
            "post_id": request.post_id
        })
        
        # The trigger will automatically handle scheduling_queue insertion
        db.commit()
        
        logger.info(f"Post {request.post_id} scheduled for {request.scheduled_for} by user {user.get('firebase_uid')}")
        
        return {
            "success": True,
            "message": "Post scheduled successfully",
            "post_id": request.post_id,
            "scheduled_for": request.scheduled_for,
            "timezone": request.timezone or "UTC"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scheduling post {request.post_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to schedule post")

@router.put("/reschedule", summary="Reschedule a post")
async def reschedule_post(
    request: RescheduleRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reschedule an existing scheduled post
    """
    try:
        # Get and validate queue item
        queue_item = get_scheduling_queue_item(db, request.queue_id, user)
        
        # Validate new schedule time
        now = datetime.utcnow()
        min_schedule_time = now + timedelta(minutes=5)
        
        if request.new_scheduled_time <= min_schedule_time:
            raise HTTPException(
                status_code=400,
                detail="New schedule time must be at least 5 minutes in the future"
            )
        
        # Update both posts and scheduling_queue tables
        db.execute(text("""
            UPDATE posts 
            SET schedule_date = :new_schedule_time, updated_at = NOW()
            WHERE id = :post_id
        """), {
            "new_schedule_time": request.new_scheduled_time,
            "post_id": queue_item.post_id
        })
        
        db.execute(text("""
            UPDATE scheduling_queue 
            SET scheduled_for = :new_schedule_time,
                status = 'pending',
                attempts = 0,
                error_message = NULL,
                updated_at = NOW()
            WHERE id = :queue_id
        """), {
            "new_schedule_time": request.new_scheduled_time,
            "queue_id": request.queue_id
        })
        
        db.commit()
        
        logger.info(f"Post {queue_item.post_id} rescheduled to {request.new_scheduled_time}")
        
        return {
            "success": True,
            "message": "Post rescheduled successfully",
            "queue_id": request.queue_id,
            "post_id": queue_item.post_id,
            "old_scheduled_time": queue_item.scheduled_for,
            "new_scheduled_time": request.new_scheduled_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rescheduling queue item {request.queue_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to reschedule post")

@router.delete("/cancel", summary="Cancel a scheduled post")
async def cancel_scheduled_post(
    request: CancelScheduleRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a scheduled post and remove from queue
    """
    try:
        # Validate post exists and user has access
        post = get_post_with_user_check(db, request.post_id, user)
        
        # Update post status to draft and remove schedule
        db.execute(text("""
            UPDATE posts 
            SET schedule_date = NULL, 
                status = 'draft',
                updated_at = NOW()
            WHERE id = :post_id
        """), {"post_id": request.post_id})
        
        # Remove from scheduling queue
        db.execute(text("""
            DELETE FROM scheduling_queue 
            WHERE post_id = :post_id
        """), {"post_id": request.post_id})
        
        # Log cancellation reason if provided
        if request.reason:
            db.execute(text("""
                INSERT INTO scheduling_analytics (
                    user_id, post_id, platform, scheduled_time, status, error_type
                )
                SELECT :user_id, :post_id, 'all', NOW(), 'cancelled', :reason
            """), {
                "user_id": post.user_db_id,
                "post_id": request.post_id,
                "reason": f"User cancelled: {request.reason}"
            })
        
        db.commit()
        
        logger.info(f"Scheduled post {request.post_id} cancelled by user {user.get('firebase_uid')}")
        
        return {
            "success": True,
            "message": "Scheduled post cancelled successfully",
            "post_id": request.post_id,
            "reason": request.reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling scheduled post {request.post_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to cancel scheduled post")

@router.get("/queue", summary="Get user's scheduling queue")
async def get_scheduling_queue(
    status: Optional[str] = Query(None, description="Filter by status: pending, processing, completed, failed"),
    platform: Optional[str] = Query(None, description="Filter by platform"),
    limit: int = Query(50, ge=1, le=100, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get user's scheduling queue with filtering and pagination
    """
    try:
        # Build query with filters
        where_conditions = ["u.firebase_uid = :firebase_uid"]
        params = {"firebase_uid": user.firebase_uid}
        
        if status:
            where_conditions.append("sq.status = :status")
            params["status"] = status
            
        if platform:
            where_conditions.append("p.platforms::jsonb ? :platform")
            params["platform"] = platform
        
        where_clause = " AND ".join(where_conditions)
        
        # Get queue items
        queue_items = db.execute(text(f"""
            SELECT 
                sq.id,
                sq.post_id,
                p.name as post_name,
                p.platforms,
                sq.scheduled_for,
                sq.status,
                sq.attempts,
                sq.last_attempt_at,
                sq.error_message,
                sq.created_at
            FROM scheduling_queue sq
            JOIN posts p ON sq.post_id = p.id
            JOIN users u ON sq.user_id = u.id
            WHERE {where_clause}
            ORDER BY sq.scheduled_for ASC
            LIMIT :limit OFFSET :offset
        """), {**params, "limit": limit, "offset": offset}).fetchall()
        
        # Get total count
        total_count = db.execute(text(f"""
            SELECT COUNT(*)
            FROM scheduling_queue sq
            JOIN posts p ON sq.post_id = p.id
            JOIN users u ON sq.user_id = u.id
            WHERE {where_clause}
        """), params).scalar()
        
        items = []
        for item in queue_items:
            platforms = json.loads(item.platforms) if item.platforms else []
            items.append(QueueItem(
                id=str(item.id),
                post_id=str(item.post_id),
                post_name=item.post_name,
                platforms=platforms,
                scheduled_for=item.scheduled_for,
                status=item.status,
                attempts=item.attempts,
                last_attempt_at=item.last_attempt_at,
                error_message=item.error_message,
                created_at=item.created_at
            ))
        
        return {
            "items": items,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total_count
        }
        
    except Exception as e:
        logger.error(f"Error fetching scheduling queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch scheduling queue")

@router.post("/bulk-schedule", summary="Schedule multiple posts")
async def bulk_schedule_posts(
    request: BulkScheduleRequest,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Schedule multiple posts at once with validation
    """
    try:
        if len(request.post_ids) != len(request.schedule_times):
            raise HTTPException(
                status_code=400,
                detail="Number of post IDs must match number of schedule times"
            )
        
        if len(request.post_ids) > 50:
            raise HTTPException(
                status_code=400,
                detail="Cannot schedule more than 50 posts at once"
            )
        
        now = datetime.utcnow()
        min_schedule_time = now + timedelta(minutes=5)
        max_schedule_time = now + timedelta(days=180)
        
        scheduled_posts = []
        errors = []
        
        for i, (post_id, schedule_time) in enumerate(zip(request.post_ids, request.schedule_times)):
            try:
                # Validate post exists and user has access
                post = get_post_with_user_check(db, post_id, user)
                
                # Validate schedule time
                if schedule_time <= min_schedule_time:
                    errors.append(f"Post {i+1}: Schedule time must be at least 5 minutes in the future")
                    continue
                    
                if schedule_time > max_schedule_time:
                    errors.append(f"Post {i+1}: Schedule time cannot be more than 6 months in the future")
                    continue
                
                # Update post
                db.execute(text("""
                    UPDATE posts 
                    SET schedule_date = :schedule_date, 
                        status = 'scheduled',
                        updated_at = NOW()
                    WHERE id = :post_id
                """), {
                    "schedule_date": schedule_time,
                    "post_id": post_id
                })
                
                scheduled_posts.append({
                    "post_id": post_id,
                    "post_name": post.name,
                    "scheduled_for": schedule_time
                })
                
            except HTTPException as e:
                errors.append(f"Post {i+1}: {e.detail}")
            except Exception as e:
                errors.append(f"Post {i+1}: {str(e)}")
        
        db.commit()
        
        logger.info(f"Bulk scheduled {len(scheduled_posts)} posts for user {user.get('firebase_uid')}")
        
        return {
            "success": True,
            "message": f"Successfully scheduled {len(scheduled_posts)} posts",
            "scheduled_posts": scheduled_posts,
            "errors": errors,
            "total_requested": len(request.post_ids),
            "total_scheduled": len(scheduled_posts),
            "total_errors": len(errors)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk scheduling: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to bulk schedule posts")

@router.get("/analytics", summary="Get scheduling analytics")
async def get_scheduling_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    platform: Optional[str] = Query(None, description="Filter by platform"),
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive scheduling analytics for the user
    """
    try:
        # Date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Build platform filter
        platform_filter = ""
        params = {
            "firebase_uid": user.get("firebase_uid"),
            "start_date": start_date,
            "end_date": end_date
        }
        
        if platform:
            platform_filter = "AND sa.platform = :platform"
            params["platform"] = platform
        
        # Get basic stats
        stats = db.execute(text(f"""
            SELECT 
                COUNT(*) FILTER (WHERE sa.status = 'scheduled') as total_scheduled,
                COUNT(*) FILTER (WHERE sa.status = 'published') as total_published,
                COUNT(*) FILTER (WHERE sa.status = 'failed') as total_failed,
                AVG(sa.delay_minutes) FILTER (WHERE sa.delay_minutes IS NOT NULL) as avg_delay
            FROM scheduling_analytics sa
            JOIN users u ON sa.user_id = u.id
            WHERE u.firebase_uid = :firebase_uid 
                AND sa.created_at >= :start_date 
                AND sa.created_at <= :end_date
                {platform_filter}
        """), params).first()
        
        # Calculate success rate
        total_attempts = (stats.total_published or 0) + (stats.total_failed or 0)
        success_rate = (stats.total_published / total_attempts * 100) if total_attempts > 0 else 0
        
        # Get platform breakdown
        platform_breakdown = {}
        platform_stats = db.execute(text(f"""
            SELECT 
                sa.platform,
                COUNT(*) FILTER (WHERE sa.status = 'scheduled') as scheduled,
                COUNT(*) FILTER (WHERE sa.status = 'published') as published,
                COUNT(*) FILTER (WHERE sa.status = 'failed') as failed
            FROM scheduling_analytics sa
            JOIN users u ON sa.user_id = u.id
            WHERE u.firebase_uid = :firebase_uid 
                AND sa.created_at >= :start_date 
                AND sa.created_at <= :end_date
                {platform_filter}
            GROUP BY sa.platform
        """), params).fetchall()
        
        for stat in platform_stats:
            platform_breakdown[stat.platform] = {
                "scheduled": stat.scheduled,
                "published": stat.published,
                "failed": stat.failed
            }
        
        # Get recent failures
        recent_failures = db.execute(text(f"""
            SELECT 
                sa.platform,
                sa.error_type,
                sa.created_at,
                p.name as post_name
            FROM scheduling_analytics sa
            JOIN users u ON sa.user_id = u.id
            LEFT JOIN posts p ON sa.post_id = p.id
            WHERE u.firebase_uid = :firebase_uid 
                AND sa.status = 'failed'
                AND sa.created_at >= :start_date 
                AND sa.created_at <= :end_date
                {platform_filter}
            ORDER BY sa.created_at DESC
            LIMIT 10
        """), params).fetchall()
        
        failures = []
        for failure in recent_failures:
            failures.append({
                "platform": failure.platform,
                "error_type": failure.error_type,
                "created_at": failure.created_at,
                "post_name": failure.post_name
            })
        
        return SchedulingAnalyticsResponse(
            total_scheduled=stats.total_scheduled or 0,
            total_published=stats.total_published or 0,
            total_failed=stats.total_failed or 0,
            success_rate=round(success_rate, 2),
            average_delay_minutes=round(stats.avg_delay or 0, 2),
            platform_breakdown=platform_breakdown,
            recent_failures=failures
        )
        
    except Exception as e:
        logger.error(f"Error fetching scheduling analytics: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch scheduling analytics")

@router.get("/optimal-times", summary="Get optimal posting times")
async def get_optimal_posting_times(
    platform: Optional[str] = Query(None, description="Get times for specific platform"),
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get AI-suggested optimal posting times based on analytics
    This is a placeholder for ML-based optimization
    """
    # For now, return static optimal times based on industry standards
    # In production, this would analyze user's historical performance
    
    optimal_times = {
        "twitter": [
            {"day_of_week": 1, "hour": 9, "engagement_score": 0.85},
            {"day_of_week": 1, "hour": 12, "engagement_score": 0.90},
            {"day_of_week": 1, "hour": 17, "engagement_score": 0.88},
            {"day_of_week": 2, "hour": 9, "engagement_score": 0.83},
            {"day_of_week": 2, "hour": 12, "engagement_score": 0.87},
        ],
        "linkedin": [
            {"day_of_week": 1, "hour": 7, "engagement_score": 0.82},
            {"day_of_week": 1, "hour": 12, "engagement_score": 0.89},
            {"day_of_week": 1, "hour": 17, "engagement_score": 0.91},
            {"day_of_week": 2, "hour": 8, "engagement_score": 0.85},
        ],
        "facebook": [
            {"day_of_week": 0, "hour": 9, "engagement_score": 0.78},
            {"day_of_week": 0, "hour": 15, "engagement_score": 0.85},
            {"day_of_week": 0, "hour": 20, "engagement_score": 0.82},
            {"day_of_week": 6, "hour": 14, "engagement_score": 0.88},
        ],
        "instagram": [
            {"day_of_week": 0, "hour": 11, "engagement_score": 0.86},
            {"day_of_week": 0, "hour": 14, "engagement_score": 0.89},
            {"day_of_week": 0, "hour": 19, "engagement_score": 0.91},
            {"day_of_week": 6, "hour": 16, "engagement_score": 0.87},
        ]
    }
    
    if platform:
        times = optimal_times.get(platform, [])
        result = {platform: times}
    else:
        result = optimal_times
    
    # Convert to OptimalTimeSlot objects
    formatted_result = {}
    for plat, times in result.items():
        formatted_result[plat] = [
            OptimalTimeSlot(
                platform=plat,
                day_of_week=time["day_of_week"],
                hour=time["hour"],
                engagement_score=time["engagement_score"]
            )
            for time in times
        ]
    
    return {
        "optimal_times": formatted_result,
        "note": "Times are based on industry averages. Personalized recommendations coming soon.",
        "timezone": "UTC"
    }

# Background scheduler (this would typically be a separate worker service)
@router.post("/process-queue", summary="Process scheduling queue (internal)")
async def process_scheduling_queue(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Internal endpoint to process the scheduling queue
    This would typically be called by a background worker service
    """
    try:
        # Get posts that are ready to be published (scheduled_for <= now)
        now = datetime.utcnow()
        
        ready_posts = db.execute(text("""
            SELECT 
                sq.id as queue_id,
                sq.post_id,
                sq.attempts,
                p.name,
                p.universal_content,
                p.platforms,
                p.media_files,
                u.firebase_uid,
                u.id as user_db_id
            FROM scheduling_queue sq
            JOIN posts p ON sq.post_id = p.id
            JOIN users u ON sq.user_id = u.id
            WHERE sq.scheduled_for <= :now 
                AND sq.status = 'pending'
                AND sq.attempts < 3
            ORDER BY sq.scheduled_for ASC
            LIMIT 10
        """), {"now": now}).fetchall()
        
        processed_count = 0
        
        for post in ready_posts:
            try:
                # Mark as processing
                db.execute(text("""
                    UPDATE scheduling_queue 
                    SET status = 'processing', 
                        last_attempt_at = NOW(),
                        attempts = attempts + 1
                    WHERE id = :queue_id
                """), {"queue_id": post.queue_id})
                db.commit()
                
                # Parse platforms and media
                platforms = json.loads(post.platforms) if post.platforms else []
                media_files = json.loads(post.media_files) if post.media_files else []
                
                # Initialize platform publisher
                publisher = PlatformPublisher(post.firebase_uid)
                
                # Publish to each platform
                publish_results = []
                success_count = 0
                
                for platform in platforms:
                    try:
                        result = await publisher.publish_to_platform(
                            platform=platform,
                            content=post.universal_content,
                            media_files=media_files
                        )
                        
                        if result.get("success"):
                            success_count += 1
                            
                        publish_results.append({
                            "platform": platform,
                            "success": result.get("success", False),
                            "platform_post_id": result.get("platform_post_id"),
                            "error": result.get("error")
                        })
                        
                        # Log to analytics
                        db.execute(text("""
                            INSERT INTO scheduling_analytics (
                                user_id, post_id, platform, scheduled_time, 
                                published_time, status, error_type
                            ) VALUES (
                                :user_id, :post_id, :platform, :scheduled_time,
                                NOW(), :status, :error_type
                            )
                        """), {
                            "user_id": post.user_db_id,
                            "post_id": post.post_id,
                            "platform": platform,
                            "scheduled_time": now,
                            "status": "published" if result.get("success") else "failed",
                            "error_type": result.get("error") if not result.get("success") else None
                        })
                        
                    except Exception as platform_error:
                        logger.error(f"Error publishing to {platform}: {str(platform_error)}")
                        publish_results.append({
                            "platform": platform,
                            "success": False,
                            "error": str(platform_error)
                        })
                
                # Update queue status based on results
                if success_count == len(platforms):
                    # All platforms succeeded
                    queue_status = "completed"
                    post_status = "published"
                elif success_count > 0:
                    # Partial success
                    queue_status = "partial"
                    post_status = "published"
                else:
                    # All failed
                    queue_status = "failed"
                    post_status = "failed"
                
                # Update queue and post
                db.execute(text("""
                    UPDATE scheduling_queue 
                    SET status = :queue_status,
                        published_at = CASE WHEN :queue_status IN ('completed', 'partial') THEN NOW() ELSE NULL END,
                        platform_results = :platform_results,
                        error_message = CASE WHEN :queue_status = 'failed' THEN 'All platforms failed' ELSE NULL END
                    WHERE id = :queue_id
                """), {
                    "queue_status": queue_status,
                    "platform_results": json.dumps(publish_results),
                    "queue_id": post.queue_id
                })
                
                db.execute(text("""
                    UPDATE posts 
                    SET status = :post_status
                    WHERE id = :post_id
                """), {
                    "post_status": post_status,
                    "post_id": post.post_id
                })
                
                db.commit()
                processed_count += 1
                
                logger.info(f"Processed scheduled post {post.post_id}: {success_count}/{len(platforms)} platforms succeeded")
                
            except Exception as post_error:
                logger.error(f"Error processing post {post.post_id}: {str(post_error)}")
                
                # Mark as failed
                db.execute(text("""
                    UPDATE scheduling_queue 
                    SET status = 'failed',
                        error_message = :error
                    WHERE id = :queue_id
                """), {
                    "error": str(post_error),
                    "queue_id": post.queue_id
                })
                db.commit()
        
        return {
            "success": True,
            "message": f"Processed {processed_count} scheduled posts",
            "processed_count": processed_count,
            "total_ready": len(ready_posts)
        }
        
    except Exception as e:
        logger.error(f"Error processing scheduling queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process scheduling queue")