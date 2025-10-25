# Social Media Platform Integration

## 🌐 Overview

The Multivio backend integrates with **7 major social media platforms**, providing unified content publishing, multi-account support, and real-time status tracking. Each platform has specific API requirements and content limitations.

### Supported Platforms

| Platform | API Version | Authentication | Content Types | Rate Limits |
|----------|-------------|----------------|---------------|-------------|
| **Twitter/X** | v2 + v1.1 | OAuth 2.0 + 1.0a | Text, Images, Videos, Polls | 300/hour |
| **Facebook** | Graph API v21.0 | OAuth 2.0 | Text, Images, Videos, Links | 200/hour |
| **Instagram** | Graph API v21.0 | OAuth 2.0 | Images, Videos, Stories, Reels | 200/hour |
| **LinkedIn** | REST API v2 | OAuth 2.0 | Text, Images, Articles, Videos | 100/hour |
| **YouTube** | Data API v3 | OAuth 2.0 | Videos, Shorts, Thumbnails | 10,000/day |
| **TikTok** | TikTok API v2 | OAuth 2.0 | Videos, Captions | 100/hour |
| **Threads** | Graph API v21.0 | OAuth 2.0 | Text, Images | 200/hour |

---

## 🐦 Twitter/X Integration

### Dual OAuth Architecture

Twitter requires different authentication methods for different operations:

- **OAuth 2.0**: Text posts, profile access, follower management
- **OAuth 1.0a**: Media uploads, video posts, advanced operations

### Implementation Details

**Platform Publisher in `app/services/platform_publisher.py`:**
```python
async def publish_to_twitter(content: dict, connection: dict, media_files: list = None):
    """Publish content to Twitter/X with automatic OAuth selection"""

    # Determine required OAuth version
    has_media = bool(media_files)
    oauth_version = "oauth1" if has_media else "oauth2"

    # Get appropriate tokens
    tokens = await get_twitter_tokens(connection, oauth_version)

    if oauth_version == "oauth1":
        # Use OAuth 1.0a for media uploads
        return await publish_with_oauth1(content, tokens, media_files)
    else:
        # Use OAuth 2.0 for text posts
        return await publish_with_oauth2(content, tokens)
```

### Content Specifications

| Content Type | Character Limit | Media Support | Additional Features |
|--------------|-----------------|----------------|-------------------|
| Text Post | 280 | ❌ | Hashtags, mentions, links |
| Image Post | 280 | ✅ (4 images) | Alt text, multiple images |
| Video Post | 280 | ✅ (2.7GB, 2:20) | Captions, thumbnails |
| Poll | 280 | ❌ | 4 options, 7 days max |

### API Endpoints Used

- **Text Posts**: `https://api.twitter.com/2/tweets`
- **Media Upload**: `https://upload.twitter.com/1.1/media/upload.json`
- **Token Refresh**: `https://api.twitter.com/2/oauth2/token`

---

## 📘 Facebook Integration

### Multi-Account Architecture

Facebook supports multiple account types:
- **Personal Profile**: Individual user posts
- **Business Pages**: Company/organization pages
- **Groups**: Community group posts

### Page Synchronization

**Facebook Pages Sync Process:**
```python
async def sync_facebook_pages(user_id: int, access_token: str):
    """Sync Facebook pages as separate connections"""

    # Get user's pages
    pages_response = await facebook_api_call(
        f"/me/accounts?access_token={access_token}"
    )

    for page in pages_response['data']:
        # Get page access token
        page_token_response = await facebook_api_call(
            f"/{page['id']}?fields=access_token&access_token={access_token}"
        )

        # Check for Instagram Business Account
        instagram_account = await get_instagram_business_account(
            page['id'], page_token_response['access_token']
        )

        # Store as separate connection
        await store_social_connection({
            "user_id": user_id,
            "provider": "facebook",
            "provider_account_id": page['id'],
            "access_token": encrypt_token(page_token_response['access_token']),
            "account_type": "page",
            "account_label": page['name'],
            "metadata": {
                "page_name": page['name'],
                "page_category": page.get('category'),
                "instagram_business_account": instagram_account
            }
        })
```

### Content Specifications

