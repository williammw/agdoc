# Database Schema Documentation

## 📊 Overview

The Multivio backend uses **Supabase PostgreSQL** as the primary database with **Row Level Security (RLS)** policies. The schema is designed for multi-tenant social media management with JSONB flexibility and efficient indexing.

### Database Architecture

```
PostgreSQL (Supabase)
├── Row Level Security (RLS)
├── JSONB for flexible metadata
├── UUID primary keys
├── Automatic timestamps
├── Foreign key constraints
└── Performance indexes
```

### Connection Details
- **Host**: Supabase managed PostgreSQL
- **Version**: PostgreSQL 15+
- **Extensions**: uuid-ossp, pgcrypto
- **Connection**: Connection pooling enabled

---

## 👥 Users Table

Primary user accounts and authentication data.

```sql
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  firebase_uid VARCHAR(255) NOT NULL UNIQUE,
  email VARCHAR(255) NOT NULL UNIQUE,
  username VARCHAR(100) UNIQUE,
  full_name VARCHAR(255),
  display_name VARCHAR(100),
  work_description VARCHAR(255),
  bio TEXT,
  avatar_url TEXT,
  email_verified BOOLEAN DEFAULT false,
  auth_provider VARCHAR(50) DEFAULT 'email',
  is_active BOOLEAN DEFAULT true,
  is_verified BOOLEAN DEFAULT false,
  stripe_customer_id VARCHAR(255),
  subscription_status VARCHAR(50) DEFAULT 'free',
  subscription_id VARCHAR(255),
  plan_name VARCHAR(50) DEFAULT 'free',
  subscription_end_date TIMESTAMPTZ,
  email_verification_token VARCHAR(255),
  email_verification_expires_at TIMESTAMPTZ,
  email_verification_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE UNIQUE INDEX idx_users_firebase_uid ON users(firebase_uid);
CREATE UNIQUE INDEX idx_users_email ON users(email);
CREATE UNIQUE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_subscription_status ON users(subscription_status);
CREATE INDEX idx_users_created_at ON users(created_at);

-- Updated at trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `id` | SERIAL | Primary key, auto-increment |
| `firebase_uid` | VARCHAR(255) | Firebase user ID, unique |
| `email` | VARCHAR(255) | User email, unique |
| `username` | VARCHAR(100) | Optional username, unique |
| `full_name` | VARCHAR(255) | Full display name |
| `display_name` | VARCHAR(100) | Preferred short name |
| `work_description` | VARCHAR(255) | Professional description |
| `bio` | TEXT | User biography |
| `avatar_url` | TEXT | Profile picture URL |
| `email_verified` | BOOLEAN | Email verification status |
| `auth_provider` | VARCHAR(50) | Authentication method |
| `stripe_customer_id` | VARCHAR(255) | Stripe customer ID |
| `subscription_status` | VARCHAR(50) | Current subscription status |
| `subscription_end_date` | TIMESTAMPTZ | Subscription expiration |
| `created_at` | TIMESTAMPTZ | Account creation timestamp |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |

---

## 🔗 Social Connections Table

OAuth tokens and social media account connections with multi-account support.

```sql
CREATE TABLE social_connections (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider VARCHAR(50) NOT NULL,
  provider_account_id VARCHAR(255) NOT NULL,
  access_token TEXT NOT NULL, -- Encrypted
  refresh_token TEXT, -- Encrypted
  expires_at TIMESTAMPTZ,
  account_label VARCHAR(255), -- User-friendly name
  account_type VARCHAR(50) DEFAULT 'personal', -- personal, business, page
  is_primary BOOLEAN DEFAULT false, -- Only one per provider/user
  metadata JSONB DEFAULT '{}', -- Platform-specific data
  -- OAuth 1.0a fields for Twitter media uploads
  oauth1_access_token TEXT, -- Encrypted OAuth 1.0a token
  oauth1_access_token_secret TEXT, -- Encrypted OAuth 1.0a secret
  oauth1_user_id VARCHAR(255), -- OAuth 1.0a user ID
  oauth1_screen_name VARCHAR(255), -- OAuth 1.0a screen name
  oauth1_created_at TIMESTAMPTZ, -- OAuth 1.0a token creation
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, provider, provider_account_id)
);

