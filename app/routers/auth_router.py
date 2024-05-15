# from datetime import datetime, timedelta
# import os
# from typing import Optional

# from authlib.integrations.starlette_client import OAuth, OAuthError
# from fastapi import APIRouter, Depends, HTTPException, Request, status
# from fastapi.security import OAuth2PasswordBearer
# from jose import JWTError, jwt
# from passlib.context import CryptContext
# from pydantic import BaseModel
# from starlette.responses import RedirectResponse

# from app.database import database
# from app.dependencies import get_user
# from app.models.models import User

# router = APIRouter()

# # Password hashing
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# # JWT settings
# SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
# ALGORITHM = "HS256"
# ACCESS_TOKEN_EXPIRE_MINUTES = 30

# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# # Initialize OAuth
# oauth = OAuth()
# oauth.register(
#     name='google',
#     client_id=os.getenv('GOOGLE_CLIENT_ID'),
#     client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
#     server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
#     client_kwargs={'scope': 'openid email profile'},
# )


# class UserCreate(BaseModel):
#     username: str
#     email: str
#     password: str


# class UserLogin(BaseModel):
#     username: str
#     password: str


# class Token(BaseModel):
#     access_token: str
#     token_type: str


# class TokenData(BaseModel):
#     username: Optional[str] = None


# def verify_password(plain_password, hashed_password):
#     return pwd_context.verify(plain_password, hashed_password)


# def get_password_hash(password):
#     return pwd_context.hash(password)


# def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
#     to_encode = data.copy()
#     if expires_delta:
#         expire = datetime.utcnow() + expires_delta
#     else:
#         expire = datetime.utcnow() + timedelta(minutes=15)
#     to_encode.update({"exp": expire})
#     encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
#     return encoded_jwt


# async def get_current_user(token: str = Depends(oauth2_scheme)):
#     credentials_exception = HTTPException(
#         status_code=status.HTTP_401_UNAUTHORIZED,
#         detail="Could not validate credentials",
#         headers={"WWW-Authenticate": "Bearer"},
#     )
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         username: str = payload.get("sub")
#         if username is None:
#             raise credentials_exception
#         token_data = TokenData(username=username)
#     except JWTError:
#         raise credentials_exception
#     user = await get_user(username=token_data.username)
#     if user is None:
#         raise credentials_exception
#     return user


# @router.post("/register", response_model=UserCreate)
# async def register(user: UserCreate):
#     user_in_db = await get_user(user.username)
#     if user_in_db:
#         raise HTTPException(
#             status_code=400, detail="Username already registered")
#     hashed_password = get_password_hash(user.password)
#     query = "INSERT INTO users (username, email, hashed_password) VALUES (:username, :email, :hashed_password)"
#     values = {"username": user.username, "email": user.email,
#               "hashed_password": hashed_password}
#     await database.execute(query=query, values=values)
#     return user


# @router.post("/login", response_model=Token)
# async def login(user: UserLogin):
#     user_in_db = await get_user(user.username)
#     if not user_in_db:
#         raise HTTPException(
#             status_code=400, detail="Incorrect username or password")
#     if not verify_password(user.password, user_in_db["hashed_password"]):
#         raise HTTPException(
#             status_code=400, detail="Incorrect username or password")
#     access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
#     access_token = create_access_token(
#         data={"sub": user.username}, expires_delta=access_token_expires)
#     return {"access_token": access_token, "token_type": "bearer"}


# @router.get("/me", response_model=UserCreate)
# async def read_users_me(current_user: User = Depends(get_current_user)):
#     return current_user


# @router.get('/login/google')
# async def login(request: Request):
#     redirect_uri = request.url_for('auth')
#     return await oauth.google.authorize_redirect(request, redirect_uri)


# @router.get('/auth')
# async def auth(request: Request):
#     try:
#         token = await oauth.google.authorize_access_token(request)
#         user_info = await oauth.google.parse_id_token(request, token)
#     except OAuthError as error:
#         raise HTTPException(status_code=400, detail=str(error))

#     user = await get_user(user_info['email'])
#     if not user:
#         query = "INSERT INTO users (username, email, hashed_password, is_active) VALUES (:username, :email, '', true)"
#         values = {"username": user_info['name'], "email": user_info['email']}
#         await database.execute(query=query, values=values)
#         user = await get_user(user_info['email'])

#     access_token = create_access_token(data={"sub": user_info['email']})
#     response = RedirectResponse(
#         url=f'http://localhost:5173?name={user_info["name"]}&email={user_info["email"]}&picture={user_info["picture"]}')
#     response.set_cookie(key="access_token",
#                         value=f"Bearer {access_token}", httponly=True)
#     return response


# @router.post("/auth/google")
# async def google_auth(request: Request):
#     body = await request.json()
#     token = body.get('token')
#     try:
#         user_info = oauth.google.parse_id_token(token)
#     except Exception as e:
#         raise HTTPException(status_code=400, detail="Invalid token")

#     user = await get_user(user_info['email'])
#     if not user:
#         query = "INSERT INTO users (username, email, hashed_password, is_active) VALUES (:username, :email, '', true)"
#         values = {"username": user_info['name'], "email": user_info['email']}
#         await database.execute(query=query, values=values)
#         user = await get_user(user_info['email'])

#     access_token = create_access_token(data={"sub": user_info['email']})
#     return {"access_token": access_token, "token_type": "bearer"}


# @router.get("/auth/google/callback")
# async def handle_google_callback(request: Request):
#     token = await oauth.google.authorize_access_token(request)
#     # Process the token, e.g., retrieve user info and create a session
#     # Redirect to frontend or a dashboard
#     return RedirectResponse(url='/some-frontend-route')
