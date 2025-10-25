# Deployment & Infrastructure

## 🚀 Deployment Overview

The Multivio backend is designed for production deployment with enterprise-grade reliability, scalability, and monitoring. The system supports multiple deployment strategies and environments.

### Supported Environments

- **Development**: Local development with hot reload
- **Staging**: Pre-production testing environment
- **Production**: Live production environment (DigitalOcean App Platform)

### Deployment Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Development   │    │     Staging     │    │   Production    │
│                 │    │                 │    │                 │
│ • Local Docker  │    │ • Docker Deploy │    │ • DigitalOcean  │
│ • Hot Reload    │    │ • Full Testing  │    │ • Auto Scaling  │
│ • Debug Tools   │    │ • Integration   │    │ • Load Balance  │
│ • Local DB      │    │ • Staging DB     │    │ • Prod DB       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

---

## 🐳 Docker Deployment

### Dockerfile Configuration

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Start application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Building and Running

```bash
# Build Docker image
docker build -t multivio-api .

# Run locally
docker run -p 8000:8000 \
  --env-file .env \
  -e ENCRYPTION_KEY="your-encryption-key" \
  multivio-api

# Run with volume mounting for development
docker run -p 8000:8000 \
  -v $(pwd):/app \
  --env-file .env \
  multivio-api
```

### Docker Compose (Development)

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
```

---

## 🌊 DigitalOcean App Platform

### Production Deployment

The application is optimized for **DigitalOcean App Platform** with:

- **Auto-scaling** based on CPU and memory usage
- **Built-in load balancing** across multiple instances
- **Automated SSL certificates** with Let's Encrypt
- **Database connection pooling** with Supabase
- **Environment variable management**
- **Deployment from GitHub** with CI/CD

### App Spec Configuration

```yaml
name: multivio-api
services:
- name: api
  source_dir: /
  github:
    repo: your-org/multivio-backend
    branch: main
    deploy_on_push: true
  run_command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
  environment_slug: python
  instance_count: 1
  instance_size_slug: professional-xs
  health_check:
    http_path: /health
  envs:
  - key: SUPABASE_URL
    type: SECRET
    value: ${supabase_url}
  - key: SUPABASE_KEY
    type: SECRET
    value: ${supabase_key}
  - key: FIREBASE_PROJECT_ID
    type: SECRET
    value: ${firebase_project_id}
  - key: ENCRYPTION_KEY
    type: SECRET
    value: ${encryption_key}
  - key: ENVIRONMENT
    value: production
```

### Environment Variables Setup

**Required Secrets:**
```bash
# Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_KEY=your-supabase-service-key

# Firebase
FIREBASE_PROJECT_ID=your-firebase-project
FIREBASE_CLIENT_EMAIL=firebase-adminsdk@project.iam.gserviceaccount.com
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
FIREBASE_CLIENT_ID=your-client-id

# Encryption (Generate securely)
ENCRYPTION_KEY=base64-encoded-32-byte-key

# AI Services
GROK_API_KEY=your-grok-api-key

# Social Media APIs
TWITTER_API_KEY=your-twitter-api-key
FACEBOOK_APP_ID=your-facebook-app-id
# ... other platform credentials
```

### Scaling Configuration

```yaml
# Auto-scaling based on CPU usage
scaling:
  min_instances: 1
  max_instances: 10
  metrics:
    cpu:
      percent: 80

# Instance sizes
instance_size_slug: professional-xs  # 512MB RAM, 1 vCPU
# Options: basic-xxs, basic-xs, professional-xs, professional-s, professional-m
```

---

## ⚙️ Environment Configuration

### Environment Variables Reference

#### Core Configuration
```bash
# Application
ENVIRONMENT=production  # development | staging | production
DEBUG=false
LOG_LEVEL=INFO

# Server
HOST=0.0.0.0
PORT=8000

# CORS
ALLOWED_ORIGINS=https://multivio.com,https://www.multivio.com,https://dev.multivio.com
```

#### Database Configuration
```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=eyJhbGc...  # Anon key
SUPABASE_SERVICE_KEY=eyJhbGc...  # Service role key

