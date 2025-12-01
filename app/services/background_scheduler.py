"""
Background Scheduler Service for Enterprise Post Scheduling
This service runs as a background worker to process scheduled posts
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import json
import sys
import os

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.services.platform_publisher import PlatformPublisher
from app.utils.database import get_database_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/multivio_scheduler.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class BackgroundScheduler:
    """
    Enterprise-level background scheduler for social media posts
    """
    
    def __init__(self):
        self.engine = create_engine(get_database_url())
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.max_attempts = 3
        self.batch_size = 10
        
    async def process_scheduling_queue(self) -> Dict[str, Any]:
        """
        Process the scheduling queue and publish ready posts
        
        Returns:
            Dict with processing results
        """
        session = self.SessionLocal()
        
        try:
            logger.info("Starting scheduling queue processing...")
            
            # Get posts that are ready to be published
            now = datetime.utcnow()
            
            ready_posts = session.execute(text("""
                SELECT 
                    sq.id as queue_id,
                    sq.post_id,
                    sq.attempts,
                    sq.scheduled_for,
                    p.name,
                    p.universal_content,
                    p.platforms,
                    p.media_files,
                    u.firebase_uid,
                    u.id as user_db_id,
                    u.email
                FROM scheduling_queue sq
                JOIN posts p ON sq.post_id = p.id
                JOIN users u ON sq.user_id = u.id
                WHERE sq.scheduled_for <= :now 
                    AND sq.status = 'pending'
                    AND sq.attempts < :max_attempts
                ORDER BY sq.scheduled_for ASC
                LIMIT :batch_size
            """), {
                "now": now,
                "max_attempts": self.max_attempts,
                "batch_size": self.batch_size
            }).fetchall()
            
            if not ready_posts:
                logger.info("No posts ready for publishing")
                return {
                    "success": True,
                    "processed_count": 0,
                    "total_ready": 0,
                    "message": "No posts ready for publishing"
                }
            
            logger.info(f"Found {len(ready_posts)} posts ready for publishing")
            
            processed_count = 0
            success_count = 0
            partial_count = 0
            failed_count = 0
            
            for post in ready_posts:
                try:
                    result = await self._process_single_post(session, post)
                    
                    if result["status"] == "completed":
                        success_count += 1
                    elif result["status"] == "partial":
                        partial_count += 1
                    else:
                        failed_count += 1
                        
                    processed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing post {post.post_id}: {str(e)}")
                    failed_count += 1
                    
                    # Mark as failed
                    session.execute(text("""
                        UPDATE scheduling_queue 
                        SET status = 'failed',
                            error_message = :error,
                            last_attempt_at = NOW(),
                            attempts = attempts + 1
                        WHERE id = :queue_id
                    """), {
                        "error": f"Processing error: {str(e)}",
                        "queue_id": post.queue_id
                    })
                    session.commit()
            
            logger.info(f"""
                Queue processing completed:
                - Processed: {processed_count}
                - Successful: {success_count}
                - Partial: {partial_count}
                - Failed: {failed_count}
            """)
            
            return {
                "success": True,
                "processed_count": processed_count,
                "success_count": success_count,
                "partial_count": partial_count,
                "failed_count": failed_count,
                "total_ready": len(ready_posts),
                "message": f"Processed {processed_count} posts"
            }
            
        except Exception as e:
            logger.error(f"Error in queue processing: {str(e)}")
            session.rollback()
            return {
                "success": False,
                "error": str(e),
                "message": "Queue processing failed"
            }
        finally:
            session.close()
    
    async def _process_single_post(self, session, post) -> Dict[str, Any]:
        """
        Process a single scheduled post
        
        Args:
            session: Database session
            post: Post record from database
            
        Returns:
            Dict with processing result
        """
        logger.info(f"Processing post {post.post_id} for user {post.email}")
        
        # Mark as processing
        session.execute(text("""
            UPDATE scheduling_queue 
            SET status = 'processing', 
                last_attempt_at = NOW(),
                attempts = attempts + 1
            WHERE id = :queue_id
        """), {"queue_id": post.queue_id})
        session.commit()
        
        try:
            # Parse platforms and media
            platforms = json.loads(post.platforms) if post.platforms else []
            media_files = json.loads(post.media_files) if post.media_files else []
            
            if not platforms:
                raise Exception("No platforms specified for post")
            
            logger.info(f"Publishing to platforms: {platforms}")
            
            # Initialize platform publisher
            publisher = PlatformPublisher(post.firebase_uid)
            
            # Publish to each platform
            publish_results = []
            success_count = 0
            
            for platform in platforms:
                try:
                    logger.info(f"Publishing to {platform}...")
                    
                    result = await publisher.publish_to_platform(
                        platform=platform,
                        content=post.universal_content,
                        media_files=media_files
                    )
                    
                    if result.get("success"):
                        success_count += 1
                        logger.info(f"Successfully published to {platform}: {result.get('platform_post_id')}")
                    else:
                        logger.error(f"Failed to publish to {platform}: {result.get('error')}")
                        
                    publish_results.append({
                        "platform": platform,
                        "success": result.get("success", False),
                        "platform_post_id": result.get("platform_post_id"),
                        "error": result.get("error"),
                        "published_at": datetime.utcnow().isoformat()
                    })
                    
                    # Log to analytics
                    delay_minutes = None
                    if post.scheduled_for:
                        delay = datetime.utcnow() - post.scheduled_for
                        delay_minutes = int(delay.total_seconds() / 60)
                    
                    session.execute(text("""
                        INSERT INTO scheduling_analytics (
                            user_id, post_id, platform, scheduled_time, 
                            published_time, delay_minutes, status, error_type
                        ) VALUES (
                            :user_id, :post_id, :platform, :scheduled_time,
                            NOW(), :delay_minutes, :status, :error_type
                        )
                    """), {
                        "user_id": post.user_db_id,
                        "post_id": post.post_id,
                        "platform": platform,
                        "scheduled_time": post.scheduled_for,
                        "delay_minutes": delay_minutes,
                        "status": "published" if result.get("success") else "failed",
                        "error_type": result.get("error") if not result.get("success") else None
                    })
                    
                except Exception as platform_error:
                    logger.error(f"Error publishing to {platform}: {str(platform_error)}")
                    publish_results.append({
                        "platform": platform,
                        "success": False,
                        "error": str(platform_error),
                        "published_at": datetime.utcnow().isoformat()
                    })
                    
                    # Log failed attempt to analytics
                    session.execute(text("""
                        INSERT INTO scheduling_analytics (
                            user_id, post_id, platform, scheduled_time, 
                            published_time, status, error_type
                        ) VALUES (
                            :user_id, :post_id, :platform, :scheduled_time,
                            NOW(), 'failed', :error_type
                        )
                    """), {
                        "user_id": post.user_db_id,
                        "post_id": post.post_id,
                        "platform": platform,
                        "scheduled_time": post.scheduled_for,
                        "error_type": f"Platform error: {str(platform_error)}"
                    })
            
            # Determine final status
            if success_count == len(platforms):
                # All platforms succeeded
                queue_status = "completed"
                post_status = "published"
                logger.info(f"Post {post.post_id} published successfully to all {len(platforms)} platforms")
            elif success_count > 0:
                # Partial success
                queue_status = "partial"
                post_status = "published"
                logger.warning(f"Post {post.post_id} published partially: {success_count}/{len(platforms)} platforms succeeded")
            else:
                # All failed - check if we should retry
                if post.attempts >= self.max_attempts:
                    queue_status = "failed"
                    post_status = "failed"
                    logger.error(f"Post {post.post_id} failed permanently after {post.attempts} attempts")
                else:
                    queue_status = "pending"  # Will retry
                    post_status = "scheduled"
                    logger.warning(f"Post {post.post_id} failed, will retry (attempt {post.attempts}/{self.max_attempts})")
            
            # Update queue status
            session.execute(text("""
                UPDATE scheduling_queue 
                SET status = :queue_status,
                    published_at = CASE WHEN :queue_status IN ('completed', 'partial') THEN NOW() ELSE NULL END,
                    platform_results = :platform_results,
                    error_message = CASE 
                        WHEN :queue_status = 'failed' THEN 'All platforms failed permanently'
                        WHEN :queue_status = 'partial' THEN 'Some platforms failed'
                        ELSE NULL 
                    END
                WHERE id = :queue_id
            """), {
                "queue_status": queue_status,
                "platform_results": json.dumps(publish_results),
                "queue_id": post.queue_id
            })
            
            # Update post status
            session.execute(text("""
                UPDATE posts 
                SET status = :post_status
                WHERE id = :post_id
            """), {
                "post_status": post_status,
                "post_id": post.post_id
            })
            
            session.commit()
            
            return {
                "status": queue_status,
                "success_count": success_count,
                "total_platforms": len(platforms),
                "results": publish_results
            }
            
        except Exception as e:
            logger.error(f"Error processing post {post.post_id}: {str(e)}")
            
            # Mark as failed or pending retry
            if post.attempts >= self.max_attempts:
                queue_status = "failed"
                post_status = "failed"
                error_message = f"Processing failed permanently: {str(e)}"
            else:
                queue_status = "pending"
                post_status = "scheduled"
                error_message = f"Processing failed, will retry: {str(e)}"
            
            session.execute(text("""
                UPDATE scheduling_queue 
                SET status = :queue_status,
                    error_message = :error_message
                WHERE id = :queue_id
            """), {
                "queue_status": queue_status,
                "error_message": error_message,
                "queue_id": post.queue_id
            })
            
            session.execute(text("""
                UPDATE posts 
                SET status = :post_status
                WHERE id = :post_id
            """), {
                "post_status": post_status,
                "post_id": post.post_id
            })
            
            session.commit()
            
            return {
                "status": queue_status,
                "error": str(e)
            }
    
    async def cleanup_old_queue_items(self, days_old: int = 30) -> Dict[str, Any]:
        """
        Clean up old completed/failed queue items
        
        Args:
            days_old: Remove items older than this many days
            
        Returns:
            Dict with cleanup results
        """
        session = self.SessionLocal()
        
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            result = session.execute(text("""
                DELETE FROM scheduling_queue 
                WHERE status IN ('completed', 'failed')
                    AND updated_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            deleted_count = result.rowcount
            session.commit()
            
            logger.info(f"Cleaned up {deleted_count} old queue items")
            
            return {
                "success": True,
                "deleted_count": deleted_count,
                "message": f"Cleaned up {deleted_count} old queue items"
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up old queue items: {str(e)}")
            session.rollback()
            return {
                "success": False,
                "error": str(e),
                "message": "Cleanup failed"
            }
        finally:
            session.close()
    
    async def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current queue status for monitoring
        
        Returns:
            Dict with queue statistics
        """
        session = self.SessionLocal()
        
        try:
            # Get queue statistics
            stats = session.execute(text("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'processing') as processing,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'partial') as partial,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE scheduled_for <= NOW() AND status = 'pending') as overdue
                FROM scheduling_queue
            """)).first()
            
            # Get next scheduled post
            next_post = session.execute(text("""
                SELECT scheduled_for
                FROM scheduling_queue
                WHERE status = 'pending' AND scheduled_for > NOW()
                ORDER BY scheduled_for ASC
                LIMIT 1
            """)).first()
            
            return {
                "success": True,
                "queue_stats": {
                    "pending": stats.pending,
                    "processing": stats.processing,
                    "completed": stats.completed,
                    "partial": stats.partial,
                    "failed": stats.failed,
                    "overdue": stats.overdue
                },
                "next_scheduled": next_post.scheduled_for if next_post else None,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting queue status: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to get queue status"
            }
        finally:
            session.close()


async def main():
    """
    Main function for running the scheduler as a standalone service
    """
    logger.info("Starting Background Scheduler Service...")
    
    scheduler = BackgroundScheduler()
    
    # Process the queue
    result = await scheduler.process_scheduling_queue()
    
    if result["success"]:
        logger.info(f"Scheduler run completed: {result['message']}")
    else:
        logger.error(f"Scheduler run failed: {result.get('message', 'Unknown error')}")
    
    # Optional: Clean up old items (run weekly)
    cleanup_result = await scheduler.cleanup_old_queue_items(days_old=30)
    logger.info(f"Cleanup result: {cleanup_result['message']}")
    
    # Print queue status
    status = await scheduler.get_queue_status()
    if status["success"]:
        logger.info(f"Queue status: {status['queue_stats']}")


if __name__ == "__main__":
    # Run the scheduler
    asyncio.run(main())