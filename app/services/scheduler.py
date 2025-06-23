"""
Background Scheduler Service
Handles scheduled post publishing
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from app.utils.database import get_database
from app.services.platform_publisher import PlatformPublisher, PublishStatus

logger = logging.getLogger(__name__)

class PostScheduler:
    """Background service for processing scheduled posts"""
    
    def __init__(self):
        self.db = get_database(admin_access=True)
        self.publisher = PlatformPublisher()
        self.running = False
        
    async def start(self):
        """Start the scheduler background task"""
        self.running = True
        logger.info("Post scheduler started")
        
        while self.running:
            try:
                await self.process_due_posts()
                # Check every minute for due posts
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in scheduler main loop: {str(e)}")
                await asyncio.sleep(60)  # Continue after error
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        logger.info("Post scheduler stopped")
    
    async def process_due_posts(self):
        """Process all posts that are due for publishing"""
        try:
            # Get all scheduled posts that are due
            current_time = datetime.now(timezone.utc)
            
            response = self.db.table('scheduled_posts').select('*').eq(
                'status', 'pending'
            ).lte('scheduled_for', current_time.isoformat()).execute()
            
            if not response.data:
                return
            
            logger.info(f"Found {len(response.data)} posts due for publishing")
            
            for scheduled_post in response.data:
                await self.process_single_scheduled_post(scheduled_post)
                
        except Exception as e:
            logger.error(f"Error processing due posts: {str(e)}")
    
    async def process_single_scheduled_post(self, scheduled_post: Dict[str, Any]):
        """Process a single scheduled post"""
        try:
            post_id = scheduled_post['post_id']
            user_id = scheduled_post['user_id']
            scheduled_post_id = scheduled_post['id']
            
            # Update scheduled post status to processing
            self.db.table('scheduled_posts').update({
                'status': 'processing',
                'last_attempt_at': datetime.now(timezone.utc).isoformat(),
                'attempts': scheduled_post.get('attempts', 0) + 1
            }).eq('id', scheduled_post_id).execute()
            
            # Get the full post data
            post_response = self.db.table('posts').select('*').eq(
                'id', post_id
            ).execute()
            
            if not post_response.data:
                logger.error(f"Post {post_id} not found for scheduled publishing")
                await self._mark_scheduled_post_failed(
                    scheduled_post_id, 
                    "Post not found"
                )
                return
            
            post_data = post_response.data[0]
            
            # Transform post data for publishing
            from app.routers.posts_unified import transform_post_data
            post = transform_post_data(post_data)
            
            if not post.get('platforms'):
                logger.error(f"No platforms configured for post {post_id}")
                await self._mark_scheduled_post_failed(
                    scheduled_post_id, 
                    "No platforms configured"
                )
                return
            
            # Update post status to publishing
            self.db.table('posts').update({
                'status': 'publishing'
            }).eq('id', post_id).execute()
            
            # Create publishing results records
            await self._create_publishing_results_records(post_id, post['platforms'])
            
            # Prepare content data
            content_data = {
                'content_mode': post.get('content_mode', 'universal'),
                'universal_content': post.get('universal_content', ''),
                'universal_metadata': post.get('universal_metadata', {}),
                'platform_content': post.get('platform_content', {}),
                'media_files': post.get('media_files', [])
            }
            
            # Publish to all platforms
            results = await self.publisher.publish_to_platforms(
                user_id, 
                post['platforms'], 
                content_data
            )
            
            # Process results
            published_count = 0
            failed_count = 0
            
            for result in results:
                if result.status == PublishStatus.SUCCESS:
                    published_count += 1
                    await self._update_publishing_result(
                        post_id, result.platform, "success", 
                        result.platform_post_id, None, result.metadata
                    )
                else:
                    failed_count += 1
                    await self._update_publishing_result(
                        post_id, result.platform, "failed", 
                        None, result.error_message, result.metadata
                    )
            
            # Update final post status
            if published_count > 0 and failed_count == 0:
                final_status = "published"
            elif published_count > 0 and failed_count > 0:
                final_status = "published"  # Partial success
            else:
                final_status = "failed"
            
            self.db.table('posts').update({
                'status': final_status
            }).eq('id', post_id).execute()
            
            # Update scheduled post status
            if published_count > 0:
                self.db.table('scheduled_posts').update({
                    'status': 'completed'
                }).eq('id', scheduled_post_id).execute()
                
                logger.info(f"Successfully published scheduled post {post_id} to {published_count} platforms")
            else:
                await self._mark_scheduled_post_failed(
                    scheduled_post_id, 
                    f"Failed to publish to any platform"
                )
                
        except Exception as e:
            logger.error(f"Error processing scheduled post {scheduled_post.get('id')}: {str(e)}")
            await self._mark_scheduled_post_failed(
                scheduled_post.get('id'), 
                str(e)
            )
    
    async def _create_publishing_results_records(self, post_id: str, platforms: List[Dict[str, Any]]):
        """Create initial publishing result records"""
        try:
            records = []
            for platform in platforms:
                records.append({
                    "post_id": post_id,
                    "platform": platform["provider"],
                    "platform_account_id": platform["accountId"],
                    "status": "pending"
                })
            
            if records:
                self.db.table('post_publishing_results').insert(records).execute()
                
        except Exception as e:
            logger.error(f"Error creating publishing result records: {str(e)}")
    
    async def _update_publishing_result(
        self, 
        post_id: str, 
        platform: str, 
        status: str, 
        platform_post_id: str = None,
        error_message: str = None,
        metadata: Dict[str, Any] = None
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
            
            self.db.table('post_publishing_results').update(update_data).eq(
                'post_id', post_id
            ).eq('platform', platform).execute()
            
        except Exception as e:
            logger.error(f"Error updating publishing result: {str(e)}")
    
    async def _mark_scheduled_post_failed(self, scheduled_post_id: str, error_message: str):
        """Mark a scheduled post as failed"""
        try:
            self.db.table('scheduled_posts').update({
                'status': 'failed',
                'error_message': error_message,
                'last_attempt_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', scheduled_post_id).execute()
            
            logger.error(f"Marked scheduled post {scheduled_post_id} as failed: {error_message}")
            
        except Exception as e:
            logger.error(f"Error marking scheduled post as failed: {str(e)}")
    
    async def retry_failed_posts(self, max_retries: int = 3):
        """Retry failed scheduled posts that haven't exceeded max retries"""
        try:
            # Get failed posts that can be retried
            response = self.db.table('scheduled_posts').select('*').eq(
                'status', 'failed'
            ).lt('attempts', max_retries).execute()
            
            if not response.data:
                return
            
            logger.info(f"Retrying {len(response.data)} failed scheduled posts")
            
            for scheduled_post in response.data:
                # Reset status to pending for retry
                self.db.table('scheduled_posts').update({
                    'status': 'pending',
                    'error_message': None
                }).eq('id', scheduled_post['id']).execute()
                
                # Process the post again
                await self.process_single_scheduled_post(scheduled_post)
                
        except Exception as e:
            logger.error(f"Error retrying failed posts: {str(e)}")

# Global scheduler instance
scheduler = PostScheduler()

async def start_scheduler():
    """Start the global scheduler"""
    await scheduler.start()

def stop_scheduler():
    """Stop the global scheduler"""
    scheduler.stop()

# Helper function for immediate use in posts_unified.py
async def process_scheduled_posts():
    """Process scheduled posts immediately (for background tasks)"""
    await scheduler.process_due_posts()