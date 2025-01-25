import logging
from fastapi import APIRouter, HTTPException, Depends, Request
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
from app.services.facebook import FacebookAPI
import httpx
from enum import Enum
from typing import Optional


class PrivacyType(str, Enum):
    PUBLIC = "PUBLIC"
    FRIENDS = "FRIENDS"
    ONLY_ME = "ONLY_ME"


class TargetAudience(BaseModel):
    age_min: Optional[int] = Field(None, ge=13, le=65)
    age_max: Optional[int] = Field(None, ge=13, le=65)
    countries: Optional[List[str]] = None
    interests: Optional[List[str]] = None


class MediaUploadRequest(BaseModel):
    account_id: str = Field(..., description="The Facebook page ID")
    page_access_token: str = Field(..., description="The page access token")
    url: str = Field(..., description="URL of the media")
    caption: Optional[str] = None
    privacy: PrivacyType = Field(default=PrivacyType.PUBLIC)
    allow_comments: bool = Field(default=True)


class FacebookPostRequest(BaseModel):
    account_id: str = Field(..., description="The Facebook page ID")
    text: str = Field(..., description="The post content")
    privacy: str = Field(
        default="PUBLIC", description="Post privacy setting")
    allow_comments: bool = Field(
        default=True, description="Whether to allow comments")
    target_audience: Optional[TargetAudience] = None

    @validator('privacy')
    def validate_privacy(cls, v):
        valid_values = ['PUBLIC', 'FRIENDS', 'ONLY_ME']
        upper_v = v.upper()
        if upper_v not in valid_values:
            raise ValueError(f"Privacy must be one of: {', '.join(valid_values)}")
        return upper_v


class FacebookPostResponse(BaseModel):
    id: str = Field(..., description="The created post ID")
    success: bool = Field(
        default=True, description="Whether the post was created successfully")


class FacebookDisconnectRequest(BaseModel):
    account_id: str


class FacebookDisconnectResponse(BaseModel):
    success: bool
    message: Optional[str] = None


class TextPostRequest(BaseModel):
    account_id: str
    text: str
    privacy: str = Field(..., pattern="^(public|friends|only_me)$",description="Privacy setting: 'public', 'friends', or 'only_me'")
    allow_comments: bool = True
    target_audience: Optional[TargetAudience] = None


class TextPostResponse(BaseModel):
    id: str


class PhotoUploadRequest(BaseModel):
    account_id: str = Field(..., description="The Facebook page ID")
    text: str = Field(..., description="The post content")
    photos: List[str] = Field(..., description="List of photo URLs")
    privacy: str = Field(default="PUBLIC", description="Post privacy setting")
    allowComments: bool = Field(default=True, description="Whether to allow comments")
    targetAudience: Optional[TargetAudience] = None

    @validator('privacy')
    def validate_privacy(cls, v):
        valid_values = ['PUBLIC', 'FRIENDS', 'ONLY_ME']
        upper_v = v.upper()
        if upper_v not in valid_values:
            raise ValueError(f"Privacy must be one of: {', '.join(valid_values)}")
        return upper_v


router = APIRouter()
logger = logging.getLogger(__name__)

# Load environment variables at module level
FACEBOOK_API_VERSION = os.environ.get("FACEBOOK_API_VERSION", "v21.0")
FACEBOOK_OAUTH_URL = f"https://www.facebook.com/{FACEBOOK_API_VERSION}/dialog/oauth"
FACEBOOK_SCOPE = "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_metadata,business_management"
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://dev.multivio.com")

# Log environment variables at module load
logger.info("Facebook Router Environment Variables:")
logger.info(f"FACEBOOK_API_VERSION: {FACEBOOK_API_VERSION}")
logger.info(f"FACEBOOK_APP_ID present: {bool(FACEBOOK_APP_ID)}")
logger.info(f"FACEBOOK_APP_SECRET present: {bool(FACEBOOK_APP_SECRET)}")
logger.info(f"FRONTEND_URL: {FRONTEND_URL}")


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
    request: FacebookPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        logger.info(f"Creating post for account: {request.account_id}")
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
        logger.info(f"Executing query with values: {values}")
        
        account = await db.fetch_one(query=query, values=values)
        
        if not account:
            logger.error(f"Account not found for id: {request.account_id}")
            raise HTTPException(status_code=404, detail="Facebook account not found")
            
        logger.info(f"Found account: {account}")
        
        # Prepare the Graph API request
        api_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/feed"
        
        # Prepare post data
        post_data = {
            "message": request.text,
            "access_token": account["access_token"]
        }

        # Add privacy settings if not public
        if request.privacy != "PUBLIC":
            post_data["privacy"] = {"value": request.privacy.lower()}

        # Disable comments if specified
        if not request.allow_comments:
            post_data["enable_comments"] = False

        logger.info(f"Making request to Facebook API: {api_url}")
        # Make the request to Facebook Graph API
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, data=post_data)
            
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Facebook API error: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get("message", "Failed to create Facebook post")
                )

            result = response.json()
            logger.info(f"Post created successfully: {result}")
            return FacebookPostResponse(
                id=result["id"],
                success=True
            )

    except Exception as e:
        logger.error(f"Error in create_facebook_post: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/media/photos", response_model=FacebookPostResponse)
async def upload_photos(
    request: PhotoUploadRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        logger.info(f"Uploading photos with text: {request.text}")
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
        logger.info(f"Executing query with values: {values}")
        
        account = await db.fetch_one(query=query, values=values)
        
        if not account:
            logger.error(f"Account not found for id: {request.account_id}")
            raise HTTPException(status_code=404, detail="Facebook account not found")
            
        logger.info(f"Found account: {account}")

        api_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/photos"
        
        async with httpx.AsyncClient() as client:
            # Upload each photo
            photo_ids = []
            for photo_url in request.photos:
                post_data = {
                    "url": photo_url,
                    "access_token": account["access_token"],
                    "published": False
                }
                
                logger.info(f"Uploading photo: {photo_url}")
                response = await client.post(api_url, data=post_data)
                if response.status_code != 200:
                    error_data = response.json()
                    logger.error(f"Photo upload failed: {error_data}")
                    raise HTTPException(status_code=response.status_code, detail="Failed to upload photo")
                
                result = response.json()
                logger.info(f"Photo uploaded: {result}")
                photo_ids.append(result["id"])
            
            # Create post with photos
            feed_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{account['platform_account_id']}/feed"
            post_data = {
                "message": request.text,
                "access_token": account["access_token"],
                "attached_media": [{"media_fbid": photo_id} for photo_id in photo_ids]
            }
            
            if request.privacy != "PUBLIC":
                post_data["privacy"] = {"value": request.privacy.lower()}
            
            if not request.allowComments:
                post_data["enable_comments"] = False
                
            logger.info("Creating post with photos")
            response = await client.post(feed_url, data=post_data)
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Post creation failed: {error_data}")
                raise HTTPException(status_code=response.status_code, detail="Failed to create post")
                
            result = response.json()
            logger.info(f"Post created successfully: {result}")
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
