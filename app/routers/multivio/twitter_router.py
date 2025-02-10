from fastapi import APIRouter, HTTPException, Request, File, UploadFile, Form, Response, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from app.dependencies import get_current_user, get_database
from databases import Database
import os
import secrets
import base64
import hashlib
import httpx
from typing import Annotated, Optional, List
from fastapi import Body
import json
import asyncio
from datetime import datetime, timezone, timedelta
import logging
import time

router = APIRouter(tags=["twitter"])
logger = logging.getLogger(__name__)

# Environment variables
TWITTER_CLIENT_ID = os.getenv("TWITTER_OAUTH2_CLIENT_ID")
TWITTER_CLIENT_SECRET = os.getenv("TWITTER_OAUTH2_CLIENT_SECRET")
CALLBACK_URL = os.getenv("TWITTER_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL")

# API URLs
TWITTER_API_V2 = "https://api.twitter.com/2"


def generate_code_verifier(length: int = 64) -> str:
    return secrets.token_urlsafe(length)


def generate_code_challenge(verifier: str) -> str:
    sha256_hash = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")


async def handle_rate_limit(response: httpx.Response):
    """Handle Twitter API rate limits"""
    if response.status_code == 429:
        reset_time = int(response.headers.get('x-rate-limit-reset', 0))
        current_time = int(time.time())
        sleep_time = max(reset_time - current_time, 0)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        return True
    return False


async def get_twitter_account(db: Database, account_id: str, user_id: str) -> dict:
    """Get Twitter account information from database"""
    query = """
    SELECT 
        id,
        access_token,
        refresh_token,
        platform_account_id,
        expires_at AT TIME ZONE 'UTC' as expires_at
    FROM mo_social_accounts 
    WHERE id = :account_id 
    AND user_id = :user_id 
    AND platform = 'twitter'
    """

    account = await db.fetch_one(
        query=query,
        values={
            "account_id": account_id,
            "user_id": user_id
        }
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Twitter account not found"
        )

    return dict(account)

# In your twitter_router.py


