# TikTok OAuth Implementation

**Status**: ✅ **COMPLETED & WORKING** - TikTok OAuth is fully implemented and operational.

This document describes the complete backend implementation for TikTok OAuth integration in the FastAPI application.

## Overview

The TikTok OAuth implementation follows the same patterns as other social media providers (Facebook, LinkedIn, Twitter, YouTube, etc.) and provides:

1. **OAuth Authentication Flow**: Process TikTok OAuth tokens and create/authenticate users
2. **Token Storage**: Securely encrypt and store TikTok access tokens and refresh tokens
3. **Profile Management**: Fetch and cache TikTok user profile data
4. **Multi-Account Support**: Support for multiple TikTok accounts per user
5. **API Testing**: Test endpoints to verify TikTok API connectivity

## API Endpoints

### 1. OAuth Authentication

**Endpoint**: `POST /api/v1/auth/oauth/tiktok`

**Purpose**: Process TikTok OAuth authentication and store user/token data

**Request Body**:
```json
{
  "provider": "tiktok",
  "provider_account_id": "tiktok_open_id_here",
  "access_token": "access_token_here",
  "refresh_token": "refresh_token_here",
  "expires_in": 86400,
  "user_session_email": "user@example.com",
  "email": "user@example.com",
  "name": "Display Name",
  "picture": "https://avatar-url.com/image.jpg",
  "metadata": {
    "additional": "tiktok_data"
  }
}
```

**Response**:
```json
{
  "firebase_uid": "firebase_user_id",
  "user_id": 123,
  "email": "user@example.com",
  "full_name": "Display Name",
  "avatar_url": "https://avatar-url.com/image.jpg",
  "email_verified": true,
  "auth_provider": "tiktok.com",
  "firebase_token": "custom_firebase_token"
}
```

**Features**:
- Creates Firebase user if doesn't exist
- Creates/updates database user record
- Stores encrypted TikTok tokens in social_connections table
- Supports multi-account scenarios
- Handles session email for authenticated users

### 2. Token Storage

**Endpoint**: `POST /api/v1/social-connections/store-token`

**Purpose**: Store or update TikTok OAuth tokens and profile data

**Request Body**:
```json
{
  "provider": "tiktok",
  "provider_account_id": "tiktok_open_id",
  "access_token": "encrypted_access_token",
  "refresh_token": "encrypted_refresh_token",
  "expires_at": "2024-12-31T23:59:59Z",
  "account_label": "My TikTok Account",
  "account_type": "personal",
  "is_primary": true,
  "profile_metadata": "{\"display_name\": \"User Name\"}"
}
```

**Features**:
- Encrypts tokens using Fernet encryption
- Handles token expiration timestamps
- Supports account labeling for multi-account management
- Updates existing connections or creates new ones

### 3. Profile Management

**Endpoint**: `GET /api/v1/social-connections/tiktok/profile`

**Purpose**: Fetch TikTok user profile (cached or from API)

**Query Parameters**:
- `force`: boolean (optional) - Force refresh from TikTok API

**Response**:
```json
{
  "open_id": "tiktok_open_id",
  "display_name": "User Display Name",
  "username": "username",
  "avatar_url": "https://avatar-url.com/image.jpg",
  "follower_count": 1000,
  "following_count": 500,
  "likes_count": 10000,
  "video_count": 50,
  "bio_description": "User bio",
  "is_verified": false
}
```

**Endpoint**: `POST /api/v1/social-connections/store-tiktok-profile`

**Purpose**: Manually store TikTok profile data

**Request Body**:
```json
{
  "profile": {
    "open_id": "tiktok_open_id",
    "display_name": "User Name",
    "avatar_url": "https://avatar-url.com/image.jpg",
    "follower_count": 1000,
    "bio_description": "User bio"
  }
}
```

### 4. Connection Testing

**Endpoint**: `GET /api/v1/social-connections/tiktok/test`

**Purpose**: Test TikTok API connectivity and token validity

**Response**:
```json
{
  "connected": true,
  "message": "TikTok connection verified",
  "profile": {
    "open_id": "tiktok_open_id",
    "display_name": "User Name",
    "avatar_url": "https://avatar-url.com/image.jpg"
  }
}
```

## Database Schema

The TikTok integration uses the existing `social_connections` table:

```sql
-- Example TikTok connection record
INSERT INTO social_connections (
  user_id,
  provider,
  provider_account_id,
  access_token,  -- Encrypted
  refresh_token, -- Encrypted
  expires_at,
  account_label,
  account_type,
  is_primary,
  metadata
) VALUES (
  123,
  'tiktok',
  'tiktok_open_id_12345',
  'encrypted_access_token',
  'encrypted_refresh_token',
  '2024-12-31 23:59:59+00',
  'My TikTok Account',
  'personal',
  true,
  '{
    "profile": {
      "open_id": "tiktok_open_id_12345",
      "display_name": "User Name",
      "avatar_url": "https://avatar-url.com/image.jpg",
      "follower_count": 1000,
      "bio_description": "User bio"
    }
  }'
);
```

## Security Features

### Token Encryption
- All access tokens and refresh tokens are encrypted using Fernet (AES 128)
- Encryption key is stored in environment variable `ENCRYPTION_KEY`
- Decryption only happens when tokens are needed for API calls

### Authentication
- All endpoints require valid Firebase authentication
- User authentication handled via `get_current_user` dependency
- Cross-references Firebase UID with database user records

