# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AGDOC** is the **media-processing backend** for the Multivio social media platform.
It is a Python/FastAPI service that does FFmpeg-based media work and AI media
generation. It is a focused microservice — **it does not handle user auth,
OAuth, posting, or billing**. Those all live in the Multivio frontend (`smmp`).

> Scope note: AGDOC is *purely* media processing for now. It previously also
> handled auth / social-connections / subscriptions — that has all moved to
> `smmp`. Older docs/migrations referencing `auth.py`, `social_connections`,
> Firebase-as-primary-auth, or a DigitalOcean Postgres describe that retired
> incarnation and no longer apply.

## The two Multivio repos

| Repo | What it is | Host |
|------|-----------|------|
| **smmp** (`/Users/manwaiwong/Developer/personal/smmp`) | Multivio — Next.js 16 frontend: UI, auth, OAuth, posting, scheduling, Stripe billing, AI orchestration | Vercel (`multivio.com`) |
| **agdoc** (this repo) | FFmpeg media-processing + AI media generation microservice | DigitalOcean App Platform |

- **smmp calls agdoc** for media jobs (resize, crop, trim, subtitle burn,
  thumbnails, compose, slideshow). Internal endpoints are authenticated with an
  API key — the `INTERNAL_API_KEY` env var here, sent by smmp as `AGDOC_INTERNAL_API_KEY`.
- **Shared infrastructure:** both repos use the **same Supabase project**
  (`mzlspxsxifcqotacrhek`) and the **same Cloudflare R2 bucket** (`multivio`).
- Separate repos, separate hosts — a push to one does **not** deploy the other.
- smmp documents this integration in `smmp/.claude/rules/agdoc-integration.md`
  and the `agdoc-deploy` skill.

## Deployment — GitHub → DOCR → App Platform

**AGDOC deploys via a container image, not source.** The chain:

1. `git push` to GitHub `master`
2. GitHub Actions (`.github/workflows/deploy.yml`) builds a `linux/amd64` Docker
   image and pushes it to **DigitalOcean Container Registry (DOCR)**:
   `registry.digitalocean.com/umami-backend-api/docker-agdoc:latest`
3. DigitalOcean **App Platform** has `deploy_on_push` enabled on that image —
   it auto-deploys the new `:latest` container

So: **commit + push to `master` is the deploy.** No manual step. Build takes
~2–3 min (GHA layer cache) then App Platform rolls the container.

| Field | Value |
|-------|-------|
| App Platform app | `jellyfish-app` (id `285e2e03-1f77-4a9d-b806-3ecb1da35087`) |
| Region | Singapore (`sgp`) |
| Instance | `apps-s-1vcpu-2gb`, 1 instance, http port 8000 |
| DOCR image | `registry.digitalocean.com/umami-backend-api/docker-agdoc:latest` |
| Production URL | https://jellyfish-app-ds6sv.ondigitalocean.app |
| API docs | https://jellyfish-app-ds6sv.ondigitalocean.app/docs |
| GitHub | `https://github.com/williammw/agdoc` (private, `master`) |

> When working on AGDOC from a Claude Code session, use the smmp-side
> `agdoc-deploy` skill — it codifies the commit → push → DO deploy → verify loop.

## Development Commands

