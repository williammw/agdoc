from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
import os
import secrets
import base64
import hashlib
import httpx
from typing import Annotated
from fastapi import Body
from typing import Optional

router = APIRouter(tags=["twitter"])

# Environment variables for twitter
TWITTER_CLIENT_ID = os.getenv("TWITTER_OAUTH2_CLIENT_ID")
TWITTER_CLIENT_SECRET = os.getenv("TWITTER_OAUTH2_CLIENT_SECRET")
# Dynamic callback URL based on environment
BASE_URL = os.getenv("BASE_URL")
CALLBACK_URL = f"{BASE_URL}/twitter/callback"

def generate_code_verifier(length: int = 64) -> str:
    return secrets.token_urlsafe(length)

def generate_code_challenge(verifier: str) -> str:
    sha256_hash = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")

@router.post("/auth")
async def init_oauth():
    """Initialize OAuth 2.0 flow"""
    try:
        if not TWITTER_CLIENT_ID:
            raise HTTPException(
                status_code=500,
                detail="Twitter Client ID not configured"
            )

        # Generate PKCE values
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = secrets.token_urlsafe(32)

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
        
        return JSONResponse({
            "authUrl": auth_url,
            "state": state,
            "code_verifier": code_verifier  # Store this securely in production
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/callback")
async def oauth_callback(
    code: str,
    state: str,
    code_verifier: str
):
    """Handle OAuth 2.0 callback"""
    try:
        # Exchange code for access token
        token_url = "https://api.twitter.com/2/oauth2/token"
        data = {
            'code': code,
            'grant_type': 'authorization_code',
            'client_id': TWITTER_CLIENT_ID,
            'redirect_uri': CALLBACK_URL,
            'code_verifier': code_verifier
        }
        
        auth = httpx.BasicAuth(TWITTER_CLIENT_ID, TWITTER_CLIENT_SECRET)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data, auth=auth)
            tokens = response.json()
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=tokens)
            
            return tokens

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user")
async def get_user_info(
    access_token: str
):
    """Get Twitter user info"""
    try:
        url = "https://api.twitter.com/2/users/me"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                params={
                    "user.fields": "profile_image_url,name,username"
                }
            )

            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=response.json())

            return response.json()["data"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tweet")
async def create_tweet(
    request: Request,  # Add this to get the raw request
    text: Annotated[str, Body()],  # Change this to use Body
    access_token: Annotated[str, Body()]  # Change this to use Body
):
    """Create a new tweet"""
    try:
        url = "https://api.twitter.com/2/tweets"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = {"text": text}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers)
            result = response.json()

            if response.status_code != 201:
                raise HTTPException(status_code=400, detail=result)

            return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/tweet/{tweet_id}")
async def delete_tweet(
    tweet_id: str,
    access_token: str
):
    """Delete a tweet"""
    try:
        url = f"https://api.twitter.com/2/tweets/{tweet_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.delete(url, headers=headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=response.json())
                
            return {"message": "Tweet deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# https://twitter.com/i/oauth2/authorize?response_type =code&client_id=MHA1eGFZb2ZfNjlVMndya0NkbTk6MTpjaQ&redirect_uri=https%3A%2F%2Ff0fe-185-245-239-66.ngrok-free.app%2Ftwitter%2Fcallback&scope=tweet.read%20tweet.write%20users.read%20offline.access&state=Yv38ia01r_7P6X3iZJnShAr2qSjPoXxcMb7uRRq6L8g&code_challenge=FQXIvqciwgbuIHfIy9NR6u510cZi99XmTV1zGD--ljs&code_challenge_method=S256