| Content Type | Character Limit | Media Support | Targeting |
|--------------|-----------------|----------------|-----------|
| Text Post | Unlimited | ❌ | Public, Friends, Custom |
| Image Post | Unlimited | ✅ (Multiple) | All targeting options |
| Video Post | Unlimited | ✅ (4GB, 240min) | All targeting options |
| Link Post | Unlimited | ✅ (Thumbnail) | All targeting options |

### Instagram Business Integration

Facebook pages can be linked to Instagram Business accounts:
```python
async def get_instagram_business_account(page_id: str, page_token: str):
    """Get Instagram Business Account linked to Facebook Page"""

    response = await facebook_api_call(
        f"/{page_id}?fields=instagram_business_account&access_token={page_token}"
    )

    if 'instagram_business_account' in response:
        ig_account = response['instagram_business_account']
        return {
            "id": ig_account['id'],
            "username": ig_account.get('username'),
            "profile_picture_url": ig_account.get('profile_picture_url')
        }

    return None
```

---

## 💼 LinkedIn Integration

### Organization Support

LinkedIn supports posting to both personal profiles and organization pages.

### Content Specifications

| Content Type | Character Limit | Media Support | Visibility |
|--------------|-----------------|----------------|------------|
| Text Post | 3,000 | ❌ | Public, Connections |
| Image Post | 3,000 | ✅ (Single/Multiple) | All options |
| Video Post | 3,000 | ✅ (200MB, 10min) | All options |
| Article | 40,000 | ✅ | Public only |

### Organization Discovery

**Find user's organizations:**
```python
async def get_linkedin_organizations(access_token: str):
    """Get LinkedIn organizations user can post to"""

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": "202401"
    }

    response = await linkedin_api_call(
        "/organizationAcls?q=roleAssignee",
        headers=headers
    )

    organizations = []
    for org_acl in response['elements']:
        org_details = await get_organization_details(
            org_acl['organization'], access_token
        )
        organizations.append(org_details)

    return organizations
```

### Article Posting

LinkedIn articles require special handling:
```python
async def publish_linkedin_article(content: dict, connection: dict):
    """Publish article to LinkedIn"""

    article_data = {
        "author": f"urn:li:person:{connection['provider_account_id']}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": content['title']
                },
                "shareMediaCategory": "ARTICLE",
                "media": [{
                    "status": "READY",
                    "description": {
                        "text": content['content']
                    },
                    "originalUrl": content.get('url'),
                    "title": {
                        "text": content['title']
                    }
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    return await linkedin_api_call("/ugcPosts", method="POST", json=article_data)
```

---

## 📹 YouTube Integration

### Video Upload Process

YouTube integration focuses on video content creation and publishing.

### Content Specifications

| Content Type | Duration | Size Limit | Privacy |
|--------------|----------|------------|---------|
| Regular Video | Unlimited | 256GB | Public, Private, Unlisted |
| Short | 60 seconds | 9GB | Public, Private |

### Upload Implementation

**Large file upload with resumable API:**
```python
async def upload_to_youtube(video_file: dict, metadata: dict, connection: dict):
    """Upload video to YouTube with resumable upload"""

    # Initialize resumable upload
    upload_url = await initialize_youtube_upload(metadata, connection['access_token'])

    # Upload in chunks
    with open(video_file['path'], 'rb') as f:
        chunk_size = 1024 * 1024  # 1MB chunks
        uploaded_bytes = 0

        while uploaded_bytes < video_file['size']:
            chunk = f.read(chunk_size)

            headers = {
                'Content-Length': str(len(chunk)),
                'Content-Range': f'bytes {uploaded_bytes}-{uploaded_bytes + len(chunk) - 1}/{video_file["size"]}'
            }

            response = await youtube_api_call(
                upload_url,
                method='PUT',
                headers=headers,
                data=chunk,
                access_token=connection['access_token']
            )

            uploaded_bytes += len(chunk)

            if response.status_code == 308:  # Resume incomplete
                continue
            elif response.status_code in [200, 201]:
                return response.json()  # Upload complete
```

### Thumbnail Management

