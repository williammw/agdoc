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
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Define redirect URIs for different environments
REDIRECT_URIS = {
    "production": "https://www.multivio.com/linkedin/callback",
    "development": "https://347b-185-245-239-66.ngrok-free.app/linkedin/callback", 
    "local": "http://localhost:5173/linkedin/callback"
}

# Get the appropriate redirect URI based on environment
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", REDIRECT_URIS.get(ENVIRONMENT, REDIRECT_URIS["development"]))

logger.info(f"Using LinkedIn Redirect URI: {REDIRECT_URI}")

# LinkedIn API endpoints
LINKEDIN_ENDPOINTS = {
    "auth": "https://www.linkedin.com/oauth/v2/authorization",
    "token": "https://www.linkedin.com/oauth/v2/accessToken",
    "user_info": "https://api.linkedin.com/v2/userinfo",
    "profile": "https://api.linkedin.com/v2/me",
    "profile_picture": "https://api.linkedin.com/v2/me?projection=(id,profilePicture(displayImage~:playableStreams))",
    "share": "https://api.linkedin.com/v2/ugcPosts",
    "organizations": "https://api.linkedin.com/v2/organizationalEntityAcls",
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
    try:
        # Get origin from request headers to determine the correct redirect URI
        origin = request.headers.get("origin", "")
        logger.debug(f"Request origin: {origin}")
        
        # Determine environment based on origin
        current_env = "production" if "multivio.com" in origin else "development"
        if "localhost" in origin:
            current_env = "local"
            
        # Use the appropriate redirect URI
        current_redirect_uri = REDIRECT_URIS.get(current_env, REDIRECT_URI)
        logger.debug(f"Using redirect URI for {current_env}: {current_redirect_uri}")
        
        state = secrets.token_urlsafe(32)
        auth_params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": current_redirect_uri,
            "scope": "openid profile email w_member_social r_organization_admin w_organization_social r_organization_social rw_organization_admin",
            "state": state
        }

        auth_url = f"{LINKEDIN_ENDPOINTS['auth']}?{urlencode(auth_params)}"
        logger.debug(f"Generated LinkedIn auth URL with redirect_uri: {current_redirect_uri}")
        return {"authUrl": auth_url, "state": state}
    except Exception as e:
        logger.exception("Error in initialize_linkedin_auth")
        raise HTTPException(status_code=500, detail=str(e))

@router.api_route("/callback", methods=["GET", "POST"])
async def linkedin_callback(request: Request):
    try:
        # Extract code and state from POST body (sent by frontend)
        data = await request.json()
        code = data.get("code")
        state = data.get("state")
        
        # Get origin from request headers to determine the correct redirect URI
        origin = request.headers.get("origin", "")
        logger.debug(f"Callback request origin: {origin}")
        
        # Determine environment based on origin
        current_env = "production" if "multivio.com" in origin else "development"
        if "localhost" in origin:
            current_env = "local"
            
        # Use the appropriate redirect URI
        current_redirect_uri = REDIRECT_URIS.get(current_env, REDIRECT_URI)
        logger.debug(f"Using callback redirect URI for {current_env}: {current_redirect_uri}")

        logger.debug(f"Callback received - code: {code}, state: {state}")

        if not code:
            raise HTTPException(status_code=400, detail="Authorization code is required")

        # Exchange code for access token
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": current_redirect_uri,  # Must match the auth redirect_uri
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }
        
        logger.debug(f"Token request data: {token_data}")
        
        token_response = requests.post(
            LINKEDIN_ENDPOINTS['token'],
            data=token_data
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

        # Get organizations/company pages with detailed info
        logger.debug("Fetching organizations...")
        org_response = requests.get(
            f"{LINKEDIN_ENDPOINTS['organizations']}?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED&count=100",
            headers=headers
        )
        logger.debug(f"Organizations response: {org_response.text}")
        
        organizations = []
        company_pages = []
        
        if org_response.ok:
            org_data = org_response.json()
            logger.debug(f"Found {len(org_data.get('elements', []))} organizations")
            
            for element in org_data.get("elements", []):
                org_id = element.get("organizationalTarget")
                if not org_id:
                    continue

                # Extract numeric ID from URN
                numeric_id = org_id.split(":")[-1] if org_id.startswith("urn:li:organization:") else org_id
                
                logger.debug(f"Fetching details for org {numeric_id}")
                # Get detailed organization info
                org_details_response = requests.get(
                    f"https://api.linkedin.com/v2/organizations/{numeric_id}",
                    headers=headers
                )
                
                if not org_details_response.ok:
                    logger.error(f"Failed to get org details for {numeric_id}: {org_details_response.text}")
                    continue

                org_details = org_details_response.json()
                logger.debug(f"Organization details: {org_details}")

                # Get organization/page followers
                followers_response = requests.get(
                    f"https://api.linkedin.com/v2/networkSizes/{numeric_id}?edgeType=CompanyFollowedByMember",
                    headers=headers
                )
                follower_count = followers_response.json().get("firstDegreeSize", 0) if followers_response.ok else 0

                page_info = {
                    "id": numeric_id,
                    "name": org_details.get("localizedName", ""),
                    "vanityName": org_details.get("vanityName", ""),
                    "description": org_details.get("localizedDescription", ""),
                    "websiteUrl": org_details.get("localizedWebsite", ""),
                    "logoUrl": org_details.get("logoV2", {}).get("original", ""),
                    "industry": org_details.get("localizedIndustry", ""),
                    "staffCount": org_details.get("staffCount", 0),
                    "followerCount": follower_count,
                    "type": "Company",
                    "role": element.get("role", ""),
                    "permissions": {
                        "canPost": element.get("role") in ["ADMINISTRATOR", "CONTENT_ADMIN"],
                        "canManage": element.get("role") == "ADMINISTRATOR"
                    }
                }

                logger.debug(f"Adding page info: {page_info}")
                organizations.append(page_info)
                company_pages.append(page_info)

        # Construct response with both profile and pages
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
            },
            "companyPages": company_pages
        }

    except Exception as e:
        logger.exception("Error in LinkedIn callback")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/share")
async def share_post(request: Request):
    data = await request.json()
    if not all(k in data for k in ["accountId", "content", "accessToken"]):
        raise HTTPException(status_code=400, detail="Account ID, content, and access token are required")

    # Modify the content structure based on account type
    content = data['content']
    account_type = content['author'].split(':')[2].lower()  # person or organization
    
    if account_type == 'person':
        # For personal accounts, use person URN format
        post_content = {
            "author": f"urn:li:person:{data['accountId']}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": content['specificContent']['com.linkedin.ugc.ShareContent']['shareCommentary']['text']
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
    else:
        # For company accounts, use organization URN format
        post_content = content

    response = requests.post(
        LINKEDIN_ENDPOINTS['share'],
        headers=get_linkedin_headers(data['accessToken'], include_restli=True),
        json=post_content
    )

    if not response.ok:
        logger.error(f"Share failed: {response.text}")
        raise HTTPException(status_code=response.status_code, detail=f"Failed to post: {response.text}")
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
