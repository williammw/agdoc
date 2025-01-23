from .lifespan import app_lifespan
from app.routers import auth2_router, posts_router, recognize_router, search_router, umami_router, agi_router, dev_router, cdn_router, agents_router, auth_router, chat_router, cv_router, rag_router, live_stream_router, users_router, comment_router, videos_router, ws_router, grok_router, openai_router
# Add this import
from app.routers.multivio import linkedin_router, media_router, twitter_router, userinfo_router, content_router, facebook_router, instagram_router, threads_router, youtube_router, folders_router

from threadpoolctl import threadpool_limits
from dotenv import load_dotenv
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, HTTPException
import shutil
import subprocess
import os
import traceback
import logging
# os.environ["KMP_INIT_AT_FORK"] = "FALSE"


# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI(lifespan=app_lifespan, debug=True)
logger = logging.getLogger(__name__)

# CORS configuration
origins = [
    "http://localhost:5173",  # Vite default port
    "http://localhost:8000",  # FastAPI default port
    "https://235534.netlify.app",
    "https://umamiverse.netlify.app",
    "https://customer-ljfwh4kunvdrirzl.cloudflarestream.com",
    "https://umamiai.netlify.app",
    "ws://localhost:8000/api/v1/ws",
    "https://create-n-deploy.vercel.app",
    "https://api.x.ai/v1",
    "https://www.multivio.com",    
    "https://multivio.com",
    "https://dev.multivio.com",
    "https://dev.ohmeowkase.com",
    "https://5f8d2b54c46c795fe5d5e6209e3bbbf5.r2.cloudflarestorage.com",
    "https://jellyfish-app-ds6sv.ondigitalocean.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization", "Content-Type"],
    expose_headers=["*"]
)
# Add SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=os.getenv(
    'SESSION_SECRET_KEY', 'your_session_secret_key'))

# Router list
router_list = [
    (umami_router.router, "/api/v1/umami", ["umami"]),
    (agi_router.router, "/api/v1/agi", ["agi"]),
    (cdn_router.router, "/api/v1/cdn", ["cdn"]),
    (dev_router.router, "/api/v1/dev", ["dev"]),
    (agents_router.router, "/api/v1/agents", ["agents"]),
    (auth_router.router, "/api/v1/auth", ["auth"]),
    (auth2_router.router, "/api/v2/auth", ["auth"]),
    (chat_router.router, "/api/v1", ["chats"]),
    (cv_router.router, "/api/v1/cv", ["cv"]),
    (rag_router.router, "/api/v1/rag", ["rag"]),
    (live_stream_router.router, "/api/v1/live-stream", ["live-stream"]),
    (users_router.router, "/api/v1/users", ["users"]),
    (posts_router.router, "/api/v1/posts", ["posts"]),
    (comment_router.router, "/api/v1/comments", ["comments"]),
    (videos_router.router, "/api/v1/videos", ["videos"]),
    (grok_router.router, "/api/v1/grok", ["grok"]),
    (openai_router.router, "/api/v1/openai", ["openai"]),
    (ws_router.router, "/api/v1/ws", ["websocket"]),
    (twitter_router.router, "/api/v1/twitter", ["twitter"]),
    (linkedin_router.router, "/api/v1/linkedin", ["linkedin"]),
    (youtube_router.router, "/api/v1/youtube", ["youtube"]),
    # Add the new user info router
    (userinfo_router.router, "/api/v1/multivio/user-info", ["userinfo"]),
    (content_router.router, "/api/v1/content", ["content"]),
    (facebook_router.router, "/api/v1/facebook", ["facebook"]),
    (instagram_router.router, "/api/v1/instagram", ["instagram"]),
    
    (folders_router.router, "/api/v1/folders", ["folders"]),
    (media_router.router, "/api/v1/media", ["media"]),
]
for router, prefix, tags in router_list:
    app.include_router(router, prefix=prefix, tags=tags)

from app.routers.multivio.content_router import router as content_router
app.include_router(content_router, prefix="/api", tags=["content"])

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again later."}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.get("/")
async def greeting():
    return {"message": "Nothing to see here. v0.2.1"}


@app.get("/check-ffmpeg")
async def check_ffmpeg():
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        return {"status": "FFmpeg not found in PATH"}

    try:
        result = subprocess.run(
            [ffmpeg_path, '-version'], capture_output=True, text=True)
        return {
            "status": "FFmpeg found",
            "path": ffmpeg_path,
            "version": result.stdout
        }
    except Exception as e:
        return {
            "status": "FFmpeg found but execution failed",
            "error": str(e)
        }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    with threadpool_limits(limits=1, user_api='openmp'):
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)