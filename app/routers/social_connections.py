from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from typing import Dict, Any, List, Optional, Union
from app.dependencies.auth import get_current_user
from app.models.social_connections import SocialConnection, SocialConnectionCreate
from app.utils.database import get_database
from app.utils.encryption import encrypt_token, decrypt_token
from pydantic import BaseModel
from datetime import datetime, timezone
from fastapi.responses import JSONResponse
import httpx
import json
import logging
from supabase import Client as SupabaseClient

# Configure logger for this module
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/social-connections",
    tags=["social_connections"],
)

class InstagramAccount(BaseModel):
    id: str
    name: str
    username: str
    profile_picture_url: Optional[str] = None
    access_token: Optional[str] = None

class InstagramAccountsRequest(BaseModel):
    accounts: List[InstagramAccount]

class LinkedInProfile(BaseModel):
    id: str
    firstName: str
    lastName: str
    profilePicture: Optional[str] = None
    vanityName: Optional[str] = None
    headline: Optional[str] = None
    company: Optional[str] = None
    companyId: Optional[str] = None

class LinkedInProfileRequest(BaseModel):
    profile: LinkedInProfile

class LinkedInPostRequest(BaseModel):
    content: str
    imageUrl: Optional[str] = None
    articleUrl: Optional[str] = None

class ThreadsProfile(BaseModel):
    id: str
    username: str
    name: Optional[str] = None
    bio: Optional[str] = None
    profile_picture_url: Optional[str] = None
    follower_count: Optional[int] = None
    following_count: Optional[int] = None

class ThreadsProfileRequest(BaseModel):
    profile: ThreadsProfile

# Helper function to decrypt data (for backward compatibility)
def decrypt_data(encrypted_data):
    if not encrypted_data:
        return None
    return decrypt_token(encrypted_data)

