-- Social Media Connections Table with Multi-Account Support
CREATE TABLE IF NOT EXISTS social_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    provider_account_id VARCHAR(255) NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMPTZ,
    metadata JSONB,
    account_label VARCHAR(255),
    is_primary BOOLEAN NOT NULL DEFAULT false,
    account_type VARCHAR(50) NOT NULL DEFAULT 'personal',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Ensure unique combination of user, provider, and specific account
    UNIQUE(user_id, provider, provider_account_id),
    -- Ensure only one primary account per provider per user
    UNIQUE(user_id, provider, is_primary) DEFERRABLE INITIALLY DEFERRED
);

-- Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS social_connections_user_id_idx ON social_connections(user_id);
CREATE INDEX IF NOT EXISTS social_connections_provider_idx ON social_connections(provider);
CREATE INDEX IF NOT EXISTS social_connections_user_provider_idx ON social_connections(user_id, provider);
CREATE INDEX IF NOT EXISTS social_connections_primary_idx ON social_connections(user_id, provider, is_primary) WHERE is_primary = true;

-- Add constraint to ensure valid account types
ALTER TABLE social_connections ADD CONSTRAINT social_connections_account_type_check 
    CHECK (account_type IN ('personal', 'business', 'brand', 'organization'));

-- Create partial unique index to enforce only one primary account per provider per user
-- This replaces the UNIQUE constraint above which doesn't work well with boolean columns
DROP INDEX IF EXISTS social_connections_primary_unique_idx;
CREATE UNIQUE INDEX social_connections_primary_unique_idx 
    ON social_connections(user_id, provider) 
    WHERE is_primary = true; 