```python
async def upload_thumbnail(video_id: str, thumbnail_path: str, access_token: str):
    """Upload custom thumbnail for video"""

    with open(thumbnail_path, 'rb') as f:
        thumbnail_data = f.read()

    response = await youtube_api_call(
        f"/videos?part=snippet&id={video_id}",
        method="PUT",
        headers={
            "Content-Type": "application/octet-stream"
        },
        data=thumbnail_data,
        access_token=access_token
    )

    return response.json()
```

---

## 🎵 TikTok Integration

### Video-First Platform

TikTok integration focuses on short-form video content.

### Content Specifications

| Content Type | Duration | Size Limit | Privacy |
|--------------|----------|------------|---------|
| Video | 3-180 seconds | 500MB | Public, Private, Friends |

### Upload Process

**TikTok video upload:**
```python
async def upload_to_tiktok(video_data: dict, metadata: dict, connection: dict):
    """Upload video to TikTok"""

    # Initialize upload
    init_response = await tiktok_api_call(
        "/video/init/",
        method="POST",
        json={
            "open_id": connection['provider_account_id'],
            "access_token": connection['access_token']
        }
    )

    upload_url = init_response['data']['upload_url']

    # Upload video file
    with open(video_data['path'], 'rb') as f:
        video_content = f.read()

    upload_response = await tiktok_api_call(
        upload_url,
        method="PUT",
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(len(video_content))
        },
        data=video_content
    )

    # Publish video
    publish_response = await tiktok_api_call(
        "/video/publish/",
        method="POST",
        json={
            "open_id": connection['provider_account_id'],
            "access_token": connection['access_token'],
            "video_id": init_response['data']['video_id'],
            "title": metadata.get('title', ''),
            "description": metadata.get('description', ''),
            "privacy_level": metadata.get('privacy', 'PUBLIC')
        }
    )

    return publish_response
```

---

## 🧵 Threads Integration

### Text-Focused Platform

Threads integration via Meta's Graph API.

### Content Specifications

| Content Type | Character Limit | Media Support | Features |
|--------------|-----------------|----------------|----------|
| Text Post | 500 | ❌ | Links, mentions |
| Image Post | 500 | ✅ (Single) | Alt text, captions |

### Publishing Implementation

```python
async def publish_to_threads(content: dict, media_url: str = None, connection: dict):
    """Publish content to Threads"""

    post_data = {
        "media_type": "TEXT" if not media_url else "IMAGE",
        "text": content['content']
    }

    if media_url:
        # Upload image first
        media_response = await threads_api_call(
            "/threads/threads_media",
            method="POST",
            json={
                "media_type": "IMAGE",
                "image_url": media_url,
                "alt_text": content.get('alt_text', '')
            },
            access_token=connection['access_token']
        )

        post_data.update({
            "media_type": "IMAGE",
            "media_id": media_response['id']
        })

    # Create post
    response = await threads_api_call(
        "/threads/threads_publish",
        method="POST",
        json=post_data,
        access_token=connection['access_token']
    )

    return response
```

---

## 🔄 Platform Publisher Service

### Unified Publishing Interface

**Core service in `app/services/platform_publisher.py`:**
```python
class PlatformPublisher:
    def __init__(self):
        self.platforms = {
            'twitter': TwitterPublisher(),
            'facebook': FacebookPublisher(),
            'instagram': InstagramPublisher(),
            'linkedin': LinkedInPublisher(),
            'youtube': YouTubePublisher(),
            'tiktok': TikTokPublisher(),
            'threads': ThreadsPublisher()
        }

    async def publish_content(self, platform: str, content: dict,
                            connection: dict, media_files: list = None) -> dict:
        """Unified publishing interface"""

        if platform not in self.platforms:
            raise ValueError(f"Unsupported platform: {platform}")

        publisher = self.platforms[platform]

        try:
            result = await publisher.publish(content, connection, media_files)

            # Store publishing result
            await store_publish_result(
                user_id=connection['user_id'],
                platform=platform,
                content_id=result.get('id'),
                status='success',
                metadata=result
            )

            return result

        except Exception as e:
            # Store failure result
            await store_publish_result(
                user_id=connection['user_id'],
                platform=platform,
                status='failed',
                error=str(e)
            )
            raise
```

### Error Handling

