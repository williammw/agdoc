"""
Platform Publishing Service
Handles publishing to all social media platforms
"""

import asyncio
import httpx
import json
import logging
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from html import unescape
import base64
import hashlib
import hmac
import urllib.parse
import time
import secrets

from app.utils.encryption import decrypt_token
import os
from app.utils.database import get_database

logger = logging.getLogger(__name__)

class PublishStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"

@dataclass
class PublishResult:
    platform: str
    status: PublishStatus
    platform_post_id: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class PlatformContent:
    content: str
    media_urls: List[str]
    hashtags: List[str] = None
    mentions: List[str] = None
    metadata: Dict[str, Any] = None

# COMPLETELY REMOVED: The global function that was using environment variables
# Any code still calling the old function will now fail explicitly
def generate_oauth1_header_REMOVED(*args, **kwargs):
    """This function has been removed. Use PlatformPublisher._generate_oauth1_header_user_tokens() instead."""
    raise RuntimeError("🚨 CRITICAL ERROR: generate_oauth1_header_REMOVED() was called! Use PlatformPublisher._generate_oauth1_header_user_tokens() with user-specific tokens instead!")

def clean_html_content(html_content: str) -> str:
    """Convert HTML content to plain text suitable for social media"""
    if not html_content:
        return ""
    
    # Replace common HTML tags with appropriate formatting
    # Convert <p> tags to newlines
    content = re.sub(r'<p[^>]*>', '', html_content)
    content = re.sub(r'</p>', '\n\n', content)
    
    # Convert <br> tags to newlines
    content = re.sub(r'<br[^>]*/?>', '\n', content)
    
    # Convert <strong> and <b> tags to **bold** (for platforms that support it)
    content = re.sub(r'<(strong|b)[^>]*>(.*?)</\1>', r'**\2**', content)
    
    # Convert <em> and <i> tags to *italic* (for platforms that support it)
    content = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', content)
    
    # Convert links to plain text with URL
    content = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'\2 (\1)', content)
    
    # Remove any remaining HTML tags
    content = re.sub(r'<[^>]+>', '', content)
    
    # Decode HTML entities
    content = unescape(content)
    
    # Clean up extra whitespace
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)  # Remove extra newlines
    content = content.strip()
    
    return content

