# Authentication & Security

## 🔐 Authentication Architecture

The Multivio backend implements a dual authentication system combining **Firebase Authentication** with **OAuth 2.0/1.0a** for social media platform access. All API endpoints require valid authentication except health checks.

### Authentication Flow

```
User Login → Firebase Auth → JWT Token Generation → API Request
      ↓              ↓              ↓              ↓
Frontend → Firebase SDK → Backend Validation → Database RLS
      ↓              ↓              ↓              ↓
Session ← Token Verify ← User Context ← Secure Access
```

---

## 🔥 Firebase Authentication

### Setup Requirements

**Environment Variables:**
```bash
# Firebase Configuration
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_CLIENT_EMAIL=service-account@project.iam.gserviceaccount.com
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
FIREBASE_CLIENT_ID=your-client-id
FIREBASE_AUTH_URI=https://accounts.google.com/o/oauth2/auth
FIREBASE_TOKEN_URI=https://oauth2.googleapis.com/token
```

### Firebase Admin SDK Integration

**Initialization in `app/utils/firebase.py`:**
```python
from firebase_admin import credentials, auth, initialize_app

cred = credentials.Certificate({
    "type": "service_account",
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI")
})

firebase_app = initialize_app(cred)
```

### Token Verification

**Middleware in `app/dependencies/auth.py`:**
```python
from firebase_admin import auth as firebase_auth
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def get_current_user(token: str = Depends(security)):
    """Verify Firebase token and return user context"""
    try:
        # Verify Firebase token
        decoded_token = firebase_auth.verify_id_token(token.credentials)

        # Get or create user in database
        user = await get_or_create_user(decoded_token)

        return {
            "firebase_uid": decoded_token["uid"],
            "user_id": user.id,
            "email": decoded_token.get("email"),
            "email_verified": decoded_token.get("email_verified", False)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
```

---

## 🌐 OAuth 2.0 Implementation

### Supported Platforms

| Platform | OAuth Version | Token Refresh | Multi-Account |
|----------|---------------|---------------|---------------|
| Twitter/X | 2.0 + 1.0a | 2 hours | ✅ |
| Facebook | 2.0 | 60 days | ✅ |
| Instagram | 2.0 | 60 days | ✅ |
| LinkedIn | 2.0 | Manual | ✅ |
| YouTube | 2.0 | Auto | ✅ |
| TikTok | 2.0 | 24 hours | ✅ |
| Threads | 2.0 | 60 days | ✅ |

### OAuth Flow Implementation

#### 1. Authorization URL Generation

**Endpoint:** `POST /api/v1/auth/oauth/{provider}`

**Process:**
```python
def generate_oauth_url(provider: str, redirect_uri: str) -> str:
    """Generate OAuth authorization URL for platform"""
    config = OAUTH_CONFIGS[provider]

    params = {
        'client_id': config['client_id'],
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': config['scope'],
        'state': generate_state_token()
    }

    if config.get('use_pkce'):
        verifier, challenge = generate_pkce()
        params.update({
            'code_challenge': challenge,
            'code_challenge_method': 'S256'
        })

    base_url = config['auth_url']
    return f"{base_url}?{urlencode(params)}"
```

#### 2. Callback Processing

**Process:**
```python
async def process_oauth_callback(provider: str, code: str, state: str):
    """Exchange authorization code for tokens"""
    # Verify state parameter
    if not verify_state_token(state):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Exchange code for tokens
    token_response = await exchange_code_for_tokens(provider, code)

    # Store connection
    connection = await store_social_connection(
        user_id=current_user['user_id'],
        provider=provider,
        tokens=token_response,
        metadata=profile_data
    )

    return connection
```

#### 3. Token Storage & Encryption

**Encryption in `app/utils/encryption.py`:**
```python
import os
from cryptography.fernet import Fernet

# Generate key from environment variable
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY environment variable required")

cipher = Fernet(ENCRYPTION_KEY.encode())

def encrypt_token(token: str) -> str:
    """Encrypt OAuth token"""
    if not token:
        return None
    return cipher.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypt OAuth token"""
    if not encrypted_token:
        return None
    return cipher.decrypt(encrypted_token.encode()).decode()
```

---

## 🐦 Twitter Dual OAuth Implementation

### Architecture Overview

Twitter requires **OAuth 1.0a** for media uploads and **OAuth 2.0** for text posts. The system automatically detects requirements and uses appropriate authentication.

```
Content Type → Authentication Method
     ↓              ↓
Text Only → OAuth 2.0 (Bearer Token)
Has Media → OAuth 1.0a (Signature)
```

### Database Schema Extensions

