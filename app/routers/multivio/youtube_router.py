from fastapi import APIRouter, HTTPException, Depends, Request, Body, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from typing import Optional, Dict
import os
import json
from dotenv import load_dotenv
import secrets
from pydantic import BaseModel
import tempfile
from app.dependencies import get_current_user, get_database
from databases import Database
import requests
from datetime import datetime, timedelta
import time
import sqlalchemy as sa

load_dotenv()

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://dev.multivio.com")
API_URL = os.getenv("API_URL", "https://dev.ohmeowkase.com")

# Parse redirect URIs and select the appropriate one
REDIRECT_URIS = os.getenv("YOUTUBE_REDIRECT_URIS", "").split(",")
# Use the frontend callback URL since we're handling the callback in the frontend
REDIRECT_URI = "https://dev.multivio.com/youtube/callback"

print(f"Using YouTube redirect URI: {REDIRECT_URI}")

# Define request models
class DisconnectRequest(BaseModel):
    account_id: str

class PostRequest(BaseModel):
    account_id: str
    content: Dict

class VideoUploadRequest(BaseModel):
    title: str
    description: str
    privacy: str
    tags: list[str]
    categoryId: str
    madeForKids: bool
    notifySubscribers: bool

router = APIRouter(tags=["youtube"])

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

