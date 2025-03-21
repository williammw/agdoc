-- oauth_tables.sql
-- Core OAuth tables for multi-platform social media integration

-- Enum for social platforms
CREATE TYPE mo_social_platform AS ENUM (
    'facebook',
    'instagram',
    'twitter',
    'x',
    'linkedin',
    'youtube',
    'threads',
    'tiktok',
    'patreon',
    'pinterest'
);

-- Enum for OAuth versions
CREATE TYPE mo_oauth_version AS ENUM (
    'oauth1',
    'oauth2'
);

-- Enum for processing status
CREATE TYPE mo_processing_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed'
);

-- Platform configuration table
CREATE TABLE mo_social_platforms (
    platform mo_social_platform PRIMARY KEY,
    display_name VARCHAR(50) NOT NULL,
    oauth_version mo_oauth_version NOT NULL DEFAULT 'oauth2',
    client_id TEXT,
    client_secret TEXT,
    auth_url TEXT,
    token_url TEXT,
    scope TEXT,
    default_redirect_template TEXT,
    logo_url TEXT,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

-- OAuth state table - for tracking OAuth flows
CREATE TABLE mo_oauth_states (
    state VARCHAR(128) PRIMARY KEY,
    platform mo_social_platform NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    code_verifier TEXT DEFAULT '',
    redirect_uri TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used BOOLEAN DEFAULT FALSE
);

-- Add indexes on OAuth states table
CREATE INDEX idx_mo_oauth_states_user_platform ON mo_oauth_states(user_id, platform);
CREATE INDEX idx_mo_oauth_states_used ON mo_oauth_states(used);

-- Updated trigger function for timestamp updates
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Insert initial platform data
INSERT INTO mo_social_platforms 
(platform, display_name, oauth_version, auth_url, token_url, scope, default_redirect_template, logo_url) 
VALUES
('facebook', 'Facebook', 'oauth2', 
 'https://www.facebook.com/v21.0/dialog/oauth', 
 'https://graph.facebook.com/v21.0/oauth/access_token',
 'pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_metadata,business_management',
 '{frontend_url}/facebook/callback',
 '/images/platforms/facebook.svg'),

('instagram', 'Instagram', 'oauth2', 
 'https://www.facebook.com/v21.0/dialog/oauth', 
 'https://graph.facebook.com/v21.0/oauth/access_token',
 'instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement,instagram_manage_insights',
 '{frontend_url}/instagram/callback',
 '/images/platforms/instagram.svg'),

('twitter', 'Twitter', 'oauth2', 
 'https://twitter.com/i/oauth2/authorize', 
 'https://api.twitter.com/2/oauth2/token',
 'tweet.read tweet.write users.read offline.access',
 '{frontend_url}/twitter/callback',
 '/images/platforms/twitter.svg'),

('x', 'X', 'oauth2', 
 'https://twitter.com/i/oauth2/authorize', 
 'https://api.twitter.com/2/oauth2/token',
 'tweet.read tweet.write users.read offline.access',
 '{frontend_url}/twitter/callback',
 '/images/platforms/x.svg'),

('linkedin', 'LinkedIn', 'oauth2', 
 'https://www.linkedin.com/oauth/v2/authorization', 
 'https://www.linkedin.com/oauth/v2/accessToken',
 'r_liteprofile r_emailaddress w_member_social',
 '{frontend_url}/linkedin/callback',
 '/images/platforms/linkedin.svg'),

('youtube', 'YouTube', 'oauth2', 
 'https://accounts.google.com/o/oauth2/auth', 
 'https://oauth2.googleapis.com/token',
 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube',
 '{frontend_url}/youtube/callback',
 '/images/platforms/youtube.svg'),

('threads', 'Threads', 'oauth2', 
 'https://www.facebook.com/v21.0/dialog/oauth', 
 'https://graph.facebook.com/v21.0/oauth/access_token',
 'instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement,instagram_manage_insights',
 '{frontend_url}/threads/callback',
 '/images/platforms/threads.svg'),

('tiktok', 'TikTok', 'oauth2', 
 'https://open-api.tiktok.com/platform/oauth/connect/', 
 'https://open-api.tiktok.com/oauth/access_token/',
 'user.info.basic video.publish',
 '{frontend_url}/tiktok/callback',
 '/images/platforms/tiktok.svg');