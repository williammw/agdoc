import logging
import secrets
import httpx
from httpx import HTTPStatusError, ConnectTimeout, ConnectError, ReadTimeout
from fastapi import APIRouter, HTTPException, Depends, Request, Header, File, UploadFile, Form
from databases import Database
from datetime import datetime, timezone, timedelta
from app.dependencies import get_current_user, get_database
from typing import Optional
import os
import json
import traceback
import base64
import hashlib
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Union

import mimetypes
import math
from typing import Optional, List, Dict, Any
import asyncio
import httpx
import requests
import time
import random
import urllib.parse
import re
import base64
import logging

router = APIRouter(tags=["twitter"])
logger = logging.getLogger(__name__)

# Constants
TWITTER_CLIENT_ID = os.getenv("TWITTER_OAUTH2_CLIENT_ID")
TWITTER_CLIENT_SECRET = os.getenv("TWITTER_OAUTH2_CLIENT_SECRET")
TWITTER_AUTH_URL = "https://x.com/i/oauth2/authorize"
TWITTER_TOKEN_URL = "https://api.x.com/2/oauth2/token"
TWITTER_API_V2 = "https://api.x.com/2"
TWITTER_UPLOAD_API = "https://upload.twitter.com/1.1/media/upload.json"
CALLBACK_URL = os.getenv("TWITTER_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL")
# Add these constants
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for uploads
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB for images
MAX_VIDEO_SIZE = 15 * 1024 * 1024  # 15MB for videos
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif'}
ALLOWED_VIDEO_TYPES = {'video/mp4'}
MAX_RETRIES = 3  # Reduced from 5 to 3
INITIAL_RETRY_DELAY = 5  # Increased from 2 to 5 seconds
MAX_RETRY_DELAY = 15  # Reduced from 32 to 15 seconds

# Cache settings
USER_CACHE = {}  # Simple in-memory cache/auth
CACHE_TTL = 300  # 5 minutes in seconds


def generate_pkce_pair():
    """Generate PKCE code verifier and challenge"""
    code_verifier = secrets.token_urlsafe(32)
    code_verifier_bytes = code_verifier.encode('ascii')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier_bytes).digest()
    ).decode('ascii').rstrip('=')
    return code_verifier, code_challenge


@router.get("/amiworks")
async def amiworks():
    return {"message": "amiwosrks"}

