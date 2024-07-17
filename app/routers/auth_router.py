import os
import base64
import hashlib
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from fastapi.encoders import jsonable_encoder
import base64
from app import database
from app.dependencies import get_current_user, get_database
# from app.firebase_admin_config import auth, verify_token
from pydantic import BaseModel, Field, EmailStr
from databases import Database
import uuid
from typing import Optional
from fastapi.responses import JSONResponse
import boto3  # Assuming you're using AWS S3 for file storage
import logging

import aiofiles
from datetime import datetime, date, time, timedelta

from app.firebase_admin_config import verify_token, auth
import secrets
from jose import JWTError, jwt
# import traceback
router = APIRouter()
logger = logging.getLogger(__name__)
# Initialize S3 client
s3 = boto3.client('s3')
BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
# Change this to your actual domain in production
BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000')


class VerificationRequest(BaseModel):
    contact: str
    method: str


class UserRegistration(BaseModel):
    uid: str
    email: Optional[str] = None
    phoneNumber: Optional[str] = None
    displayName: Optional[str] = None
    photoURL: Optional[str] = None



class EmailSignupRequest(BaseModel):
    email: str
    password: str
    code: str


class PhoneVerificationRequest(BaseModel):
    phone_number: str


class PhoneSignupRequest(BaseModel):
    phone: str
    code: str
    password: str


class UserInDB(BaseModel):
    id: str
    email: str
    username: str
    name: str
    bio: str
    photo_url: str


class UserProfile(BaseModel):
    id: str
    username: Optional[str] = None
    email: Optional[str] = None
    auth_provider: str
    created_at: datetime
    is_active: bool
    full_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None


class CompleteProfileRequest(BaseModel):
    userId: str
    dob: date
    username: str
    fullName: str
    bio: str

class UpdatePasswordRequest(BaseModel):
    newPassword: str


class UpdateProfileRequest(BaseModel):
    username: str
    full_name: str
    bio: str
    dob: Optional[date] = None
    avatar_url: Optional[str] = None


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


# @router.get("/user-profile", response_model=UserProfile)
# async def get_user_profile(current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
#     try:
#         firebase_user = auth.get_user(current_user['uid'])
#         # print('*****_________******* :: ', firebase_user.uid)
        

#         query = "SELECT * FROM users WHERE id = :id"
#         user = await db.fetch_one(query=query, values={"id": firebase_user.uid})

#         if not user:
#             # User doesn't exist in our database, create a new user
#             query = """
#             INSERT INTO users (id, username, email, auth_provider, created_at, is_active, full_name, phone_number)
#             VALUES (:id, :username, :email, :auth_provider, CURRENT_TIMESTAMP, true, :full_name, :phone_number)
#             RETURNING *
#             """
#             values = {
#                 "id": firebase_user.uid,
#                 "username": firebase_user.display_name or firebase_user.phone_number or "",
#                 "email": firebase_user.email,  # This can be None for phone auth
#                 "auth_provider": "firebase",
#                 "full_name": firebase_user.display_name,
#                 "phone_number": firebase_user.phone_number
#             }
#             user = await db.fetch_one(query=query, values=values)

#         if not user:
#             raise HTTPException(
#                 status_code=404, detail="User not found and could not be created")

#         # Convert the database result to a dict and create a UserProfile object
#         user_dict = dict(user)
#         return UserProfile(**user_dict)
#     except Exception as e:
#         print(f"Error in get_user_profile: {str(e)}")
#         raise HTTPException(status_code=400, detail=str(e))

