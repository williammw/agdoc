# AGDOC Development Setup

## Quick Start

```bash
# 1. Navigate to project
cd /Volumes/ExtremeSSD/workspaces/realworld-workspaces/agdoc

# 2. Create virtual environment (if not exists)
python3 -m venv venv

# 3. Activate virtual environment
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Start the server
./scripts/start-dev.sh
```

## URLs

| Environment | URL |
|-------------|-----|
| Local | http://localhost:8000 |
| Remote | https://dev.ohmeowkase.com |
| API Docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

## Cloudflare Tunnel Setup

The tunnel config at `~/.cloudflared/config.yml` includes:

```yaml
ingress:
  - hostname: dev.multivio.com
    service: http://localhost:3000
  - hostname: dev.ohmeowkase.com
    service: http://localhost:8000
  - service: http_status:404
```

### DNS Configuration (One-time setup)

You need to update the DNS record for `dev.ohmeowkase.com` in Cloudflare:

1. Go to Cloudflare Dashboard → ohmeowkase.com → DNS
2. Find or create a CNAME record for `dev`
3. Set it to: `15690112-e176-466f-867c-63d588351b84.cfargotunnel.com`
4. Enable Proxied (orange cloud)

### Running the Tunnel

The tunnel runs automatically with:
```bash
cloudflared tunnel run
```

Or use the Social Media Manager's tunnel script which now includes both domains.

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:port/db

# APIs
XAI_API_KEY=your-xai-key
TOGETHER_API_KEY=your-together-key
OPENAI_API_KEY=your-openai-key

# Cloudflare R2
R2_ENDPOINT_URL=https://xxx.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=your-access-key
R2_SECRET_ACCESS_KEY=your-secret-key
R2_BUCKET_NAME=multivio
R2_DEV_URL=cdn.multivio.com

# Firebase
FIREBASE_PROJECT_ID=your-project
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
FIREBASE_CLIENT_EMAIL=firebase-adminsdk@project.iam.gserviceaccount.com
```

## Project Structure

```
agdoc/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── routers/
│   │   ├── ai.py            # AI endpoints
│   │   ├── auth.py          # Authentication
│   │   ├── content.py       # Content management
│   │   ├── media.py         # Media processing
│   │   ├── posts_unified.py # Unified posts API
│   │   ├── scheduling.py    # Post scheduling
│   │   └── social_connections.py
│   ├── services/
│   │   ├── ai_service.py
│   │   ├── platform_publisher.py
│   │   └── scheduler.py
│   ├── utils/
│   │   ├── database.py
│   │   ├── encryption.py
│   │   └── firebase.py
│   └── db/
│       └── migrations/
├── scripts/
│   └── start-dev.sh
├── requirements.txt
└── Dockerfile
```

## API Endpoints

### Health
- `GET /` - Welcome message
- `GET /health` - Health check

### AI
- `POST /api/ai/generate` - Generate content
- `POST /api/ai/transform` - Transform content

### Media
- `POST /api/media/upload` - Upload media
- `GET /api/media/{id}` - Get media
- `POST /api/media/process` - Process media

### Posts
- `GET /api/posts` - List posts
- `POST /api/posts` - Create post
- `GET /api/posts/{id}` - Get post
- `PUT /api/posts/{id}` - Update post
- `DELETE /api/posts/{id}` - Delete post

### Scheduling
- `POST /api/schedule` - Schedule post
- `GET /api/schedule` - List scheduled posts
- `DELETE /api/schedule/{id}` - Cancel scheduled post

## Development

### Running Tests
```bash
pytest
```

### Linting
```bash
flake8 app/
```

### Type Checking
```bash
mypy app/
```

## Integration with Social Media Manager

The AGDOC API is used by the Social Media Manager (Next.js) for:

1. **Media Processing** - FFmpeg-based image/video processing
2. **AI Content Generation** - Text generation and transformation
3. **Post Scheduling** - Enterprise scheduling system
4. **Platform Publishing** - Publishing to social platforms

### API Base URL Configuration

In Social Media Manager's `.env.local`:
```bash
AGDOC_API_URL=https://dev.ohmeowkase.com
```

Or for local development:
```bash
AGDOC_API_URL=http://localhost:8000
```