@router.post("/store-token")
async def store_token(
    data: SocialConnectionCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Store social media OAuth token"""
    # Encrypt sensitive data
    encrypted_access_token = encrypt_token(data.access_token)
    encrypted_refresh_token = encrypt_token(data.refresh_token) if data.refresh_token else None
    
    # Format expires_at correctly - it could be a string, datetime, or None
    expires_at = None
    if data.expires_at:
        if isinstance(data.expires_at, str):
            try:
                # Try to parse as ISO format
                expires_at = datetime.fromisoformat(data.expires_at.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # Try to parse as timestamp
                    expires_at = datetime.fromtimestamp(int(data.expires_at), tz=timezone.utc)
                except (ValueError, TypeError):
                    # Keep as is if we can't parse
                    expires_at = data.expires_at
        elif isinstance(data.expires_at, datetime):
            # Convert datetime to ISO string to make it JSON serializable
            expires_at = data.expires_at.isoformat()
        else:
            # Convert to string - best approach for unknown type
            expires_at = str(data.expires_at)
    
    try:
        # Check if connection already exists
        response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).eq('provider', data.provider).execute()
        
        if response.data and len(response.data) > 0:
            # Update existing connection
            existing_connection = response.data[0]
            update_data = {
                'access_token': encrypted_access_token,
                'refresh_token': encrypted_refresh_token,
                'expires_at': expires_at,
                'provider_account_id': data.provider_account_id,
                'updated_at': 'now()'
            }
            
            # Add metadata if provided
            if data.profile_metadata:
                # Parse JSON string if needed
                try:
                    if isinstance(data.profile_metadata, str):
                        profile_data = json.loads(data.profile_metadata)
                    else:
                        profile_data = data.profile_metadata
                except (json.JSONDecodeError, TypeError):
                    profile_data = data.profile_metadata
                
                # If there's existing metadata, update it; otherwise create new
                if existing_connection.get('metadata'):
                    existing_metadata = existing_connection.get('metadata', {}) or {}
                    # For LinkedIn and Threads, store profile in metadata
                    if data.provider in ['linkedin', 'threads']:
                        existing_metadata['profile'] = profile_data
                    update_data['metadata'] = existing_metadata
                else:
                    # Create new metadata object
                    if data.provider in ['linkedin', 'threads']:
                        update_data['metadata'] = {'profile': profile_data}
            
            db.table('social_connections').update(update_data).eq('id', existing_connection['id']).execute()
        else:
            # Create new connection
            insert_data = {
                'user_id': int(current_user["id"]),  # Ensure user_id is an integer
                'provider': data.provider,
                'provider_account_id': data.provider_account_id,
                'access_token': encrypted_access_token,
                'refresh_token': encrypted_refresh_token,
                'expires_at': expires_at
            }
            
            # Add metadata if provided
            if data.profile_metadata:
                # Parse JSON string if needed
                try:
                    if isinstance(data.profile_metadata, str):
                        profile_data = json.loads(data.profile_metadata)
                    else:
                        profile_data = data.profile_metadata
                except (json.JSONDecodeError, TypeError):
                    profile_data = data.profile_metadata
                
                if data.provider in ['linkedin', 'threads']:
                    insert_data['metadata'] = {'profile': profile_data}
            
            db.table('social_connections').insert(insert_data).execute()
        
        return {"status": "success", "message": f"{data.provider} account connected successfully"}
    except Exception as e:
        print(f"Error storing token: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to store social media token: {str(e)}")

@router.get("/connections")
async def get_connections(
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database),
    include_tokens: bool = Query(False, description="Include decrypted access tokens in the response")
):
    """Get all social connections for the current user"""
    try:
        logger.info(f"Fetching connections for user {current_user.get('id')} with include_tokens={include_tokens}")
        
        if include_tokens:
            # Include sensitive data but decrypt it first
            response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).execute()
            
            if response.data:
                # Decrypt tokens before returning with proper error handling
                for conn in response.data:
                    logger.info(f"Processing connection: {conn.get('provider')} for user {current_user.get('id')}")
                    
                    # Safely decrypt access_token
                    if conn.get('access_token'):
                        try:
                            conn['access_token'] = decrypt_token(conn['access_token'])
                            logger.info(f"Successfully decrypted access_token for {conn.get('provider')}")
                        except Exception as e:
                            logger.error(f"Failed to decrypt access_token for {conn.get('provider')}: {str(e)}")
                            conn['access_token'] = None  # Set to None instead of failing
                    
                    # Safely decrypt refresh_token
                    if conn.get('refresh_token'):
                        try:
                            conn['refresh_token'] = decrypt_token(conn['refresh_token'])
                            logger.info(f"Successfully decrypted refresh_token for {conn.get('provider')}")
                        except Exception as e:
                            logger.error(f"Failed to decrypt refresh_token for {conn.get('provider')}: {str(e)}")
                            conn['refresh_token'] = None  # Set to None instead of failing
            
            return response.data if response.data else []
        else:
            # Regular behavior without tokens for security
            response = db.table('social_connections').select('provider, provider_account_id, created_at, expires_at, metadata').eq('user_id', current_user["id"]).execute()
            return response.data if response.data else []
            
    except Exception as e:
        logger.error(f"Error fetching connections for user {current_user.get('id')}: {str(e)}")
        logger.error(f"Exception type: {type(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve social connections: {str(e)}")

@router.get("/token/{provider}")
async def get_token(
    provider: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Get decrypted access token for a specific provider"""
    try:
        logger.info(f"Retrieving token for provider {provider} and user {current_user.get('id')}")
        
        # Get the token for the specified provider
        response = db.table('social_connections').select('access_token, refresh_token, expires_at').eq('user_id', current_user["id"]).eq('provider', provider).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail=f"No {provider} connection found")
        
        connection = response.data[0]
        
        # Safely decrypt tokens with error handling
        access_token = None
        refresh_token = None
        
        if connection.get('access_token'):
            try:
                access_token = decrypt_token(connection['access_token'])
                logger.info(f"Successfully decrypted access_token for {provider}")
            except Exception as e:
                logger.error(f"Failed to decrypt access_token for {provider}: {str(e)}")
                access_token = None
        
        if connection.get('refresh_token'):
            try:
                refresh_token = decrypt_token(connection['refresh_token'])
                logger.info(f"Successfully decrypted refresh_token for {provider}")
            except Exception as e:
                logger.error(f"Failed to decrypt refresh_token for {provider}: {str(e)}")
                refresh_token = None
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": connection.get('expires_at')
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving token for {provider}: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve token: {str(e)}")

@router.delete("/{provider}")
async def remove_connection(
    provider: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Remove a social connection"""
    try:
        # Check if connection exists
        response = db.table('social_connections').select('id').eq('user_id', current_user["id"]).eq('provider', provider).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail=f"No {provider} connection found")
        
        # Delete the connection
        db.table('social_connections').delete().eq('user_id', current_user["id"]).eq('provider', provider).execute()
        
        return {"status": "success", "message": f"{provider} connection removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error removing connection: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove social connection: {str(e)}")

@router.post("/store-facebook-pages")
async def store_facebook_pages(
    data: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Store Facebook pages data in the user's connection metadata"""
    try:
        # Get the Facebook connection
        response = db.table('social_connections').select('id').eq('user_id', current_user["id"]).eq('provider', 'facebook').execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="No Facebook connection found")
        
        connection_id = response.data[0]['id']
        
        # Update the connection with metadata (pages)
        db.table('social_connections').update({
            'metadata': {'pages': data.get('pages', [])}
        }).eq('id', connection_id).execute()
        
        return {"status": "success", "message": "Facebook pages stored successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error storing Facebook pages: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to store Facebook pages: {str(e)}")

