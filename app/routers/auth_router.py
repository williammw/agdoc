from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from app.dependencies import get_current_user, get_database
from app.firebase_admin_config import auth
from pydantic import BaseModel, Field
from databases import Database
import os
import uuid
from typing import Optional
from fastapi.responses import JSONResponse
import boto3  # Assuming you're using AWS S3 for file storage
import logging
from datetime import datetime
import aiofiles
from datetime import datetime, timedelta
from app.firebase_admin_config import verify_token, auth

from jose import JWTError, jwt
# import traceback
router = APIRouter()
logger = logging.getLogger(__name__)
# Initialize S3 client
s3 = boto3.client('s3')
BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
# Change this to your actual domain in production
BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000')



class UserInDB(BaseModel):
    id: str
    email: str
    username: str
    name: str
    bio: str
    photo_url: str


def serialize_datetime(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


async def get_or_create_user(db: Database, firebase_user):
    query = "SELECT * FROM users WHERE id = :id"
    user = await db.fetch_one(query=query, values={"id": firebase_user.uid})

    if not user:
        query = """
        INSERT INTO users (id, email, username, name, bio, photo_url)
        VALUES (:id, :email, :username, :name, :bio, :photo_url)
        """
        values = {
            "id": firebase_user.uid,
            "email": firebase_user.email,
            "username": firebase_user.display_name or "",
            "name": firebase_user.display_name or "",
            "bio": "",
            "photo_url": firebase_user.photo_url or ""
        }
        await db.execute(query=query, values=values)
        user = await db.fetch_one(query="SELECT * FROM users WHERE id = :id", values={"id": firebase_user.uid})

    return UserInDB(**user)


@router.get("/user-profile")
async def get_user_profile(current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    logger.info(f"Fetching profile for user: {current_user['uid']}")
    try:
        query = "SELECT * FROM users WHERE id = :id"
        user = await db.fetch_one(query=query, values={"id": current_user['uid']})

        if not user:
            logger.info(
                f"User not found in database, creating new user: {current_user['uid']}")
            firebase_user = auth.get_user(current_user['uid'])
            query = """
            INSERT INTO users (id, email, username, full_name, bio, avatar_url, auth_provider)
            VALUES (:id, :email, :username, :full_name, :bio, :avatar_url, :auth_provider)
            """
            values = {
                "id": current_user['uid'],
                "email": firebase_user.email,
                "username": firebase_user.display_name or "",
                "full_name": firebase_user.display_name or "",
                "bio": "",
                "avatar_url": firebase_user.photo_url or "",
                "auth_provider": "firebase"
            }
            await db.execute(query=query, values=values)
            user = await db.fetch_one("SELECT * FROM users WHERE id = :id", values={"id": current_user['uid']})

        logger.info(f"User profile retrieved/created: {user['id']}")

        # Convert user dict to a regular dict and serialize datetime
        user_dict = dict(user)
        for key, value in user_dict.items():
            user_dict[key] = serialize_datetime(value)

        return JSONResponse(content=user_dict)
    except Exception as e:
        logger.error(f"Error fetching user profile: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)}
        )


class ProfileUpdate(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)
    bio: str = Field(..., max_length=1000)


@router.put("/update-profile")
async def update_profile(profile: ProfileUpdate, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    logger.info(f"Updating profile for user: {current_user['uid']}")
    try:
        # Update Firebase user
        auth.update_user(
            current_user['uid'],
            display_name=profile.full_name,
        )

        # Update database user
        query = """
        UPDATE users
        SET username = :username, full_name = :full_name, bio = :bio
        WHERE id = :id
        """
        values = {
            "id": current_user['uid'],
            "username": profile.username,
            "full_name": profile.full_name,
            "bio": profile.bio
        }
        await db.execute(query=query, values=values)

        # Fetch updated user
        updated_user = await db.fetch_one("SELECT * FROM users WHERE id = :id", values={"id": current_user['uid']})

        # Serialize datetime objects
        serialized_user = {k: serialize_datetime(
            v) for k, v in dict(updated_user).items()}

        return JSONResponse(content=serialized_user)
    except Exception as e:
        logger.error(f"Error updating user profile: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)}
        )


UPLOAD_DIR = "uploads/avatars"  # Make sure this directory exists
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


@router.post("/update-avatar")
async def update_avatar(file: UploadFile = File(...), current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    logger.info(f"Updating avatar for user: {current_user['uid']}")
    try:
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)

        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)

        # Generate the full URL for the uploaded file
        avatar_url = f"{BASE_URL}/uploads/avatars/{unique_filename}"

        # Update Firebase user
        auth.update_user(
            current_user['uid'],
            photo_url=avatar_url
        )

        # Update database user
        query = "UPDATE users SET avatar_url = :avatar_url WHERE id = :id"
        values = {"id": current_user['uid'], "avatar_url": avatar_url}
        await db.execute(query=query, values=values)

        return JSONResponse(content={"message": "Avatar updated successfully", "avatar_url": avatar_url}, status_code=200)
    except Exception as e:
        logger.error(f"Error updating avatar: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)}
        )
    

# Define constants
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    uid: Optional[str] = None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/token", response_model=Token)
async def login_for_access_token(request: Request):
    body = await request.json()
    id_token = body.get("id_token")

    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ID token is required")

    try:
        decoded_token = verify_token(id_token)
        uid = decoded_token['uid']
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": uid}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}
