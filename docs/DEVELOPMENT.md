# Development Guide

## 🛠️ Development Setup

This guide covers setting up the Multivio backend for local development, including environment setup, testing, and contribution guidelines.

### Prerequisites

- **Python 3.11+**
- **Git**
- **Docker** (optional, for containerized development)
- **Supabase account** (for database)
- **Firebase project** (for authentication)
- **Social media developer accounts** (for platform integrations)

### Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd agdoc

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit environment variables (see Environment Setup below)
nano .env

# Initialize database
python app/db/init_db.py

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Access API documentation
open http://localhost:8000/docs
```

---

## ⚙️ Environment Setup

### Environment Variables

Create a `.env` file with the following variables:

```bash
# Application
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG

# Server
HOST=0.0.0.0
PORT=8000

# Database (Supabase)
SUPABASE_URL=https://your-dev-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_KEY=your-supabase-service-key

# Firebase
FIREBASE_PROJECT_ID=your-dev-firebase-project
FIREBASE_CLIENT_EMAIL=firebase-adminsdk@project.iam.gserviceaccount.com
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
FIREBASE_CLIENT_ID=your-client-id

# Encryption (Generate with: python -c "import secrets; import base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
ENCRYPTION_KEY=your-32-byte-base64-encoded-key

# AI Services (Optional for development)
GROK_API_KEY=your-grok-api-key

# Social Media APIs (Optional - use test credentials)
TWITTER_API_KEY=your-twitter-api-key
FACEBOOK_APP_ID=your-facebook-app-id
# ... other platform credentials

# CORS (Development)
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,https://dev.multivio.com
```

### Firebase Setup

1. **Create Firebase Project**
   - Go to [Firebase Console](https://console.firebase.google.com/)
   - Create a new project or use existing one

2. **Enable Authentication**
   - Go to Authentication → Sign-in method
   - Enable Google provider
   - Enable Email/Password provider

3. **Create Service Account**
   - Go to Project Settings → Service Accounts
   - Click "Generate new private key"
   - Download the JSON file
   - Extract the values for your `.env` file

### Supabase Setup

1. **Create Supabase Project**
   - Go to [Supabase](https://supabase.com/)
   - Create a new project

2. **Get Connection Details**
   - Go to Settings → API
   - Copy Project URL and anon/public key
   - Copy service_role key (keep secret!)

3. **Apply Database Schema**
   - Go to SQL Editor in Supabase
   - Run the migration files in order:
     - `app/db/migrations/001_initial_schema.sql`
     - `app/db/migrations/002_subscription_schema.sql`
     - `app/db/migrations/003_content_management.sql`
     - `app/db/migrations/004_unified_posts.sql`
     - `app/db/migrations/005_oauth1_columns.sql`

---

## 🏃 Running the Application

### Development Mode

```bash
# Activate virtual environment
source venv/bin/activate

# Run with hot reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run with specific configuration
uvicorn app.main:app --reload --log-level debug --access-log
```

### Docker Development

```bash
# Build development image
docker build -t multivio-api-dev .

# Run with volume mounting for live reload
docker run -p 8000:8000 \
  -v $(pwd):/app \
  --env-file .env \
  multivio-api-dev \
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker Compose (Full Stack)

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
    volumes:
      - .:/app
      - /app/__pycache__
    command: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: multivio_dev
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

---

## 🧪 Testing

### Available Test Scripts

```bash
# Test AI endpoints
python test_ai_endpoints.py

# Test OAuth1 flow (Twitter)
python test_oauth1_endpoints.py
```

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
pytest

# Run specific test file
pytest test_ai_endpoints.py -v

# Run with coverage
pytest --cov=app --cov-report=html
```

### Manual API Testing

```bash
# Health check
curl http://localhost:8000/health

# API documentation
open http://localhost:8000/docs

# Test authentication (requires Firebase token)
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN"
```

### Testing with Frontend

1. **Start backend**: `uvicorn app.main:app --reload`
2. **Start frontend**: In separate terminal, navigate to frontend project and run `npm run dev`
3. **Test integration**: Use frontend to interact with API
4. **Monitor logs**: Check backend terminal for requests and errors

---

## 📝 Code Quality

### Code Formatting

```bash
# Install development dependencies
pip install black isort flake8 mypy

# Format code
black .

# Sort imports
isort .

# Check formatting
black --check .
isort --check-only .

# Lint code
flake8 app/

# Type checking
mypy app/
```

### Pre-commit Hooks

Create `.pre-commit-config.yaml`:

```yaml
repos:
- repo: https://github.com/psf/black
  rev: 23.9.1
  hooks:
  - id: black

- repo: https://github.com/pycqa/isort
  rev: 5.12.0
  hooks:
  - id: isort

