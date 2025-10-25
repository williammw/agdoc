# API Reference Documentation

## 📋 Overview

This document provides comprehensive reference for all API endpoints in the Multivio backend. The API is built with FastAPI and provides RESTful endpoints for social media management, AI content generation, authentication, and more.

### Base URL
- **Development**: `https://dev.ohmeowkase.com`
- **Production**: `https://jellyfish-app-ds6sv.ondigitalocean.app`

### Authentication
All endpoints (except health checks) require Firebase authentication:
```
Authorization: Bearer <firebase_token>
```

### Content Type
All requests use JSON:
```
Content-Type: application/json
```

---

## 🔐 Authentication Endpoints (`/api/v1/auth`)

### GET `/me`
Get current user profile and account information.

**Response:**
```json
{
  "firebase_uid": "string",
  "user_id": 123,
  "email": "user@example.com",
  "full_name": "John Doe",
  "display_name": "John",
  "work_description": "Software Developer",
  "bio": "Passionate about building great products",
  "avatar_url": "https://...",
  "email_verified": true,
  "auth_provider": "google",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

### PUT `/profile`
Update user profile information.

**Request Body:**
```json
{
  "full_name": "John Doe",
  "display_name": "John",
  "work_description": "Software Developer",
  "bio": "Passionate about building great products"
}
```

**Response:** Same as GET `/me`

### POST `/oauth/{provider}`
Handle OAuth callback for social media platform connection.

**Supported Providers:** `google`, `facebook`, `twitter`, `linkedin`, `instagram`, `threads`, `youtube`, `tiktok`

**Request Body:**
```json
{
  "provider": "facebook",
  "provider_account_id": "123456789",
  "access_token": "access_token_here",
  "refresh_token": "refresh_token_here",
  "expires_in": 86400,
  "user_session_email": "user@example.com",
  "email": "user@example.com",
  "name": "Display Name",
  "picture": "https://avatar-url.com/image.jpg",
  "metadata": {
    "additional": "platform_specific_data"
  }
}
```

**Response:**
```json
{
  "firebase_uid": "firebase_user_id",
  "user_id": 123,
  "email": "user@example.com",
  "full_name": "Display Name",
  "avatar_url": "https://avatar-url.com/image.jpg",
  "connection_created": true,
  "account_type": "personal"
}
```

---

## 🔗 Social Connections (`/api/v1/social-connections`)

### GET `/connections`
List all connected social media accounts for the authenticated user.

**Query Parameters:**
- `include_tokens` (boolean): Include encrypted tokens in response (default: false)

**Response:**
```json
[
  {
    "id": "uuid",
    "provider": "twitter",
    "provider_account_id": "12345",
    "account_label": "@username",
    "account_type": "personal",
    "is_primary": true,
    "metadata": {
      "screen_name": "username",
      "followers_count": 1234
    },
    "created_at": "2024-01-01T00:00:00Z",
    "access_token": "encrypted_token", // only if include_tokens=true
    "refresh_token": "encrypted_token"  // only if include_tokens=true
  }
]
```

### POST `/store-token`
Store OAuth tokens for a social media connection.

**Request Body:**
```json
{
  "provider": "facebook",
  "provider_account_id": "12345",
  "access_token": "encrypted_access_token",
  "refresh_token": "encrypted_refresh_token",
  "expires_at": "2024-12-31T23:59:59Z",
  "metadata": {
    "account_type": "business",
    "account_label": "Business Page"
  }
}
```

### DELETE `/account/{connection_id}`
Remove a specific social media account connection.

**Response:**
```json
{
  "success": true,
  "message": "Account removed successfully"
}
```

### PUT `/account/{connection_id}/primary`
Set an account as the primary account for its provider.

**Response:**
```json
{
  "success": true,
  "message": "Primary account updated successfully"
}
```

### PUT `/account/{connection_id}/label`
Update the label for a specific account.

**Request Body:**
```json
{
  "account_label": "New Label"
}
```

### POST `/sync-facebook-pages`
Sync Facebook pages as separate connections (for multi-account support).

**Response:**
```json
{
  "success": true,
  "pages_synced": 2,
  "message": "Facebook pages synchronized successfully"
}
```

### GET `/sync-status/{provider}`
Check if account synchronization is needed.

**Response:**
```json
{
  "needs_sync": false,
  "reason": "All accounts are synchronized"
}
```

### POST `/twitter-oauth1-initiate`
Initiate Twitter OAuth 1.0a flow for media uploads.

**Query Parameters:**
- `redirect_uri`: Frontend callback URI

**Response:**
```json
{
  "status": "success",
  "authorization_url": "https://api.twitter.com/oauth/authorize?oauth_token=...",
  "oauth_token": "request_token",
  "message": "Redirect user to authorization_url to complete OAuth flow"
}
```

### POST `/twitter-oauth1-callback`
Handle Twitter OAuth 1.0a callback and store tokens.

**Query Parameters:**
- `oauth_token`: OAuth token from Twitter
- `oauth_verifier`: OAuth verifier from Twitter

**Response:**
```json
{
  "status": "success",
  "message": "Twitter OAuth 1.0a flow completed successfully",
  "twitter_user": {
    "user_id": "12345",
    "screen_name": "username"
  },
  "oauth_version": "1.0a",
  "capabilities": ["media_upload", "oauth1_auth"]
}
```

### GET `/twitter-oauth1-status`
Check Twitter OAuth 1.0a authentication status.

**Response:**
```json
{
  "oauth1_authenticated": true,
  "oauth1_accounts_count": 1,
  "total_twitter_accounts": 1,
  "accounts": [
    {
      "provider_account_id": "12345",
      "screen_name": "username",
      "account_label": "@username",
      "is_primary": true,
      "oauth1_authenticated": true,
      "oauth1_created_at": "2024-12-22T10:30:00Z",
      "capabilities": ["media_upload", "oauth1_auth"]
    }
  ],
  "message": "Found 1 Twitter accounts with OAuth 1.0a authentication"
}
```

---

## 📝 Content Management (`/api/v1/posts`)

### GET `/posts`
List all posts for the authenticated user.

**Query Parameters:**
- `limit` (integer): Maximum number of posts to return (default: 50)
- `offset` (integer): Pagination offset (default: 0)
- `status` (string): Filter by status (`draft`, `published`, `scheduled`)

**Response:**
```json
[
  {
    "id": "uuid",
    "user_id": 123,
    "name": "My Post Title",
    "content_mode": "universal",
    "universal_content": "Content for all platforms",
    "universal_metadata": {},
    "platform_content": {},
    "platforms": ["twitter", "facebook"],
    "media_files": [],
    "schedule_date": null,
    "status": "draft",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

### GET `/posts/{post_id}`
Get a specific post by ID.

**Response:** Single post object (same format as above)

### POST `/posts`
Create a new post.

**Request Body:**
```json
{
  "name": "My Post Title",
  "content_mode": "universal",
  "universal_content": "Content for all platforms",
  "universal_metadata": {},
  "platform_content": {},
  "platforms": ["twitter", "facebook"],
  "media_files": [],
  "schedule_date": null
}
```

**Response:** Created post object

### PATCH `/posts/{post_id}`
Update an existing post (partial update for auto-save).

**Request Body:**
```json
{
  "name": "Updated Title",
  "universal_content": "Updated content"
}
```

**Response:** Updated post object

### DELETE `/posts/{post_id}`
Delete a post.

**Response:**
```json
{
  "success": true,
  "message": "Post deleted successfully"
}
```

### POST `/posts/{post_id}/publish`
Publish a post to selected platforms.

**Request Body:**
```json
{
  "platforms": ["twitter", "facebook"],
  "schedule_date": null // null for immediate publish
}
```

**Response:**
```json
{
  "success": true,
  "post_id": "uuid",
  "published_to": ["twitter", "facebook"],
  "scheduled_for": null,
  "message": "Post published successfully"
}
```

### GET `/posts/stats/summary`
Get posting statistics for the user.

**Response:**
```json
{
  "total_posts": 150,
  "published_posts": 120,
  "scheduled_posts": 15,
  "draft_posts": 15,
  "platform_breakdown": {
    "twitter": 80,
    "facebook": 65,
    "linkedin": 45,
    "instagram": 30
  },
  "recent_activity": [
    {
      "date": "2024-12-22",
      "posts_published": 5
    }
  ]
}
```

---

## 🤖 AI Content Generation (`/api/v1/ai`)

### POST `/transform`
Transform existing content using AI.

**Request Body:**
```json
{
  "content": "Your original content here",
  "transformation_type": "platform_optimize",
  "target_platform": "twitter",
  "target_tone": "professional",
  "target_length": 280,
  "additional_instructions": "Make it more engaging",
  "model": "grok-3-mini",
  "stream": false
}
```

**Response:**
```json
{
  "original_content": "...",
  "transformed_content": "...",
  "transformation_type": "platform_optimize",
  "target_platform": "twitter",
  "suggestions": ["Add a question", "Include emoji"],
  "reasoning": "Optimized for Twitter's character limit and engagement patterns",
  "model_used": "grok-3-mini",
  "processing_time": 1.23,
  "character_count": 275,
  "word_count": 45
}
```

### POST `/generate`
Generate new content from prompts.

**Request Body:**
```json
{
  "prompt": "Write about AI in social media",
  "topic": "Artificial Intelligence",
  "target_platform": "linkedin",
  "content_tone": "professional",
  "target_length": 500,
  "include_hashtags": true,
  "include_call_to_action": true,
  "context": "For a tech company audience",
  "model": "grok-4",
  "stream": false
}
```

**Response:**
```json
{
  "generated_content": "...",
  "prompt_used": "...",
  "target_platform": "linkedin",
  "suggestions": ["LinkedIn best practices", "Professional tone"],
  "hashtags": ["#AI", "#SocialMedia", "#Technology"],
  "reasoning": "Generated professional content optimized for LinkedIn audience",
  "model_used": "grok-4",
  "processing_time": 2.45,
  "character_count": 487,
  "word_count": 78
}
```

### GET `/models`
List available AI models.

**Response:**
```json
{
  "models": [
    {
      "id": "grok-4",
      "name": "Grok-4",
      "capability": "Latest and most advanced",
      "max_tokens": 4000,
      "best_for": ["Complex transformations", "Creative writing"]
    },
    {
      "id": "grok-3-mini",
      "name": "Grok-3-Mini",
      "capability": "Fast and efficient",
      "max_tokens": 2000,
      "best_for": ["Quick transformations", "Hashtag generation"]
    }
  ]
}
```

### GET `/platforms`
List supported social media platforms with optimization guidelines.

**Response:**
```json
{
  "platforms": [
    {
      "id": "twitter",
      "name": "Twitter/X",
      "character_limit": 280,
      "optimization": {
        "hooks": "Engaging first sentence",
        "hashtags": "2-3 relevant hashtags",
        "format": "Thread format for long content"
      }
    }
  ]
}
```

### GET `/health`
Check AI service health and configuration.

**Response:**
```json
{
  "status": "healthy",
  "grok_api_configured": true,
  "models_available": ["grok-4", "grok-3-mini"],
  "last_health_check": "2024-12-22T10:30:00Z"
}
```

### POST `/test`
Test AI service functionality.

**Response:**
```json
{
  "success": true,
  "test_result": "AI service is working correctly",
  "model_tested": "grok-3-mini",
  "response_time": 1.2
}
```

---

## 📅 Scheduling (`/api/v1/scheduling`)

### POST `/schedule`
Schedule a post for future publishing.

**Request Body:**
```json
{
  "post_id": "uuid",
  "schedule_date": "2024-12-25T09:00:00Z",
  "platforms": ["twitter", "facebook"],
  "timezone": "America/New_York"
}
```

**Response:**
```json
{
  "success": true,
  "scheduled_post_id": "uuid",
  "schedule_date": "2024-12-25T09:00:00Z",
  "platforms": ["twitter", "facebook"],
  "job_id": "scheduler_job_123"
}
```

### POST `/bulk-schedule`
Schedule multiple posts at once.

**Request Body:**
```json
{
  "posts": [
    {
      "post_id": "uuid1",
      "schedule_date": "2024-12-25T09:00:00Z",
      "platforms": ["twitter"]
    },
    {
      "post_id": "uuid2",
      "schedule_date": "2024-12-25T14:00:00Z",
      "platforms": ["facebook", "linkedin"]
    }
  ],
  "timezone": "America/New_York"
}
```

### GET `/queue`
Get current scheduling queue status.

**Response:**
```json
{
  "total_scheduled": 15,
  "pending_jobs": 5,
  "running_jobs": 2,
  "completed_today": 8,
  "failed_today": 0,
  "next_scheduled": "2024-12-22T15:30:00Z"
}
```

### DELETE `/cancel/{scheduled_post_id}`
Cancel a scheduled post.

**Response:**
```json
{
  "success": true,
  "message": "Scheduled post cancelled successfully"
}
```

---

## 📷 Media Management (`/api/v1/media`)

### POST `/upload`
Upload media files (images, videos).

**Content-Type:** `multipart/form-data`

**Form Data:**
- `file`: Media file
- `platform`: Target platform (optional)
- `alt_text`: Alternative text (optional)

**Response:**
```json
{
  "file_id": "uuid",
  "filename": "image.jpg",
  "file_type": "image/jpeg",
  "file_size": 1024000,
  "cdn_url": "https://cdn.multivio.com/uploads/uuid.jpg",
  "thumbnail_url": "https://cdn.multivio.com/thumbnails/uuid.jpg",
  "platform_compatibility": ["twitter", "facebook", "instagram"],
  "upload_date": "2024-12-22T10:30:00Z"
}
```

### GET `/library`
Get user's media library.

**Query Parameters:**
- `limit` (integer): Maximum items to return (default: 50)
- `offset` (integer): Pagination offset (default: 0)
- `file_type` (string): Filter by type (`image`, `video`)

**Response:**
```json
{
  "total_files": 150,
  "files": [
    {
      "file_id": "uuid",
      "filename": "image.jpg",
      "file_type": "image/jpeg",
      "file_size": 1024000,
      "cdn_url": "https://cdn.multivio.com/uploads/uuid.jpg",
      "thumbnail_url": "https://cdn.multivio.com/thumbnails/uuid.jpg",
      "platform_compatibility": ["twitter", "facebook"],
      "upload_date": "2024-12-22T10:30:00Z"
    }
  ]
}
```

### DELETE `/file/{file_id}`
Delete a media file.

**Response:**
```json
{
  "success": true,
  "message": "File deleted successfully"
}
```

### GET `/public/{file_id}`
Public access to media files (no authentication required).

**Response:** File content with appropriate Content-Type header

---

## 💳 Subscriptions (`/api/v1/subscriptions`)

### GET `/status`
Get current subscription status.

**Response:**
```json
{
  "subscription_active": true,
  "plan_name": "pro",
  "plan_id": "price_xxx",
  "status": "active",
  "current_period_start": "2024-12-01T00:00:00Z",
  "current_period_end": "2025-01-01T00:00:00Z",
  "cancel_at_period_end": false,
  "monthly_post_quota": 1000,
  "posts_used_this_month": 150,
  "posts_remaining": 850
}
```

### POST `/activate`
Activate a subscription (webhook handler for Stripe).

**Request Body:** Stripe webhook payload

**Response:**
```json
{
  "success": true,
  "message": "Subscription activated successfully"
}
```

### POST `/cancel`
Cancel current subscription.

**Response:**
```json
{
  "success": true,
  "message": "Subscription will be cancelled at period end",
  "cancel_at": "2025-01-01T00:00:00Z"
}
```

---

## 🔍 Health & Monitoring

### GET `/health`
Application health check.

**Response:**
```json
{
  "status": "healthy",
  "version": "3.0.1",
  "api": "Multivio API",
  "environment": "production",
  "database": "connected",
  "redis": "connected",
  "uptime": "30d 4h 15m",
  "timestamp": "2024-12-22T10:30:00Z"
}
```

### GET `/docs`
Interactive API documentation (Swagger UI).

### GET `/redoc`
Alternative API documentation (ReDoc).

### GET `/openapi.json`
OpenAPI schema definition.

---

## 📊 Error Responses

### Authentication Errors
```json
{
  "detail": "Authentication required",
  "type": "authentication_error",
  "status_code": 401
}
```

### Validation Errors
```json
{
  "detail": [
    {
      "loc": ["body", "content"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ],
  "type": "validation_error",
  "status_code": 422
}
```

### Platform Errors
```json
{
  "detail": "Twitter API rate limit exceeded",
  "type": "platform_error",
  "platform": "twitter",
  "retry_after": 900,
  "status_code": 429
}
```

### AI Service Errors
```json
{
  "detail": "AI service temporarily unavailable",
  "type": "ai_service_error",
  "retry_after": 60,
  "status_code": 503
}
```

---

## ⚡ Rate Limiting

The API implements rate limiting to prevent abuse:

- **General endpoints**: 100 requests per minute per user
- **AI endpoints**: 50 requests per minute per user
- **Media upload**: 20 uploads per minute per user
- **Publishing**: 30 posts per minute per user

Rate limit headers are included in responses:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1640995200
```

---

## 🔒 Security Headers

All responses include security headers:
```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'
Referrer-Policy: strict-origin-when-cross-origin
```

---

**Version**: 3.0.1
**Last Updated**: September 2025
**Base URL**: `https://jellyfish-app-ds6sv.ondigitalocean.app/api/v1`
