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

# Import our routers - ONLY media and AI processing
from app.routers import media, ai

app = FastAPI(
    title="AGDOC Media Processing API",
    description="API for media processing and AI content generation",
    version="2.0.0",
    root_path="",
    servers=[
        {"url": "https://dev.ohmeowkase.com", "description": "Development"},
    ]
)

# IMPORTANT: Add ProxyHeaders middleware FIRST (before other middleware)
app.add_middleware(ProxyHeadersMiddleware)

# Add TrustedHost middleware to handle proxy headers
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "dev.ohmeowkase.com",
        "localhost",
        "127.0.0.1"
    ]
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
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

# Include routers - ONLY media and AI
app.include_router(media.router)
app.include_router(media.public_router)
app.include_router(ai.router)

@app.get("/")
async def root():
    return {
        "message": "AGDOC Media Processing API v2.0.0",
        "endpoints": {
            "media": "/api/v1/media",
            "ai": "/api/v1/ai",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "api": "AGDOC Media Processing API",
        "services": ["media", "ai"]
    }