- repo: https://github.com/pycqa/flake8
  rev: 6.0.0
  hooks:
  - id: flake8

- repo: https://github.com/pre-commit/mirrors-mypy
  rev: v1.5.1
  hooks:
  - id: mypy
```

Install hooks:
```bash
pip install pre-commit
pre-commit install
```

---

## 🏗️ Project Structure

### Adding New Features

#### 1. New API Endpoint

```python
# 1. Add to router (e.g., app/routers/auth.py)
@router.post("/new-feature")
async def new_feature(request: NewFeatureRequest, current_user: dict = Depends(get_current_user)):
    """New feature endpoint"""
    # Implementation
    pass

# 2. Add Pydantic models (app/models/auth.py)
class NewFeatureRequest(BaseModel):
    parameter: str

class NewFeatureResponse(BaseModel):
    result: str

# 3. Add to main.py if new router
from app.routers import new_router
app.include_router(new_router.router, prefix="/api/v1/new", tags=["new"])
```

#### 2. New Social Platform

```python
# 1. Add platform configuration (app/core/oauth/base.py)
PLATFORM_CONFIGS = {
    "newplatform": {
        "client_id": os.getenv("NEWPLATFORM_CLIENT_ID"),
        "client_secret": os.getenv("NEWPLATFORM_CLIENT_SECRET"),
        "auth_url": "https://newplatform.com/oauth/authorize",
        "token_url": "https://newplatform.com/oauth/token",
        "scope": ["read", "write"],
        "use_pkce": True
    }
}

# 2. Add publisher (app/services/platform_publisher.py)
class NewPlatformPublisher(BasePublisher):
    async def publish(self, content: dict, connection: dict, media_files: list = None):
        # Implementation
        pass

# 3. Register platform
self.platforms['newplatform'] = NewPlatformPublisher()
```

#### 3. Database Changes

```sql
-- 1. Create migration file (app/db/migrations/006_new_feature.sql)
ALTER TABLE posts ADD COLUMN new_feature_data JSONB DEFAULT '{}';

-- 2. Update models (app/models/content.py)
class Post(Base):
    new_feature_data: Optional[dict] = Field(default_factory=dict)

-- 3. Apply migration
# Via Supabase SQL editor or script
```

### Code Organization Guidelines

- **Routers**: API endpoints and request/response handling
- **Services**: Business logic and external API integrations
- **Models**: Pydantic models and database schemas
- **Utils**: Helper functions and utilities
- **Dependencies**: FastAPI dependency injection
- **Middleware**: Custom request/response processing

---

## 🔧 Debugging

### Logging Configuration

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Or set environment variable
LOG_LEVEL=DEBUG
```

### Common Debug Scenarios

#### Database Connection Issues
```python
# Test database connection
from app.utils.database import get_database
db = get_database()
result = db.table('users').select('*').limit(1).execute()
print("Database connection successful:", len(result.data) >= 0)
```

#### OAuth Token Issues
```python
# Debug token encryption/decryption
from app.utils.encryption import encrypt_token, decrypt_token
test_token = "test_token_123"
encrypted = encrypt_token(test_token)
decrypted = decrypt_token(encrypted)
print("Encryption works:", decrypted == test_token)
```

#### API Request Debugging
```python
# Add logging to router
import logging
logger = logging.getLogger(__name__)

@router.post("/debug-endpoint")
async def debug_endpoint(request: Request):
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Request body: {await request.body()}")
    return {"debug": "complete"}
```

### Debugging Tools

#### VS Code Debugging
Create `.vscode/launch.json`:
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug FastAPI",
            "type": "python",
            "request": "launch",
            "module": "uvicorn",
            "args": ["app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        }
    ]
}
```

#### PDB Debugging
```python
# Add breakpoint in code
import pdb; pdb.set_trace()

# Or use breakpoint() in Python 3.7+
breakpoint()
```

---

## 🚀 Deployment

### Local Production Testing

```bash
# Run without reload (production-like)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# Test with production environment
ENVIRONMENT=production uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Docker Deployment Testing

```bash
# Build production image
docker build -t multivio-api-prod .

# Run production container
docker run -p 8000:8000 \
  --env-file .env.production \
  --name multivio-api-prod \
  multivio-api-prod
```

### Pre-deployment Checklist

- [ ] All tests pass (`pytest`)
- [ ] Code is formatted (`black . && isort .`)
- [ ] Linting passes (`flake8 app/`)
- [ ] Type checking passes (`mypy app/`)
- [ ] Environment variables are configured
- [ ] Database migrations are applied
- [ ] API documentation is accessible (`/docs`)
- [ ] Health check passes (`/health`)

---

## 🤝 Contributing

### Development Workflow

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/new-feature-name
   ```

2. **Make Changes**
   - Follow code quality guidelines
   - Add tests for new functionality
   - Update documentation

3. **Test Changes**
   ```bash
   # Run tests
   pytest

   # Manual testing
   python test_ai_endpoints.py
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