@router.get("/user-profile")
async def get_user_profile(current_user: dict = Depends(get_current_user), database=Depends(get_database)):
    try:
        query = "SELECT id, email, username, full_name, bio, avatar_url FROM users WHERE id = :user_id"
        user = await database.fetch_one(query=query, values={"user_id": current_user['uid']})

        firebase_user = auth.get_user(current_user['uid'])
        firebase_user_email = firebase_user.email if firebase_user else None

        if user:
            return dict(user)
        else:
            # If user doesn't exist in our database, create a new entry
            create_query = """
            INSERT INTO users (id, email)
            VALUES (:id, :email)
            ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
            RETURNING id, email, username, full_name, bio, avatar_url
            """

            # Use Firebase email if available, otherwise use an empty string
            email = firebase_user_email or ""

            new_user = await database.fetch_one(create_query, {
                "id": current_user['uid'],
                "email": email
            })
            return dict(new_user)
    except Exception as e:
        print(f"Error in get_user_profile: {str(e)}")
        print(f"Current user data: {current_user}")
        print(f"Firebase user email: {firebase_user_email}")
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}")


class ProfileUpdate(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


@router.post("/update-profile")
async def update_profile(profile: ProfileUpdate, current_user: dict = Depends(get_current_user), database=Depends(get_database)):
    try:
        query = """
        UPDATE users
        SET username = COALESCE(:username, username),
            full_name = COALESCE(:full_name, full_name),
            bio = COALESCE(:bio, bio),
            avatar_url = COALESCE(:avatar_url, avatar_url)
        WHERE id = :id
        RETURNING id, email, username, full_name, bio, avatar_url
        """
        values = {
            "id": current_user['uid'],
            "username": profile.username,
            "full_name": profile.full_name,
            "bio": profile.bio,
            "avatar_url": profile.avatar_url
        }
        updated_user = await database.fetch_one(query=query, values=values)

        if updated_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        return dict(updated_user)
    except Exception as e:
        print(f"Error updating user profile: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to update profile")
class ProfileUpdate(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)
    bio: str = Field(..., max_length=1000)





@router.post("/update-password")
async def update_password(request: UpdatePasswordRequest, current_user: dict = Depends(get_current_user)):
    try:
        # Update the password using Firebase Admin SDK
        auth.update_user(current_user['uid'], password=request.newPassword)

        return {"message": "Password updated successfully"}
    except Exception as e:
        print(f"Error updating password: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

# auth_router.py


# @router.post("/update-profile")
# async def update_profile(request: UpdateProfileRequest, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
#     try:
#         # Update user in Firebase
#         auth.update_user(
#             current_user['uid'],
#             display_name=request.full_name,
#         )

#         # Update user in RDS
#         query = """
#         UPDATE users
#         SET username = :username, full_name = :full_name, bio = :bio, avatar_url = :avatar_url
#         WHERE id = :id
#         RETURNING *
#         """
#         values = {
#             "id": current_user['uid'],
#             "username": request.username,
#             "full_name": request.full_name,
#             "bio": request.bio,
#             "avatar_url": request.avatar_url
#         }

#         updated_user = await db.fetch_one(query=query, values=values)

#         # Convert datetime objects to strings
#         serializable_user = dict(updated_user)
#         for key, value in serializable_user.items():
#             if isinstance(value, (datetime, date)):
#                 serializable_user[key] = value.isoformat()

#         return JSONResponse(content=serializable_user)
#     except Exception as e:
#         logger.error(f"Error updating user profile: {str(e)}")
#         raise HTTPException(status_code=400, detail=str(e))


# @router.post("/upload-avatar")
# async def upload_avatar(file: UploadFile = File(...), current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):

#     try:
#         file_extension = os.path.splitext(file.filename)[1]
#         unique_filename = f"{uuid.uuid4()}{file_extension}"
#         file_path = os.path.join(UPLOAD_DIR, unique_filename)

#         async with aiofiles.open(file_path, 'wb') as out_file:
#             content = await file.read()
#             await out_file.write(content)

#         avatar_url = f"{BASE_URL}/uploads/avatars/{unique_filename}"

#         # Update Firebase user
#         auth.update_user(
#             current_user['uid'],
#             photo_url=avatar_url
#         )

#         # Update database user
#         query = "UPDATE users SET avatar_url = :avatar_url WHERE id = :id RETURNING *"
#         values = {"id": current_user['uid'], "avatar_url": avatar_url}
#         updated_user = await db.fetch_one(query=query, values=values)

#         return JSONResponse(content={"message": "Avatar updated successfully", "avatar_url": avatar_url, "user": dict(updated_user)})
#     except Exception as e:
#         logger.error(f"Error updating avatar: {str(e)}")
#         raise HTTPException(status_code=400, detail=str(e))


# UPLOAD_DIR = "uploads/avatars"  # Make sure this directory exists
# if not os.path.exists(UPLOAD_DIR):
#     os.makedirs(UPLOAD_DIR)


# @router.post("/update-avatar")
# async def update_avatar(file: UploadFile = File(...), current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
#     logger.info(f"Updating avatar for user: {current_user['uid']}")
#     try:
#         file_extension = os.path.splitext(file.filename)[1]
#         unique_filename = f"{uuid.uuid4()}{file_extension}"
#         file_path = os.path.join(UPLOAD_DIR, unique_filename)

#         async with aiofiles.open(file_path, 'wb') as out_file:
#             content = await file.read()
#             await out_file.write(content)

#         # Generate the full URL for the uploaded file
#         avatar_url = f"{BASE_URL}/uploads/avatars/{unique_filename}"

#         # Update Firebase user
#         auth.update_user(
#             current_user['uid'],
#             photo_url=avatar_url
#         )

#         # Update database user
#         query = "UPDATE users SET avatar_url = :avatar_url WHERE id = :id"
#         values = {"id": current_user['uid'], "avatar_url": avatar_url}
#         await db.execute(query=query, values=values)

#         return JSONResponse(content={"message": "Avatar updated successfully", "avatar_url": avatar_url}, status_code=200)
#     except Exception as e:
#         logger.error(f"Error updating avatar: {str(e)}")
#         return JSONResponse(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             content={"detail": str(e)}
#         )


@router.post("/confirm-phone-signup")
async def confirm_phone_signup(request: PhoneSignupRequest, db: Database = Depends(get_database)):
    try:
        # Verify the code
        verification = auth.verify_phone_number(request.phone, request.code)

        # Create user in Firebase
        user = auth.create_user(
            phone_number=request.phone,
            password=request.password
        )

        # Store user in RDS
        query = """
        INSERT INTO users (id, phone_number, created_at, is_active)
        VALUES (:id, :phone, CURRENT_TIMESTAMP, true)
        RETURNING *
        """
        values = {"id": user.uid, "phone": request.phone}
        new_user = await db.fetch_one(query=query, values=values)

        return JSONResponse(content={"message": "User created successfully", "user": dict(new_user)})
    except Exception as e:
        logger.error(f"Error confirming phone signup: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/confirm-email-signup")
async def confirm_email_signup(request: EmailSignupRequest, db: Database = Depends(get_database)):
    try:
        # Verify the code (you might need to implement a custom verification system for email)
        # For simplicity, we're assuming the code is valid here

        # Create user in Firebase
        user = auth.create_user(
            email=request.email,
            password=request.password
        )

        # Store user in RDS
        query = """
        INSERT INTO users (id, email, created_at, is_active)
        VALUES (:id, :email, CURRENT_TIMESTAMP, true)
        RETURNING *
        """
        values = {"id": user.uid, "email": request.email}
        new_user = await db.fetch_one(query=query, values=values)

        return JSONResponse(content={"message": "User created successfully", "user": dict(new_user)})
    except Exception as e:
        logger.error(f"Error confirming email signup: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/google-signup")
async def google_signup(token: str, db: Database = Depends(get_database)):
    try:
        # Verify the Google ID token
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']

        # Get the user info from Firebase
        user = auth.get_user(uid)

        # Store user in RDS
        query = """
        INSERT INTO users (id, email, full_name, avatar_url, created_at, is_active, auth_provider)
        VALUES (:id, :email, :full_name, :avatar_url, CURRENT_TIMESTAMP, true, 'google')
        ON CONFLICT (id) DO UPDATE
        SET email = EXCLUDED.email,
            full_name = EXCLUDED.full_name,
            avatar_url = EXCLUDED.avatar_url,
            auth_provider = EXCLUDED.auth_provider
        RETURNING *
        """
        values = {
            "id": user.uid,
            "email": user.email,
            "full_name": user.display_name,
            "avatar_url": user.photo_url
        }
        new_user = await db.fetch_one(query=query, values=values)

        return JSONResponse(content={"message": "User created/updated successfully", "user": dict(new_user)})
    except Exception as e:
        logger.error(f"Error during Google signup: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

# Add this function to handle errors globally


# @router.exception_handler(HTTPException)
# async def http_exception_handler(request: Request, exc: HTTPException):
#     return JSONResponse(
#         status_code=exc.status_code,
#         content={"detail": str(exc.detail)}
#     )

# Add this function to handle unexpected errors


# @router.exception_handler(Exception)
# async def general_exception_handler(request: Request, exc: Exception):
#     logger.error(f"Unexpected error: {str(exc)}")
#     return JSONResponse(
#         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#         content={"detail": "An unexpected error occurred. Please try again later."}
#     )
    

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


@router.post("/send_verification_code")
async def send_verification_code(request: VerificationRequest):
    try:
        logger.info(f"Received request to send verification code: {request}")
        if request.method == 'phone':
            # Use Firebase Admin SDK to send SMS
            verification = auth.send_verification_code(request.contact)
        else:
            # Use Firebase Admin SDK to send email
            verification = auth.generate_email_verification_link(
                request.contact)
        return {"message": "Verification code sent"}
    except Exception as e:
        logger.error(f"Error sending verification code: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/signup_with_phone")
async def signup_with_phone(request: PhoneSignupRequest, db: Database = Depends(get_database)):
    try:
        # Verify the code
        verification = auth.verify_phone_number(request.phone, request.code)

        # Create user in Firebase
        user = auth.create_user(
            phone_number=request.phone,
            password=request.password
        )

        # Store user in RDS
        query = "INSERT INTO users (id, phone_number) VALUES (:id, :phone)"
        values = {"id": user.uid, "phone": request.phone}
        await db.execute(query=query, values=values)

        return {"message": "User created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/signup_with_email")
async def signup_with_email(request: EmailSignupRequest, db: Database = Depends(get_database)):
    try:
        # Verify the code (you might need to implement a custom verification system for email)
        # For simplicity, we're assuming the code is valid here

        # Create user in Firebase
        user = auth.create_user(
            email=request.email,
            password=request.password
        )

        # Store user in RDS
        query = "INSERT INTO users (id, email) VALUES (:id, :email)"
        values = {"id": user.uid, "email": request.email}
        await db.execute(query=query, values=values)

        return {"message": "User created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/register", response_model=UserProfile)
async def register_user(user: UserRegistration, db: Database = Depends(get_database)):
    logger.info(f"Registering user: {user}")
    try:
        query = """
        INSERT INTO users (id, username, email, auth_provider, created_at, is_active, full_name, avatar_url, phone_number)
        VALUES (:id, :username, :email, :auth_provider, CURRENT_TIMESTAMP, true, :full_name, :avatar_url, :phone_number)
        ON CONFLICT (id) DO UPDATE
        SET username = EXCLUDED.username, 
            email = EXCLUDED.email,
            full_name = EXCLUDED.full_name,
            avatar_url = EXCLUDED.avatar_url,
            phone_number = EXCLUDED.phone_number
        RETURNING *
        """
        values = {
            "id": user.uid,
            "username": user.displayName or user.phoneNumber or user.email or "",
            "email": user.email,
            "auth_provider": "firebase",
            "full_name": user.displayName,
            "avatar_url": user.photoURL,
            "phone_number": user.phoneNumber
        }
        new_user = await db.fetch_one(query=query, values=values)
        return UserProfile(**new_user)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/complete-profile")
async def complete_profile(request: CompleteProfileRequest, db: Database = Depends(get_database)):
    print('************\n')
    try:
        # Update user in Firebase
        auth.update_user(
            request.userId,
            display_name=request.fullName,
        )

        # Update user in RDS
        query = """
        UPDATE users
        SET dob = :dob, username = :username, full_name = :full_name, bio = :bio
        WHERE id = :id
        RETURNING *
        """
        values = {
            "id": request.userId,
            "dob": request.dob,
            "username": request.username,
            "full_name": request.fullName,
            "bio": request.bio
        }
        updated_user = await db.fetch_one(query=query, values=values)

        # Convert datetime objects to strings
        serializable_user = dict(updated_user)
        for key, value in serializable_user.items():
            if isinstance(value, (datetime, date)):
                serializable_user[key] = value.isoformat()

        return JSONResponse(content=serializable_user)
    except Exception as e:
        logger.error(f"Error completing user profile: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


class LinkEmailRequest(BaseModel):
    email: str


@router.post("/link-email-password")
async def link_email_password(request: LinkEmailRequest, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    try:
        # Update the user's email in the database
        query = """
        UPDATE users
        SET email = :email
        WHERE id = :id
        RETURNING *
        """
        values = {"id": current_user['uid'], "email": request.email}
        updated_user = await db.fetch_one(query=query, values=values)

        if not updated_user:
            raise HTTPException(status_code=404, detail="User not found")

        return {"message": "Email linked successfully", "user": dict(updated_user)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Firebase password hash parameters
FIREBASE_SIGNER_KEY = base64.b64decode(
    "wNBHg9oudUKpHZAzrE8AN7zKlrCS+owMQaPR7KiCpkkB56aKoH1nq1I90WvuZH/XQ8HY/KZ7mrTWW5dHq7YyTA==")
FIREBASE_SALT_SEPARATOR = base64.b64decode("Bw==")
FIREBASE_ROUNDS = 8
FIREBASE_MEM_COST = 14


def hash_password(password: str) -> str:
    salt = os.urandom(16)

    # Combine salt with the salt separator
    salt_with_separator = salt + FIREBASE_SALT_SEPARATOR

    # Use scrypt with Firebase's parameters
    derived_key = hashlib.scrypt(
        password.encode(),
        salt=salt_with_separator,
        n=2**FIREBASE_MEM_COST,
        r=FIREBASE_ROUNDS,
        p=1,
        dklen=32
    )

    # Combine the results as Firebase does
    to_encode = salt + derived_key

    # Base64 encode the result
    encoded = base64.b64encode(to_encode).decode()

    # Return the result in Firebase's format
    return f"$scrypt${FIREBASE_MEM_COST}${FIREBASE_ROUNDS}${base64.b64encode(salt).decode()}${encoded}"

class TempUserCreate(BaseModel):
    email: EmailStr
    password: str


class TempUserResponse(BaseModel):
    tempUserId: str
    email: EmailStr


@router.post("/create-temp-user", response_model=TempUserResponse)
async def create_temp_user(user: TempUserCreate, database: Database = Depends(get_database)):
    temp_user_id = str(uuid.uuid4())
    logger.info(f"user password : {user.password}")
    hashed_password = hash_password(user.password)

    query = """
    INSERT INTO temp_users (id, email, password, created_at)
    VALUES (:id, :email, :password, :created_at)
    RETURNING id
    """
    values = {
        "id": temp_user_id,
        "email": user.email,
        "password": user.password,
        "created_at": datetime.now()
    }

    try:
        result = await database.fetch_one(query=query, values=values)
        inserted_id = result['id']
        print(f"Inserted temp user with ID: {inserted_id}")
        return TempUserResponse(tempUserId=str(inserted_id), email=user.email)
    except Exception as e:
        print(f"Error creating temp user: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create temporary user: {str(e)}")


@router.get("/get-temp-user/{temp_user_id}")
async def get_temp_user(temp_user_id: str, database: Database = Depends(get_database)):
    logger.info(f"get-temp-user :: Getting temp user with ID: {temp_user_id}")
    query = """
    SELECT id, email, password FROM temp_users
    WHERE id = :id AND created_at > :expiration_time
    """
    expiration_time = datetime.now() - timedelta(hours=24)
    values = {"id": temp_user_id, "expiration_time": expiration_time}

    user = await database.fetch_one(query=query, values=values)

    if not user:
        raise HTTPException(
            status_code=404, detail="Temporary user not found or expired")

    return {"email": user['email'], "password": user['password'], "tempUserId": str(user['id'])}


@router.post("/verify-user")
async def verify_user(data: dict, database: Database = Depends(get_database)):
    logger.info(f"Verifying user with ID: {data['tempUserId']}")

    # First, check if the user exists
    check_query = """
    SELECT id FROM users WHERE id = :user_id
    """
    check_values = {"user_id": data['tempUserId']}

    try:
        user = await database.fetch_one(check_query, values=check_values)
        if not user:
            logger.error(f"User with ID {data['tempUserId']} not found")
            raise HTTPException(status_code=404, detail="User not found")

        # If user exists, proceed with update
        update_query = """
        UPDATE users SET is_verified = TRUE WHERE id = :user_id
        """
        update_values = {"user_id": data['tempUserId']}

        await database.execute(update_query, values=update_values)
        logger.info(f"User {data['tempUserId']} verified successfully")
        return {"message": "User verified successfully"}
    except Exception as e:
        logger.error(f"Failed to verify user: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to verify user: {str(e)}")
    


@router.delete("/delete-temp-user/{temp_user_id}")
async def delete_temp_user(temp_user_id: str, database: Database = Depends(get_database)):
    query = """
    DELETE FROM temp_users
    WHERE id = :id
    """
    values = {"id": temp_user_id}

    try:
        result = await database.execute(query=query, values=values)
        if result == 0:
            raise HTTPException(
                status_code=404, detail="Temporary user not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete temporary user: {str(e)}")

    return {"message": "Temporary user deleted successfully"}

# New endpoint to verify the temp user's password


def verify_password(stored_password: str, provided_password: str) -> bool:
    # Extract parts from the stored password
    parts = stored_password.split('$')
    if len(parts) != 6 or parts[1] != 'scrypt':
        return False

    mem_cost = int(parts[2])
    rounds = int(parts[3])
    salt = base64.b64decode(parts[4])
    stored_hash = base64.b64decode(parts[5])

    # Combine salt with the salt separator
    salt_with_separator = salt + FIREBASE_SALT_SEPARATOR

    # Hash the provided password
    derived_key = hashlib.scrypt(
        provided_password.encode(),
        salt=salt_with_separator,
        n=2**mem_cost,
        r=rounds,
        p=1,
        dklen=32
    )

    # Compare the derived key with the stored hash
    return salt + derived_key == stored_hash


@router.post("/verify-temp-user-password")
async def verify_temp_user_password(temp_user_id: str, password: str, database: Database = Depends(get_database)):
    query = """
    SELECT password FROM temp_users
    WHERE id = :id AND created_at > :expiration_time
    """
    expiration_time = datetime.now() - timedelta(hours=24)
    values = {"id": temp_user_id, "expiration_time": expiration_time}

    user = await database.fetch_one(query=query, values=values)

    if not user:
        raise HTTPException(
            status_code=404, detail="Temporary user not found or expired")

    if verify_password(user['password'], password):
        return {"message": "Password verified successfully"}
    else:
        raise HTTPException(status_code=400, detail="Invalid password")

@router.post("/confirm-user/{temp_user_id}")
async def confirm_user(temp_user_id: str, database=Depends(get_database)):
    async with database.transaction():
        # Fetch the temporary user
        fetch_query = "SELECT * FROM temp_users WHERE id = :id"
        temp_user = await database.fetch_one(fetch_query, {"id": temp_user_id})

        if not temp_user:
            raise HTTPException(
                status_code=404, detail="Temporary user not found")

        # Check if user already exists
        check_user_query = "SELECT id FROM users WHERE email = :email"
        existing_user = await database.fetch_one(check_user_query, {"email": temp_user['email']})

        if existing_user:
            # User already exists, update their password instead of creating a new user
            update_user_query = """
            UPDATE users SET password = :password WHERE email = :email
            """
            await database.execute(update_user_query, {"email": temp_user['email'], "password": temp_user['password']})
        else:
            # Create a new user
            create_user_query = """
            INSERT INTO users (email, password)
            VALUES (:email, :password)
            """
            await database.execute(create_user_query, {"email": temp_user['email'], "password": temp_user['password']})

        # Delete the temporary user
        delete_query = "DELETE FROM temp_users WHERE id = :id"
        await database.execute(delete_query, {"id": temp_user_id})

    return {"message": "User confirmed successfully"}


async def cleanup_temp_users(database=Depends(get_database)):
    expiration_time = datetime.now() - timedelta(hours=24)
    query = "DELETE FROM temp_users WHERE created_at <= :expiration_time"
    await database.execute(query=query, values={"expiration_time": expiration_time})


class PermanentUserCreate(BaseModel):
    uid: str
    email: str
    username: str
    full_name: str
    bio: str
    dob: Optional[str] = None


@router.post("/create-permanent-user")
async def create_permanent_user(user_data: PermanentUserCreate, database=Depends(get_database), current_user: dict = Depends(get_current_user)):
    if current_user['uid'] != user_data.uid:
        raise HTTPException(
            status_code=403, detail="Not authorized to create this user")

    print('user_data', user_data)

    try:
        # Convert the dob string to a datetime object if it's not None
        dob = datetime.strptime(
            user_data.dob, "%Y-%m-%d").date() if user_data.dob else None

        query = """
        INSERT INTO users (id, email, username, full_name, bio, dob)
        VALUES (:uid, :email, :username, :full_name, :bio, :dob)
        ON CONFLICT (id) DO UPDATE
        SET email = EXCLUDED.email,
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            bio = EXCLUDED.bio,
            dob = EXCLUDED.dob
        RETURNING id, email, username, full_name, bio, dob, avatar_url
        """
        values = {
            "uid": user_data.uid,
            "email": user_data.email,
            "username": user_data.username,
            "full_name": user_data.full_name,
            "bio": user_data.bio,
            "dob": dob
        }
        result = await database.fetch_one(query=query, values=values)

        if result:
            return dict(result)
        else:
            raise HTTPException(
                status_code=500, detail="Failed to create or update user")
    except ValueError as ve:
        print(f"Error parsing date: {str(ve)}")
        raise HTTPException(
            status_code=400, detail="Invalid date format for dob. Use YYYY-MM-DD.")
    except Exception as e:
        print(f"Error creating permanent user: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}")


class CompleteRegistrationModel(BaseModel):
    tempUserId: str
    firebaseUid: str


@router.post("/complete-registration")
async def complete_registration(
    data: CompleteRegistrationModel,
    database: Database = Depends(get_database)
):
    query = """
    UPDATE users
    SET firebase_uid = :firebase_uid, is_verified = TRUE
    WHERE id = :temp_user_id
    """
    values = {
        "firebase_uid": data.firebaseUid,
        "temp_user_id": data.tempUserId
    }

    try:
        await database.execute(query=query, values=values)
        return {"message": "Registration completed successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to complete registration: {str(e)}")