@router.post("/store-instagram-accounts")
async def store_instagram_accounts(
    data: InstagramAccountsRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Store Instagram accounts linked to Facebook pages"""
    try:
        # Check if Facebook connection exists
        fb_response = db.table('social_connections').select('id, metadata').eq('user_id', current_user["id"]).eq('provider', 'facebook').execute()
        
        if not fb_response.data or len(fb_response.data) == 0:
            raise HTTPException(status_code=404, detail="No Facebook connection found")
        
        fb_connection_id = fb_response.data[0]['id']
        fb_metadata = fb_response.data[0].get('metadata', {}) or {}
        
        # Create or update Instagram metadata in the Facebook connection
        if not fb_metadata:
            fb_metadata = {}
            
        # Prepare accounts data for storage (remove access tokens)
        safe_accounts = []
        for account in data.accounts:
            safe_account = account.dict(exclude={'access_token'})
            safe_accounts.append(safe_account)
        
        # Store Instagram accounts in Facebook metadata
        fb_metadata['instagram_accounts'] = safe_accounts
        
        # Update Facebook connection with Instagram accounts
        db.table('social_connections').update({
            'metadata': fb_metadata
        }).eq('id', fb_connection_id).execute()
        
        # Next, check if we have Instagram as a provider
        ig_response = db.table('social_connections').select('id').eq('user_id', current_user["id"]).eq('provider', 'instagram').execute()
        
        # For Instagram accounts with tokens, store them individually with 'instagram' provider
        if data.accounts:
            for account in data.accounts:
                if account.access_token:
                    # Encrypt token
                    encrypted_token = encrypt_token(account.access_token)
                    
                    # Store as a separate Instagram connection or update existing
                    ig_exists = False
                    ig_id = None
                    
                    if ig_response.data:
                        for ig_conn in ig_response.data:
                            ig_conn_detail = db.table('social_connections').select('metadata').eq('id', ig_conn['id']).execute()
                            if ig_conn_detail.data and ig_conn_detail.data[0].get('metadata'):
                                if ig_conn_detail.data[0]['metadata'].get('instagram_id') == account.id:
                                    ig_exists = True
                                    ig_id = ig_conn['id']
                                    break
                    
                    # Prepare Instagram connection metadata
                    ig_metadata = {
                        'instagram_id': account.id,
                        'username': account.username,
                        'name': account.name,
                        'profile_picture_url': account.profile_picture_url
                    }
                    
                    if ig_exists and ig_id:
                        # Update existing Instagram connection
                        db.table('social_connections').update({
                            'access_token': encrypted_token,
                            'metadata': ig_metadata,
                            'updated_at': 'now()'
                        }).eq('id', ig_id).execute()
                    else:
                        # Create new Instagram connection
                        db.table('social_connections').insert({
                            'user_id': int(current_user["id"]),
                            'provider': 'instagram',
                            'provider_account_id': account.id,
                            'access_token': encrypted_token,
                            'metadata': ig_metadata
                        }).execute()
                        
        return {"status": "success", "message": f"Stored {len(data.accounts)} Instagram accounts"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error storing Instagram accounts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to store Instagram accounts: {str(e)}")

@router.get("/instagram/accounts")
async def get_instagram_accounts(
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Get all Instagram accounts for the current user"""
    try:
        # First check Facebook connection for Instagram accounts
        fb_response = db.table('social_connections').select('metadata').eq('user_id', current_user["id"]).eq('provider', 'facebook').execute()
        
        instagram_accounts = []
        
        # Process Facebook metadata for Instagram accounts
        if fb_response.data and len(fb_response.data) > 0:
            fb_conn = fb_response.data[0]
            if fb_conn.get('metadata') and fb_conn['metadata'].get('instagram_accounts'):
                instagram_accounts = fb_conn['metadata']['instagram_accounts']
        
        # Also check for direct Instagram connections
        ig_response = db.table('social_connections').select('provider_account_id, metadata').eq('user_id', current_user["id"]).eq('provider', 'instagram').execute()
        
        if ig_response.data and len(ig_response.data) > 0:
            for ig_conn in ig_response.data:
                if ig_conn.get('metadata'):
                    ig_id = ig_conn['provider_account_id']
                    
                    # Check if this account is already in our list
                    existing = next((acc for acc in instagram_accounts if acc.get('id') == ig_id), None)
                    
                    if not existing:
                        # Add this Instagram account to the list
                        instagram_accounts.append({
                            'id': ig_id,
                            'name': ig_conn['metadata'].get('name', 'Instagram Account'),
                            'username': ig_conn['metadata'].get('username', ''),
                            'profile_picture_url': ig_conn['metadata'].get('profile_picture_url')
                        })
        
        return instagram_accounts
    except Exception as e:
        print(f"Error fetching Instagram accounts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve Instagram accounts: {str(e)}")

@router.post("/store-linkedin-profile")
async def store_linkedin_profile(
    data: LinkedInProfileRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Store LinkedIn profile data"""
    try:
        # Get the LinkedIn connection
        response = db.table('social_connections').select('id').eq('user_id', current_user["id"]).eq('provider', 'linkedin').execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="No LinkedIn connection found")
        
        connection_id = response.data[0]['id']
        
        # Update the connection with metadata (LinkedIn profile)
        db.table('social_connections').update({
            'metadata': data.profile.dict()
        }).eq('id', connection_id).execute()
        
        return {"status": "success", "message": "LinkedIn profile stored successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error storing LinkedIn profile: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to store LinkedIn profile: {str(e)}")

@router.post("/linkedin/post")
async def post_to_linkedin(
    post_data: LinkedInPostRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Post content to LinkedIn"""
    try:
        # Get LinkedIn access token
        token_response = db.table('social_connections').select('access_token').eq('user_id', current_user["id"]).eq('provider', 'linkedin').execute()
        
        if not token_response.data or len(token_response.data) == 0:
            raise HTTPException(status_code=404, detail="No LinkedIn connection found")
        
        # Decrypt token
        access_token = decrypt_token(token_response.data[0]['access_token'])
        
        if not access_token:
            raise HTTPException(status_code=400, detail="Invalid LinkedIn access token")
        
        # Build LinkedIn share content
        share_content = {
            "author": f"urn:li:person:{current_user['id']}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": post_data.content
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
        
        # Add media if provided
        if post_data.imageUrl:
            share_content["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "IMAGE"
            share_content["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [{
                "status": "READY",
                "description": {
                    "text": "Image"
                },
                "media": post_data.imageUrl,
                "title": {
                    "text": "Image"
                }
            }]
        elif post_data.articleUrl:
            share_content["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "ARTICLE"
            share_content["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [{
                "status": "READY",
                "originalUrl": post_data.articleUrl
            }]
        
        # Post to LinkedIn API
        import requests
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        response = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=headers,
            json=share_content
        )
        
        if response.status_code not in [200, 201]:
            raise HTTPException(
                status_code=response.status_code, 
                detail=f"LinkedIn API error: {response.text}"
            )
        
        return {"status": "success", "message": "Posted to LinkedIn successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error posting to LinkedIn: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to post to LinkedIn: {str(e)}")

@router.get("/linkedin/profile")
async def get_linkedin_profile(
    current_user: dict = Depends(get_current_user), 
    db: SupabaseClient = Depends(get_database)
):
    try:
        response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).eq('provider', 'linkedin').execute()
        
        if not response.data or len(response.data) == 0:
            return JSONResponse(status_code=404, content={"message": "LinkedIn connection not found"})
        
        linkedin_connection = response.data[0]
        
        # Check if we have stored profile data in metadata
        if linkedin_connection.get('metadata') and linkedin_connection['metadata'].get('profile'):
            return linkedin_connection['metadata']['profile']
        
        # Return empty object if no profile found
        return {}
    except Exception as e:
        logger.error(f"Error retrieving LinkedIn profile: {str(e)}")
        return JSONResponse(status_code=500, content={"message": f"Internal server error: {str(e)}"})

@router.get("/linkedin/organizations")
async def get_linkedin_organizations(
    force: bool = False,
    company_id: str = None,
    current_user: dict = Depends(get_current_user), 
    db: SupabaseClient = Depends(get_database)
):
    try:
        # Get LinkedIn connection
        response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).eq('provider', 'linkedin').execute()
        
        if not response.data or len(response.data) == 0:
            return JSONResponse(status_code=404, content={"message": "LinkedIn connection not found"})
        
        linkedin_connection = response.data[0]
        access_token = decrypt_data(linkedin_connection['access_token'])
        
        # First try to get organizations from metadata if not forcing refresh
        if not force and linkedin_connection.get('metadata') and linkedin_connection['metadata'].get('organizations'):
            logger.info(f"Returning cached LinkedIn organizations for user {current_user['id']}")
            return linkedin_connection['metadata']['organizations']
        
        logger.info(f"Fetching fresh LinkedIn organizations for user {current_user['id']}")
        
        # If a specific company ID is provided, try to fetch just that one
        if company_id:
            try:
                org_detail_response = httpx.get(
                    f'https://api.linkedin.com/v2/organizations/{company_id}',
                    headers={
                        'Authorization': f'Bearer {access_token}',
                        'X-Restli-Protocol-Version': '2.0.0'
                    }
                )
                
                if org_detail_response.status_code == 200:
                    org_detail = org_detail_response.json()
                    
                    # Create organization object
                    organization = {
                        'id': org_detail.get('id'),
                        'name': org_detail.get('localizedName', 'LinkedIn Organization'),
                        'vanityName': org_detail.get('vanityName'),
                        'organizationType': org_detail.get('organizationType', {}).get('localizedName')
                    }
                    
                    # Try to get logo if available
                    try:
                        logo_response = httpx.get(
                            f'https://api.linkedin.com/v2/organizations/{company_id}/logoImage',
                            headers={
                                'Authorization': f'Bearer {access_token}',
                                'X-Restli-Protocol-Version': '2.0.0'
                            }
                        )
                        
                        if logo_response.status_code == 200:
                            logo_data = logo_response.json()
                            if logo_data and logo_data.get('displayImage') and logo_data['displayImage'].get('elements') and len(logo_data['displayImage']['elements']) > 0:
                                organization['logoUrl'] = logo_data['displayImage']['elements'][0]['identifiers'][0]['identifier']
                    except Exception as logo_err:
                        logger.error(f"Error fetching logo for specific organization {company_id}: {str(logo_err)}")
                    
                    # Get specific role for this organization
                    try:
                        role_response = httpx.get(
                            f'https://api.linkedin.com/v2/organizationAcls?q=organization&organization=urn:li:organization:{company_id}',
                            headers={
                                'Authorization': f'Bearer {access_token}',
                                'X-Restli-Protocol-Version': '2.0.0'
                            }
                        )
                        
                        if role_response.status_code == 200:
                            role_data = role_response.json()
                            if role_data.get('elements') and len(role_data['elements']) > 0:
                                organization['role'] = role_data['elements'][0].get('role', 'MEMBER')
                    except Exception as role_err:
                        logger.error(f"Error fetching role for specific organization {company_id}: {str(role_err)}")
                    
                    # Save as single item and return
                    metadata = linkedin_connection.get('metadata', {}) or {}
                    if not 'organizations' in metadata:
                        metadata['organizations'] = []
                    
                    # Replace if exists or add to list
                    found = False
                    for i, org in enumerate(metadata['organizations']):
                        if org.get('id') == organization['id']:
                            metadata['organizations'][i] = organization
                            found = True
                            break
                            
                    if not found:
                        metadata['organizations'].append(organization)
                    
                    # Update metadata in database
                    db.table('social_connections').update({
                        'metadata': metadata
                    }).eq('id', linkedin_connection['id']).execute()
                    
                    return [organization]
                else:
                    logger.error(f"Error fetching organization {company_id}: {org_detail_response.text}")
            except Exception as e:
                logger.error(f"Error processing specific organization {company_id}: {str(e)}")
        
        # If not in metadata, fetch from LinkedIn API
        orgs = []
        try:
            # Try to get organizations the user administers
            admin_response = httpx.get(
                'https://api.linkedin.com/v2/organizationAcls?q=roleAssignee&role=ADMINISTRATOR',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'X-Restli-Protocol-Version': '2.0.0'
                }
            )
            
            if admin_response.status_code == 200:
                admin_data = admin_response.json()
                logger.info(f"LinkedIn admin organizations response: {admin_data}")
                
                if admin_data.get('elements') and len(admin_data['elements']) > 0:
                    # Log exact URN structure for debugging
                    for element in admin_data['elements']:
                        if element.get('organization'):
                            logger.info(f"Organization URN structure: {element['organization']}")
                            
                    # Extract organization IDs from the response
                    org_ids = []
                    for element in admin_data['elements']:
                        if element.get('organization'):
                            org_id = element['organization'].split(':')[1]
                            org_ids.append(org_id)
                    
                    # Special handling for 105348666 if in the list
                    if '105348666' not in org_ids and company_id != '105348666':
                        org_ids.append('105348666')
                        logger.info("Adding organization ID 105348666 explicitly")
                    
                    # Fetch details for each organization
                    for org_id in org_ids:
                        org_detail_response = httpx.get(
                            f'https://api.linkedin.com/v2/organizations/{org_id}',
                            headers={
                                'Authorization': f'Bearer {access_token}',
                                'X-Restli-Protocol-Version': '2.0.0'
                            },
                            timeout=10.0  # Add timeout to prevent hanging
                        )
                        
                        if org_detail_response.status_code == 200:
                            org_detail = org_detail_response.json()
                            logger.info(f"Organization {org_id} details: {org_detail}")
                            
                            organization = {
                                'id': org_detail.get('id'),
                                'name': org_detail.get('localizedName', f'LinkedIn Organization {org_id}'),
                                'vanityName': org_detail.get('vanityName'),
                                'organizationType': org_detail.get('organizationType', {}).get('localizedName')
                            }
                            
                            # Try to get logo if available
                            try:
                                logo_response = httpx.get(
                                    f'https://api.linkedin.com/v2/organizations/{org_id}/logoImage',
                                    headers={
                                        'Authorization': f'Bearer {access_token}',
                                        'X-Restli-Protocol-Version': '2.0.0'
                                    },
                                    timeout=5.0  # Add timeout to prevent hanging
                                )
                                
                                if logo_response.status_code == 200:
                                    logo_data = logo_response.json()
                                    if logo_data and logo_data.get('displayImage') and logo_data['displayImage'].get('elements') and len(logo_data['displayImage']['elements']) > 0:
                                        organization['logoUrl'] = logo_data['displayImage']['elements'][0]['identifiers'][0]['identifier']
                                        logger.info(f"Found logo for organization {org_id}")
                            except Exception as logo_err:
                                logger.error(f"Error fetching logo for organization {org_id}: {str(logo_err)}")
                            
                            orgs.append(organization)
                    
            
            # Fallback: Try alternate endpoint for organizations
            if not orgs or (force and '105348666' not in [org.get('id') for org in orgs]):
                logger.info("No organizations found via administrator route, trying organizational entity endpoint")
                
                try:
                    # Try adding organization 105348666 explicitly
                    org_id = '105348666'
                    org_detail_response = httpx.get(
                        f'https://api.linkedin.com/v2/organizations/{org_id}',
                        headers={
                            'Authorization': f'Bearer {access_token}',
                            'X-Restli-Protocol-Version': '2.0.0'
                        },
                        timeout=10.0
                    )
                    
                    if org_detail_response.status_code == 200:
                        org_detail = org_detail_response.json()
                        logger.info(f"Successfully fetched organization 105348666: {org_detail}")
                        
                        # First try to fetch with specialized organization info endpoint
                        try:
                            # This endpoint provides more detailed company info
                            company_info_response = httpx.get(
                                f'https://api.linkedin.com/v2/organizations/{org_id}?projection=(localizedName,vanityName,localizedDescription,logoImage,organizationType)',
                                headers={
                                    'Authorization': f'Bearer {access_token}',
                                    'X-Restli-Protocol-Version': '2.0.0'
                                },
                                timeout=10.0
                            )
                            
                            if company_info_response.status_code == 200:
                                company_info = company_info_response.json()
                                logger.info(f"Got detailed company info for 105348666: {company_info}")
                                
                                # Use the detailed company info to build organization data
                                organization = {
                                    'id': org_id,
                                    'name': company_info.get('localizedName', org_detail.get('localizedName', 'Your LinkedIn Company')),
                                    'vanityName': company_info.get('vanityName', org_detail.get('vanityName')),
                                    'organizationType': (company_info.get('organizationType') or {}).get('localizedName'),
                                    'description': company_info.get('localizedDescription'),
                                    'role': 'ADMINISTRATOR'  # Assume admin role for specifically targeted page
                                }
                                
                                # Get logo directly from the projection if available
                                if company_info.get('logoImage') and company_info['logoImage'].get('vectorImage'):
                                    vector_image = company_info['logoImage']['vectorImage']
                                    if vector_image.get('rootUrl') and vector_image.get('artifacts') and len(vector_image['artifacts']) > 0:
                                        artifact = vector_image['artifacts'][0]  # Use the first artifact
                                        logo_url = f"{vector_image['rootUrl']}{artifact['fileIdentifyingUrlPathSegment']}"
                                        organization['logoUrl'] = logo_url
                                
                            else:
                                logger.warning(f"Failed to get detailed company info: {company_info_response.text}")
                                # Fall back to basic organization details
                                organization = {
                                    'id': org_id,
                                    'name': org_detail.get('localizedName', 'Your LinkedIn Company'),
                                    'vanityName': org_detail.get('vanityName'),
                                    'organizationType': (org_detail.get('organizationType') or {}).get('localizedName'),
                                    'role': 'ADMINISTRATOR'  # Assume admin role for specifically targeted page
                                }
                        except Exception as company_info_err:
                            logger.error(f"Error fetching detailed company info: {company_info_err}")
                            # Fall back to basic organization details
                            organization = {
                                'id': org_id,
                                'name': org_detail.get('localizedName', 'Your LinkedIn Company'),
                                'vanityName': org_detail.get('vanityName'),
                                'organizationType': (org_detail.get('organizationType') or {}).get('localizedName'),
                                'role': 'ADMINISTRATOR'  # Assume admin role for specifically targeted page
                            }
                        
                        # Try to get logo if needed (if not already set)
                        if not organization.get('logoUrl'):
                            try:
                                logo_response = httpx.get(
                                    f'https://api.linkedin.com/v2/organizations/{org_id}/logoImage',
                                    headers={
                                        'Authorization': f'Bearer {access_token}',
                                        'X-Restli-Protocol-Version': '2.0.0'
                                    },
                                    timeout=5.0
                                )
                                
                                if logo_response.status_code == 200:
                                    logo_data = logo_response.json()
                                    if logo_data and logo_data.get('displayImage') and logo_data['displayImage'].get('elements') and len(logo_data['displayImage']['elements']) > 0:
                                        organization['logoUrl'] = logo_data['displayImage']['elements'][0]['identifiers'][0]['identifier']
                            except Exception as logo_err:
                                logger.error(f"Error fetching logo for organization 105348666: {str(logo_err)}")
                        
                        # Add to orgs list, replacing if exists or appending
                        found = False
                        for i, org in enumerate(orgs):
                            if org.get('id') == org_id:
                                orgs[i] = organization
                                found = True
                                break
                                
                        if not found:
                            orgs.append(organization)
                    else:
                        logger.error(f"Failed to fetch organization 105348666: {org_detail_response.text}")
                except Exception as e:
                    logger.error(f"Error processing organization 105348666: {str(e)}")
                
                # Try the standard entity endpoint as well
                alt_response = httpx.get(
                    'https://api.linkedin.com/v2/organizationalEntityAcls?q=roleAssignee',
                    headers={
                        'Authorization': f'Bearer {access_token}',
                        'X-Restli-Protocol-Version': '2.0.0'
                    },
                    timeout=10.0
                )
                
                if alt_response.status_code == 200:
                    alt_data = alt_response.json()
                    logger.info(f"LinkedIn organizational entity response: {alt_data}")
                    
                    if alt_data.get('elements') and len(alt_data['elements']) > 0:
                        # Extract organization IDs
                        org_ids = []
                        for acl in alt_data['elements']:
                            if acl.get('organizationalEntity') and acl['organizationalEntity'].startswith('organization:'):
                                org_id = acl['organizationalEntity'].split(':')[1]
                                org_ids.append(org_id)
                        
                        # Fetch organization details
                        for org_id in org_ids:
                            # Skip if we already processed this org
                            if any(org.get('id') == org_id for org in orgs):
                                continue
                                
                            org_detail_response = httpx.get(
                                f'https://api.linkedin.com/v2/organizations/{org_id}',
                                headers={
                                    'Authorization': f'Bearer {access_token}',
                                    'X-Restli-Protocol-Version': '2.0.0'
                                },
                                timeout=10.0
                            )
                            
                            if org_detail_response.status_code == 200:
                                org_detail = org_detail_response.json()
                                organization = {
                                    'id': org_detail.get('id'),
                                    'name': org_detail.get('localizedName', f'LinkedIn Organization {org_id}'),
                                    'vanityName': org_detail.get('vanityName'),
                                    'organizationType': org_detail.get('organizationType', {}).get('localizedName')
                                }
                                orgs.append(organization)
            
            # Store organizations in metadata if found
            if orgs:
                metadata = linkedin_connection.get('metadata', {}) or {}
                metadata['organizations'] = orgs
                
                # Update metadata in database
                db.table('social_connections').update({
                    'metadata': metadata
                }).eq('id', linkedin_connection['id']).execute()
                
                logger.info(f"Updated LinkedIn organizations for user {current_user['id']}: {orgs}")
                
            return orgs
                
        except Exception as linkedin_err:
            logger.error(f"Error fetching LinkedIn organizations: {str(linkedin_err)}")
            return []
        
    except Exception as e:
        logger.error(f"Error retrieving LinkedIn organizations: {str(e)}")
        return JSONResponse(status_code=500, content={"message": f"Internal server error: {str(e)}"})