5. **Push and Create PR**
   ```bash
   git push origin feature/new-feature-name
   # Create pull request on GitHub
   ```

### Commit Message Guidelines

```
type(scope): description

Types:
- feat: new feature
- fix: bug fix
- docs: documentation
- style: formatting
- refactor: code restructuring
- test: testing
- chore: maintenance

Examples:
- feat(auth): add Google OAuth support
- fix(api): handle null values in posts endpoint
- docs(api): update authentication guide
```

### Code Review Process

**Pull Request Requirements:**
- [ ] Tests pass
- [ ] Code is reviewed
- [ ] Documentation updated
- [ ] Migration scripts included (if needed)
- [ ] Environment variables documented

**Review Checklist:**
- [ ] Code follows project conventions
- [ ] Error handling is appropriate
- [ ] Security considerations addressed
- [ ] Performance implications considered
- [ ] Tests cover edge cases

---

## 📊 Performance Monitoring

### Development Metrics

```python
# Add performance monitoring
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        response = await call_next(request)

        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)

        # Log slow requests
        if process_time > 1.0:
            logger.warning(".2f")

        return response
```

### Profiling Tools

```python
# Memory profiling
from memory_profiler import profile

@profile
def memory_intensive_function():
    # Code to profile
    pass

# CPU profiling
import cProfile
cProfile.run('memory_intensive_function()')
```

### Database Query Monitoring

```python
# Log slow queries
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

# Or use SQLAlchemy events
from sqlalchemy import event

@event.listens_for(engine, "before_execute")
def before_execute(conn, clauseelement, multiparams, params):
    logger.info(f"Executing query: {clauseelement}")

@event.listens_for(engine, "after_execute")
def after_execute(conn, clauseelement, multiparams, params, result):
    logger.info(f"Query executed in {time.time() - start_time} seconds")
```

---

## 🔒 Security Development

### Local Security Testing

```bash
# Test CORS
curl -H "Origin: http://malicious-site.com" \
     -H "Access-Control-Request-Method: GET" \
     -X OPTIONS http://localhost:8000/api/v1/posts

# Test authentication
curl -X GET http://localhost:8000/api/v1/auth/me
# Should return 401 Unauthorized

# Test input validation
curl -X POST http://localhost:8000/api/v1/posts \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"name": ""}'  # Invalid empty name
# Should return 422 Validation Error
```

### Dependency Security

```bash
# Check for vulnerable dependencies
pip install safety
safety check

# Update dependencies securely
pip install pip-tools
pip-compile --upgrade requirements.in
pip install -r requirements.txt
```

---

## 📚 Resources

### Documentation Links

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://pydantic-docs.helpmanual.io/)
- [SQLAlchemy Documentation](https://sqlalchemy.org/)
- [Supabase Documentation](https://supabase.com/docs)
- [Firebase Admin SDK](https://firebase.google.com/docs/admin/setup)

### Development Tools

- [Postman](https://postman.com/) - API testing
- [Insomnia](https://insomnia.rest/) - API client
- [pgAdmin](https://pgadmin.org/) - Database administration
- [Redis Commander](https://rediscommander.com/) - Redis GUI
- [Firebase Console](https://console.firebase.google.com/) - Authentication management

### Learning Resources

- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)
- [Async Python Course](https://fastapi.tiangolo.com/tutorial/async/)
- [OAuth 2.0 Specification](https://tools.ietf.org/html/rfc6749)
- [JWT Handbook](https://tools.ietf.org/html/rfc7519)

---

## 🚨 Troubleshooting

### Common Issues

#### Import Errors
```bash
# Clear Python cache
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} +

# Reinstall dependencies
pip uninstall -r requirements.txt -y
pip install -r requirements.txt
```

#### Database Connection Issues
```python
# Test connection manually
import asyncpg
conn = await asyncpg.connect(os.getenv('SUPABASE_URL'))
await conn.close()
```

#### Firebase Authentication Issues
```python
# Test Firebase token
from firebase_admin import auth
decoded = auth.verify_id_token('your_token_here')
print(decoded)
```

#### Port Already in Use
```bash
# Find process using port
lsof -i :8000

# Kill process
kill -9 <PID>

# Or use different port
uvicorn app.main:app --port 8001
```

### Getting Help

1. **Check Documentation**: Review relevant docs in `/docs` folder
2. **Search Issues**: Check GitHub issues for similar problems
3. **Debug Logs**: Enable debug logging and check output
4. **Health Check**: Verify `/health` endpoint returns healthy status
5. **Community**: Ask in development discussions or team chat

---

**Version**: 3.0.1
**Last Updated**: September 2025
**Development Status**: Active ✅