**Platform-specific error handling:**
```python
class PlatformError(Exception):
    def __init__(self, platform: str, error_code: str, message: str, retryable: bool = False):
        self.platform = platform
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{platform}: {message}")

# Platform-specific error codes
PLATFORM_ERRORS = {
    'twitter': {
        'RATE_LIMIT_EXCEEDED': PlatformError('twitter', 'rate_limit', 'Rate limit exceeded', True),
        'DUPLICATE_STATUS': PlatformError('twitter', 'duplicate', 'Duplicate tweet'),
        'MEDIA_UPLOAD_FAILED': PlatformError('twitter', 'media_error', 'Media upload failed', True)
    },
    'facebook': {
        'ACCESS_TOKEN_EXPIRED': PlatformError('facebook', 'token_expired', 'Access token expired'),
        'PERMISSION_DENIED': PlatformError('facebook', 'permission', 'Insufficient permissions'),
        'ACCOUNT_DISABLED': PlatformError('facebook', 'disabled', 'Account disabled')
    }
    # ... other platforms
}
```

---

## 📊 Publishing Analytics

### Real-time Status Tracking

**Publishing results storage:**
```sql
CREATE TABLE publishing_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id INTEGER NOT NULL REFERENCES users(id),
  post_id UUID REFERENCES posts(id),
  platform VARCHAR(50) NOT NULL,
  platform_post_id VARCHAR(255),
  status VARCHAR(50) NOT NULL, -- success, failed, pending
  error_message TEXT,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_publishing_results_user_id ON publishing_results(user_id);
CREATE INDEX idx_publishing_results_post_id ON publishing_results(post_id);
CREATE INDEX idx_publishing_results_platform ON publishing_results(platform);
CREATE INDEX idx_publishing_results_status ON publishing_results(status);
```

### Analytics Queries

**Publishing success rates:**
```sql
SELECT
  platform,
  COUNT(*) as total_posts,
  COUNT(*) FILTER (WHERE status = 'success') as successful_posts,
  ROUND(
    COUNT(*) FILTER (WHERE status = 'success')::decimal /
    COUNT(*)::decimal * 100, 2
  ) as success_rate
FROM publishing_results
WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY platform
ORDER BY total_posts DESC;
```

**Platform performance comparison:**
```sql
SELECT
  platform,
  AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_publish_time,
  COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
  COUNT(*) FILTER (WHERE error_message LIKE '%rate%limit%') as rate_limit_errors
FROM publishing_results
WHERE status IN ('success', 'failed')
  AND created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY platform;
```

---

## 🔧 Platform Configuration

### Environment Variables

```bash
# Twitter/X
TWITTER_API_KEY=your_twitter_api_key
TWITTER_API_SECRET=your_twitter_api_secret
TWITTER_BEARER_TOKEN=your_bearer_token

# Facebook
FACEBOOK_APP_ID=your_facebook_app_id
FACEBOOK_APP_SECRET=your_facebook_app_secret

# Instagram
INSTAGRAM_APP_ID=your_instagram_app_id
INSTAGRAM_APP_SECRET=your_instagram_app_secret

# LinkedIn
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret

# YouTube
YOUTUBE_CLIENT_ID=your_youtube_client_id
YOUTUBE_CLIENT_SECRET=your_youtube_client_secret

# TikTok
TIKTOK_CLIENT_KEY=your_tiktok_client_key
TIKTOK_CLIENT_SECRET=your_tiktok_client_secret

# Threads (Meta)
THREADS_APP_ID=your_threads_app_id
THREADS_APP_SECRET=your_threads_app_secret
```

### Platform Limits Configuration

