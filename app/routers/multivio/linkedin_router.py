"""
LinkedIn router implementation aligned with official LinkedIn OAuth documentation.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import requests
from urllib.parse import urlencode
import os
from dotenv import load_dotenv
import secrets
from app.dependencies import get_current_user, get_database
import logging
import time
import traceback
import json
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from uuid import UUID, uuid4
from databases import Database
from enum import Enum
import base64
import hashlib

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(tags=['LinkedIn'])

# Configuration
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Define the type of your LinkedIn app (affects OAuth flow)
# Should be either "web" or "native" - based on your LinkedIn Developer Portal settings
LINKEDIN_APP_TYPE = os.getenv("LINKEDIN_APP_TYPE", "web")  # Default to web application

# Define redirect URIs for different environments
REDIRECT_URIS = {
    "production": "https://www.multivio.com/linkedin/callback",
    "development": "https://dev.multivio.com/linkedin/callback",
    "local": "https://dev.multivio.com/linkedin/callback"
}

# Get the appropriate redirect URI based on environment
# IMPORTANT: Use LINKEDIN_REDIRECT_URI env var, not REDIRECT_URI
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", REDIRECT_URIS.get(
    ENVIRONMENT, REDIRECT_URIS["development"]))

logger.info(f"LinkedIn OAuth Configuration:")
logger.info(f"Client ID: {CLIENT_ID[:5]}... (truncated)")
logger.info(f"Redirect URI: {REDIRECT_URI}")
logger.info(f"Environment: {ENVIRONMENT}")
logger.info(f"App Type: {LINKEDIN_APP_TYPE}")

# LinkedIn API endpoints
API_BASE = "https://api.linkedin.com/v2"
AUTH_BASE = "https://www.linkedin.com/oauth/v2"

ENDPOINTS = {
    "auth": "https://www.linkedin.com/oauth/v2/authorization",
    "token": "https://www.linkedin.com/oauth/v2/accessToken",
    "profile": "https://api.linkedin.com/v2/me",
    "email": "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))",
    "share": "https://api.linkedin.com/v2/ugcPosts",
    "organizations": "https://api.linkedin.com/v2/organizationalEntityAcls?q=roleAssignee",
    "organization_details": "https://api.linkedin.com/v2/organizations/{id}"
}

# LinkedIn API scopes
LINKEDIN_SCOPES = {
    "basic": [
        "openid",              # Use name and photo
        "profile",             # Use name and photo
        "email",              # Use primary email
        "r_basicprofile",     # Basic profile info
    ],
    "social": [
        "w_member_social",     # Create posts on behalf of member
        "r_organization_social",  # Read org posts
        "w_organization_social",  # Create org pw_organization_socialosts
    ],
    "organization": [
        "r_organization_admin",  # Read org pages and analytics
        "rw_organization_admin",  # Manage org pages
    ],
    "advertising": [
        "r_ads",               # Read ad accounts
        "rw_ads",              # Manage ad accounts
        "r_ads_reporting",     # Read ad reporting
    ],
    "connections": [
        "r_1st_connections_size",  # Number of connections
    ]
}

# Choose the scopes you need
REQUIRED_SCOPES = [
    *LINKEDIN_SCOPES["basic"],
    *LINKEDIN_SCOPES["social"],
    *LINKEDIN_SCOPES["organization"]
]

# Add this enum class
class SocialPlatform(str, Enum):
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    THREADS = "threads"

# Models
class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: Optional[str] = None

class UserProfile(BaseModel):
    id: str
    firstName: str
    lastName: str
    profilePicture: Optional[str] = None
    email: Optional[str] = None

class SharePost(BaseModel):
    text: str
    visibility: str = "PUBLIC"
    article_url: Optional[str] = None
    organization_id: Optional[str] = None

class ArticleMetadata(BaseModel):
    url: str

class OAuthState(BaseModel):
    state: str
    platform: SocialPlatform = SocialPlatform.LINKEDIN
    user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    code_verifier: str = ""

class SocialAccount(BaseModel):
    id: Optional[UUID] = None
    user_id: str
    platform: SocialPlatform = SocialPlatform.LINKEDIN
    platform_account_id: str
    username: str
    profile_picture_url: Optional[str] = None
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata: Optional[dict] = None
    media_type: Optional[str] = None
    media_count: Optional[int] = 0

# State management for CSRF protection
active_states = {}

def generate_state():
    state = secrets.token_urlsafe(32)
    active_states[state] = time.time()
    return state

def validate_state(state: str) -> bool:
    timestamp = active_states.get(state)
    if not timestamp:
        return False
    # Remove expired states (older than 1 hour)
    current_time = time.time()
    active_states.clear()
    return (current_time - timestamp) < 3600

@router.get("/auth/init")
async def linkedin_auth(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Initialize LinkedIn OAuth flow based on app type (web or native)"""
    try:
        # Get the user ID - depending on how it's set in the current_user dict
        user_id = current_user.get('uid') or current_user.get('id')
        logger.debug(f"Initializing LinkedIn auth for user: {user_id}")

        # Generate state for CSRF protection
        state = generate_state()

        # Generate code verifier and challenge for PKCE - only used for native apps
        code_verifier = None
        code_challenge = None
        
        if LINKEDIN_APP_TYPE.lower() == "native":
            # For native apps, PKCE is required
            code_verifier = secrets.token_urlsafe(48)  # This gives about 64 chars
            code_challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
            code_challenge = base64.urlsafe_b64encode(
                code_challenge_bytes).decode().rstrip("=")
            logger.info("Using PKCE flow for native app")
        else:
            # For web apps, PKCE is not needed
            logger.info("Using standard OAuth flow for web app")

        # Store state and optional code_verifier in database
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=10)
        
        # Prepare for database storage
        insert_values = {
            "state": state,
            "platform": "linkedin",
            "user_id": user_id,
            "created_at": now,
            "expires_at": expires_at,
            "code_verifier": code_verifier or ""  # Store empty string if None
        }
        
        await db.execute(
            """
            INSERT INTO mo_oauth_states (
                state, 
                platform, 
                user_id, 
                created_at, 
                expires_at, 
                code_verifier
            )
            VALUES (
                :state, 
                :platform, 
                :user_id, 
                :created_at, 
                :expires_at, 
                :code_verifier
            )
            """,
            insert_values
        )

        # Construct auth URL - add PKCE parameters only for native apps
        auth_params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "scope": " ".join(REQUIRED_SCOPES),
        }
        
        # Add code challenge for native apps (PKCE flow)
        if LINKEDIN_APP_TYPE.lower() == "native" and code_challenge:
            auth_params.update({
                "code_challenge": code_challenge,
                "code_challenge_method": "S256"
            })

        logger.info(f"Authorization parameters: {json.dumps(auth_params, indent=2)}")

        auth_url = f"{ENDPOINTS['auth']}?{urlencode(auth_params)}"
        logger.debug(f"Generated LinkedIn auth URL: {auth_url}")

        return {
            "url": auth_url,
            "state": state
        }
    except Exception as e:
        logger.error(f"Error initializing LinkedIn auth: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize LinkedIn authentication"
        )

