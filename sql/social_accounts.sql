-- social_accounts.sql
-- Tables for managing social media accounts

-- Social accounts table - stores connected accounts
CREATE TABLE mo_social_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    platform mo_social_platform NOT NULL,
    platform_account_id VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    profile_picture_url TEXT,
    display_name VARCHAR(255),
    account_type VARCHAR(50),
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    oauth1_token TEXT,
    oauth1_token_secret TEXT,
    expires_at TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    media_type VARCHAR(20),
    media_count INTEGER DEFAULT 0,
    followers_count INTEGER,
    following_count INTEGER,
    post_count INTEGER,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Business/page accounts might be linked to a parent account
    parent_account_id UUID REFERENCES mo_social_accounts(id) ON DELETE SET NULL,
    
    -- Ensure unique user-platform-account combinations
    CONSTRAINT mo_social_accounts_user_id_platform_platform_account_id_key
    UNIQUE (user_id, platform, platform_account_id)
);

-- Indexes for social accounts
CREATE INDEX idx_social_accounts_user_id ON mo_social_accounts(user_id);
CREATE INDEX idx_social_accounts_platform ON mo_social_accounts(platform);
CREATE INDEX idx_social_accounts_oauth1 ON mo_social_accounts(oauth1_token) WHERE oauth1_token IS NOT NULL;

-- Foreign key to user table
ALTER TABLE mo_social_accounts 
ADD CONSTRAINT mo_social_accounts_user_id_fkey
FOREIGN KEY (user_id) REFERENCES mo_user_info(id) ON DELETE CASCADE;

-- Trigger for updated_at
CREATE TRIGGER update_social_accounts_updated_at
BEFORE UPDATE ON mo_social_accounts
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Account tokens history (for auditing/troubleshooting)
CREATE TABLE mo_social_account_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES mo_social_accounts(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    issued_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    is_valid BOOLEAN DEFAULT TRUE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    revocation_reason TEXT
);

-- Account status history
CREATE TABLE mo_social_account_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES mo_social_accounts(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    details TEXT,
    error_message TEXT,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- Account settings for platform-specific preferences
CREATE TABLE mo_social_account_settings (
    account_id UUID PRIMARY KEY REFERENCES mo_social_accounts(id) ON DELETE CASCADE,
    auto_refresh_tokens BOOLEAN DEFAULT TRUE,
    default_post_privacy VARCHAR(20) DEFAULT 'public',
    crosspost_enabled BOOLEAN DEFAULT FALSE,
    notification_preferences JSONB,
    custom_settings JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Trigger for account_settings updated_at
CREATE TRIGGER update_social_account_settings_updated_at
BEFORE UPDATE ON mo_social_account_settings
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();