"""
Twitter/X Publishing Service - Complete Working Implementation
Integrated from tested working flows for text, images, and videos
"""

import asyncio
import httpx
import logging
import time
import hashlib
import hmac
import base64
import urllib.parse
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

from app.utils.encryption import decrypt_token
from app.utils.database import get_database

logger = logging.getLogger(__name__)

# Twitter API Configuration
TWITTER_CONSUMER_KEY = os.getenv("TWITTER_CONSUMER_API_KEY", "7Ykr2GhF9vqWje6GJy63m79hP")
TWITTER_CONSUMER_SECRET = os.getenv("TWITTER_CONSUMER_API_SECRET", "LMofjKzcAHmUcONiHcXfxsaJpWMUQF1OWLsQeANi4HWTSJMIWp")

# Twitter API Endpoints
TWITTER_UPLOAD_URL_V1 = "https://upload.twitter.com/1.1/media/upload.json"
TWITTER_TWEET_URL_V2 = "https://api.twitter.com/2/tweets"

# Media Limits
MAX_IMAGES_PER_TWEET = 4
MAX_VIDEO_SIZE = 512 * 1024 * 1024  # 512MB
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB

class TwitterPublishStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"

@dataclass
class TwitterPublishResult:
    status: TwitterPublishStatus
    tweet_id: Optional[str] = None
    media_ids: Optional[List[str]] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class TwitterPublisher:
    """Complete Twitter/X publishing service with working text, image, and video flows"""
    
    def __init__(self):
        self.consumer_key = TWITTER_CONSUMER_KEY
        self.consumer_secret = TWITTER_CONSUMER_SECRET
        
    async def get_user_twitter_tokens(self, user_id: int) -> Dict[str, str]:
        """Get user's Twitter OAuth tokens from database"""
        supabase = get_database(admin_access=True)
        
        try:
            # Get Twitter connection with all token fields
            twitter_result = supabase.table('social_connections').select(
                'access_token, refresh_token, oauth1_access_token, oauth1_access_token_secret'
            ).eq('user_id', user_id).eq('provider', 'twitter').execute()
            
            if not twitter_result.data:
                raise Exception("Twitter connection not found for user")
            
            connection = twitter_result.data[0]
            
            # Decrypt tokens
            tokens = {}
            
            # OAuth 2.0 token
            if connection['access_token']:
                try:
                    tokens['access_token'] = decrypt_token(connection['access_token'])
                    logger.info("✅ OAuth 2.0 token decrypted successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to decrypt OAuth 2.0 token: {e}")
            
            # OAuth 1.0a tokens
            if connection.get('oauth1_access_token'):
                try:
                    tokens['oauth1_token'] = decrypt_token(connection['oauth1_access_token'])
                    logger.info("✅ OAuth 1.0a token decrypted successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to decrypt OAuth 1.0a token: {e}")
            
            if connection.get('oauth1_access_token_secret'):
                try:
                    tokens['oauth1_secret'] = decrypt_token(connection['oauth1_access_token_secret'])
                    logger.info("✅ OAuth 1.0a secret decrypted successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to decrypt OAuth 1.0a secret: {e}")
            
            return tokens
            
        except Exception as e:
            logger.error(f"Database error getting Twitter tokens: {e}")
            raise Exception(f"Failed to get Twitter tokens: {str(e)}")
    
    def create_oauth1_header(self, method: str, url: str, oauth_token: str, oauth_token_secret: str, additional_params: Optional[Dict[str, str]] = None) -> str:
        """Generate OAuth 1.0a authorization header"""
        oauth_params = {
            'oauth_consumer_key': self.consumer_key,
            'oauth_token': oauth_token,
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_nonce': hashlib.md5(f"{time.time()}{os.urandom(8).hex()}".encode()).hexdigest(),
            'oauth_version': '1.0'
        }
        
        # Add additional parameters for signature calculation
        all_params = oauth_params.copy()
        if additional_params:
            all_params.update(additional_params)
        
        # Generate signature
        signature = self._generate_oauth1_signature(method, url, all_params, oauth_token_secret)
        oauth_params['oauth_signature'] = signature
        
        # Create header
        return 'OAuth ' + ', '.join([
            f'{k}="{urllib.parse.quote(str(v), safe="")}"' 
            for k, v in oauth_params.items()
        ])
    
    def _generate_oauth1_signature(self, method: str, url: str, params: Dict[str, str], token_secret: str) -> str:
        """Generate OAuth 1.0a signature"""
        # Create parameter string
        param_string = "&".join([
            f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}" 
            for k, v in sorted(params.items())
        ])
        
        # Create signature base string
        base_string = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_string, safe='')}"
        
        # Create signing key
        signing_key = f"{urllib.parse.quote(self.consumer_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
        
        # Generate signature
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        ).decode()
        
        return signature
    
    async def download_media(self, url: str) -> bytes:
        """Download media from URL"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    
    async def post_text_tweet(self, text: str, tokens: Dict[str, str]) -> TwitterPublishResult:
        """
        Post text-only tweet using V2 API with OAuth 2.0
        
        Args:
            text: Tweet content (max 280 chars)
            tokens: Dictionary with 'access_token' (OAuth 2.0)
        
        Returns:
            TwitterPublishResult with tweet_id or error
        """
        try:
            # Validate OAuth 2.0 token
            if not tokens.get('access_token'):
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="OAuth 2.0 access token required for text tweets"
                )
            
            # Prepare headers
            oauth2_token = tokens.get("access_token")
            logger.info(f"🔑 Using OAuth 2.0 token for text tweet: {oauth2_token[:20]}..." if oauth2_token else "🔑 No OAuth 2.0 token available")
            
            if not oauth2_token:
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="No OAuth 2.0 token available for text tweet creation"
                )
            
            headers = {
                'Authorization': f'Bearer {oauth2_token}',
                'Content-Type': 'application/json'
            }
            
            # Prepare payload
            payload = {'text': text}
            
            # Make request
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"🐦 Creating text-only tweet")
                response = await client.post(TWITTER_TWEET_URL_V2, headers=headers, json=payload)
                
                if response.status_code == 201:
                    result = response.json()
                    tweet_id = result['data']['id']
                    logger.info(f"✅ Text tweet created: {tweet_id}")
                    return TwitterPublishResult(
                        status=TwitterPublishStatus.SUCCESS,
                        tweet_id=tweet_id,
                        metadata={"type": "text_only"}
                    )
                else:
                    error_msg = f"{response.status_code} - {response.text}"
                    logger.error(f"❌ Text tweet failed: {error_msg}")
                    
                    # Provide helpful error messages based on status code
                    if response.status_code == 429:
                        friendly_error = "Twitter rate limit exceeded. Please wait a few minutes before trying again."
                    elif response.status_code == 401:
                        friendly_error = "Twitter authentication failed. Please reconnect your Twitter account."
                    elif response.status_code == 403:
                        friendly_error = "Twitter permissions error. Make sure your account has tweet permissions."
                    else:
                        friendly_error = f"Text tweet creation failed: {error_msg}"
                    
                    return TwitterPublishResult(
                        status=TwitterPublishStatus.FAILED,
                        error_message=friendly_error
                    )
                    
        except Exception as e:
            logger.error(f"❌ Exception in text tweet: {e}")
            return TwitterPublishResult(
                status=TwitterPublishStatus.FAILED,
                error_message=f"Text tweet exception: {str(e)}"
            )
    
    async def upload_image(self, image_data: bytes, tokens: Dict[str, str]) -> Optional[str]:
        """Upload single image to Twitter using V1.1 API with OAuth 1.0a"""
        try:
            # Validate OAuth 1.0a tokens
            if not (tokens.get('oauth1_token') and tokens.get('oauth1_secret')):
                raise Exception("OAuth 1.0a tokens required for image upload")
            
            # Generate OAuth 1.0a header
            auth_header = self.create_oauth1_header(
                'POST',
                TWITTER_UPLOAD_URL_V1,
                tokens['oauth1_token'],
                tokens['oauth1_secret']
            )
            
            headers = {'Authorization': auth_header}
            files = {'media': ('image.jpg', image_data, 'image/jpeg')}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(TWITTER_UPLOAD_URL_V1, headers=headers, files=files)
                
                if response.status_code == 200:
                    result = response.json()
                    media_id = result.get('media_id_string')
                    logger.info(f"✅ Image uploaded: {media_id}")
                    return media_id
                else:
                    error_msg = f"{response.status_code} - {response.text}"
                    logger.error(f"❌ Image upload failed: {error_msg}")
                    raise Exception(f"Image upload failed: {error_msg}")
                    
        except Exception as e:
            logger.error(f"❌ Image upload exception: {e}")
            raise e
    
    async def post_tweet_with_images(self, text: str, image_urls: List[str], tokens: Dict[str, str]) -> TwitterPublishResult:
        """
        Post tweet with images using V1.1 upload + V2 tweet creation
        
        Args:
            text: Tweet content
            image_urls: List of image URLs (max 4 images)
            tokens: Dictionary with OAuth 1.0a and 2.0 tokens
        
        Returns:
            TwitterPublishResult with tweet_id and media_ids or error
        """
        try:
            # Validate tokens
            if not tokens.get('access_token'):
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="OAuth 2.0 token required for tweet creation"
                )
            if not (tokens.get('oauth1_token') and tokens.get('oauth1_secret')):
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="OAuth 1.0a tokens required for media upload"
                )
            
            # Step 1: Upload images (max 4)
            media_ids = []
            failed_uploads = []
            
            for i, image_url in enumerate(image_urls[:MAX_IMAGES_PER_TWEET]):
                try:
                    logger.info(f"📥 Downloading image {i+1}: {image_url}")
                    image_data = await self.download_media(image_url)
                    logger.info(f"✅ Downloaded {len(image_data):,} bytes")
                    
                    media_id = await self.upload_image(image_data, tokens)
                    media_ids.append(media_id)
                    
                except Exception as e:
                    logger.error(f"❌ Failed to upload image {i+1}: {e}")
                    failed_uploads.append(f"Image {i+1}: {str(e)}")
            
            if not media_ids:
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message=f"Failed to upload any images: {'; '.join(failed_uploads)}"
                )
            
            # Step 2: Create tweet with V2 API
            oauth2_token = tokens.get("access_token")
            logger.info(f"🔑 Using OAuth 2.0 token for image tweet: {oauth2_token[:20]}..." if oauth2_token else "🔑 No OAuth 2.0 token available")
            
            if not oauth2_token:
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="No OAuth 2.0 token available for tweet creation",
                    media_ids=media_ids
                )
            
            headers = {
                'Authorization': f'Bearer {oauth2_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'text': text,
                'media': {'media_ids': media_ids}
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"🐦 Creating tweet with {len(media_ids)} images")
                response = await client.post(TWITTER_TWEET_URL_V2, headers=headers, json=payload)
                
                if response.status_code == 201:
                    result = response.json()
                    tweet_id = result['data']['id']
                    
                    success_status = TwitterPublishStatus.SUCCESS if not failed_uploads else TwitterPublishStatus.PARTIAL
                    message = f"Tweet created with {len(media_ids)} images"
                    if failed_uploads:
                        message += f" ({len(failed_uploads)} failed uploads)"
                    
                    logger.info(f"✅ {message}: {tweet_id}")
                    return TwitterPublishResult(
                        status=success_status,
                        tweet_id=tweet_id,
                        media_ids=media_ids,
                        error_message="; ".join(failed_uploads) if failed_uploads else None,
                        metadata={
                            "type": "text_with_images",
                            "image_count": len(media_ids),
                            "failed_uploads": len(failed_uploads)
                        }
                    )
                else:
                    error_msg = f"{response.status_code} - {response.text}"
                    logger.error(f"❌ Image tweet creation failed: {error_msg}")
                    
                    # Provide helpful error messages based on status code
                    if response.status_code == 429:
                        friendly_error = "Twitter rate limit exceeded. Please wait a few minutes before trying again. Your images were uploaded successfully."
                    elif response.status_code == 401:
                        friendly_error = "Twitter authentication failed. Please reconnect your Twitter account."
                    elif response.status_code == 403:
                        friendly_error = "Twitter permissions error. Make sure your account has tweet permissions."
                    else:
                        friendly_error = f"Tweet creation failed: {error_msg}"
                    
                    return TwitterPublishResult(
                        status=TwitterPublishStatus.FAILED,
                        error_message=friendly_error,
                        media_ids=media_ids  # Images were uploaded successfully
                    )
                    
        except Exception as e:
            logger.error(f"❌ Exception in image tweet: {e}")
            return TwitterPublishResult(
                status=TwitterPublishStatus.FAILED,
                error_message=f"Image tweet exception: {str(e)}"
            )
    
    async def upload_video_chunked(self, video_data: bytes, tokens: Dict[str, str]) -> str:
        """
        Upload video using V1.1 chunked upload API with OAuth 1.0a
        
        Args:
            video_data: Video file bytes
            tokens: Dictionary with OAuth 1.0a tokens
        
        Returns:
            media_id: Uploaded video media ID
        """
        # Validate OAuth 1.0a tokens
        if not (tokens.get('oauth1_token') and tokens.get('oauth1_secret')):
            raise Exception("OAuth 1.0a tokens required for video upload")
        
        total_bytes = len(video_data)
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            logger.info(f"🎬 Starting video upload ({total_bytes:,} bytes)")
            
            # Step 1: INIT - Initialize upload
            init_data = {
                'command': 'INIT',
                'media_type': 'video/mp4',
                'total_bytes': total_bytes,
                'media_category': 'tweet_video'
            }
            
            auth_header = self.create_oauth1_header(
                'POST', TWITTER_UPLOAD_URL_V1, tokens['oauth1_token'], tokens['oauth1_secret'], init_data
            )
            
            response = await client.post(
                TWITTER_UPLOAD_URL_V1, 
                headers={'Authorization': auth_header}, 
                data=init_data
            )
            
            if response.status_code not in [200, 201, 202]:
                raise Exception(f"Video INIT failed: {response.status_code} - {response.text}")
            
            init_result = response.json()
            media_id = init_result.get('media_id_string') or str(init_result.get('media_id'))
            
            if not media_id:
                raise Exception(f"No media_id in INIT response: {init_result}")
            
            logger.info(f"✅ INIT successful: media_id={media_id}")
            
            # Step 2: APPEND - Upload chunks
            segment_index = 0
            
            for i in range(0, total_bytes, CHUNK_SIZE):
                chunk = video_data[i:i + CHUNK_SIZE]
                
                append_data = {
                    'command': 'APPEND',
                    'media_id': media_id,
                    'segment_index': segment_index
                }
                
                # For APPEND, don't include form data in OAuth signature
                auth_header = self.create_oauth1_header(
                    'POST', TWITTER_UPLOAD_URL_V1, tokens['oauth1_token'], tokens['oauth1_secret']
                )
                
                files = {'media': chunk}
                
                logger.info(f"📤 APPEND segment {segment_index}: {len(chunk):,} bytes")
                response = await client.post(
                    TWITTER_UPLOAD_URL_V1,
                    headers={'Authorization': auth_header},
                    data=append_data,
                    files=files
                )
                
                if response.status_code not in [200, 204]:
                    raise Exception(f"Video APPEND failed: {response.status_code} - {response.text}")
                
                segment_index += 1
            
            # Step 3: FINALIZE - Complete upload
            finalize_data = {
                'command': 'FINALIZE',
                'media_id': media_id
            }
            
            auth_header = self.create_oauth1_header(
                'POST', TWITTER_UPLOAD_URL_V1, tokens['oauth1_token'], tokens['oauth1_secret'], finalize_data
            )
            
            logger.info(f"🏁 FINALIZE: media_id={media_id}")
            response = await client.post(
                TWITTER_UPLOAD_URL_V1,
                headers={'Authorization': auth_header},
                data=finalize_data
            )
            
            if response.status_code != 200:
                raise Exception(f"Video FINALIZE failed: {response.status_code} - {response.text}")
            
            finalize_result = response.json()
            
            # Step 4: STATUS - Wait for processing (if needed)
            processing_info = finalize_result.get('processing_info')
            if processing_info:
                await self._check_video_processing_status(media_id, tokens, client)
            
            logger.info(f"✅ Video uploaded successfully: {media_id}")
            return media_id
    
    async def _check_video_processing_status(self, media_id: str, tokens: Dict[str, str], client: httpx.AsyncClient):
        """Poll video processing status until complete"""
        max_attempts = 30
        attempt = 0
        
        logger.info(f"⏳ Starting video processing status checks for media_id: {media_id}")
        
        while attempt < max_attempts:
            status_params = {
                'command': 'STATUS',
                'media_id': media_id
            }
            
            auth_header = self.create_oauth1_header(
                'GET', TWITTER_UPLOAD_URL_V1, tokens['oauth1_token'], tokens['oauth1_secret'], status_params
            )
            
            response = await client.get(
                TWITTER_UPLOAD_URL_V1,
                headers={'Authorization': auth_header},
                params=status_params
            )
            
            if response.status_code != 200:
                logger.warning(f"STATUS check failed: {response.status_code} - {response.text}")
                # Don't break on status check failure - continue with upload
                if response.status_code == 401:
                    logger.warning("⚠️ Status check authentication failed, but video upload was successful")
                break
            
            result = response.json()
            processing_info = result.get('processing_info', {})
            state = processing_info.get('state', 'unknown')
            progress = processing_info.get('progress_percent', 0)
            
            logger.info(f"📊 Processing status: {state} ({progress}% complete)")
            
            if state == 'succeeded':
                logger.info("✅ Video processing completed successfully!")
                break
            elif state == 'failed':
                error = processing_info.get('error', {})
                logger.error(f"❌ Video processing failed: {error}")
                raise Exception(f"Video processing failed: {error}")
            
            check_after = processing_info.get('check_after_secs', 2)
            logger.info(f"⏳ Waiting {check_after} seconds before next status check...")
            await asyncio.sleep(check_after)
            attempt += 1
        
        if attempt >= max_attempts:
            logger.warning(f"⚠️ Status checking timed out after {max_attempts} attempts")
    
    async def post_tweet_with_video(self, text: str, video_url: str, tokens: Dict[str, str]) -> TwitterPublishResult:
        """
        Post tweet with video using V1.1 chunked upload + V2 tweet creation
        
        Args:
            text: Tweet content
            video_url: Video file URL
            tokens: Dictionary with OAuth 1.0a and 2.0 tokens
        
        Returns:
            TwitterPublishResult with tweet_id and media_id or error
        """
        try:
            # Validate tokens
            if not tokens.get('access_token'):
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="OAuth 2.0 token required for tweet creation"
                )
            if not (tokens.get('oauth1_token') and tokens.get('oauth1_secret')):
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="OAuth 1.0a tokens required for video upload"
                )
            
            # Step 1: Download video
            logger.info(f"📥 Downloading video: {video_url}")
            video_data = await self.download_media(video_url)
            video_size_mb = len(video_data) / 1024 / 1024
            logger.info(f"✅ Downloaded {len(video_data):,} bytes ({video_size_mb:.1f} MB)")
            
            # Check video size limit
            if len(video_data) > MAX_VIDEO_SIZE:
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message=f"Video too large: {video_size_mb:.1f}MB (max {MAX_VIDEO_SIZE/1024/1024}MB)"
                )
            
            # Step 2: Upload video with chunked upload
            media_id = await self.upload_video_chunked(video_data, tokens)
            
            # Step 3: CRITICAL - Wait for processing to complete
            # This delay ensures V1.1 media ID works with V2 tweet creation
            logger.info("⏳ Adding 5-second delay to ensure video processing completion...")
            await asyncio.sleep(5)
            
            # Step 4: Create tweet with V2 API
            oauth2_token = tokens.get("access_token")
            logger.info(f"🔑 Using OAuth 2.0 token for tweet creation: {oauth2_token[:20]}..." if oauth2_token else "🔑 No OAuth 2.0 token available")
            
            if not oauth2_token:
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message="No OAuth 2.0 token available for tweet creation",
                    media_ids=[media_id]
                )
            
            headers = {
                'Authorization': f'Bearer {oauth2_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'text': text,
                'media': {'media_ids': [media_id]}
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"🐦 Creating tweet with video")
                response = await client.post(TWITTER_TWEET_URL_V2, headers=headers, json=payload)
                
                if response.status_code == 201:
                    result = response.json()
                    tweet_id = result['data']['id']
                    logger.info(f"✅ Video tweet created: {tweet_id}")
                    return TwitterPublishResult(
                        status=TwitterPublishStatus.SUCCESS,
                        tweet_id=tweet_id,
                        media_ids=[media_id],
                        metadata={
                            "type": "text_with_video",
                            "video_size": len(video_data),
                            "video_size_mb": round(video_size_mb, 1)
                        }
                    )
                else:
                    error_msg = f"{response.status_code} - {response.text}"
                    logger.error(f"❌ Video tweet creation failed: {error_msg}")
                    
                    # Provide helpful error messages based on status code
                    if response.status_code == 429:
                        friendly_error = "Twitter rate limit exceeded. Please wait a few minutes before trying again. Your video was uploaded successfully."
                    elif response.status_code == 401:
                        friendly_error = "Twitter authentication failed. Please reconnect your Twitter account."
                    elif response.status_code == 403:
                        friendly_error = "Twitter permissions error. Make sure your account has tweet permissions."
                    else:
                        friendly_error = f"Tweet creation failed: {error_msg}"
                    
                    return TwitterPublishResult(
                        status=TwitterPublishStatus.FAILED,
                        error_message=friendly_error,
                        media_ids=[media_id]  # Video was uploaded successfully
                    )
                    
        except Exception as e:
            logger.error(f"❌ Exception in video tweet: {e}")
            return TwitterPublishResult(
                status=TwitterPublishStatus.FAILED,
                error_message=f"Video tweet exception: {str(e)}"
            )
    
    async def publish_content(self, user_id: int, content: str, media_urls: List[str] = None) -> TwitterPublishResult:
        """
        Unified function to post to Twitter with automatic media type detection
        
        Args:
            user_id: User ID to get tokens for
            content: Tweet content
            media_urls: Optional list of media URLs (images or videos)
        
        Returns:
            TwitterPublishResult with success/failure details
        """
        try:
            # Get user's Twitter tokens
            tokens = await self.get_user_twitter_tokens(user_id)
            
            if not media_urls:
                # Text-only post
                logger.info("📝 Publishing text-only tweet")
                return await self.post_text_tweet(content, tokens)
            
            # Determine media type from first URL
            first_url = media_urls[0].lower()
            
            if any(ext in first_url for ext in ['.mp4', '.mov', '.avi', '.mkv']):
                # Video post (only first video)
                logger.info("🎥 Publishing video tweet")
                return await self.post_tweet_with_video(content, media_urls[0], tokens)
            
            elif any(ext in first_url for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                # Image post (up to 4 images)
                logger.info(f"🖼️ Publishing image tweet with {len(media_urls)} images")
                return await self.post_tweet_with_images(content, media_urls, tokens)
            
            else:
                return TwitterPublishResult(
                    status=TwitterPublishStatus.FAILED,
                    error_message=f"Unsupported media type: {first_url}"
                )
                
        except Exception as e:
            logger.error(f"❌ Exception in publish_content: {e}")
            return TwitterPublishResult(
                status=TwitterPublishStatus.FAILED,
                error_message=f"Publishing exception: {str(e)}"
            )