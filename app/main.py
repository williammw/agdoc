
from fastapi import FastAPI
# Your database and router imports remain the same
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.routers import umami_router, agi_router, dev_router, cdn_router, tvibkr_router, agents_router, auth_router, chat_router
from .lifespan import app_lifespan
from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env file
app = FastAPI(lifespan=app_lifespan)


# CORS configuration
origins = [
    "http://localhost:5173",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=os.getenv(
    'SESSION_SECRET_KEY', 'your_session_secret_key'))

app.include_router(umami_router.router, prefix="/api/v1/umami", tags=["umami"])
app.include_router(agi_router.router, prefix="/api/v1/agi", tags=["agi"])
app.include_router(cdn_router.router, prefix="/api/v1/cdn", tags=["cdn"])
app.include_router(dev_router.router, prefix="/api/v1/dev", tags=["dev"])
app.include_router(tvibkr_router.router, prefix="/api/v1/tvibkr", )
app.include_router(agents_router.router, prefix="/api/v1/agents")
# app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(chat_router.router, prefix="/api/v1", tags=["chats"])

@app.get("/")
async def greeting():
    return {"message": "Hello from  MEE API!"}






