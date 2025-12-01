# Multivio Backend API - Project Overview

## 🎯 System Purpose

The **agdoc** backend is a comprehensive FastAPI-based API server that powers the Multivio social media management platform. It provides enterprise-grade social media publishing capabilities with AI-powered content generation, multi-platform OAuth integration, and advanced scheduling features.

### Core Capabilities

- **🤖 AI-Powered Content**: Generate and transform content using Grok AI
- **🌐 Multi-Platform Publishing**: Post to 7+ social media platforms simultaneously
- **🔐 Enterprise Authentication**: Firebase-based auth with OAuth integrations
- **📅 Advanced Scheduling**: Background job processing and queue management
- **💾 Unified Content Management**: Single API for all content operations
- **🔄 Token Management**: Automatic refresh and health monitoring
- **👥 Multi-Account Support**: Multiple accounts per platform with proper isolation

---

## 🏗️ System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MULTIVIO BACKEND API                           │
│                        (agdoc - FastAPI Server)                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL INTEGRATIONS                           │
│   ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐      │
│   │Twitter│Facebook│Instagram│LinkedIn│YouTube│TikTok│Threads│Stripe│     │
│   └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           BUSINESS LOGIC LAYER                          │
│   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │
│   │Auth Service │ │Content      │ │Platform    │ │AI Service   │       │
│   │             │ │Publisher    │ │Publisher   │ │             │       │
│   └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           DATA ACCESS LAYER                             │
│   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │
│   │PostgreSQL   │ │Redis Cache  │ │Cloudflare  │ │Firebase     │       │
│   │(Supabase)   │ │             │ │R2 Storage  │ │Admin SDK    │       │
│   └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Application Structure

```
app/
├── main.py                    # FastAPI application entry point
├── routers/                   # API endpoint definitions
│   ├── auth.py               # Authentication & OAuth endpoints
│   ├── social_connections.py # Social media connection management
│   ├── posts_unified.py      # Unified content posting system
│   ├── ai.py                 # AI content generation endpoints
│   ├── scheduling.py         # Post scheduling system
│   ├── media.py              # Media upload/management
│   └── subscriptions.py      # Stripe billing integration
├── models/                    # Pydantic data models
│   ├── users.py              # User profile models
│   ├── ai.py                 # AI-related models
│   ├── content.py            # Content models
│   └── social_connections.py # Social connection models
├── services/                  # Business logic services
│   ├── ai_service.py         # Grok AI integration
│   ├── platform_publisher.py # Multi-platform publishing
│   └── background_scheduler.py # Background job processing
├── utils/                     # Utility functions
│   ├── database.py           # Database connection management
│   ├── encryption.py         # Token encryption/decryption
│   ├── firebase.py           # Firebase Admin SDK utilities
│   └── email.py              # Email service utilities
├── dependencies/              # FastAPI dependencies
│   └── auth.py               # Authentication guards
├── middleware/                # Custom middleware
│   └── https_redirect.py     # HTTPS redirect middleware
└── core/                      # Core functionality
    └── oauth/                 # OAuth configurations
```

---

## 🔧 Technology Stack

### Core Framework
- **FastAPI 0.111.1+** - High-performance async web framework
- **Python 3.11+** - Modern Python with advanced async features
- **Pydantic** - Data validation and serialization
- **SQLAlchemy** - Database ORM and query building

### Database & Caching
- **Supabase PostgreSQL** - Primary database with Row Level Security
- **Redis** - Session storage, caching, and background job queues
- **Cloudflare R2** - Media file storage with CDN delivery

### Authentication & Security
- **Firebase Admin SDK** - User authentication and token verification
- **JWT Tokens** - Session management with secure claims
- **OAuth 2.0/1.0a** - Social media platform authentication
- **Encryption** - AES-256 encryption for sensitive tokens

### External Integrations
- **Grok AI (xAI)** - Advanced content generation and transformation
- **Stripe** - Subscription management and billing
- **Social Media APIs** - Platform-specific publishing APIs
- **SendGrid/Mailgun/Resend** - Multi-provider email service