@router.post("/auth/init")
async def init_oauth(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Initialize OAuth 2.0 flow with PKCE"""
    try:
        if not TWITTER_CLIENT_ID:
            raise HTTPException(
                status_code=500, detail="Twitter Client ID not configured")

        # Generate PKCE values
        code_verifier, code_challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(32)

        # Store state and code_verifier
        now = datetime.now(timezone.utc)
        query = """
        INSERT INTO mo_oauth_states (
            state, platform, user_id, code_verifier, expires_at, created_at
        ) VALUES (
            :state, 'twitter', :user_id, :code_verifier, :expires_at, :created_at
        )
        """
        values = {
            "state": state,
            "user_id": current_user["uid"],
            "code_verifier": code_verifier,
            "expires_at": now + timedelta(minutes=10),
            "created_at": now
        }
        await db.execute(query=query, values=values)

        # Construct authorization URL
        auth_params = {
            'response_type': 'code',
            'client_id': TWITTER_CLIENT_ID,
            'redirect_uri': CALLBACK_URL,
            'scope': 'tweet.read tweet.write users.read offline.access',
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }

        authorization_url = f"{TWITTER_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

        return {
            "authUrl": authorization_url,
            "state": state
        }

    except Exception as e:
        logger.error(f"Error in init_oauth: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/callback")
async def oauth_callback(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Handle OAuth callback and exchange code for token"""
    try:
        # Add logging to debug database connection
        logger.info("Database connection object: %s", db)
        
        data = await request.json()
        code = data.get("code")
        code_verifier = data.get("code_verifier")
        state = data.get("state")

        if not all([code, code_verifier, state]):
            raise HTTPException(
                status_code=400,
                detail="Missing required parameters"
            )

        # Exchange code for token
        token_data = await exchange_code(
            code=code,
            code_verifier=code_verifier,
            client_id=TWITTER_CLIENT_ID,
            client_secret=TWITTER_CLIENT_SECRET
        )

        # Try to get user info, but don't fail if rate limited
        try:
            user_info = await get_user_info(token_data["access_token"])
            # Store in database if we got user info
            account_id = await store_tokens(user_info, token_data, db, current_user["uid"])
            logger.info(f"Successfully stored Twitter account with ID: {account_id}")
            
            # Return combined response
            return {
                "access_token": token_data["access_token"],
                "token_type": token_data.get("token_type", "bearer"),
                "expires_in": token_data.get("expires_in", 7200),
                "scope": token_data.get("scope", ""),
                "refresh_token": token_data.get("refresh_token"),
                "account_id": account_id,
                "user_info": user_info["data"]
            }
            
        except HTTPException as he:
            if he.status_code == 429 or he.status_code == 503:
                # If rate limited, just return the token
                # The frontend can fetch user info later
                logger.warning("Rate limited during user info fetch, returning token only")
                return {
                    "access_token": token_data["access_token"],
                    "token_type": token_data.get("token_type", "bearer"),
                    "expires_in": token_data.get("expires_in", 7200),
                    "scope": token_data.get("scope", ""),
                    "refresh_token": token_data.get("refresh_token"),
                    "rate_limited": True
                }
            raise

    except Exception as e:
        logger.error(f"Error in oauth_callback: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.get("/user")
async def get_twitter_user(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get Twitter user profile and connected accounts"""
    try:
        # Check cache first
        cache_key = f"twitter_user_{current_user['uid']}"
        cached_data = USER_CACHE.get(cache_key)
        if cached_data and cached_data['expires_at'] > time.time():
            return cached_data['data']

        query = """
        SELECT
            id,
            platform_account_id,
            username,
            profile_picture_url,
            access_token,
            refresh_token,
            expires_at,
            metadata
        FROM mo_social_accounts
        WHERE user_id = :user_id
        AND platform = 'twitter'
        """

        accounts = await db.fetch_all(
            query=query,
            values={"user_id": current_user["uid"]}
        )

        if not accounts:
            return {
                "connected": False,
                "accounts": []
            }

        account_list = []
        for account in accounts:
            account_dict = dict(account)
            
            # Check if token needs refresh
            now = datetime.now(timezone.utc)
            is_expired = account["expires_at"] and account["expires_at"] <= now + timedelta(minutes=5)
            
            if is_expired and account["refresh_token"]:
                try:
                    # Refresh the token
                    refresh_result = await refresh_token(account["id"], current_user, db)
                    account_dict["access_token"] = refresh_result["access_token"]
                except Exception as e:
                    logger.error(f"Token refresh failed for account {account['id']}: {str(e)}")
                    # Continue with old token if refresh fails
            
            if account_dict["metadata"]:
                account_dict["metadata"] = json.loads(account_dict["metadata"])
            account_list.append(account_dict)

        response_data = {
            "connected": True,
            "accounts": account_list
        }

        # Cache the response
        USER_CACHE[cache_key] = {
            'data': response_data,
            'expires_at': time.time() + CACHE_TTL
        }

        return response_data

    except Exception as e:
        logger.error(f"Error in get_twitter_user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/me")
async def get_current_user_profile(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    authorization: str = Header(...),
    x_twitter_token: Optional[str] = Header(None, alias="X-Twitter-Token")
):
    """Get current user's Twitter profile"""
    try:
        # First try to get token from the X-Twitter-Token header
        if x_twitter_token:
            access_token = x_twitter_token
        # Fall back to authorization header if needed (for backward compatibility)
        elif authorization and authorization.startswith('Bearer '):
            access_token = authorization.split(' ')[1]
        else:
            raise HTTPException(
                status_code=401,
                detail="Missing Twitter token. Please provide X-Twitter-Token header."
            )
        
        # Validate token before making API calls
        is_valid = await check_token_validity(access_token)
        if not is_valid:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired Twitter token"
            )

        async with httpx.AsyncClient() as client:
            async def fetch_user_profile():
                response = await client.get(
                    f"{TWITTER_API_V2}/users/me",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                        "User-Agent": "MultivioApp/1.0.0"
                    },
                    params={
                        "user.fields": "id,name,username,profile_image_url,verified,public_metrics,description,entities,pinned_tweet_id,protected,url,withheld"
                    }
                )
                response.raise_for_status()
                return response.json()

            user_data = await retry_with_backoff(fetch_user_profile)

            # Get the Twitter account from database
            query = """
            SELECT id, metadata 
            FROM mo_social_accounts 
            WHERE user_id = :user_id 
            AND platform = 'twitter' 
            AND platform_account_id = :platform_account_id
            """

            account = await db.fetch_one(
                query=query,
                values={
                    "user_id": current_user["uid"],
                    "platform_account_id": user_data["data"]["id"]
                }
            )

            if account:
                # Update metadata
                metadata = json.loads(
                    account["metadata"]) if account["metadata"] else {}
                metadata.update({
                    "verified": user_data["data"].get("verified", False),
                    "metrics": user_data["data"].get("public_metrics", {})
                })

                await db.execute("""
                    UPDATE mo_social_accounts 
                    SET metadata = :metadata,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """, {
                    "id": account["id"],
                    "metadata": json.dumps(metadata)
                })

            return user_data

    except httpx.RequestError as e:
        logger.error(f"Network error when calling Twitter API: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"Error communicating with Twitter API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error in get_current_user_profile: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/disconnect")
async def disconnect_twitter_account(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Disconnect Twitter account"""
    try:
        data = await request.json()
        account_id = data.get("account_id")

        if not account_id:
            raise HTTPException(
                status_code=400, detail="Account ID is required")

        # Delete the social account from database
        query = """
        DELETE FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'twitter'
        RETURNING id
        """

        result = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "user_id": current_user["uid"]
            }
        )

        if not result:
            raise HTTPException(
                status_code=404,
                detail="Twitter account not found or already disconnected"
            )

        return {"success": True, "message": "Twitter account disconnected successfully"}

    except Exception as e:
        logger.error(f"Error disconnecting Twitter account: {str(e)}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


class MediaUploadResponse(BaseModel):
    media_id: str
    expires_after_secs: Optional[int]
    processing_info: Optional[Dict[str, Any]]


async def check_media_processing(
    client: httpx.AsyncClient,
    media_id: str,
    access_token: str,
    timeout: int = 30
) -> bool:
    """Check media processing status with timeout"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = await client.get(
                TWITTER_UPLOAD_API,
                params={
                    "command": "STATUS",
                    "media_id": media_id
                },
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to check media status"
                )

            data = response.json()
            processing_info = data.get("processing_info", {})

            if processing_info.get("state") == "succeeded":
                return True
            elif processing_info.get("state") == "failed":
                error = processing_info.get("error", {})
                raise HTTPException(
                    status_code=400,
                    detail=f"Media processing failed: {error.get('message', 'Unknown error')}"
                )

            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error checking media status: {str(e)}")
            raise

    raise HTTPException(
        status_code=408,
        detail="Media processing timeout"
    )


@router.post("/media/upload", response_model=MediaUploadResponse)
async def upload_media(
    file: UploadFile = File(...),
    access_token: str = Form(None),  # Make this optional as we'll also check header
    current_user: dict = Depends(get_current_user),
    x_twitter_token: Optional[str] = Header(None, alias="X-Twitter-Token")
):
    """Upload media using chunked upload for Twitter"""
    try:
        # Get access token from form or header
        token = x_twitter_token or access_token
        
        if not token:
            raise HTTPException(
                status_code=401,
                detail="Missing Twitter token. Please provide X-Twitter-Token header or access_token in form data"
            )
            
        # Validate token
        is_valid = await check_token_validity(token)
        if not is_valid:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired Twitter token"
            )
            
        # Validate file type
        content_type = file.content_type or mimetypes.guess_type(file.filename)[
            0]
        if not content_type:
            raise HTTPException(
                status_code=400,
                detail="Could not determine file type"
            )

        is_video = content_type in ALLOWED_VIDEO_TYPES
        is_image = content_type in ALLOWED_IMAGE_TYPES

        if not (is_video or is_image):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only JPEG, PNG, GIF, and MP4 are supported"
            )

        # Read file into memory and check size
        file_content = await file.read()
        file_size = len(file_content)

        if is_image and file_size > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=400,
                detail="Image file too large. Maximum size is 5MB"
            )
        elif is_video and file_size > MAX_VIDEO_SIZE:
            raise HTTPException(
                status_code=400,
                detail="Video file too large. Maximum size is 15MB"
            )

        async with httpx.AsyncClient() as client:
            # INIT - Initialize upload
            init_data = {
                "command": "INIT",
                "total_bytes": file_size,
                "media_type": content_type,
                "media_category": "tweet_video" if is_video else "tweet_image"
            }

            init_response = await client.post(
                TWITTER_UPLOAD_API,
                data=init_data,
                headers={"Authorization": f"Bearer {token}"}
            )

            if init_response.status_code != 200:
                raise HTTPException(
                    status_code=init_response.status_code,
                    detail="Failed to initialize media upload"
                )

            media_id = init_response.json()["media_id_string"]

            # APPEND - Upload chunks
            chunk_size = CHUNK_SIZE
            chunks = math.ceil(file_size / chunk_size)

            for i in range(chunks):
                start = i * chunk_size
                end = min(start + chunk_size, file_size)
                chunk = file_content[start:end]

                append_data = {
                    "command": "APPEND",
                    "media_id": media_id,
                    "segment_index": i
                }

                files = {
                    "media": chunk
                }

                append_response = await client.post(
                    TWITTER_UPLOAD_API,
                    data=append_data,
                    files=files,
                    headers={"Authorization": f"Bearer {token}"}
                )

                if append_response.status_code != 200:
                    raise HTTPException(
                        status_code=append_response.status_code,
                        detail=f"Failed to upload chunk {i + 1}/{chunks}"
                    )

            # FINALIZE - Complete upload
            finalize_data = {
                "command": "FINALIZE",
                "media_id": media_id
            }

            finalize_response = await client.post(
                TWITTER_UPLOAD_API,
                data=finalize_data,
                headers={"Authorization": f"Bearer {token}"}
            )

            if finalize_response.status_code != 200:
                raise HTTPException(
                    status_code=finalize_response.status_code,
                    detail="Failed to finalize media upload"
                )

            result = finalize_response.json()

            # For videos, wait for processing
            if is_video and "processing_info" in result:
                await check_media_processing(client, media_id, token)

            return MediaUploadResponse(
                media_id=media_id,
                expires_after_secs=result.get("expires_after_secs"),
                processing_info=result.get("processing_info")
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading media: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload media: {str(e)}"
        )


