from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# Import custom middleware
from app.middleware.https_redirect import ProxyHeadersMiddleware

# Load environment variables first, before importing other modules
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("Environment variables loaded in main.py")
except ImportError:
    print("python-dotenv not installed")

# Import our routers
from app.routers import auth, social_connections, subscriptions, media, ai
from app.routers import content_simple as content
from app.routers import posts_unified, scheduling

# Import database initialization function
from app.utils.database import initialize_database

app = FastAPI(
    title="Multivio API",
    description="API for Multivio",
    version="1.0.0",
    # Important for DigitalOcean App Platform - ensures HTTPS URLs
    root_path="",
    servers=[
        {"url": "https://jellyfish-app-ds6sv.ondigitalocean.app", "description": "Production"},
        {"url": "https://dev.ohmeowkase.com", "description": "Development"},
    ]
)

# IMPORTANT: Add ProxyHeaders middleware FIRST (before other middleware)
# This fixes HTTPS redirect issues on DigitalOcean App Platform
app.add_middleware(ProxyHeadersMiddleware)

# Add TrustedHost middleware to handle proxy headers
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "jellyfish-app-ds6sv.ondigitalocean.app",
        "dev.ohmeowkase.com",
        "localhost",
        "127.0.0.1"
    ]
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
app.include_router(scheduling.router)  # Enterprise scheduling system
app.include_router(media.router)
app.include_router(media.public_router)
app.include_router(ai.router)  # AI content generation and transformation

@app.get("/")
async def root():
    return {"message": "Welcome to Multivio API v3.0.1"}

@app.get("/health")
async def health():
    """Health check endpoint"""
    health_status = {
        "status": "healthy",
        "version": "3.0.1",
        "api": "Multivio API",
        "environment": "production",
        "database": "unknown"
    }
    
    # Test database connection
    try:
        from app.utils.database import get_db
        # Try to get a database connection
        db = await get_db().__anext__()
        if db:
            health_status["database"] = "connected"
        await db.close()
    except Exception as e:
        health_status["database"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status

@app.on_event("startup")
async def on_startup():
    """Initialize the database on startup"""
    await initialize_database() 