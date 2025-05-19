from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from typing import Dict, Any, List, Optional
from app.dependencies.auth import get_current_user
from app.models.social_connections import SocialConnection, SocialConnectionCreate
from app.utils.database import get_database
from app.utils.encryption import encrypt_token, decrypt_token

router = APIRouter(
    prefix="/api/v1/social-connections",
    tags=["social_connections"],
)

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
    
    try:
        # Check if connection already exists
        response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).eq('provider', data.provider).execute()
        
        if response.data and len(response.data) > 0:
            # Update existing connection
            existing_connection = response.data[0]
            db.table('social_connections').update({
                'access_token': encrypted_access_token,
                'refresh_token': encrypted_refresh_token,
                'expires_at': data.expires_at,
                'provider_account_id': data.provider_account_id,
                'updated_at': 'now()'
            }).eq('id', existing_connection['id']).execute()
        else:
            # Create new connection
            db.table('social_connections').insert({
                'user_id': int(current_user["id"]),  # Ensure user_id is an integer
                'provider': data.provider,
                'provider_account_id': data.provider_account_id,
                'access_token': encrypted_access_token,
                'refresh_token': encrypted_refresh_token,
                'expires_at': data.expires_at
            }).execute()
        
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
        if include_tokens:
            # Include sensitive data but decrypt it first
            response = db.table('social_connections').select('*').eq('user_id', current_user["id"]).execute()
            
            if response.data:
                # Decrypt tokens before returning
                for conn in response.data:
                    if conn.get('access_token'):
                        conn['access_token'] = decrypt_token(conn['access_token'])
                    if conn.get('refresh_token'):
                        conn['refresh_token'] = decrypt_token(conn['refresh_token'])
            
            return response.data if response.data else []
        else:
            # Regular behavior without tokens for security
            response = db.table('social_connections').select('provider, provider_account_id, created_at, expires_at').eq('user_id', current_user["id"]).execute()
            return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching connections: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve social connections: {str(e)}")

@router.get("/token/{provider}")
async def get_token(
    provider: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db = Depends(get_database)
):
    """Get decrypted access token for a specific provider"""
    try:
        # Get the token for the specified provider
        response = db.table('social_connections').select('access_token, refresh_token, expires_at').eq('user_id', current_user["id"]).eq('provider', provider).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail=f"No {provider} connection found")
        
        connection = response.data[0]
        
        # Decrypt tokens
        access_token = decrypt_token(connection['access_token']) if connection.get('access_token') else None
        refresh_token = decrypt_token(connection['refresh_token']) if connection.get('refresh_token') else None
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": connection.get('expires_at')
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving token: {e}")
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