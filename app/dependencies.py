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


async def get_database():
    return database

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

        query = """
        SELECT id, username, email, auth_provider, created_at, is_active, full_name, 
               bio, avatar_url, phone_number, dob
        FROM users 
        WHERE id = :uid
        """
        user = await db.fetch_one(query=query, values={"uid": uid})

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_dict = dict(user)
        user_dict['uid'] = uid
        print("User data from get_current_user:", user_dict)
        return user_dict
    except firebase_auth.UserDisabledError:
        raise HTTPException(
            status_code=403, detail="User account is disabled. Please check your email for verification instructions.")
    except Exception as e:
        print(f"Error in get_current_user: {str(e)}")
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
