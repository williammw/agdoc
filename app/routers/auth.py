from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import HTTPBearer
from firebase_admin import auth

from app.dependencies.auth import get_current_user, get_current_user_token
from app.utils.database import get_db, update_user_by_firebase_uid, get_user_by_firebase_uid, create_user
from app.models.users import UserUpdate, UserResponse, UserWithInfo

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    # Remove the global dependency to avoid double validation
    # dependencies=[Depends(HTTPBearer())],
)

# Create database dependencies
db_admin = get_db(admin_access=True)
db_standard = get_db(admin_access=False)

@router.get("/me", response_model=UserWithInfo)
async def get_me(
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
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

# Generic OAuth processing function to avoid code duplication
async def process_oauth_authentication(
    provider: str,
    email: str,
    name: Optional[str] = None,
    picture: Optional[str] = None,
    provider_account_id: Optional[str] = None,
    supabase = None
):
    """
    Process OAuth authentication for any provider
    
    This function handles the common parts of the OAuth flow for all providers.
    """
    try:
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email is required for {provider} authentication"
            )
            
        # Look up the user by email in Firebase Auth
        try:
            # Check if user already exists in Firebase by email
            try:
                user_record = auth.get_user_by_email(email)
                firebase_uid = user_record.uid
                
                # Update user profile if needed
                needs_update = False
                update_args = {}
                
                if name and user_record.display_name != name:
                    update_args["display_name"] = name
                    needs_update = True
                    
                if picture and user_record.photo_url != picture:
                    update_args["photo_url"] = picture
                    needs_update = True
                
                if needs_update:
                    auth.update_user(firebase_uid, **update_args)
                    print(f"Updated Firebase user profile for {email}")
                
            except auth.UserNotFoundError:
                # User doesn't exist yet, create them
                user_record = auth.create_user(
                    email=email,
                    email_verified=True,  # OAuth emails are already verified
                    display_name=name or "",
                    photo_url=picture or "",
                    provider_id=f"{provider}.com"
                )
                firebase_uid = user_record.uid
                print(f"Created new Firebase user for {email}")
            
            # Get or create user in our database
            db_user = await get_user_by_firebase_uid(supabase, firebase_uid)
            
            if not db_user:
                # Create new user in our database
                user_data = {
                    "firebase_uid": firebase_uid,
                    "email": email,
                    "email_verified": True,
                    "auth_provider": f"{provider}.com",
                    "full_name": name or "",
                    "avatar_url": picture or "",
                }
                
                db_user = await create_user(supabase, user_data)
                print(f"Created new user in database for {email}")
            else:
                # Update user profile in our database if needed
                needs_update = False
                update_data = {}
                
                if name and db_user.get("full_name") != name:
                    update_data["full_name"] = name
                    needs_update = True
                    
                if picture and db_user.get("avatar_url") != picture:
                    update_data["avatar_url"] = picture
                    needs_update = True
                
                if provider_account_id:
                    update_data[f"{provider}_id"] = provider_account_id
                    needs_update = True
                
                if needs_update:
                    await update_user_by_firebase_uid(supabase, firebase_uid, update_data)
                    print(f"Updated user profile in database for {email}")
            
            # Create a custom token for the client
            custom_token = auth.create_custom_token(firebase_uid)
            
            # Return comprehensive data for the frontend
            return {
                "firebase_token": custom_token.decode('utf-8'),
                "firebase_uid": firebase_uid,
                "user_id": db_user["id"],
                "email": db_user["email"],
                "full_name": db_user.get("full_name", ""),
                "avatar_url": db_user.get("avatar_url", ""),
                "email_verified": True,
                "auth_provider": f"{provider}.com"
            }
            
        except Exception as firebase_error:
            print(f"Firebase authentication error: {firebase_error}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Failed to authenticate with {provider}: {str(firebase_error)}"
            )
            
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"OAuth error with {provider}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process {provider} authentication: {str(e)}"
        )

