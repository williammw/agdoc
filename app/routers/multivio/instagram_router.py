import random
from pydantic import BaseModel, Field
import logging
from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File
from databases import Database
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict
import os
import secrets
import traceback
from datetime import datetime, timezone, timedelta
from app.dependencies import get_current_user, get_database
from app.models.mo_social import OAuthState, OAuthInitResponse
from urllib.parse import quote, urlencode
import json
import httpx
from enum import Enum
from typing import Optional
import asyncio
import ffmpeg
from typing import Optional, Dict, Any


# Models for request/response
class VideoMetadata(BaseModel):
    width: int
    height: int
    duration: float
    format: str
    audio_codec: Optional[str]
    video_codec: str


class MediaType(str, Enum):
    """Valid media types for Instagram uploads"""
    IMAGE = "IMAGE"
    REELS = "REELS" 
    CAROUSEL = "CAROUSEL"


class PostVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    HIDDEN = "HIDDEN"


class MediaUploadRequest(BaseModel):
    """Request model for media uploads"""
    account_id: str = Field(..., description="The Instagram account ID")
    media_type: MediaType = Field(...,
                                description="Type of media being uploaded")
    url: str = Field(..., description="URL of the media file")
    caption: Optional[str] = Field(None, description="Caption for the post")

    class Config:
        use_enum_values = True


class InstagramPostRequest(BaseModel):
    account_id: str
    media_ids: List[str] = Field(...,
                               description="List of media IDs to include in post")
    caption: str
    location: Optional[str] = None
    hide_likes: bool = Field(default=False)
    hide_comments: bool = Field(default=False)

class CarouselPostRequest(BaseModel):
    """Request model for carousel posts with media URLs"""
    account_id: str
    media_urls: List[str] = Field(...,
                                  description="List of media URLs to include in carousel")
    caption: str
    location: Optional[str] = None
    hide_likes: bool = Field(default=False)
    hide_comments: bool = Field(default=False)


class InstagramDisconnectRequest(BaseModel):
    account_id: str


class InstagramDisconnectResponse(BaseModel):
    success: bool
    message: Optional[str] = None


router = APIRouter()
logger = logging.getLogger(__name__)

# Load environment variables
FACEBOOK_API_VERSION = os.environ.get("FACEBOOK_API_VERSION", "v21.0")
INSTAGRAM_GRAPH_URL = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}"
FACEBOOK_OAUTH_URL = f"https://www.facebook.com/{FACEBOOK_API_VERSION}/dialog/oauth"
INSTAGRAM_SCOPE = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement,instagram_manage_insights"
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://dev.multivio.com")

# Timeouts and retry settings
UPLOAD_TIMEOUT = 300  # 5 minutes for uploads
STATUS_CHECK_TIMEOUT = 30  # 30 seconds for status checks
MAX_STATUS_CHECKS = 30
BASE_DELAY = 10  # Base delay between status checks in seconds
MAX_DELAY = 60  # Maximum delay between status checks

# Log environment variables
logger.info("Instagram Router Environment Variables:")
logger.info(f"FACEBOOK_API_VERSION: {FACEBOOK_API_VERSION}")
logger.info(f"FACEBOOK_APP_ID present: {bool(FACEBOOK_APP_ID)}")
logger.info(f"FACEBOOK_APP_SECRET present: {bool(FACEBOOK_APP_SECRET)}")
logger.info(f"FRONTEND_URL: {FRONTEND_URL}")


async def get_media_type(url: str) -> str:
    """Determine if a URL points to an image or video."""
    video_extensions = ('.mp4', '.mov', '.avi')
    return 'VIDEO' if any(url.lower().endswith(ext) for ext in video_extensions) else 'IMAGE'

