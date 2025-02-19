import logging
import uuid
import boto3
from fastapi import APIRouter, HTTPException, Depends, Request
from databases import Database
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import secrets
import traceback
from datetime import datetime, timezone, timedelta
from app.dependencies import get_current_user, get_database
# from app.models.mo_social import OauthState, OauthInitResponse
from urllib.parse import quote, urlencode
import json
import httpx
from fastapi.responses import RedirectResponse, HTMLResponse

# Configure logging
logger = logging.getLogger(__name__)
    
# Constants from environment
THREADS_API_VERSION = os.environ.get("THREADS_API_VERSION", "v22.0")
THREADS_APP_ID = os.environ.get("THREADS_APP_ID")
THREADS_APP_SECRET = os.environ.get("THREADS_APP_SECRET")
THREADS_REDIRECT_URI = os.environ.get("THREADS_REDIRECT_URI")

# API Endpoints
THREADS_OAUTH_URL = "https://threads.net/oauth/authorize"
THREADS_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
THREADS_API_URL = "https://graph.threads.net"

# Required scopes
THREADS_SCOPE = "threads_basic,threads_content_publish"

# Models
class OAuthInitResponse(BaseModel):
    auth_url: str
    state: str

class TokenResponse(BaseModel):
    access_token: str
    user_id: str
    expires_in: Optional[int]
    token_type: Optional[str]

router = APIRouter( tags=["threads"])

@router.get("/landing")
async def threads_landing(request: Request):
    return {"message": "Threads landing"}

