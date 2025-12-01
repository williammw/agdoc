# Multivio Backend API Documentation

## 📚 Documentation Overview

This documentation provides comprehensive technical reference for the **agdoc** FastAPI backend that powers the Multivio social media management platform.

### 📁 Documentation Structure

| Document | Description |
|----------|-------------|
| **[PROJECT-OVERVIEW.md](./PROJECT-OVERVIEW.md)** | Complete project overview, architecture, and features |
| **[API-REFERENCE.md](./API-REFERENCE.md)** | Detailed API endpoints documentation |
| **[DATABASE-SCHEMA.md](./DATABASE-SCHEMA.md)** | Database tables, relationships, and migrations |
| **[AUTHENTICATION.md](./AUTHENTICATION.md)** | Authentication system, OAuth flows, and security |
| **[SOCIAL-PLATFORMS.md](./SOCIAL-PLATFORMS.md)** | Social media integrations and publishing |
| **[AI-ENDPOINTS.md](./AI-ENDPOINTS.md)** | AI content generation and transformation |
| **[DEPLOYMENT.md](./DEPLOYMENT.md)** | Deployment, configuration, and infrastructure |
| **[DEVELOPMENT.md](./DEVELOPMENT.md)** | Development setup, testing, and contribution |

### 🚀 Quick Start

1. **Read the Project Overview** - Understand the system architecture
2. **Check API Reference** - Find specific endpoint documentation
3. **Review Authentication** - Understand auth flows and security
4. **See Deployment Guide** - Learn about production setup

### 🎯 Key Features Documented

- **Multi-Platform Social Media Integration**: Twitter/X, Facebook, Instagram, LinkedIn, YouTube, TikTok, Threads
- **AI-Powered Content Generation**: Grok AI integration for content creation and transformation
- **Dual OAuth Architecture**: OAuth 2.0 + OAuth 1.0a support for Twitter media uploads
- **Unified Posts System**: Single API for managing content across all platforms
- **Enterprise Scheduling**: Background job processing with APScheduler
- **Token Management**: Automatic refresh and health monitoring
- **Multi-Account Support**: Multiple accounts per platform with proper isolation

### 🛠️ Technology Stack

**Backend Framework:**
- FastAPI (Python 3.11+) - High-performance async web framework
- Pydantic - Data validation and serialization
- SQLAlchemy - Database ORM

**Database & Storage:**
- Supabase PostgreSQL - Primary database with Row Level Security
- Redis - Caching and session storage
- Cloudflare R2 - Media file storage

**External Integrations:**
- Firebase Admin SDK - User authentication
- Grok AI (xAI) - Content generation
- Stripe - Subscription management
- Social Media APIs - Platform-specific integrations

**Infrastructure:**
- Docker - Containerization
- DigitalOcean App Platform - Production hosting
- Celery - Background task processing
- APScheduler - Job scheduling

### 🔧 Development Resources

**Quick Commands:**
```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
python test_ai_endpoints.py
python test_oauth1_endpoints.py
```

**Key Files:**
- `app/main.py` - FastAPI application entry point
- `app/routers/` - API endpoint definitions
- `app/models/` - Pydantic data models
- `app/services/` - Business logic services
- `app/utils/` - Utility functions

### 📞 Support & Resources

**Primary Documentation:**
- [Main README.md](../README.md) - Project overview and setup
- [CLAUDE.md](../CLAUDE.md) - Development guidance for AI assistants

**API Documentation:**
- Swagger UI: `http://localhost:8000/docs` (development)
- ReDoc: `http://localhost:8000/redoc` (development)
- OpenAPI Schema: `http://localhost:8000/openapi.json`

**Testing:**
- AI Endpoints: `python test_ai_endpoints.py`
- OAuth1 Flow: `python test_oauth1_endpoints.py`

---

**Version**: 3.0.1
**Last Updated**: September 2025
**API Status**: Production Ready ✅
