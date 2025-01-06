from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import requests
from urllib.parse import urlencode
import os
from dotenv import load_dotenv
import secrets
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(tags=['LinkedIn'])

# Configuration
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:5173/linkedin/callback")  # Full callback URL from env

# LinkedIn API endpoints
LINKEDIN_ENDPOINTS = {
    "auth": "https://www.linkedin.com/oauth/v2/authorization",
    "token": "https://www.linkedin.com/oauth/v2/accessToken",
    "user_info": "https://api.linkedin.com/v2/userinfo",
    "profile": "https://api.linkedin.com/v2/me",
    "profile_picture": "https://api.linkedin.com/v2/me?projection=(id,profilePicture(displayImage~:playableStreams))",
    "share": "https://api.linkedin.com/v2/ugcPosts",
    "organizations": "https://api.linkedin.com/v2/organizationalEntityAcls?q=roleAssignee",
    "revoke": "https://www.linkedin.com/oauth/v2/revoke"
}

def get_linkedin_headers(access_token: str, include_restli: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    if include_restli:
        headers.update({
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        })
    return headers

@router.post("/auth")
async def initialize_linkedin_auth(request: Request):
    state = secrets.token_urlsafe(32)
    
    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,  # Always use frontend callback
        "scope": "openid profile w_member_social email",
        "state": state
    }

    auth_url = f"{LINKEDIN_ENDPOINTS['auth']}?{urlencode(auth_params)}"
    logger.debug(f"Generated LinkedIn auth URL with redirect_uri: {REDIRECT_URI}")
    return {"authUrl": auth_url, "state": state}

@router.api_route("/callback", methods=["GET", "POST"])
async def linkedin_callback(request: Request):
    try:
        # Extract code and state from POST body (sent by frontend)
        data = await request.json()
        code = data.get("code")
        state = data.get("state")

        logger.debug(f"Callback received - code: {code}, state: {state}")

        if not code:
            raise HTTPException(status_code=400, detail="Authorization code is required")

        # Exchange code for access token
        token_response = requests.post(
            LINKEDIN_ENDPOINTS['token'],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,  # Must match the auth redirect_uri
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET
            }
        )

        if not token_response.ok:
            logger.error(f"Token request failed: {token_response.status_code} - {token_response.text}")
            raise HTTPException(status_code=400, detail=f"Failed to get access token: {token_response.text}")

        access_token = token_response.json()["access_token"]
        headers = get_linkedin_headers(access_token)

        # Get user info and profile data
        user_data = requests.get(LINKEDIN_ENDPOINTS['user_info'], headers=headers).json()
        profile_data = requests.get(LINKEDIN_ENDPOINTS['profile'], headers=headers).json()
        
        # Get profile picture
        picture_response = requests.get(LINKEDIN_ENDPOINTS['profile_picture'], headers=headers)
        profile_picture_url = user_data.get('picture')

        if not profile_picture_url and picture_response.ok:
            picture_data = picture_response.json()
            if "profilePicture" in picture_data:
                elements = picture_data["profilePicture"].get("displayImage~", {}).get("elements", [])
                if elements:
                    profile_picture_url = max(
                        elements,
                        key=lambda x: x.get("data", {}).get("width", 0)
                    ).get("identifiers", [{}])[0].get("identifier")

        # Get organizations
        org_response = requests.get(LINKEDIN_ENDPOINTS['organizations'], headers=headers)
        organizations = []
        
        if org_response.ok:
            for element in org_response.json().get("elements", []):
                if element.get("role") == "ADMINISTRATOR":
                    org_id = element.get("organizationalTarget")
                    if org_id:
                        org_details = requests.get(
                            f"https://api.linkedin.com/v2/organizations/{org_id}",
                            headers=headers
                        ).json()
                        organizations.append({
                            "id": org_id,
                            "name": org_details.get("localizedName", ""),
                            "vanityName": org_details.get("vanityName", ""),
                            "logoUrl": org_details.get("logoV2", {}).get("original", ""),
                            "type": "Company"
                        })

        # Construct response
        user_profile = {
            "id": user_data.get("sub") or profile_data.get("id"),
            "firstName": user_data.get("given_name", ""),
            "lastName": user_data.get("family_name", ""),
            "email": user_data.get("email"),
            "profilePicture": profile_picture_url,
            "type": "Personal"
        }

        return {
            "accessToken": access_token,
            "profileData": {
                **user_profile,
                "accounts": [user_profile, *organizations]
            }
        }

    except Exception as e:
        logger.exception("Error in LinkedIn callback")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/share")
async def share_post(request: Request):
    data = await request.json()
    if not all(k in data for k in ["accountId", "content", "accessToken"]):
        raise HTTPException(status_code=400, detail="Account ID, content, and access token are required")

    response = requests.post(
        LINKEDIN_ENDPOINTS['share'],
        headers=get_linkedin_headers(data['accessToken'], include_restli=True),
        json=data['content']
    )

    if not response.ok:
        raise HTTPException(status_code=400, detail=f"Failed to post: {response.text}")
    return {"success": True}

@router.post("/revoke")
async def revoke_access(request: Request):
    try:
        data = await request.json()
        access_token = data.get("accessToken")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="Access token is required")

        revoke_response = requests.post(
            LINKEDIN_ENDPOINTS['revoke'],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "token": access_token
            }
        )

        if not revoke_response.ok:
            error = revoke_response.json()
            if error.get("error") == "invalid_grant":
                return {"success": True, "message": "Token already expired or revoked"}
            raise HTTPException(status_code=400, detail=f"Failed to revoke token: {revoke_response.text}")

        return {"success": True, "message": "Token successfully revoked"}
    except Exception as e:
        logger.exception("Error in revoke_access")
        raise HTTPException(status_code=400, detail=str(e))