@router.post("/auth/init", response_model=OAuthInitResponse)
async def instagram_auth_init(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Initialize Instagram OAuth flow"""
    try:
        if not FACEBOOK_APP_ID:
            raise HTTPException(
                status_code=500, detail="FACEBOOK_APP_ID not configured")

        state = secrets.token_urlsafe(32)

        # Store state in database
        query = """
        INSERT INTO mo_oauth_states (
            state,
            platform,
            user_id,
            expires_at,
            created_at
        ) VALUES (
            :state,
            'instagram',
            :user_id,
            :expires_at,
            :created_at
        )
        """

        now = datetime.now(timezone.utc)
        values = {
            "state": state,
            "user_id": current_user["uid"],
            "expires_at": now + timedelta(minutes=10),
            "created_at": now
        }

        await db.execute(query=query, values=values)

        redirect_uri = f"{FRONTEND_URL}/instagram/callback"
        logger.info(f"Using redirect URI: {redirect_uri}")

        # OAuth parameters
        params = {
            'client_id': FACEBOOK_APP_ID,
            'redirect_uri': redirect_uri,
            'scope': INSTAGRAM_SCOPE,
            'state': state,
            'response_type': 'code',
            'display': 'popup'
        }

        auth_url = f"{FACEBOOK_OAUTH_URL}?{urlencode(params)}"
        logger.info(f"Generated Instagram auth URL: {auth_url}")

        return OAuthInitResponse(auth_url=auth_url, state=state)

    except Exception as e:
        logger.error(f"Error in instagram_auth_init: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/callback")
async def instagram_auth_callback(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Handle Instagram OAuth callback"""
    try:
        if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
            raise HTTPException(
                status_code=500, detail="Instagram credentials not configured")

        data = await request.json()
        code = data.get("code")
        state = data.get("state")

        logger.info(
            f"Received callback with code: {code[:10]}... and state: {state}")

        # Verify state
        query = """
        SELECT 
            user_id, 
            expires_at AT TIME ZONE 'UTC' as expires_at
        FROM mo_oauth_states 
        WHERE state = :state AND platform = 'instagram'
        """
        result = await db.fetch_one(query=query, values={"state": state})

        if not result:
            raise HTTPException(status_code=400, detail="Invalid state")

        # Convert expires_at to timezone-aware datetime if it isn't already
        expires_at = result["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        current_time = datetime.now(timezone.utc)
        if expires_at < current_time:
            raise HTTPException(status_code=400, detail="State expired")

        if result["user_id"] != current_user["uid"]:
            raise HTTPException(status_code=400, detail="User mismatch")

        # Exchange code for access token
        redirect_uri = f"{FRONTEND_URL}/instagram/callback"
        token_url = f"{INSTAGRAM_GRAPH_URL}/oauth/access_token"

        token_params = {
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "redirect_uri": redirect_uri,
            "code": code
        }

        async with httpx.AsyncClient() as client:
            # Get initial token
            token_response = await client.get(token_url, params=token_params)
            if token_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to exchange code for token")

            token_data = token_response.json()
            short_lived_token = token_data["access_token"]

            # Get long-lived token
            exchange_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/oauth/access_token"
            exchange_params = {
                "grant_type": "fb_exchange_token",
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "fb_exchange_token": short_lived_token
            }

            long_lived_response = await client.get(exchange_url, params=exchange_params)
            if long_lived_response.status_code != 200:
                error_data = long_lived_response.json()
                raise HTTPException(
                    status_code=400,
                    detail=error_data.get("error", {}).get("message", "Failed to get long-lived token")
                )

            long_lived_data = long_lived_response.json()
            access_token = long_lived_data["access_token"]
            expires_in = long_lived_data.get("expires_in", 5184000)  # Default to 60 days

            # Get user's Facebook pages
            pages_response = await client.get(
                f"{INSTAGRAM_GRAPH_URL}/me/accounts",
                params={"access_token": access_token}
            )

            if pages_response.status_code != 200:
                raise HTTPException(
                    status_code=400, detail="Failed to fetch Facebook pages")

            pages = pages_response.json().get("data", [])

            # Get Instagram business accounts for each page
            instagram_accounts = []
            for page in pages:
                # Get long-lived token for the page
                page_exchange_params = {**exchange_params, "fb_exchange_token": page["access_token"]}
                page_token_response = await client.get(exchange_url, params=page_exchange_params)
                
                if page_token_response.status_code == 200:
                    page_token_data = page_token_response.json()
                    page_access_token = page_token_data["access_token"]

                    ig_response = await client.get(
                        f"{INSTAGRAM_GRAPH_URL}/{page['id']}",
                        params={
                            "fields": "instagram_business_account",
                            "access_token": page_access_token
                        }
                    )

                    if ig_response.status_code == 200:
                        ig_data = ig_response.json()
                        if "instagram_business_account" in ig_data:
                            # Get Instagram account details
                            ig_account_response = await client.get(
                                f"{INSTAGRAM_GRAPH_URL}/{ig_data['instagram_business_account']['id']}",
                                params={
                                    "fields": "id,username,profile_picture_url",
                                    "access_token": page_access_token
                                }
                            )

                            if ig_account_response.status_code == 200:
                                ig_account_data = ig_account_response.json()
                                instagram_accounts.append({
                                    "id": ig_account_data["id"],
                                    "username": ig_account_data["username"],
                                    "profile_picture_url": ig_account_data.get("profile_picture_url"),
                                    "access_token": page_access_token
                                })

            # Store Instagram accounts in database
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=expires_in)

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
                updated_at
            ) VALUES (
                :user_id,
                'instagram',
                :platform_account_id,
                :username,
                :profile_picture_url,
                :access_token,
                :refresh_token,
                :expires_at,
                :metadata,
                :created_at,
                :created_at
            )
            ON CONFLICT (platform, user_id, platform_account_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                profile_picture_url = EXCLUDED.profile_picture_url,
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.created_at
            RETURNING id
            """

            stored_accounts = []
            for account in instagram_accounts:
                values = {
                    "user_id": current_user["uid"],
                    "platform_account_id": account["id"],
                    "username": account["username"],
                    "profile_picture_url": account["profile_picture_url"],
                    "access_token": account["access_token"],
                    "refresh_token": None,
                    "expires_at": expires_at,
                    "metadata": json.dumps({"account_type": "business"}),
                    "created_at": now
                }
                result = await db.fetch_one(query=query, values=values)
                if result:
                    stored_account = {**account}
                    stored_account["id"] = result["id"]
                    stored_accounts.append(stored_account)

            return {
                "success": True,
                "accounts": stored_accounts
            }

    except Exception as e:
        logger.error(f"Error in instagram_auth_callback: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


async def test_token(access_token: str, instagram_account_id: str) -> bool:
    """Test if the token is valid by making a simple API request."""
    try:
        async with httpx.AsyncClient() as client:
            logger.info(
                f"Testing token for Instagram account {instagram_account_id}")
            response = await client.get(
                f"{INSTAGRAM_GRAPH_URL}/{instagram_account_id}",
                params={
                    "fields": "id,username",
                    "access_token": access_token
                }
            )

            if response.status_code != 200:
                logger.error(
                    f"Token test failed with status {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False

            data = response.json()
            logger.info(
                f"Token test successful. Account username: {data.get('username')}")
            return True

    except Exception as e:
        logger.error(f"Error testing token: {str(e)}")
        return False


async def validate_and_refresh_token(db: Database, account: Dict) -> str:
    """Validate and refresh Instagram token with debug logging."""
    try:
        logger.info(f"Starting token validation for account {account['id']}")
        logger.info(
            f"Current token (first 10 chars): {account['access_token'][:10]}...")

        # Test current token first
        if await test_token(account['access_token'], account['platform_account_id']):
            logger.info("Current token is still valid")
            return account['access_token']

        logger.info("Current token failed validation, attempting refresh")

        # Get the metadata - handle Record object properly
        try:
            # Use direct attribute access for Record object
            metadata_str = account["metadata"] if account["metadata"] is not None else "{}"
            metadata = json.loads(metadata_str)
        except (json.JSONDecodeError, KeyError):
            metadata = {}

        logger.info(f"Account metadata: {metadata}")

        # First try to get pages with current token
        async with httpx.AsyncClient() as client:
            logger.info("Fetching Facebook pages")
            me_response = await client.get(
                f"{INSTAGRAM_GRAPH_URL}/me/accounts",
                params={"access_token": account["access_token"]}
            )

            if me_response.status_code != 200:
                logger.error(f"Failed to get pages: {me_response.text}")
                raise HTTPException(
                    status_code=401,
                    detail="Could not access Facebook pages. Please reconnect your account."
                )

            pages = me_response.json().get("data", [])
            logger.info(f"Found {len(pages)} Facebook pages")

            # Try each page to find the Instagram business account
            for page in pages:
                logger.info(f"Checking page {page['id']}")
                ig_response = await client.get(
                    f"{INSTAGRAM_GRAPH_URL}/{page['id']}",
                    params={
                        "fields": "instagram_business_account",
                        "access_token": page["access_token"]
                    }
                )

                if ig_response.status_code == 200:
                    ig_data = ig_response.json()
                    logger.info(f"Instagram data for page: {ig_data}")

                    if (
                        "instagram_business_account" in ig_data and
                        ig_data["instagram_business_account"]["id"] == account["platform_account_id"]
                    ):
                        logger.info(
                            f"Found matching Instagram account for page {page['id']}")

                        # Use the page's access token directly
                        logger.info(
                            "Using page access token for media operations")
                        new_token = page["access_token"]

                        # Test the new token
                        if not await test_token(new_token, account['platform_account_id']):
                            logger.error("Page token validation failed")
                            continue

                        # Update the database
                        now = datetime.now(timezone.utc)
                        metadata['page_id'] = page['id']

                        await db.execute(
                            """
                            UPDATE mo_social_accounts 
                            SET 
                                access_token = :access_token,
                                updated_at = :updated_at,
                                metadata = :metadata
                            WHERE id = :account_id
                            """,
                            {
                                "access_token": new_token,
                                "updated_at": now,
                                "metadata": json.dumps(metadata),
                                "account_id": account["id"]
                            }
                        )

                        logger.info("Successfully updated token in database")
                        return new_token

            logger.error("No valid token found for any connected page")
            raise HTTPException(
                status_code=401,
                detail="Could not find valid credentials. Please reconnect your account."
            )

    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=401,
            detail="Failed to refresh Instagram access. Please reconnect your account."
        )


async def validate_video_metadata(video_url: str) -> VideoMetadata:
    """Validate video file meets Instagram requirements using FFmpeg"""
    try:
        # Get video metadata using ffmpeg
        probe = await asyncio.create_subprocess_exec(
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            video_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await probe.communicate()

        if probe.returncode != 0:
            raise ValueError(f"FFprobe error: {stderr.decode()}")

        metadata = json.loads(stdout.decode())

        # Extract video stream info
        video_stream = next(
            s for s in metadata['streams'] if s['codec_type'] == 'video')
        audio_stream = next(
            (s for s in metadata['streams'] if s['codec_type'] == 'audio'), None)

        # Validate format
        if not metadata['format']['format_name'].lower() in ['mov', 'mp4']:
            raise ValueError("Video must be in MOV or MP4 format")

        # Check video codec
        if video_stream['codec_name'] not in ['h264']:
            raise ValueError("Video codec must be H.264")

        # Check audio codec if present
        if audio_stream and audio_stream['codec_name'] not in ['aac']:
            raise ValueError("Audio codec must be AAC")

        # Check audio sample rate if present
        if audio_stream and int(audio_stream['sample_rate']) > 48000:
            raise ValueError("Audio sample rate must not exceed 48kHz")

        return VideoMetadata(
            width=int(video_stream['width']),
            height=int(video_stream['height']),
            duration=float(metadata['format']['duration']),
            format=metadata['format']['format_name'],
            audio_codec=audio_stream['codec_name'] if audio_stream else None,
            video_codec=video_stream['codec_name']
        )

    except Exception as e:
        logger.error(f"Video validation error: {str(e)}")
        raise ValueError(f"Video validation failed: {str(e)}")


async def get_instagram_account(
    db: Database,
    account_id: str,
    user_id: str
) -> Dict[str, Any]:
    """
    Get Instagram account information from the database.
    
    Args:
        db: Database connection
        account_id: The ID of the account to retrieve
        user_id: The ID of the user who owns the account
        
    Returns:
        Dict containing account information
        
    Raises:
        HTTPException: If account not found or unauthorized access
    """
    query = """
    SELECT 
        id,
        access_token,
        platform_account_id,
        metadata,
        expires_at AT TIME ZONE 'UTC' as expires_at,
        created_at AT TIME ZONE 'UTC' as created_at,
        updated_at AT TIME ZONE 'UTC' as updated_at
    FROM mo_social_accounts 
    WHERE id = :account_id 
    AND user_id = :user_id 
    AND platform = 'instagram'
    """

    account = await db.fetch_one(
        query=query,
        values={
            "account_id": account_id,
            "user_id": user_id
        }
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Instagram account not found"
        )

    # Convert to dict for easier handling
    account_dict = dict(account)

    # Parse metadata if it exists
    if account_dict.get("metadata"):
        try:
            account_dict["metadata"] = json.loads(account_dict["metadata"])
        except json.JSONDecodeError:
            account_dict["metadata"] = {}

    # Verify token exists
    if not account_dict.get("access_token"):
        raise HTTPException(
            status_code=401,
            detail="No valid Instagram token found. Please reconnect your account."
        )

    return account_dict




async def check_media_status(client: httpx.AsyncClient, creation_id: str, access_token: str) -> str:
    """Check media status with exponential backoff"""
    delay = BASE_DELAY
    for attempt in range(MAX_STATUS_CHECKS):
        try:
            status_response = await client.get(
                f"{INSTAGRAM_GRAPH_URL}/{creation_id}",
                params={
                    "fields": "status_code",
                    "access_token": access_token
                },
                timeout=STATUS_CHECK_TIMEOUT
            )

            if status_response.status_code == 200:
                status_data = status_response.json()
                status = status_data.get("status_code")
                logger.info(f"Media status check {attempt + 1}: {status}")

                if status == "FINISHED":
                    return status
                elif status == "ERROR":
                    error_details = status_data.get(
                        "status_code_details", "Unknown error")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Media processing failed: {error_details}"
                    )

            # Exponential backoff with jitter
            jitter = random.uniform(0, 0.1 * delay)
            delay = min(delay * 1.5 + jitter, MAX_DELAY)
            await asyncio.sleep(delay)

        except httpx.TimeoutError:
            logger.warning(
                f"Timeout during status check attempt {attempt + 1}")
            continue
        except Exception as e:
            logger.error(f"Error during status check: {str(e)}")
            raise

    raise HTTPException(status_code=400, detail="Media processing timed out")


@router.post("/posts/media")
async def upload_media(
    request: MediaUploadRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Upload media to Instagram"""
    try:
        logger.info(f"Starting media upload for user {current_user['uid']}")
        logger.info(f"Request data: {request.dict()}")

        # Get account info
        account = await get_instagram_account(db, request.account_id, current_user["uid"])

        # Use custom timeout settings for httpx client
        async with httpx.AsyncClient(timeout=httpx.Timeout(UPLOAD_TIMEOUT)) as client:
            try:
                # Create container with exact parameters from documentation
                container_url = f"{INSTAGRAM_GRAPH_URL}/{account['platform_account_id']}/media"

                # Base container data with required parameters
                container_data = {
                    "access_token": account["access_token"],
                }

                if request.media_type == MediaType.IMAGE:
                    container_data.update({
                        "image_url": request.url,
                        "media_type": "IMAGE"
                    })
                elif request.media_type == MediaType.REELS:
                    container_data.update({
                        "video_url": request.url,
                        "media_type": "REELS",
                        "share_to_feed": "true"
                    })

                # Add caption if provided
                if request.caption:
                    container_data["caption"] = request.caption

                logger.info(
                    f"Creating media container for {request.media_type}")
                logger.info(f"Container data: {container_data}")

                # Create container with error handling
                try:
                    container_response = await client.post(container_url, data=container_data)
                    container_response.raise_for_status()
                except httpx.HTTPError as e:
                    error_data = container_response.json() if hasattr(
                        container_response, 'json') else {}
                    error_message = error_data.get("error", {}).get(
                        "message", "Failed to create media container")
                    logger.error(f"Container creation failed: {error_message}")
                    logger.error(f"Full error response: {error_data}")
                    raise HTTPException(status_code=e.response.status_code if hasattr(
                        e, 'response') else 500, detail=error_message)

                creation_id = container_response.json()["id"]
                logger.info(f"Media container created with ID: {creation_id}")

                # For videos/reels, we need to wait for processing
                if request.media_type == MediaType.REELS:
                    await check_media_status(client, creation_id, account["access_token"])

                # Publish media with retry logic
                max_publish_attempts = 3
                for attempt in range(max_publish_attempts):
                    try:
                        publish_url = f"{INSTAGRAM_GRAPH_URL}/{account['platform_account_id']}/media_publish"
                        publish_data = {
                            "creation_id": creation_id,
                            "access_token": account["access_token"]
                        }

                        publish_response = await client.post(publish_url, data=publish_data)
                        publish_response.raise_for_status()
                        return publish_response.json()

                    except httpx.HTTPError as e:
                        if attempt == max_publish_attempts - 1:  # Last attempt
                            error_data = e.response.json() if hasattr(e, 'response') else {}
                            error_message = error_data.get("error", {}).get(
                                "message", "Failed to publish media")
                            raise HTTPException(status_code=e.response.status_code if hasattr(
                                e, 'response') else 500, detail=error_message)
                        # Exponential backoff
                        await asyncio.sleep(2 ** attempt)

            except httpx.TimeoutError:
                logger.error("Timeout during media upload or publishing")
                raise HTTPException(
                    status_code=504, detail="Request timed out during media processing")

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Unexpected error in upload_media: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/auth/token-status/{account_id}")
async def check_token_status(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Check the status of an Instagram token."""
    try:
        query = """
        SELECT 
            id,
            access_token, 
            platform_account_id,
            metadata,
            expires_at AT TIME ZONE 'UTC' as expires_at,
            created_at AT TIME ZONE 'UTC' as created_at,
            updated_at AT TIME ZONE 'UTC' as updated_at
        FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'instagram'
        """
        
        account = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "user_id": current_user["uid"]
            }
        )

        if not account:
            return {
                "status": "not_found",
                "message": "Account not found"
            }

        token_exists = bool(account['access_token'])
        token_length = len(account['access_token']) if account['access_token'] else 0
        token_format_valid = account['access_token'].startswith(('EAA', 'IGA')) if token_exists else False

        # Test token if it exists and format is valid
        token_valid = False
        if token_exists and token_format_valid:
            token_valid = await test_token(account['access_token'], account['platform_account_id'])

        return {
            "status": "ok" if (token_exists and token_format_valid and token_valid) else "invalid",
            "token_exists": token_exists,
            "token_length": token_length,
            "token_format_valid": token_format_valid,
            "token_valid": token_valid,
            "created_at": account['created_at'].isoformat(),
            "updated_at": account['updated_at'].isoformat(),
            "expires_at": account['expires_at'].isoformat() if account['expires_at'] else None
        }

    except Exception as e:
        logger.error(f"Error checking token status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))




# Then add the new endpoint:

@router.post("/posts/carousel")
async def create_carousel_post(
    request: CarouselPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Create a carousel post on Instagram using media URLs"""
    try:
        # Get account info
        account = await get_instagram_account(db, request.account_id, current_user["uid"])

        # First, determine media types and validate
        logger.info(
            f"Creating containers for {len(request.media_urls)} media items")
        media_types = [await get_media_type(url) for url in request.media_urls]

        # Ensure all media types are the same
        unique_types = set(media_types)
        if len(unique_types) > 1:
            raise HTTPException(
                status_code=400,
                detail="Instagram carousel posts must contain either all images or all videos. Mixed media types are not supported."
            )

        media_type = media_types[0]  # All items are the same type
        logger.info(f"Carousel media type: {media_type}")

        async with httpx.AsyncClient(timeout=httpx.Timeout(UPLOAD_TIMEOUT)) as client:
            container_ids = []

            # Create containers for each media URL
            for media_url in request.media_urls:
                try:
                    container_url = f"{INSTAGRAM_GRAPH_URL}/{account['platform_account_id']}/media"

                    # Set up container data based on media type
                    container_data = {
                        "access_token": account["access_token"],
                        "media_type": media_type
                    }

                    if media_type == "IMAGE":
                        container_data["image_url"] = media_url
                    else:  # VIDEO
                        container_data["video_url"] = media_url

                    container_response = await client.post(container_url, data=container_data)
                    if container_response.status_code != 200:
                        error_data = container_response.json()
                        raise HTTPException(
                            status_code=container_response.status_code,
                            detail=f"Failed to create container for {media_url}: {error_data.get('error', {}).get('message', 'Unknown error')}"
                        )

                    container_id = container_response.json()["id"]
                    container_ids.append(container_id)
                    logger.info(
                        f"Created container {container_id} for URL {media_url}")

                    # If it's a video, wait for processing
                    if media_type == "VIDEO":
                        await check_media_status(client, container_id, account["access_token"])

                except Exception as e:
                    logger.error(
                        f"Failed to create container for URL {media_url}: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to process media: {str(e)}"
                    )

            # Create the carousel container
            carousel_url = f"{INSTAGRAM_GRAPH_URL}/{account['platform_account_id']}/media"

            carousel_data = {
                "media_type": "CAROUSEL",
                "caption": request.caption,
                "access_token": account["access_token"],
                "children": ",".join(container_ids)
            }

            if request.location:
                carousel_data["location"] = request.location

            # Create and publish carousel with retry logic
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    # Create carousel container
                    carousel_response = await client.post(carousel_url, data=carousel_data)
                    carousel_response.raise_for_status()
                    creation_id = carousel_response.json()["id"]
                    logger.info(
                        f"Created carousel container with ID: {creation_id}")

                    # For video carousels, wait for processing
                    if media_type == "VIDEO":
                        await check_media_status(client, creation_id, account["access_token"])

                    # Publish the carousel
                    publish_url = f"{INSTAGRAM_GRAPH_URL}/{account['platform_account_id']}/media_publish"
                    publish_data = {
                        "creation_id": creation_id,
                        "access_token": account["access_token"]
                    }

                    publish_response = await client.post(publish_url, data=publish_data)
                    publish_response.raise_for_status()

                    return publish_response.json()

                except httpx.HTTPError as e:
                    if attempt == max_attempts - 1:  # Last attempt
                        error_data = e.response.json() if hasattr(e, 'response') else {}
                        error_message = error_data.get("error", {}).get(
                            "message", "Failed to publish carousel")
                        logger.error(
                            f"Carousel publishing failed: {error_message}")
                        raise HTTPException(
                            status_code=e.response.status_code if hasattr(
                                e, 'response') else 500,
                            detail=error_message
                        )
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error in create_carousel_post: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))