# Connection Pool
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
```

#### Authentication & Security
```bash
# Firebase
FIREBASE_PROJECT_ID=multivio-prod
FIREBASE_CLIENT_EMAIL=service-account@multivio-prod.iam.gserviceaccount.com
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
FIREBASE_CLIENT_ID=123456789
FIREBASE_AUTH_URI=https://accounts.google.com/o/oauth2/auth
FIREBASE_TOKEN_URI=https://oauth2.googleapis.com/token

# Encryption (REQUIRED - Generate with: python -c "import secrets; import base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
ENCRYPTION_KEY=your-32-byte-base64-encoded-key

# JWT (Optional - Firebase handles auth)
JWT_SECRET_KEY=your-jwt-secret
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
```

#### AI Services
```bash
# Primary AI (Grok)
GROK_API_KEY=xai-your-api-key

# Fallback AIs
TOGETHER_API_KEY=your-together-key
OPENAI_API_KEY=your-openai-key

# AI Configuration
AI_DEFAULT_MODEL=grok-3-mini
AI_MAX_TOKENS=2000
AI_REQUEST_TIMEOUT=30
AI_MAX_RETRIES=3
AI_STREAM_CHUNK_SIZE=50
```

#### Social Media APIs
```bash
# Twitter/X
TWITTER_API_KEY=your-twitter-api-key
TWITTER_API_SECRET=your-twitter-api-secret
TWITTER_BEARER_TOKEN=your-bearer-token

# Facebook
FACEBOOK_APP_ID=your-facebook-app-id
FACEBOOK_APP_SECRET=your-facebook-app-secret
FACEBOOK_API_VERSION=v21.0

# Instagram (uses Facebook credentials)
INSTAGRAM_APP_ID=${FACEBOOK_APP_ID}
INSTAGRAM_APP_SECRET=${FACEBOOK_APP_SECRET}

# LinkedIn
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret

# YouTube
YOUTUBE_CLIENT_ID=your-youtube-client-id
YOUTUBE_CLIENT_SECRET=your-youtube-client-secret

# TikTok
TIKTOK_CLIENT_KEY=your-tiktok-client-key
TIKTOK_CLIENT_SECRET=your-tiktok-client-secret

# Threads (uses Facebook/Meta)
THREADS_APP_ID=${FACEBOOK_APP_ID}
THREADS_APP_SECRET=${FACEBOOK_APP_SECRET}
```

#### External Services
```bash
# Email
SENDGRID_API_KEY=your-sendgrid-key
EMAIL_FROM=noreply@multivio.com

# Media Storage (Cloudflare R2)
R2_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=your-r2-access-key
R2_SECRET_ACCESS_KEY=your-r2-secret
R2_BUCKET_NAME=multivio-media
CDN_DOMAIN=https://cdn.multivio.com

# Search & Analytics
BRAVE_API_KEY=your-brave-search-key
PATERON_CLIENT_ID=your-patreon-client-id
PATERON_CLIENT_SECRET=your-patreon-secret
```

#### Performance & Caching
```bash
# Redis (Optional)
REDIS_URL=redis://localhost:6379
REDIS_CACHE_TTL=3600

# Rate Limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60  # seconds

# Background Jobs
APSCHEDULER_JOBSTORES_MEMORY=true
CELERY_BROKER_URL=${REDIS_URL}
CELERY_RESULT_BACKEND=${REDIS_URL}
```

### Environment-Specific Configurations

#### Development (.env.development)
```bash
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG

# Local services
SUPABASE_URL=https://dev-project.supabase.co
REDIS_URL=redis://localhost:6379

# Development CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,https://dev.multivio.com
```

#### Production (.env.production)
```bash
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO

# Production services
SUPABASE_URL=https://prod-project.supabase.co

# Production CORS
ALLOWED_ORIGINS=https://multivio.com,https://www.multivio.com

# Enhanced security
ENCRYPTION_KEY=<strong-production-key>
```

---

## 🔧 Infrastructure Setup

### Supabase Database Setup

1. **Create Project**
   ```bash
   # Via Supabase Dashboard or CLI
   supabase init
   supabase start
   ```

2. **Run Migrations**
   ```sql
   -- Apply schema migrations in order
   -- 001_initial_schema.sql
   -- 002_subscription_schema.sql
   -- 003_content_management.sql
   -- 004_unified_posts.sql
   -- 005_oauth1_columns.sql
   ```

3. **Configure Row Level Security**
   ```sql
   -- Enable RLS on all tables
   ALTER TABLE users ENABLE ROW LEVEL SECURITY;
   ALTER TABLE social_connections ENABLE ROW LEVEL SECURITY;
   ALTER TABLE posts ENABLE ROW LEVEL SECURITY;

   -- Create policies (see DATABASE-SCHEMA.md for details)
   ```

### Redis Setup (Optional)

```bash
# Install Redis
docker run -d -p 6379:6379 redis:7-alpine

