# import os
# from fastapi import APIRouter, HTTPException
# from pydantic import BaseModel
# from typing import Optional
# import httpx
# from dotenv import load_dotenv
# import secrets
# import base64
# import json

# load_dotenv()

# THREADS_APP_ID = os.getenv("THREADS_APP_ID")
# THREADS_APP_SECRET = os.getenv("THREADS_APP_SECRET")
# THREADS_REDIRECT_URI = os.getenv("THREADS_REDIRECT_URI", "http://localhost:5173/threads/callback")

# if not all([THREADS_APP_ID, THREADS_APP_SECRET]):
#     raise ValueError("Missing required Threads credentials in .env")

# router = APIRouter(tags=["threads"])

# # API Base URLs
# FACEBOOK_OAUTH_URL = "https://www.facebook.com/v18.0"
# GRAPH_API_URL = "https://graph.threads.net/v18.0"

# # Required Threads API scopes
# THREADS_SCOPES = [
#     "threads_basic",
#     "threads_content_publish",
#     "threads_manage_insights", 
#     "threads_manage_replies",
#     "threads_read_replies",
#     "threads_keyword_search",
#     "threads_manage_mentions"
# ]

# class TokenRequest(BaseModel):
#     code: str
#     state: str
#     redirect_uri: str

# @router.post("/auth")
# async def initialize_auth():
#     """Initialize Threads OAuth process following official documentation."""
#     try:
#         state = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
        
#         # Use Facebook's OAuth URL for authorization
#         auth_url = (
#             f"{FACEBOOK_OAUTH_URL}/dialog/oauth"
#             f"?client_id={THREADS_APP_ID}"
#             f"&redirect_uri={THREADS_REDIRECT_URI}"
#             f"&state={state}"
#             f"&scope={','.join(THREADS_SCOPES)}"
#             f"&response_type=code"
#         )
        
#         print(f"Generated auth URL: {auth_url}")
        
#         return {
#             "success": True,
#             "message": "Auth URL generated successfully",
#             "data": {
#                 "auth_url": auth_url,
#                 "state": state
#             }
#         }
#     except Exception as e:
#         return {
#             "success": False,
#             "message": "Failed to initialize auth",
#             "error": str(e)
#         }

# @router.post("/callback")
# async def handle_callback(request: TokenRequest):
#     """Handle OAuth callback for Threads."""
#     try:
#         async with httpx.AsyncClient() as client:
#             # Step 1: Exchange code for access token using Threads Graph API
#             token_response = await client.get(
#                 f"{GRAPH_API_URL}/oauth/access_token",
#                 params={
#                     "client_id": THREADS_APP_ID,
#                     "client_secret": THREADS_APP_SECRET,
#                     "redirect_uri": request.redirect_uri,
#                     "code": request.code,
#                     "grant_type": "authorization_code"
#                 }
#             )
            
#             print("Token exchange response:", await token_response.aread())
            
#             if not token_response.is_success:
#                 error_data = token_response.json()
#                 raise HTTPException(
#                     status_code=400,
#                     detail=f"Token exchange failed: {error_data.get('error', {}).get('message')}"
#                 )

#             token_data = token_response.json()
#             access_token = token_data.get("access_token")

#             # Step 2: Exchange for Threads-specific long-lived token
#             long_lived_response = await client.get(
#                 f"{GRAPH_API_URL}/access_token",
#                 params={
#                     "grant_type": "th_exchange_token",
#                     "client_secret": THREADS_APP_SECRET,
#                     "access_token": access_token
#                 }
#             )
            
#             print("Long-lived token response:", await long_lived_response.aread())

#             if not long_lived_response.is_success:
#                 error_data = long_lived_response.json()
#                 raise HTTPException(
#                     status_code=400,
#                     detail=f"Long-lived token exchange failed: {error_data.get('error', {}).get('message')}"
#                 )

#             long_lived_data = long_lived_response.json()
#             long_lived_token = long_lived_data.get("access_token")

#             # Step 3: Get user profile info
#             profile_response = await client.get(
#                 f"{GRAPH_API_URL}/me",
#                 params={
#                     "access_token": long_lived_token,
#                     "fields": "id,username,name,threads_profile_picture_url"
#                 }
#             )
            
#             print("Profile response:", await profile_response.aread())

#             if not profile_response.is_success:
#                 error_data = profile_response.json()
#                 raise HTTPException(
#                     status_code=400,
#                     detail=f"Failed to fetch profile: {error_data.get('error', {}).get('message')}"
#                 )

#             profile_data = profile_response.json()

#             return {
#                 "success": True,
#                 "message": "Authentication successful",
#                 "data": {
#                     "access_token": long_lived_token,
#                     "expires_in": long_lived_data.get("expires_in"),
#                     "token_type": long_lived_data.get("token_type"),
#                     "profile": {
#                         "id": profile_data.get("id"),
#                         "username": profile_data.get("username"),
#                         "name": profile_data.get("name"),
#                         "profile_image_url": profile_data.get("threads_profile_picture_url")
#                     }
#                 }
#             }

#     except HTTPException as e:
#         raise e
#     except Exception as e:
#         print(f"Unexpected error in callback: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=str(e)
#         )
