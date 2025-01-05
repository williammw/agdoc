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

# Define request models


class DisconnectRequest(BaseModel):
    account_id: str


class PostRequest(BaseModel):
    account_id: str
    content: Dict


router = APIRouter( tags=["youtube"])

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


@router.get("/auth")
async def auth_youtube():
    try:
        # Generate a secure state parameter
        state = secrets.token_urlsafe(16)

        flow = Flow.from_client_config(
            create_client_config(),
            scopes=SCOPES,
            redirect_uri="http://localhost:5173/youtube/callback"
        )

        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state,
            prompt='consent'  # Force consent screen to ensure refresh token
        )

        return {"url": authorization_url}
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
            redirect_uri="http://localhost:5173/youtube/callback"
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
            "id": channel['id'],
            "platform": "youtube",
            "username": channel['snippet']['title'],
            "connected": True,
            "accountType": "Channel",
            "accessToken": credentials.token,
            "refreshToken": credentials.refresh_token,
            "profileImageUrl": channel['snippet'].get('thumbnails', {}).get('default', {}).get('url'),
            "statistics": channel.get('statistics', {}),
            "connectedAt": None  # Frontend will set this
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