class TweetRequest(BaseModel):
    text: str
    media_ids: Optional[List[str]] = Field(default=[])
    is_thread: Optional[bool] = Field(default=False)
    thread_texts: Optional[List[str]] = Field(default=[])
    reply_settings: Optional[str] = Field(default="mentionedUsers")
    access_token: Optional[str] = None

    @field_validator('media_ids')
    def validate_media_ids(cls, v):
        if len(v) > 4:
            raise ValueError("Maximum 4 media items allowed per tweet")
        return v


@router.post("/tweets")
async def create_tweet(
    tweet_data: TweetRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    x_twitter_token: Optional[str] = Header(None, alias="X-Twitter-Token")
):
    """Create a new tweet with media support"""
    try:
        # Get access token from request or header
        access_token = x_twitter_token or tweet_data.access_token
        
        if not access_token:
            raise HTTPException(
                status_code=401,
                detail="Missing Twitter token. Please provide X-Twitter-Token header or access_token in body"
            )
            
        # Validate access token
        try:
            is_valid = await check_token_validity(access_token)
            if not is_valid:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired access token"
                )
        except Exception as e:
            logger.error(f"Token validation error: {str(e)}")
            raise HTTPException(
                status_code=401,
                detail=f"Failed to validate token: {str(e)}"
            )

        # Prepare tweet payload
        payload = {
            "text": tweet_data.text
        }

        # Add media if present
        if tweet_data.media_ids:
            payload["media"] = {
                "media_ids": tweet_data.media_ids
            }

        if tweet_data.reply_settings:
            payload["reply_settings"] = tweet_data.reply_settings

        # Log the payload for debugging
        logger.info(f"Creating tweet with payload: {payload}")

        # Create the tweet
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TWITTER_API_V2}/tweets",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

            if response.status_code != 201:
                error_data = response.json()
                logger.error(f"Twitter API error: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("errors", [{}])[0].get(
                        "message", "Failed to create tweet")
                )

            result = response.json()

            # Store tweet in database
            try:
                await db.execute(
                    """
                    INSERT INTO mo_tweets (
                        user_id,
                        tweet_id,
                        content,
                        media_ids,
                        created_at
                    ) VALUES (
                        :user_id,
                        :tweet_id,
                        :content,
                        :media_ids,
                        CURRENT_TIMESTAMP
                    )
                    """,
                    {
                        "user_id": current_user["uid"],
                        "tweet_id": result["data"]["id"],
                        "content": tweet_data.text,
                        "media_ids": json.dumps(tweet_data.media_ids)
                    }
                )
            except Exception as db_error:
                logger.error(f"Database error: {str(db_error)}")
                # Return success even if database storage fails
                return result

            return result

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error creating tweet: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create tweet: {str(e)}"
        )