class PlatformPublisher:
    """Main class for publishing content to social media platforms"""
    
    def __init__(self):
        self.db = get_database(admin_access=True)
        self.timeout = 30.0
        
    async def publish_to_platforms(
        self, 
        user_id: int, 
        platforms: List[Dict[str, Any]], 
        content_data: Dict[str, Any]
    ) -> List[PublishResult]:
        """
        Publish content to multiple platforms
        
        Args:
            user_id: User ID
            platforms: List of platform configurations [{"provider": "twitter", "accountId": "123", ...}]
            content_data: Content to publish with universal/platform-specific data
        
        Returns:
            List of PublishResult objects
        """
        logger.warning(f"🚀🚀🚀 PlatformPublisher.publish_to_platforms CALLED!")
        logger.warning(f"👤 User ID: {user_id}")
        logger.warning(f"📱 Platforms: {platforms}")
        logger.warning(f"📄 Content data keys: {list(content_data.keys())}")
        logger.warning(f"📁 Media files count: {len(content_data.get('media_files', []))}")
        print(f"🚀🚀🚀 PlatformPublisher.publish_to_platforms CALLED with {len(platforms)} platforms!")
        
        results = []
        
        # Process each platform concurrently for better performance
        tasks = []
        for platform in platforms:
            task = self._publish_to_single_platform(user_id, platform, content_data)
            tasks.append(task)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle any exceptions that occurred
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    platform = platforms[i]
                    processed_results.append(PublishResult(
                        platform=platform['provider'],
                        status=PublishStatus.FAILED,
                        error_message=f"Unexpected error: {str(result)}"
                    ))
                else:
                    processed_results.append(result)
            
            return processed_results
        
        return results

    async def _publish_to_single_platform(
        self, 
        user_id: int, 
        platform: Dict[str, Any], 
        content_data: Dict[str, Any]
    ) -> PublishResult:
        """Publish to a single platform"""
        
        provider = platform['provider']
        account_id = platform['accountId']
        
        logger.warning(f"🎯 _publish_to_single_platform: {provider} (account: {account_id})")
        logger.warning(f"🎯 Content data media_files: {content_data.get('media_files', [])}")
        
        try:
            # Get access token for this platform/account
            access_token = await self._get_access_token(user_id, provider, account_id)
            if not access_token:
                return PublishResult(
                    platform=provider,
                    status=PublishStatus.FAILED,
                    error_message=f"No valid access token found for {provider} account {account_id}"
                )
            
            # Prepare content for this platform
            platform_content = self._prepare_platform_content(platform, content_data)
            
            # Route to appropriate platform publisher
            logger.warning(f"🚦 Routing to platform publisher for: {provider}")
            if provider == 'twitter':
                return await self._publish_to_twitter(access_token, platform_content, platform, user_id)
            elif provider == 'linkedin':
                return await self._publish_to_linkedin(access_token, platform_content, platform)
            elif provider == 'facebook':
                return await self._publish_to_facebook(access_token, platform_content, platform)
            elif provider == 'instagram':
                return await self._publish_to_instagram(access_token, platform_content, platform)
            elif provider == 'threads':
                logger.warning(f"🧵 CALLING Threads publisher!")
                return await self._publish_to_threads(access_token, platform_content, platform)
            elif provider == 'tiktok':
                return await self._publish_to_tiktok(access_token, platform_content, platform)
            elif provider == 'youtube':
                return await self._publish_to_youtube(access_token, platform_content, platform)
            else:
                logger.warning(f"❌ Platform {provider} not supported!")
                return PublishResult(
                    platform=provider,
                    status=PublishStatus.FAILED,
                    error_message=f"Platform {provider} not supported yet"
                )
                
        except Exception as e:
            logger.error(f"Error publishing to {provider}: {str(e)}")
            return PublishResult(
                platform=provider,
                status=PublishStatus.FAILED,
                error_message=str(e)
            )

    async def _get_access_token(self, user_id: int, provider: str, account_id: str) -> Optional[str]:
        """Get decrypted access token for platform"""
        try:
            logger.info(f"Getting access token for user {user_id}, provider {provider}, account {account_id}")
            
            # Convert account_id to string to ensure consistent comparison
            account_id_str = str(account_id)
            
            response = self.db.table('social_connections').select('access_token, provider_account_id').eq(
                'user_id', user_id
            ).eq('provider', provider).eq('provider_account_id', account_id_str).execute()
            
            logger.info(f"Database query: user_id={user_id}, provider={provider}, provider_account_id={account_id_str}")
            logger.info(f"Database response for access token: {response.data}")
            
            if response.data and len(response.data) > 0:
                encrypted_token = response.data[0]['access_token']
                found_account_id = response.data[0]['provider_account_id']
                logger.info(f"Found token for account {found_account_id}")
                logger.info(f"Encrypted token exists: {bool(encrypted_token)}")
                logger.info(f"Encrypted token length: {len(encrypted_token) if encrypted_token else 0}")
                
                if encrypted_token:
                    try:
                        # Check encryption key availability
                        encryption_key = os.getenv("ENCRYPTION_KEY")
                        logger.info(f"Encryption key available: {bool(encryption_key)}")
                        
                        decrypted_token = decrypt_token(encrypted_token)
                        logger.info(f"Decryption result: {bool(decrypted_token)}")
                        logger.info(f"Decrypted token length: {len(decrypted_token) if decrypted_token else 0}")
                        
                        if decrypted_token:
                            logger.info(f"Successfully decrypted token for {provider}")
                            return decrypted_token
                        else:
                            logger.error(f"Decryption returned None/empty for {provider} account {account_id}")
                            logger.error(f"This usually means the ENCRYPTION_KEY is missing or incorrect")
                            return None
                    except Exception as decrypt_error:
                        logger.error(f"Decryption failed for {provider}: {str(decrypt_error)}")
                        encryption_key = os.getenv("ENCRYPTION_KEY")
                        logger.error(f"Encryption key present: {bool(encryption_key)}")
                        return None
                else:
                    logger.warning(f"Empty access token for {provider} account {account_id}")
                    return None
            
            # If no exact match found, let's log all available accounts for debugging
            debug_response = self.db.table('social_connections').select('provider_account_id, account_label').eq(
                'user_id', user_id
            ).eq('provider', provider).execute()
            
            available_accounts = [f"{row['provider_account_id']} ({row.get('account_label', 'no label')})" 
                                for row in debug_response.data]
            
            logger.warning(f"No access token found for {provider} account {account_id}")
            logger.warning(f"Available {provider} accounts for user {user_id}: {available_accounts}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting access token for {provider}: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _prepare_platform_content(self, platform: Dict[str, Any], content_data: Dict[str, Any]) -> PlatformContent:
        """Prepare content for specific platform"""
        
        provider = platform['provider']
        account_id = platform['accountId']
        
        logger.warning(f"🎨🎨🎨 _prepare_platform_content called for {provider}")
        print(f"🎨🎨🎨 _prepare_platform_content called for {provider} - THIS IS A PRINT STATEMENT")
        
        # Check if we have platform-specific content
        platform_key = f"{provider}-{account_id}"
        platform_specific = content_data.get('platform_content', {}).get(platform_key, {})
        
        if platform_specific and content_data.get('content_mode') == 'specific':
            # Use platform-specific content
            content = platform_specific.get('content', content_data.get('universal_content', ''))
            hashtags = platform_specific.get('hashtags', [])
            mentions = platform_specific.get('mentions', [])
            metadata = platform_specific.get('metadata', {})
            
            # Use platform-specific media selection via mediaIds
            platform_media_ids = platform_specific.get('mediaIds', [])
            if platform_media_ids:
                # Filter shared media pool by selected mediaIds
                all_media_files = content_data.get('media_files', [])
                media_files = [media for media in all_media_files if media.get('id') in platform_media_ids]
                logger.info(f"Using platform-specific media selection for {provider}-{account_id}: {len(media_files)} files from {len(platform_media_ids)} selected IDs")
            else:
                # Fall back to universal media
                media_files = content_data.get('media_files', [])
                logger.info(f"Using universal media for {provider}-{account_id}: {len(media_files)} files")
        else:
            # Use universal content
            content = content_data.get('universal_content', '')
            universal_metadata = content_data.get('universal_metadata', {})
            hashtags = universal_metadata.get('hashtags', [])
            mentions = universal_metadata.get('mentions', [])
            metadata = universal_metadata
            media_files = content_data.get('media_files', [])
        
        # Clean HTML content for social media platforms
        cleaned_content = clean_html_content(content)
        
        # Log the content transformation for debugging
        if content != cleaned_content:
            logger.info(f"Cleaned HTML content for {provider}:")
            logger.info(f"  Original: {content}")
            logger.info(f"  Cleaned:  {cleaned_content}")
        
        # Filter media files for platform compatibility
        compatible_media = []
        compatible_media_objects = []  # Keep full media objects for type detection
        
        logger.info(f"🔍 Processing {len(media_files)} media files for platform {provider}")
        
        for i, media in enumerate(media_files):
            logger.info(f"📁 Media file {i}: type={type(media)}, data={media}")
            # Handle both string URLs and media objects
            if isinstance(media, str):
                compatible_media.append(media)
                compatible_media_objects.append({'cdn_url': media, 'type': 'unknown'})
            else:
                # Handle both camelCase and snake_case field names (frontend uses camelCase)
                platform_compatibility = media.get('platform_compatibility', media.get('platformCompatibility', []))
                cdn_url = media.get('cdn_url')
                processing_status = media.get('processing_status', 'completed')
                media_type = media.get('type', 'unknown')
                file_type = media.get('file_type', '')
                
                logger.info(f"📋 Media details: compatibility={platform_compatibility}, cdn_url={bool(cdn_url)}, status={processing_status}, type={media_type}, file_type={file_type}")
                
                # Check platform compatibility
                is_compatible = provider in platform_compatibility or not platform_compatibility
                logger.info(f"🔍 Platform compatibility check: provider='{provider}', is_compatible={is_compatible}")
                
                if is_compatible:
                    # Only process media files that have a valid CDN URL and are fully processed
                    if cdn_url and processing_status == 'completed':
                        compatible_media.append(cdn_url)
                        
                        # Transform unified posts media object to platform publisher format
                        # This ensures video detection works correctly for Instagram
                        # Handle both camelCase (frontend) and snake_case (backend) field names
                        transformed_media = {
                            'cdn_url': cdn_url,
                            'type': media.get('type', 'unknown'),  # 'image' or 'video'
                            'file_type': media.get('file_type', media.get('fileType', '')),  # MIME type like 'video/mp4'
                            'mime_type': media.get('file_type', media.get('fileType', '')),  # Also map to mime_type for fallback
                            'original_filename': media.get('original_filename', media.get('originalFilename', media.get('fileName', ''))),
                            'metadata': media.get('metadata', {}),
                            'duration': media.get('duration') or media.get('metadata', {}).get('duration'),
                            'thumbnail_url': media.get('thumbnail_url', media.get('thumbnailUrl', '')),
                            'processing_status': media.get('processing_status', media.get('processingStatus', 'completed'))
                        }
                        compatible_media_objects.append(transformed_media)
                        logger.info(f"✅ Added compatible media: type={transformed_media['type']}, file_type={transformed_media['file_type']}")
                    else:
                        if not cdn_url:
                            logger.warning(f"❌ Skipping media file {media.get('id', 'unknown')} for {provider} - missing cdn_url field")
                        elif processing_status != 'completed':
                            logger.warning(f"❌ Skipping media file {media.get('id', 'unknown')} for {provider} - processing status: {processing_status}")
                else:
                    logger.info(f"❌ Skipping media file - not compatible with {provider}")
        
        logger.info(f"Platform {provider} has {len(compatible_media)} compatible media files")
        logger.info(f"Compatible media URLs for {provider}: {compatible_media}")
        
        # Log debug info about media filtering
        if len(media_files) > len(compatible_media):
            filtered_count = len(media_files) - len(compatible_media)
            logger.info(f"Filtered out {filtered_count} media files for {provider} (missing cdn_url or incomplete processing)")
        
        # Add media objects to metadata for type detection
        if not metadata:
            metadata = {}
        metadata['media_objects'] = compatible_media_objects
        
        return PlatformContent(
            content=cleaned_content,
            media_urls=compatible_media,
            hashtags=hashtags,
            mentions=mentions,
            metadata=metadata
        )

    # Platform-specific publishing methods

    async def _publish_to_twitter(
        self, 
        access_token: str, 
        content: PlatformContent, 
        platform: Dict[str, Any],
        user_id: int
    ) -> PublishResult:
        """Publish to Twitter/X"""
        try:
            # Prepare tweet content
            tweet_text = content.content
            if content.hashtags:
                tweet_text += " " + " ".join([f"#{tag}" for tag in content.hashtags])
            
            # Twitter API v2
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            tweet_data = {"text": tweet_text}
            
            # Handle media uploads first if there are any
            media_ids = []
            media_upload_warnings = []
            
            if content.media_urls:
                logger.info(f"🐦 Attempting to upload {len(content.media_urls)} media files to X")
                logger.info(f"🐦 Calling _upload_twitter_media with platform: {platform}")
                logger.info(f"🐦 User ID: {user_id}")
                for media_url in content.media_urls[:4]:  # Twitter allows max 4 media
                    logger.info(f"🐦 About to call _upload_twitter_media for: {media_url}")
                    try:
                        media_id = await self._upload_twitter_media(access_token, media_url, platform, user_id)
                        logger.info(f"🐦 _upload_twitter_media returned: {media_id}")
                    except Exception as e:
                        logger.error(f"🐦 Exception in _upload_twitter_media: {str(e)}")
                        media_id = None
                    if media_id:
                        media_ids.append(media_id)
                        logger.info(f"🐦 Successfully uploaded media: {media_id}")
                    else:
                        media_upload_warnings.append(f"Failed to upload media: {media_url}")
                        logger.warning(f"🐦 Failed to upload media: {media_url}")
            
            if media_ids:
                tweet_data["media"] = {"media_ids": media_ids}
                logger.info(f"🐦 Tweet will include {len(media_ids)} media attachments")
            elif content.media_urls:
                # We had media but couldn't upload any
                logger.warning(f"🐦 Had {len(content.media_urls)} media files but couldn't upload any - posting text-only")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    "https://api.twitter.com/2/tweets",
                    headers=headers,
                    json=tweet_data
                )
                
                if response.status_code in [200, 201]:
                    response_data = response.json()
                    tweet_id = response_data.get("data", {}).get("id")
                    
                    # Determine result status based on media upload success
                    result_status = PublishStatus.SUCCESS
                    result_metadata = {"tweet_data": response_data}
                    
                    if content.media_urls and not media_ids:
                        # Had media but couldn't upload any - partial success
                        result_status = PublishStatus.PARTIAL
                        result_metadata["warnings"] = media_upload_warnings
                        result_metadata["limitation"] = "X API v2 OAuth doesn't support media uploads - text posted successfully"
                        logger.warning(f"🐦 Partial success: Text posted but media upload failed due to OAuth 2.0 limitation")
                    elif content.media_urls and len(media_ids) < len(content.media_urls):
                        # Some media uploaded but not all
                        result_status = PublishStatus.PARTIAL
                        result_metadata["warnings"] = media_upload_warnings
                        logger.warning(f"🐦 Partial success: {len(media_ids)}/{len(content.media_urls)} media files uploaded")
                    
                    return PublishResult(
                        platform="twitter",
                        status=result_status,
                        platform_post_id=tweet_id,
                        metadata=result_metadata
                    )
                else:
                    error_text = response.text
                    logger.error(f"🐦 Tweet creation failed: {error_text}")
                    return PublishResult(
                        platform="twitter",
                        status=PublishStatus.FAILED,
                        error_message=f"Twitter API error: {error_text}"
                    )
                    
        except Exception as e:
            logger.error(f"🐦 Twitter publishing error: {str(e)}")
            return PublishResult(
                platform="twitter",
                status=PublishStatus.FAILED,
                error_message=f"Twitter publishing error: {str(e)}"
            )

    async def _upload_twitter_media(self, access_token: str, media_url: str, platform: Dict[str, Any] = None, user_id: int = None) -> Optional[str]:
        """Upload media to Twitter using OAuth 1.0a authentication with chunked upload for larger files"""
        try:
            logger.info(f"🐦 ===== STARTING X MEDIA UPLOAD PROCESS =====")
            logger.info(f"🐦 Media URL: {media_url}")
            logger.info(f"🐦 User ID: {user_id}")
            logger.info(f"🐦 Platform data: {platform}")
            
            # Get OAuth 1.0a tokens from social connections
            logger.info(f"🐦 Attempting to get OAuth 1.0a tokens...")
            oauth1_tokens = await self._get_oauth1_tokens('twitter', platform, user_id)
            
            if not oauth1_tokens:
                logger.error(f"🚨 CRITICAL: No OAuth 1.0a tokens found!")
                logger.error(f"🚨 User needs to complete OAuth 1.0a authentication for media uploads")
                logger.error(f"🚨 This means the TwitterOAuth1Button flow needs to be completed")
                logger.error(f"🚨 Media upload will fail - returning None")
                return None
            
            logger.info(f"✅ Successfully retrieved OAuth 1.0a tokens!")
            logger.info(f"🐦 Twitter user: {oauth1_tokens.get('screen_name')} (ID: {oauth1_tokens.get('user_id')})")
            logger.info(f"🐦 Access token preview: {oauth1_tokens.get('access_token', '')[:20]}...")
            
            # Download media first
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                media_response = await client.get(media_url)
                if media_response.status_code != 200:
                    logger.error(f"🐦 Failed to download media from {media_url}")
                    return None
                
                media_data = media_response.content
                media_size = len(media_data)
                
                # Determine media type from URL or content
                content_type = media_response.headers.get('content-type', 'application/octet-stream')
                is_video = 'video' in content_type or media_url.lower().endswith(('.mp4', '.mov', '.avi'))
                is_gif = media_url.lower().endswith('.gif') or 'image/gif' in content_type
                
                # Validate file size based on X API limits
                if is_video and media_size > 512 * 1024 * 1024:  # 512MB for video
                    logger.error(f"🐦 Video file too large: {media_size / 1024 / 1024:.2f}MB (max 512MB)")
                    return None
                elif is_gif and media_size > 15 * 1024 * 1024:  # 15MB for GIF
                    logger.error(f"🐦 GIF file too large: {media_size / 1024 / 1024:.2f}MB (max 15MB)")
                    return None
                elif not is_video and not is_gif and media_size > 5 * 1024 * 1024:  # 5MB for images
                    logger.error(f"🐦 Image file too large: {media_size / 1024 / 1024:.2f}MB (max 5MB)")
                    return None
                
                # Use chunked upload for videos or files > 5MB, simple upload for smaller images
                if is_video or media_size > 5 * 1024 * 1024:
                    logger.info(f"🐦 Using chunked upload for {media_size / 1024 / 1024:.2f}MB file")
                    return await self._upload_twitter_media_chunked(
                        media_data, content_type, oauth1_tokens, is_video
                    )
                else:
                    # Simple upload for small images
                    logger.info(f"🐦 Using simple upload for {media_size / 1024:.2f}KB image")
                    
                    # Generate OAuth 1.0a signature for media upload using user's tokens
                    logger.info(f"🔐 Generating OAuth header with user-specific tokens")
                    logger.info(f"🔐 Access token preview: {oauth1_tokens['access_token'][:20]}...")
                    logger.info(f"🔐 Access token secret preview: {oauth1_tokens['access_token_secret'][:10]}...")
                    logger.info(f"🔐 User ID: {oauth1_tokens.get('user_id')}")
                    logger.info(f"🔐 Screen name: {oauth1_tokens.get('screen_name')}")
                    
                    oauth_header = self._generate_oauth1_header_user_tokens(
                        method="POST",
                        url="https://upload.twitter.com/1.1/media/upload.json",
                        oauth_token=oauth1_tokens['access_token'],
                        oauth_token_secret=oauth1_tokens['access_token_secret']
                    )
                    logger.info(f"🔐 Generated OAuth header (preview): {oauth_header[:100]}...")
                    
                    # Verify we're not using environment variable tokens
                    if oauth1_tokens['access_token'] == os.getenv('TWITTER_ACCESS_TOKEN'):
                        logger.error(f"🚨 ERROR: Using environment variable token instead of user token!")
                        logger.error(f"🚨 This should not happen - check token retrieval logic")
                    else:
                        logger.info(f"✅ Confirmed using user-specific OAuth 1.0a tokens (not environment variables)")
                    
                    headers = {
                        "Authorization": oauth_header
                    }
                    
                    files = {"media": media_data}
                    
                    logger.info(f"🐦 Uploading media using OAuth 1.0a authentication")
                    logger.info(f"🐦 Using tokens for user: {oauth1_tokens.get('screen_name')} ({oauth1_tokens.get('user_id')})")
                    logger.info(f"🐦 Media size: {len(media_data) / 1024:.2f}KB")
                    
                    upload_response = await client.post(
                        "https://upload.twitter.com/1.1/media/upload.json",
                        headers=headers,
                        files=files
                    )
                    
                    if upload_response.status_code == 200:
                        upload_data = upload_response.json()
                        media_id = upload_data.get("media_id_string")
                        logger.info(f"🐦 Media uploaded successfully with OAuth 1.0a! Media ID: {media_id}")
                        return media_id
                    else:
                        error_data = upload_response.text
                        logger.error(f"🐦 Media upload failed - Status: {upload_response.status_code}")
                        logger.error(f"🐦 Error response: {error_data}")
                        logger.error(f"🐦 Request headers: {headers}")
                        logger.error(f"🐦 Content-Type: {content_type}")
                        
                        # Try to parse error JSON if possible
                        try:
                            error_json = upload_response.json()
                            logger.error(f"🐦 Detailed error: {error_json}")
                        except:
                            pass
                        
                        return None
                    
        except Exception as e:
            logger.error(f"🐦 Error uploading media to Twitter: {str(e)}")
            
        return None
    
    async def _upload_twitter_media_chunked(self, media_data: bytes, content_type: str, oauth1_tokens: Dict[str, str], is_video: bool = False) -> Optional[str]:
        """Upload media to Twitter using chunked upload API (for videos and large files)"""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                media_size = len(media_data)
                
                # Determine media category based on content type
                if is_video:
                    media_category = "tweet_video"
                else:
                    media_category = "tweet_image"
                
                # Step 1: INIT - Initialize upload
                logger.info(f"🐦 INIT: Initializing chunked upload for {media_size / 1024 / 1024:.2f}MB {media_category}")
                
                init_params = {
                    "command": "INIT",
                    "total_bytes": str(media_size),
                    "media_type": content_type,
                    "media_category": media_category
                }
                
                init_oauth_header = self._generate_oauth1_header_user_tokens(
                    method="POST",
                    url="https://upload.twitter.com/1.1/media/upload.json",
                    oauth_token=oauth1_tokens['access_token'],
                    oauth_token_secret=oauth1_tokens['access_token_secret'],
                    params=init_params
                )
                
                init_response = await client.post(
                    "https://upload.twitter.com/1.1/media/upload.json",
                    headers={"Authorization": init_oauth_header},
                    data=init_params
                )
                
                if init_response.status_code != 200:
                    logger.error(f"🐦 INIT failed: {init_response.status_code} - {init_response.text}")
                    return None
                
                init_data = init_response.json()
                media_id = init_data.get("media_id_string")
                logger.info(f"🐦 INIT successful: media_id={media_id}")
                
                # Step 2: APPEND - Upload chunks
                chunk_size = 5 * 1024 * 1024  # 5MB chunks
                total_chunks = (media_size + chunk_size - 1) // chunk_size
                
                for segment_index in range(total_chunks):
                    start = segment_index * chunk_size
                    end = min(start + chunk_size, media_size)
                    chunk = media_data[start:end]
                    
                    logger.info(f"🐦 APPEND: Uploading chunk {segment_index + 1}/{total_chunks} ({len(chunk) / 1024 / 1024:.2f}MB)")
                    
                    append_params = {
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(segment_index)
                    }
                    
                    append_oauth_header = self._generate_oauth1_header_user_tokens(
                        method="POST",
                        url="https://upload.twitter.com/1.1/media/upload.json",
                        oauth_token=oauth1_tokens['access_token'],
                        oauth_token_secret=oauth1_tokens['access_token_secret'],
                        params=append_params
                    )
                    
                    # Use multipart/form-data for chunk upload
                    files = {"media": chunk}
                    
                    append_response = await client.post(
                        "https://upload.twitter.com/1.1/media/upload.json",
                        headers={"Authorization": append_oauth_header},
                        data=append_params,
                        files=files
                    )
                    
                    if append_response.status_code != 204:
                        logger.error(f"🐦 APPEND failed for chunk {segment_index}: {append_response.status_code}")
                        return None
                
                # Step 3: FINALIZE - Complete upload
                logger.info(f"🐦 FINALIZE: Completing upload")
                
                finalize_params = {
                    "command": "FINALIZE",
                    "media_id": media_id
                }
                
                finalize_oauth_header = self._generate_oauth1_header_user_tokens(
                    method="POST",
                    url="https://upload.twitter.com/1.1/media/upload.json",
                    oauth_token=oauth1_tokens['access_token'],
                    oauth_token_secret=oauth1_tokens['access_token_secret'],
                    params=finalize_params
                )
                
                finalize_response = await client.post(
                    "https://upload.twitter.com/1.1/media/upload.json",
                    headers={"Authorization": finalize_oauth_header},
                    data=finalize_params
                )
                
                if finalize_response.status_code != 201:
                    logger.error(f"🐦 FINALIZE failed: {finalize_response.status_code} - {finalize_response.text}")
                    return None
                
                finalize_data = finalize_response.json()
                
                # Step 4: STATUS - Check processing status (for videos)
                if "processing_info" in finalize_data:
                    processing_info = finalize_data["processing_info"]
                    state = processing_info.get("state", "")
                    
                    if state == "pending" or state == "in_progress":
                        logger.info(f"🐦 STATUS: Media processing {state}...")
                        check_after_secs = processing_info.get("check_after_secs", 1)
                        
                        # Poll for status
                        max_attempts = 30
                        for attempt in range(max_attempts):
                            await asyncio.sleep(check_after_secs)
                            
                            status_params = {
                                "command": "STATUS",
                                "media_id": media_id
                            }
                            
                            status_oauth_header = self._generate_oauth1_header_user_tokens(
                                method="GET",
                                url="https://upload.twitter.com/1.1/media/upload.json",
                                oauth_token=oauth1_tokens['access_token'],
                                oauth_token_secret=oauth1_tokens['access_token_secret'],
                                params=status_params
                            )
                            
                            status_response = await client.get(
                                "https://upload.twitter.com/1.1/media/upload.json",
                                headers={"Authorization": status_oauth_header},
                                params=status_params
                            )
                            
                            if status_response.status_code == 200:
                                status_data = status_response.json()
                                processing_info = status_data.get("processing_info", {})
                                state = processing_info.get("state", "")
                                
                                if state == "succeeded":
                                    logger.info(f"🐦 Media processing complete!")
                                    break
                                elif state == "failed":
                                    error = processing_info.get("error", {})
                                    logger.error(f"🐦 Media processing failed: {error}")
                                    return None
                                else:
                                    check_after_secs = processing_info.get("check_after_secs", 1)
                
                logger.info(f"🐦 Chunked upload successful! Media ID: {media_id}")
                return media_id
                
        except Exception as e:
            logger.error(f"🐦 Error in chunked media upload: {str(e)}")
            return None
    
    async def _get_oauth1_tokens(self, provider: str, platform: Dict[str, Any] = None, user_id: int = None) -> Optional[Dict[str, str]]:
        """Get OAuth 1.0a tokens from social connections using dedicated database columns"""
        try:
            logger.info(f"🔍 _get_oauth1_tokens called with provider={provider}, user_id={user_id}")
            logger.info(f"🔍 Platform data received: {platform}")
            
            # Get provider account ID from platform data
            provider_account_id = platform.get('accountId') if platform else None
            logger.info(f"🔍 Provider account ID: {provider_account_id}")
            
            # Convert account_id to string for consistent comparison
            account_id_str = str(provider_account_id) if provider_account_id else None
            
            # Query for OAuth 1.0a tokens using dedicated columns
            query = self.db.table('social_connections').select('oauth1_access_token, oauth1_access_token_secret, oauth1_user_id, oauth1_screen_name, oauth1_created_at, provider_account_id, account_label').eq('provider', provider)
            
            if user_id:
                query = query.eq('user_id', user_id)
            
            if account_id_str:
                query = query.eq('provider_account_id', account_id_str)
            else:
                # If no specific account ID, get primary connection
                query = query.order('is_primary desc, created_at asc').limit(1)
            
            logger.info(f"🔍 Executing database query for OAuth 1.0a tokens: user_id={user_id}, provider={provider}, provider_account_id={account_id_str}")
            response = query.execute()
            
            logger.info(f"🔍 Database response: {len(response.data) if response.data else 0} connections found")
            
            if not response.data:
                logger.warning(f"🐦 No {provider} connection found for user {user_id}")
                
                # Debug: List all connections for this user
                debug_query = self.db.table('social_connections').select('provider, provider_account_id, account_label').eq('user_id', user_id)
                debug_response = debug_query.execute()
                logger.warning(f"🔍 All connections for user {user_id}: {debug_response.data}")
                
                return None
            
            # Get the first (and should be only) connection
            connection = response.data[0]
            found_account_id = connection.get('provider_account_id')
            account_label = connection.get('account_label', 'unknown')
            
            logger.info(f"🔍 Found connection: account_id={found_account_id}, label={account_label}")
            
            # Check if OAuth 1.0a tokens exist in dedicated columns
            oauth1_access_token = connection.get('oauth1_access_token')
            oauth1_access_token_secret = connection.get('oauth1_access_token_secret')
            
            if not oauth1_access_token or not oauth1_access_token_secret:
                logger.warning(f"🐦 No OAuth 1.0a tokens found in dedicated columns for {provider} account {found_account_id}")
                logger.warning(f"🔍 oauth1_access_token present: {bool(oauth1_access_token)}")
                logger.warning(f"🔍 oauth1_access_token_secret present: {bool(oauth1_access_token_secret)}")
                return None
            
            logger.info(f"✅ Found OAuth 1.0a tokens in dedicated columns")
            
            # Decrypt tokens
            from app.utils.encryption import decrypt_token
            
            try:
                decrypted_tokens = {
                    'access_token': decrypt_token(oauth1_access_token),
                    'access_token_secret': decrypt_token(oauth1_access_token_secret),
                    'user_id': connection.get('oauth1_user_id'),
                    'screen_name': connection.get('oauth1_screen_name')
                }
                
                logger.info(f"🐦 Successfully retrieved and decrypted OAuth 1.0a tokens from dedicated columns for {provider} user {decrypted_tokens['screen_name']} (account: {found_account_id})")
                logger.info(f"🔍 Decrypted token preview: {decrypted_tokens['access_token'][:20]}...") 
                
                return decrypted_tokens
                
            except Exception as decrypt_error:
                logger.error(f"🐦 Failed to decrypt OAuth 1.0a tokens from dedicated columns: {str(decrypt_error)}")
                logger.error(f"🔍 Raw tokens - access_token length: {len(oauth1_access_token) if oauth1_access_token else 0}")
                logger.error(f"🔍 Raw tokens - access_token_secret length: {len(oauth1_access_token_secret) if oauth1_access_token_secret else 0}")
                return None
                
        except Exception as e:
            logger.error(f"🐦 Error getting OAuth 1.0a tokens: {str(e)}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            return None
    
    def _generate_oauth1_header_user_tokens(self, method: str, url: str, oauth_token: str, oauth_token_secret: str, params: dict = None) -> str:
        """Generate OAuth 1.0a Authorization header for X API media upload"""
        if params is None:
            params = {}
        
        # Generate OAuth parameters
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        
        consumer_key = os.getenv('TWITTER_CONSUMER_API_KEY')
        consumer_secret = os.getenv('TWITTER_CONSUMER_API_SECRET')
        
        # OAuth base parameters
        oauth_params = {
            'oauth_consumer_key': consumer_key,
            'oauth_nonce': nonce,
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': timestamp,
            'oauth_token': oauth_token,
            'oauth_version': '1.0'
        }
        
        # Combine all parameters for signature generation
        all_params = {**params, **oauth_params}
        
        # Sort parameters
        sorted_params = sorted(all_params.items())
        
        # Create parameter string
        param_string = '&'.join([f"{urllib.parse.quote_plus(str(k))}={urllib.parse.quote_plus(str(v))}" for k, v in sorted_params])
        
        # Create signature base string
        base_string = f"{method.upper()}&{urllib.parse.quote_plus(url)}&{urllib.parse.quote_plus(param_string)}"
        
        # Create signing key
        signing_key = f"{urllib.parse.quote_plus(consumer_secret)}&{urllib.parse.quote_plus(oauth_token_secret)}"
        
        # Generate signature
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        ).decode()
        
        # Add signature to OAuth parameters
        oauth_params['oauth_signature'] = signature
        
        # Create OAuth header string
        oauth_string = ', '.join([f'{k}="{urllib.parse.quote(str(v))}"' for k, v in sorted(oauth_params.items())])
        return f"OAuth {oauth_string}"

    async def _upload_linkedin_media(self, client: httpx.AsyncClient, access_token: str, media_url: str, author_urn: str) -> Optional[str]:
        """Upload media to LinkedIn and return the asset URN"""
        try:
            logger.info(f"LinkedIn: Starting media upload process for {media_url}")
            
            # Step 1: Download the media from CDN
            media_response = await client.get(media_url)
            if media_response.status_code != 200:
                logger.error(f"LinkedIn: Failed to download media from {media_url}")
                return None
            
            media_content = media_response.content
            media_size = len(media_content)
            content_type = media_response.headers.get('content-type', 'image/jpeg')
            
            logger.info(f"LinkedIn: Downloaded media, size: {media_size} bytes, type: {content_type}")
            
            # Determine the appropriate recipe based on content type
            is_video = content_type.startswith('video/')
            recipe = "urn:li:digitalmediaRecipe:feedshare-video" if is_video else "urn:li:digitalmediaRecipe:feedshare-image"
            
            logger.info(f"LinkedIn: Using recipe: {recipe}")
            
            # Step 2: Register upload with LinkedIn
            register_upload_request = {
                "registerUploadRequest": {
                    "recipes": [recipe],
                    "owner": author_urn,
                    "serviceRelationships": [{
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent"
                    }]
                }
            }
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            }
            
            register_response = await client.post(
                "https://api.linkedin.com/v2/assets?action=registerUpload",
                headers=headers,
                json=register_upload_request
            )
            
            if register_response.status_code not in [200, 201]:
                logger.error(f"LinkedIn: Failed to register upload: {register_response.text}")
                return None
            
            register_data = register_response.json()
            upload_url = register_data['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
            asset_urn = register_data['value']['asset']
            
            logger.info(f"LinkedIn: Registered upload, asset URN: {asset_urn}")
            
            # Step 3: Upload the media to LinkedIn's servers
            upload_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": content_type
            }
            
            upload_response = await client.put(
                upload_url,
                headers=upload_headers,
                content=media_content
            )
            
            if upload_response.status_code not in [200, 201]:
                logger.error(f"LinkedIn: Failed to upload media: {upload_response.text}")
                return None
            
            logger.info(f"LinkedIn: Media uploaded successfully")
            
            # Step 4: Check upload status (optional but recommended)
            status_check_url = f"https://api.linkedin.com/v2/assets/{asset_urn.split(':')[-1]}"
            status_headers = {
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0"
            }
            
            # Wait a moment for processing
            await asyncio.sleep(2)
            
            status_response = await client.get(status_check_url, headers=status_headers)
            if status_response.status_code == 200:
                status_data = status_response.json()
                upload_status = status_data.get('recipes', [{}])[0].get('status', 'UNKNOWN')
                logger.info(f"LinkedIn: Upload status: {upload_status}")
                
                if upload_status == 'AVAILABLE':
                    return asset_urn
                else:
                    # Even if not immediately available, LinkedIn often processes it quickly
                    # Return the URN anyway as it usually works
                    logger.warning(f"LinkedIn: Media still processing, but returning URN anyway")
                    return asset_urn
            else:
                # If we can't check status, assume it's okay and return the URN
                logger.warning(f"LinkedIn: Could not check upload status, but returning URN anyway")
                return asset_urn
                
        except Exception as e:
            logger.error(f"LinkedIn: Error uploading media: {str(e)}")
            return None

    async def _publish_to_linkedin(
        self, 
        access_token: str, 
        content: PlatformContent, 
        platform: Dict[str, Any]
    ) -> PublishResult:
        """Publish to LinkedIn"""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            }
            
            # Determine if this is a personal or organization post
            account_type = platform.get('account_type', 'personal')
            
            # Check account_type in nested metadata if not found at top level
            if account_type == 'personal' and platform.get('metadata', {}).get('profile', {}).get('account_type'):
                account_type = platform.get('metadata', {}).get('profile', {}).get('account_type')
            
            account_id = platform.get('accountId')
            
            if account_type == 'business':
                # Organization post
                author_urn = f"urn:li:organization:{account_id}"
            else:
                # Personal post - need to get person URN
                author_urn = f"urn:li:person:{account_id}"
            
            post_text = content.content
            if content.hashtags:
                post_text += "\n\n" + " ".join([f"#{tag}" for tag in content.hashtags])
            
            share_content = {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": post_text},
                        "shareMediaCategory": "NONE"
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                }
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Handle media if present
                if content.media_urls:
                    logger.info(f"LinkedIn: Uploading {len(content.media_urls)} media files")
                    
                    # LinkedIn only supports single media per post
                    media_url = content.media_urls[0]
                    if len(content.media_urls) > 1:
                        logger.warning(f"LinkedIn only supports single media per post, using first media file")
                    
                    # Upload media to LinkedIn and get URN
                    media_urn = await self._upload_linkedin_media(client, access_token, media_url, author_urn)
                    
                    if media_urn:
                        # Detect media type from metadata or URL
                        media_objects = content.metadata.get('media_objects', []) if content.metadata else []
                        is_video = False
                        
                        if media_objects and len(media_objects) > 0:
                            media_obj = media_objects[0]
                            obj_type = media_obj.get('type', '').lower()
                            file_type = media_obj.get('file_type', '').lower()
                            is_video = obj_type == 'video' or file_type.startswith('video/')
                        
                        # Fallback to URL check
                        if not is_video and isinstance(media_url, str):
                            is_video = any(media_url.lower().endswith(ext) for ext in ['.mp4', '.mov', '.mpeg4', '.avi'])
                        
                        # Update share content with media URN
                        media_category = "VIDEO" if is_video else "IMAGE"
                        share_content["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = media_category
                        share_content["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [{
                            "status": "READY",
                            "description": {"text": ""},
                            "media": media_urn,  # Use the URN instead of URL
                            "title": {"text": ""}
                        }]
                        logger.info(f"LinkedIn: Media uploaded successfully as {media_category}, URN: {media_urn}")
                    else:
                        logger.warning(f"LinkedIn: Failed to upload media, posting text-only")
                        # Continue with text-only post
                
                # Post to LinkedIn
                response = await client.post(
                    "https://api.linkedin.com/v2/ugcPosts",
                    headers=headers,
                    json=share_content
                )
                
                if response.status_code in [200, 201]:
                    response_data = response.json()
                    post_id = response_data.get("id")
                    
                    return PublishResult(
                        platform="linkedin",
                        status=PublishStatus.SUCCESS,
                        platform_post_id=post_id,
                        metadata={"linkedin_data": response_data}
                    )
                else:
                    return PublishResult(
                        platform="linkedin",
                        status=PublishStatus.FAILED,
                        error_message=f"LinkedIn API error: {response.text}"
                    )
                    
        except Exception as e:
            return PublishResult(
                platform="linkedin",
                status=PublishStatus.FAILED,
                error_message=f"LinkedIn publishing error: {str(e)}"
            )

    async def _publish_to_facebook(
        self, 
        access_token: str, 
        content: PlatformContent, 
        platform: Dict[str, Any]
    ) -> PublishResult:
        """Publish to Facebook"""
        try:
            account_id = platform.get('accountId')
            account_type = platform.get('account_type', 'personal')
            account_label = platform.get('displayName', 'Unknown')
            
            logger.info(f"Publishing to Facebook account: {account_label} (ID: {account_id}, Type: {account_type})")
            
            # Determine endpoint based on account type
            if account_type == 'page':
                # Post to Facebook page
                endpoint = f"https://graph.facebook.com/v23.0/{account_id}/feed"
            else:
                # Post to personal feed
                endpoint = f"https://graph.facebook.com/v23.0/{account_id}/feed"
            
            post_text = content.content
            if content.hashtags:
                post_text += "\n\n" + " ".join([f"#{tag}" for tag in content.hashtags])
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Handle media by uploading directly to Facebook
                if content.media_urls:
                    # Upload image(s) and create post with photo
                    return await self._publish_facebook_with_photos(
                        client, endpoint, access_token, post_text, content.media_urls, account_label
                    )
                else:
                    # Text-only post
                    return await self._publish_facebook_text_only(
                        client, endpoint, access_token, post_text, account_label
                    )
                    
        except Exception as e:
            logger.error(f"Facebook publishing error for {account_label}: {str(e)}")
            return PublishResult(
                platform="facebook",
                status=PublishStatus.FAILED,
                error_message=f"Facebook publishing error: {str(e)}"
            )

    async def _publish_facebook_text_only(
        self, 
        client: httpx.AsyncClient, 
        endpoint: str, 
        access_token: str, 
        message: str,
        account_label: str
    ) -> PublishResult:
        """Publish text-only post to Facebook"""
        try:
            post_data = {
                "message": message,
                "access_token": access_token
            }
            
            response = await client.post(endpoint, data=post_data)
            
            if response.status_code == 200:
                response_data = response.json()
                post_id = response_data.get("id")
                logger.info(f"✅ Successfully posted text to Facebook {account_label}: {post_id}")
                
                return PublishResult(
                    platform="facebook",
                    status=PublishStatus.SUCCESS,
                    platform_post_id=post_id,
                    metadata={"facebook_data": response_data, "account_label": account_label}
                )
            else:
                logger.error(f"❌ Facebook API error for {account_label}: {response.text}")
                return PublishResult(
                    platform="facebook",
                    status=PublishStatus.FAILED,
                    error_message=f"Facebook API error for {account_label}: {response.text}"
                )
        except Exception as e:
            logger.error(f"Error posting text to Facebook {account_label}: {str(e)}")
            return PublishResult(
                platform="facebook",
                status=PublishStatus.FAILED,
                error_message=f"Error posting to {account_label}: {str(e)}"
            )

    async def _publish_facebook_with_photos(
        self, 
        client: httpx.AsyncClient, 
        endpoint: str, 
        access_token: str, 
        message: str,
        media_urls: List[str],
        account_label: str
    ) -> PublishResult:
        """Publish post with photos to Facebook by uploading images directly"""
        try:
            page_id = endpoint.split('/')[-2]  # Extract page ID from endpoint
            
            # For single image, upload directly and create post
            if len(media_urls) == 1:
                media_url = media_urls[0]
                logger.info(f"Uploading single image to Facebook {account_label}: {media_url}")
                
                # Download the image first
                media_response = await client.get(media_url)
                if media_response.status_code != 200:
                    return PublishResult(
                        platform="facebook",
                        status=PublishStatus.FAILED,
                        error_message=f"Failed to download image from {media_url}"
                    )
                
                image_data = media_response.content
                
                # Determine content type from the response or URL
                content_type = media_response.headers.get('content-type', 'image/jpeg')
                
                # Upload image using the photos endpoint
                upload_endpoint = f"https://graph.facebook.com/v23.0/{page_id}/photos"
                
                files = {
                    'source': ('image.jpg', image_data, content_type)
                }
                
                upload_data = {
                    'message': message,
                    'access_token': access_token,
                    'published': 'true'  # Publish immediately
                }
                
                upload_response = await client.post(upload_endpoint, files=files, data=upload_data)
                
                if upload_response.status_code == 200:
                    upload_result = upload_response.json()
                    photo_id = upload_result.get("id")
                    post_id = upload_result.get("post_id", photo_id)
                    
                    logger.info(f"✅ Successfully posted image to Facebook {account_label}: {post_id}")
                    
                    return PublishResult(
                        platform="facebook",
                        status=PublishStatus.SUCCESS,
                        platform_post_id=post_id,
                        metadata={
                            "facebook_data": upload_result, 
                            "account_label": account_label,
                            "photo_id": photo_id
                        }
                    )
                else:
                    logger.error(f"❌ Facebook image upload error for {account_label}: {upload_response.text}")
                    return PublishResult(
                        platform="facebook",
                        status=PublishStatus.FAILED,
                        error_message=f"Facebook image upload error for {account_label}: {upload_response.text}"
                    )
            
            else:
                # Multiple images - upload each as unpublished, then create multi-photo post
                logger.info(f"Uploading {len(media_urls)} images to Facebook {account_label}")
                
                photo_ids = []
                failed_uploads = []
                
                # Step 1: Upload each photo as unpublished
                for idx, media_url in enumerate(media_urls):
                    try:
                        logger.info(f"Uploading image {idx + 1}/{len(media_urls)}: {media_url}")
                        
                        # Download the image
                        media_response = await client.get(media_url)
                        if media_response.status_code != 200:
                            failed_uploads.append(f"Failed to download image {idx + 1}")
                            continue
                        
                        image_data = media_response.content
                        content_type = media_response.headers.get('content-type', 'image/jpeg')
                        
                        # Upload as unpublished photo
                        upload_endpoint = f"https://graph.facebook.com/v23.0/{page_id}/photos"
                        
                        files = {
                            'source': (f'image_{idx}.jpg', image_data, content_type)
                        }
                        
                        upload_data = {
                            'access_token': access_token,
                            'published': 'false'  # Keep unpublished for multi-photo post
                        }
                        
                        upload_response = await client.post(upload_endpoint, files=files, data=upload_data)
                        
                        if upload_response.status_code == 200:
                            upload_result = upload_response.json()
                            photo_id = upload_result.get("id")
                            if photo_id:
                                photo_ids.append(photo_id)
                                logger.info(f"✅ Uploaded photo {idx + 1}: {photo_id}")
                        else:
                            failed_uploads.append(f"Failed to upload image {idx + 1}: {upload_response.text}")
                            logger.error(f"Failed to upload image {idx + 1}: {upload_response.text}")
                            
                    except Exception as e:
                        failed_uploads.append(f"Error uploading image {idx + 1}: {str(e)}")
                        logger.error(f"Error uploading image {idx + 1}: {str(e)}")
                
                # Check if we have any photos to publish
                if not photo_ids:
                    return PublishResult(
                        platform="facebook",
                        status=PublishStatus.FAILED,
                        error_message=f"Failed to upload any images. Errors: {'; '.join(failed_uploads)}"
                    )
                
                # Step 2: Create multi-photo post with uploaded photos
                try:
                    # Prepare attached_media parameter
                    attached_media = [{"media_fbid": photo_id} for photo_id in photo_ids]
                    
                    post_data = {
                        'message': message,
                        'attached_media': json.dumps(attached_media),
                        'access_token': access_token
                    }
                    
                    logger.info(f"Creating multi-photo post with {len(photo_ids)} photos")
                    
                    # Create the multi-photo post
                    post_response = await client.post(endpoint, data=post_data)
                    
                    if post_response.status_code == 200:
                        post_result = post_response.json()
                        post_id = post_result.get("id")
                        
                        logger.info(f"✅ Successfully created multi-photo post on Facebook {account_label}: {post_id}")
                        
                        return PublishResult(
                            platform="facebook",
                            status=PublishStatus.SUCCESS,
                            platform_post_id=post_id,
                            metadata={
                                "facebook_data": post_result,
                                "account_label": account_label,
                                "photo_ids": photo_ids,
                                "total_photos": len(photo_ids),
                                "failed_uploads": failed_uploads
                            }
                        )
                    else:
                        logger.error(f"❌ Failed to create multi-photo post: {post_response.text}")
                        return PublishResult(
                            platform="facebook",
                            status=PublishStatus.FAILED,
                            error_message=f"Failed to create multi-photo post: {post_response.text}"
                        )
                        
                except Exception as e:
                    logger.error(f"Error creating multi-photo post: {str(e)}")
                    return PublishResult(
                        platform="facebook",
                        status=PublishStatus.FAILED,
                        error_message=f"Error creating multi-photo post: {str(e)}"
                    )
                
        except Exception as e:
            logger.error(f"Error uploading images to Facebook {account_label}: {str(e)}")
            return PublishResult(
                platform="facebook",
                status=PublishStatus.FAILED,
                error_message=f"Error uploading to {account_label}: {str(e)}"
            )

    async def _publish_to_instagram(
        self, 
        access_token: str, 
        content: PlatformContent, 
        platform: Dict[str, Any]
    ) -> PublishResult:
        """Publish to Instagram (requires business account)"""
        logger.warning(f"📸📸📸 _publish_to_instagram called!")
        logger.warning(f"📸 Content object: {content}")
        logger.warning(f"📸 Content media_urls: {content.media_urls}")
        logger.warning(f"📸 Content has {len(content.media_urls) if content.media_urls else 0} media URLs")
        print(f"📸📸📸 INSTAGRAM PUBLISHER CALLED!")
        
        try:
            account_id = platform.get('accountId')
            
            # Instagram requires media for posts
            if not content.media_urls:
                return PublishResult(
                    platform="instagram",
                    status=PublishStatus.FAILED,
                    error_message="Instagram posts require media (image or video). No valid media files were found with completed processing status and CDN URLs."
                )
            
            post_text = content.content
            if content.hashtags:
                post_text += "\n\n" + " ".join([f"#{tag}" for tag in content.hashtags])
            
            # Get media objects from metadata for type detection
            media_objects = content.metadata.get('media_objects', []) if content.metadata else []
            
            # Debug logging
            logger.warning(f"🔍 Instagram publishing debug:")
            logger.warning(f"  📱 Media URLs count: {len(content.media_urls)}")
            logger.warning(f"  📱 Media URLs: {content.media_urls}")
            logger.warning(f"  📁 Media objects count: {len(media_objects)}")
            logger.warning(f"  📁 Media objects: {media_objects}")
            
            # Check if we have media at all
            if not content.media_urls:
                logger.warning(f"⚠️ No media URLs found for Instagram publishing!")
                return PublishResult(
                    platform="instagram",
                    status=PublishStatus.FAILED,
                    error_message="No media URLs provided - Instagram requires media for publishing"
                )
            
            # Check if single or multiple media
            if len(content.media_urls) == 1:
                # Single media post - detect if image or video
                media_url = content.media_urls[0]
                media_type = 'image'
                
                # Video detection from media object
                logger.warning(f"🎬 Starting video detection for single media")
                if media_objects and len(media_objects) > 0:
                    media_obj = media_objects[0]
                    logger.warning(f"🎬 Media object found: {media_obj}")
                    
                    # Check multiple possible video indicators
                    obj_type = media_obj.get('type', '').lower()
                    file_type = media_obj.get('file_type', '').lower()
                    mime_type = media_obj.get('mime_type', '').lower()
                    original_filename = media_obj.get('original_filename', '').lower()
                    
                    logger.warning(f"🎬 Video detection values:")
                    logger.warning(f"  - obj_type: '{obj_type}' (is 'video'? {obj_type == 'video'})")
                    logger.warning(f"  - file_type: '{file_type}' (starts with 'video/'? {file_type.startswith('video/')})")
                    logger.warning(f"  - mime_type: '{mime_type}' (starts with 'video/'? {mime_type.startswith('video/')})")
                    logger.warning(f"  - original_filename: '{original_filename}'")
                    
                    if (obj_type == 'video' or 
                        file_type.startswith('video/') or 
                        mime_type.startswith('video/') or
                        any(original_filename.endswith(ext) for ext in ['.mp4', '.mov', '.mpeg4', '.avi', '.mkv'])):
                        media_type = 'video'
                        logger.warning(f"✅ DETECTED AS VIDEO! - type: {obj_type}, file_type: {file_type}")
                    else:
                        media_type = 'image'
                        logger.warning(f"❌ DETECTED AS IMAGE! - type: {obj_type}, file_type: {file_type}")
                else:
                    logger.warning(f"🎬 No media objects found for video detection")
                
                # Fallback to URL extension check
                if media_type == 'image' and isinstance(media_url, str):
                    if any(media_url.lower().endswith(ext) for ext in ['.mp4', '.mov', '.mpeg4', '.avi', '.mkv']):
                        media_type = 'video'
                        logger.info(f"Detected video file from URL extension: {media_url}")
                
                logger.warning(f"🎯 Final media type determination: {media_type}")
                logger.warning(f"🎯 About to call _publish_instagram_single_media with:")
                logger.warning(f"  - media_url: {media_url}")
                logger.warning(f"  - media_type: {media_type}")
                        
                return await self._publish_instagram_single_media(
                    account_id, access_token, media_url, post_text, media_type
                )
            else:
                # Multiple media - check if any videos are included
                has_video = False
                
                # Check from media objects
                for i, media_obj in enumerate(media_objects[:len(content.media_urls)]):
                    if media_obj.get('type') == 'video' or media_obj.get('file_type', '').startswith('video/'):
                        has_video = True
                        break
                
                # Fallback to URL extension check
                if not has_video:
                    for media_url in content.media_urls:
                        if isinstance(media_url, str) and any(media_url.lower().endswith(ext) for ext in ['.mp4', '.mov', '.mpeg4']):
                            has_video = True
                            break
                
                if has_video:
                    # Instagram doesn't support mixed media carousels with videos
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.FAILED,
                        error_message="Instagram carousels don't support videos. Please post videos individually or use only images for carousel posts."
                    )
                
                # Multiple images - use carousel
                return await self._publish_instagram_carousel(
                    account_id, access_token, content.media_urls, post_text
                )
                    
        except Exception as e:
            return PublishResult(
                platform="instagram",
                status=PublishStatus.FAILED,
                error_message=f"Instagram publishing error: {str(e)}"
            )

    async def _publish_instagram_single_media(
        self, 
        account_id: str, 
        access_token: str, 
        media_url: str, 
        caption: str,
        media_type: str = 'image',  # 'image' or 'video'
        as_reel: bool = False  # Whether to post video as Reel
    ) -> PublishResult:
        """Publish single media to Instagram"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Step 1: Create media container
                container_data = {
                    "caption": caption,
                    "access_token": access_token
                }
                
                # Set appropriate parameters based on media type
                logger.warning(f"🎥 Setting container parameters for media_type: {media_type}")
                
                if media_type == 'video':
                    logger.warning(f"🎥 SETTING VIDEO PARAMETERS")
                    if not media_url:
                        return PublishResult(
                            platform="instagram",
                            status=PublishStatus.FAILED,
                            error_message="No video URL provided for Instagram video post"
                        )
                    
                    container_data["video_url"] = media_url
                    logger.warning(f"🎥 Set video_url in container: {media_url}")
                    
                    # Instagram requires media_type for ALL videos
                    if as_reel:
                        # Post as Instagram Reel
                        container_data["media_type"] = "REELS"
                        logger.warning(f"🎥 Creating Instagram REELS container with video URL: {media_url}")
                    else:
                        # Instagram no longer supports feed videos - must be REELS
                        container_data["media_type"] = "REELS"
                        logger.warning(f"🎥 Creating Instagram REELS container (default for all videos) with video URL: {media_url}")
                        logger.warning(f"🎥 Note: Instagram requires all videos to be posted as REELS")
                    
                    # Validate video URL is accessible
                    try:
                        # Quick HEAD request to check if URL is accessible
                        head_response = await client.head(media_url, timeout=10.0)
                        if head_response.status_code >= 400:
                            logger.error(f"Video URL not accessible: {media_url}, status: {head_response.status_code}")
                            return PublishResult(
                                platform="instagram",
                                status=PublishStatus.FAILED,
                                error_message=f"Video URL not accessible (HTTP {head_response.status_code}). Instagram requires publicly accessible video URLs."
                            )
                        
                        content_type = head_response.headers.get('content-type', 'unknown')
                        content_length = head_response.headers.get('content-length', 'unknown')
                        logger.info(f"Video URL accessible: {media_url}, content-type: {content_type}, size: {content_length}")
                        
                        # Check content type
                        if not content_type.startswith('video/'):
                            logger.warning(f"URL content-type is not video: {content_type}")
                            
                    except Exception as e:
                        logger.error(f"Failed to verify video URL accessibility: {str(e)}")
                        # Continue anyway - let Instagram determine if it can access
                        
                else:
                    # Default to image
                    logger.warning(f"📷 SETTING IMAGE PARAMETERS (media_type was: {media_type})")
                    if not media_url:
                        return PublishResult(
                            platform="instagram",
                            status=PublishStatus.FAILED,
                            error_message="No image URL provided for Instagram image post"
                        )
                    
                    container_data["image_url"] = media_url
                    logger.warning(f"📷 Set image_url in container: {media_url}")
                
                
                # Log the final container data
                logger.warning(f"📤 Final container data being sent to Instagram:")
                for key, value in container_data.items():
                    if key != 'access_token':
                        logger.warning(f"  - {key}: {value}")
                
                container_response = await client.post(
                    f"https://graph.facebook.com/v23.0/{account_id}/media",
                    data=container_data
                )
                
                if container_response.status_code != 200:
                    error_text = container_response.text
                    
                    # Parse specific Instagram error messages
                    try:
                        error_data = container_response.json()
                        error_info = error_data.get('error', {})
                        error_message = error_info.get('message', 'Unknown error')
                        error_code = error_info.get('code')
                        error_subcode = error_info.get('error_subcode')
                        user_title = error_info.get('error_user_title', '')
                        user_msg = error_info.get('error_user_msg', '')
                        
                        # Handle specific video download errors
                        if error_code == 9004 and error_subcode == 2207052:
                            detailed_error = f"Instagram video download failed. {user_title}: {user_msg}"
                            
                            # Add troubleshooting suggestions
                            if 'could not be fetched from this URI' in user_msg:
                                detailed_error += "\n\nTroubleshooting:\n"
                                detailed_error += "1. Ensure video URL is publicly accessible\n"
                                detailed_error += "2. Check filename has no spaces (use underscores)\n"
                                detailed_error += "3. Verify SSL certificate is valid\n"
                                detailed_error += "4. Ensure video format meets Instagram requirements"
                                
                            return PublishResult(
                                platform="instagram",
                                status=PublishStatus.FAILED,
                                error_message=detailed_error
                            )
                        else:
                            detailed_error = f"Instagram container creation failed (Code: {error_code}): {error_message}"
                            if user_msg:
                                detailed_error += f" - {user_msg}"
                                
                    except Exception:
                        detailed_error = f"Instagram container creation failed: {error_text}"
                    
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.FAILED,
                        error_message=detailed_error
                    )
                
                container_id = container_response.json().get("id")
                logger.warning(f"✅ Container created successfully with ID: {container_id}")
                
                # For videos, check container status before publishing
                if media_type == 'video':
                    logger.warning(f"🔍 Checking container status before publishing...")
                    
                    # Step 2a: Check container status (CRITICAL for videos)
                    max_status_checks = 10
                    status_check_delay = 3  # seconds
                    
                    for status_attempt in range(max_status_checks):
                        logger.warning(f"📋 Status check {status_attempt + 1}/{max_status_checks} for container {container_id}")
                        
                        status_response = await client.get(
                            f"https://graph.facebook.com/v23.0/{container_id}?fields=status_code,status&access_token={access_token}"
                        )
                        
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            status_code = status_data.get('status_code')
                            status = status_data.get('status')
                            
                            logger.warning(f"📊 Container status: code={status_code}, status={status}")
                            
                            # Instagram status codes:
                            # FINISHED = Ready to publish
                            # IN_PROGRESS = Still processing
                            # ERROR = Processing failed
                            
                            if status_code == 'FINISHED':
                                logger.warning(f"✅ Container processing completed! Ready to publish.")
                                break
                            elif status_code == 'ERROR':
                                return PublishResult(
                                    platform="instagram",
                                    status=PublishStatus.FAILED,
                                    error_message=f"Instagram container processing failed: {status_data}"
                                )
                            else:  # IN_PROGRESS or other
                                logger.warning(f"⏳ Container still processing (status: {status_code}), waiting {status_check_delay} seconds...")
                                await asyncio.sleep(status_check_delay)
                        else:
                            logger.warning(f"❌ Status check failed: {status_response.text}")
                            await asyncio.sleep(status_check_delay)
                    
                    # If we've exhausted status checks without FINISHED status
                    if status_attempt == max_status_checks - 1:
                        logger.warning(f"⚠️ Container status check timeout after {max_status_checks} attempts")
                
                # Step 2b: Publish the container
                publish_data = {
                    "creation_id": container_id,
                    "access_token": access_token
                }
                
                logger.warning(f"📤 Publishing container {container_id} to Instagram...")
                
                publish_response = await client.post(
                    f"https://graph.facebook.com/v23.0/{account_id}/media_publish",
                    data=publish_data
                )
                
                if publish_response.status_code == 200:
                    response_data = publish_response.json()
                    post_id = response_data.get("id")
                    
                    logger.info(f"✅ Successfully posted single media to Instagram: {post_id}")
                    
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.SUCCESS,
                        platform_post_id=post_id,
                        metadata={"instagram_data": response_data, "media_count": 1}
                    )
                else:
                    error_response = publish_response.text
                    logger.warning(f"❌ Instagram publish failed: {error_response}")
                    
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.FAILED,
                        error_message=f"Instagram publish failed: {error_response}"
                    )
                    
        except Exception as e:
            return PublishResult(
                platform="instagram",
                status=PublishStatus.FAILED,
                error_message=f"Instagram single media error: {str(e)}"
            )

    async def _publish_instagram_carousel(
        self, 
        account_id: str, 
        access_token: str, 
        media_urls: List[str], 
        caption: str
    ) -> PublishResult:
        """Publish carousel (multiple media) to Instagram"""
        try:
            # Instagram carousel limits: 2-10 items
            if len(media_urls) < 2:
                return PublishResult(
                    platform="instagram",
                    status=PublishStatus.FAILED,
                    error_message="Instagram carousel requires at least 2 media items"
                )
            
            if len(media_urls) > 10:
                media_urls = media_urls[:10]  # Limit to 10 items
                logger.warning(f"Instagram carousel limited to 10 items, truncated from {len(media_urls)}")

            logger.info(f"Creating Instagram carousel with {len(media_urls)} media items")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Step 1: Create child media containers for each media item
                child_container_ids = []
                failed_uploads = []
                
                for idx, media_url in enumerate(media_urls):
                    try:
                        logger.info(f"Creating child container {idx + 1}/{len(media_urls)}: {media_url}")
                        
                        container_data = {
                            "image_url": media_url,
                            "is_carousel_item": "true",  # Important for carousel items
                            "access_token": access_token
                        }
                        
                        container_response = await client.post(
                            f"https://graph.facebook.com/v23.0/{account_id}/media",
                            data=container_data
                        )
                        
                        if container_response.status_code == 200:
                            container_id = container_response.json().get("id")
                            if container_id:
                                child_container_ids.append(container_id)
                                logger.info(f"✅ Created child container {idx + 1}: {container_id}")
                            else:
                                failed_uploads.append(f"No container ID returned for item {idx + 1}")
                        else:
                            failed_uploads.append(f"Failed to create container for item {idx + 1}: {container_response.text}")
                            logger.error(f"Failed to create container for item {idx + 1}: {container_response.text}")
                            
                    except Exception as e:
                        failed_uploads.append(f"Error creating container for item {idx + 1}: {str(e)}")
                        logger.error(f"Error creating container for item {idx + 1}: {str(e)}")

                # Check if we have enough successful containers
                if len(child_container_ids) < 2:
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.FAILED,
                        error_message=f"Failed to create enough child containers. Succeeded: {len(child_container_ids)}, Failed: {len(failed_uploads)}. Errors: {'; '.join(failed_uploads)}"
                    )

                logger.info(f"Successfully created {len(child_container_ids)} child containers")

                # Step 2: Create carousel container
                carousel_data = {
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_container_ids),  # Comma-separated list
                    "caption": caption,
                    "access_token": access_token
                }
                
                logger.info(f"Creating carousel container with children: {carousel_data['children']}")
                
                carousel_response = await client.post(
                    f"https://graph.facebook.com/v23.0/{account_id}/media",
                    data=carousel_data
                )
                
                if carousel_response.status_code != 200:
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.FAILED,
                        error_message=f"Instagram carousel container creation failed: {carousel_response.text}"
                    )
                
                carousel_container_id = carousel_response.json().get("id")
                logger.info(f"✅ Created carousel container: {carousel_container_id}")
                
                # Step 3: Publish the carousel
                publish_data = {
                    "creation_id": carousel_container_id,
                    "access_token": access_token
                }
                
                publish_response = await client.post(
                    f"https://graph.facebook.com/v23.0/{account_id}/media_publish",
                    data=publish_data
                )
                
                if publish_response.status_code == 200:
                    response_data = publish_response.json()
                    post_id = response_data.get("id")
                    
                    logger.info(f"✅ Successfully posted Instagram carousel: {post_id} with {len(child_container_ids)} media items")
                    
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.SUCCESS,
                        platform_post_id=post_id,
                        metadata={
                            "instagram_data": response_data,
                            "media_count": len(child_container_ids),
                            "carousel_container_id": carousel_container_id,
                            "child_container_ids": child_container_ids,
                            "failed_uploads": failed_uploads
                        }
                    )
                else:
                    return PublishResult(
                        platform="instagram",
                        status=PublishStatus.FAILED,
                        error_message=f"Instagram carousel publish failed: {publish_response.text}"
                    )
                    
        except Exception as e:
            return PublishResult(
                platform="instagram",
                status=PublishStatus.FAILED,
                error_message=f"Instagram carousel error: {str(e)}"
            )

    async def _publish_to_threads(
        self, 
        access_token: str, 
        content: PlatformContent, 
        platform: Dict[str, Any]
    ) -> PublishResult:
        """Publish to Threads using the official Threads API"""
        try:
            logger.warning(f"🧵🧵🧵 THREADS PUBLISHER CALLED!")
            account_id = platform.get('accountId')
            logger.warning(f"🧵 Account ID: {account_id}")
            logger.warning(f"🧵 Content: {content.content}")
            logger.warning(f"🧵 Media URLs: {content.media_urls}")
            
            # Prepare post text (max 500 characters for Threads)
            post_text = content.content
            if content.hashtags:
                post_text += "\n\n" + " ".join([f"#{tag}" for tag in content.hashtags])
            
            # Limit text to 500 characters (Threads limit)
            if len(post_text) > 500:
                post_text = post_text[:497] + "..."
                logger.warning(f"🧵 Text truncated to 500 characters: {post_text}")
            
            # Threads API - Create container data
            container_data = {
                "media_type": "TEXT",
                "text": post_text,
                "access_token": access_token
            }
            
            # Handle media if present (single image support)
            if content.media_urls and len(content.media_urls) > 0:
                media_url = content.media_urls[0]
                container_data["media_type"] = "IMAGE"
                container_data["image_url"] = media_url
                logger.warning(f"🧵 Adding image: {media_url}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Debug: Check token permissions first - use Threads API endpoint
                logger.warning(f"🔍 Checking access token permissions...")
                token_check_response = await client.get(
                    f"https://graph.threads.net/v1.0/me?fields=id,name,username&access_token={access_token}"
                )
                logger.warning(f"🔍 Token permissions response: {token_check_response.status_code}")
                if token_check_response.status_code == 200:
                    permissions = token_check_response.json()
                    logger.warning(f"🔍 Available permissions: {permissions}")
                    
                    # Check specifically for Threads permissions
                    threads_perms = [p for p in permissions.get('data', []) if 'threads' in p.get('permission', '')]
                    logger.warning(f"🧵 Threads-specific permissions: {threads_perms}")
                
                # Debug: Check what Grok research revealed about correct endpoints
                logger.warning(f"🧵 === THREADS API DEBUG INFO ===")
                logger.warning(f"🧵 Current setup:")
                logger.warning(f"🧵   - OAuth App ID: {os.getenv('THREADS_CLIENT_ID', 'NOT_SET')}")
                logger.warning(f"🧵   - API App ID: {os.getenv('THREADS_APP_ID', 'NOT_SET')}")
                logger.warning(f"🧵   - User Account ID: {account_id}")
                logger.warning(f"🧵   - Endpoint: https://graph.threads.net/v1.0/{account_id}/threads")
                logger.warning(f"🧵 === END DEBUG INFO ===")
                
                # Step 1: Create media container
                logger.warning(f"🧵 Creating Threads container with data: {container_data}")
                logger.warning(f"🧵 Using endpoint: https://graph.threads.net/v1.0/{account_id}/threads")
                
                # Use the correct Threads API endpoint
                endpoint_url = f"https://graph.threads.net/v1.0/{account_id}/threads"
                logger.warning(f"🧵 Attempting API call to: {endpoint_url}")
                
                container_response = await client.post(
                    endpoint_url,
                    data=container_data
                )
                
                logger.warning(f"🧵 Container response status: {container_response.status_code}")
                logger.warning(f"🧵 Container response: {container_response.text}")
                
                if container_response.status_code != 200:
                    error_text = container_response.text
                    logger.error(f"🧵 Container creation failed: {error_text}")
                    
                    # Parse detailed error message
                    try:
                        error_data = container_response.json()
                        error_message = error_data.get('error', {}).get('message', error_text)
                        error_code = error_data.get('error', {}).get('code', 'unknown')
                        detailed_error = f"Threads container creation failed (Code: {error_code}): {error_message}"
                    except:
                        detailed_error = f"Threads container creation failed: {error_text}"
                    
                    return PublishResult(
                        platform="threads",
                        status=PublishStatus.FAILED,
                        error_message=detailed_error
                    )
                
                container_data_response = container_response.json()
                container_id = container_data_response.get("id")
                logger.warning(f"🧵 Container created successfully with ID: {container_id}")
                
                # Step 2: Wait before publishing (Threads recommendation: ~30 seconds)
                # For now, let's use a shorter delay for testing
                logger.warning(f"🧵 Waiting 5 seconds before publishing...")
                await asyncio.sleep(5)
                
                # Step 3: Publish the container
                publish_data = {
                    "creation_id": container_id,
                    "access_token": access_token
                }
                
                logger.warning(f"🧵 Publishing Threads container {container_id}")
                logger.warning(f"🧵 Using endpoint: https://graph.threads.net/v1.0/{account_id}/threads_publish")
                
                publish_response = await client.post(
                    f"https://graph.threads.net/v1.0/{account_id}/threads_publish",
                    data=publish_data
                )
                
                logger.warning(f"🧵 Publish response status: {publish_response.status_code}")
                logger.warning(f"🧵 Publish response: {publish_response.text}")
                
                if publish_response.status_code == 200:
                    response_data = publish_response.json()
                    post_id = response_data.get("id")
                    
                    return PublishResult(
                        platform="threads",
                        status=PublishStatus.SUCCESS,
                        platform_post_id=post_id,
                        metadata={"threads_data": response_data}
                    )
                else:
                    return PublishResult(
                        platform="threads",
                        status=PublishStatus.FAILED,
                        error_message=f"Threads publish failed: {publish_response.text}"
                    )
                    
        except Exception as e:
            return PublishResult(
                platform="threads",
                status=PublishStatus.FAILED,
                error_message=f"Threads publishing error: {str(e)}"
            )

    async def _publish_to_tiktok(
        self, 
        access_token: str, 
        content: PlatformContent, 
        platform: Dict[str, Any]
    ) -> PublishResult:
        """Publish to TikTok (requires video)"""
        return PublishResult(
            platform="tiktok",
            status=PublishStatus.FAILED,
            error_message="TikTok publishing not yet implemented - requires video upload workflow"
        )

    async def _publish_to_youtube(
        self, 
        access_token: str, 
        content: PlatformContent, 
        platform: Dict[str, Any]
    ) -> PublishResult:
        """Publish to YouTube (requires video)"""
        return PublishResult(
            platform="youtube",
            status=PublishStatus.FAILED,
            error_message="YouTube publishing not yet implemented - requires video upload workflow"
        )