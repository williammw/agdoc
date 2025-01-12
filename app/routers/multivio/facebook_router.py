from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional
import httpx
import os
from pydantic import BaseModel
from fastapi.responses import RedirectResponse
import logging

router = APIRouter(tags=["facebook"])

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FACEBOOK_API_VERSION = os.getenv("FACEBOOK_API_VERSION", "v21.0")
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

class FacebookAuthRequest(BaseModel):
    redirect_uri: str

class FacebookPage(BaseModel):
    id: str
    name: str
    access_token: str

class FacebookPost(BaseModel):
    message: str
    page_id: str
    page_access_token: str

@router.get("/auth")
async def facebook_auth(request: Request):
    """Initiate Facebook OAuth flow"""
    scope = "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_metadata,business_management"
    redirect_uri = f"{request.base_url}callback"
    
    auth_url = (
        f"https://www.facebook.com/{FACEBOOK_API_VERSION}/dialog/oauth?"
        f"client_id={FACEBOOK_APP_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"scope={scope}&"
        "response_type=code&"
        "auth_type=reauthenticate"
    )
    return RedirectResponse(url=auth_url)

@router.get("/callback")
async def facebook_callback(code: str, request: Request):
    """Handle Facebook OAuth callback"""
    redirect_uri = f"{request.base_url}"
    
    async with httpx.AsyncClient() as client:
        # Exchange code for access token
        token_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/oauth/access_token"
        token_response = await client.get(
            token_url,
            params={
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "code": code,
                "redirect_uri": redirect_uri
            }
        )
        
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get access token")
        
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        
        # Get user ID
        me_response = await client.get(
            f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/me",
            params={"access_token": access_token}
        )
        
        if me_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get user info")
            
        user_data = me_response.json()
        user_id = user_data.get("id")
        
        # Redirect back to frontend with data
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?platform=facebook&userId={user_id}&accessToken={access_token}"
        )

@router.get("/pages/{user_id}")
async def get_facebook_pages(user_id: str, access_token: str):
    logger.info(f"Fetching pages for user_id: {user_id}")
    
    async with httpx.AsyncClient() as client:
        try:
            # Get user permissions
            permissions_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{user_id}/permissions"
            logger.info(f"Checking permissions at: {permissions_url}")
            
            permissions_response = await client.get(permissions_url, params={"access_token": access_token})
            logger.info(f"Permissions response status: {permissions_response.status_code}")
            
            if permissions_response.status_code != 200:
                error_data = permissions_response.json()
                logger.error(f"Permissions check failed: {error_data}")
                raise HTTPException(
                    status_code=permissions_response.status_code,
                    detail=f"Failed to verify permissions: {error_data.get('error', {}).get('message', 'Unknown error')}"
                )

            # Debug permissions
            permissions_data = permissions_response.json()
            logger.info(f"Permissions data: {permissions_data}")

            # Get pages
            pages_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{user_id}/accounts"
            logger.info(f"Fetching pages from: {pages_url}")
            
            pages_response = await client.get(pages_url, params={"access_token": access_token})
            logger.info(f"Pages response status: {pages_response.status_code}")
            
            if pages_response.status_code != 200:
                error_data = pages_response.json()
                logger.error(f"Pages fetch failed: {error_data}")
                raise HTTPException(
                    status_code=pages_response.status_code,
                    detail=f"Failed to fetch pages: {error_data.get('error', {}).get('message', 'Unknown error')}"
                )
            
            pages_data = pages_response.json()
            logger.info(f"Pages data: {pages_data}")
            
            if not pages_data.get("data"):
                logger.warning("No pages found in response")
                raise HTTPException(status_code=404, detail="No Facebook pages found for this user")

            # Get page pictures and create response
            pages = []
            for page in pages_data["data"]:
                try:
                    picture_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{page['id']}/picture"
                    picture_response = await client.get(
                        picture_url,
                        params={
                            "redirect": "false",
                            "access_token": page["access_token"]
                        }
                    )
                    picture_data = picture_response.json()
                    
                    pages.append({
                        "id": page["id"],
                        "platform": "facebook",
                        "username": page["name"],
                        "connected": True,
                        "accountType": "Page",
                        "connectedAt": None,
                        "isPage": True,
                        "pageAccessToken": page["access_token"],
                        "thumbnailUrl": picture_data.get("data", {}).get("url")
                    })
                except Exception as e:
                    logger.error(f"Error processing page {page.get('id')}: {str(e)}")
                    # Continue with next page if one fails
                    continue

            logger.info(f"Successfully processed {len(pages)} pages")
            return pages
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/post")
async def create_facebook_post(post: FacebookPost):
    async with httpx.AsyncClient() as client:
        post_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{post.page_id}/feed"
        response = await client.post(
            post_url,
            json={
                "message": post.message,
                "access_token": post.page_access_token
            }
        )
        
        if response.status_code != 200:
            error_data = response.json()
            raise HTTPException(
                status_code=400,
                detail=error_data.get("error", {}).get("message", "Failed to post to Facebook")
            )
            
        return response.json()
