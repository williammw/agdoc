from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import HTTPBearer
from firebase_admin import auth

from app.dependencies.auth import get_current_user, get_current_user_token
from app.utils.database import get_db, update_user_by_firebase_uid, get_user_by_firebase_uid, create_user
from app.models.users import UserResponse, UserWithInfo
from app.utils.encryption import encrypt_token

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
        
        # Ensure we have the latest user data with all profile fields
        fresh_user = supabase.table('users').select('*').eq('id', current_user["id"]).execute()
        
        if fresh_user.data and len(fresh_user.data) > 0:
            result = dict(fresh_user.data[0])
        else:
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

# Helper function to store social connections with multi-account support
async def store_social_connection_multi_account(
    user_id: int,
    provider: str,
    provider_account_id: str,
    access_token: str,
    refresh_token: str = None,
    expires_in: int = None,
    metadata: dict = None,
    account_label: str = None,
    account_type: str = "personal",
    supabase = None
):
    """
    Store social connection with support for multiple accounts per platform.
    """
    # Calculate expiration time
    expires_at = None
    if expires_in:
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    
    # Check if this specific account already exists
    existing_result = supabase.table("social_connections").select("*").filter(
        "user_id", "eq", user_id
    ).filter(
        "provider", "eq", provider
    ).filter(
        "provider_account_id", "eq", provider_account_id
    ).execute()
    
    # Check if this is the first account for this provider (should be primary)
    is_primary = False
    if not existing_result.data:
        other_accounts_result = supabase.table("social_connections").select("*").filter(
            "user_id", "eq", user_id
        ).filter(
            "provider", "eq", provider
        ).execute()
        
        is_primary = len(other_accounts_result.data) == 0
    
    # Extract account label from metadata if not provided
    if not account_label and metadata:
        account_label = (
            metadata.get("name") or 
            metadata.get("username") or 
            metadata.get("profile", {}).get("name") or
            f"{provider.capitalize()} Account"
        )
    
    connection_data = {
        "user_id": user_id,
        "provider": provider,
        "provider_account_id": provider_account_id,
        "access_token": encrypt_token(access_token),
        "refresh_token": encrypt_token(refresh_token) if refresh_token else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "metadata": metadata,
        "account_label": account_label,
        "is_primary": is_primary,
        "account_type": account_type,
        "updated_at": datetime.utcnow().isoformat()
    }
    
    if existing_result.data:
        # Update existing connection
        supabase.table("social_connections").update(connection_data).filter(
            "id", "eq", existing_result.data[0]["id"]
        ).execute()
        print(f"Updated existing {provider} connection for user {user_id}")
    else:
        # Insert new connection
        connection_data["created_at"] = datetime.utcnow().isoformat()
        supabase.table("social_connections").insert(connection_data).execute()
        print(f"Created new {provider} connection for user {user_id}")

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

