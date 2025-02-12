# dependencies.py
from firebase_admin import auth as firebase_auth
from databases import Database
from fastapi import Depends, HTTPException, Header, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from .firebase_admin_config import verify_token, auth
from .database import database
from typing import Optional
from jose import JWTError, jwt
from pydantic import BaseModel
from app.models.models import User
from datetime import datetime, timedelta
import os
import logging

from fastapi import Depends, HTTPException, status

security = HTTPBearer()


SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
# security = HTTPBearer()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

logger = logging.getLogger(__name__)




class TokenData(BaseModel):
    username: Optional[str] = None


# Update the database dependency to use yield
async def get_database():
    """
    Dependency that yields the database instance
    """
    try:
        yield database
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")

# v1
# async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
#     token = credentials.credentials
#     logger.info("Verifying token")
#     try:
#         decoded_token = verify_token(token)
#         logger.info(f"Token verified for user: {decoded_token['uid']}")
#         return decoded_token
#     except Exception as e:
#         logger.error(f"Token verification failed: {str(e)}")
#         raise HTTPException(
#             status_code=401,
#             detail=f"Invalid or expired token: {str(e)}",
#             headers={"WWW-Authenticate": "Bearer"},
#         )

#v2


async def get_current_user(authorization: str = Header(...), db: Database = Depends(get_database)):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = firebase_auth.verify_id_token(
            token, check_revoked=True)
        uid = decoded_token['uid']

        # Check if the user is disabled in Firebase
        firebase_user = firebase_auth.get_user(uid)
        if firebase_user.disabled:
            raise HTTPException(
                status_code=403, detail="User account is disabled. Please check your email for verification instructions.")

        # First try mo_user_info table
        query = """
        SELECT id, email, username, full_name, plan_type, monthly_post_quota, remaining_posts,
               language_preference, timezone, notification_preferences, is_active, is_verified,
               created_at, updated_at, last_login_at
        FROM mo_user_info 
        WHERE id = :uid
        """
        user = await db.fetch_one(query=query, values={"uid": uid})

        # If not found in mo_user_info, try users table
        if not user:
            query = """
            SELECT id, username, email, auth_provider, created_at, is_active, full_name, 
                   last_username_change, bio, avatar_url, phone_number, dob, status, cover_image
            FROM users 
            WHERE id = :uid
            """
            user = await db.fetch_one(query=query, values={"uid": uid})

            # If still not found, return just the Firebase user info
            if not user:
                return {
                    "uid": uid,
                    "email": firebase_user.email,
                    "username": firebase_user.display_name or firebase_user.email.split('@')[0] if firebase_user.email else None
                }

        user_dict = dict(user)
        user_dict['uid'] = uid
        return user_dict
    except firebase_auth.UserDisabledError:
        raise HTTPException(
            status_code=403, detail="User account is disabled. Please check your email for verification instructions.")
    except Exception as e:
        logger.error(f"Error in get_current_user: {str(e)}")
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
