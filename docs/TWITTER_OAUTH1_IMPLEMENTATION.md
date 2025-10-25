# Twitter OAuth 1.0a Implementation

This document describes the newly implemented Twitter OAuth 1.0a flow for the FastAPI backend. This implementation enables media upload capabilities for Twitter/X through dedicated OAuth 1.0a authentication.

## Overview

The current Twitter OAuth 2.0 implementation supports text posting but lacks media upload capabilities. Twitter's media upload API requires OAuth 1.0a authentication, so this implementation adds a dual authentication system where users can have both OAuth 2.0 (for text posts) and OAuth 1.0a (for media uploads) tokens for their Twitter accounts.

## Architecture

### Database Schema Changes

Added new columns to the `social_connections` table:

```sql
-- OAuth 1.0a columns for dual authentication support
oauth1_access_token TEXT,           -- Encrypted OAuth 1.0a access token
oauth1_access_token_secret TEXT,    -- Encrypted OAuth 1.0a access token secret  
oauth1_user_id VARCHAR(255),        -- OAuth 1.0a user ID from Twitter
oauth1_screen_name VARCHAR(255),    -- OAuth 1.0a screen name from Twitter
oauth1_created_at TIMESTAMPTZ       -- Timestamp when OAuth 1.0a tokens were obtained
```

### File Changes

1. **`/app/routers/social_connections.py`** - Added three new endpoints and helper functions
2. **`/app/db/migrations/005_oauth1_columns.sql`** - Database migration for new columns
3. **`test_oauth1_endpoints.py`** - Test script for validation

## New API Endpoints

### 1. Initiate OAuth 1.0a Flow

**POST** `/api/v1/social-connections/twitter-oauth1-initiate`

**Parameters:**
- `redirect_uri` (query param): Frontend callback URI

**Response:**
```json
{
  "status": "success",
  "authorization_url": "https://api.twitter.com/oauth/authorize?oauth_token=...",
  "oauth_token": "request_token",
  "message": "Redirect user to authorization_url to complete OAuth flow"
}
```

**Purpose:** 
- Gets request token from Twitter using backend credentials
- Stores temporary request token data in database
- Returns authorization URL for frontend to redirect user

### 2. Handle OAuth 1.0a Callback

**POST** `/api/v1/social-connections/twitter-oauth1-callback`

**Parameters:**
- `oauth_token` (query param): OAuth token from Twitter callback
- `oauth_verifier` (query param): OAuth verifier from Twitter callback

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

**Purpose:**
- Exchanges request token for access token
- Stores OAuth 1.0a tokens in dedicated database columns
- Verifies tokens with Twitter API
- Updates existing Twitter connection or creates new one

### 3. Check OAuth 1.0a Status

**GET** `/api/v1/social-connections/twitter-oauth1-status`

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

**Purpose:**
- Checks which Twitter accounts have OAuth 1.0a authentication
- Returns capabilities for each account
- Helps frontend determine if media upload is available

## Helper Functions

### OAuth 1.0a Signature Generation

```python
def _generate_oauth1_signature(method, url, params, consumer_secret, token_secret=""):
    """Generate OAuth 1.0a HMAC-SHA1 signature"""
```

### OAuth 1.0a Header Generation

```python
def _generate_oauth1_header(method, url, consumer_key, consumer_secret, 
                           oauth_token=None, oauth_token_secret="", 
                           oauth_verifier=None, additional_params=None):
    """Generate complete OAuth 1.0a Authorization header"""
```

## Environment Variables Required

The implementation requires these environment variables in the backend:

```bash
TWITTER_CONSUMER_API_KEY=your_twitter_consumer_key
TWITTER_CONSUMER_API_SECRET=your_twitter_consumer_secret
```

These are the Twitter API v1.1 credentials (different from OAuth 2.0 credentials).

## Flow Diagram

