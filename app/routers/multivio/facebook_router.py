from fastapi import APIRouter, Depends, HTTPException, Request
from databases import Database
import logging
import secrets
import os
from datetime import datetime, timedelta, timezone
from app.dependencies import get_current_user, get_database
from app.models.mo_social import OAuthState, OAuthInitResponse
from urllib.parse import quote, urlencode
import json

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

        import httpx
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