-- Indexes
CREATE INDEX idx_social_connections_user_id ON social_connections(user_id);
CREATE INDEX idx_social_connections_provider ON social_connections(provider);
CREATE INDEX idx_social_connections_provider_account_id ON social_connections(provider_account_id);
CREATE INDEX idx_social_connections_account_type ON social_connections(account_type);
CREATE INDEX idx_social_connections_is_primary ON social_connections(is_primary);
CREATE INDEX idx_social_connections_expires_at ON social_connections(expires_at);
CREATE INDEX idx_social_connections_metadata ON social_connections USING gin(metadata);

-- Updated at trigger
CREATE TRIGGER update_social_connections_updated_at
    BEFORE UPDATE ON social_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key, auto-generated |
| `user_id` | INTEGER | Foreign key to users table |
| `provider` | VARCHAR(50) | Platform name (twitter, facebook, etc.) |
| `provider_account_id` | VARCHAR(255) | Platform-specific account ID |
| `access_token` | TEXT | Encrypted OAuth 2.0 access token |
| `refresh_token` | TEXT | Encrypted OAuth 2.0 refresh token |
| `expires_at` | TIMESTAMPTZ | Token expiration timestamp |
| `account_label` | VARCHAR(255) | User-friendly account name |
| `account_type` | VARCHAR(50) | Account type classification |
| `is_primary` | BOOLEAN | Primary account flag per provider |
| `metadata` | JSONB | Platform-specific configuration data |
| `oauth1_*` | TEXT/TIMESTAMPTZ | Twitter OAuth 1.0a credentials |
| `created_at` | TIMESTAMPTZ | Connection creation timestamp |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |

### Metadata Structure Examples

**Facebook Page:**
```json
{
  "page_id": "123456789",
  "page_name": "My Business Page",
  "page_category": "Business",
  "permissions": ["pages_manage_posts", "pages_read_engagement"],
  "instagram_business_account": {
    "id": "987654321",
    "username": "mybusiness"
  }
}
```

**Twitter Account:**
```json
{
  "screen_name": "username",
  "followers_count": 1234,
  "friends_count": 567,
  "verified": false,
  "profile_image_url": "https://...",
  "oauth1_capable": true
}
```

---

## 📝 Posts Table

Unified content storage for all social media posts.

