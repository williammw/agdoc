from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import HTTPBearer

from app.dependencies.auth import get_current_user, get_current_user_token
from app.utils.database import get_database, update_user_by_firebase_uid
from app.models.users import UserUpdate, UserResponse, UserWithInfo

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    # Remove the global dependency to avoid double validation
    # dependencies=[Depends(HTTPBearer())],
)

@router.get("/me", response_model=UserWithInfo)
async def get_me(
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(get_database)
):
    """
    Get the current authenticated user's complete profile with user info
    
    Returns a combined user profile with account information in a single request.
    """
    try:
        # Get user info from the database
        response = supabase.table('user_info').select('*').eq('user_id', current_user["id"]).execute()
        
        # Combine user and user_info
        result = dict(current_user)
        
        if response.data and len(response.data) > 0:
            result["user_info"] = response.data[0]
        else:
            # Create user_info if it doesn't exist yet
            create_response = supabase.table('user_info').insert({
                'user_id': current_user["id"],
                'plan_type': 'free',
                'monthly_post_quota': 10,
                'remaining_posts': 10
            }).execute()
            
            if create_response.data and len(create_response.data) > 0:
                result["user_info"] = create_response.data[0]
        
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user info: {str(e)}"
        )

@router.post("/token-refresh")
async def refresh_token(
    token_data: Dict[str, Any] = Depends(get_current_user_token)
):
    """
    Verify and refresh the authentication token
    
    This endpoint validates the current token and returns user identity details.
    It can be used by the frontend to verify that a cached token is still valid.
    """
    return {
        "valid": True,
        "user_id": token_data.get("uid"),
        "email": token_data.get("email"),
        "email_verified": token_data.get("email_verified", False),
        "auth_provider": token_data.get("firebase", {}).get("sign_in_provider", "email"),
    }

@router.put("/profile", response_model=UserResponse)
async def update_profile(
    updates: UserUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(get_database)
):
    """
    Update the current user's profile information
    
    Enhanced profile update endpoint with validation and conflict detection.
    """
    try:
        # Filter out None values
        update_data = {k: v for k, v in updates.dict().items() if v is not None}
        
        if not update_data:
            return current_user
        
        # Check for username conflicts if updating username
        if "username" in update_data:
            username_check = supabase.table('users').select('id').eq('username', update_data["username"]).neq('id', current_user["id"]).execute()
            
            if username_check.data and len(username_check.data) > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username already taken"
                )
        
        # Update user
        updated_user = await update_user_by_firebase_uid(
            supabase, 
            current_user["firebase_uid"], 
            update_data
        )
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user profile"
            )
        
        return updated_user
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating profile: {str(e)}"
        )

@router.get("/sync")
async def sync_profile(
    current_user: Dict[str, Any] = Depends(get_current_user),
    token_data: Dict[str, Any] = Depends(get_current_user_token),
    supabase = Depends(get_database)
):
    """
    Synchronize the user profile with Firebase data
    
    Updates local user profile with any changes from Firebase authentication.
    """
    try:
        # Extract Firebase user data
        firebase_data = {
            "email": token_data.get("email", ""),
            "email_verified": token_data.get("email_verified", False),
            "full_name": token_data.get("name", current_user.get("full_name", "")),
            "avatar_url": token_data.get("picture", current_user.get("avatar_url", "")),
        }
        
        # Only update fields that have changed
        update_data = {}
        for key, value in firebase_data.items():
            if key in current_user and current_user[key] != value and value:
                update_data[key] = value
        
        if not update_data:
            return {"synced": False, "message": "No changes needed"}
        
        # Update user with Firebase data
        updated_user = await update_user_by_firebase_uid(
            supabase, 
            current_user["firebase_uid"], 
            update_data
        )
        
        if updated_user:
            return {
                "synced": True,
                "updated_fields": list(update_data.keys()),
                "user": updated_user
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to sync user profile"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error syncing profile: {str(e)}"
        ) 