```
1. Frontend calls /twitter-oauth1-initiate
   ↓
2. Backend gets request token from Twitter
   ↓
3. Backend stores temporary token data
   ↓
4. Backend returns authorization URL
   ↓
5. Frontend redirects user to Twitter
   ↓
6. User authorizes app on Twitter
   ↓
7. Twitter redirects to frontend callback
   ↓
8. Frontend calls /twitter-oauth1-callback
   ↓
9. Backend exchanges tokens with Twitter
   ↓
10. Backend stores OAuth 1.0a tokens
    ↓
11. Backend verifies tokens work
    ↓
12. Flow complete - media upload enabled
```

## Integration with Existing System

### Dual Authentication Support

- Users can have both OAuth 2.0 and OAuth 1.0a tokens for the same Twitter account
- OAuth 2.0 tokens stored in `access_token` column (for text posts)
- OAuth 1.0a tokens stored in `oauth1_*` columns (for media uploads)
- Platform publisher automatically uses OAuth 1.0a for media operations

### Backward Compatibility

- Existing OAuth 2.0 connections continue to work unchanged
- OAuth 1.0a tokens are additive - they enhance existing connections
- If OAuth 1.0a tokens not available, media upload gracefully fails with clear error

### Security

- All tokens encrypted using existing encryption utilities
- Temporary request token data expires after 15 minutes
- OAuth 1.0a tokens verified immediately after exchange
- Proper signature generation prevents token replay attacks

## Testing

Run the test script to validate implementation:

```bash
python test_oauth1_endpoints.py
```

## Frontend Integration

The frontend should:

1. Check OAuth 1.0a status before enabling media upload features
2. Initiate OAuth 1.0a flow when user wants to upload media but lacks tokens
3. Handle the callback flow after user authorization
4. Update UI to reflect OAuth 1.0a capabilities

Example frontend flow:
```javascript
// Check if user can upload media
const status = await fetch('/api/v1/social-connections/twitter-oauth1-status');
if (!status.oauth1_authenticated) {
  // Start OAuth 1.0a flow
  const initiate = await fetch('/api/v1/social-connections/twitter-oauth1-initiate?redirect_uri=...');
  window.location.href = initiate.authorization_url;
}
```

## Platform Publisher Integration

The existing platform publisher automatically detects OAuth 1.0a tokens and uses them for media upload operations. No changes needed to publishing code - it already has the logic to use OAuth 1.0a tokens when available.

## Deployment Notes

1. **Database Migration**: Run migration 005_oauth1_columns.sql before deploying
2. **Environment Variables**: Ensure Twitter OAuth 1.0a credentials are set
3. **Testing**: Verify endpoints work with Twitter's sandbox if available
4. **Monitoring**: Monitor OAuth 1.0a token usage and refresh patterns

## Troubleshooting

### Common Issues

1. **"Twitter OAuth 1.0a credentials not configured"**
   - Ensure TWITTER_CONSUMER_API_KEY and TWITTER_CONSUMER_API_SECRET are set

2. **"Invalid or expired request token"**
   - Request tokens expire after 15 minutes
   - User took too long to authorize or refreshed the page

3. **"Failed to exchange Twitter tokens"**
   - Check that Twitter app has correct callback URLs configured
   - Verify signature generation is working correctly

4. **Media upload still fails after OAuth 1.0a**
   - Check that tokens are being retrieved correctly in platform publisher
   - Verify encryption/decryption is working properly

### Debug Logging

The implementation includes extensive logging with emoji prefixes:
- 🐦 General Twitter OAuth flow
- 🔐 OAuth signature/header generation  
- ✅ Success operations
- 🚨 Error conditions
- 🧹 Cleanup operations

## Future Enhancements

1. **Token Refresh**: Implement OAuth 1.0a token refresh logic
2. **Multiple Apps**: Support multiple Twitter app credentials
3. **Scope Management**: Handle different permission scopes
4. **Batch Operations**: Optimize for multiple media uploads
5. **Rate Limiting**: Implement proper rate limiting for OAuth calls