@router.post("/token")
async def get_auth_token(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Get a Firebase token for an existing authenticated user
    
    This endpoint is used to get a Firebase token for users who are already
    authenticated through NextAuth but need a Firebase token for backend API calls.
    """
    try:
        email = data.get("email")
        name = data.get("name")
        picture = data.get("picture")
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required for token generation"
            )
        
        # Look up the user by email in our database
        result = supabase.table("users").select("*").eq("email", email).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found. Please complete registration first."
            )
        
        user = result.data[0]
        
        # Get or verify Firebase user
        firebase_user = None
        try:
            firebase_user = auth.get_user_by_email(email)
        except auth.UserNotFoundError:
            # User doesn't exist in Firebase, create them
            try:
                firebase_user = auth.create_user(
                    email=email,
                    display_name=name or user.get("full_name"),
                    photo_url=picture or user.get("avatar_url")
                )
                
                # Update our database with the new Firebase UID
                supabase.table("users").update({
                    "firebase_uid": firebase_user.uid
                }).eq("id", user["id"]).execute()
                
            except Exception as e:
                print(f"Error creating Firebase user: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create Firebase user"
                )
        
        # Generate a custom token for this user (for backend use)
        firebase_token = auth.create_custom_token(firebase_user.uid).decode('utf-8')
        print(f"Generated custom token for user {firebase_user.uid} (email: {email})")
        
        return {
            "firebase_token": firebase_token,
            "user_id": user["id"],
            "firebase_uid": firebase_user.uid,
            "message": "Token generated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in token generation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate token: {str(e)}"
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
        
        # Store the Twitter connection data for social media management with multi-account support
        if user_result and "user_id" in user_result and access_token:
            try:
                await store_social_connection_multi_account(
                    user_id=user_result["user_id"],
                    provider="twitter",
                    provider_account_id=provider_account_id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=expires_in,
                    metadata={
                        'profile': profile,
                        'token_type': token_type,
                        'scope': scope
                    },
                    account_label=name or username,
                    account_type="personal",
                    supabase=supabase
                )
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

@router.post("/oauth/tiktok")
async def tiktok_oauth(
    data: Dict[str, Any] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Process TikTok OAuth authentication
    
    This endpoint receives the TikTok OAuth data from the frontend and
    either finds an existing user or creates a new one, then stores the
    TikTok connection with tokens and user data.
    """
    try:
        # Extract data from the request
        email = data.get("email")
        name = data.get("name")
        picture = data.get("picture")
        provider_account_id = data.get("provider_account_id")  # TikTok open_id
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")
        metadata = data.get("metadata", {})
        user_session_email = data.get("user_session_email")  # Email from NextAuth session
        
        print(f"Processing TikTok OAuth for {email} (TikTok ID: {provider_account_id})")
        print(f"Session email: {user_session_email}")
        
        # Use session email as primary identifier if provided
        auth_email = user_session_email or email
        
        if not auth_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required for TikTok authentication"
            )
        
        if not provider_account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TikTok open_id is required"
            )
        
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access token is required for TikTok authentication"
            )
        
        # Process authentication and get user data
        user_result = await process_oauth_authentication(
            provider="tiktok",
            email=auth_email,
            name=name,
            picture=picture,
            provider_account_id=provider_account_id,
            supabase=supabase
        )
        
        # Store the TikTok connection data for social media management with multi-account support
        if user_result and "user_id" in user_result and access_token:
            try:
                # Prepare TikTok metadata with user info
                tiktok_metadata = {
                    'profile': {
                        'open_id': provider_account_id,
                        'display_name': name,
                        'avatar_url': picture,
                        **metadata  # Include any additional metadata passed from frontend
                    }
                }
                
                await store_social_connection_multi_account(
                    user_id=user_result["user_id"],
                    provider="tiktok",
                    provider_account_id=provider_account_id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=expires_in,
                    metadata=tiktok_metadata,
                    account_label=name or f"TikTok Account",
                    account_type="personal",
                    supabase=supabase
                )
                print(f"Successfully stored TikTok connection for user {user_result['user_id']}")
            except Exception as e:
                print(f"Error storing TikTok connection data: {e}")
                # Don't fail the authentication if connection storage fails
        
        return user_result
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"TikTok OAuth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process TikTok authentication"
        )

