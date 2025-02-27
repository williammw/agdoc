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

class DisconnectRequest(BaseModel):
    account_id: str

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
            raise HTTPException(
                status_code=400, detail="Missing code or state")

        # First check if this code has already been used successfully
        account_check = await db.fetch_one(
            """
            SELECT id FROM mo_social_accounts 
            WHERE user_id = :user_id 
            AND platform = 'threads' 
            AND metadata->>'auth_code' = :code
            """,
            values={
                "user_id": current_user["uid"],
                "code": code
            }
        )

        # If we already have an account with this code, return success
        if account_check:
            return {
                "success": True,
                "message": "Account already connected"
            }

        # Verify state
        state_record = await db.fetch_one(
            """
            SELECT user_id, expires_at 
            FROM mo_oauth_states 
            WHERE state = :state AND platform = 'threads'
            FOR UPDATE
            """,
            values={"state": state}
        )

        if not state_record:
            logger.warning(f"State not found: {state}")
            raise HTTPException(status_code=400, detail="Invalid state")

        if state_record["expires_at"] < datetime.now(timezone.utc):
            logger.warning(f"State expired: {state}")
            raise HTTPException(status_code=400, detail="State expired")

        if state_record["user_id"] != current_user["uid"]:
            logger.warning(f"User mismatch for state: {state}")
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
                raise HTTPException(
                    status_code=400,
                    detail=error_data.get("error", {}).get(
                        "message", "Failed to exchange code")
                )

            token_data = token_response.json()
            platform_account_id = str(token_data.get('user_id', ''))

            # Get user info
            user_info_response = await client.get(
                f"{THREADS_API_URL}/{platform_account_id}",
                params={
                    'fields': 'id,username,name,threads_profile_picture_url,threads_biography',
                    'access_token': token_data['access_token']
                }
            )

            if user_info_response.status_code != 200:
                logger.error(
                    f"Failed to get user info: {user_info_response.text}")
                raise HTTPException(
                    status_code=400, detail="Failed to get user info")

            user_info = user_info_response.json()

            # Delete state after successful use
            await db.execute(
                "DELETE FROM mo_oauth_states WHERE state = :state AND platform = 'threads'",
                values={"state": state}
            )

            # Store account
            now = datetime.now(timezone.utc)
            expires_at = now + \
                timedelta(seconds=token_data.get('expires_in', 3600))

            metadata = {
                "name": user_info.get('name', ''),
                "biography": user_info.get('threads_biography', ''),
                "raw_response": user_info,
                "auth_code": code,  # Store code to prevent reuse
                "connected_at": now.isoformat()
            }

            # Use transaction for the account update
            async with db.transaction():
                await db.execute(
                    """
                    INSERT INTO mo_social_accounts (
                        user_id, platform, platform_account_id, username,
                        profile_picture_url, access_token, expires_at,
                        metadata, created_at, updated_at
                    ) VALUES (
                        :user_id, 'threads', :platform_account_id, :username,
                        :profile_picture_url, :access_token, :expires_at,
                        :metadata, :now, :now
                    ) ON CONFLICT (platform, user_id, platform_account_id) 
                    DO UPDATE SET
                        username = EXCLUDED.username,
                        profile_picture_url = EXCLUDED.profile_picture_url,
                        access_token = EXCLUDED.access_token,
                        expires_at = EXCLUDED.expires_at,
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                    """,
                    values={
                        "user_id": current_user["uid"],
                        "platform_account_id": platform_account_id,
                        "username": user_info.get('username', ''),
                        "profile_picture_url": user_info.get('threads_profile_picture_url', ''),
                        "access_token": token_data['access_token'],
                        "expires_at": expires_at,
                        "metadata": json.dumps(metadata),
                        "now": now
                    }
                )

            return {
                "access_token": token_data['access_token'],
                "user_id": platform_account_id,
                "expires_in": token_data.get('expires_in'),
                "token_type": token_data.get('token_type')
            }

    except Exception as e:
        logger.error(f"Error in threads_auth_callback: {str(e)}")
        logger.error(traceback.format_exc())
        if isinstance(e, HTTPException):
            raise
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

@router.get("/user")
async def get_threads_user(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get Threads user profile and connected accounts"""
    try:
        # Get auth header but don't validate it (already done by get_current_user)
        auth_header = request.headers.get('Authorization')
        logger.info(f"Processing request with auth header: {auth_header[:20]}...")

        query = """
        SELECT 
            id,
            platform_account_id,
            username,
            profile_picture_url,
            access_token,
            expires_at AT TIME ZONE 'UTC' as expires_at,
            metadata
        FROM mo_social_accounts 
        WHERE user_id = :user_id 
        AND platform = 'threads'
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
                try:
                    account_dict["metadata"] = json.loads(account_dict["metadata"])
                except json.JSONDecodeError:
                    account_dict["metadata"] = {}
            
            # Convert datetime to ISO format string
            if account_dict.get("expires_at"):
                account_dict["expires_at"] = account_dict["expires_at"].isoformat()

            account_list.append(account_dict)

        return {
            "connected": True,
            "accounts": account_list
        }

    except Exception as e:
        logger.error(f"Error in get_threads_user: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    



@router.post("/auth/disconnect")
async def disconnect_threads(
    request: DisconnectRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Disconnect a Threads account"""
    try:
        # Delete the account from database
        query = """
        DELETE FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'threads'
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
            raise HTTPException(status_code=404, detail="Account not found")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in disconnect_threads: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

