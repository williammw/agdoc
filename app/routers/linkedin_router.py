from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import requests
from urllib.parse import urlencode
import os
from dotenv import load_dotenv
import secrets
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(tags=['LinkedIn'])

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("FRONTEND_URL") + "/linkedin/callback"

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USER_INFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_PROFILE_URL = "https://api.linkedin.com/v2/me"
LINKEDIN_PROFILE_PICTURE_URL = "https://api.linkedin.com/v2/me?projection=(id,profilePicture(displayImage~:playableStreams))"
LINKEDIN_SHARE_URL = "https://api.linkedin.com/v2/ugcPosts"
LINKEDIN_ORGANIZATIONS_URL = "https://api.linkedin.com/v2/organizationalEntityAcls?q=roleAssignee"


@router.post("/auth")
async def initialize_linkedin_auth():
    state = secrets.token_urlsafe(32)
    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile w_member_social email",
        "state": state
    }

    auth_url = f"{LINKEDIN_AUTH_URL}?{urlencode(auth_params)}"
    logger.debug(f"Generated LinkedIn auth URL: {auth_url}")
    return {"authUrl": auth_url, "state": state}


@router.api_route("/callback", methods=["GET", "POST"])
async def linkedin_callback(request: Request):
    try:
        # Handle both GET params and POST body
        if request.method == "GET":
            code = request.query_params.get("code")
            state = request.query_params.get("state")
        else:
            body = await request.json()
            code = body.get("code")
            state = body.get("state")
        
        logger.debug(f"Received callback - method: {request.method}, code: {code}, state: {state}")

        if not code:
            logger.error("No authorization code received")
            raise HTTPException(status_code=400, detail="Authorization code is required")

        # Exchange code for access token
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }

        logger.debug("Requesting access token with data:", token_data)
        token_response = requests.post(LINKEDIN_TOKEN_URL, data=token_data)

        if not token_response.ok:
            logger.error(
                f"Token request failed: {token_response.status_code} - {token_response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to get access token: {token_response.text}"
            )

        token_info = token_response.json()
        access_token = token_info["access_token"]
        logger.debug("Successfully obtained access token")

        headers = {"Authorization": f"Bearer {access_token}"}

        # Get user info using OpenID endpoint
        logger.debug("Requesting user info")
        user_response = requests.get(
            LINKEDIN_USER_INFO_URL,
            headers=headers
        )

        if not user_response.ok:
            logger.error(
                f"User info request failed: {user_response.status_code} - {user_response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to get user info: {user_response.text}"
            )

        user_data = user_response.json()
        logger.debug(f"User data received: {user_data}")

        # Get additional profile data if needed
        logger.debug("Requesting profile data")
        profile_response = requests.get(
            LINKEDIN_PROFILE_URL,
            headers=headers
        )

        profile_data = {}
        if profile_response.ok:
            profile_data = profile_response.json()
            logger.debug(f"Profile data received: {profile_data}")

        # Get profile picture
        logger.debug("Requesting profile picture")
        picture_response = requests.get(
            LINKEDIN_PROFILE_PICTURE_URL, headers=headers)
        profile_picture_url = user_data.get(
            'picture')  # Try to get from OpenID first

        if not profile_picture_url and picture_response.ok:
            picture_data = picture_response.json()
            logger.debug(f"Picture data received: {picture_data}")
            if "profilePicture" in picture_data:
                picture_elements = picture_data["profilePicture"].get(
                    "displayImage~", {}).get("elements", [])
                if picture_elements:
                    largest_image = max(picture_elements, key=lambda x: x.get(
                        "data", {}).get("width", 0))
                    profile_picture_url = largest_image.get("identifiers", [{}])[
                        0].get("identifier")

        # Get organization/pages data
        logger.debug("Requesting organization data")
        org_response = requests.get(
            LINKEDIN_ORGANIZATIONS_URL, headers=headers)

        organizations = []
        if org_response.ok:
            org_data = org_response.json()
            logger.debug(f"Organization data received: {org_data}")

            # Get details for each organization
            if "elements" in org_data:
                for element in org_data["elements"]:
                    if element.get("role") == "ADMINISTRATOR":
                        org_id = element.get("organizationalTarget")
                        if org_id:
                            # Get organization details
                            org_details_response = requests.get(
                                f"https://api.linkedin.com/v2/organizations/{org_id}",
                                headers=headers
                            )
                            if org_details_response.ok:
                                org_details = org_details_response.json()
                                organizations.append({
                                    "id": org_id,
                                    "name": org_details.get("localizedName", ""),
                                    "vanityName": org_details.get("vanityName", ""),
                                    "logoUrl": org_details.get("logoV2", {}).get("original", ""),
                                    "type": "Company"
                                })

        # Create accounts list with both personal and organization accounts
        accounts = [{
            "id": user_data.get("sub") or profile_data.get("id"),
            "firstName": user_data.get("given_name", ""),
            "lastName": user_data.get("family_name", ""),
            "email": user_data.get("email"),
            "profilePicture": profile_picture_url,
            "type": "Personal"
        }]

        # Add organization accounts
        accounts.extend(organizations)

        return {
            "accessToken": access_token,
            "profileData": {
                "id": user_data.get("sub") or profile_data.get("id"),
                "firstName": user_data.get("given_name", ""),
                "lastName": user_data.get("family_name", ""),
                "email": user_data.get("email"),
                "profilePicture": profile_picture_url,
                "accounts": accounts
            }
        }
    except Exception as e:
        logger.exception("Error in LinkedIn callback")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/share")
async def share_post(request: Request):
    data = await request.json()
    account_id = data.get("accountId")
    content = data.get("content")

    if not account_id or not content:
        raise HTTPException(
            status_code=400, detail="Account ID and content are required")

    headers = {
        "Authorization": f"Bearer {data.get('accessToken')}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    response = requests.post(
        LINKEDIN_SHARE_URL,
        headers=headers,
        json=content
    )

    if not response.ok:
        raise HTTPException(
            status_code=400, detail=f"Failed to post: {response.text}")

    return {"success": True}


@router.post("/revoke")
async def revoke_access(request: Request):
    try:
        data = await request.json()
        access_token = data.get("accessToken")

        if not access_token:
            raise HTTPException(
                status_code=400, detail="Access token is required")

        # Revoke the token with LinkedIn
        revoke_response = requests.post(
            "https://www.linkedin.com/oauth/v2/revoke",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "token": access_token
            }
        )

        # If token is already invalid/expired/revoked, consider it a success
        if not revoke_response.ok:
            error_data = revoke_response.json()
            if error_data.get("error") == "invalid_grant":
                return {"success": True, "message": "Token already expired or revoked"}
            
            logger.error(
                f"Token revocation failed: {revoke_response.status_code} - {revoke_response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to revoke token: {revoke_response.text}"
            )

        return {"success": True, "message": "Token successfully revoked"}
    except Exception as e:
        logger.exception("Error in revoke_access")
        raise HTTPException(status_code=400, detail=str(e))
