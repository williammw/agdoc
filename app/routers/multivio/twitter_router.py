import logging
import secrets
import httpx
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from databases import Database
from datetime import datetime, timezone, timedelta
from app.dependencies import get_current_user, get_database
from typing import Optional
import os
import json
import traceback

router = APIRouter(tags=["twitter"])
logger = logging.getLogger(__name__)

# Constants
TWITTER_CLIENT_ID = os.getenv("TWITTER_OAUTH2_CLIENT_ID")
TWITTER_CLIENT_SECRET = os.getenv("TWITTER_OAUTH2_CLIENT_SECRET")
TWITTER_API_V2 = "https://api.x.com/2"
CALLBACK_URL = os.getenv("TWITTER_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL")
TWITTER_UPLOAD_API = "https://upload.twitter.com/1.1/media/upload.json"

@router.post("/auth/init")
async def init_oauth(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Initialize Twitter OAuth flow"""
    try:
        if not TWITTER_CLIENT_ID:
            raise HTTPException(
                status_code=500, detail="Twitter Client ID not configured")

        # Generate state and PKCE values
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = generate_code_challenge(code_verifier)

        # Store state and code_verifier
        now = datetime.now(timezone.utc)
        query = """
        INSERT INTO mo_oauth_states (
            state,
            platform,
            user_id,
            code_verifier,
            expires_at,
            created_at
        ) VALUES (
            :state,
            'twitter',
            :user_id,
            :code_verifier,
            :expires_at,
            :created_at
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

        # Generate OAuth URL
        params = {
            'response_type': 'code',
            'client_id': TWITTER_CLIENT_ID,
            'redirect_uri': CALLBACK_URL,
            'scope': 'tweet.read tweet.write users.read offline.access',
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }

        auth_url = f"https://twitter.com/i/oauth2/authorize?{httpx.QueryParams(params)}"

        return {
            "auth_url": auth_url,
            "state": state,
            "code_verifier": code_verifier
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
    """Handle Twitter OAuth callback"""
    try:
        # Log incoming request data
        data = await request.json()
        logger.info(f"Received callback data: {data}")
        code = data.get("code")
        state = data.get("state")

        if not code or not state:
            raise HTTPException(
                status_code=400,
                detail="Missing code or state parameter"
            )

        # Verify state and get stored data
        logger.info(f"Verifying state: {state}")
        query = """
        SELECT 
            state, user_id, code_verifier, 
            expires_at AT TIME ZONE 'UTC' as expires_at
        FROM mo_oauth_states 
        WHERE state = :state 
        AND platform = 'twitter'
        """

        stored_data = await db.fetch_one(query=query, values={"state": state})
        logger.info(f"Retrieved stored data: {stored_data}")

        if not stored_data:
            raise HTTPException(status_code=400, detail="Invalid state")

        # Convert expires_at to timezone-aware datetime if it isn't already
        expires_at = stored_data["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="State expired")

        if stored_data["user_id"] != current_user["uid"]:
            raise HTTPException(status_code=400, detail="User mismatch")

        # Check for already processed code
        account_query = """
        SELECT id FROM mo_social_accounts 
        WHERE user_id = :user_id 
        AND platform = 'twitter'
        AND metadata->>'oauth_code' = :code
        """
        
        existing_account = await db.fetch_one(
            query=account_query,
            values={
                "user_id": current_user["uid"],
                "code": code
            }
        )

        if existing_account:
            return {
                "message": "Account already connected",
                "success": True
            }

        # Exchange code for tokens
        token_url = f"{TWITTER_API_V2}/oauth2/token"
        token_data = {
            'code': code,
            'grant_type': 'authorization_code',
            'client_id': TWITTER_CLIENT_ID,
            'redirect_uri': CALLBACK_URL,
            'code_verifier': stored_data["code_verifier"]
        }

        logger.info(f"Exchanging code for token with data: {token_data}")
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                token_url,
                data=token_data,
                auth=(TWITTER_CLIENT_ID, TWITTER_CLIENT_SECRET)
            )

            if token_response.status_code != 200:
                error_data = token_response.json()
                logger.error(f"Token exchange failed: {error_data}")
                raise HTTPException(
                    status_code=token_response.status_code,
                    detail=f"Failed to exchange code for token: {error_data.get('error_description', '')}"
                )

            tokens = token_response.json()
            logger.info("Successfully obtained tokens")

            # Get user info
            user_response = await client.get(
                f"{TWITTER_API_V2}/users/me",
                headers={
                    "Authorization": f"Bearer {tokens['access_token']}",
                },
                params={
                    "user.fields": "profile_image_url,verified,public_metrics"
                }
            )

            if user_response.status_code != 200:
                error_data = user_response.json()
                logger.error(f"Failed to get user info: {error_data}")
                raise HTTPException(
                    status_code=user_response.status_code,
                    detail="Failed to get user info"
                )

            user_data = user_response.json()["data"]
            logger.info(f"Retrieved user data: {user_data}")

            # Store in database
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=tokens['expires_in'])

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
                'twitter',
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

            values = {
                "user_id": current_user["uid"],
                "platform_account_id": user_data["id"],
                "username": user_data["username"],
                "profile_picture_url": user_data.get("profile_image_url"),
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_at": expires_at,
                "metadata": json.dumps({
                    "verified": user_data.get("verified", False),
                    "metrics": user_data.get("public_metrics", {}),
                    "oauth_code": code  # Track processed codes
                }),
                "created_at": now
            }

            await db.execute(query=query, values=values)
            logger.info("Successfully stored account data")

            # Clean up oauth state
            await db.execute(
                "DELETE FROM mo_oauth_states WHERE state = :state",
                {"state": state}
            )

            return {
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_in": tokens["expires_in"]
            }

    except Exception as e:
        logger.error(f"Error in oauth_callback: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        if isinstance(e, HTTPException):
            raise e

        raise HTTPException(
            status_code=500,
            detail=f"Failed to process callback: {str(e)}"
        )


@router.get("/user")
async def get_twitter_user(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get Twitter user profile and connected accounts"""
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
            if account_dict["metadata"]:
                account_dict["metadata"] = json.loads(account_dict["metadata"])
            account_list.append(account_dict)

        return {
            "connected": True,
            "accounts": account_list
        }

    except Exception as e:
        logger.error(f"Error in get_twitter_user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/me")
async def get_current_user_profile(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    authorization: str = Header(...)
):
    """Get current user's Twitter profile"""
    try:
        if not authorization or not authorization.startswith('Bearer '):
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.split(' ')[1]

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TWITTER_API_V2}/users/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "x-twitter-client-id": TWITTER_CLIENT_ID
                },
                params={
                    "user.fields": "id,name,username,profile_image_url,verified,public_metrics"
                }
            )

            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Twitter API error: {error_data}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get("error", {}).get(
                        "message", "Failed to fetch user profile")
                )

            user_data = response.json()

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

# Utility functions


def generate_code_challenge(code_verifier: str) -> str:
    """Generate PKCE code challenge from verifier"""
    import base64
    import hashlib

    sha256_hash = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")