@router.post("/auth/callback")
async def linkedin_callback(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Handle LinkedIn OAuth callback"""
    try:
        # Process and validate the request data
        data = await request.json()
        code = data.get("code")
        state = data.get("state")

        if not code or not state:
            logger.error("Missing code or state parameter in callback")
            raise HTTPException(
                status_code=400, detail="Missing required parameters (code or state)")

        logger.info(
            f"Received callback with code: {code[:10] if code else None}... (length: {len(code) if code else 0}) and state: {state}")
        logger.info(
            f"Current user ID: {current_user.get('uid') or current_user.get('id')}")

        # Verify state from database and get code_verifier
        stored_state_query = """
        SELECT 
            state, 
            platform, 
            user_id, 
            code_verifier,
            expires_at AT TIME ZONE 'UTC' as expires_at,
            created_at AT TIME ZONE 'UTC' as created_at
        FROM mo_oauth_states 
        WHERE state = :state 
        AND platform = 'linkedin'
        AND expires_at > CURRENT_TIMESTAMP
        """

        stored_state = await db.fetch_one(stored_state_query, {"state": state})

        logger.info(f"Found state: {stored_state is not None}")

        # Additional logging for debugging
        if stored_state:
            current_time = datetime.now(timezone.utc)
            logger.info(
                f"State expiration time: {stored_state['expires_at']}, Current time: {current_time}")
            logger.info(
                f"State created for user: {stored_state['user_id']}, Current user: {current_user.get('uid') or current_user.get('id')}")
        else:
            # Try to find why the state is invalid
            all_states = await db.fetch_all(
                """SELECT state, platform, expires_at AT TIME ZONE 'UTC' as expires_at, created_at AT TIME ZONE 'UTC' as created_at 
                   FROM mo_oauth_states WHERE state = :state""",
                {"state": state}
            )
            if all_states:
                for s in all_states:
                    logger.error(
                        f"Found state but it may be expired or for wrong platform: {dict(s)}")
            else:
                logger.error(f"No state record found with state={state}")

        if not stored_state:
            raise HTTPException(
                status_code=400, detail="Invalid or expired state parameter")

        # Verify the user matches
        user_id = current_user.get('uid') or current_user.get('id')
        if stored_state["user_id"] != user_id:
            logger.error(
                f"User mismatch: {stored_state['user_id']} != {user_id}")
            raise HTTPException(
                status_code=400, detail="User mismatch in state verification")

        # Get code_verifier from stored state
        code_verifier = stored_state["code_verifier"]

        # Clean up credentials to remove whitespace
        clean_client_id = CLIENT_ID.strip() if CLIENT_ID else ""
        clean_client_secret = CLIENT_SECRET.strip() if CLIENT_SECRET else ""

        # Add detailed logging for troubleshooting
        logger.info(f"Token exchange parameters:")
        logger.info(f"- Client ID: {clean_client_id[:5]}... (length: {len(clean_client_id)})")
        logger.info(f"- Client Secret length: {len(clean_client_secret)}")
        logger.info(f"- Redirect URI: {REDIRECT_URI}")
        logger.info(f"- Code length: {len(code)}")
        logger.info(f"- Code verifier length: {len(code_verifier) if code_verifier else 0}")
        logger.info(f"- App type: {LINKEDIN_APP_TYPE}")
        
        # Choose the appropriate token request based on app type
        token_response = None
        
        if LINKEDIN_APP_TYPE.lower() == "web":
            # For web app - use client_id and client_secret in body (no PKCE)
            logger.info("Using web app OAuth flow with client credentials in body")
            token_request_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": clean_client_id,
                "client_secret": clean_client_secret,
            }
            
            # Debug data for logging (hide secret)
            debug_data = token_request_data.copy()
            debug_data["client_secret"] = "***REDACTED***"
            logger.info(f"Token request data: {json.dumps(debug_data, indent=2)}")
            
            # Make the request
            token_response = requests.post(
                ENDPOINTS["token"],
                data=urlencode(token_request_data),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                },
                timeout=10
            )
            
        else:  # Native app
            # For native app - use PKCE flow without client_secret
            logger.info("Using native app OAuth flow with PKCE")
            
            if not code_verifier:
                logger.error("Missing code_verifier for PKCE flow")
                raise HTTPException(
                    status_code=400, 
                    detail="Invalid OAuth state: missing code_verifier for PKCE flow"
                )
                
            token_request_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": clean_client_id,
                "code_verifier": code_verifier
            }
            
            logger.info(f"Token request data: {json.dumps(token_request_data, indent=2)}")
            
            # Make the request
            token_response = requests.post(
                ENDPOINTS["token"],
                data=urlencode(token_request_data),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                },
                timeout=10
            )
        
        # If primary flow fails, try fallback options
        if not token_response or not token_response.ok:
            logger.warning(f"Primary authentication flow failed: {token_response.status_code if token_response else 'No response'}")
            logger.warning(f"Response content: {token_response.text if token_response else 'None'}")
            
            # Fallback strategies
            fallback_strategies = []
            
            if LINKEDIN_APP_TYPE.lower() == "web":
                # For web app fallbacks:
                # 1. Try with Basic Auth header
                fallback_strategies.append({
                    "name": "Web app with Basic Auth",
                    "data": {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": REDIRECT_URI,
                    },
                    "auth": requests.auth.HTTPBasicAuth(clean_client_id, clean_client_secret)
                })
                
                # 2. Try without PKCE 
                fallback_strategies.append({
                    "name": "Web app without PKCE (alt format)",
                    "data": {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": REDIRECT_URI,
                        "client_id": clean_client_id,
                        "client_secret": clean_client_secret,
                    },
                    "auth": None
                })
            else:
                # For native app fallbacks:
                # 1. Try with client_secret (not recommended by LinkedIn but might work)
                fallback_strategies.append({
                    "name": "Native app with client secret (non-standard)",
                    "data": {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": REDIRECT_URI,
                        "client_id": clean_client_id,
                        "client_secret": clean_client_secret,
                        "code_verifier": code_verifier
                    },
                    "auth": None
                })
                
                # 2. Try without code_verifier
                fallback_strategies.append({
                    "name": "Native app without code_verifier (non-standard)",
                    "data": {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": REDIRECT_URI,
                        "client_id": clean_client_id,
                    },
                    "auth": None
                })
            
            # Try each fallback strategy
            for strategy in fallback_strategies:
                logger.info(f"Trying fallback: {strategy['name']}")
                
                # Debug log without exposing secrets
                debug_data = strategy['data'].copy()
                if "client_secret" in debug_data:
                    debug_data["client_secret"] = "***REDACTED***"
                logger.info(f"Fallback request data: {json.dumps(debug_data, indent=2)}")
                
                try:
                    fallback_response = requests.post(
                        ENDPOINTS["token"],
                        data=urlencode(strategy['data']),
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Accept": "application/json"
                        },
                        auth=strategy['auth'],
                        timeout=10
                    )
                    
                    logger.info(f"Fallback {strategy['name']} response: {fallback_response.status_code}")
                    logger.info(f"Response content: {fallback_response.text[:200]}")
                    
                    if fallback_response.ok:
                        token_response = fallback_response
                        logger.info(f"Fallback {strategy['name']} succeeded!")
                        break
                except Exception as e:
                    logger.error(f"Error in fallback {strategy['name']}: {str(e)}")
        
        # Final result handling
        if not token_response or not token_response.ok:
            try:
                error_data = token_response.json() if token_response and token_response.text else {"error": "Unknown error"}
                error_msg = error_data.get('error_description', error_data.get('error', 'Unknown error'))
            except:
                error_msg = token_response.text if token_response else "No response from LinkedIn"

            logger.error(f"Token exchange error: {error_msg}")
            
            # Add some LinkedIn-specific error interpretation
            if token_response and "invalid_client" in token_response.text:
                logger.error("LinkedIn 'invalid_client' error typically means:")
                logger.error("1. Client ID or client secret is incorrect")
                logger.error("2. Client ID might not be recognized by LinkedIn")
                logger.error("3. Application might be disabled or restricted")
                logger.error("4. App type setting might be incorrect (web vs native)")
                logger.error("Check your LinkedIn Developer portal settings")
            
            status_code = token_response.status_code if token_response else 500
            raise HTTPException(
                status_code=status_code,
                detail=f"LinkedIn API error: {error_msg}"
            )

        token_data = token_response.json()
        
        # Now it's safe to delete the state since authentication succeeded
        await db.execute(
            "DELETE FROM mo_oauth_states WHERE state = :state",
            {"state": state}
        )
        
        headers = {"Authorization": f"Bearer {token_data['access_token']}"}

        # Get user profile
        profile_response = requests.get(ENDPOINTS["profile"], headers=headers)
        if not profile_response.ok:
            logger.error(f"Failed to get profile data: {profile_response.text}")
            raise HTTPException(
                status_code=401,
                detail=f"LinkedIn API error: Failed to get profile data"
            )
            
        profile_data = profile_response.json()
        
        # Check if profile data has the required fields
        if not profile_data.get("id"):
            logger.error("Profile data doesn't contain user ID")
            logger.error(f"Profile data: {json.dumps(profile_data, indent=2)}")
            raise HTTPException(
                status_code=400,
                detail="Invalid profile data received from LinkedIn"
            )

        # Get email
        email_response = requests.get(ENDPOINTS["email"], headers=headers)
        email_data = email_response.json() if email_response.ok else {"elements": []}

        # Get organization data
        org_response = requests.get(
            ENDPOINTS["organizations"], headers=headers)
        org_data = org_response.json() if org_response.ok else {"elements": []}
        logger.info(f"Organization Data: {json.dumps(org_data, indent=2)}")

        # Get detailed organization info
        org_details = []
        if org_response.ok and "elements" in org_data:
            for org in org_data.get("elements", []):
                if "organizationalTarget" not in org:
                    continue
                    
                org_id = org["organizationalTarget"].split(
                    ":")[-1]  # Extract ID from URN
                org_detail_response = requests.get(
                    ENDPOINTS["organization_details"].format(id=org_id),
                    headers=headers
                )
                if org_detail_response.ok:
                    org_details.append(org_detail_response.json())

        logger.info(
            f"Organization Details: {json.dumps(org_details, indent=2)}")

        # Add these logging statements:
        logger.info("LinkedIn Authorization Response Data:")
        logger.info(f"Token Data: {json.dumps(token_data, indent=2)}")
        logger.info(f"Profile Data: {json.dumps(profile_data, indent=2)}")
        logger.info(f"Email Data: {json.dumps(email_data, indent=2)}")

        # Safely extract email (with error handling)
        try:
            email = email_data.get("elements", [{}])[0].get(
                "handle~", {}).get("emailAddress")
        except (IndexError, KeyError):
            email = None

        logger.debug(f"Creating social account with data: {profile_data}")

        # Create the account
        try:
            # Set the correct user ID field
            user_id = current_user.get('uid') or current_user.get('id')
            if not user_id:
                logger.error("User ID missing from current_user object")
                raise HTTPException(status_code=400, detail="User ID missing")

            # Safely extract first name and last name with fallbacks
            first_name = "Unknown"
            last_name = "User"
            
            try:
                first_name = profile_data.get("firstName", {}).get("localized", {}).get("en_US", "Unknown")
                last_name = profile_data.get("lastName", {}).get("localized", {}).get("en_US", "User")
            except (KeyError, AttributeError, TypeError) as e:
                logger.warning(f"Error extracting name data: {str(e)}")
                # If detailed localized name info isn't available, try simpler fallbacks
                if isinstance(profile_data.get("firstName"), str):
                    first_name = profile_data.get("firstName")
                if isinstance(profile_data.get("lastName"), str):
                    last_name = profile_data.get("lastName")
            
            username = f"{first_name} {last_name}"
            
            # Extract LinkedIn ID safely
            linkedin_id = profile_data.get("id")
            if not linkedin_id:
                raise ValueError("LinkedIn profile ID is missing")

            # Current time and expiration time for the token
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=token_data.get("expires_in", 3600))

            social_account = SocialAccount(
                user_id=user_id,
                platform_account_id=linkedin_id,
                username=username,
                profile_picture_url=None,
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                expires_at=expires_at,
                metadata={
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": email,
                    "organizations": org_data.get("elements", []),
                    "organization_details": org_details
                }
            )
            logger.debug(
                f"Created social account object: {social_account.dict()}")
        except Exception as e:
            logger.error(f"Error creating social account: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500, detail=f"Failed to create social account: {str(e)}")

        # Try to get profile picture
        try:
            picture_response = requests.get(
                f"{API_BASE}/me?projection=(id,profilePicture(displayImage~:playableStreams))",
                headers=headers
            )
            if picture_response.ok:
                picture_data = picture_response.json()
                picture_elements = (
                    picture_data.get("profilePicture", {})
                    .get("displayImage~", {})
                    .get("elements", [])
                )
                if picture_elements:
                    picture_elements.sort(
                        key=lambda x: x.get("data", {}).get("width", 0),
                        reverse=True
                    )
                    social_account.profile_picture_url = picture_elements[
                        0]["identifiers"][0]["identifier"]
        except Exception as e:
            logger.warning(f"Error getting profile picture: {str(e)}")
            # Continue without profile picture if there's an error

        # Upsert account in database
        account_data = social_account.dict(exclude={'id'})

        # Convert metadata to JSON string just before database operation
        if account_data.get('metadata'):
            account_data['metadata'] = json.dumps(account_data['metadata'])

        # Log the exact type of expires_at to help debug
        logger.info(f"Type of expires_at: {type(account_data.get('expires_at'))}")
        logger.info(f"Value of expires_at: {account_data.get('expires_at')}")

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
            media_type,
            media_count,
            created_at,
            updated_at
        ) VALUES (
            :user_id,
            :platform,
            :platform_account_id,
            :username,
            :profile_picture_url,
            :access_token,
            :refresh_token,
            :expires_at,
            :metadata,
            :media_type,
            :media_count,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (user_id, platform, platform_account_id) 
        DO UPDATE SET
            username = EXCLUDED.username,
            profile_picture_url = EXCLUDED.profile_picture_url,
            access_token = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            expires_at = EXCLUDED.expires_at,
            metadata = EXCLUDED.metadata,
            media_type = EXCLUDED.media_type,
            media_count = EXCLUDED.media_count,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, user_id, platform, platform_account_id, username, profile_picture_url,
                  access_token, refresh_token, expires_at, metadata, media_type, media_count
        """

        created_account = await db.fetch_one(query=query, values=account_data)

        if not created_account:
            raise HTTPException(
                status_code=500,
                detail="Failed to create or update social account"
            )

        # Update the social_account with the returned data
        social_account.id = created_account["id"]

        # Make sure to serialize datetime objects in the response
        response_dict = social_account.dict()
        for key, value in response_dict.items():
            if isinstance(value, datetime):
                response_dict[key] = value.isoformat()

        return response_dict

    except Exception as e:
        logger.error(f"LinkedIn callback error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to complete LinkedIn authentication: {str(e)}"
        )


@router.post("/share/{account_id}")
async def share_post(
    post: SharePost,
    account_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Share a post on LinkedIn"""
    try:
        # Get user's LinkedIn account
        query = """
        SELECT access_token, platform_account_id, metadata
        FROM mo_social_accounts 
        WHERE id = :account_id AND user_id = :user_id AND platform = 'linkedin'
        """
        values = {
            "account_id": account_id,
            "user_id": current_user["id"]
        }

        account = await db.fetch_one(query=query, values=values)

        if not account:
            raise HTTPException(
                status_code=404, detail="LinkedIn account not found")

        headers = {
            "Authorization": f"Bearer {account['access_token']}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }

        # Base post data
        post_data = {
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": post.text
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": post.visibility
            }
        }

        # Set author based on whether it's an organization post
        if post.organization_id:
            # Verify user has permission to post as this organization
            metadata = json.loads(
                account['metadata']) if account['metadata'] else {}
            org_roles = metadata.get('organizations', [])
            has_permission = False
            for org_role in org_roles:
                if (org_role['organizationalTarget'] == f"urn:li:organization:{post.organization_id}"
                        and org_role['role'] in ['ADMINISTRATOR', 'OWNER']):
                    has_permission = True
                    break

            if not has_permission:
                raise HTTPException(
                    status_code=403,
                    detail="You don't have permission to post as this organization"
                )

            post_data["author"] = f"urn:li:organization:{post.organization_id}"
        else:
            post_data["author"] = f"urn:li:person:{account['platform_account_id']}"

        if post.article_url:
            post_data["specificContent"]["com.linkedin.ugc.ShareContent"].update({
                "shareMediaCategory": "ARTICLE",
                "media": [{
                    "status": "READY",
                    "originalUrl": post.article_url
                }]
            })

        response = requests.post(
            ENDPOINTS["share"],
            headers=headers,
            json=post_data
        )

        if not response.ok:
            error_text = response.text
            try:
                error_json = response.json()
                error_text = json.dumps(error_json, indent=2)
            except:
                pass
            logger.error(f"LinkedIn API error response: {error_text}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"LinkedIn API error: {error_text}"
            )

        post_id = response.headers.get("x-restli-id")
        logger.debug(f"Successfully created LinkedIn post with ID: {post_id}")

        return {
            "status": "success",
            "post_id": post_id,
            "message": "Post shared successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LinkedIn API error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to share post")


@router.post("/article/metadata")
async def get_article_metadata(article: ArticleMetadata):
    """Get metadata for an article URL"""
    try:
        # Use requests to fetch the article page
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(article.url, headers=headers, timeout=5)
        response.raise_for_status()

        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract metadata
        metadata = {
            "url": article.url,
            "title": None,
            "description": None,
            "thumbnailUrl": None
        }

        # Try Open Graph tags first
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        og_image = soup.find("meta", property="og:image")

        # Fallback to standard meta tags
        title_tag = soup.find("title")
        desc_tag = soup.find("meta", attrs={"name": "description"})

        # Set values with fallbacks
        metadata["title"] = (
            og_title.get("content") if og_title else
            title_tag.string if title_tag else
            None
        )
        metadata["description"] = (
            og_desc.get("content") if og_desc else
            desc_tag.get("content") if desc_tag else
            None
        )
        metadata["thumbnailUrl"] = og_image.get(
            "content") if og_image else None

        return JSONResponse(content=metadata)

    except requests.RequestException as e:
        logger.error(f"Failed to fetch article metadata: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch article metadata: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error processing article metadata: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process article metadata"
        )


@router.post("/refresh")
async def refresh_token_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Refresh LinkedIn access token"""
    try:
        data = await request.json()
        refresh_token = data.get("refresh_token")

        if not refresh_token:
            raise HTTPException(
                status_code=400, detail="Refresh token is required")

        # Get the user ID
        user_id = current_user.get('uid') or current_user.get('id')
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is missing")

        # Get new tokens
        new_tokens = await get_new_tokens(refresh_token)

        # Calculate expiration datetime
        expires_at = datetime.utcnow(
        ) + timedelta(seconds=new_tokens["expires_in"])

        # Update DB
        try:
            await db.execute("""
                UPDATE mo_social_accounts 
                SET 
                    access_token = :access_token,
                    refresh_token = :refresh_token,
                    expires_at = :expires_at,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = :user_id AND platform = 'linkedin'
            """, {
                "access_token": new_tokens["access_token"],
                "refresh_token": new_tokens["refresh_token"],
                "expires_at": expires_at,
                "user_id": user_id
            })

            # Add expiration info to the response
            new_tokens["expires_at"] = expires_at.isoformat()
            return new_tokens

        except Exception as db_error:
            logger.error(
                f"Database error during token refresh: {str(db_error)}")
            raise HTTPException(
                status_code=500, detail=f"Failed to update token in database: {str(db_error)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Failed to refresh token: {str(e)}")


async def get_new_tokens(refresh_token: str) -> dict:
    """Get new access token using refresh token from LinkedIn"""
    try:
        if not refresh_token:
            raise ValueError("Refresh token is required")

        if not CLIENT_ID or not CLIENT_SECRET:
            raise ValueError("LinkedIn client ID and secret are required")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }

        logger.debug(f"Refreshing token with data: {data}")

        # Ensure proper encoding and headers
        encoded_data = urlencode(data)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }

        response = requests.post(
            ENDPOINTS["token"],
            data=encoded_data,
            headers=headers
        )

        if not response.ok:
            try:
                error_data = response.json()
                error_msg = error_data.get(
                    'error_description', error_data.get('error', 'Unknown error'))
            except Exception:
                error_msg = f"Error response: {response.status_code} - {response.text}"

            logger.error(f"Token refresh error: {error_msg}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"LinkedIn API error: {error_msg}"
            )

        token_data = response.json()
        logger.debug(f"Got new token data: {token_data}")

        return {
            "access_token": token_data["access_token"],
            # LinkedIn might not always return new refresh token
            # Use old token if no new one
            "refresh_token": token_data.get("refresh_token", refresh_token),
            # Default to 1 hour if not provided
            "expires_in": token_data.get("expires_in", 3600)
        }

    except requests.RequestException as e:
        logger.error(f"Failed to refresh LinkedIn token: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to refresh token: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Failed to refresh token"
        )


