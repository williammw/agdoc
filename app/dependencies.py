# dependencies.py
from firebase_admin import auth as firebase_auth
from fastapi import Depends, HTTPException, Header, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from .firebase_admin_config import verify_token, auth
from .database import database, supabase
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from pydantic import BaseModel
from app.models.models import User
from datetime import datetime, timedelta
import os
import logging
import traceback

from fastapi import Depends, HTTPException, status

security = HTTPBearer()

SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

logger = logging.getLogger(__name__)


class TokenData(BaseModel):
    username: Optional[str] = None


# Update the database dependency to use our adapter
async def get_database():
    """
    Dependency that yields the database adapter (compatible with databases package)
    """
    try:
        yield database
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Database connection error: {str(e)}"
        )


async def get_current_user(authorization: str = Header(...), db = Depends(get_database)):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = firebase_auth.verify_id_token(
            token, check_revoked=True)
        uid = decoded_token['uid']

        # Check if the user is disabled in Firebase
        firebase_user = firebase_auth.get_user(uid)
        if firebase_user.disabled:
            raise HTTPException(
                status_code=403, detail="User account is disabled.")

        # First try to get user from mo_user_info using our database adapter
        user_query = """
        SELECT id, email, username, full_name, plan_type, monthly_post_quota, 
               remaining_posts, language_preference, timezone, notification_preferences, 
               is_active, is_verified, created_at, updated_at, last_login_at
        FROM mo_user_info
        WHERE id = :uid
        """
        
        user = await db.fetch_one(user_query, {"uid": uid})

        # If not found in mo_user_info, try users table
        if not user:
            users_query = """
            SELECT id, username, email, auth_provider, created_at, is_active, full_name,
                   last_username_change, bio, avatar_url, phone_number, dob, status, cover_image
            FROM users
            WHERE id = :uid
            """
            
            user = await db.fetch_one(users_query, {"uid": uid})

            # If still not found, CREATE a new user record
            if not user:
                # Create username from email or display name
                username = firebase_user.display_name or firebase_user.email.split(
                    '@')[0] if firebase_user.email else f"user_{uid[:8]}"

                # Insert into mo_user_info using our database adapter
                try:
                    insert_query = """
                    INSERT INTO mo_user_info (
                        id, email, username, full_name, plan_type, 
                        monthly_post_quota, remaining_posts, is_active, is_verified
                    ) VALUES (
                        :id, :email, :username, :full_name, :plan_type,
                        :monthly_post_quota, :remaining_posts, :is_active, :is_verified
                    )
                    RETURNING id, email, username, full_name, plan_type
                    """
                    
                    insert_values = {
                        "id": uid,
                        "email": firebase_user.email or "",
                        "username": username,
                        "full_name": username,
                        "plan_type": "free",
                        "monthly_post_quota": 10,
                        "remaining_posts": 10,
                        "is_active": True,
                        "is_verified": True
                    }
                    
                    user = await db.fetch_one(insert_query, insert_values)
                    logger.info(f"Created new user record for {uid}")
                except Exception as e:
                    logger.error(f"Failed to create user record: {str(e)}")
                    # Return basic info even if DB insert fails
                    return {
                        "uid": uid,
                        "email": firebase_user.email,
                        "username": username
                    }

        # Convert to dict for compatibility with existing code
        user_dict = dict(user) if user else {}
        user_dict['uid'] = uid
        return user_dict

    except firebase_auth.UserDisabledError:
        raise HTTPException(
            status_code=403, detail="User account is disabled.")
    except Exception as e:
        logger.error(f"Error in get_current_user: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=401, detail="Invalid authentication credentials")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now() + expires_delta
    else:
        expire = datetime.now() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# Add a function to get raw Supabase client if needed
async def get_supabase_client():
    """
    Dependency that yields the raw Supabase client for direct access
    """
    try:
        yield supabase
    except Exception as e:
        logger.error(f"Supabase client error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Supabase connection error: {str(e)}"
        )
