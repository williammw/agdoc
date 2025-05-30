# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **FastAPI backend** for the Multivio social media management platform. It handles authentication, social media connections, subscription management, and API integrations.

## Development Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run with specific environment
export ENCRYPTION_KEY="your-encryption-key"
uvicorn app.main:app --reload

# Run tests
pytest

# Generate encryption key
python -c "import secrets; import base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

## Architecture Overview

This FastAPI backend serves as the API layer between the Next.js frontend and various services:
- **Supabase**: Database and authentication
- **Firebase Admin SDK**: User authentication and token generation
- **Social Media APIs**: OAuth and posting capabilities
- **Stripe**: Subscription management

### Project Structure

```
app/
├── main.py                 # FastAPI application entry point
├── routers/               # API route handlers
│   ├── auth.py           # Authentication & OAuth endpoints
│   ├── social_connections.py  # Social media connection management
│   └── subscriptions.py   # Stripe subscription handling
├── models/                # Pydantic models & SQLAlchemy schemas
│   ├── users.py          # User models
│   └── social_connections.py  # Social connection models
├── dependencies/          # FastAPI dependencies
│   └── auth.py           # Authentication guards
├── utils/                 # Utility functions
│   ├── database.py       # Database connections
│   ├── encryption.py     # Token encryption/decryption
│   └── firebase.py       # Firebase Admin SDK
└── config/               # Configuration files
    └── serviceAccountKey.json  # Firebase service account
```

## Key Features

### 1. Multi-Account Social Media Support
- **Multiple accounts per platform**: Users can connect multiple Facebook, Twitter, etc. accounts
- **Primary account designation**: First account is auto-primary, changeable
- **Account management**: Individual account removal, labeling, and settings
- **Metadata storage**: Platform-specific data stored in JSONB column
- **Facebook Pages Sync**: Converts Facebook pages stored in metadata to separate connection entries for multi-account support

### 2. Authentication Flow
- **Firebase Authentication**: Primary authentication method
- **OAuth Integration**: Social platform OAuth for account connections
- **Token Management**: Encrypted storage of access/refresh tokens
- **Custom Firebase Tokens**: Generated for frontend authentication

### 3. User Profile Management
- **Extended profile fields**: display_name, work_description, bio
- **Profile update endpoint**: PUT /api/v1/auth/profile
- **Frontend integration**: General settings tab with form validation
- **Character limits**: display_name (100), work_description (255), bio (unlimited)
- **Real-time updates**: Changes immediately reflected in UI

### 4. Database Schema

**users table**:
```sql
- id: INTEGER primary key
- firebase_uid: VARCHAR(255) unique
- email: VARCHAR(255) unique
- username: VARCHAR(100) unique
- full_name: VARCHAR(255)
- avatar_url: TEXT
- email_verified: BOOLEAN
- auth_provider: VARCHAR(50)
- is_active: BOOLEAN default true
- display_name: VARCHAR(100) - How users prefer to be called
- work_description: VARCHAR(255) - What best describes their work
- bio: TEXT - User biography
- created_at: TIMESTAMP
- updated_at: TIMESTAMP
```

**social_connections table**:
```sql
- id: UUID primary key
- user_id: INTEGER (references users.id)
- provider: VARCHAR(50) - facebook, twitter, linkedin, etc.
- provider_account_id: VARCHAR(255) - Platform-specific account ID
- access_token: TEXT (encrypted)
- refresh_token: TEXT (encrypted)
- expires_at: TIMESTAMP
- metadata: JSONB - Platform-specific data
- account_label: VARCHAR(255) - User-friendly name
- is_primary: BOOLEAN - Primary account flag
- account_type: VARCHAR(50) - personal, business, etc.
```

## Environment Configuration

Required environment variables:
```env
# Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key

# Encryption (REQUIRED - Generate secure key for production)
ENCRYPTION_KEY=base64-encoded-32-byte-key

# Firebase
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_CLIENT_EMAIL=service-account-email
FIREBASE_PRIVATE_KEY=service-account-private-key
```

## API Endpoints

### Authentication (`/api/v1/auth`)
- `GET /me` - Get current user profile with user info
- `PUT /profile` - Update user profile (display_name, work_description, bio)
- `POST /oauth/google` - Google OAuth handler
- `POST /oauth/facebook` - Facebook OAuth handler
- `POST /oauth/twitter` - Twitter OAuth handler
- `POST /oauth/linkedin` - LinkedIn OAuth handler
- `POST /oauth/threads` - Threads OAuth handler
- `POST /oauth/youtube` - YouTube OAuth handler

### Social Connections (`/api/v1/social-connections`)
- `GET /connections` - Get all user connections
- `POST /store-token` - Store OAuth tokens
- `GET /token/{provider}` - Get decrypted tokens
- `DELETE /{provider}` - Remove all provider connections
- `DELETE /account/{connection_id}` - Remove specific account
- `PUT /account/{connection_id}/primary` - Set primary account
- `PUT /account/{connection_id}/label` - Update account label
- `POST /sync-facebook-pages` - Sync Facebook pages as separate connections
- `GET /sync-status/{provider}` - Check if pages need syncing

### Subscriptions (`/api/v1/subscriptions`)
- `POST /activate` - Activate subscription
- `GET /status` - Get subscription status
- `POST /cancel` - Cancel subscription

## Common Development Tasks

### User Profile Updates

To handle user profile updates in the backend:

