from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.models.models import User
from app.database import database
from app.dependencies import get_user, get_current_user
from typing import Optional
router = APIRouter()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[str] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now() + expires_delta
    else:
        expire = datetime.now() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


@router.post("/register", response_model=UserCreate)
async def register(user: UserCreate):
    user_in_db = await get_user(user.username)
    if user_in_db:
        raise HTTPException(
            status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    query = "INSERT INTO users (username, email, hashed_password) VALUES (:username, :email, :hashed_password)"
    values = {"username": user.username, "email": user.email,
              "hashed_password": hashed_password}
    await database.execute(query=query, values=values)
    return user


@router.post("/login", response_model=Token)
async def login(user: UserLogin):
    user_in_db = await get_user(user.username)
    if not user_in_db:
        raise HTTPException(
            status_code=400, detail="Incorrect username or password")
    if not verify_password(user.password, user_in_db["hashed_password"]):
        raise HTTPException(
            status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserCreate)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