```sql
-- OAuth 1.0a columns added to social_connections
ALTER TABLE social_connections
ADD COLUMN oauth1_access_token TEXT,
ADD COLUMN oauth1_access_token_secret TEXT,
ADD COLUMN oauth1_user_id VARCHAR(255),
ADD COLUMN oauth1_screen_name VARCHAR(255),
ADD COLUMN oauth1_created_at TIMESTAMPTZ;
```

### OAuth 1.0a Flow

#### 1. Initiate OAuth 1.0a

**Endpoint:** `POST /api/v1/social-connections/twitter-oauth1-initiate`

```python
async def initiate_oauth1(user_id: int, redirect_uri: str):
    """Get OAuth 1.0a request token and authorization URL"""

    # Get request token from Twitter
    oauth = OAuth1Session(
        TWITTER_CONSUMER_KEY,
        client_secret=TWITTER_CONSUMER_SECRET
    )

    request_token_response = oauth.post(
        "https://api.twitter.com/oauth/request_token",
        data={"oauth_callback": redirect_uri}
    )

    request_token_data = dict(parse_qsl(request_token_response.text))
    request_token = request_token_data['oauth_token']

    # Store temporary request token
    await store_oauth1_request_token(user_id, request_token, request_token_data)

    # Generate authorization URL
    auth_url = f"https://api.twitter.com/oauth/authorize?oauth_token={request_token}"

    return {"authorization_url": auth_url, "oauth_token": request_token}
```

#### 2. Handle OAuth 1.0a Callback

**Endpoint:** `POST /api/v1/social-connections/twitter-oauth1-callback`

```python
async def handle_oauth1_callback(oauth_token: str, oauth_verifier: str, user_id: int):
    """Exchange request token for access token"""

    # Retrieve stored request token data
    request_data = await get_oauth1_request_token(oauth_token, user_id)

    # Create OAuth session with request token
    oauth = OAuth1Session(
        TWITTER_CONSUMER_KEY,
        client_secret=TWITTER_CONSUMER_SECRET,
        resource_owner_key=oauth_token,
        resource_owner_secret=request_data['oauth_token_secret'],
        verifier=oauth_verifier
    )

    # Exchange for access token
    access_token_response = oauth.post("https://api.twitter.com/oauth/access_token")
    access_token_data = dict(parse_qsl(access_token_response.text))

    # Store OAuth 1.0a credentials
    await store_oauth1_credentials(user_id, access_token_data)

    return {
        "status": "success",
        "capabilities": ["media_upload", "oauth1_auth"],
        "user": {
            "user_id": access_token_data['user_id'],
            "screen_name": access_token_data['screen_name']
        }
    }
```

### Signature Generation

**OAuth 1.0a Signature in `app/routers/social_connections.py`:**
```python
def generate_oauth1_signature(method: str, url: str, params: dict,
                            consumer_secret: str, token_secret: str = "") -> str:
    """Generate OAuth 1.0a HMAC-SHA1 signature"""

    # Create parameter string
    param_string = "&".join([f"{quote(k)}={quote(str(v))}"
                           for k, v in sorted(params.items())])

    # Create signature base string
    signature_base = f"{method.upper()}&{quote(url)}&{quote(param_string)}"

    # Create signing key
    signing_key = f"{quote(consumer_secret)}&{quote(token_secret)}"

    # Generate signature
    import hmac
    import hashlib
    signature = hmac.new(
        signing_key.encode(),
        signature_base.encode(),
        hashlib.sha1
    ).digest()

    return base64.b64encode(signature).decode()
```

---

## 🔄 Token Management System

### Automatic Token Refresh

**Supported Platforms:**
- **Twitter/X**: OAuth 2.0 refresh (2-hour expiry)
- **Facebook/Instagram/Threads**: Long-lived tokens (60-day expiry)
- **TikTok**: API v2 refresh (24-hour tokens, 1-year refresh)
- **YouTube**: Google OAuth auto-refresh (1-hour tokens)
- **LinkedIn**: Manual reconnection (no auto-refresh)

### Refresh Implementation

**Service in `app/services/token_manager.py`:**
```python
class TokenManager:
    def __init__(self):
        self.refresh_configs = {
            'twitter': {
                'threshold_hours': 1,
                'refresh_url': 'https://api.twitter.com/2/oauth2/token',
                'grant_type': 'refresh_token'
            },
            'facebook': {
                'threshold_days': 7,
                'refresh_url': 'https://graph.facebook.com/v21.0/oauth/access_token',
                'grant_type': 'fb_exchange_token'
            },
            # ... other platforms
        }

    async def refresh_token_if_needed(self, connection_id: str) -> bool:
        """Check and refresh token if approaching expiry"""
        connection = await self.get_connection(connection_id)

        if not self.needs_refresh(connection):
            return True

        try:
            new_tokens = await self.perform_refresh(connection)
            await self.update_connection_tokens(connection_id, new_tokens)
            return True
        except Exception as e:
            logger.error(f"Token refresh failed for {connection.provider}: {e}")
            return False
```