**Built-in platform limits:**
```python
PLATFORM_LIMITS = {
    'twitter': {
        'max_characters': 280,
        'max_images': 4,
        'max_video_duration': 140,  # seconds
        'supported_formats': ['jpg', 'png', 'gif', 'mp4', 'mov']
    },
    'facebook': {
        'max_characters': None,  # Unlimited
        'max_video_duration': 14400,  # 4 hours
        'supported_formats': ['jpg', 'png', 'gif', 'mp4', 'mov', 'avi']
    },
    'instagram': {
        'max_characters': 2200,
        'max_video_duration': 90,  # 1.5 minutes
        'supported_formats': ['jpg', 'png', 'mp4', 'mov']
    },
    'linkedin': {
        'max_characters': 3000,
        'max_video_duration': 600,  # 10 minutes
        'supported_formats': ['jpg', 'png', 'gif', 'mp4', 'mov']
    },
    'youtube': {
        'max_title_length': 100,
        'max_description_length': 5000,
        'max_video_duration': None,  # Unlimited
        'supported_formats': ['mp4', 'mov', 'avi', 'wmv', 'flv', 'webm']
    },
    'tiktok': {
        'max_characters': 4000,
        'min_video_duration': 3,  # seconds
        'max_video_duration': 180,  # 3 minutes
        'supported_formats': ['mp4', 'mov', 'avi']
    },
    'threads': {
        'max_characters': 500,
        'max_images': 1,
        'supported_formats': ['jpg', 'png']
    }
}
```

---

## 🧪 Testing Platform Integrations

### Unit Tests

**Platform publisher tests:**
```python
@pytest.mark.asyncio
async def test_twitter_publishing():
    """Test Twitter content publishing"""
    publisher = PlatformPublisher()

    content = {
        "content": "Test tweet #hashtag",
        "hashtags": ["hashtag"]
    }

    connection = {
        "access_token": "encrypted_token",
        "oauth1_access_token": "encrypted_oauth1_token"
    }

    result = await publisher.publish_content(
        'twitter', content, connection
    )

    assert result['status'] == 'success'
    assert 'tweet_id' in result

@pytest.mark.asyncio
async def test_facebook_page_sync():
    """Test Facebook page synchronization"""
    user_id = 123
    access_token = "valid_facebook_token"

    result = await sync_facebook_pages(user_id, access_token)

    assert result['pages_synced'] >= 0
    assert result['message'] == "Facebook pages synchronized successfully"
```

### Integration Tests

**End-to-end publishing test:**
```python
@pytest.mark.asyncio
async def test_full_publishing_flow(client, test_user):
    """Test complete publishing workflow"""

    # Create post
    post_data = {
        "name": "Test Post",
        "universal_content": "Test content for all platforms",
        "platforms": ["twitter", "facebook"]
    }

    post_response = await client.post(
        "/api/v1/posts",
        json=post_data,
        headers={"Authorization": f"Bearer {test_user['token']}"}
    )

    post_id = post_response.json()['id']

    # Publish post
    publish_response = await client.post(
        f"/api/v1/posts/{post_id}/publish",
        headers={"Authorization": f"Bearer {test_user['token']}"}
    )

    assert publish_response.status_code == 200
    result = publish_response.json()

    assert result['success'] == True
    assert len(result['published_to']) == 2
```

---

## 📈 Monitoring & Health Checks

### Platform Health Monitoring

**Health check endpoints:**
```python
@app.get("/health/platforms")
async def platform_health_check():
    """Check health of all platform integrations"""

    health_status = {}

    for platform in SUPPORTED_PLATFORMS:
        try:
            # Test API connectivity
            is_healthy = await test_platform_connectivity(platform)
            health_status[platform] = {
                "status": "healthy" if is_healthy else "unhealthy",
                "last_checked": datetime.utcnow().isoformat(),
                "response_time": None  # Could measure actual response time
            }
        except Exception as e:
            health_status[platform] = {
                "status": "error",
                "error": str(e),
                "last_checked": datetime.utcnow().isoformat()
            }

    return health_status
```

### Rate Limit Monitoring

**Rate limit tracking:**
```python
class RateLimitTracker:
    def __init__(self):
        self.requests = {}  # platform -> [timestamps]

    async def check_rate_limit(self, platform: str, user_id: int) -> bool:
        """Check if user is within rate limits"""

        now = datetime.utcnow()
        window_start = now - timedelta(hours=1)

        # Clean old requests
        self.requests[platform] = [
            ts for ts in self.requests.get(platform, [])
            if ts > window_start
        ]

        # Check current request count
        current_requests = len(self.requests[platform])

        if current_requests >= PLATFORM_RATE_LIMITS[platform]:
            return False

        # Add current request
        self.requests[platform].append(now)
        return True
```

---

**Version**: 3.0.1
**Last Updated**: September 2025
**Platforms**: 7 Active Integrations ✅