@router.get("/auth/validate-token/{account_id}")
async def validate_token(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Validate user's Twitter token and refresh if expired"""
    try:
        query = """
        SELECT access_token, refresh_token, expires_at
        FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'twitter'
        """

        account = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "user_id": current_user["uid"]
            }
        )

        if not account:
            return {"valid": False, "error": "Account not found"}

        # Check if token is expired or about to expire (within 5 minutes)
        now = datetime.now(timezone.utc)
        is_expired = account["expires_at"] and account["expires_at"] <= now + timedelta(minutes=5)

        if is_expired and account["refresh_token"]:
            try:
                # Refresh the token
                refresh_result = await refresh_token(account_id, current_user, db)
                return {
                    "valid": True,
                    "access_token": refresh_result["access_token"]
                }
            except Exception as e:
                logger.error(f"Token refresh failed: {str(e)}")
                return {"valid": False, "error": "Token refresh failed"}
                
        # If not expired, return the existing token without validating against Twitter API
        # This avoids unnecessary API calls that could lead to rate limiting
        return {
            "valid": True, 
            "access_token": account["access_token"]
        }

    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        return {
            "valid": False,
            "error": f"Token validation failed: {str(e)}"
        }


def generate_code_challenge(code_verifier: str) -> str:
    """Generate PKCE code challenge from verifier"""
    import base64
    import hashlib

    sha256_hash = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")


