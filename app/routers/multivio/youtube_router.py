from fastapi import APIRouter, HTTPException, Depends, Request, Body
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from typing import Optional, Dict
import os
import json
from dotenv import load_dotenv
import secrets
from pydantic import BaseModel

load_dotenv()

FRONTEND_URL = "http://localhost:5173"
REDIRECT_URI = f"{FRONTEND_URL}/youtube/callback"

# Define request models
class DisconnectRequest(BaseModel):
    account_id: str

class PostRequest(BaseModel):
    account_id: str
    content: Dict

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
            "redirect_uris": os.getenv("YOUTUBE_REDIRECT_URIS", "http://localhost:5173/youtube/callback").split(",")
        }
    }

@router.post("/auth")
async def auth_youtube(request: Request):
    try:
        # Get state from request body
        body = await request.json()
        state = body.get('state')
        redirect_uri = body.get('redirect_uri')

        if not state:
            raise HTTPException(status_code=400, detail="State parameter is required")

        flow = Flow.from_client_config(
            create_client_config(),
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )

        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state,
            prompt='consent'
        )

        return {"authUrl": authorization_url}
    except Exception as e:
        print(f"Auth error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/callback")
async def callback(code: str, state: Optional[str] = None):
    try:
        print(
            f"Received callback with code: {code[:10]}... and state: {state}")

        flow = Flow.from_client_config(
            create_client_config(),
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )

        # Fetch token with the received code
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get user channel info
        youtube = build('youtube', 'v3', credentials=credentials)
        channels_response = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        ).execute()

        if not channels_response.get('items'):
            raise HTTPException(
                status_code=400, detail="No YouTube channel found")

        channel = channels_response['items'][0]

        print(
            f"Successfully fetched channel info for: {channel['snippet']['title']}")

        account_data = {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "id": channel['id'],
            "title": channel['snippet']['title'],
            "thumbnail_url": channel['snippet'].get('thumbnails', {}).get('default', {}).get('url')
        }

        return account_data

    except Exception as e:
        print(f"Callback error: {str(e)}")  # Add detailed error logging
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/disconnect")
async def disconnect_youtube(request: DisconnectRequest):
    try:
        print(f"Disconnecting YouTube account: {request.account_id}")
        # Here you would typically revoke the token and clean up any stored credentials
        return {"status": "success", "message": "Account disconnected successfully"}
    except Exception as e:
        print(f"Disconnect error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/post")
async def create_post(request: PostRequest):
    # YouTube doesn't support text-only posts
    raise HTTPException(
        status_code=400,
        detail="YouTube doesn't support text-only posts. Please use YouTube Studio to upload videos."
    )