@router.post("/auth/init")
async def init_oauth(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        if not TWITTER_CLIENT_ID:
            raise HTTPException(
                status_code=500, detail="Twitter Client ID not configured")

        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = secrets.token_urlsafe(32)

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

        # Construct auth URL with correct scopes
        params = {
            'response_type': 'code',
            'client_id': TWITTER_CLIENT_ID,
            'redirect_uri': CALLBACK_URL,
            'scope': 'tweet.read tweet.write users.read offline.access',  # Removed media.upload
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }

        auth_url = f"https://twitter.com/i/oauth2/authorize?{httpx.QueryParams(params)}"

        return JSONResponse({
            "authUrl": auth_url,
            "state": state
        })

    except Exception as e:
        logger.error(f"Error in init_oauth: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/callback")
async def oauth_callback_get(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None
):
    """Handle initial OAuth callback - redirects to frontend"""
    if error or error_description:
        params = httpx.QueryParams({
            'error': error or 'unknown_error',
            'error_description': error_description or 'An error occurred during authentication'
        })
        return RedirectResponse(
            url=f"{FRONTEND_URL}/twitter/auth-error?{params}",
            status_code=302
        )

    if not code or not state:
        params = httpx.QueryParams({
            'error': 'missing_params',
            'error_description': 'Required parameters are missing'
        })
        return RedirectResponse(
            url=f"{FRONTEND_URL}/twitter/auth-error?{params}",
            status_code=302
        )

    # Redirect to frontend with code and state
    params = httpx.QueryParams({
        'code': code,
        'state': state
    })
    return RedirectResponse(
        url=f"{FRONTEND_URL}/twitter/callback?{params}",
        status_code=302
    )


@router.post("/auth/callback")
async def oauth_callback_post(
    code: Annotated[str, Body()],
    state: Annotated[str, Body()],
    db: Database = Depends(get_database)
):
    """Handle OAuth 2.0 token exchange"""
    try:
        # Get stored auth data with code_verifier
        query = """
        SELECT 
            state,
            platform,
            user_id,
            code_verifier,
            expires_at AT TIME ZONE 'UTC' as expires_at
        FROM mo_oauth_states 
        WHERE state = :state 
        AND platform = 'twitter'
        AND expires_at > CURRENT_TIMESTAMP
        """

        stored_data = await db.fetch_one(query=query, values={"state": state})

        if not stored_data:
            raise HTTPException(
                status_code=400, detail="Invalid or expired state parameter")

        code_verifier = stored_data["code_verifier"]
        if not code_verifier:
            raise HTTPException(
                status_code=400, detail="No code verifier found")

        # Exchange code for token
        token_url = f"{TWITTER_API_V2}/oauth2/token"
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

            if response.status_code != 200:
                error_data = response.json()
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_data.get(
                        "error_description", "Token exchange failed")
                )

            tokens = response.json()

            # Get user info with new token
            user_response = await client.get(
                f"{TWITTER_API_V2}/users/me",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                params={
                    "user.fields": "id,name,username,profile_image_url,protected,verified,public_metrics"
                }
            )

            if user_response.status_code != 200:
                raise HTTPException(
                    status_code=400, detail="Failed to get user info")

            user_info = user_response.json()

            # Store account info
            now = datetime.now(timezone.utc)
            expires_at = now + \
                timedelta(seconds=tokens.get('expires_in', 7200))

            # Clean up the OAuth state
            await db.execute(
                "DELETE FROM mo_oauth_states WHERE state = :state",
                {"state": state}
            )

            # Store the account info
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
            RETURNING id
            """

            twitter_user = user_info['data']
            values = {
                "user_id": stored_data["user_id"],
                "platform_account_id": twitter_user["id"],
                "username": twitter_user["username"],
                "profile_picture_url": twitter_user.get("profile_image_url"),
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_at": expires_at,
                "metadata": json.dumps({
                    "verified": twitter_user.get("verified", False),
                    "protected": twitter_user.get("protected", False),
                    "metrics": twitter_user.get("public_metrics", {})
                }),
                "created_at": now
            }

            result = await db.fetch_one(query=query, values=values)

            return {
                "id": result["id"],
                "username": twitter_user["username"],
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_in": tokens.get("expires_in")
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in oauth_callback: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/refresh")
async def refresh_token(
    refresh_token: Annotated[str, Body()],
):
    """Refresh the access token"""
    try:
        token_url = f"{TWITTER_API_V2}/oauth2/token"
        data = {
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
            'client_id': TWITTER_CLIENT_ID
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


@router.post("/tweets")
async def create_tweet(
    access_token: Annotated[str, Body()],
    text: Annotated[str, Body()],
    media_ids: Annotated[Optional[List[str]], Body()] = None,
    reply_settings: Annotated[Optional[str], Body()] = None,
    quote_tweet_id: Annotated[Optional[str], Body()] = None,
    reply_to_tweet_id: Annotated[Optional[str], Body()] = None,
    is_thread: Annotated[Optional[bool], Body()] = False,
    thread_texts: Annotated[Optional[List[str]], Body()] = None
):
    """Create a tweet or thread"""
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # Handle single tweet
        if not is_thread:
            data = {
                "text": text,
                "reply": {
                    "in_reply_to_tweet_id": reply_to_tweet_id
                } if reply_to_tweet_id else None,
                "quote_tweet_id": quote_tweet_id,
                "reply_settings": reply_settings,
                "media": {
                    "media_ids": media_ids
                } if media_ids else None
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{TWITTER_API_V2}/tweets",
                    json={k: v for k, v in data.items() if v is not None},
                    headers=headers
                )

                if response.status_code != 201:
                    if await handle_rate_limit(response):
                        response = await client.post(
                            f"{TWITTER_API_V2}/tweets",
                            json={k: v for k, v in data.items() if v is not None},
                            headers=headers
                        )
                    else:
                        raise HTTPException(
                            status_code=400, detail=response.json())

            return response.json()

        # Handle thread creation
        else:
            if not thread_texts:
                raise HTTPException(
                    status_code=400, detail="Thread texts are required for thread creation")

            # Create first tweet
            first_tweet_data = {
                "text": text,
                "reply_settings": reply_settings,
                "media": {
                    "media_ids": media_ids
                } if media_ids else None
            }

            async with httpx.AsyncClient() as client:
                first_response = await client.post(
                    f"{TWITTER_API_V2}/tweets",
                    json={k: v for k, v in first_tweet_data.items()
                          if v is not None},
                    headers=headers
                )

                if first_response.status_code != 201:
                    if await handle_rate_limit(first_response):
                        first_response = await client.post(
                            f"{TWITTER_API_V2}/tweets",
                            json={k: v for k, v in first_tweet_data.items()
                                  if v is not None},
                            headers=headers
                        )
                    else:
                        raise HTTPException(
                            status_code=400, detail=first_response.json())

                first_tweet = first_response.json()
                previous_tweet_id = first_tweet['data']['id']
                thread_tweets = [first_tweet]

                # Create the rest of the thread
                for thread_text in thread_texts:
                    thread_tweet_data = {
                        "text": thread_text,
                        "reply": {
                            "in_reply_to_tweet_id": previous_tweet_id
                        }
                    }

                    thread_response = await client.post(
                        f"{TWITTER_API_V2}/tweets",
                        json=thread_tweet_data,
                        headers=headers
                    )

                    if thread_response.status_code != 201:
                        if await handle_rate_limit(thread_response):
                            thread_response = await client.post(
                                f"{TWITTER_API_V2}/tweets",
                                json=thread_tweet_data,
                                headers=headers
                            )
                        else:
                            raise HTTPException(
                                status_code=400, detail=thread_response.json())

                    thread_tweet = thread_response.json()
                    thread_tweets.append(thread_tweet)
                    previous_tweet_id = thread_tweet['data']['id']

                return {
                    "thread": thread_tweets
                }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tweets/{tweet_id}")
async def delete_tweet(
    tweet_id: str,
    access_token: Annotated[str, Body()]
):
    """Delete a tweet"""
    try:
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{TWITTER_API_V2}/tweets/{tweet_id}",
                headers=headers
            )

            if response.status_code != 200:
                if await handle_rate_limit(response):
                    response = await client.delete(
                        f"{TWITTER_API_V2}/tweets/{tweet_id}",
                        headers=headers
                    )
                else:
                    raise HTTPException(
                        status_code=400, detail=response.json())

            return {"message": "Tweet deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    access_token: str = Form(...)
):
    """Upload media for a tweet"""
    try:
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        # Read file content
        content = await file.read()

        async with httpx.AsyncClient() as client:
            # Initialize upload
            init_response = await client.post(
                "https://upload.twitter.com/1.1/media/upload.json",
                data={
                    "command": "INIT",
                    "total_bytes": len(content),
                    "media_type": file.content_type,
                },
                headers=headers
            )

            if init_response.status_code != 200:
                raise HTTPException(
                    status_code=400, detail=init_response.json())

            media_id = init_response.json()["media_id_string"]

            # Upload media in chunks
            chunk_size = 1024 * 1024  # 1MB chunks
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                append_response = await client.post(
                    "https://upload.twitter.com/1.1/media/upload.json",
                    data={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": i // chunk_size
                    },
                    files={"media": chunk},
                    headers=headers
                )

                if append_response.status_code != 200:
                    raise HTTPException(
                        status_code=400, detail=append_response.json())

            # Finalize upload
            finalize_response = await client.post(
                "https://upload.twitter.com/1.1/media/upload.json",
                data={
                    "command": "FINALIZE",
                    "media_id": media_id
                },
                headers=headers
            )

            if finalize_response.status_code != 200:
                raise HTTPException(
                    status_code=400, detail=finalize_response.json())

            return {"media_id": media_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user")
async def get_user_info(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get user's Twitter accounts"""
    try:
        query = """
        SELECT 
            id,
            platform_account_id,
            username,
            profile_picture_url,
            access_token,
            refresh_token,
            expires_at AT TIME ZONE 'UTC' as expires_at,
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
            if account_dict.get("metadata"):
                account_dict["metadata"] = json.loads(account_dict["metadata"])
            account_list.append(account_dict)

        return {
            "connected": True,
            "accounts": account_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/validate-token")
async def validate_token(
    account_id: Annotated[str, Body(embed=True)],
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Validate and refresh token if needed"""
    try:
        # Get account info
        account = await get_twitter_account(db, account_id, current_user["uid"])

        # Check if token needs refresh (15 minutes buffer)
        now = datetime.now(timezone.utc)
        expires_at = account["expires_at"].replace(
            tzinfo=timezone.utc) if account["expires_at"].tzinfo is None else account["expires_at"]

        if expires_at - timedelta(minutes=15) <= now:
            # Token needs refresh
            refresh_result = await refresh_token(account["refresh_token"])

            # Update token in database
            query = """
            UPDATE mo_social_accounts 
            SET 
                access_token = :access_token,
                refresh_token = :refresh_token,
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE id = :account_id
            """

            expires_at = now + timedelta(seconds=refresh_result["expires_in"])
            await db.execute(
                query=query,
                values={
                    "access_token": refresh_result["access_token"],
                    "refresh_token": refresh_result.get("refresh_token", account["refresh_token"]),
                    "expires_at": expires_at,
                    "updated_at": now,
                    "account_id": account_id
                }
            )

            return {
                "valid": True,
                "access_token": refresh_result["access_token"],
                "expires_in": refresh_result["expires_in"]
            }

        return {
            "valid": True,
            "access_token": account["access_token"],
            "expires_in": int((expires_at - now).total_seconds())
        }

    except Exception as e:
        logger.error(f"Token validation error: {str(e)}")
        return {
            "valid": False,
            "error": str(e)
        }