# Or install locally
brew install redis  # macOS
sudo apt install redis-server  # Ubuntu

# Start Redis
redis-server
```

### Firebase Setup

1. **Create Firebase Project**
2. **Enable Authentication**
3. **Create Service Account**
   - Go to Project Settings → Service Accounts
   - Generate new private key
   - Download JSON (contains all required credentials)

---

## 🚀 CI/CD Pipeline

### GitHub Actions Workflow

```yaml
name: Deploy to DigitalOcean

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    - name: Run tests
      run: |
        python test_ai_endpoints.py
        python test_oauth1_endpoints.py
    - name: Run linting
      run: |
        black --check .
        isort --check-only .

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
    - name: Deploy to DigitalOcean
      uses: digitalocean/app_action@main
      with:
        app_name: multivio-api
        token: ${{ secrets.DIGITALOCEAN_ACCESS_TOKEN }}
```

### Deployment Checklist

- [ ] All tests pass
- [ ] Code is linted and formatted
- [ ] Environment variables are configured
- [ ] Database migrations are applied
- [ ] Firebase service account is set up
- [ ] Social media API keys are configured
- [ ] AI service API keys are configured
- [ ] SSL certificates are valid
- [ ] Health checks are passing

---

## 📊 Monitoring & Observability

### Health Checks

**Application Health**
```
GET /health
```
Returns comprehensive health status:
```json
{
  "status": "healthy",
  "version": "3.0.1",
  "database": "connected",
  "redis": "connected",
  "uptime": "30d 4h 15m",
  "environment": "production"
}
```

**AI Service Health**
```
GET /api/v1/ai/health
```
Returns AI service status:
```json
{
  "status": "healthy",
  "grok_api_configured": true,
  "models_available": ["grok-4", "grok-3-mini"],
  "response_time_ms": 245
}
```

### Logging Configuration

**Structured Logging Setup:**
```python
import logging
import json
from pythonjsonlogger import jsonlogger

# Configure JSON logging
logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)
```

### Metrics Collection

**Application Metrics:**
- Request count and response times
- Error rates by endpoint
- Database connection pool usage
- AI service usage and performance
- OAuth token refresh success rates

**Infrastructure Metrics:**
- CPU and memory usage
- Network I/O
- Disk space usage
- Database query performance

### Alerting

**Critical Alerts:**
- Application health check failures
- Database connection issues
- High error rates (>5%)
- AI service unavailability
- OAuth token refresh failures

**Performance Alerts:**
- Response times > 2 seconds
- Memory usage > 80%
- Database connection pool exhaustion

---

## 🔒 Security Configuration

### SSL/TLS Configuration

**DigitalOcean App Platform** automatically provides:
- SSL certificates via Let's Encrypt
- HTTP to HTTPS redirects
- TLS 1.2+ support
- Secure headers (HSTS, CSP, etc.)

### Network Security

**Firewall Rules:**
- Restrict database access to application servers
- Allow API access only from frontend domains
- Block direct access to sensitive endpoints

**API Security:**
- Rate limiting on all endpoints
- Input validation and sanitization
- CORS protection
- Authentication required for all operations

### Data Protection

**Encryption:**
- OAuth tokens encrypted at rest
- Database connections over SSL
- Secure environment variable handling

**Access Control:**
- Row Level Security (RLS) in database
- Firebase authentication verification
- API key rotation for external services

---

## 🔄 Backup & Recovery

### Database Backups

**Supabase Automated Backups:**
- Daily backups retained for 7 days
- Point-in-time recovery available
- Cross-region replication

**Manual Backup Process:**
```bash
# Export database schema
pg_dump -h your-host -U your-user -d your-db --schema-only > schema.sql

# Export data (anonymized)
pg_dump -h your-host -U your-user -d your-db --data-only --exclude-table=logs > data.sql
```

### Application Backups

**Configuration Backup:**
```bash
# Backup environment variables (encrypted)
tar -czf env-backup.tar.gz .env*