@router.get("/linkedin/test")
async def test_linkedin_connection(
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Test LinkedIn connection and API access"""
    try:
        # Get LinkedIn access token
        token_response = db.table('social_connections').select('access_token').eq('user_id', current_user["id"]).eq('provider', 'linkedin').execute()
        
        if not token_response.data or len(token_response.data) == 0:
            return {
                "connected": False,
                "message": "No LinkedIn connection found"
            }
        
        # Decrypt token
        access_token = decrypt_token(token_response.data[0]['access_token'])
        
        if not access_token:
            return {
                "connected": False,
                "message": "Invalid LinkedIn access token"
            }
        
        # Test LinkedIn API access
        import requests
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        # Simple API test - get basic profile
        response = requests.get(
            "https://api.linkedin.com/v2/me",
            headers=headers
        )
        
        if response.status_code != 200:
            return {
                "connected": False,
                "status_code": response.status_code,
                "message": f"LinkedIn API error: {response.text}"
            }
        
        profile_data = response.json()
        
        # Try to get email address as well
        email_response = requests.get(
            "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))",
            headers=headers
        )
        
        email_data = {}
        if email_response.status_code == 200:
            email_data = email_response.json()
        
        return {
            "connected": True,
            "message": "LinkedIn connection verified",
            "profile": profile_data,
            "email_data": email_data
        }
    except Exception as e:
        print(f"Error testing LinkedIn connection: {e}")
        return {
            "connected": False,
            "message": f"Error: {str(e)}"
        }

@router.get("/threads/profile")
async def get_threads_profile(
    force: bool = False,
    current_user: dict = Depends(get_current_user), 
    db: SupabaseClient = Depends(get_database)
):
    """Get Threads profile for the current user"""
    try:
        # Get the Threads connection
        response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).eq('provider', 'threads').execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="No Threads connection found")
        
        connection = response.data[0]
        
        # Check if we have profile data in metadata
        if not force and connection.get('metadata') and connection.get('metadata').get('profile'):
            logger.info("Returning cached Threads profile")
            return connection['metadata']['profile']
        
        # Decrypt access token
        access_token = decrypt_token(connection['access_token']) if connection.get('access_token') else None
        
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token available for Threads")
        
        # Fetch profile from Threads API
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            # Threads API URL - Using the Meta Graph API
            # Note: We use the Instagram API since Threads is built on Instagram's infrastructure
            api_url = f"https://graph.instagram.com/v18.0/me?fields=id,username,name,biography,profile_picture_url,followers_count,follows_count"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(api_url, headers=headers, timeout=15.0)
                
                if response.status_code == 200:
                    profile_data = response.json()
                    
                    # Transform the data to match our ThreadsProfile model
                    threads_profile = {
                        "id": profile_data.get("id"),
                        "username": profile_data.get("username"),
                        "name": profile_data.get("name"),
                        "bio": profile_data.get("biography"),
                        "profile_picture_url": profile_data.get("profile_picture_url"),
                        "follower_count": profile_data.get("followers_count"),
                        "following_count": profile_data.get("follows_count")
                    }
                    
                    # Update the metadata in the database
                    metadata = connection.get('metadata', {}) or {}
                    metadata['profile'] = threads_profile
                    
                    db.table('social_connections').update({
                        'metadata': metadata,
                        'updated_at': 'now()'
                    }).eq('id', connection['id']).execute()
                    
                    logger.info(f"Updated Threads profile for user {current_user['id']}")
                    return threads_profile
                else:
                    error_data = response.json() if response.headers.get("content-type") == "application/json" else {"message": response.text}
                    logger.error(f"Error fetching Threads profile: {error_data}")
                    raise HTTPException(status_code=response.status_code, detail=f"Error fetching Threads profile: {error_data}")
        
        except httpx.RequestError as e:
            logger.error(f"Error making request to Threads API: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error connecting to Threads API: {str(e)}")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving Threads profile: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve Threads profile: {str(e)}")

@router.post("/store-threads-profile")
async def store_threads_profile(
    data: ThreadsProfileRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Store Threads profile data"""
    try:
        # Get the Threads connection
        response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).eq('provider', 'threads').execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="No Threads connection found")
        
        connection = response.data[0]
        
        # Update the metadata with the new profile
        metadata = connection.get('metadata', {}) or {}
        metadata['profile'] = data.profile.dict()
        
        # Update the database
        db.table('social_connections').update({
            'metadata': metadata,
            'updated_at': 'now()'
        }).eq('id', connection['id']).execute()
        
        return {"status": "success", "message": "Threads profile stored successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error storing Threads profile: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to store Threads profile: {str(e)}")
