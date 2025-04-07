from .lifespan import app_lifespan
from app.routers import auth2_router, posts_router, recognize_router, search_router, umami_router, agi_router, dev_router, cdn_router, agents_router, auth_router, cv_router, live_stream_router, users_router, comment_router, videos_router, ws_router, openai_router, session_router, session_router
# Add this import
# Import individual router modules from multivio directory
from app.routers.multivio.grok_router import router as grok_router
from app.routers.multivio.linkedin_router import router as linkedin_router
from app.routers.multivio.media_router import router as media_router
from app.routers.multivio.twitter_router import router as twitter_router
from app.routers.multivio.userinfo_router import router as userinfo_router
from app.routers.multivio.chat_router import router as chat_router
from app.routers.multivio.facebook_router import router as facebook_router
from app.routers.multivio.instagram_router import router as instagram_router
from app.routers.multivio.threads_router import router as threads_router
from app.routers.multivio.youtube_router import router as youtube_router
from app.routers.multivio.folders_router import router as folders_router
from app.routers.multivio.recycle_router import router as recycle_router
from app.routers.multivio.together_router import router as together_router
from app.routers.multivio.smart_router import router as smart_router
from app.routers.multivio.general_router import router as general_router
from app.routers.multivio.brave_search_router import router as brave_search_router
from app.routers.multivio.direct_search_router import router as direct_search_router
from app.routers.multivio.websearch_router import router as websearch_router
from app.routers.multivio.puppeteer_router import router as puppeteer_router
from app.routers.multivio.pipeline_router import router as pipeline_router
from app.routers.multivio.patreon_router import router as patreon_router
from app.routers.multivio.intent_feedback_router import router as intent_feedback_router
from app.routers.multivio.feedback_router import router as feedback_router

from threadpoolctl import threadpool_limits
from dotenv import load_dotenv
import sys
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

# Check for required API keys
required_keys = {
    "BRAVE_API_KEY": "Brave Web Search - required for web search functionality",
    "PATREON_CLIENT_ID": "Patreon OAuth - required for Patreon integration",
    "PATREON_CLIENT_SECRET": "Patreon OAuth - required for Patreon integration",
    "PATREON_REDIRECT_URI": "Patreon OAuth - required for Patreon integration"
    # Add other required keys here as needed
}

missing_keys = []
for key, description in required_keys.items():
    if not os.getenv(key):
        missing_keys.append(f"{key}: {description}")
        
if missing_keys:
    print("\n⚠️  WARNING: Missing required API keys ⚠️")
    print("The following environment variables are missing:")
    for key in missing_keys:
        print(f"  - {key}")
    print("Some functionality may be limited.\n")

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

# Updated SessionMiddleware with better settings
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv('SESSION_SECRET_KEY', 'your_session_secret_key'),
    max_age=3600,  # 1 hour session timeout
    same_site="lax",  # Better security
    https_only=True  # Force secure cookies in production
)

# Router list (updated to include the session router)
router_list = [
    (umami_router.router, "/api/v1/umami", ["umami"]),
    (agi_router.router, "/api/v1/agi", ["agi"]),
    (cdn_router.router, "/api/v1/cdn", ["cdn"]),
    (dev_router.router, "/api/v1/dev", ["dev"]),
    (agents_router.router, "/api/v1/agents", ["agents"]),
    (auth_router.router, "/api/v1/auth", ["auth"]),
    (auth2_router.router, "/api/v2/auth", ["auth"]),
    (chat_router, "/api/v1/chat", ["chat"]),
    (cv_router.router, "/api/v1/cv", ["cv"]),
    # (rag_router.router, "/api/v1/rag", ["rag"]),
    (live_stream_router.router, "/api/v1/live-stream", ["live-stream"]),
    (users_router.router, "/api/v1/users", ["users"]),
    (posts_router.router, "/api/v1/posts", ["posts"]),
    (comment_router.router, "/api/v1/comments", ["comments"]),
    (videos_router.router, "/api/v1/videos", ["videos"]),
    (grok_router, "/api/v1/grok", ["grok"]),
    (openai_router.router, "/api/v1/openai", ["openai"]),
    (ws_router.router, "/api/v1/ws", ["websocket"]),
    (twitter_router, "/api/v1/twitter", ["twitter"]),
    (linkedin_router, "/api/v1/linkedin", ["linkedin"]),
    (youtube_router, "/api/v1/youtube", ["youtube"]),
    # Add the new user info router
    (userinfo_router, "/api/v1/multivio/user-info", ["userinfo"]),
    (facebook_router, "/api/v1/facebook", ["facebook"]),
    (instagram_router, "/api/v1/instagram", ["instagram"]),
    (recycle_router, "/api/v1/recycle", ["recycle"]),
    (folders_router, "/api/v1/folders", ["folders"]),
    (media_router, "/api/v1/media", ["media"]),
    (threads_router, "/api/v1/threads", ["threads"]),
    (together_router, "/api/v1/together", ["together"]),
    (smart_router, "/api/v1/smart", ["smart"]),
    (general_router, "/api/v1/general", ["general"]),
    (brave_search_router, "/api/v1/brave-search", ["brave_search"]),
    (direct_search_router, "/api/v1/direct-search", ["direct_search"]),
    (websearch_router, "/api/v1/websearch", ["websearch"]),
    (puppeteer_router, "/api/v1/puppeteer", ["puppeteer"]),
    (pipeline_router, "/api/v1/pipeline", ["pipeline"]),
    (patreon_router, "/api/v1/patreon", ["patreon"]),
    (intent_feedback_router, "/api/v1/intent-feedback", ["intent_feedback"]),
    (feedback_router, "/api/v1/feedback", ["feedback"]),
    (session_router.router, "/api/v1/session", ["session"]),  # Add the session router
]
for router, prefix, tags in router_list:
    app.include_router(router, prefix=prefix, tags=tags)

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
    return {"message": "Nothing to see here. v0.2.2"}


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