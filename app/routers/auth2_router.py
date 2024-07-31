from fastapi import Depends, File, Form, HTTPException, Header, UploadFile
import logging
from fastapi import APIRouter, HTTPException, Depends, Response, Header, logger
from firebase_admin import auth as firebase_auth
from firebase_admin import firestore
from app.dependencies import get_current_user, get_database
from databases import Database
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, date
from email.message import EmailMessage
import smtplib
import os
import secrets
import io
from PIL import Image
import re
from app.routers.cdn_router import upload_to_r2


def clean_username(username):
    # Use regular expression to find all characters that are letters, numbers, or underscores
    cleaned_username = re.sub(r'[^a-zA-Z0-9_]', '', username)
    return cleaned_username

router = APIRouter()
logging.basicConfig(level=logging.INFO)


class EmailPasswordRegister(BaseModel):
    email: EmailStr
    password: str
    display_name: Optional[str] = None
    photo_url: Optional[str] = None


class PhoneRegister(BaseModel):
    phone_number: str
    verification_code: str
    display_name: Optional[str] = None
    photo_url: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    photo_url: Optional[str] = None
    disabled: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    username: Optional[str] = None
    email: Optional[str] = None
    auth_provider: str = None
    created_at: datetime
    is_active: bool 
    full_name: Optional[str] = None
    bio: Optional[str]
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None
    dob: Optional[date] = None
    cover_image: Optional[str] = None
    status: Optional[str] = None


    class Config:
        orm_mode = True



# async def get_current_user(authorization: str = Header(...)):
#     try:
#         token = authorization.split("Bearer ")[1]
#         decoded_token = firebase_auth.verify_id_token(token)
#         return {"uid": decoded_token['uid']}
#     except Exception as e:
#         raise HTTPException(
#             status_code=401, detail="Invalid authentication credentials")


async def create_user_in_db(db: Database, user: firebase_auth.UserRecord):
    query = """
    INSERT INTO users (id, email, phone_number, username, full_name, avatar_url, auth_provider, created_at, is_active)
    VALUES (:id, :email, :phone_number, :username, :full_name, :avatar_url, :auth_provider, :created_at, :is_active)
    """
    values = {
        "id": user.uid,
        "email": user.email,
        "phone_number": user.phone_number,
        "username": user.display_name or "",
        "full_name": user.display_name or "",
        "avatar_url": user.photo_url or "",
        "auth_provider": "firebase",
        "created_at": datetime.now(),
        "is_active": not user.disabled
    }
    await db.execute(query=query, values=values)


