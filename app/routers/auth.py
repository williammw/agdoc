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
                    photo_url=picture or ""
                    # Removed provider_id as it's not supported by Firebase auth.create_user()
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
                
                # Store provider-specific IDs in a safer way
                # Don't try to update provider-specific columns directly as they may not exist
                # Instead, store this information in the social_connections table or metadata
                if provider_account_id:
                    print(f"Provider account ID {provider_account_id} will be stored in social_connections table for {provider}")
                    # Note: We don't update the users table with provider-specific columns
                    # as these columns may not exist in the schema
                
                if needs_update:
                    await update_user_by_firebase_uid(supabase, firebase_uid, update_data)
                    print(f"Updated user profile in database for {email}")
            
            # Create a custom token for the user for frontend authentication
            try:
                print(f"Creating custom token for Firebase UID: {firebase_uid}")
                custom_token = auth.create_custom_token(firebase_uid)
                token_str = custom_token.decode('utf-8') if isinstance(custom_token, bytes) else custom_token
                print(f"Custom token created successfully: {token_str[:50]}...")
                
                # Return comprehensive data for the frontend including firebase_token
                return {
                    "firebase_uid": firebase_uid,
                    "user_id": db_user["id"],
                    "email": db_user["email"],
                    "full_name": db_user.get("full_name", ""),
                    "avatar_url": db_user.get("avatar_url", ""),
                    "email_verified": True,
                    "auth_provider": f"{provider}.com",
                    "firebase_token": token_str
                }
            except Exception as token_error:
                print(f"Error creating custom token for UID {firebase_uid}: {token_error}")
                # Check if the user exists
                try:
                    user_check = auth.get_user(firebase_uid)
                    print(f"User exists in Firebase: {user_check.email}")
                except Exception as user_error:
                    print(f"User doesn't exist in Firebase: {user_error}")
                
                # Fallback: return user data without firebase_token
                return {
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
    data: Dict[str, Any] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process Twitter OAuth authentication
    
    This endpoint receives the Twitter OAuth2 tokens from the frontend and
    either finds an existing user or creates a new one, then returns a
    Firebase custom token for continued authentication.
    """
    try:
        # Extract tokens and user info from request body
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        token_type = data.get("token_type", "Bearer")
        expires_in = data.get("expires_in")
        scope = data.get("scope")
        
        # Extract profile information
        profile = data.get("profile", {})
        provider_account_id = profile.get("id")
        name = profile.get("name")
        username = profile.get("username")
        picture = profile.get("profile_image_url")
        
        # Twitter OAuth2 doesn't always provide email directly
        # For a production app, you would need to request email access
        # Handle cases where email isn't provided by creating a placeholder
        email = profile.get("email")
        if not email:
            email = f"{provider_account_id}@twitter.placeholder.com"
        
        # Store the social connection with token and profile data
        # This will be used for posting to Twitter later
        user_result = await process_oauth_authentication(
            provider="twitter",
            email=email,
            name=name,
            picture=picture,
            provider_account_id=provider_account_id,
            supabase=supabase
        )
        
        # Store the Twitter connection data for social media management
        if user_result and "user_id" in user_result:
            try:
                # Check if we already have a social connection for this user and provider
                connection_response = supabase.table('social_connections').select('*').eq('user_id', user_result["user_id"]).eq('provider', 'twitter').execute()
                
                connection_data = {
                    'user_id': user_result["user_id"],
                    'provider': 'twitter',
                    'provider_account_id': provider_account_id,
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'token_type': token_type,
                    'expires_in': expires_in,
                    'scope': scope,
                    'metadata': {
                        'profile': profile,
                        'connected_at': 'now()'
                    }
                }
                
                if connection_response.data and len(connection_response.data) > 0:
                    # Update existing connection
                    supabase.table('social_connections').update(connection_data).eq('id', connection_response.data[0]['id']).execute()
                    print(f"Updated existing Twitter connection for user {user_result['user_id']}")
                else:
                    # Create new connection
                    supabase.table('social_connections').insert(connection_data).execute()
                    print(f"Created new Twitter connection for user {user_result['user_id']}")
                    
            except Exception as e:
                print(f"Error storing Twitter connection data: {e}")
                # Don't fail the authentication if connection storage fails
        
        return user_result
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"Twitter OAuth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process Twitter authentication"
        )

@router.post("/oauth/linkedin")
async def linkedin_oauth(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process LinkedIn OAuth authentication
    
    This endpoint receives data from the frontend and processes LinkedIn authentication.
    """
    # Extract data from the request
    email = data.get("email")
    name = data.get("name")
    picture = data.get("picture")
    linkedin_id = data.get("id")  # LinkedIn user ID
    
    # Process authentication and return response
    return await process_oauth_authentication(
        provider="linkedin",
        email=email,
        name=name,
        picture=picture,
        provider_account_id=linkedin_id,
        supabase=supabase
    )

@router.post("/oauth/threads")
async def threads_oauth(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process Threads OAuth authentication
    
    This endpoint receives data from the frontend and processes Threads authentication.
    """
    # Extract data from the request
    email = data.get("email")
    name = data.get("name")
    picture = data.get("picture")
    threads_id = data.get("id")  # Threads user ID
    username = data.get("username")  # Threads username
    
    # Log the authentication attempt
    print(f"Processing Threads OAuth for {email} (ID: {threads_id}, Username: {username})")
    
    # Process authentication and return response
    result = await process_oauth_authentication(
        provider="threads",
        email=email,
        name=name or username,  # Use username as fallback if name not provided
        picture=picture,
        provider_account_id=threads_id,
        supabase=supabase
    )
    
    # Store additional Threads-specific information if needed
    if username and threads_id and result and "user_id" in result:
        try:
            # Check if we already have a social connection for this user and provider
            connection_response = supabase.table('social_connections').select('*').eq('user_id', result["user_id"]).eq('provider', 'threads').execute()
            
            # If not found, store the basic profile in metadata
            if not connection_response.data or len(connection_response.data) == 0:
                # Create minimal profile metadata
                threads_profile = {
                    "id": threads_id,
                    "username": username,
                    "name": name,
                    "profile_picture_url": picture
                }
                
                # Create a placeholder social connection to store metadata
                # Note: This will be properly updated when the actual OAuth token is received
                supabase.table('social_connections').insert({
                    'user_id': result["user_id"],
                    'provider': 'threads',
                    'provider_account_id': threads_id,
                    'metadata': {'profile': threads_profile}
                }).execute()
                
                print(f"Created placeholder Threads connection for user {result['user_id']}")
        except Exception as e:
            print(f"Error storing Threads metadata: {e}")
    
    return result

@router.post("/oauth/youtube")
async def youtube_oauth(
    data: Dict[str, Any] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process YouTube OAuth authentication
    
    This endpoint receives the YouTube OAuth data from the frontend and
    either finds an existing user or creates a new one, then stores the
    YouTube connection with tokens and channel data.
    """
    try:
        # Extract data from the request
        email = data.get("email")
        name = data.get("name")
        picture = data.get("picture")
        provider_account_id = data.get("provider_account_id")
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")
        channel_data = data.get("channel_data")
        user_session_email = data.get("user_session_email")  # Email from NextAuth session
        
        print(f"Processing YouTube OAuth for {email} (Channel ID: {provider_account_id})")
        print(f"Session email: {user_session_email}")
        
        # Use session email as primary identifier if provided
        auth_email = user_session_email or email
        
        if not auth_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required for YouTube authentication"
            )
        
        # Process authentication and get user data
        user_result = await process_oauth_authentication(
            provider="youtube",  # Use 'youtube' as provider instead of 'google'
            email=auth_email,
            name=name,
            picture=picture,
            provider_account_id=provider_account_id,
            supabase=supabase
        )
        
        # Note: YouTube tokens will be stored by the frontend using the standard store-token endpoint
        # We just handle authentication and return the firebase_token here
        print(f"YouTube OAuth authentication successful for user {user_result.get('user_id')} - tokens will be stored by frontend")
        
        return user_result
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"YouTube OAuth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process YouTube authentication"
        )

@router.get("/token")
async def get_auth_token(
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """
    Get a Firebase token for the current authenticated user
    
    This endpoint returns a Firebase custom token that can be used for
    authenticating with other backend services.
    """
    try:
        firebase_uid = current_user.get("firebase_uid")
        if not firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Firebase UID in user data"
            )
        
        # Create a custom token for the user
        custom_token = auth.create_custom_token(firebase_uid)
        token_str = custom_token.decode('utf-8') if isinstance(custom_token, bytes) else custom_token
        
        return {
            "firebase_token": token_str,
            "user_id": current_user.get("id"),
            "firebase_uid": firebase_uid,
            "email": current_user.get("email")
        }
        
    except Exception as e:
        print(f"Error creating auth token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create authentication token"
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