### Health Monitoring

**Background monitoring in `app/services/background_scheduler.py`:**
```python
async def monitor_token_health():
    """Background job to monitor token health"""
    while True:
        try:
            # Get connections expiring soon
            expiring_connections = await get_expiring_connections(hours=24)

            for connection in expiring_connections:
                success = await token_manager.refresh_token_if_needed(connection.id)

                if not success:
                    # Notify user of refresh failure
                    await notify_user_token_issue(connection.user_id, connection.provider)

            await asyncio.sleep(3600)  # Check every hour

        except Exception as e:
            logger.error(f"Token health monitoring error: {e}")
            await asyncio.sleep(300)  # Retry in 5 minutes
```

---

## 🔒 Security Measures

### Encryption Standards
- **AES-256**: Symmetric encryption for OAuth tokens
- **Environment Variables**: Keys never stored in code
- **Secure Generation**: Cryptographically secure key generation

### API Security
- **JWT Verification**: All requests validated with Firebase
- **Row Level Security**: Database-level access control
- **Rate Limiting**: Per-user and per-endpoint limits
- **CORS Protection**: Configured allowed origins
- **Input Validation**: Pydantic models for all requests

### Session Management
- **Stateless**: No server-side session storage
- **Secure Cookies**: HTTP-only, SameSite protection
- **Token Expiry**: 30-minute JWT expiration
- **Refresh Logic**: Automatic token refresh when needed

---

## 🛡️ Error Handling

### Authentication Errors
```json
{
  "detail": "Authentication required",
  "type": "authentication_error",
  "status_code": 401
}
```

### Token Errors
```json
{
  "detail": "OAuth token expired",
  "type": "token_expired_error",
  "platform": "twitter",
  "status_code": 401
}
```

### OAuth Errors
```json
{
  "detail": "OAuth authorization failed",
  "type": "oauth_error",
  "platform": "facebook",
  "error_code": "access_denied",
  "status_code": 400
}
```

---

## 🧪 Testing Authentication

### Unit Tests
```python
def test_firebase_token_verification():
    """Test Firebase token verification"""
    # Mock Firebase token
    mock_token = "eyJhbGciOiJSUzI1NiIsImtpZCI6..."

    # Verify token
    decoded = verify_firebase_token(mock_token)

    assert decoded["uid"] == "test_user_id"
    assert decoded["email"] == "test@example.com"

def test_oauth_token_encryption():
    """Test token encryption/decryption"""
    test_token = "test_access_token_123"

    # Encrypt
    encrypted = encrypt_token(test_token)
    assert encrypted != test_token

    # Decrypt
    decrypted = decrypt_token(encrypted)
    assert decrypted == test_token
```

### Integration Tests
```python
async def test_oauth_flow(client, test_user):
    """Test complete OAuth flow"""
    # Initiate OAuth
    response = await client.post(
        "/api/v1/auth/oauth/facebook",
        json={"redirect_uri": "http://localhost:3000/callback"}
    )

    assert response.status_code == 200
    auth_url = response.json()["authorization_url"]

    # Mock OAuth callback
    callback_response = await client.post(
        "/api/v1/auth/oauth/facebook/callback",
        json={
            "code": "mock_authorization_code",
            "state": "valid_state_token"
        }
    )

    assert callback_response.status_code == 200
    assert "connection_created" in callback_response.json()
```

---

## 📊 Monitoring & Analytics

### Authentication Metrics
- **Login Success Rate**: Percentage of successful authentications
- **Token Refresh Rate**: Frequency of token refreshes
- **Failed Authentication**: Rate of authentication failures
- **OAuth Completion Rate**: Success rate of OAuth flows

### Security Monitoring
- **Suspicious Activity**: Unusual authentication patterns
- **Token Expiry Alerts**: Proactive token refresh notifications
- **Rate Limit Hits**: Users hitting rate limits
- **Failed OAuth Attempts**: OAuth flow failures

### Logging Strategy
```python
# Authentication events
logger.info(f"User login: {user_id}", extra={
    "event": "user_login",
    "user_id": user_id,
    "provider": auth_provider,
    "ip_address": ip_address,
    "user_agent": user_agent
})

# OAuth events
logger.info(f"OAuth connection: {provider}", extra={
    "event": "oauth_connection",
    "user_id": user_id,
    "provider": provider,
    "account_type": account_type,
    "success": True
})

# Token refresh events
logger.info(f"Token refresh: {provider}", extra={
    "event": "token_refresh",
    "user_id": user_id,
    "provider": provider,
    "success": True,
    "expires_in": expires_in_seconds
})
```

---

**Version**: 3.0.1
**Last Updated**: September 2025
**Security Status**: 🔒 Enterprise Grade
