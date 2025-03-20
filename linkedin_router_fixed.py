"""
This is a fixed version of your LinkedIn router. Replace linkedin_router.py with this file.
It includes all the OAuth fixes and a debug endpoint to help diagnose issues.
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

# Define redirect URIs for different environments
REDIRECT_URIS = {
    "production": "https://www.multivio.com/linkedin/callback",
    "development": "https://dev.multivio.com/linkedin/callback",
    "local": "https://dev.multivio.com/linkedin/callback"
}

# Get the appropriate redirect URI based on environment
# Note: Make sure this exact URI is registered with LinkedIn
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", REDIRECT_URIS.get(
    ENVIRONMENT, REDIRECT_URIS["development"]))

logger.info(f"LinkedIn OAuth Configuration:")
logger.info(f"Client ID: {CLIENT_ID[:5]}... (truncated)")
logger.info(f"Redirect URI: {REDIRECT_URI}")
logger.info(f"Environment: {ENVIRONMENT}")

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
        "r_organization_social", # Read org posts
        "w_organization_social", # Create org pw_organization_socialosts
    ],
    "organization": [
        "r_organization_admin",  # Read org pages and analytics
        "rw_organization_admin", # Manage org pages
    ],
    "advertising": [
        "r_ads",               # Read ad accounts
        "rw_ads",              # Manage ad accounts
        "r_ads_reporting",     # Read ad reporting
    ],
    "connections": [
        "r_1st_connections_size", # Number of connections
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
    """Initialize LinkedIn OAuth flow"""
    try:
        # Get the user ID - depending on how it's set in the current_user dict
        user_id = current_user.get('uid') or current_user.get('id')
        logger.debug(f"Initializing LinkedIn auth for user: {user_id}")
        
        # Generate state for CSRF protection
        state = generate_state()
        
        # Generate code verifier and challenge for PKCE
        # Length should be between 43 and 128 characters - use 64 for good security
        code_verifier = secrets.token_urlsafe(48)  # This gives about 64 chars
        
        # Generate code challenge with S256 method as recommended by OAuth2 standards
        code_challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge_bytes).decode().rstrip("=")
        
        # Store state and code_verifier in database
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=10)
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
            {
                "state": state,
                "platform": "linkedin",
                "user_id": user_id,
                "created_at": now,
                "expires_at": expires_at,
                "code_verifier": code_verifier
            }
        )

        # Construct auth URL with PKCE - ensure we use exactly the registered redirect URI
        auth_params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "scope": " ".join(REQUIRED_SCOPES),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        
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
            raise HTTPException(status_code=400, detail="Missing required parameters (code or state)")
            
        logger.info(f"Received callback with code: {code[:10] if code else None}... (length: {len(code) if code else 0}) and state: {state}")
        logger.info(f"Current user ID: {current_user.get('uid') or current_user.get('id')}")
        
        # Safely convert current_user to JSON-serializable dict
        safe_user_dict = {}
        for k, v in current_user.items():
            if k != 'access_token':
                if isinstance(v, datetime):
                    safe_user_dict[k] = v.isoformat()
                else:
                    safe_user_dict[k] = v
        logger.info(f"Current user details: {json.dumps(safe_user_dict, indent=2)}")
        
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
            logger.info(f"State expiration time: {stored_state['expires_at']}, Current time: {current_time}")
            logger.info(f"State created for user: {stored_state['user_id']}, Current user: {current_user.get('uid') or current_user.get('id')}")
        else:
            # Try to find why the state is invalid
            all_states = await db.fetch_all(
                """SELECT state, platform, expires_at AT TIME ZONE 'UTC' as expires_at, created_at AT TIME ZONE 'UTC' as created_at 
                   FROM mo_oauth_states WHERE state = :state""",
                {"state": state}
            )
            if all_states:
                for s in all_states:
                    logger.error(f"Found state but it may be expired or for wrong platform: {dict(s)}")
            else:
                logger.error(f"No state record found with state={state}")
        
        if not stored_state:
            raise HTTPException(status_code=400, detail="Invalid or expired state parameter")
            
        # Verify the user matches
        user_id = current_user.get('uid') or current_user.get('id')
        if stored_state["user_id"] != user_id:
            logger.error(f"User mismatch: {stored_state['user_id']} != {user_id}")
            raise HTTPException(status_code=400, detail="User mismatch in state verification")
            
        # Get code_verifier from stored state
        code_verifier = stored_state["code_verifier"]
        
        if not code_verifier:
            logger.error(f"No code_verifier found for state={state}")
            raise HTTPException(status_code=400, detail="Invalid OAuth state: missing code_verifier")
            
        # Delete the state after use to prevent replay attacks
        await db.execute(
            "DELETE FROM mo_oauth_states WHERE state = :state",
            {"state": state}
        )
        
        # Exchange code for access token using code_verifier for PKCE
        # LinkedIn's OAuth implementation is inconsistent - try standard form with exact data format
        
        # Use x-www-form-urlencoded with properly formatted data
        token_request_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }
        
        # Add code_verifier if it exists
        if code_verifier:
            token_request_data["code_verifier"] = code_verifier
        
        # Detailed logging to help debug
        debug_data = token_request_data.copy()
        if "client_secret" in debug_data:
            debug_data["client_secret"] = "***REDACTED***"
        if "code" in debug_data:
            debug_data["code"] = debug_data["code"][:10] + "..." if debug_data["code"] else None
        if "code_verifier" in debug_data:
            debug_data["code_verifier"] = debug_data["code_verifier"][:5] + "..." if debug_data["code_verifier"] else None
        
        logger.info(f"Token request data: {json.dumps(debug_data, indent=2)}")
        
        # Ensure proper encoding and headers
        encoded_data = urlencode(token_request_data)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        
        # Log the exact URL and headers being used
        logger.info(f"Token endpoint: {ENDPOINTS['token']}")
        logger.info(f"Headers: {headers}")
        
        # Use native requests without any extra modifications
        token_response = requests.post(
            ENDPOINTS["token"],
            data=encoded_data,
            headers=headers
        )
        
        logger.debug(f"Token exchange response status: {token_response.status_code}")
        logger.debug(f"Token exchange response: {token_response.text}")
        
        if not token_response.ok:
            try:
                error_data = token_response.json() if token_response.text else {"error": "Unknown error"}
                error_msg = error_data.get('error_description', error_data.get('error', 'Unknown error'))
            except:
                error_msg = token_response.text or "Unknown error"
                
            logger.error(f"Token exchange error: {error_msg}")
            logger.error(f"Full error response: {token_response.text}")
            raise HTTPException(
                status_code=token_response.status_code,
                detail=f"LinkedIn API error: {error_msg}"
            )
            
        token_data = token_response.json()
        headers = {"Authorization": f"Bearer {token_data['access_token']}"}

        # Get user profile
        profile_response = requests.get(ENDPOINTS["profile"], headers=headers)
        profile_data = profile_response.json()
        
        # Get email
        email_response = requests.get(ENDPOINTS["email"], headers=headers)
        email_data = email_response.json()

        # Get organization data
        org_response = requests.get(ENDPOINTS["organizations"], headers=headers)
        org_data = org_response.json()
        logger.info(f"Organization Data: {json.dumps(org_data, indent=2)}")

        # Get detailed organization info
        org_details = []
        for org in org_data.get("elements", []):
            org_id = org["organizationalTarget"].split(":")[-1]  # Extract ID from URN
            org_detail_response = requests.get(
                ENDPOINTS["organization_details"].format(id=org_id),
                headers=headers
            )
            if org_detail_response.ok:
                org_details.append(org_detail_response.json())
        
        logger.info(f"Organization Details: {json.dumps(org_details, indent=2)}")

        # Add these logging statements:
        logger.info("LinkedIn Authorization Response Data:")
        logger.info(f"Token Data: {json.dumps(token_data, indent=2)}")
        logger.info(f"Profile Data: {json.dumps(profile_data, indent=2)}")
        logger.info(f"Email Data: {json.dumps(email_data, indent=2)}")

        email = email_data.get("elements", [{}])[0].get("handle~", {}).get("emailAddress")

        logger.debug(f"Creating social account with data: {profile_data}")

        # Create the account
        try:
            # Set the correct user ID field
            user_id = current_user.get('uid') or current_user.get('id')
            if not user_id:
                logger.error("User ID missing from current_user object")
                raise HTTPException(status_code=400, detail="User ID missing")
                
            social_account = SocialAccount(
                user_id=user_id,
                platform_account_id=profile_data["id"],
                username=f"{profile_data['firstName']['localized']['en_US']} {profile_data['lastName']['localized']['en_US']}",
                profile_picture_url=None,
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                expires_at=datetime.utcnow() + timedelta(seconds=token_data["expires_in"]),
                metadata={
                    "firstName": profile_data["firstName"]["localized"]["en_US"],
                    "lastName": profile_data["lastName"]["localized"]["en_US"],
                    "email": email,
                    "organizations": org_data.get("elements", []),
                    "organization_details": org_details
                }
            )
            logger.debug(f"Created social account object: {social_account.dict()}")
        except Exception as e:
            logger.error(f"Error creating social account: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create social account: {str(e)}")

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
                    social_account.profile_picture_url = picture_elements[0]["identifiers"][0]["identifier"]
        except:
            pass

        # Upsert account in database
        account_data = social_account.dict(exclude={'id'})
        
        # Convert datetime objects to strings for database operations
        for key, value in account_data.items():
            if isinstance(value, datetime):
                account_data[key] = value.isoformat()
        
        # Convert metadata to JSON string just before database operation
        if account_data.get('metadata'):
            account_data['metadata'] = json.dumps(account_data['metadata'])
            
        logger.debug(f"Account data for database: {account_data}")

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

        # State has already been cleaned up earlier after verification
        # No need to delete again

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
            raise HTTPException(status_code=404, detail="LinkedIn account not found")

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
            metadata = json.loads(account['metadata']) if account['metadata'] else {}
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
            raise HTTPException(status_code=400, detail="Refresh token is required")
            
        # Get the user ID
        user_id = current_user.get('uid') or current_user.get('id')
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is missing")
            
        # Get new tokens
        new_tokens = await get_new_tokens(refresh_token)
        
        # Calculate expiration datetime
        expires_at = datetime.utcnow() + timedelta(seconds=new_tokens["expires_in"])

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
            logger.error(f"Database error during token refresh: {str(db_error)}")
            raise HTTPException(status_code=500, detail=f"Failed to update token in database: {str(db_error)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to refresh token: {str(e)}")


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
                error_msg = error_data.get('error_description', error_data.get('error', 'Unknown error'))
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
            "refresh_token": token_data.get("refresh_token", refresh_token),  # Use old token if no new one
            "expires_in": token_data.get("expires_in", 3600)  # Default to 1 hour if not provided
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
        logger.debug(f"Disconnecting LinkedIn account {account_id} for user {current_user['id']}")
        
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
                headers={"Authorization": "Bearer invalid_token_just_testing_connectivity"},
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
            logger.info(f"Test token request data: {json.dumps(test_data_log)}")
            
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
