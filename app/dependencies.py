# dependencies.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from .firebase_admin_config import verify_token
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


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        decoded_token = verify_token(token)
        return {"uid": decoded_token['uid']}
    except Exception as e:
        print(f"Error verifying token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now() + expires_delta
    else:
        expire = datetime.now() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