```sql
CREATE TABLE posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL, -- Post title/name
  content_mode VARCHAR(50) DEFAULT 'universal', -- universal or specific
  universal_content TEXT, -- Content for universal mode
  universal_metadata JSONB DEFAULT '{}', -- Universal content metadata
  platform_content JSONB DEFAULT '{}', -- Platform-specific content
  platforms JSONB DEFAULT '[]', -- Selected platforms for publishing
  media_files JSONB DEFAULT '[]', -- Attached media files
  schedule_date TIMESTAMPTZ, -- Future publishing date
  status VARCHAR(50) DEFAULT 'draft', -- draft, published, scheduled, failed
  publish_job_id VARCHAR(255), -- Background job tracking
  published_at TIMESTAMPTZ, -- Actual publishing timestamp
  publish_results JSONB DEFAULT '{}', -- Publishing status per platform
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_posts_user_id ON posts(user_id);
CREATE INDEX idx_posts_status ON posts(status);
CREATE INDEX idx_posts_content_mode ON posts(content_mode);
CREATE INDEX idx_posts_schedule_date ON posts(schedule_date);
CREATE INDEX idx_posts_created_at ON posts(created_at);
CREATE INDEX idx_posts_platforms ON posts USING gin(platforms);
CREATE INDEX idx_posts_platform_content ON posts USING gin(platform_content);

-- Updated at trigger
CREATE TRIGGER update_posts_updated_at
    BEFORE UPDATE ON posts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key, auto-generated |
| `user_id` | INTEGER | Foreign key to users table |
| `name` | VARCHAR(255) | Post title or name |
| `content_mode` | VARCHAR(50) | Content mode (universal/specific) |
| `universal_content` | TEXT | Content for universal publishing |
| `universal_metadata` | JSONB | Universal content metadata |
| `platform_content` | JSONB | Platform-specific content variants |
| `platforms` | JSONB | Array of target platforms |
| `media_files` | JSONB | Array of attached media files |
| `schedule_date` | TIMESTAMPTZ | Scheduled publishing date |
| `status` | VARCHAR(50) | Post status |
| `publish_results` | JSONB | Publishing results per platform |
| `created_at` | TIMESTAMPTZ | Post creation timestamp |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |

### Content Structure Examples

**Universal Content:**
```json
{
  "content": "Check out our new product launch! #innovation",
  "hashtags": ["innovation", "productlaunch"],
  "mentions": [],
  "links": ["https://example.com/product"]
}
```

**Platform-Specific Content:**
```json
{
  "twitter": {
    "content": "🚀 New product launch! Check it out #innovation",
    "hashtags": ["innovation", "tech"],
    "max_length": 280
  },
  "linkedin": {
    "content": "Excited to announce our latest product launch. This innovation represents months of hard work from our amazing team.",
    "hashtags": ["innovation", "business", "productlaunch"],
    "visibility": "PUBLIC"
  }
}
```

### Media Files Structure

```json
[
  {
    "file_id": "uuid",
    "filename": "product-image.jpg",
    "file_type": "image/jpeg",
    "file_size": 2048000,
    "cdn_url": "https://cdn.multivio.com/uploads/uuid.jpg",
    "thumbnail_url": "https://cdn.multivio.com/thumbnails/uuid.jpg",
    "platform_compatibility": ["twitter", "facebook", "instagram"],
    "alt_text": "Product launch image",
    "upload_date": "2024-12-22T10:30:00Z"
  }
]
```

---

## 💳 Subscription Management Tables

Tables for managing Stripe subscriptions and billing.

```sql
CREATE TABLE subscription_history (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_email VARCHAR(255) NOT NULL,
  stripe_subscription_id VARCHAR(255),
  plan_name VARCHAR(50),
  status VARCHAR(50),
  amount_paid INTEGER, -- Amount in cents
  currency VARCHAR(3) DEFAULT 'usd',
  period_start TIMESTAMPTZ,
  period_end TIMESTAMPTZ,
  stripe_customer_id VARCHAR(255),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_info (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
  plan_type VARCHAR(50) DEFAULT 'free',
  monthly_post_quota INTEGER DEFAULT 10,
  remaining_posts INTEGER DEFAULT 10,
  subscription_id VARCHAR(255),
  subscription_status VARCHAR(50),
  subscription_end_date TIMESTAMPTZ,
  last_quota_reset TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  preferences JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_subscription_history_user_email ON subscription_history(user_email);
CREATE INDEX idx_subscription_history_stripe_subscription_id ON subscription_history(stripe_subscription_id);
CREATE INDEX idx_subscription_history_status ON subscription_history(status);
CREATE INDEX idx_user_info_user_id ON user_info(user_id);
CREATE INDEX idx_user_info_plan_type ON user_info(plan_type);
```

---

## 🎨 Media Files Table

Metadata for uploaded media files.

```sql
CREATE TABLE media_files (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename VARCHAR(255) NOT NULL,
  original_filename VARCHAR(255),
  file_type VARCHAR(100), -- MIME type
  file_size INTEGER, -- Size in bytes
  cdn_url TEXT, -- Cloudflare R2 public URL
  thumbnail_url TEXT, -- Thumbnail URL
  platform_compatibility JSONB DEFAULT '[]', -- Compatible platforms
  alt_text TEXT, -- Alternative text for accessibility
  upload_date TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_media_files_user_id ON media_files(user_id);
CREATE INDEX idx_media_files_file_type ON media_files(file_type);
CREATE INDEX idx_media_files_upload_date ON media_files(upload_date);
CREATE INDEX idx_media_files_platform_compatibility ON media_files USING gin(platform_compatibility);
```

---

## 🔐 Row Level Security (RLS) Policies

Supabase RLS policies ensure users can only access their own data.

### Users Table Policies
```sql
-- Users can only see their own profile
CREATE POLICY "Users can view own profile" ON users
  FOR SELECT USING (auth.uid()::text = firebase_uid);

-- Users can update their own profile
CREATE POLICY "Users can update own profile" ON users
  FOR UPDATE USING (auth.uid()::text = firebase_uid);

-- Allow inserts for new user registration
CREATE POLICY "Allow user registration" ON users
  FOR INSERT WITH CHECK (true);
```

### Social Connections Policies
```sql
-- Users can only see their own connections
CREATE POLICY "Users can view own connections" ON social_connections
  FOR SELECT USING (user_id IN (
    SELECT id FROM users WHERE firebase_uid = auth.uid()::text
  ));

-- Users can manage their own connections
CREATE POLICY "Users can manage own connections" ON social_connections
  FOR ALL USING (user_id IN (
    SELECT id FROM users WHERE firebase_uid = auth.uid()::text
  ));
```

### Posts Policies
```sql
-- Users can only see their own posts
CREATE POLICY "Users can view own posts" ON posts
  FOR SELECT USING (user_id IN (
    SELECT id FROM users WHERE firebase_uid = auth.uid()::text
  ));

-- Users can manage their own posts
CREATE POLICY "Users can manage own posts" ON posts
  FOR ALL USING (user_id IN (
    SELECT id FROM users WHERE firebase_uid = auth.uid()::text
  ));
```

---

## 🏗️ Database Migrations

Migration files are stored in `app/db/migrations/` and applied in order.

### Migration File Structure
```
001_initial_schema.sql      # Initial tables
002_subscription_schema.sql # Subscription management
003_content_management.sql  # Posts and media tables
004_unified_posts.sql       # Unified content system
005_oauth1_columns.sql      # Twitter OAuth 1.0a support
```

### Migration Process
```bash
# Apply migrations via Supabase SQL editor or
# Run through application initialization
python app/db/init_db.py
```

---

## 📊 Database Performance

### Indexing Strategy
- **Primary Keys**: UUID and SERIAL for uniqueness
- **Foreign Keys**: Indexed for JOIN performance
- **JSONB Columns**: GIN indexes for metadata queries
- **Common Filters**: Status, dates, user_id indexed
- **Composite Indexes**: Multi-column indexes where needed

### Query Optimization
- **Connection Pooling**: Supabase handles connection limits
- **Query Planning**: EXPLAIN ANALYZE for complex queries
- **Batch Operations**: Bulk inserts/updates where possible
- **Pagination**: LIMIT/OFFSET for large result sets

### Monitoring
- **Query Performance**: Slow query logging
- **Connection Usage**: Monitor connection pool
- **Storage Growth**: Table size and index monitoring
- **RLS Performance**: Policy evaluation overhead

---

## 🔧 Database Maintenance

### Regular Tasks
```sql
-- Analyze tables for query planning
ANALYZE users, social_connections, posts;

-- Vacuum for space reclamation
VACUUM (ANALYZE) users, social_connections, posts;

-- Reindex if needed
REINDEX TABLE CONCURRENTLY users;
```

### Backup Strategy
- **Supabase Managed**: Automatic daily backups
- **Point-in-Time Recovery**: 7-day retention
- **Export Capabilities**: SQL and CSV exports

### Schema Evolution
- **Backward Compatibility**: New columns with defaults
- **Migration Scripts**: Versioned migration files
- **Rollback Plans**: Reversible migrations
- **Testing**: Migration testing in staging

---

**Version**: 3.0.1
**Last Updated**: September 2025
**Database**: Supabase PostgreSQL 15+