```bash
# Activate virtual environment (Python 3.10+ required)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest

# Generate an encryption key
python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Local env lives in `.env` (gitignored). FFmpeg must be installed
(`brew install ffmpeg`); `FFMPEG_PATH` points at the binary.

## Architecture

FastAPI service — `AGDOC Media Processing API` (v2.0.0). Entry point `app/main.py`.

```
app/
├── main.py            # FastAPI app, middleware, router registration, lifespan
├── routers/           # API route handlers
│   ├── media.py       # /api/v1/media   — upload, library, thumbnails, zip, ffmpeg-info
│   ├── ai.py          # /api/v1/ai      — transform, generate, models, platforms, health
│   ├── compose.py     # /api/v1/compose — composition jobs
│   └── videos.py      # /api/v1/videos  — subtitle burn, slideshow, job status
├── services/          # ai_service.py — AI provider integration
├── models/            # Pydantic models
├── db/                # Supabase client / data access
├── dependencies/      # FastAPI dependencies (API-key guard, etc.)
├── middleware/        # ProxyHeaders + custom middleware
└── utils/             # encryption, helpers
```

### Router pattern: `router` vs `public_router`

Several routers expose two `APIRouter`s on the same prefix:
- `router` — authenticated routes
- `public_router` — service-to-service routes that smmp calls with the
  `INTERNAL_API_KEY` (`x-api-key` header)

## API Endpoints

### Media — `/api/v1/media`
- `POST /upload` — upload media
- `GET /status/{media_id}` — processing status
- `GET /library` — list media
- `DELETE /{media_id}` — delete media
- `GET /variants/{media_id}` — media variants
- `POST /generate-thumbnail` *(public)* — video thumbnail generation
- `POST /create-zip` *(public)* — bundle files into a zip
- `GET /ffmpeg-info` *(public)* — FFmpeg build/codec info

### AI — `/api/v1/ai`
- `POST /transform` — AI media transform
- `POST /generate` — AI media generation
- `GET /models` — available models
- `GET /platforms` — platform info
- `GET /health` — AI subsystem health
- `POST /test` — test endpoint

### Compose — `/api/v1/compose`
- `POST ""` *(public)* — submit a composition job
- `GET /{job_id}` *(public)* — composition job status
- `GET /my-jobs` — caller's jobs

### Videos — `/api/v1/videos` *(all public)*
- `POST /subtitle` — burn subtitles (ASS/SRT, force_style)
- `POST /slideshow` — build a slideshow video
- `GET /jobs/{job_id}` — video job status

## Environment Configuration

Production env vars are set on the **DigitalOcean App Platform** app
(`jellyfish-app`). Local dev mirrors them in `.env`. Key groups:

```env
# Database — Supabase only (no DigitalOcean Postgres)
SUPABASE_URL=https://mzlspxsxifcqotacrhek.supabase.co
SUPABASE_KEY=<anon key>
SUPABASE_SERVICE_KEY=<service-role key>

# Service-to-service auth (smmp -> agdoc)
INTERNAL_API_KEY=<shared secret, sent by smmp as AGDOC_INTERNAL_API_KEY>

# Encryption (base64-encoded 32-byte key)
ENCRYPTION_KEY=<key>

# Cloudflare R2 (shared bucket: multivio)
R2_ENDPOINT_URL=...   R2_ACCESS_KEY_ID=...   R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=multivio   R2_DEV_URL=cdn.multivio.com

# Media processing
FFMPEG_PATH=/opt/homebrew/bin/ffmpeg   # local; container path differs

# AI providers
XAI_API_KEY / GROK_API_KEY   GEMINI_API_KEY   TOGETHER_API_KEY
REPLICATE_API_TOKEN   OPENAI_API_KEY

# Firebase Admin SDK (token verification only)
FIREBASE_PROJECT_ID / FIREBASE_CLIENT_EMAIL / FIREBASE_PRIVATE_KEY ...
```

## .claude Skills

Domain skills live in `.claude/skills/`:
- `ffmpeg-expert` — FFmpeg command construction and pipelines
- `media-validation` — input validation for media uploads
- `async-processing` — async job processing patterns
- `api-architect` — FastAPI endpoint/architecture guidance

## Common Tasks

### Adding a media-processing endpoint
1. Add the route to the relevant router (`media` / `compose` / `videos`)
2. Decide `router` (authenticated) vs `public_router` (smmp service calls)
3. Build the FFmpeg command — see the `ffmpeg-expert` skill
4. Validate inputs — see the `media-validation` skill
5. For long jobs, use the async job pattern (`async-processing` skill)

### Database changes
AGDOC uses the shared Supabase project. Schema changes are coordinated with
smmp — apply migrations against Supabase, not a separate AGDOC database.

## Troubleshooting

| Issue | Check |
|-------|-------|
| Deploy didn't take effect | Did GitHub Actions build succeed? Did App Platform pull the new `:latest`? |
| `401` on internal calls | `INTERNAL_API_KEY` here must match smmp's `AGDOC_INTERNAL_API_KEY` |
| Encryption key errors | `ENCRYPTION_KEY` must be a base64-encoded 32-byte key |
| FFmpeg not found | Install FFmpeg; verify `FFMPEG_PATH` |
| CORS errors | Add the frontend origin to allowed CORS origins in `main.py` |

## Security Notes

- Internal endpoints are gated by the `INTERNAL_API_KEY` shared secret
- OAuth tokens (where stored) are encrypted at rest via `app/utils/encryption.py`
- Never commit secrets — `.env` is gitignored
- App Platform env vars should use the encrypted `SECRET` type, not plaintext

---

**Service:** AGDOC Media Processing API · FastAPI v2.0.0
**Role:** Media-processing microservice for Multivio (frontend = `smmp`)
**Deploy:** push `master` → GitHub Actions → DOCR image → App Platform auto-deploy
