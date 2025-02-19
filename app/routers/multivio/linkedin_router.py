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
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from uuid import UUID, uuid4
from databases import Database
from enum import Enum

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
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", REDIRECT_URIS.get(
    ENVIRONMENT, REDIRECT_URIS["development"]))

logger.info(f"Using LinkedIn Redirect URI: {REDIRECT_URI}")

# LinkedIn API endpoints
API_BASE = "https://api.linkedin.com/v2"
AUTH_BASE = "https://www.linkedin.com/oauth/v2"

ENDPOINTS = {
    "auth": "https://www.linkedin.com/oauth/v2/authorization",
    "token": "https://www.linkedin.com/oauth/v2/accessToken",
    "profile": "https://api.linkedin.com/v2/me",
    "email": "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))",
    "share": "https://api.linkedin.com/v2/ugcPosts"
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
        "w_organization_social", # Create org posts
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
        state = generate_state()
        expires_at = datetime.utcnow() + timedelta(hours=1)
        
        # Store state in database
        await db.execute(
            """
            INSERT INTO mo_oauth_states (state, platform, user_id, created_at, expires_at)
            VALUES (:state, :platform, :user_id, :created_at, :expires_at)
            """,
            {
                "state": state,
                "platform": "linkedin",
                "user_id": current_user["id"],
                "created_at": datetime.utcnow(),
                "expires_at": expires_at
            }
        )

        # Construct auth URL
        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "scope": " ".join(REQUIRED_SCOPES)
        }
        
        auth_url = f"{ENDPOINTS['auth']}?{urlencode(params)}"
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

@router.get("/callback")
async def linkedin_callback(
    code: str, 
    state: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Handle LinkedIn OAuth callback"""
    try:
        logger.debug(f"Received callback with code: {code[:10]}... and state: {state}")
        logger.debug(f"Current user: {current_user}")
        
        # Verify state from database
        stored_state = await db.fetch_one(
            """
            SELECT * FROM mo_oauth_states 
            WHERE state = :state AND platform = 'linkedin' AND user_id = :user_id
            AND expires_at > NOW()
            """,
            {"state": state, "user_id": current_user["id"]}
        )
        
        logger.debug(f"Stored state: {stored_state}")
        
        if not stored_state:
            logger.error(f"No stored state found for state={state} and user_id={current_user['id']}")
            raise HTTPException(status_code=400, detail="Invalid or expired state")

        # Exchange code for access token
        token_response = requests.post(
            ENDPOINTS["token"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET
            }
        )
        
        if not token_response.ok:
            error_data = token_response.json()
            error_msg = error_data.get('error_description', error_data.get('error', 'Unknown error'))
            logger.error(f"Token exchange error: {error_msg}")
            raise HTTPException(
                status_code=token_response.status_code,
                detail=f"LinkedIn API error: {error_msg}"
            )
            
        token_data = token_response.json()
        headers = {"Authorization": f"Bearer {token_data['access_token']}"}

        # Get user profile
        profile_response = requests.get(ENDPOINTS["profile"], headers=headers)
        profile_data = profile_response.json()
        logger.debug(f"LinkedIn profile data: {json.dumps(profile_data, indent=2)}")

        # Get email
        email_response = requests.get(ENDPOINTS["email"], headers=headers)
        email_data = email_response.json()
        logger.debug(f"LinkedIn email data: {json.dumps(email_data, indent=2)}")
        email = email_data.get("elements", [{}])[0].get("handle~", {}).get("emailAddress")

        logger.debug(f"Creating social account with data: {profile_data}")

        # Create the account
        social_account = SocialAccount(
            user_id=current_user["id"],
            platform_account_id=profile_data["id"],
            username=f"{profile_data['firstName']['localized']['en_US']} {profile_data['lastName']['localized']['en_US']}",
            profile_picture_url=None,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=datetime.utcnow() + timedelta(seconds=token_data["expires_in"]),
            metadata={
                "firstName": profile_data["firstName"]["localized"]["en_US"],
                "lastName": profile_data["lastName"]["localized"]["en_US"],
                "email": email
            }
        )

        logger.debug(f"Created social account object: {social_account.dict()}")

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

        # Clean up used state
        await db.execute(
            "DELETE FROM mo_oauth_states WHERE state = :state",
            {"state": state}
        )

        return social_account.dict()

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
        SELECT access_token, platform_account_id
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

        post_data = {
            "author": f"urn:li:person:{account['platform_account_id']}",
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

        if post.article_url:
            post_data["specificContent"]["com.linkedin.ugc.ShareContent"].update({
                "shareMediaCategory": "ARTICLE",
                "media": [{
                    "status": "READY",
                    "originalUrl": post.article_url
                }]
            })

        # logger.debug(f"Sending post data to LinkedIn: {json.dumps(post_data, indent=2)}")
        
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


# Add to linkedin_router.py
@router.post("/refresh")
async def refresh_token(
    refresh_token: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    # Get new tokens from LinkedIn
    new_tokens = get_new_tokens(refresh_token)

    # Update DB
    await db.execute("""
        UPDATE mo_social_accounts 
        SET 
            access_token = :access_token,
            refresh_token = :refresh_token,
            expires_at = :expires_at
        WHERE user_id = :user_id AND platform = 'linkedin'
    """, {
        "access_token": new_tokens["access_token"],
        "refresh_token": new_tokens["refresh_token"],
        "expires_at": datetime.utcnow() + timedelta(seconds=new_tokens["expires_in"]),
        "user_id": current_user["id"]
    })

    return new_tokens


async def get_new_tokens(refresh_token: str) -> dict:
    """Get new access token using refresh token from LinkedIn"""
    try:
        response = requests.post(
            ENDPOINTS["token"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET
            }
        )

        if not response.ok:
            error_data = response.json()
            error_msg = error_data.get(
                'error_description', error_data.get('error', 'Unknown error'))
            logger.error(f"Token refresh error: {error_msg}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"LinkedIn API error: {error_msg}"
            )

        token_data = response.json()
        return {
            "access_token": token_data["access_token"],
            # LinkedIn might not always return new refresh token
            "refresh_token": token_data.get("refresh_token"),
            "expires_in": token_data["expires_in"]
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
                logger.warning(f"Failed to revoke LinkedIn token: {revoke_response.text}")
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