async def retry_with_backoff(func, max_retries=2, initial_delay=5):
    """Improved retry with better backoff strategy"""
    last_error = None
    
    for attempt in range(max_retries):
        try:
            return await func()
        except HTTPStatusError as e:
            last_error = e
            if e.response.status_code == 429:
                # Let the main function handle rate limits
                raise
            elif e.response.status_code >= 500:
                if attempt == max_retries - 1:
                    raise
                retry_after = min(
                    initial_delay * (2 ** attempt),
                    MAX_RETRY_DELAY
                )
                logger.warning(f"Server error (attempt {attempt + 1}/{max_retries}). Retrying after {retry_after} seconds...")
                await asyncio.sleep(retry_after)
                continue
            raise
        except (ConnectError, ConnectTimeout, ReadTimeout) as e:
            last_error = e
            if attempt == max_retries - 1:
                raise
            retry_after = min(
                initial_delay * (2 ** attempt),
                MAX_RETRY_DELAY
            )
            logger.warning(f"Network error (attempt {attempt + 1}/{max_retries}). Retrying after {retry_after} seconds...")
            await asyncio.sleep(retry_after)
            continue
    
    raise last_error


async def exchange_code(
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str
) -> dict:
    """Exchange authorization code for access token"""
    try:
        # Create Basic Auth header
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TWITTER_TOKEN_URL,
                data={
                    'code': code,
                    'grant_type': 'authorization_code',
                    'redirect_uri': CALLBACK_URL,
                    'code_verifier': code_verifier
                },
                headers={
                    'Authorization': f'Basic {auth_b64}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            logger.info(f"Token exchange response: {response.status_code}")
            logger.info(f"Response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Token exchange error: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get('error_description', 'Failed to exchange code for token')
                )
            
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Network error during token exchange: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"Error communicating with Twitter API: {str(e)}"
        )


