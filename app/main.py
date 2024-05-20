# main.py
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
    "http://192.168.1.2:5173",
    "http://192.168.1.2:8000"
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


router_list = [
    (umami_router, "/api/v1/umami", ["umami"]),
    (agi_router, "/api/v1/agi", ["agi"]),
    (cdn_router, "/api/v1/cdn", ["cdn"]),
    (dev_router, "/api/v1/dev", ["dev"]),
    # (tvibkr_router, "/api/v1/tvibkr", []),
    (agents_router, "/api/v1/agents", ["agents"]),
    # Uncomment once auth is properly configured
    # (auth_router, "/api/v1/auth", ["auth"]),
    (chat_router, "/api/v1", ["chats"]),
]

for router, prefix, tags in router_list:
    app.include_router(router.router, prefix=prefix, tags=tags)

@app.get("/")
async def greeting():
    return {"message": "Hello from  MEE API!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