@router.post("/register/email")
async def register_with_email_password(user_data: EmailPasswordRegister, db: Database = Depends(get_database)):
    try:
        firebase_user = firebase_auth.create_user(
            email=user_data.email,
            password=user_data.password,
            display_name=user_data.display_name,
            photo_url=user_data.photo_url,
            email_verified=False
        )
        await create_user_in_db(db, firebase_user)
        return {"message": "User registered successfully", "uid": firebase_user.uid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/register/phone")
async def register_with_phone(user_data: PhoneRegister, db: Database = Depends(get_database)):
    try:
        # Verify the phone number with the verification code
        # This is a placeholder - you need to implement the actual verification logic
        # using Firebase Phone Authentication
        phone_number = firebase_auth.verify_phone_number(
            user_data.phone_number, user_data.verification_code)

        firebase_user = firebase_auth.create_user(
            phone_number=phone_number,
            display_name=user_data.display_name,
            photo_url=user_data.photo_url
        )
        await create_user_in_db(db, firebase_user)
        return {"message": "User registered successfully", "uid": firebase_user.uid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

#get user


@router.get("/user", response_model=UserResponse)
async def get_user(current_user: dict = Depends(get_current_user)):
    try:
        print("Current user data:", current_user)
        return UserResponse(**current_user)
    except Exception as e:
        print(f"Error in get_user: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error processing user data: {str(e)}")


@router.put("/user")
async def update_user(user_data: UserUpdate, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    print("user_data", user_data) 
    try:
        update_args = {k: v for k, v in user_data.model_dump().items()
                       if v is not None}
        firebase_user = firebase_auth.update_user(current_user['uid'], **update_args)

        # Update user in RDS
        query = """
        UPDATE users
        SET email = :email, phone_number = :phone_number, username = :username, 
            full_name = :full_name, avatar_url = :avatar_url, is_active = :is_active
        WHERE id = :id
        """
        # logger("update_user", firebase_user.uid)
        values = {
            "id": firebase_user.uid,
            "email": firebase_user.email,
            "phone_number": firebase_user.phone_number,
            "username": firebase_user.display_name or "",
            "full_name": firebase_user.display_name or "",
            "avatar_url": firebase_user.photo_url or "",
            "is_active": not firebase_user.disabled
        }
        await db.execute(query=query, values=values)
        print('put user', firebase_user.uid)
        return {"message": "User updated successfully", "uid": firebase_user.uid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class UnverifiedAccount(BaseModel):
    email: EmailStr
    firebase_uid: str
    email_verification_code: str



class VerifyEmail(BaseModel):
    oobCode: str





@router.post("/create-unverified-account")
async def create_unverified_account(account: UnverifiedAccount, db: Database = Depends(get_database)):
    try:
        query = """
        INSERT INTO users (id, email, auth_provider, created_at, is_active, email_verified, email_verification_code, email_verification_sent_at)
        VALUES (:id, :email, 'email', CURRENT_TIMESTAMP, true, false,:email_verification_code, CURRENT_TIMESTAMP)
        """
        values = {
            "id": account.firebase_uid,
            "email": account.email,
            "email_verification_code": account.email_verification_code
        }
        await db.execute(query=query, values=values)
        return {"message": "Unverified account created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



class VerifyEmailRequest(BaseModel):
    verification_code: str
    # firebase_uid: str

@router.post("/verify-email")
async def verify_email(verification: VerifyEmailRequest, db: Database = Depends(get_database)):
    try:
        # Verify the oobCode with Firebase Admin SDK
        # check_revoked = True
        # decoded_token = firebase_auth.verify_id_token(
        #     verification.oobCode, check_revoked=check_revoked)
        # uid = decoded_token['uid']

        # Update the user's email_verified status in your database
        query = """
        UPDATE users
        SET email_verified = true 
        WHERE  email_verification_code = :email_verification_code
        """

        values = {
            # "uid": verification.firebase_uid,
            "email_verification_code": verification.verification_code
        }
        await db.execute(query=query, values=values)

        return {"message": "Email verified successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Update the login endpoint to check email verification status
@router.post("/login")
async def login(current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    print('login', current_user)
    try:
        # Check if the email is verified
        query = "SELECT email_verified FROM users WHERE id = :user_id"
        updated_user = await db.fetch_one(query=query, values={"user_id": current_user['uid']})

        if not updated_user or not updated_user['email_verified']:
            raise HTTPException(
                status_code=403, detail="Email not verified. Please verify your email before logging in.")

        user_dict = dict(updated_user)
        print("Updated user data:", user_dict)  # Add this line for debugging


        q2 = """
        SELECT * from users where id = :user_id
        """
        user = await db.fetch_one(query=q2, values={"user_id": current_user['uid']})
        logged_user = dict(user)

        # Ensure all required fields are present
        user_response = {
            "id": logged_user["id"],
            "email": logged_user["email"],
            "auth_provider": logged_user["auth_provider"],
            "created_at": logged_user["created_at"],
            "is_active": logged_user["is_active"],
            "username": logged_user.get("username"),
            "full_name": logged_user.get("full_name"),
            "bio": logged_user.get("bio"),
            "avatar_url": logged_user.get("avatar_url"),
            "phone_number": logged_user.get("phone_number"),
            "dob": logged_user.get("dob"),
        }

        return UserResponse(**user_response)
    except Exception as e:
        print(f"Error in login: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {str(e)}")
    

@router.post("/logout")
async def logout(response: Response):
    # Clear the session cookie
    response.delete_cookie(key="session")
    return {"message": "Logged out successfully"}




# Login in with Google Account
@router.post("/google-login")
async def google_login(authorization: str = Header(...), db: Database = Depends(get_database)):
    try:
        # Verify the Firebase ID token
        id_token = authorization.split("Bearer ")[1]
        decoded_token = firebase_auth.verify_id_token(id_token)
        uid = decoded_token['uid']

        # Check if user exists in your database
        query = "SELECT * FROM users WHERE id = :uid"
        user = await db.fetch_one(query=query, values={"uid": uid})

        if not user:
            # If user doesn't exist, create a new entry
            firebase_user = firebase_auth.get_user(uid)
            insert_query = """
            INSERT INTO users (id, email, username, full_name, auth_provider, created_at, is_active, avatar_url)
            VALUES (:id, :email, :username, :full_name, 'google', :created_at, true, :avatar_url)
            RETURNING *
            """
            print('google login',firebase_user.display_name)
            values = {
                "id": uid,
                "email": firebase_user.email,
                "username": "",
                "full_name": firebase_user.display_name or "",
                "created_at": datetime.now(),
                "avatar_url": firebase_user.photo_url or ""
                
                
            }
            user = await db.fetch_one(query=insert_query, values=values)
        else:
            # Update last login
            update_query = """
            UPDATE users SET last_login = CURRENT_TIMESTAMP
            WHERE id = :uid
            RETURNING *
            """
            user = await db.fetch_one(query=update_query, values={"uid": uid})

        return {
            "id": user['id'],
            "email": user['email'],
            "username": user['username'],
            "full_name": user['full_name'],
            "avatar_url": user['avatar_url'],
            "auth_provider": user['auth_provider'],
            "cover_image": user['cover_image'],
            "status": user['status'],
            "bio": user['bio']
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class DisabledAccount(BaseModel):
    email: str
    firebase_uid: str


class ActivateAccount(BaseModel):
    oobCode: str


@router.post("/create-disabled-account")
async def create_disabled_account(account: DisabledAccount, db: Database = Depends(get_database)):
    print('create-disabled-account', account.email, account.firebase_uid)
    try:
        uid = account.firebase_uid
        email = account.email
        query = "SELECT * FROM users WHERE id = :uid"
        user = await db.fetch_one(query=query, values={"uid": uid})

        if not user:
            # If user doesn't exist, create a new entry
            firebase_user = firebase_auth.get_user(uid)
            insert_query = """
            INSERT INTO users (id, email, username, full_name, auth_provider, created_at, is_active, avatar_url)
            VALUES (:id, :email, :username, :full_name, 'email', :created_at, false, :avatar_url)
            RETURNING *
            """
            values = {
                "id": uid,
                "email": email,
                "username": "",
                "full_name":  "",
                "created_at": datetime.now(),
                "avatar_url":  ""
            }
            user = await db.fetch_one(query=insert_query, values=values)
        else:
            # Update last login
            update_query = """
            UPDATE users SET last_login = CURRENT_TIMESTAMP
            WHERE id = :uid
            RETURNING *
            """
            user = await db.fetch_one(query=update_query, values={"uid": uid})
        # Disable the user in Firebase
        print(account.firebase_uid)
        firebase_auth.update_user(
            account.firebase_uid,
            disabled=True
        )

        return {"message": "Disabled account created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/activate-account")
async def activate_account(activation: ActivateAccount):
    try:
        # Verify the oobCode with Firebase Admin SDK
        check_revoked = True
        decoded_token = firebase_auth.verify_id_token(
            activation.oobCode, check_revoked=check_revoked)
        uid = decoded_token['uid']

        # Enable the user in Firebase
        firebase_auth.update_user(
            uid,
            disabled=False
        )

        # Activate the user's account in your database
        # For example:
        # await db.activate_user(firebase_uid=uid)

        return {"message": "Account activated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def send_verification_email(email: str, token: str):
    msg = EmailMessage()
    msg.set_content(
        f"Click the following link to verify your email: http://localhost:5173/verify-email?token={token}")
    msg['Subject'] = "Verify your email"
    msg['From'] = "william.manwai@gmail.com"  # Replace with your Gmail address
    msg['To'] = email

    # Send the email using Gmail's SMTP server
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.set_debuglevel(1)  # Add this line to enable debug output
            server.ehlo()  # Can be omitted
            server.starttls()
            server.ehlo()  # Can be omitted
            server.login(
                "william.manwai@gmail.com",  # Replace with your Gmail address
                # Use an environment variable for the app password
                os.getenv("EMAIL_PASSWORD")
            )
            server.send_message(msg)
            print("Email sent successfully!")
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP Authentication Error: {e}")
        print("Please check your email and password.")
    except smtplib.SMTPException as e:
        print(f"SMTP Exception: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


@router.get("/test-email")
async def test_email():
  # print(os.getenv("EMAIL_PASSWORD"))
  test_email = "iamcheapcoder@gmail.com"

  # Generate a dummy token for testing
  
  test_token = secrets.token_urlsafe(32)

  # Set your Gmail app password as an environment variable
  # You can do this in your terminal before running the script:
  # export EMAIL_PASSWORD="your-app-password-here"

  try:
      send_verification_email(test_email, test_token)
  except Exception as e:
      print(f"An error occurred: {e}")


class UserCreate(BaseModel):
    firebaseUid: Optional[str] = None
    phoneNumber: Optional[str] = None
    username: Optional[str] = None
    fullName: Optional[str] = None


# async def create_user(user_data: UserCreate, current_user: dict = Depends(get_current_user),  db: Database = Depends(get_database)):


@router.post("/create-user")
async def create_user(user_data: UserCreate, authorization: str = Header(...), db: Database = Depends(get_database)):
    try:
        # Verify the Firebase token
        token = authorization.split("Bearer ")[1]
        decoded_token = firebase_auth.verify_id_token(
            token, check_revoked=True)
        firebase_uid = decoded_token['uid']

        # Ensure the Firebase UID matches the one in the request
        if firebase_uid != user_data.firebaseUid:
            raise HTTPException(status_code=403, detail="Unauthorized")

        query = """
        INSERT INTO users (id, phone_number, username, full_name)
        VALUES (:firebase_uid, :phone_number, :username, :full_name)
        RETURNING id
        """
        values = {
            "firebase_uid": firebase_uid,
            "phone_number": user_data.phoneNumber,
            "username": user_data.username,
            "full_name": user_data.fullName
        }

        user_id = await db.fetch_val(query=query, values=values)
        return {"id": user_id, "message": "User created successfully"}
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid Firebase token")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Database error: {str(e)}")


# https://pub-f807f542a88040d7a549c087eff40e12.r2.dev/EzrLXFNlmDO3izsWmavFt2hPQpe2/avatar/.jpg
# https://cdn.ohmeowkase.com/EzrLXFNlmDO3izsWmavFt2hPQpe2/avatar/.jpg


@router.post("/update-profile/{user_id}")
async def update_profile(
    user_id: str,
    username: str = Form(None),
    full_name: str = Form(None),
    bio: str = Form(None),
    status: str = Form(None),
    avatar_url: UploadFile = File(None),
    cover_image: UploadFile = File(None),
    current_user: dict = Depends(get_current_user),
    database: Database = Depends(get_database),
    authorization: str = Header(...)
):
    if current_user['uid'] != user_id:
        raise HTTPException(
            status_code=403, detail="Not authorized to update this profile")

    # Fetch current user data
    query = "SELECT * FROM users WHERE id = :user_id"
    current_user_data = await database.fetch_one(query=query, values={"user_id": user_id})

    update_data = {}
    if username is not None and username != current_user_data['username']:
        update_data['username'] = clean_username(username)
    if full_name is not None and full_name != current_user_data['full_name']:
        update_data['full_name'] = full_name
    if bio is not None and bio != current_user_data['bio']:
        update_data['bio'] = bio
    if status is not None and status != current_user_data['status']:
        if status not in ['available', 'busy', 'at_restaurant', 'cooking', 'food_coma']:
            raise HTTPException(status_code=400, detail="Invalid status")
        update_data['status'] = status

    if avatar_url:
        avatar_result = await upload_to_r2(avatar_url, database, authorization,'avatar')
        if avatar_result['url'] != current_user_data['avatar_url']:
            update_data['avatar_url'] = avatar_result['url']

    if cover_image:
        cover_result = await upload_to_r2(cover_image, database, authorization, 'cover')
        if cover_result['url'] != current_user_data['cover_image']:
            update_data['cover_image'] = cover_result['url']

    if not update_data:
        return {"message": "No changes detected", "user": current_user_data}

    set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
    query = f"""
    UPDATE users
    SET {set_clause}
    WHERE id = :user_id
    RETURNING *
    """

    values = {**update_data, 'user_id': user_id}
    updated_user = await database.fetch_one(query=query, values=values)

    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "Profile updated successfully", "user": updated_user}
