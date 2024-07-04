from .lifespan import app_lifespan
from app.routers import umami_router, agi_router, dev_router, cdn_router, tvibkr_router, agents_router, auth_router, chat_router, cv_router, rag_router
from threadpoolctl import threadpool_limits
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
import os
os.environ["KMP_INIT_AT_FORK"] = "FALSE"


# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI(lifespan=app_lifespan)

# CORS configuration
origins = [
    "http://localhost:5173",
    "http://localhost:8000",
    "http://192.168.1.2:5173",
    "http://192.168.1.2:8000",
    "https://235534.netlify.app",
    "https://umamiverse.netlify.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this to your frontend's URL in production
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
    (chat_router, "/api/v1", ["chats"]),
    (cv_router, "/api/v1/cv", ["cv"]),
    (rag_router, "/api/v1/rag", ["rag"]),
]

for router, prefix, tags in router_list:
    app.include_router(router.router, prefix=prefix, tags=tags)


@app.get("/")
async def greeting():
    return {"message": "Nothing to see here."}

if __name__ == "__main__":
    with threadpool_limits(limits=1, user_api='openmp'):
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