### Development & Deployment
- **Docker** - Containerization for consistent deployments
- **Celery** - Distributed task queue for background processing
- **APScheduler** - Lightweight job scheduling
- **DigitalOcean App Platform** - Production hosting and scaling

---

## 🌟 Key Features

### 1. 🤖 AI-Powered Content Generation

**Capabilities:**
- Content transformation for different platforms and tones
- Original content generation from prompts
- Platform-specific optimization (Twitter, LinkedIn, Facebook, etc.)
- Hashtag suggestions and call-to-action integration
- Streaming responses for real-time content generation

**Technical Implementation:**
- Grok AI integration with multiple model support
- Async HTTP client with connection pooling
- Platform-specific prompt engineering
- Comprehensive error handling and fallbacks

### 2. 🌐 Multi-Platform Social Media Integration

**Supported Platforms:**
- **Twitter/X**: OAuth 2.0 + OAuth 1.0a dual architecture
- **Facebook**: Graph API with multi-account support
- **Instagram**: Business API integration
- **LinkedIn**: Pages API with organization support
- **YouTube**: Data API v3 integration
- **TikTok**: TikTok for Developers API
- **Threads**: Meta Threads API

**Features:**
- Multi-account support per platform
- Automatic token refresh and health monitoring
- Platform-specific content adaptation
- Real-time publishing status updates

### 3. 🔐 Enterprise Authentication System

**Authentication Methods:**
- Firebase email/password authentication
- Google OAuth integration
- Social media OAuth for account connections
- JWT-based session management

**Security Features:**
- Row Level Security (RLS) in PostgreSQL
- Encrypted token storage
- Rate limiting and abuse protection
- CORS configuration for frontend domains

### 4. 📅 Advanced Scheduling System

**Scheduling Capabilities:**
- Immediate publishing
- Scheduled posts with date/time selection
- Bulk scheduling operations
- Timezone-aware scheduling
- Queue management with retry logic

**Technical Implementation:**
- APScheduler for job scheduling
- Background task processing
- Queue persistence and recovery
- Analytics and performance monitoring

### 5. 💾 Unified Content Management

**Content System:**
- Single posts table for all content types
- Platform-specific content variants
- Media file management with Cloudflare R2
- Content versioning and history
- Auto-save functionality

**Database Design:**
- JSONB columns for flexible metadata
- Efficient indexing for performance
- Foreign key relationships for data integrity
- Migration system for schema evolution

---

## 🔄 Data Flow Architecture

### Content Creation Flow

```
User Input → Content Editor → Auto-Save → Database Storage
      ↓              ↓              ↓              ↓
   Frontend → API Validation → Business Logic → PostgreSQL
      ↓              ↓              ↓              ↓
   Response ← Error Handling ← Processing ← Persistence
```

### Publishing Flow

```
Post Request → Platform Selection → Token Validation → API Calls
      ↓              ↓              ↓              ↓
   Scheduling → Queue Processing → Platform APIs → Status Updates
      ↓              ↓              ↓              ↓
   Database ← Error Handling ← Success/Failure ← Real-time Sync
```

### Authentication Flow

```
Login Request → Firebase Verification → JWT Generation → Session Creation
      ↓              ↓              ↓              ↓
   Frontend → API Gateway → Token Validation → Database Query
      ↓              ↓              ↓              ↓
   Protected ← RLS Policies ← User Context ← Profile Data
```

---

## 📊 Performance & Scalability

### Performance Optimizations

**Database Performance:**
- Indexed queries for common access patterns
- JSONB optimization for metadata queries
- Connection pooling with Supabase
- Query result caching

**API Performance:**
- Async/await throughout the application
- Connection pooling for external APIs
- Request deduplication
- Efficient serialization with Pydantic

**Caching Strategy:**
- Redis for session storage and temporary data
- Application-level caching for frequently accessed data
- CDN integration for media assets