1. **Pydantic Models** (in `app/models/users.py`):
```python
class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    display_name: Optional[str] = None
    work_description: Optional[str] = None
    bio: Optional[str] = None
```

2. **Profile Update Endpoint** (in `app/routers/auth.py`):
```python
@router.put("/profile", response_model=UserResponse)
async def update_profile(
    profile_data: dict = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    # Validates and updates only allowed fields
    allowed_fields = {'full_name', 'display_name', 'work_description', 'bio'}
```

3. **Frontend Request Example**:
```javascript
await fetch('/api/v1/auth/profile', {
    method: 'PUT',
    headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        full_name: "John Doe",
        display_name: "John",
        work_description: "Software Developer",
        bio: "Passionate about building great products"
    })
});
```

### Adding a New OAuth Provider

1. **Add OAuth handler in `auth.py`**:
```python
@router.post("/oauth/newplatform")
async def newplatform_oauth(
    data: Dict[str, Any] = Body(...),
    supabase = Depends(db_admin)
):
    # Extract OAuth data
    # Process authentication
    # Store connection with multi-account support
```

2. **Update frontend callback handling**
3. **Add provider-specific utilities if needed**

### Handling Metadata

**Important**: SQLAlchemy reserves `metadata` as an attribute name. In models:
```python
# Use metadata_json as attribute, map to metadata column
metadata_json = Column("metadata", JSONB, nullable=True)
```

### Token Encryption

All OAuth tokens are encrypted before storage:
```python
from app.utils.encryption import encrypt_token, decrypt_token

# Encrypt before storing
encrypted_token = encrypt_token(access_token)

# Decrypt when retrieving
decrypted_token = decrypt_token(encrypted_token)
```

## Testing

### Manual API Testing
```bash
# Get connections
curl -X GET "http://localhost:8000/api/v1/social-connections/connections" \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN"

# Remove specific account
curl -X DELETE "http://localhost:8000/api/v1/social-connections/account/{connection_id}" \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN"
```

### Common Test Scenarios
1. Connect first account (should be primary)
2. Connect second account (should not be primary)
3. Remove primary account (should promote another)
4. Update account labels
5. Test token refresh flows
6. Connect Facebook account with pages and sync them
7. Verify Facebook pages appear as separate connections

## Database Migrations

### Adding New User Profile Fields

When adding new fields to the users table:

1. **Create SQL migration file** (e.g., `003_user_profile_fields.sql`):
```sql
-- Add user profile fields
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS display_name VARCHAR(100),
ADD COLUMN IF NOT EXISTS work_description VARCHAR(255),
ADD COLUMN IF NOT EXISTS bio TEXT;
```

2. **Update Pydantic models** in `app/models/users.py`
3. **Update API endpoints** to handle new fields
4. **Run migration** via Supabase SQL editor

## Deployment

### Production Deployment
1. Set all environment variables
2. Use production Firebase service account
3. Enable HTTPS only
4. Set proper CORS origins
5. Use strong ENCRYPTION_KEY

### DigitalOcean App Platform
- **Production URL**: https://jellyfish-app-ds6sv.ondigitalocean.app/
- **Development URL**: https://dev.ohmeowkase.com/
- **Environment**: Set via App Platform dashboard

## Troubleshooting

### Common Issues

1. **"metadata is reserved" error**
   - Ensure models use `metadata_json` attribute
   - Check Column mapping to database

2. **Encryption key errors**
   - Set ENCRYPTION_KEY environment variable
   - Use base64-encoded 32-byte key

3. **Firebase token errors**
   - Verify service account credentials
   - Check Firebase project ID matches

4. **CORS errors**
   - Add frontend URL to allowed origins
   - Check request includes credentials

5. **Profile update 403 errors**
   - Ensure RLS policies allow updates for authenticated users
   - Check Firebase token is valid and included in request
   - Verify user has permission to update their own profile

6. **Missing profile fields in API response**
   - Update all Pydantic models (UserBase, UserResponse) to include new fields
   - Ensure database query selects all columns
   - Check that GET /me endpoint fetches fresh user data

### Debug Mode
```python
# Enable detailed logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Security Considerations

1. **Token Storage**: All OAuth tokens encrypted at rest
2. **Authentication**: Firebase tokens required for all endpoints
3. **Database Access**: Row-level security via Supabase
4. **CORS**: Strict origin checking
5. **Environment**: Never commit secrets, use .env files

## Recent Updates
π
### User Profile Management (January 2025)
- Added extended user profile fields (display_name, work_description, bio)
- New `PUT /api/v1/auth/profile` endpoint for profile updates
- Updated Pydantic models to include profile fields in API responses
- Frontend General settings tab with profile form and validation

### Multi-Account Support (December 2024)
- Added support for multiple accounts per platform
- New endpoints for account-specific operations
- Primary account designation
- Account labeling and type classification
- Migration script for existing data

### Facebook Pages Sync (December 2024)
- New `/sync-facebook-pages` endpoint converts pages to separate connections
- Pages stored as individual connections with `account_type: 'page'`
- Each page can have its own access token and metadata
- Frontend "Sync Pages" button for easy conversion
- `/sync-status/facebook` endpoint to check if pages need syncing

### Metadata Handling Fix
- Renamed model attribute to avoid SQLAlchemy conflict
- Maintained API compatibility with `metadata` field
- Custom ORM conversion for proper mapping

---

**Version**: 2.2.0  
**Last Updated**: January 2025  
**Key Changes**: User profile management, multi-account support, Facebook pages sync, metadata handling fixes