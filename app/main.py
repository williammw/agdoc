from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import our routers
from app.routers import auth, social_connections, subscriptions, media, ai
from app.routers import content_simple as content
from app.routers import posts_unified, twitter_test

# Import database initialization function
from app.utils.database import initialize_database

app = FastAPI(
    title="Multivio API",
    description="API for Multivio",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    # Allow specific origins
    # In production, use a specific list of allowed origins
    allow_origins=[
        "http://localhost:3000",  # Local frontend dev
        "http://localhost:5173",  # Vite dev server
        "https://dev.multivio.com",  # Development frontend
        "https://multivio.com",  # Production frontend
        "https://www.multivio.com",  # Production frontend with www
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(social_connections.router)
app.include_router(subscriptions.router)
app.include_router(content.router)  # Keep old router for backward compatibility
app.include_router(posts_unified.router)  # New unified posts API
app.include_router(media.router)
app.include_router(media.public_router)
app.include_router(ai.router)  # AI content generation and transformation
app.include_router(twitter_test.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "Welcome to Multivio API v2.2.0 "}

@app.on_event("startup")
async def on_startup():
    """Initialize the database on startup"""
    await initialize_database() 