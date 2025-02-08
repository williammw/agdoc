import logging
import uuid
import boto3
from fastapi import APIRouter, HTTPException, Depends, Request
from databases import Database
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
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

# Configure logging
logger = logging.getLogger(__name__)

# Constants
FACEBOOK_API_VERSION = os.environ.get("FACEBOOK_API_VERSION", "v21.0")
FACEBOOK_OAUTH_URL = f"https://www.facebook.com/{FACEBOOK_API_VERSION}/dialog/oauth"
FACEBOOK_GRAPH_URL = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}"
FACEBOOK_SCOPE = "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_metadata,business_management"
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://dev.multivio.com")
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "cdn.multivio.com")

# Media handling constants
ALLOWED_TYPES = {
    'image': ['.jpg', '.jpeg', '.png'],
    'video': ['.mp4', '.mov']
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Configure R2 client
s3_client = boto3.client('s3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name='weur')
bucket_name = 'multivio'

# Base Models
class PrivacyType(str, Enum):
    PUBLIC = "public"      # Changed from "PUBLIC"
    FRIENDS = "friends"    # Changed from "FRIENDS"
    ONLY_ME = "only_me"   # Changed from "ONLY_ME"

class TargetAudience(BaseModel):
    age_min: Optional[int] = Field(None, ge=13, le=65)
    age_max: Optional[int] = Field(None, ge=13, le=65)
    countries: Optional[List[str]] = None
    interests: Optional[List[str]] = None


class FacebookPostBase(BaseModel):
    account_id: str = Field(..., description="The Facebook page ID")
    text: Optional[str] = None
    privacy: PrivacyType = Field(default=PrivacyType.PUBLIC)
    allow_comments: bool = Field(default=True)
    target_audience: Optional[TargetAudience] = None

    class Config:
        use_enum_values = True  # This will use the actual values instead of enum names


class PhotoPostRequest(FacebookPostBase):
    media_ids: List[str]

class TextPostRequest(FacebookPostBase):
    text: str = Field(..., description="The post content")

class MediaPostRequest(FacebookPostBase):
    media_urls: List[str]
    is_carousel: bool = False
    temporary: bool = False  # Add this field with a default value of False
class FacebookPostResponse(BaseModel):
    id: str = Field(..., description="The created post ID")
    success: bool = Field(default=True)

class FacebookDisconnectRequest(BaseModel):
    account_id: str

class FacebookDisconnectResponse(BaseModel):
    success: bool
    message: Optional[str] = None

class MediaUploadRequest(BaseModel):
    filename: str
    content_type: str
    folder_id: Optional[str] = None

class MediaUploadResponse(BaseModel):
    url: str
    asset_id: str
    public_url: str

# Router
router = APIRouter()

# Log environment variables at module load
logger.info("Facebook Router Environment Variables:")
logger.info(f"FACEBOOK_API_VERSION: {FACEBOOK_API_VERSION}")
logger.info(f"FACEBOOK_APP_ID present: {bool(FACEBOOK_APP_ID)}")
logger.info(f"FACEBOOK_APP_SECRET present: {bool(FACEBOOK_APP_SECRET)}")
logger.info(f"FRONTEND_URL: {FRONTEND_URL}")

# Add these constants at the top of your file
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
UPLOAD_TIMEOUT = 300  # 5 minutes timeout for upload operations
MAX_RETRIES = 3


@router.post("/auth/init", response_model=OAuthInitResponse)
async def facebook_auth_init(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
  """Initialize Facebook OAuth flow"""
  try:
    if not FACEBOOK_APP_ID:
      raise HTTPException(
          status_code=500, detail="FACEBOOK_APP_ID not configured")

    # Rest of the init function remains the same, but use FACEBOOK_APP_ID constant
    state = secrets.token_urlsafe(32)

    # Store state in database with current timestamp
    query = """
    INSERT INTO mo_oauth_states (
      state,
      platform,
      user_id,
      expires_at,
      created_at
    ) VALUES (
      :state,
      'facebook',
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

    redirect_uri = f"{FRONTEND_URL}/facebook/callback"
    logger.info(f"Using redirect URI: {redirect_uri}")

    # OAuth parameters
    params = {
        'client_id': FACEBOOK_APP_ID,
        'redirect_uri': redirect_uri,
        'scope': FACEBOOK_SCOPE,
        'state': state,
        'response_type': 'code',
        'display': 'popup'
    }

    auth_url = f"{FACEBOOK_OAUTH_URL}?{urlencode(params)}"
    logger.info(f"Generated Facebook auth URL: {auth_url}")

    return OAuthInitResponse(auth_url=auth_url, state=state)

  except Exception as e:
    logger.error(f"Error in facebook_auth_init: {str(e)}")
    raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/callback", response_model=dict)
async def facebook_auth_callback(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
  """Handle Facebook OAuth callback"""
  try:
    # Check environment variables first
    if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
      logger.error(
          f"Missing credentials - APP_ID present: {bool(FACEBOOK_APP_ID)}, APP_SECRET present: {bool(FACEBOOK_APP_SECRET)}")
      raise HTTPException(
          status_code=500, detail="Facebook credentials not configured")

    data = await request.json()
    code = data.get("code")
    state = data.get("state")

    logger.info(
        f"Received callback with code: {code[:10]}... and state: {state}")

    # Verify state
    query = """
    SELECT 
      user_id, 
      (expires_at AT TIME ZONE 'UTC')::timestamptz as expires_at
    FROM mo_oauth_states 
    WHERE state = :state AND platform = 'facebook'
    """
    result = await db.fetch_one(query=query, values={"state": state})

    if not result:
      raise HTTPException(status_code=400, detail="Invalid state")

    # Add debug logging
    logger.info(
        f"Comparing timestamps - DB expires_at: {result['expires_at']}, Current time: {datetime.now(timezone.utc)}")

    if result["expires_at"] < datetime.now(timezone.utc):
      raise HTTPException(status_code=400, detail="State expired")

    if result["user_id"] != current_user["uid"]:
      raise HTTPException(status_code=400, detail="User mismatch")

    # Exchange code for access token
    redirect_uri = f"{FRONTEND_URL}/facebook/callback"
    token_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/oauth/access_token"

    token_params = {
        "client_id": FACEBOOK_APP_ID,
        "client_secret": FACEBOOK_APP_SECRET,
        "redirect_uri": redirect_uri,
        "code": code
    }

    logger.info("Attempting to exchange code for token...")

    async with httpx.AsyncClient() as client:
      token_response = await client.get(
          token_url,
          params=token_params
      )

      if token_response.status_code != 200:
        logger.error(f"Token exchange failed: {token_response.text}")
        raise HTTPException(
            status_code=400, detail="Failed to exchange code for token")

      token_data = token_response.json()
      access_token = token_data["access_token"]

      # Get user profile and pages
      profile_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/me"
      pages_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/me/accounts"

      profile_response = await client.get(
          profile_url,
          params={
              "access_token": access_token,
              "fields": "id,name,email"
          }
      )

      pages_response = await client.get(
          pages_url,
          params={
              "access_token": access_token
          }
      )

      if profile_response.status_code != 200 or pages_response.status_code != 200:
        raise HTTPException(
            status_code=400, detail="Failed to fetch user data")

      profile_data = profile_response.json()
      pages_data = pages_response.json()

      # Store account in database
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
        'facebook',
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
      """

      now = datetime.now(timezone.utc)
      # Calculate token expiration (Facebook tokens typically expire in 60 days)
      expires_at = now + timedelta(days=60)

      # Store each page as a separate account
      for page in pages_data.get("data", []):
        values = {
            "user_id": current_user["uid"],
            "platform_account_id": page["id"],
            "username": page["name"],
            "profile_picture_url": None,  # We can fetch this later if needed
            "access_token": page["access_token"],
            "refresh_token": None,  # Facebook page tokens don't have refresh tokens
            "expires_at": expires_at,
            "metadata": json.dumps({"page_data": page}),
            "created_at": now
        }
        await db.execute(query=query, values=values)

      return {
          "success": True,
          "profile": profile_data,
          "pages": pages_data.get("data", [])
      }

  except Exception as e:
    logger.error(f"Error in facebook_auth_callback: {str(e)}")
    raise HTTPException(status_code=500, detail=str(e))


@router.get("/user")
async def facebook_get_user(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
  """Get Facebook user profile and connected pages"""
  try:
    # Fetch connected Facebook accounts from database
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
    AND platform = 'facebook'
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

    # Convert accounts to list of dicts and parse metadata
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
    logger.error(f"Error in facebook_get_user: {str(e)}")
    raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/disconnect", response_model=FacebookDisconnectResponse)
async def disconnect_facebook_account(
    request: FacebookDisconnectRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
) -> FacebookDisconnectResponse:
  """Disconnect a Facebook account."""
  try:
    # Delete the social account from database
    query = """
    DELETE FROM mo_social_accounts 
    WHERE id = :account_id 
    AND user_id = :user_id 
    AND platform = 'facebook'
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
          detail="Facebook account not found or already disconnected"
      )

    return FacebookDisconnectResponse(
        success=True,
        message="Facebook account disconnected successfully"
    )

  except Exception as e:
    if isinstance(e, HTTPException):
      raise e
    raise HTTPException(
        status_code=500,
        detail=f"Failed to disconnect Facebook account: {str(e)}"
    )
  

@router.post("/posts/text", response_model=FacebookPostResponse)
async def create_facebook_post(
    request: TextPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        logger.info(f"Creating post for account: {request.account_id}")
        # Get user's Facebook account
        query = """
        SELECT access_token, platform_account_id, metadata
        FROM mo_social_accounts 
        WHERE id = :account_id AND user_id = :user_id AND platform = 'facebook'
        """
        values = {
            "account_id": request.account_id,
            "user_id": current_user["uid"]
        }
        logger.info(f"Executing query with values: {values}")

        account = await db.fetch_one(query=query, values=values)

        if not account:
            logger.error(f"Account not found for id: {request.account_id}")
            raise HTTPException(
                status_code=404, detail="Facebook account not found")

        logger.info(f"Found account: {account}")

        # Check if this is a Page account by examining metadata
        metadata = json.loads(
            account["metadata"]) if account["metadata"] else {}
        is_page = "page_data" in metadata

        # Prepare the Graph API request
        api_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/feed"

        # Prepare post data
        post_data = {
            "message": request.text,
            "access_token": account["access_token"]
        }

        # Only add privacy settings for personal profiles, not pages
        if not is_page:
            # Map the privacy settings to Facebook's expected values
            privacy_mapping = {
                "public": "EVERYONE",
                "friends": "ALL_FRIENDS",
                "only_me": "SELF"
            }
            fb_privacy_value = privacy_mapping.get(
                request.privacy.lower(), "EVERYONE")
            post_data["privacy"] = json.dumps({"value": fb_privacy_value})

        if not request.allow_comments:
            post_data["enable_comments"] = False

        if request.target_audience and not is_page:  # Only add targeting for personal profiles
            audience = {}
            if request.target_audience.age_min:
                audience["age_min"] = request.target_audience.age_min
            if request.target_audience.age_max:
                audience["age_max"] = request.target_audience.age_max
            if request.target_audience.countries:
                audience["countries"] = request.target_audience.countries
            if request.target_audience.interests:
                audience["interests"] = request.target_audience.interests
            if audience:
                post_data["targeting"] = audience

        logger.info(f"Making request to Facebook API with data: {post_data}")
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, data=post_data)

            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Failed to create post: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get(
                        "message", "Failed to create post")
                )

            result = response.json()
            logger.info(f"Post created successfully: {result}")
            return FacebookPostResponse(id=result["id"], success=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_facebook_post: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/media/photos", response_model=FacebookPostResponse)
async def upload_photos(
    request: MediaPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Get user's Facebook account
        query = """
        SELECT access_token, platform_account_id
        FROM mo_social_accounts 
        WHERE id = :account_id AND user_id = :user_id AND platform = 'facebook'
        """
        values = {
            "account_id": request.account_id,
            "user_id": current_user["uid"]
        }
        
        account = await db.fetch_one(query=query, values=values)
        
        if not account:
            raise HTTPException(status_code=404, detail="Facebook account not found")

        api_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/photos"
        
        async with httpx.AsyncClient() as client:
            # Upload the first photo (since this endpoint is for single photo upload)
            photo_url = request.media_urls[0]  # Take the first URL from the array
            
            post_data = {
                "url": photo_url,
                "access_token": account["access_token"],
                "published": False,  # Don't publish immediately
                "temporary": request.temporary
            }
            
            logger.info(f"Uploading photo: {photo_url}")
            response = await client.post(api_url, data=post_data)
            
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Photo upload failed: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get("message", "Failed to upload photo")
                )
            
            result = response.json()
            logger.info(f"Photo uploaded: {result}")
            
            # Update asset status
            await update_asset_status(db, photo_url, current_user["uid"])
            
            return FacebookPostResponse(id=result["id"], success=True)
            
    except Exception as e:
        logger.error(f"Error in upload_photos: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
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
            raise HTTPException(status_code=400, detail="Access token required")

        # Exchange token
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "fb_exchange_token": short_lived_token
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/oauth/access_token",
                params=params
            )
            
            if response.status_code != 200:
                error_data = response.json()
                raise HTTPException(
                    status_code=400,
                    detail=error_data.get("error", {}).get("message", "Token exchange failed")
                )

            token_data = response.json()
            return token_data

    except Exception as e:
        logger.error(f"Error exchanging token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/refresh-token", response_model=dict)
async def refresh_page_token(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Refresh page access token"""
    try:
        data = await request.json()
        page_id = data.get("page_id")
        
        if not page_id:
            raise HTTPException(status_code=400, detail="Page ID required")

        # Get current token from database
        query = """
        SELECT access_token, platform_account_id
        FROM mo_social_accounts 
        WHERE platform_account_id = :page_id 
        AND user_id = :user_id 
        AND platform = 'facebook'
        """
        
        account = await db.fetch_one(
            query=query,
            values={
                "page_id": page_id,
                "user_id": current_user["uid"]
            }
        )

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Get new page access token
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{page_id}",
                params={
                    "fields": "access_token",
                    "access_token": account["access_token"]
                }
            )
            
            if response.status_code != 200:
                error_data = response.json()
                raise HTTPException(
                    status_code=400,
                    detail=error_data.get("error", {}).get("message", "Token refresh failed")
                )

            token_data = response.json()
            new_token = token_data.get("access_token")

            if not new_token:
                raise HTTPException(status_code=400, detail="No new token received")

            # Update token in database
            expires_at = datetime.now(timezone.utc) + timedelta(days=60)
            
            update_query = """
            UPDATE mo_social_accounts 
            SET access_token = :access_token,
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE platform_account_id = :page_id 
            AND user_id = :user_id 
            AND platform = 'facebook'
            """

            await db.execute(
                query=update_query,
                values={
                    "access_token": new_token,
                    "expires_at": expires_at,
                    "updated_at": datetime.now(timezone.utc),
                    "page_id": page_id,
                    "user_id": current_user["uid"]
                }
            )

            return {
                "access_token": new_token,
                "expires_in": 60 * 24 * 60 * 60  # 60 days in seconds
            }

    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
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
            expires_at
        FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'facebook'
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

        # Check if token needs refresh (24 hours before expiry)
        expires_at = account["expires_at"]
        buffer_time = timedelta(hours=24)
        
        if expires_at - buffer_time <= datetime.now(timezone.utc):
            # Refresh token
            refresh_response = await refresh_page_token(
                request=request,
                current_user=current_user,
                db=db
            )
            return refresh_response
        
        return {
            "access_token": account["access_token"],
            "expires_in": int((expires_at - datetime.now(timezone.utc)).total_seconds())
        }

    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Utility functions
def validate_privacy(privacy: str) -> str:
    """Validate and normalize privacy setting"""
    valid_values = ['PUBLIC', 'FRIENDS', 'ONLY_ME']
    upper_v = privacy.upper()
    if upper_v not in valid_values:
        raise ValueError(f"Privacy must be one of: {', '.join(valid_values)}")
    return upper_v

async def get_facebook_account(db: Database, account_id: str, user_id: str) -> Dict[str, Any]:
    """Get Facebook account information from database"""
    query = """
    SELECT 
        id,
        access_token,
        platform_account_id,
        metadata,
        expires_at AT TIME ZONE 'UTC' as expires_at
    FROM mo_social_accounts 
    WHERE id = :account_id 
    AND user_id = :user_id 
    AND platform = 'facebook'
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
            detail="Facebook account not found"
        )

    return dict(account)

async def update_asset_status(db: Database, url: str, user_id: str, status: str = 'completed'):
    """Update asset processing status"""
    await db.execute("""
        UPDATE mo_assets 
        SET processing_status = :status,
            metadata = jsonb_set(
                metadata::jsonb,
                '{facebook_status}',
                :status_json
            )
        WHERE url = :url
        AND created_by = :user_id
    """, {
        "url": url,
        "user_id": user_id,
        "status": status,
        "status_json": f'"{status}"'
    })

# Media Upload Endpoints


@router.post("/media/presigned", response_model=MediaUploadResponse)
async def get_presigned_url(
    request: MediaUploadRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Generate presigned URL for media upload to R2 with asset tracking"""
    try:
        # Validate file type
        ext = os.path.splitext(request.filename)[1].lower()
        media_type = request.content_type.split('/')[0]

        if (media_type not in ALLOWED_TYPES or
                ext not in ALLOWED_TYPES[media_type]):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types are: {ALLOWED_TYPES}"
            )

        # Generate unique key
        timestamp = datetime.now().strftime('%Y/%m/%d')
        asset_id = str(uuid.uuid4())
        key = f"facebook/{current_user['uid']}/{timestamp}/{asset_id}{ext}"

        try:
            # Generate presigned URL
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod='put_object',
                Params={
                    'Bucket': bucket_name,
                    'Key': key,
                    'ContentType': request.content_type
                },
                ExpiresIn=3600  # 1 hour
            )

            logger.info(
                f"Generated presigned URL for Facebook media: {presigned_url}")

            # Insert record into assets table
            query = """
            INSERT INTO mo_assets (
                id, name, type, url, content_type, original_name,
                file_size, folder_id, created_by, processing_status,
                metadata, is_deleted, created_at, updated_at
            ) VALUES (
                :id, :name, :type, :url, :content_type, :original_name,
                :file_size, :folder_id, :created_by, :processing_status,
                :metadata, false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """

            values = {
                "id": asset_id,
                "name": request.filename,
                "type": media_type,
                "url": f"https://{CDN_DOMAIN}/{key}",
                "content_type": request.content_type,
                "original_name": request.filename,
                "file_size": 0,  # Will be updated after upload
                "folder_id": request.folder_id,
                "created_by": current_user["uid"],
                "processing_status": 'pending',
                "metadata": json.dumps({
                    "platform": "facebook",
                    "upload_status": "pending"
                })
            }

            await db.execute(query, values)

            return {
                "url": presigned_url,
                "asset_id": asset_id,
                "public_url": f"https://{CDN_DOMAIN}/{key}"
            }

        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate upload URL: {str(e)}"
            )

    except Exception as e:
        logger.error(f"Error in get_presigned_url: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/media/status/{asset_id}")