# Backup application code
git tag backup-$(date +%Y%m%d)
git push origin --tags
```

### Disaster Recovery

**Recovery Time Objectives:**
- **RTO**: 4 hours (time to restore service)
- **RPO**: 1 hour (maximum data loss)

**Recovery Process:**
1. Deploy backup application instance
2. Restore database from backup
3. Update DNS records
4. Verify application functionality
5. Notify users of service restoration

---

## 📈 Performance Optimization

### Application Performance

**FastAPI Optimizations:**
```python
# Gunicorn configuration for production
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8000"
max_requests = 1000
max_requests_jitter = 50
```

**Database Optimization:**
- Connection pooling with SQLAlchemy
- Query result caching
- Database indexes on frequently queried columns
- Read replicas for analytics queries

**Caching Strategy:**
```python
# Redis caching for API responses
from redis import Redis
redis_client = Redis.from_url(os.getenv("REDIS_URL"))

@app.middleware("http")
async def cache_middleware(request, call_next):
    cache_key = f"{request.method}:{request.url.path}"
    cached_response = redis_client.get(cache_key)

    if cached_response:
        return JSONResponse(json.loads(cached_response))

    response = await call_next(request)

    if response.status_code == 200:
        redis_client.setex(cache_key, 300, response.body.decode())

    return response
```

### Scaling Strategies

**Horizontal Scaling:**
- Stateless application design
- Session storage in Redis
- Background jobs in Celery
- Database connection pooling

**Vertical Scaling:**
- Instance size upgrades based on load
- Memory optimization and garbage collection
- CPU-intensive tasks offloaded to background workers

---

## 🧪 Testing Strategy

### Automated Testing

**Test Structure:**
```
tests/
├── unit/              # Unit tests for individual functions
├── integration/       # API integration tests
├── e2e/              # End-to-end user journey tests
├── performance/      # Load and performance tests
└── security/         # Security and penetration tests
```

**Running Tests:**
```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# All tests with coverage
pytest --cov=app --cov-report=html

# Performance tests
locust -f tests/performance/locustfile.py
```

### Load Testing

**Locust Configuration:**
```python
from locust import HttpUser, task, between

class APIUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def get_posts(self):
        self.client.get("/api/v1/posts",
                       headers={"Authorization": f"Bearer {self.token}"})

    @task(2)
    def create_post(self):
        self.client.post("/api/v1/posts",
                        json={"name": "Test Post", "universal_content": "Content"},
                        headers={"Authorization": f"Bearer {self.token}"})

    @task(1)
    def ai_transform(self):
        self.client.post("/api/v1/ai/transform",
                        json={"content": "Test", "transformation_type": "platform_optimize"},
                        headers={"Authorization": f"Bearer {self.token}"})
```

### Continuous Integration

**Quality Gates:**
- All tests must pass
- Code coverage > 80%
- No critical security vulnerabilities
- Performance benchmarks met
- Linting and formatting checks pass

---

## 📞 Support & Troubleshooting

### Common Deployment Issues

**Database Connection Issues:**
```bash
# Test database connectivity
python -c "
import asyncpg
conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
await conn.close()
print('Database connection successful')
"
```

**Environment Variable Issues:**
```bash
# Validate environment variables
python -c "
import os
required_vars = ['SUPABASE_URL', 'FIREBASE_PROJECT_ID', 'ENCRYPTION_KEY']
missing = [v for v in required_vars if not os.getenv(v)]
if missing:
    print(f'Missing environment variables: {missing}')
else:
    print('All required environment variables are set')
"
```

**Performance Issues:**
- Check application logs for slow queries
- Monitor database connection pool usage
- Verify Redis cache hit rates
- Review background job queue lengths

### Emergency Procedures

**Service Outage Response:**
1. Check application health endpoints
2. Review recent deployments and changes
3. Check infrastructure status (DigitalOcean, Supabase)
4. Scale up application instances if needed
5. Roll back to previous deployment if necessary
6. Communicate with users about status

**Data Recovery:**
1. Assess data loss scope
2. Restore from most recent backup
3. Verify data integrity
4. Update application with recovery status
5. Notify affected users

---

**Version**: 3.0.1
**Last Updated**: September 2025
**Deployment Status**: Production Ready ✅