@router.post("/oauth/google")
async def google_oauth(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process Google OAuth authentication
    
    This endpoint receives the Google OAuth tokens from the frontend and
    either finds an existing user or creates a new one, then returns a
    Firebase custom token for continued authentication.
    """
    try:
        # Extract tokens and user info from request body
        id_token = data.get("id_token")
        access_token = data.get("access_token")
        email = data.get("email")
        name = data.get("name") 
        picture = data.get("picture")
        
        if not email:
            # Try to extract email from the token if not provided directly
            try:
                # This is a simplified JWT parser to extract the payload without verification
                # We're not using this for authentication, just to extract the email
                if id_token and '.' in id_token:
                    token_parts = id_token.split('.')
                    if len(token_parts) >= 2:
                        import base64
                        import json
                        padded = token_parts[1] + '=' * (4 - len(token_parts[1]) % 4)
                        payload = json.loads(base64.b64decode(padded).decode('utf-8'))
                        email = payload.get('email')
                        name = name or payload.get('name')
                        picture = picture or payload.get('picture')
                else:
                    print("Invalid token format, cannot extract email")
            except Exception as e:
                print(f"Error extracting info from token: {e}")
                # Continue with the flow, we'll check if email is provided below
        
        return await process_oauth_authentication(
            provider="google",
            email=email,
            name=name,
            picture=picture,
            provider_account_id=data.get("provider_account_id"),
            supabase=supabase
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise

@router.post("/oauth/facebook")
async def facebook_oauth(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process Facebook OAuth authentication
    
    This endpoint receives the Facebook OAuth tokens from the frontend and
    either finds an existing user or creates a new one, then returns a
    Firebase custom token for continued authentication.
    """
    try:
        # Extract tokens and user info from request body
        access_token = data.get("access_token")
        email = data.get("email")
        name = data.get("name") 
        picture = data.get("picture")
        provider_account_id = data.get("provider_account_id")
        
        if not email and access_token:
            # Try to fetch user data from Facebook Graph API
            try:
                import requests
                # Basic profile fields
                fields = "id,name,email,picture"
                graph_url = f"https://graph.facebook.com/me?fields={fields}&access_token={access_token}"
                
                response = requests.get(graph_url)
                if response.status_code == 200:
                    user_data = response.json()
                    email = email or user_data.get("email")
                    name = name or user_data.get("name")
                    provider_account_id = provider_account_id or user_data.get("id")
                    if "picture" in user_data and "data" in user_data["picture"]:
                        picture = picture or user_data["picture"]["data"].get("url")
                else:
                    print(f"Failed to fetch Facebook user data: {response.text}")
            except Exception as e:
                print(f"Error fetching user data from Facebook: {e}")
        
        return await process_oauth_authentication(
            provider="facebook",
            email=email,
            name=name,
            picture=picture,
            provider_account_id=provider_account_id,
            supabase=supabase
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise

@router.post("/oauth/twitter")
async def twitter_oauth(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process Twitter OAuth authentication
    
    This endpoint receives the Twitter OAuth tokens from the frontend and
    either finds an existing user or creates a new one, then returns a
    Firebase custom token for continued authentication.
    """
    try:
        # Extract tokens and user info from request body
        access_token = data.get("access_token")
        oauth_token = data.get("oauth_token")
        oauth_token_secret = data.get("oauth_token_secret")
        email = data.get("email")
        name = data.get("name") 
        picture = data.get("picture")
        provider_account_id = data.get("provider_account_id")
        
        # Note: Twitter OAuth sometimes doesn't provide email directly
        # For a production app, you would need to request email access
        # and handle cases where email isn't provided
        
        if not email:
            email = f"{provider_account_id}@twitter.placeholder.com"
        
        return await process_oauth_authentication(
            provider="twitter",
            email=email,
            name=name,
            picture=picture,
            provider_account_id=provider_account_id,
            supabase=supabase
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise

@router.post("/oauth/linkedin")
async def linkedin_oauth(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process LinkedIn OAuth authentication
    
    This endpoint receives the LinkedIn OAuth tokens from the frontend and
    either finds an existing user or creates a new one, then returns a
    Firebase custom token for continued authentication.
    """
    try:
        # Extract tokens and user info from request body
        access_token = data.get("access_token")
        email = data.get("email")
        name = data.get("name") 
        picture = data.get("picture")
        provider_account_id = data.get("provider_account_id")
        
        if not email and access_token:
            # Try to fetch user data from LinkedIn API
            try:
                import requests
                # LinkedIn API endpoints
                profile_url = "https://api.linkedin.com/v2/me"
                email_url = "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))"
                
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                
                # Get basic profile
                profile_response = requests.get(profile_url, headers=headers)
                if profile_response.status_code == 200:
                    profile_data = profile_response.json()
                    provider_account_id = provider_account_id or profile_data.get("id")
                    name = name or f"{profile_data.get('localizedFirstName', '')} {profile_data.get('localizedLastName', '')}"
                
                # Get email if available
                email_response = requests.get(email_url, headers=headers)
                if email_response.status_code == 200:
                    email_data = email_response.json()
                    if "elements" in email_data and len(email_data["elements"]) > 0:
                        email = email or email_data["elements"][0]["handle~"]["emailAddress"]
                
            except Exception as e:
                print(f"Error fetching user data from LinkedIn: {e}")
        
        # LinkedIn doesn't always provide email through the API
        if not email and provider_account_id:
            email = f"{provider_account_id}@linkedin.placeholder.com"
        
        return await process_oauth_authentication(
            provider="linkedin",
            email=email,
            name=name,
            picture=picture,
            provider_account_id=provider_account_id,
            supabase=supabase
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise

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
    supabase = Depends(db_admin)
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
    supabase = Depends(db_admin)
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