async def check_upload_status(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Check the status of a media upload"""
    try:
        query = """
        SELECT id, url, processing_status, processing_error, metadata
        FROM mo_assets
        WHERE id = :asset_id 
        AND created_by = :user_id 
        AND is_deleted = false
        """

        asset = await db.fetch_one(
            query=query,
            values={
                "asset_id": asset_id,
                "user_id": current_user["uid"]
            }
        )

        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        return {
            "id": asset["id"],
            "url": asset["url"],
            "status": asset["processing_status"],
            "error": asset["processing_error"],
            "metadata": json.loads(asset["metadata"]) if asset["metadata"] else None
        }

    except Exception as e:
        logger.error(f"Error checking upload status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/media/post", response_model=FacebookPostResponse)
async def create_media_post(
    request: MediaPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Create a media post (photos or videos) on Facebook"""
    try:
        account = await get_facebook_account(db, request.account_id, current_user["uid"])

        async with httpx.AsyncClient() as client:
            media_ids = []

            # First, upload all media to Facebook
            for media_url in request.media_urls:
                is_video = media_url.lower().endswith(('.mp4', '.mov'))

                if is_video:
                    # Upload video
                    video_data = {
                        "file_url": media_url,
                        "access_token": account["access_token"],
                        "description": request.text
                    }

                    if request.privacy != "PUBLIC":
                        video_data["privacy"] = {
                            "value": request.privacy.lower()}

                    response = await client.post(
                        f"{FACEBOOK_GRAPH_URL}/{account['platform_account_id']}/videos",
                        data=video_data
                    )
                else:
                    # Upload photo
                    photo_data = {
                        "url": media_url,
                        "access_token": account["access_token"],
                        "temporary": "true" if request.is_carousel else "false",
                        "published": "false" if request.is_carousel else "true"
                    }

                    if request.text and not request.is_carousel:
                        photo_data["message"] = request.text

                    if request.privacy != "PUBLIC":
                        photo_data["privacy"] = {
                            "value": request.privacy.lower()}

                    response = await client.post(
                        f"{FACEBOOK_GRAPH_URL}/{account['platform_account_id']}/photos",
                        data=photo_data
                    )

                if response.status_code != 200:
                    error_data = response.json()
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=error_data.get("error", {}).get(
                            "message", "Failed to upload media")
                    )

                result = response.json()
                media_ids.append(result["id"])

            # If it's a carousel post, create a feed post with all media
            if request.is_carousel:
                feed_data = {
                    "message": request.text,
                    "access_token": account["access_token"],
                    "attached_media": [{"media_fbid": media_id} for media_id in media_ids]
                }

                if request.privacy != "PUBLIC":
                    feed_data["privacy"] = {"value": request.privacy.lower()}

                if not request.allow_comments:
                    feed_data["enable_comments"] = False

                response = await client.post(
                    f"{FACEBOOK_GRAPH_URL}/{account['platform_account_id']}/feed",
                    data=feed_data
                )

                if response.status_code != 200:
                    error_data = response.json()
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=error_data.get("error", {}).get(
                            "message", "Failed to create carousel post")
                    )

                result = response.json()

            # Update asset status
            for media_url in request.media_urls:
                await update_asset_status(db, media_url, current_user["uid"])

            return FacebookPostResponse(
                id=result["id"]
            )

    except Exception as e:
        logger.error(f"Error creating media post: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/posts/photos", response_model=FacebookPostResponse)