@router.post("/disconnect/{account_id}")
async def disconnect_account(
    account_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Disconnect a LinkedIn account"""
    try:
        logger.debug(
            f"Disconnecting LinkedIn account {account_id} for user {current_user['id']}")

        # First, get the account to verify ownership and get access token
        account = await db.fetch_one(
            """
            SELECT access_token, platform_account_id 
            FROM mo_social_accounts 
            WHERE id = :account_id 
            AND user_id = :user_id 
            AND platform = 'linkedin'
            """,
            {
                "account_id": account_id,
                "user_id": current_user["id"]
            }
        )

        if not account:
            raise HTTPException(
                status_code=404,
                detail="LinkedIn account not found or you don't have permission to disconnect it"
            )

        # Optionally revoke access token with LinkedIn
        try:
            headers = {"Authorization": f"Bearer {account['access_token']}"}
            revoke_response = requests.get(
                "https://www.linkedin.com/oauth/v2/revoke",
                headers=headers
            )
            if not revoke_response.ok:
                logger.warning(f"Failed to revoke LinkedIn token:")
        except Exception as e:
            logger.warning(f"Error revoking LinkedIn token: {str(e)}")

        # Delete the account from our database
        await db.execute(
            """
            DELETE FROM mo_social_accounts 
            WHERE id = :account_id 
            AND user_id = :user_id 
            AND platform = 'linkedin'
            """,
            {
                "account_id": account_id,
                "user_id": current_user["id"]
            }
        )

        return {"status": "success", "message": "Account disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disconnecting LinkedIn account: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to disconnect LinkedIn account: {str(e)}"
        )


@router.get("/user")
async def get_user_accounts(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get user's connected LinkedIn accounts"""
    try:
        # Get all LinkedIn accounts for the user
        query = """
        SELECT 
            id, user_id, platform, platform_account_id, username, 
            profile_picture_url, access_token, refresh_token, 
            expires_at, metadata, media_type, media_count
        FROM mo_social_accounts 
        WHERE user_id = :user_id AND platform = 'linkedin'
        """
        accounts = await db.fetch_all(query, {"user_id": current_user["id"]})

        # Convert accounts to list of SocialAccount models
        account_list = []
        for acc in accounts:
            # Parse metadata if it exists
            metadata = json.loads(acc["metadata"]) if acc["metadata"] else None

            account = SocialAccount(
                id=acc["id"],
                user_id=acc["user_id"],
                platform=acc["platform"],
                platform_account_id=acc["platform_account_id"],
                username=acc["username"],
                profile_picture_url=acc["profile_picture_url"],
                access_token=acc["access_token"],
                refresh_token=acc["refresh_token"],
                expires_at=acc["expires_at"],
                metadata=metadata,
                media_type=acc["media_type"],
                media_count=acc["media_count"]
            )
            account_list.append(account)

        return {"accounts": [acc.dict() for acc in account_list]}

    except Exception as e:
        logger.error(f"Error fetching LinkedIn accounts: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch LinkedIn accounts: {str(e)}"
        )

# Add debugging endpoint to help troubleshoot LinkedIn OAuth issues


@router.get("/debug-config")
async def debug_linkedin_config():
    """Debug LinkedIn OAuth configuration"""
    try:
        # Verify environment variables are loaded correctly
        config = {
            "client_id": CLIENT_ID[:5] + "..." if CLIENT_ID else None,
            "client_id_length": len(CLIENT_ID) if CLIENT_ID else 0,
            "client_secret_set": bool(CLIENT_SECRET),
            "client_secret_length": len(CLIENT_SECRET) if CLIENT_SECRET else 0,
            "redirect_uri": REDIRECT_URI,
            "environment": ENVIRONMENT,
            "app_type": LINKEDIN_APP_TYPE,
            "token_endpoint": ENDPOINTS["token"],
            "auth_endpoint": ENDPOINTS["auth"],
        }

        # Check if credentials start/end with whitespace (common error)
        if CLIENT_ID and (CLIENT_ID.strip() != CLIENT_ID):
            config["warning"] = "CLIENT_ID contains leading or trailing whitespace"
        if CLIENT_SECRET and (CLIENT_SECRET.strip() != CLIENT_SECRET):
            config["warning"] = "CLIENT_SECRET contains leading or trailing whitespace"

        # Test connection to LinkedIn API
        try:
            # Simple test with invalid token to see if we can reach the API
            response = requests.get(
                "https://api.linkedin.com/v2/me",
                headers={
                    "Authorization": "Bearer invalid_token_just_testing_connectivity"},
                timeout=5
            )
            config["api_connectivity"] = {
                "status_code": response.status_code,
                "reason": response.reason
            }

            # Test a dummy token request with valid credentials (but invalid code)
            test_data = {
                "grant_type": "authorization_code",
                "code": "dummy_code",
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            }

            # Redact secret for logging
            test_data_log = test_data.copy()
            test_data_log["client_secret"] = "***REDACTED***"
            logger.info(
                f"Test token request data: {json.dumps(test_data_log)}")

            # Encode data properly
            encoded_data = urlencode(test_data)
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }

            token_response = requests.post(
                ENDPOINTS["token"],
                data=encoded_data,
                headers=headers,
                timeout=5
            )

            config["token_endpoint_test"] = {
                "status_code": token_response.status_code,
                "reason": token_response.reason,
                "body": token_response.text[:200] + "..." if len(token_response.text) > 200 else token_response.text
            }

        except Exception as e:
            config["api_connectivity"] = {"error": str(e)}

        # Check redirect URI format
        if REDIRECT_URI:
            if not REDIRECT_URI.startswith("https://"):
                config["redirect_warning"] = "Redirect URI should use HTTPS"

            if " " in REDIRECT_URI:
                config["redirect_warning"] = "Redirect URI contains spaces"

        return config
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}