@router.post("/auth/disconnect")
async def disconnect_account(
    account_id: Annotated[str, Body()],
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Disconnect Twitter account"""
    try:
        # Delete account from database
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
                detail="Account not found or already disconnected"
            )

        return {
            "success": True,
            "message": "Account disconnected successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to disconnect account: {str(e)}"
        )


@router.get("/user/me")
async def get_user_info_with_token(
    request: Request,
    db: Database = Depends(get_database)
):
    """Get user info using Twitter OAuth token"""
    try:
        # Get the Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header"
            )

        # Extract the token
        token = auth_header.split(' ')[1]

        # Use token to get user info from Twitter
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TWITTER_API_V2}/users/me",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "user.fields": "id,name,username,profile_image_url,protected,verified,public_metrics"
                }
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to get user info from Twitter"
                )

            user_info = response.json()
            return user_info

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.post("/auth/update-token")
async def update_token(
    account_id: Annotated[str, Body()],
    access_token: Annotated[str, Body()],
    refresh_token: Annotated[str, Body()],
    expires_at: Annotated[str, Body()],
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Update stored tokens"""
    try:
        query = """
        UPDATE mo_social_accounts 
        SET 
            access_token = :access_token,
            refresh_token = :refresh_token,
            expires_at = :expires_at,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :account_id 
        AND user_id = :user_id
        AND platform = 'twitter'
        RETURNING id
        """

        result = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "user_id": current_user["uid"]
            }
        )

        if not result:
            raise HTTPException(
                status_code=404,
                detail="Account not found"
            )

        return {"success": True}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