@router.post("/auth/disconnect", response_model=InstagramDisconnectResponse)
async def disconnect_instagram_account(
    request: InstagramDisconnectRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Disconnect an Instagram account"""
    try:
        query = """
        DELETE FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'instagram'
        RETURNING id
        """

        result = await db.fetch_one(
            query=query,
            values={
                "account_id": request.account_id,
                "user_id": current_user["uid"]
            }
        )

        if not result:
            raise HTTPException(
                status_code=404,
                detail="Instagram account not found or already disconnected"
            )

        return InstagramDisconnectResponse(
            success=True,
            message="Instagram account disconnected successfully"
        )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500,
            detail=f"Failed to disconnect Instagram account: {str(e)}"
        )


@router.get("/user")
async def get_instagram_user(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get Instagram user profile and connected accounts"""
    try:
        query = """
        SELECT 
            id,
            platform_account_id,
            username,
            profile_picture_url,
            access_token,
            expires_at,
            metadata
        FROM mo_social_accounts 
        WHERE user_id = :user_id 
        AND platform = 'instagram'
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
            if account_dict["metadata"]:
                account_dict["metadata"] = json.loads(account_dict["metadata"])
            account_list.append(account_dict)

        return {
            "connected": True,
            "accounts": account_list
        }

    except Exception as e:
        logger.error(f"Error in get_instagram_user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/exchange-token", response_model=dict)
async def exchange_token(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Exchange short-lived token for long-lived token"""
    try:
        data = await request.json()
        short_lived_token = data.get("access_token")

        if not short_lived_token:
            raise HTTPException(
                status_code=400, detail="Access token required")

        # Exchange token
        params = {
            "grant_type": "ig_exchange_token",
            "client_secret": FACEBOOK_APP_SECRET,
            "access_token": short_lived_token
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://graph.instagram.com/access_token",
                params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                raise HTTPException(
                    status_code=400,
                    detail=error_data.get("error", {}).get(
                        "message", "Token exchange failed")
                )

            token_data = response.json()
            return token_data

    except Exception as e:
        logger.error(f"Error exchanging token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/refresh-token", response_model=dict)
async def refresh_token(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Refresh Instagram access token"""
    try:
        data = await request.json()
        account_id = data.get("account_id")
        
        if not account_id:
            raise HTTPException(status_code=400, detail="Account ID required")

        # Get current token from database
        query = """
        SELECT access_token, platform_account_id, metadata
        FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'instagram'
        """
        
        account = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "user_id": current_user["uid"]
            }
        )

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # For Instagram Business accounts, we need to use the Facebook Graph API
        async with httpx.AsyncClient() as client:
            # First, get the long-lived token using Facebook Graph API
            exchange_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/oauth/access_token"
            exchange_params = {
                "grant_type": "fb_exchange_token",
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "fb_exchange_token": account["access_token"]
            }

            response = await client.get(exchange_url, params=exchange_params)
            
            if response.status_code != 200:
                error_data = response.json()
                raise HTTPException(
                    status_code=400,
                    detail=error_data.get("error", {}).get("message", "Token refresh failed")
                )

            token_data = response.json()
            new_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 5184000)  # Default to 60 days

            if not new_token:
                raise HTTPException(status_code=400, detail="No new token received")

            # Update token in database
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            
            update_query = """
            UPDATE mo_social_accounts 
            SET access_token = :access_token,
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE id = :account_id 
            AND user_id = :user_id 
            AND platform = 'instagram'
            """

            await db.execute(
                query=update_query,
                values={
                    "access_token": new_token,
                    "expires_at": expires_at,
                    "updated_at": datetime.now(timezone.utc),
                    "account_id": account_id,
                    "user_id": current_user["uid"]
                }
            )

            return {
                "access_token": new_token,
                "expires_in": expires_in
            }

    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/validate-token", response_model=dict)
async def validate_token(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Validate and refresh token if needed"""
    try:
        data = await request.json()
        account_id = data.get("account_id")

        if not account_id:
            raise HTTPException(status_code=400, detail="Account ID required")

        # Get account from database
        query = """
        SELECT 
            access_token,
            platform_account_id,
            expires_at AT TIME ZONE 'UTC' as expires_at
        FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'instagram'
        """

        account = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "user_id": current_user["uid"]
            }
        )

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Convert expires_at to timezone-aware datetime if it isn't already
        expires_at = account["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        # Check if token needs refresh (24 hours before expiry)
        current_time = datetime.now(timezone.utc)
        buffer_time = timedelta(hours=24)

        if expires_at - buffer_time <= current_time:
            # Refresh token
            refresh_response = await refresh_token(
                request=Request(scope={"type": "http"}),
                current_user=current_user,
                db=db
            )
            return refresh_response

        return {
            "access_token": account["access_token"],
            "expires_in": int((expires_at - current_time).total_seconds())
        }

    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Update the callback function to use long-lived token