### Scalability Features

**Horizontal Scaling:**
- Stateless API design
- Redis-based session storage
- Background job processing with Celery
- Database read replicas (future)

**Load Balancing:**
- Multiple worker processes
- Request distribution across instances
- Queue-based processing for heavy operations

---

## 🚀 Deployment & Infrastructure

### Development Environment
```
Local Development:
├── uvicorn --reload --host 0.0.0.0 --port 8000
├── PostgreSQL via Supabase
├── Redis for caching
└── Local file storage for media
```

### Production Environment
```
DigitalOcean App Platform:
├── Containerized FastAPI application
├── Managed PostgreSQL database
├── Redis for caching and queues
├── Cloudflare R2 for media storage
└── Automatic scaling and health monitoring
```

### CI/CD Pipeline
```
Git Push → GitHub Actions → Testing → Docker Build → Deploy
    ↓           ↓              ↓          ↓            ↓
Source Code → Linting → Unit Tests → Container → Production
    ↓           ↓              ↓          ↓            ↓
Version Control → Code Quality → Coverage → Images → Live API
```

---

## 🔍 Monitoring & Observability

### Application Monitoring
- **Health Checks**: `/health` endpoint with database connectivity
- **Performance Metrics**: Response times and error rates
- **Background Jobs**: Queue status and job processing metrics
- **Token Health**: OAuth token expiration monitoring

### Logging Strategy
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Error Tracking**: Comprehensive error logging with stack traces
- **Audit Logging**: User actions and API calls tracking

### Error Handling
- **Graceful Degradation**: Fallbacks for external service failures
- **Retry Logic**: Exponential backoff for transient failures
- **User-Friendly Messages**: Sanitized error responses
- **Alerting**: Critical error notifications

---

## 🎯 Development Workflow

### Local Development Setup
```bash
# Clone repository
git clone <repository-url>
cd agdoc

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your configuration

# Run database migrations
python app/db/init_db.py

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Testing Strategy
```bash
# Run AI endpoint tests
python test_ai_endpoints.py

# Run OAuth1 flow tests
python test_oauth1_endpoints.py

# API documentation
# Swagger UI: http://localhost:8000/docs
# ReDoc: http://localhost:8000/redoc
```

### Code Quality
```bash
# Code formatting
black .
isort .

# Type checking
mypy app/

# Linting
flake8 app/
```

---

## 📈 Future Roadmap

### Planned Enhancements

**Q4 2025:**
- GraphQL API layer for flexible queries
- Advanced analytics dashboard
- Real-time collaboration features
- Mobile app API optimization

**Q1 2026:**
- Kubernetes migration for advanced scaling
- Multi-region deployment
- Advanced AI features (content strategies, A/B testing)
- Integration marketplace

**Q2 2026:**
- Enterprise features (team management, approval workflows)
- White-label solution capabilities
- Advanced automation workflows
- API rate limit management

### Technical Debt & Improvements

**Performance:**
- Query optimization and database indexing
- Caching layer enhancements
- Background job queue optimization

**Security:**
- Advanced threat detection
- API key rotation automation
- Enhanced audit logging

**Reliability:**
- Circuit breaker patterns
- Service mesh implementation
- Disaster recovery procedures

---

## 🤝 Contributing

### Development Guidelines
1. Follow FastAPI best practices and async/await patterns
2. Write comprehensive type hints and Pydantic models
3. Include unit tests for new functionality
4. Update documentation for API changes
5. Follow conventional commit messages

### Code Review Process
1. Create feature branch from `main`
2. Implement changes with tests
3. Submit pull request with description
4. Code review and approval
5. Merge to `main` with CI/CD deployment

### Documentation Updates
- Update API documentation for endpoint changes
- Maintain accurate database schema documentation
- Keep deployment guides current
- Update troubleshooting guides for common issues

---

**Version**: 3.0.1
**Last Updated**: September 2025
**Status**: Production Ready ✅