### Error Handling
- Comprehensive error handling for OAuth flow failures
- Graceful degradation if token storage fails
- Proper HTTP status codes and error messages
- Logging for debugging and monitoring

## TikTok API Integration

### API Base URL
- Production: `https://open.tiktokapis.com`
- Version: v2

### Supported Endpoints
- **User Info**: `/v2/user/info/` - Fetch user profile data
- **Video Management**: (Future implementation)
- **Publishing**: (Future implementation)

### Required Scopes
The implementation assumes these TikTok OAuth scopes:
- `user.info.basic` - Basic user information
- `user.info.profile` - Extended profile information
- `video.list` - Access to user's videos (for future features)
- `video.upload` - Video upload capabilities (for future features)

## Integration with Frontend

### Expected Data Flow
1. Frontend initiates TikTok OAuth flow
2. TikTok redirects with authorization code
3. Frontend exchanges code for tokens
4. Frontend calls `/api/v1/auth/oauth/tiktok` with token data
5. Backend processes authentication and stores tokens
6. Frontend receives Firebase token for subsequent API calls

### Frontend Requirements
The frontend should send:
- `provider_account_id`: TikTok's `open_id` field
- `access_token`: OAuth access token
- `refresh_token`: OAuth refresh token (if available)
- `expires_in`: Token expiration in seconds
- `user_session_email`: Email from NextAuth session (for existing users)
- `email`: Email from TikTok profile (may not be available)
- `name`: Display name from TikTok profile
- `picture`: Avatar URL from TikTok profile
- `metadata`: Additional TikTok user data

## Multi-Account Support

The implementation supports multiple TikTok accounts per user:

- Each TikTok account creates a separate `social_connections` record
- `provider_account_id` uniquely identifies each TikTok account
- `is_primary` flag indicates the default account for posting
- `account_label` allows custom naming of accounts
- Users can switch between accounts in the frontend

## Error Scenarios

### Common Errors
1. **Missing Email**: Required for user authentication
2. **Missing Open ID**: TikTok's unique identifier is required
3. **Missing Access Token**: Cannot store connection without token
4. **Invalid Token**: Token encryption/decryption failures
5. **API Errors**: TikTok API rate limits or service issues

### Error Responses
```json
{
  "detail": "Email is required for TikTok authentication",
  "status_code": 400
}
```

## Testing

### Manual Testing
1. Use `/api/v1/social-connections/tiktok/test` to verify connection
2. Check token storage with `/api/v1/social-connections/connections`
3. Test profile fetching with `/api/v1/social-connections/tiktok/profile`

### Integration Testing
- Verify OAuth flow with test TikTok developer account
- Test multi-account scenarios
- Validate token refresh functionality
- Check encryption/decryption of stored tokens

## Future Enhancements

### Video Management
- Fetch user's TikTok videos
- Video analytics and insights
- Bulk video operations

### Publishing Features
- Upload videos to TikTok
- Schedule TikTok posts
- Cross-platform publishing (TikTok + other platforms)

### Analytics Integration
- TikTok Insights API integration
- Performance metrics tracking
- Audience analytics

## Dependencies

### Python Packages
- `fastapi` - Web framework
- `httpx` - HTTP client for TikTok API calls
- `cryptography` - Token encryption/decryption
- `firebase-admin` - Firebase authentication
- `supabase` - Database operations
- `pydantic` - Data validation and serialization

### Environment Variables
- `ENCRYPTION_KEY` - For token encryption
- `SUPABASE_URL` - Database connection
- `SUPABASE_SERVICE_KEY` - Database admin access
- Firebase configuration variables

## ✅ Implementation Status

**COMPLETED**: TikTok OAuth integration is fully working and tested.

### What's Working:
- ✅ **Frontend OAuth Flow**: Users can successfully connect TikTok accounts
- ✅ **Backend Token Processing**: Secure token storage with encryption  
- ✅ **User Profile Fetching**: TikTok user data retrieved and stored
- ✅ **Multi-Account Support**: Multiple TikTok accounts per user supported
- ✅ **Database Integration**: Tokens and metadata stored in social_connections table
- ✅ **Error Handling**: Comprehensive error handling and validation
- ✅ **Security**: All tokens encrypted using Fernet (AES 128)

### Frontend Integration Points:
- **OAuth Route**: `/api/tiktok-connect` - handles TikTok OAuth flow
- **UI Component**: `ConnectedAccounts.tsx` - displays TikTok connections  
- **Utilities**: `tiktok.ts` - TikTok-specific helper functions
- **Store Integration**: Platform requirements and connection management

### Backend Integration Points:
- **OAuth Endpoint**: `POST /api/v1/auth/oauth/tiktok` - processes OAuth tokens
- **Profile Endpoints**: Get/store TikTok profile data with caching
- **Testing Endpoints**: Verify TikTok API connectivity
- **Database**: Uses existing `social_connections` table schema

## Deployment Notes

✅ **ALREADY DEPLOYED**: The following production requirements are met:

1. ✅ TikTok OAuth application configured with correct redirect URIs
2. ✅ Environment variables properly set (TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET)
3. ✅ CORS configured for frontend-backend communication
4. ✅ Error handling and logging implemented
5. ✅ Integration tested and confirmed working

---

This implementation provides a complete, secure, and scalable TikTok OAuth integration that follows the established patterns used by other social media providers in the application.
