# Multivio API

A comprehensive **AI-powered social media management platform** built with FastAPI, featuring multi-platform publishing, intelligent content generation, n˜advanced scheduling, and enterprise-grade authentication.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.1-009688.svg)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-336791.svg)](https://supabase.com/)
[![Firebase](https://img.shields.io/badge/Firebase-Authentication-FFCA28.svg)](https://firebase.google.com/)

## 🚀 Features

### 🤖 AI-Powered Content Generation
- **Content Transformation**: Rewrite content for different platforms (Twitter, LinkedIn, Facebook, Instagram, Threads, YouTube, TikTok)
- **Tone Adjustment**: Professional, casual, humorous, engaging tones
- **Content Optimization**: Platform-specific formatting and length optimization
- **Hashtag Generation**: Intelligent hashtag suggestions
- **Streaming Responses**: Real-time content generation with streaming support
- **Grok AI Integration**: Powered by xAI's Grok for high-quality content

### 📱 Multi-Platform Social Media Management
- **Unified Posting**: Single interface for posting to multiple platforms simultaneously
- **Platform-Specific Content**: Customize content for each platform's unique requirements
- **OAuth Integration**: Seamless authentication with all major social platforms
- **Multi-Account Support**: Manage multiple accounts per platform
- **Real-time Publishing**: Instant publishing with status tracking

### 📅 Advanced Scheduling System
- **Enterprise Scheduling**: Background job processing with APScheduler
- **Bulk Operations**: Schedule multiple posts at once
- **Timezone Support**: User-specific timezone handling
- **Analytics Dashboard**: Track posting performance and engagement
- **Queue Management**: Advanced queue system with retry logic
- **Optimal Timing**: AI-suggested optimal posting times

### 🔐 Enterprise Authentication
- **Firebase Authentication**: Secure authentication with Firebase Auth
- **Multi-Provider OAuth**: Google, Facebook, Twitter, LinkedIn, Threads, YouTube, TikTok
- **Role-Based Access**: User permissions and access control
- **Email Verification**: Secure email verification system
- **Rate Limiting**: Built-in rate limiting and abuse protection
- **Session Management**: Secure session handling

### 📊 Content Management
- **Media Upload**: Support for images, videos, and documents
- **Content Library**: Organize and manage all your content
- **Version Control**: Track content changes and versions
- **Content Templates**: Reusable content templates
- **Content Analytics**: Track performance across platforms

### 🏗️ Architecture & Infrastructure

#### Backend Stack
- **FastAPI**: High-performance async web framework
- **PostgreSQL**: Primary database via Supabase
- **Redis**: Caching and session storage
- **Firebase**: Authentication and user management
- **Docker**: Containerized deployment
- **FFmpeg**: Video processing and media handling

#### Key Technologies
- **SQLAlchemy**: ORM for database operations
- **Pydantic**: Data validation and serialization
- **Celery**: Background task processing
- **APScheduler**: Job scheduling
- **OpenAI/Together AI**: AI content generation
- **SendGrid**: Email services

## 📁 Project Structure

```
├── app/                          # Main application
│   ├── api/                      # API version management
│   │   └── v1/
│   │       └── routers/          # API endpoint routers
│   ├── core/                     # Core functionality
│   │   └── oauth/                # OAuth configurations
│   ├── db/                       # Database schemas and migrations
│   │   ├── migrations/           # Database migration files
│   │   ├── schema.sql            # Main database schema
│   │   └── *.sql                 # Individual table schemas
│   ├── dependencies/             # FastAPI dependencies
│   │   └── auth.py               # Authentication dependencies
│   ├── main.py                   # FastAPI application entry point
│   ├── middleware/               # Custom middleware
│   │   └── https_redirect.py     # HTTPS redirect middleware
│   ├── models/                   # Pydantic data models
│   │   ├── ai.py                 # AI-related models
│   │   ├── content.py            # Content models
│   │   ├── social_connections.py # Social media connections
│   │   └── users.py              # User models
│   ├── routers/                  # API route handlers
│   │   ├── ai.py                 # AI content generation endpoints
│   │   ├── auth.py               # Authentication endpoints
│   │   ├── content*.py           # Content management endpoints
│   │   ├── media.py              # Media upload/management
│   │   ├── posts_unified.py      # Unified posting system
│   │   ├── scheduling.py         # Post scheduling system
│   │   ├── social_connections.py # Social platform connections
│   │   └── subscriptions.py      # Subscription management
│   ├── services/                 # Business logic services
│   │   ├── ai_service.py         # AI content processing
│   │   ├── background_scheduler.py # Background job processing
│   │   ├── platform_publisher.py # Multi-platform publishing
│   │   └── twitter_publisher.py  # Twitter-specific publishing
│   └── utils/                    # Utility functions
│       ├── database.py           # Database connection utilities
│       ├── email.py              # Email service utilities
│       ├── encryption.py         # Data encryption utilities
│       ├── firebase.py           # Firebase utilities
│       └── timezone.py           # Timezone handling
├── config/                       # Configuration files
├── docs/                         # Documentation
├── scripts/                      # Utility scripts
├── tests/                        # Test files
├── Dockerfile                    # Docker configuration
├── requirements.txt              # Python dependencies
└── venv/                         # Python virtual environment
```

## 🛠️ Installation & Setup

### Prerequisites

- **Python 3.10+**
- **PostgreSQL** (via Supabase)
- **Redis** (for caching and sessions)
- **Docker** (optional, for containerized deployment)

### Environment Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd agdoc
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file with the following variables:

   ```env
   # Supabase Configuration
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_anon_key
   SUPABASE_SERVICE_KEY=your_supabase_service_key

   # Firebase Configuration
   FIREBASE_PROJECT_ID=your_firebase_project_id
   FIREBASE_PRIVATE_KEY_ID=your_private_key_id
   FIREBASE_PRIVATE_KEY=your_private_key
   FIREBASE_CLIENT_EMAIL=your_client_email
   FIREBASE_CLIENT_ID=your_client_id
   FIREBASE_AUTH_URI=https://accounts.google.com/o/oauth2/auth
   FIREBASE_TOKEN_URI=https://oauth2.googleapis.com/token

   # AI Services
   GROK_API_KEY=your_grok_api_key
   TOGETHER_API_KEY=your_together_api_key
   OPENAI_API_KEY=your_openai_api_key

   # Email Service
   SENDGRID_API_KEY=your_sendgrid_api_key

   # Social Media API Keys
   TWITTER_API_KEY=your_twitter_api_key
   TWITTER_API_SECRET=your_twitter_api_secret
   LINKEDIN_CLIENT_ID=your_linkedin_client_id
   LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret
   FACEBOOK_APP_ID=your_facebook_app_id
   FACEBOOK_APP_SECRET=your_facebook_app_secret
   INSTAGRAM_APP_ID=your_instagram_app_id
   INSTAGRAM_APP_SECRET=your_instagram_app_secret
   TIKTOK_CLIENT_KEY=your_tiktok_client_key
   TIKTOK_CLIENT_SECRET=your_tiktok_client_secret
   YOUTUBE_CLIENT_ID=your_youtube_client_id
   YOUTUBE_CLIENT_SECRET=your_youtube_client_secret

   # Other Services
   BRAVE_API_KEY=your_brave_search_api_key
   PATREON_CLIENT_ID=your_patreon_client_id
   PATREON_CLIENT_SECRET=your_patreon_client_secret
   PATREON_REDIRECT_URI=your_patreon_redirect_uri
   ```

5. **Database Setup:**
   ```bash
   # Initialize database
   python app/utils/database.py
   ```

6. **Run the application:**
   ```bash
   # Development mode
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

   # Production mode
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

## 🚀 Deployment

### Docker Deployment

1. **Build the image:**
   ```bash
   docker build -t multivio-api .
   ```

2. **Run the container:**
   ```bash
   docker run -p 8000:8000 --env-file .env multivio-api
   ```

### Production Deployment

The application is designed to work seamlessly with:
- **DigitalOcean App Platform**
- **Vercel** (for frontend)
- **Supabase** (database)
- **Cloudflare** (CDN)

## 📚 API Documentation

Once the application is running, access the interactive API documentation:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

### Key API Endpoints

#### Authentication
- `POST /api/v1/auth/oauth/google` - Google OAuth
- `POST /api/v1/auth/oauth/facebook` - Facebook OAuth
- `POST /api/v1/auth/oauth/twitter` - Twitter OAuth
- `GET /api/v1/auth/me` - Get current user profile

#### Content Management
- `POST /api/v1/posts` - Create new post
- `GET /api/v1/posts` - List user posts
- `PUT /api/v1/posts/{id}` - Update post
- `DELETE /api/v1/posts/{id}` - Delete post

#### AI Content Generation
- `POST /api/v1/ai/transform` - Transform content with AI
- `POST /api/v1/ai/generate` - Generate new content
- `POST /api/v1/ai/optimize` - Optimize content for platforms

#### Scheduling
- `POST /api/v1/scheduling/schedule` - Schedule a post
- `POST /api/v1/scheduling/bulk-schedule` - Bulk schedule posts
- `GET /api/v1/scheduling/queue` - Get scheduling queue
- `DELETE /api/v1/scheduling/{id}` - Cancel scheduled post

#### Social Media Integration
- `POST /api/v1/social/connect` - Connect social media account
- `GET /api/v1/social/connections` - List connected accounts
- `POST /api/v1/social/publish` - Publish to connected platforms

## 🤖 AI Features

### Content Transformation
Transform existing content for different platforms:

```python
{
  "content": "Your original content here",
  "target_platform": "twitter",
  "tone": "professional",
  "max_length": 280,
  "include_hashtags": true
}
```

### Content Generation
Generate new content from prompts:

```python
{
  "prompt": "Write a LinkedIn post about AI in social media",
  "platform": "linkedin",
  "tone": "professional",
  "include_call_to_action": true
}
```

### Platform Optimization
Automatically optimize content for each platform's requirements:
- **Twitter**: Character limits, hashtags, threading
- **LinkedIn**: Professional tone, industry insights
- **Facebook**: Engaging, community-focused
- **Instagram**: Visual storytelling, emojis
- **TikTok**: Trendy, short-form content
- **YouTube**: SEO-optimized titles and descriptions

## 📊 Analytics & Reporting

### Post Performance
- Engagement metrics across platforms
- Reach and impression tracking
- Click-through rates
- Conversion tracking

### Scheduling Analytics
- Optimal posting times
- Platform performance comparison
- Success/failure rates
- Queue performance metrics

### User Analytics
- Content creation patterns
- Platform usage statistics
- Engagement trends
- Growth metrics

## 🔒 Security Features

- **OAuth 2.0 Integration** with all major platforms
- **JWT Token Authentication** with Firebase
- **Rate Limiting** to prevent abuse
- **Data Encryption** for sensitive information
- **CORS Protection** with configurable origins
- **HTTPS Enforcement** in production
- **Input Validation** with Pydantic models

## 🔧 Development

### Running Tests
```bash
pytest
```

### Code Formatting
```bash
black .
isort .
```

### Database Migrations
```bash
# Apply migrations
python app/db/init_db.py

# Create new migration
python scripts/create_migration.py "migration_description"
```

### Background Tasks
```bash
# Start Celery worker
celery -A app.services.background_scheduler worker --loglevel=info

# Start scheduler
python app/services/background_scheduler.py
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 Support

For support and questions:
- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/your-repo/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-repo/discussions)

## 🗺️ Roadmap

### Upcoming Features
- [ ] Advanced AI content strategies
- [ ] Social media automation workflows
- [ ] Team collaboration features
- [ ] Advanced analytics dashboard
- [ ] Mobile app companion
- [ ] API rate limit management
- [ ] Content calendar integration

---

**Built with ❤️ using FastAPI, React, and modern web technologies.**