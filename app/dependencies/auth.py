from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.utils.firebase import verify_firebase_token
from app.utils.database import get_db, get_user_by_firebase_uid, create_user

# Security scheme for Swagger UI
security = HTTPBearer()

# Create database dependency with admin access
db_admin = get_db(admin_access=True)

async def get_current_user_token(
    request: Request = None,
    authorization: str = Header(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Get and verify the current user's Firebase token
    
    This dependency extracts and validates the Firebase ID token from the Authorization header.
    It can be used with either header-based or security scheme-based authorization.
    """
    # First try to get the token from the Authorization header
    token = None
    
    # 1. Try to get the token from the Authorization header
    if authorization:
        # Handle "Bearer" prefix if present
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization
    
    # 2. If not found, try to get it from the security scheme
    if not token and credentials:
        token = credentials.credentials
    
    # 3. If still not found, check if it's in request headers (for non-standard header cases)
    if not token and request:
        for header in ['authorization', 'Authorization']:
            if header in request.headers:
                header_value = request.headers[header]
                if header_value.startswith("Bearer "):
                    token = header_value[7:]
                else:
                    token = header_value
                break
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token. Please include valid Bearer token in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify the token with Firebase
    try:
        return await verify_firebase_token(token)
    except HTTPException as e:
        # Re-raise with more context if needed
        if e.status_code == status.HTTP_401_UNAUTHORIZED:
            print(f"Token verification failed for token: {token[:10]}...")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token verification failed: {e.detail}. Please login again to get a fresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise

async def get_current_user(
    token_data: Dict[str, Any] = Depends(get_current_user_token),
    conn = Depends(db_admin)
) -> Dict[str, Any]:
    """
    Get the current authenticated user from the database
    
    This dependency verifies the token and then fetches the user from our database.
    If the user doesn't exist in our database yet but has a valid Firebase token,
    it creates a new user record.
    """
    firebase_uid = token_data.get("uid")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials: Missing user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        # Look up the user in our database
        user = await get_user_by_firebase_uid(conn, firebase_uid)
        
        # If user doesn't exist in our database but has valid Firebase auth,
        # create a new user record
        if not user:
            # Create a new user with Firebase data
            user_data = {
                "firebase_uid": firebase_uid,
                "email": token_data.get("email", ""),
                "email_verified": token_data.get("email_verified", False),
                "auth_provider": token_data.get("firebase", {}).get("sign_in_provider", "email"),
                "full_name": token_data.get("name", ""),
                "avatar_url": token_data.get("picture", ""),
            }
            
            user = await create_user(conn, user_data)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create user record in database",
                )
        
        # Check if the user is active
        if not user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        
        return user
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log the error and raise a 500
        print(f"Database error in get_current_user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while retrieving user",
        )

async def get_optional_user(
    token_data: Optional[Dict[str, Any]] = Depends(get_current_user_token),
    conn = Depends(db_admin)
) -> Optional[Dict[str, Any]]:
    """
    Get the current user if authenticated, otherwise return None
    
    This dependency can be used for endpoints that work with or without authentication.
    """
    if not token_data:
        return None
    
    try:
        return await get_current_user(token_data, conn)
    except HTTPException:
        return None 