@router.post("/auth/init", response_model=OAuthInitResponse)
async def threads_auth_init(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Initialize Threads OAuth flow"""
    try:
        if not THREADS_APP_ID:
            raise HTTPException(status_code=500, detail="THREADS_APP_ID not configured")

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Store state in database
        query = """
        INSERT INTO mo_oauth_states (
            state, platform, user_id, expires_at, created_at
        ) VALUES (:state, 'threads', :user_id, :expires_at, :created_at)
        """
        
        now = datetime.now(timezone.utc)
        await db.execute(query=query, values={
            "state": state,
            "user_id": current_user["uid"],
            "expires_at": now + timedelta(minutes=10),
            "created_at": now
        })

        # Build authorization URL
        params = {
            'client_id': THREADS_APP_ID,
            'redirect_uri': THREADS_REDIRECT_URI,
            'scope': THREADS_SCOPE,
            'response_type': 'code',
            'state': state
        }

        auth_url = f"{THREADS_OAUTH_URL}?{urlencode(params)}"
        logger.info(f"Generated Threads auth URL: {auth_url}")

        return OAuthInitResponse(auth_url=auth_url, state=state)

    except Exception as e:
        logger.error(f"Error in threads_auth_init: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/callback")
async def threads_auth_callback(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Handle OAuth callback and exchange code for tokens"""
    try:
        data = await request.json()
        code = data.get("code")
        state = data.get("state")

        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing code or state")

        # Verify state
        query = """
        SELECT user_id, expires_at 
        FROM mo_oauth_states 
        WHERE state = :state AND platform = 'threads'
        """
        state_record = await db.fetch_one(query=query, values={"state": state})

        if not state_record:
            raise HTTPException(status_code=400, detail="Invalid state")
        if state_record["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="State expired")
        if state_record["user_id"] != current_user["uid"]:
            raise HTTPException(status_code=400, detail="User mismatch")

        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_response = await client.post(
                THREADS_TOKEN_URL,
                data={
                    'client_id': THREADS_APP_ID,
                    'client_secret': THREADS_APP_SECRET,
                    'grant_type': 'authorization_code',
                    'redirect_uri': THREADS_REDIRECT_URI,
                    'code': code
                }
            )
            
            if token_response.status_code != 200:
                error_data = token_response.json()
                logger.error(f"Token exchange failed: {error_data}")
                error_message = error_data.get("error", {}).get("message", "Failed to exchange code for token")
                raise HTTPException(status_code=400, detail=error_message)
                
            token_data = token_response.json()
            
            # Ensure user_id is properly formatted as string
            try:
                platform_account_id = str(token_data.get('user_id', ''))[:50]  # Limit to 50 chars
                if not platform_account_id:
                    raise ValueError("Empty user_id received from Threads")
            except (TypeError, ValueError) as e:
                logger.error(f"Error formatting user_id: {str(e)}")
                raise HTTPException(status_code=400, detail="Invalid user ID received from Threads")

            # Get user info from Threads using the SAME client session
            logger.info(f"Fetching user info for platform_account_id: {platform_account_id}")
            user_info_response = await client.get(
                f"{THREADS_API_URL}/{platform_account_id}",
                params={
                    'fields': 'id,username,name,threads_profile_picture_url,threads_biography',
                    'access_token': token_data['access_token']
                }
            )

            logger.info(f"User info response status: {user_info_response.status_code}")
            logger.info(f"User info raw response: {user_info_response.text}")

            if user_info_response.status_code != 200:
                logger.error(f"Failed to get user info: {user_info_response.text}")
                raise HTTPException(status_code=400, detail="Failed to get user info from Threads")

            user_info = user_info_response.json()

            # Store in database
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=token_data.get('expires_in', 3600))

            query = """
            INSERT INTO mo_social_accounts (
                user_id, platform, platform_account_id, username, profile_picture_url,
                access_token, expires_at, metadata, created_at, updated_at
            ) VALUES (
                :user_id, 'threads', :platform_account_id, :username, :profile_picture_url,
                :access_token, :expires_at, :metadata, :created_at, :created_at
            ) ON CONFLICT (platform, user_id, platform_account_id) 
            DO UPDATE SET
                username = EXCLUDED.username,
                profile_picture_url = EXCLUDED.profile_picture_url,
                access_token = EXCLUDED.access_token,
                expires_at = EXCLUDED.expires_at,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.created_at
            """

            await db.execute(query=query, values={
                "user_id": current_user["uid"],
                "platform_account_id": platform_account_id,
                "username": user_info.get('username', ''),
                "profile_picture_url": user_info.get('threads_profile_picture_url', ''),
                "access_token": token_data['access_token'],
                "expires_at": expires_at,
                "metadata": json.dumps({
                    "name": user_info.get('name', ''),
                    "biography": user_info.get('threads_biography', ''),
                    "raw_response": user_info
                }),
                "created_at": now
            })

            return TokenResponse(
                access_token=token_data['access_token'],
                user_id=platform_account_id,
                expires_in=token_data.get('expires_in'),
                token_type=token_data.get('token_type')
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in threads_auth_callback: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/refresh")
async def refresh_token(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Refresh a long-lived token"""
    try:
        # Get current token from database
        query = """
        SELECT access_token, expires_at
        FROM mo_social_accounts
        WHERE user_id = :user_id AND platform = 'threads'
        """
        token_record = await db.fetch_one(query=query, values={"user_id": current_user["uid"]})

        if not token_record:
            raise HTTPException(status_code=404, detail="No token found")

        # Refresh token
        async with httpx.AsyncClient() as client:
            refresh_response = await client.get(
                f"{THREADS_API_URL}/refresh_access_token",
                params={
                    'grant_type': 'th_refresh_token',
                    'access_token': token_record['access_token']
                }
            )

            if refresh_response.status_code != 200:
                error_data = refresh_response.json()
                logger.error(f"Token refresh failed: {error_data}")
                raise HTTPException(status_code=400, detail=error_data.get("error_message", "Failed to refresh token"))

            token_data = refresh_response.json()

            # Update token in database
            query = """
            UPDATE mo_social_accounts
            SET access_token = :access_token,
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE user_id = :user_id AND platform = 'threads'
            """

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=token_data['expires_in'])

            await db.execute(query=query, values={
                "user_id": current_user["uid"],
                "access_token": token_data['access_token'],
                "expires_at": expires_at,
                "updated_at": now
            })

            return TokenResponse(**token_data)

    except Exception as e:
        logger.error(f"Error in refresh_token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
async def threads_callback(
    code: str,
    state: str,
    request: Request,
    db: Database = Depends(get_database)
):
    """Handle the initial OAuth callback"""
    try:
        # Return success page that closes itself
        html_content = """
        <!DOCTYPE html>
        <html>
        <body>
            <script>
                window.close();
            </script>
            <p>Authentication successful! You can close this window.</p>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    except Exception as e:
        error_msg = quote(str(e))
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body>
            <script>
                window.close();
            </script>
            <p>Authentication failed: {error_msg}</p>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)

@router.get("/user/me")
async def get_threads_user(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get connected Threads accounts for the current user"""
    try:
        # Get the authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

        # Extract Firebase token (not Threads token)
        firebase_token = auth_header.split(' ')[1]
        
        # Verify Firebase token and get user info
        try:
            # This should be handled by get_current_user dependency
            if not current_user or not current_user.get("uid"):
                raise HTTPException(status_code=401, detail="Invalid authentication")
            
            query = """
            SELECT 
                id,
                platform_account_id,
                username,
                profile_picture_url,
                access_token,
                expires_at,
                metadata,
                created_at,
                updated_at
            FROM mo_social_accounts 
            WHERE user_id = :user_id AND platform = 'threads'
            """
            
            accounts = await db.fetch_all(query=query, values={"user_id": current_user["uid"]})
            
            if not accounts:
                return []
                
            return [
                {
                    "id": str(account["id"]),
                    "platform_account_id": account["platform_account_id"],
                    "username": account["username"],
                    "profile_picture_url": account["profile_picture_url"],
                    "metadata": json.loads(account["metadata"]) if account["metadata"] else {},
                    "created_at": account["created_at"].isoformat() if account["created_at"] else None,
                    "updated_at": account["updated_at"].isoformat() if account["updated_at"] else None
                }
                for account in accounts
            ]

        except Exception as e:
            logger.error(f"Error verifying Firebase token: {str(e)}")
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_threads_user: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