async def create_photo_post(
    request: PhotoPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Get user's Facebook account
        query = """
        SELECT access_token, platform_account_id
        FROM mo_social_accounts 
        WHERE id = :account_id AND user_id = :user_id AND platform = 'facebook'
        """
        values = {
            "account_id": request.account_id,
            "user_id": current_user["uid"]
        }
        
        account = await db.fetch_one(query=query, values=values)
        
        if not account:
            raise HTTPException(status_code=404, detail="Facebook account not found")

        # Create post with photos
        feed_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/feed"
        
        # Construct attached_media as a list of numbered parameters
        attached_media = {}
        for idx, media_id in enumerate(request.media_ids):
            attached_media[f'attached_media[{idx}]'] = json.dumps({'media_fbid': media_id})

        post_data = {
            "access_token": account["access_token"],
            **attached_media  # Spread the numbered parameters
        }

        # Add optional parameters
        if request.text:
            post_data["message"] = request.text
            
        if request.privacy != PrivacyType.PUBLIC:
            post_data["privacy"] = {"value": request.privacy.lower()}
            
        if not request.allow_comments:
            post_data["enable_comments"] = False

        if request.target_audience:
            audience = {}
            if request.target_audience.age_min:
                audience["age_min"] = request.target_audience.age_min
            if request.target_audience.age_max:
                audience["age_max"] = request.target_audience.age_max
            if request.target_audience.countries:
                audience["countries"] = request.target_audience.countries
            if request.target_audience.interests:
                audience["interests"] = request.target_audience.interests
            if audience:
                post_data["targeting"] = audience

        async with httpx.AsyncClient() as client:
            logger.info(f"Creating photo post with data: {post_data}")
            response = await client.post(feed_url, data=post_data)
            
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Failed to create photo post: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get("message", "Failed to create photo post")
                )
            
            result = response.json()
            logger.info(f"Photo post created successfully: {result}")
            
            return FacebookPostResponse(id=result["id"], success=True)
            
    except Exception as e:
        logger.error(f"Error in create_photo_post: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# Add this to your models section at the top of the file
class VideoPostRequest(FacebookPostBase):
    url: str = Field(..., description="The URL of the video file")
    description: Optional[str] = Field(None, description="Video description")

# Update the endpoint implementation


async def update_video_upload_status(
    db: Database,
    url: str,
    user_id: str,
    status: str,
    error: Optional[str] = None
):
    """Update video upload status in database"""
    try:
        # Make sure status matches the constraint
        valid_statuses = ['pending', 'processing', 'completed', 'failed']
        db_status = 'processing' if status == 'uploading' else status
        if db_status not in valid_statuses:
            db_status = 'processing'

        # Prepare metadata
        select_query = """
            SELECT metadata 
            FROM mo_assets 
            WHERE url = :url AND created_by = :user_id
        """

        result = await db.fetch_one(
            query=select_query,
            values={"url": url, "user_id": user_id}
        )

        current_metadata = json.loads(
            result['metadata']) if result and result['metadata'] else {}
        current_metadata['facebook_upload'] = {
            'status': status,
            'error': error
        }

        update_query = """
            UPDATE mo_assets 
            SET 
                processing_status = :status,
                processing_error = :error,
                metadata = :metadata
            WHERE url = :url 
            AND created_by = :user_id
        """

        await db.execute(
            query=update_query,
            values={
                "url": url,
                "user_id": user_id,
                "status": db_status,  # Use the validated status
                "error": error,
                "metadata": json.dumps(current_metadata)
            }
        )

    except Exception as e:
        logger.error(f"Error updating video status: {str(e)}")
        # Continue without failing the whole upload process
        pass


@router.post("/media/videos", response_model=FacebookPostResponse)
async def upload_video(
    request: VideoPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Upload and post a video to Facebook"""
    try:
        # Get user's Facebook account
        account = await get_facebook_account(db, request.account_id, current_user["uid"])

        # Update initial status
        await update_video_upload_status(
            db, request.url, current_user["uid"], "uploading"
        )

        # Prepare video upload request
        api_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/videos"

        post_data = {
            "file_url": request.url,
            "access_token": account["access_token"],
            "description": request.description if request.description else "",
            "published": "true"
        }

        logger.info(f"Uploading video with data: {post_data}")
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(api_url, data=post_data)

            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Video upload failed: {error_data}")
                await update_video_upload_status(
                    db, request.url, current_user["uid"], "failed",
                    error_data.get("error", {}).get("message", "Upload failed")
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get(
                        "message", "Failed to upload video")
                )

            result = response.json()
            logger.info(f"Facebook API Response: {result}")

            # Handle different response formats
            video_id = result.get("id") or result.get("video_id")
            if not video_id:
                logger.error(f"Unexpected API response format: {result}")
                raise HTTPException(
                    status_code=500,
                    detail="Unable to get video ID from Facebook response"
                )

            # Update final status
            await update_video_upload_status(
                db, request.url, current_user["uid"], "completed"
            )

            return FacebookPostResponse(id=video_id, success=True)

    except Exception as e:
        logger.error(f"Error in upload_video: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        # Update status to failed
        await update_video_upload_status(
            db, request.url, current_user["uid"], "failed",
            str(e)
        )

        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/media/videos", response_model=FacebookPostResponse)
async def upload_video(
    request: VideoPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Upload and post a video to Facebook"""
    try:
        # Get user's Facebook account
        account = await get_facebook_account(db, request.account_id, current_user["uid"])

        # Update initial status
        await update_video_upload_status(
            db, request.url, current_user["uid"], "uploading"
        )

        # Prepare video upload request
        api_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/videos"

        post_data = {
            "file_url": request.url,
            "access_token": account["access_token"],
            "description": request.description if request.description else "",
            "published": "true"
        }

        logger.info(f"Uploading video with data: {post_data}")
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(api_url, data=post_data)

            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Video upload failed: {error_data}")
                await update_video_upload_status(
                    db, request.url, current_user["uid"], "failed",
                    error_data.get("error", {}).get("message", "Upload failed")
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get(
                        "message", "Failed to upload video")
                )

            result = response.json()
            logger.info(f"Facebook API Response: {result}")

            # Handle different response formats
            video_id = result.get("id") or result.get("video_id")
            if not video_id:
                logger.error(f"Unexpected API response format: {result}")
                raise HTTPException(
                    status_code=500,
                    detail="Unable to get video ID from Facebook response"
                )

            # Update final status
            await update_video_upload_status(
                db, request.url, current_user["uid"], "completed"
            )

            return FacebookPostResponse(id=video_id, success=True)

    except Exception as e:
        logger.error(f"Error in upload_video: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        # Update status to failed
        await update_video_upload_status(
            db, request.url, current_user["uid"], "failed",
            str(e)
        )

        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

# Add this utility function


async def get_file_size(url: str) -> int:
    """Get file size from URL using HEAD request"""
    async with httpx.AsyncClient() as client:
        response = await client.head(url)
        return int(response.headers.get('content-length', 0))


# Add this to your models section at the top of the file
class VideoPostCreateRequest(FacebookPostBase):
    media_id: str = Field(..., description="The uploaded video ID")
    text: Optional[str] = Field(None, description="Post caption")


@router.post("/posts/video", response_model=FacebookPostResponse)
async def create_video_post(
    request: VideoPostCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Create a post with an uploaded video"""
    try:
        # Get user's Facebook account
        account = await get_facebook_account(db, request.account_id, current_user["uid"])

        # Instead of creating a feed post, we'll update the video post directly
        api_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{request.media_id}"

        # Prepare update data
        post_data = {
            "access_token": account["access_token"]
        }

        # Add optional parameters
        if request.text:
            post_data["description"] = request.text

        if request.privacy != PrivacyType.PUBLIC:
            post_data["privacy"] = json.dumps(
                {"value": request.privacy.lower()})

        logger.info(f"Updating video post with data: {post_data}")
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, data=post_data)

            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Failed to update video post: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get(
                        "message", "Failed to update video post")
                )

            # For video updates, success response is just "true"
            # Return the original video ID as the post ID
            return FacebookPostResponse(id=request.media_id, success=True)

    except Exception as e:
        logger.error(f"Error in create_video_post: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