def create_client_config():
    return {
        "web": {
            "client_id": os.getenv("YOUTUBE_CLIENT_ID"),
            "project_id": os.getenv("YOUTUBE_PROJECT_ID"),
            "auth_uri": os.getenv("YOUTUBE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": os.getenv("YOUTUBE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
            "auth_provider_x509_cert_url": os.getenv("YOUTUBE_AUTH_PROVIDER_CERT_URL", "https://www.googleapis.com/oauth2/v1/certs"),
            "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET"),
            "redirect_uris": [REDIRECT_URI]  # Use our configured redirect URI
        }
    }

async def get_youtube_credentials(db: Database, user_id: str, account_id: str) -> Credentials:
    """Get YouTube credentials from database"""
    query = """
        SELECT access_token, refresh_token 
        FROM mo_social_accounts 
        WHERE user_id = :user_id 
        AND platform = 'youtube' 
        AND platform_account_id = :account_id
    """
    account = await db.fetch_one(
        query=query,
        values={"user_id": user_id, "account_id": account_id}
    )
    
    if not account:
        raise HTTPException(status_code=404, detail="YouTube account not found")
    
    return Credentials(
        token=account["access_token"],
        refresh_token=account.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("YOUTUBE_CLIENT_ID"),
        client_secret=os.getenv("YOUTUBE_CLIENT_SECRET"),
        scopes=SCOPES
    )

@router.post("/auth/init")
async def auth_youtube(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Parse request body
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in request body")

        state = body.get('state')
        redirect_uri = body.get('redirect_uri')

        if not state:
            raise HTTPException(status_code=400, detail="State parameter is required")
        
        # Always use our configured redirect URI
        if redirect_uri and redirect_uri != REDIRECT_URI:
            print(f"Warning: Received redirect_uri {redirect_uri} differs from configured {REDIRECT_URI}")

        # Store state in database for verification
        query = """
            INSERT INTO mo_oauth_states (user_id, state, platform, created_at, expires_at, code_verifier)
            VALUES (:user_id, :state, :platform, :created_at, :expires_at, :code_verifier)
        """
        current_time = datetime.utcnow()
        await db.execute(
            query=query,
            values={
                "user_id": current_user["id"],
                "state": state,
                "platform": "youtube",
                "created_at": current_time,
                "expires_at": current_time + timedelta(minutes=15),  # State expires in 15 minutes
                "code_verifier": secrets.token_urlsafe(32)  # Generate random string to satisfy NOT NULL constraint
            }
        )

        flow = Flow.from_client_config(
            create_client_config(),
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )

        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state,
            prompt='consent'
        )

        return {"authUrl": authorization_url, "state": state}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Auth error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/auth/callback")
async def callback(
    code: str,
    state: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        print(f"YouTube callback received - code: {code[:10]}..., state: {state}")
        print(f"Current user: {current_user['id']}")
        print(f"Using redirect URI: {REDIRECT_URI}")

        # Verify state
        query = """
            SELECT state, code_verifier FROM mo_oauth_states 
            WHERE user_id = :user_id 
            AND state = :state 
            AND platform = 'youtube'
            AND expires_at > :current_time
        """
        current_time = datetime.utcnow()
        print(f"Verifying state at {current_time}")
        stored_state = await db.fetch_one(
            query=query,
            values={
                "user_id": current_user["id"],
                "state": state,
                "current_time": current_time
            }
        )
        
        print(f"Stored state result: {stored_state}")
        
        if not stored_state:
            raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

        # Clean up used state
        print(f"Cleaning up state: {stored_state['state']}")
        await db.execute(
            "DELETE FROM mo_oauth_states WHERE state = :state",
            values={"state": stored_state["state"]}
        )

        print("Initializing OAuth flow")
        flow = Flow.from_client_config(
            create_client_config(),
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )

        print("Fetching token")
        flow.fetch_token(code=code)
        credentials = flow.credentials
        print(f"Got credentials - token: {credentials.token[:10]}...")

        print("Fetching YouTube channel info")
        youtube = build('youtube', 'v3', credentials=credentials)
        channels_response = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        ).execute()

        if not channels_response.get('items'):
            raise HTTPException(status_code=400, detail="No YouTube channel found")

        channel = channels_response['items'][0]
        snippet = channel['snippet']
        statistics = channel['statistics']
        print(f"Got channel info - ID: {channel['id']}, Title: {snippet['title']}")

        # Store account data in database
        account_data = {
            "user_id": current_user["id"],
            "platform": "youtube",
            "platform_account_id": channel['id'],
            "username": snippet['title'],
            "profile_picture_url": snippet.get('thumbnails', {}).get('default', {}).get('url'),
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "expires_at": datetime.utcnow() + timedelta(seconds=credentials.expiry.timestamp() - time.time()) if credentials.expiry else None,
            "metadata": json.dumps({
                "name": snippet.get('title'),
                "verified": snippet.get('isVerified', False),
                "metrics": {
                    "subscribers_count": int(statistics.get('subscriberCount', 0)),
                    "video_count": int(statistics.get('videoCount', 0)),
                    "view_count": int(statistics.get('viewCount', 0))
                },
                "raw_response": {
                    "id": channel['id'],
                    "title": snippet.get('title'),
                    "description": snippet.get('description'),
                    "customUrl": snippet.get('customUrl'),
                    "thumbnails": snippet.get('thumbnails')
                }
            }),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "media_type": "video",
            "media_count": int(statistics.get('videoCount', 0)),
            "oauth1_token": None,
            "oauth1_token_secret": None
        }
        print("Prepared account data for storage")

        # Upsert account
        print("Executing upsert query")
        query = """
            INSERT INTO mo_social_accounts (
                user_id, platform, platform_account_id, username, profile_picture_url,
                access_token, refresh_token, expires_at, metadata,
                created_at, updated_at, media_type, media_count,
                oauth1_token, oauth1_token_secret
            )
            VALUES (
                :user_id, :platform, :platform_account_id, :username, :profile_picture_url,
                :access_token, :refresh_token, :expires_at, :metadata,
                :created_at, :updated_at, :media_type, :media_count,
                :oauth1_token, :oauth1_token_secret
            )
            ON CONFLICT (user_id, platform, platform_account_id) DO UPDATE SET
                username = EXCLUDED.username,
                profile_picture_url = EXCLUDED.profile_picture_url,
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at,
                media_type = EXCLUDED.media_type,
                media_count = EXCLUDED.media_count
        """
        await db.execute(query=query, values=account_data)
        print("Account data stored successfully")

        return account_data

    except Exception as e:
        print(f"Callback error: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/videos/upload")
async def upload_video(
    account_id: str = Form(...),
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(...),
    privacy: str = Form(...),
    tags: str = Form("[]"),  # JSON string of tags
    categoryId: str = Form(...),
    madeForKids: bool = Form(...),
    notifySubscribers: bool = Form(...),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        credentials = await get_youtube_credentials(db, current_user["id"], account_id)

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file.flush()

            try:
                youtube = build('youtube', 'v3', credentials=credentials)

                body = {
                    'snippet': {
                        'title': title,
                        'description': description,
                        'tags': json.loads(tags),
                        'categoryId': categoryId
                    },
                    'status': {
                        'privacyStatus': privacy,
                        'madeForKids': madeForKids,
                        'selfDeclaredMadeForKids': madeForKids
                    },
                    'notifySubscribers': notifySubscribers
                }

                media = MediaFileUpload(
                    temp_file.name,
                    mimetype=file.content_type,
                    resumable=True
                )

                request = youtube.videos().insert(
                    part='snippet,status',
                    body=body,
                    media_body=media
                )

                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        print(f"Uploaded {int(status.progress() * 100)}%")

                # Store video data
                query = """
                    INSERT INTO mo_social_videos (
                        user_id, account_id, platform, video_id,
                        title, description, privacy, url, created_at
                    )
                    VALUES (
                        :user_id, :account_id, :platform, :video_id,
                        :title, :description, :privacy, :url, :created_at
                    )
                """
                await db.execute(
                    query=query,
                    values={
                        "user_id": current_user["id"],
                        "account_id": account_id,
                        "platform": "youtube",
                        "video_id": response['id'],
                        "title": title,
                        "description": description,
                        "privacy": privacy,
                        "url": f"https://youtube.com/watch?v={response['id']}",
                        "created_at": datetime.utcnow()
                    }
                )

                return {
                    "id": response['id'],
                    "status": "success",
                    "url": f"https://youtube.com/watch?v={response['id']}"
                }

            finally:
                os.unlink(temp_file.name)

    except Exception as e:
        print(f"Upload error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/videos/{video_id}/status")
async def get_video_status(
    video_id: str,
    account_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        credentials = await get_youtube_credentials(db, current_user["id"], account_id)
        youtube = build('youtube', 'v3', credentials=credentials)
        
        response = youtube.videos().list(
            part='status,processingDetails',
            id=video_id
        ).execute()

        if not response.get('items'):
            raise HTTPException(status_code=404, detail="Video not found")

        video = response['items'][0]
        processing_status = video.get('processingDetails', {}).get('processingStatus', 'processing')
        
        status_data = {
            "status": "processed" if processing_status == "succeeded" else processing_status.lower(),
            "error": video.get('processingDetails', {}).get('processingFailureReason')
        }

        # Update video status in database
        if status_data["status"] in ["processed", "failed"]:
            query = """
                UPDATE mo_social_videos
                SET status = :status,
                    error = :error,
                    updated_at = :updated_at
                WHERE user_id = :user_id
                AND video_id = :video_id
            """
            await db.execute(
                query=query,
                values={
                    "user_id": current_user["id"],
                    "video_id": video_id,
                    "status": status_data["status"],
                    "error": status_data.get("error"),
                    "updated_at": datetime.utcnow()
                }
            )

        return status_data

    except Exception as e:
        print(f"Status check error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/disconnect")
async def disconnect_youtube(
    request: DisconnectRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Get credentials to revoke
        credentials = await get_youtube_credentials(db, current_user["id"], request.account_id)
        
        # Revoke access
        if credentials.refresh_token:
            requests.post('https://oauth2.googleapis.com/revoke',
                params={'token': credentials.refresh_token},
                headers={'content-type': 'application/x-www-form-urlencoded'})

        # Remove from database
        query = """
            DELETE FROM mo_social_accounts
            WHERE user_id = :user_id
            AND platform = 'youtube'
            AND platform_account_id = :account_id
        """
        await db.execute(
            query=query,
            values={
                "user_id": current_user["id"],
                "account_id": request.account_id
            }
        )

        return {"status": "success", "message": "Account disconnected successfully"}
    except Exception as e:
        print(f"Disconnect error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/post")
async def create_post(
    request: PostRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    raise HTTPException(
        status_code=400,
        detail="YouTube doesn't support text-only posts. Please use YouTube Studio to upload videos."
    )

@router.get("/user")
async def get_user_accounts(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        query = """
            SELECT platform_account_id as id, username, profile_picture_url, metadata,
                   created_at, updated_at, media_type, media_count
            FROM mo_social_accounts 
            WHERE user_id = :user_id 
            AND platform = 'youtube'
        """
        accounts = await db.fetch_all(
            query=query,
            values={"user_id": current_user["id"]}
        )
        
        # Transform accounts to match frontend expectations
        transformed_accounts = []
        for account in accounts:
            account_dict = dict(account)
            metadata = json.loads(account_dict.get('metadata', '{}'))
            transformed_accounts.append({
                "id": account_dict["id"],
                "username": account_dict["username"],
                "profile_picture_url": account_dict["profile_picture_url"],
                "metadata": metadata
            })
        
        return transformed_accounts
    except Exception as e:
        print(f"Error fetching YouTube accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
