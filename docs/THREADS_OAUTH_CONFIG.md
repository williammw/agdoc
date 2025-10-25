# Threads OAuth Backend Configuration

This document provides instructions for setting up Threads OAuth integration in the backend FastAPI application.

## Environment Variables

Add the following environment variables to your backend `.env` file:

```
# Threads OAuth Configuration
THREADS_APP_ID=2031580547318596
THREADS_APP_SECRET=5ef90404af570b15c5e73c7ac85bff18
THREADS_API_VERSION=v22.0
```

> **Note**: Threads uses Meta's OAuth infrastructure, so you can also reuse your Facebook or Instagram App credentials if needed.

## API Endpoints

The following endpoints have been implemented to support Threads integration:

1. **OAuth Handler**: `/api/v1/auth/oauth/threads`
   - Processes the OAuth callback data from the frontend
   - Creates/updates user accounts and stores tokens

2. **Profile Endpoint**: `/api/v1/social-connections/threads/profile`
   - Gets the Threads profile data for the authenticated user
   - Supports force-refresh with `?force=true` query parameter

3. **Store Profile Endpoint**: `/api/v1/social-connections/store-threads-profile`
   - Stores or updates Threads profile data in the database

4. **Disconnect Endpoint**: `/api/v1/social-connections/threads`
   - Deletes the Threads connection when the user disconnects

## Database Schema

Threads connection data is stored in the `social_connections` table with:
- `provider` set to "threads"
- `provider_account_id` containing the Threads user ID
- `access_token` containing the encrypted OAuth token
- `metadata` containing additional profile data (username, bio, followers, etc.)

## Token Handling

All tokens are encrypted before storage using the `encrypt_token` utility:

```python
from app.utils.encryption import encrypt_token, decrypt_token

# Encrypt before storage
encrypted_token = encrypt_token(access_token)

# Decrypt when needed
decrypted_token = decrypt_token(encrypted_token)
```

## API Integration

The backend uses Instagram's Graph API endpoints for Threads interactions:

```
https://graph.instagram.com/v18.0/me?fields=id,username,name,biography,profile_picture_url,followers_count,follows_count
```

## Security Considerations

1. Tokens are always encrypted in the database
2. API requests require valid Firebase authentication
3. Direct token access is limited to authenticated endpoints
4. Refresh mechanisms exist for expired tokens

## Testing

To test the Threads integration:

1. Connect a Threads account through the frontend
2. Verify the connection in the database
3. Test the profile endpoint to ensure data retrieval
4. Test disconnection to verify proper cleanup

## Troubleshooting

If you encounter issues with the Threads integration:

1. Check backend logs for API errors
2. Verify token encryption/decryption is working properly
3. Ensure the database contains the expected connection data
4. Verify Meta app configurations match the environment variables 