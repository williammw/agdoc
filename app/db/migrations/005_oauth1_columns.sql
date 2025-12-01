-- 005_oauth1_columns.sql
-- Add OAuth 1.0a columns to social_connections table for Twitter media upload support
-- Version: 1.5.0
-- Date: 2024-12-22

-- Start transaction
BEGIN;

-- Add version tracking
INSERT INTO migration_history (version, description)
VALUES ('1.5.0', 'Add OAuth 1.0a columns to social_connections table');

-- Add OAuth 1.0a columns to social_connections table
ALTER TABLE social_connections 
ADD COLUMN IF NOT EXISTS oauth1_access_token TEXT,
ADD COLUMN IF NOT EXISTS oauth1_access_token_secret TEXT,
ADD COLUMN IF NOT EXISTS oauth1_user_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS oauth1_screen_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS oauth1_created_at TIMESTAMPTZ;

-- Add comments to explain the new columns
COMMENT ON COLUMN social_connections.oauth1_access_token IS 'Encrypted OAuth 1.0a access token for platforms requiring dual authentication (e.g., Twitter media upload)';
COMMENT ON COLUMN social_connections.oauth1_access_token_secret IS 'Encrypted OAuth 1.0a access token secret for platforms requiring dual authentication';
COMMENT ON COLUMN social_connections.oauth1_user_id IS 'OAuth 1.0a user ID from the platform';
COMMENT ON COLUMN social_connections.oauth1_screen_name IS 'OAuth 1.0a screen name/username from the platform';
COMMENT ON COLUMN social_connections.oauth1_created_at IS 'Timestamp when OAuth 1.0a tokens were obtained';

-- Add indexes for OAuth 1.0a lookups
CREATE INDEX IF NOT EXISTS social_connections_oauth1_user_id_idx ON social_connections(oauth1_user_id) WHERE oauth1_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS social_connections_oauth1_screen_name_idx ON social_connections(oauth1_screen_name) WHERE oauth1_screen_name IS NOT NULL;

-- Commit transaction
COMMIT;