async def get_user_info(access_token: str) -> dict:
    async def fetch_user_info():
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TWITTER_API_V2}/users/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "MultivioApp/1.0.0",
                    "Accept": "application/json"
                },
                params={
                    "user.fields": "id,name,username,profile_image_url,verified,public_metrics,description"
                }
            )
            
            # Log EVERYTHING about the response
            logger.info(f"Response Status: {response.status_code}")
            logger.info(f"Response Headers: {dict(response.headers)}")
            logger.info(f"Response Body: {response.text}")
            
            if response.status_code == 429:
                error_body = response.json()
                logger.error(f"Full error response: {error_body}")
                
                # Check if this is really a rate limit or another issue
                if 'errors' in error_body:
                    for error in error_body['errors']:
                        logger.error(f"Twitter Error: {error}")
                
                reset_time = int(response.headers.get('x-rate-limit-reset', 0))
                current_time = int(time.time())
                wait_time = max(reset_time - current_time, 1)
                
                logger.warning(
                    f"Rate limit details:\n"
                    f"Current time: {current_time}\n"
                    f"Reset time: {reset_time}\n"
                    f"Wait time: {wait_time}\n"
                    f"Headers: {dict(response.headers)}"
                )
                
                if wait_time > MAX_RETRY_DELAY:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Rate limit exceeded. Try again in {wait_time} seconds"
                    )
                
                await asyncio.sleep(wait_time)
                return await fetch_user_info()
            
            response.raise_for_status()
            return response.json()

    try:
        return await retry_with_backoff(
            fetch_user_info,
            max_retries=1,  # Reduce to 1 retry since we're investigating
            initial_delay=5
        )
    except Exception as e:
        logger.error(f"Failed to get user info: {str(e)}")
        if isinstance(e, httpx.HTTPStatusError):
            logger.error(f"HTTP Error Response: {e.response.text}")
        raise HTTPException(
            status_code=503,
            detail="Failed to get user info. Please try again later."
        )


