from .lifespan import app_lifespan
from app.routers import auth2_router, posts_router, recognize_router, search_router, umami_router, agi_router, dev_router, cdn_router, tvibkr_router, agents_router, auth_router, chat_router, cv_router, rag_router, live_stream_router, users_router, comment_router, videos_router
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
app = FastAPI(lifespan=app_lifespan)
logger = logging.getLogger(__name__)

# CORS configuration
origins = [
    "http://localhost:5173",
    # "http://localhost:8000",
    "http://192.168.1.3:5173",
    "http://192.168.1.2:8000",
    "https://235534.netlify.app",
    "https://umamiverse.netlify.app",
    "https://customer-ljfwh4kunvdrirzl.cloudflarestream.com",
    "https://bed5-185-245-239-88.ngrok-free.app",
    "https://umamiai.netlify.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Update this to your frontend's URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"], 
)
# Add SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=os.getenv(
    'SESSION_SECRET_KEY', 'your_session_secret_key'))

# Router list
router_list = [
    (umami_router, "/api/v1/umami", ["umami"]),
    (agi_router, "/api/v1/agi", ["agi"]),
    (cdn_router, "/api/v1/cdn", ["cdn"]),
    (dev_router, "/api/v1/dev", ["dev"]),
    (agents_router, "/api/v1/agents", ["agents"]),
    (auth_router, "/api/v1/auth", ["auth"]),
    (auth2_router, "/api/v2/auth", ["auth"]),
    (chat_router, "/api/v1", ["chats"]),
    (cv_router, "/api/v1/cv", ["cv"]),
    (rag_router, "/api/v1/rag", ["rag"]),
    (live_stream_router, "/api/v1/live-stream", ["live-stream"]),
    (users_router, "/api/v1/users", ["users"]),
    (posts_router, "/api/v1/posts", ["posts"]),
    (comment_router, "/api/v1/comments", ["comments"]),
    (videos_router, "/api/v1/videos", ["videos"]),
    # (recognize_router, "/api/v1/recognize", ["recognition"]),
    # (search_router, "/api/v1/search", ["search"]),
]

for router, prefix, tags in router_list:
    app.include_router(router.router, prefix=prefix, tags=tags)


# Global exception handler
# @app.exception_handler(Exception)
# async def global_exception_handler(request: Request, exc: Exception):
#     logger.error(f"Unhandled exception: {str(exc)}")
#     logger.error(traceback.format_exc())
#     return JSONResponse(
#         status_code=500,
#         content={"detail": "An unexpected error occurred. Please try again later."}
#     )






@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred."},
    )

@app.get("/")
async def greeting():
    return {"message": "Nothing to see here. v0.2.0"}


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


