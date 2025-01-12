from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional
import httpx
import os
from pydantic import BaseModel
from fastapi.responses import RedirectResponse
import logging

router = APIRouter(tags=["instagram"])

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FACEBOOK_API_VERSION = os.getenv("FACEBOOK_API_VERSION", "v21.0")
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

class InstagramAccount(BaseModel):
    id: str
    username: str
    access_token: str

class InstagramPost(BaseModel):
    image_url: str
    caption: str
    account_id: str
    access_token: str

@router.get("/accounts")
async def get_instagram_accounts(access_token: str):
    """Get Instagram business accounts connected to Facebook pages"""
    logger.info("Fetching Instagram business accounts")
    
    async with httpx.AsyncClient() as client:
        try:
            # Get Facebook pages with Instagram accounts
            pages_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/me/accounts"
            logger.info(f"Fetching pages from: {pages_url}")
            
            pages_response = await client.get(
                pages_url,
                params={
                    "access_token": access_token,
                    "fields": "id,name,access_token,instagram_business_account{id,username,profile_picture_url}"
                }
            )
            
            if pages_response.status_code != 200:
                error_data = pages_response.json()
                logger.error(f"Pages fetch failed: {error_data}")
                raise HTTPException(
                    status_code=pages_response.status_code,
                    detail=f"Failed to fetch pages: {error_data.get('error', {}).get('message', 'Unknown error')}"
                )

            pages_data = pages_response.json()
            logger.info(f"Pages data received: {pages_data}")

            # Filter pages with Instagram accounts
            instagram_accounts = []
            for page in pages_data.get("data", []):
                if instagram_account := page.get("instagram_business_account"):
                    instagram_accounts.append({
                        "id": instagram_account["id"],
                        "platform": "instagram",
                        "username": instagram_account["username"],
                        "connected": True,
                        "accountType": "Business",
                        "connectedAt": None,
                        "accessToken": page["access_token"],
                        "isPage": False,
                        "thumbnailUrl": instagram_account.get("profile_picture_url")
                    })

            if not instagram_accounts:
                logger.warning("No Instagram business accounts found")
                raise HTTPException(
                    status_code=404,
                    detail="No Instagram business accounts found. Please ensure your Instagram account is a business account and connected to your Facebook page."
                )

            logger.info(f"Found {len(instagram_accounts)} Instagram accounts")
            return instagram_accounts

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/post")
async def create_instagram_post(post: InstagramPost):
    """Create an Instagram post with image"""
    logger.info(f"Creating Instagram post for account: {post.account_id}")
    
    async with httpx.AsyncClient() as client:
        try:
            # Step 1: Create media container
            container_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{post.account_id}/media"
            logger.info(f"Creating media container at: {container_url}")
            
            container_response = await client.post(
                container_url,
                json={
                    "image_url": post.image_url,
                    "caption": post.caption,
                    "access_token": post.access_token,
                    "media_type": "IMAGE"
                }
            )

            if container_response.status_code != 200:
                error_data = container_response.json()
                logger.error(f"Container creation failed: {error_data}")
                raise HTTPException(
                    status_code=container_response.status_code,
                    detail=f"Failed to create post container: {error_data.get('error', {}).get('message', 'Unknown error')}"
                )

            container_data = container_response.json()
            creation_id = container_data.get("id")
            
            if not creation_id:
                raise HTTPException(status_code=400, detail="Failed to get creation ID")

            # Step 2: Publish the container
            publish_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/{post.account_id}/media_publish"
            logger.info(f"Publishing media at: {publish_url}")
            
            publish_response = await client.post(
                publish_url,
                json={
                    "creation_id": creation_id,
                    "access_token": post.access_token
                }
            )

            if publish_response.status_code != 200:
                error_data = publish_response.json()
                logger.error(f"Publishing failed: {error_data}")
                raise HTTPException(
                    status_code=publish_response.status_code,
                    detail=f"Failed to publish post: {error_data.get('error', {}).get('message', 'Unknown error')}"
                )

            return publish_response.json()

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