async def store_tokens(user_info: dict, token_data: dict, db: Database, current_user_id: str):
    """Store tokens and user info in database"""
    try:
        logger.info(f"Starting store_tokens for user {current_user_id}")
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=token_data.get('expires_in', 7200))
        
        # Prepare metadata - Convert datetime to ISO format string
        metadata = {
            "verified": user_info["data"].get("verified", False),
            "metrics": user_info["data"].get("public_metrics", {}),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat()
        }
        
        logger.info(f"Prepared metadata: {json.dumps(metadata)}")
        
        # Upsert the social account
        query = """
        INSERT INTO mo_social_accounts (
            user_id,
            platform,
            platform_account_id,
            username,
            profile_picture_url,
            access_token,
            refresh_token,
            expires_at,
            metadata,
            created_at,
            updated_at,
            media_type,
            media_count,
            oauth1_token,
            oauth1_token_secret
        ) VALUES (
            :user_id,
            'twitter',
            :platform_account_id,
            :username,
            :profile_picture_url,
            :access_token,
            :refresh_token,
            :expires_at,
            :metadata,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            NULL,
            0,
            NULL,
            NULL
        )
        ON CONFLICT (user_id, platform, platform_account_id) 
        DO UPDATE SET
            username = EXCLUDED.username,
            profile_picture_url = EXCLUDED.profile_picture_url,
            access_token = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            expires_at = EXCLUDED.expires_at,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP,
            media_count = EXCLUDED.media_count
        RETURNING id
        """
        
        values = {
            "user_id": current_user_id,
            "platform_account_id": user_info["data"]["id"],
            "username": user_info["data"]["username"],
            "profile_picture_url": user_info["data"].get("profile_image_url"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "expires_at": expires_at,  # This is a datetime object which SQLAlchemy can handle
            "metadata": json.dumps(metadata)  # Now metadata is properly JSON serializable
        }
        
        # Create a safe copy of values for logging
        log_values = {
            **values,
            'expires_at': expires_at.isoformat(),  # Convert datetime to string for logging
            'access_token': values['access_token'][:10] + '...' if values['access_token'] else None,
            'refresh_token': values['refresh_token'][:10] + '...' if values['refresh_token'] else None
        }
        logger.info(f"Executing upsert with values: {json.dumps(log_values)}")
        
        result = await db.fetch_one(query=query, values=values)
        logger.info(f"Store tokens result: {result}")
        
        if not result:
            raise HTTPException(
                status_code=500,
                detail="Failed to store or update social account"
            )
            
        return result['id']
        
    except Exception as e:
        logger.error(f"Error storing tokens: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store tokens: {str(e)}"
        )


# Helper function to check if a token is valid with Twitter's API
async def check_token_validity(token: str) -> bool:
    """Check if a token is still valid with Twitter's API
    
    This function calls Twitter's token_info endpoint to verify
    if a token is still valid.
    
    Args:
        token: The access token to check
        
    Returns:
        bool: True if the token is valid, False otherwise
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://api.x.com/2/oauth2/token/info",
                headers={"Authorization": f"Bearer {token}"}
            )
            logger.info(f"Token validation response: {response.status_code}")
            logger.info(f"Token info: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return False


@router.post("/auth/refresh-token/{account_id}")
async def refresh_token(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Refresh Twitter OAuth2.0 access token"""
    try:
        # Get the refresh token from database
        query = """
        SELECT refresh_token
        FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'twitter'
        """

        account = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "user_id": current_user["uid"]
            }
        )

        if not account or not account["refresh_token"]:
            raise HTTPException(
                status_code=400,
                detail="No refresh token found for this account"
            )

        # Create Basic Auth header
        auth_string = f"{TWITTER_CLIENT_ID}:{TWITTER_CLIENT_SECRET}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')

        # Exchange refresh token for new access token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TWITTER_TOKEN_URL,
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': account["refresh_token"]
                },
                headers={
                    'Authorization': f'Basic {auth_b64}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )

            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Token refresh error: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get('error_description', 'Failed to refresh token')
                )

            token_data = response.json()
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=token_data.get('expires_in', 7200))

            # Update tokens in database
            update_query = """
            UPDATE mo_social_accounts
            SET 
                access_token = :access_token,
                refresh_token = :refresh_token,
                expires_at = :expires_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :account_id
            AND user_id = :user_id
            RETURNING id
            """

            result = await db.fetch_one(
                query=update_query,
                values={
                    "account_id": account_id,
                    "user_id": current_user["uid"],
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data.get("refresh_token", account["refresh_token"]),
                    "expires_at": expires_at
                }
            )

            if not result:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to update tokens"
                )

            return {
                "access_token": token_data["access_token"],
                "token_type": token_data.get("token_type", "bearer"),
                "expires_in": token_data.get("expires_in", 7200)
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh token: {str(e)}"
        )