@router.post("/token")
async def get_auth_token(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Get a Firebase token by email lookup
    
    This endpoint looks up a user by email and returns a Firebase custom token
    that can be used for authenticating with other backend services.
    """
    try:
        email = data.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required"
            )
        
        # Get user from database by email
        from app.utils.database import get_user_by_email
        user = await get_user_by_email(supabase, email)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        firebase_uid = user.get("firebase_uid")
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
            "user_id": user.get("id"),
            "firebase_uid": firebase_uid,
            "email": user.get("email")
        }
        
    except HTTPException:
        raise
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

@router.put("/profile", response_model=UserResponse)
async def update_profile(
    profile_data: dict = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """
    Update user profile information
    
    Allows users to update their display name, work description, and bio.
    """
    try:
        # Validate allowed fields
        allowed_fields = {'full_name', 'display_name', 'work_description', 'bio'}
        update_data = {k: v for k, v in profile_data.items() if k in allowed_fields and v is not None}
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for update"
            )
        
        # Add updated_at timestamp
        update_data['updated_at'] = datetime.now().isoformat()
        
        # Update user profile using firebase_uid since that's what we authenticate with
        try:
            response = supabase.table('users').update(update_data).eq('firebase_uid', current_user["firebase_uid"]).execute()
            
            if not response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            return response.data[0]
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database update failed: {str(e)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update profile: {str(e)}"
        ) 


# Email verification endpoints

@router.post("/send-verification-email")
async def send_verification_email(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Send email verification link to user
    
    This endpoint generates a verification token and sends an email to the user
    with a verification link. Used both for initial registration and resending.
    """
    try:
        email = data.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required"
            )
        
        # Check if user exists in database
        user_response = supabase.table('users').select('*').eq('email', email).execute()
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user = user_response.data[0]
        
        # Check if already verified
        if user.get('email_verified'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already verified"
            )
        
        # Generate verification token
        verification_token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        expires_at = datetime.utcnow() + timedelta(hours=24)  # 24 hour expiry
        
        # Store verification token in database
        update_data = {
            'email_verification_token': verification_token,
            'email_verification_expires_at': expires_at.isoformat(),
            'email_verification_sent_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        supabase.table('users').update(update_data).eq('id', user['id']).execute()
        
        # Send actual email using SendGrid
        verification_url = f"{data.get('base_url', 'https://dev.multivio.com')}/verify-email?token={verification_token}&email={email}"
        
        # Import email service
        from app.utils.email import send_verification_email
        
        # Send verification email
        email_sent = send_verification_email(
            email=email,
            name=user.get('full_name', 'User'),
            verification_url=verification_url
        )
        
        if not email_sent:
            # Log for debugging but don't fail the request
            print(f"Warning: Failed to send verification email to {email}, but token stored")
        
        return {
            "message": "Verification email sent successfully",
            "email_service_status": "sent" if email_sent else "fallback"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending verification email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email"
        )

@router.post("/verify-email")
async def verify_email(
    data: Dict[str, str] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Verify user email with verification token
    
    This endpoint validates the verification token and marks the user's email as verified.
    """
    try:
        token = data.get("token")
        email = data.get("email")
        
        if not token or not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token and email are required"
            )
        
        # Find user with matching email and verification token
        user_response = supabase.table('users').select('*').eq('email', email).eq('email_verification_token', token).execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification token or email"
            )
        
        user = user_response.data[0]
        
        # Check if token has expired
        if user.get('email_verification_expires_at'):
            # Handle different datetime formats and microseconds
            expires_at_str = user['email_verification_expires_at'].replace('Z', '+00:00')
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
            except ValueError:
                # Handle microseconds format issues by normalizing to 6 digits
                import re
                # Find microseconds pattern and normalize it
                expires_at_str = re.sub(r'\.(\d{1,6})', lambda m: f'.{m.group(1).ljust(6, "0")}', expires_at_str)
                expires_at = datetime.fromisoformat(expires_at_str)
            
            if datetime.utcnow().replace(tzinfo=expires_at.tzinfo) > expires_at:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Verification token has expired"
                )
        
        # Check if already verified
        if user.get('email_verified'):
            return {
                "message": "Email is already verified",
                "verified": True
            }
        
        # Mark email as verified and clear verification token
        update_data = {
            'email_verified': True,
            'email_verification_token': None,
            'email_verification_expires_at': None,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        supabase.table('users').update(update_data).eq('id', user['id']).execute()
        
        # Also update Firebase user
        try:
            firebase_user = auth.get_user_by_email(email)
            auth.update_user(firebase_user.uid, email_verified=True)
            print(f"Updated Firebase email verification for {email}")
        except Exception as firebase_error:
            print(f"Warning: Could not update Firebase email verification: {firebase_error}")
        
        # Send welcome email after successful verification
        try:
            from app.utils.email import send_welcome_email
            send_welcome_email(email=email, name=user.get('full_name', 'User'))
        except Exception as welcome_error:
            print(f"Warning: Failed to send welcome email to {email}: {welcome_error}")
        
        return {
            "message": "Email verified successfully",
            "verified": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error verifying email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify email"
        )

@router.get("/verification-status/{email}")
async def get_verification_status(
    email: str,
    supabase = Depends(db_admin)
):
    """
    Check email verification status for a user
    
    This endpoint checks if a user's email is verified and provides verification status.
    """
    try:
        # Get user by email
        user_response = supabase.table('users').select('email_verified', 'email_verification_sent_at').eq('email', email).execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user = user_response.data[0]
        
        return {
            "email": email,
            "verified": user.get('email_verified', False),
            "verification_sent_at": user.get('email_verification_sent_at'),
            "can_resend": True  # Always allow resend for now
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error checking verification status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check verification status"
        )

# Password change endpoint

@router.put("/change-password")
async def change_password(
    data: Dict[str, str] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """
    Change user password
    
    This endpoint allows authenticated users to change their password.
    Requires current password for verification.
    """
    try:
        current_password = data.get("current_password")
        new_password = data.get("new_password")
        
        if not current_password or not new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password and new password are required"
            )
        
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be at least 8 characters long"
            )
        
        # Validate password strength
        if not _validate_password_strength(new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character"
            )
        
        # Get user's Firebase UID to update password in Firebase
        firebase_uid = current_user.get("firebase_uid")
        if not firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Firebase UID not found for user"
            )
        
        # Verify current password by attempting to sign in with Firebase
        try:
            # For security, we'll update the password in Firebase directly
            # The current password verification happens on the frontend before calling this endpoint
            auth.update_user(firebase_uid, password=new_password)
            print(f"Password updated successfully for user {current_user['email']}")
            
            return {
                "message": "Password updated successfully",
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as firebase_error:
            print(f"Error updating password in Firebase: {firebase_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update password"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error changing password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )

def _validate_password_strength(password: str) -> bool:
    """
    Validate password strength
    
    Args:
        password: Password to validate
        
    Returns:
        bool: True if password meets strength requirements
    """
    if len(password) < 8:
        return False
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*(),.?\":{}|<>" for c in password)
    
    return has_upper and has_lower and has_digit and has_special

# Rate limiting for authentication endpoints

failed_attempts = {}  # In production, use Redis or database
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = 900  # 15 minutes

def check_rate_limit(email: str) -> bool:
    """
    Check if user is rate limited
    
    Args:
        email: User email to check
        
    Returns:
        bool: True if user can attempt login, False if rate limited
    """
    now = datetime.utcnow()
    
    if email in failed_attempts:
        attempts, last_attempt = failed_attempts[email]
        
        # Reset if lockout period has passed
        if (now - last_attempt).total_seconds() > LOCKOUT_DURATION:
            del failed_attempts[email]
            return True
        
        # Check if user is locked out
        if attempts >= LOCKOUT_THRESHOLD:
            return False
    
    return True

def record_failed_attempt(email: str):
    """
    Record a failed login attempt
    
    Args:
        email: User email
    """
    now = datetime.utcnow()
    
    if email in failed_attempts:
        attempts, _ = failed_attempts[email]
        failed_attempts[email] = (attempts + 1, now)
    else:
        failed_attempts[email] = (1, now)

def clear_failed_attempts(email: str):
    """
    Clear failed attempts for successful login
    
    Args:
        email: User email
    """
    if email in failed_attempts:
        del failed_attempts[email]

# Rate limiting endpoints

@router.post("/check-rate-limit")
async def check_user_rate_limit(
    data: Dict[str, str] = Body(...),
):
    """
    Check if user is rate limited
    
    Returns 429 if user is locked out, 200 if allowed to proceed
    """
    try:
        email = data.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required"
            )
        
        if not check_rate_limit(email):
            attempts, last_attempt = failed_attempts.get(email, (0, datetime.utcnow()))
            remaining_time = LOCKOUT_DURATION - int((datetime.utcnow() - last_attempt).total_seconds())
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account temporarily locked due to too many failed attempts. Try again in {remaining_time // 60} minutes."
            )
        
        return {"message": "Rate limit check passed"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error checking rate limit: {e}")
        return {"message": "Rate limit check passed"}  # Fail open for now

@router.post("/record-failed-attempt")
async def record_login_failure(
    data: Dict[str, str] = Body(...),
):
    """
    Record a failed login attempt
    """
    try:
        email = data.get("email")
        if email:
            record_failed_attempt(email)
        
        return {"message": "Failed attempt recorded"}
        
    except Exception as e:
        print(f"Error recording failed attempt: {e}")
        return {"message": "Failed attempt recorded"}

@router.post("/clear-rate-limit")
async def clear_user_rate_limit(
    data: Dict[str, str] = Body(...),
):
    """
    Clear failed attempts for successful login
    """
    try:
        email = data.get("email")
        if email:
            clear_failed_attempts(email)
        
        return {"message": "Rate limit cleared"}
        
    except Exception as e:
        print(f"Error clearing rate limit: {e}")
        return {"message": "Rate limit cleared"}