@router.get("/debug-credentials")
async def debug_linkedin_credentials():
    """Comprehensive debug tool for LinkedIn OAuth issues"""
    try:
        # Test without exposing sensitive data
        clean_client_id = CLIENT_ID.strip() if CLIENT_ID else ""
        clean_client_secret = CLIENT_SECRET.strip() if CLIENT_SECRET else ""
        
        debug_info = {
            "credentials": {
                "client_id_first_chars": clean_client_id[:5] + "..." if clean_client_id else None,
                "client_id_length": len(clean_client_id),
                "client_secret_first_chars": clean_client_secret[:3] + "..." if clean_client_secret else None,
                "client_secret_length": len(clean_client_secret),
                "contains_whitespace": {
                    "client_id": clean_client_id != CLIENT_ID if CLIENT_ID else False,
                    "client_secret": clean_client_secret != CLIENT_SECRET if CLIENT_SECRET else False,
                }
            },
            "app_config": {
                "app_type": LINKEDIN_APP_TYPE,
                "recommended_flow": "Standard OAuth" if LINKEDIN_APP_TYPE.lower() == "web" else "PKCE flow"
            },
            "redirect_uri": {
                "value": REDIRECT_URI,
                "starts_with_https": REDIRECT_URI.startswith("https://") if REDIRECT_URI else False,
                "contains_spaces": " " in REDIRECT_URI if REDIRECT_URI else False,
                "possible_issues": []
            },
            "environment": {
                "current": ENVIRONMENT,
                "valid_environments": list(REDIRECT_URIS.keys())
            },
            "test_connections": {}
        }
        
        # Check for common redirect URI issues
        if REDIRECT_URI:
            if not REDIRECT_URI.startswith("https://"):
                debug_info["redirect_uri"]["possible_issues"].append(
                    "LinkedIn OAuth usually requires HTTPS for redirect URIs"
                )
            if " " in REDIRECT_URI:
                debug_info["redirect_uri"]["possible_issues"].append(
                    "Redirect URI contains spaces, which will cause encoding issues"
                )
            if REDIRECT_URI.endswith("/"):
                debug_info["redirect_uri"]["possible_issues"].append(
                    "Trailing slash in redirect URI - must match exactly with LinkedIn settings"
                )

        # Test connectivity to LinkedIn API endpoints
        try:
            # Test authorization endpoint
            auth_response = requests.head(
                ENDPOINTS["auth"],
                timeout=5,
                allow_redirects=False
            )
            debug_info["test_connections"]["auth_endpoint"] = {
                "url": ENDPOINTS["auth"],
                "status_code": auth_response.status_code,
                "response_time_ms": auth_response.elapsed.total_seconds() * 1000
            }
            
            # Test token endpoint
            token_response = requests.head(
                ENDPOINTS["token"],
                timeout=5,
                allow_redirects=False
            )
            debug_info["test_connections"]["token_endpoint"] = {
                "url": ENDPOINTS["token"],
                "status_code": token_response.status_code,
                "response_time_ms": token_response.elapsed.total_seconds() * 1000
            }
            
            # Test invalid client credentials request
            # This should fail with 401, but will show if we can reach the endpoint
            test_body = {
                "grant_type": "client_credentials",
                "client_id": "test_client_id",
                "client_secret": "test_client_secret"
            }
            test_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }
            test_response = requests.post(
                ENDPOINTS["token"],
                data=urlencode(test_body),
                headers=test_headers,
                timeout=5
            )
            debug_info["test_connections"]["invalid_credentials_test"] = {
                "status_code": test_response.status_code,
                "response_body": test_response.text[:200] + "..." if len(test_response.text) > 200 else test_response.text,
                "expected_error": "invalid_client",
                "contains_expected_error": "invalid_client" in test_response.text
            }
            
            # Now try with actual client id but fake secret
            # This helps verify if our client ID is recognized by LinkedIn
            test_body = {
                "grant_type": "client_credentials",
                "client_id": clean_client_id,
                "client_secret": "fake_secret_for_testing"
            }
            test_response = requests.post(
                ENDPOINTS["token"],
                data=urlencode(test_body),
                headers=test_headers,
                timeout=5
            )
            debug_info["test_connections"]["real_client_id_test"] = {
                "status_code": test_response.status_code,
                "response_body": test_response.text[:200] + "..." if len(test_response.text) > 200 else test_response.text,
                "contains_invalid_client": "invalid_client" in test_response.text
            }
            
        except Exception as e:
            debug_info["test_connections"]["error"] = str(e)
        
        # Add recommendations based on debug info
        debug_info["recommendations"] = []
        
        # App type recommendations
        if LINKEDIN_APP_TYPE.lower() not in ["web", "native"]:
            debug_info["recommendations"].append(
                "LINKEDIN_APP_TYPE should be set to either 'web' or 'native' based on your LinkedIn app configuration."
            )
        
        # Client ID/Secret recommendations
        if debug_info["credentials"]["client_id_length"] == 0:
            debug_info["recommendations"].append(
                "CLIENT_ID is missing. Check your environment variables."
            )
        elif debug_info["credentials"]["client_id_length"] < 10:
            debug_info["recommendations"].append(
                "CLIENT_ID seems too short. Verify it's correct in the LinkedIn Developer portal."
            )
            
        if debug_info["credentials"]["client_secret_length"] == 0:
            debug_info["recommendations"].append(
                "CLIENT_SECRET is missing. Check your environment variables."
            )
        
        if debug_info["credentials"]["contains_whitespace"]["client_id"]:
            debug_info["recommendations"].append(
                "CLIENT_ID contains whitespace. Remove any leading/trailing spaces."
            )
            
        if debug_info["credentials"]["contains_whitespace"]["client_secret"]:
            debug_info["recommendations"].append(
                "CLIENT_SECRET contains whitespace. Remove any leading/trailing spaces."
            )
        
        # Add test result recommendations
        if "real_client_id_test" in debug_info["test_connections"]:
            test_result = debug_info["test_connections"]["real_client_id_test"]
            if not test_result["contains_invalid_client"]:
                debug_info["recommendations"].append(
                    "LinkedIn doesn't recognize your client ID. Double-check it in the LinkedIn Developer portal."
                )
        
        return debug_info
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}
