-- Migration 003: Content Management System
-- This migration adds tables for post creation, scheduling, and publishing

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Post Groups: Container for organizing multiple related posts
CREATE TABLE IF NOT EXISTS post_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    content_mode VARCHAR(20) DEFAULT 'universal' CHECK (content_mode IN ('universal', 'specific')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Post Drafts: Individual posts within a group (before publishing)
CREATE TABLE IF NOT EXISTS post_drafts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_group_id UUID NOT NULL REFERENCES post_groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Platform targeting
    platform VARCHAR(50) NOT NULL,
    account_id UUID REFERENCES social_connections(id) ON DELETE SET NULL,
    account_key VARCHAR(100), -- Format: "provider:account_id" for flexible targeting
    
    -- Content data
    content TEXT,
    hashtags JSONB DEFAULT '[]'::jsonb,
    mentions JSONB DEFAULT '[]'::jsonb,
    media_ids JSONB DEFAULT '[]'::jsonb,
    
    -- Platform-specific fields
    youtube_title VARCHAR(100),
    youtube_description TEXT,
    youtube_tags JSONB DEFAULT '[]'::jsonb,
    
    -- Additional metadata
    location VARCHAR(255),
    link VARCHAR(500),
    
    -- Scheduling
    schedule_date DATE,
    schedule_time TIME,
    timezone VARCHAR(50) DEFAULT 'UTC',
    
    -- Status tracking
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'scheduled', 'publishing', 'published', 'failed')),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Published Posts: Record of successfully published posts
CREATE TABLE IF NOT EXISTS published_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_draft_id UUID REFERENCES post_drafts(id) ON DELETE SET NULL,
    post_group_id UUID NOT NULL REFERENCES post_groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Platform info
    platform VARCHAR(50) NOT NULL,
    account_id UUID REFERENCES social_connections(id) ON DELETE SET NULL,
    
    -- Content snapshot at time of publishing
    content_snapshot JSONB NOT NULL,
    
    -- Platform response data
    platform_post_id VARCHAR(255), -- ID returned by the platform
    platform_url VARCHAR(500), -- URL to the published post
    platform_response JSONB, -- Full platform API response
    
    -- Publishing details
    published_at TIMESTAMPTZ DEFAULT NOW(),
    engagement_stats JSONB DEFAULT '{}'::jsonb, -- Likes, shares, comments, etc.
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Media Files: Store media metadata and references
CREATE TABLE IF NOT EXISTS media_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- File information
    filename VARCHAR(255) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(10) NOT NULL CHECK (file_type IN ('image', 'video')),
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    
    -- Storage information
    storage_path VARCHAR(500) NOT NULL,
    storage_url VARCHAR(500),
    
    -- Platform compatibility
    platform_compatibility JSONB DEFAULT '[]'::jsonb,
    
    -- Processing status
    processing_status VARCHAR(20) DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
    
    -- Metadata
    width INTEGER,
    height INTEGER,
    duration INTEGER, -- For videos, in seconds
    thumbnail_url VARCHAR(500),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scheduled Jobs: Track background tasks for publishing
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_draft_id UUID NOT NULL REFERENCES post_drafts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    job_type VARCHAR(50) NOT NULL DEFAULT 'publish_post',
    scheduled_for TIMESTAMPTZ NOT NULL,
    
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    
    error_message TEXT,
    result JSONB,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS post_groups_user_id_idx ON post_groups(user_id);
CREATE INDEX IF NOT EXISTS post_groups_created_at_idx ON post_groups(created_at DESC);

CREATE INDEX IF NOT EXISTS post_drafts_post_group_id_idx ON post_drafts(post_group_id);
CREATE INDEX IF NOT EXISTS post_drafts_user_id_idx ON post_drafts(user_id);
CREATE INDEX IF NOT EXISTS post_drafts_status_idx ON post_drafts(status);
CREATE INDEX IF NOT EXISTS post_drafts_schedule_idx ON post_drafts(schedule_date, schedule_time) WHERE status = 'scheduled';

CREATE INDEX IF NOT EXISTS published_posts_user_id_idx ON published_posts(user_id);
CREATE INDEX IF NOT EXISTS published_posts_platform_idx ON published_posts(platform);
CREATE INDEX IF NOT EXISTS published_posts_published_at_idx ON published_posts(published_at DESC);

CREATE INDEX IF NOT EXISTS media_files_user_id_idx ON media_files(user_id);
CREATE INDEX IF NOT EXISTS media_files_file_type_idx ON media_files(file_type);

CREATE INDEX IF NOT EXISTS scheduled_jobs_scheduled_for_idx ON scheduled_jobs(scheduled_for) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS scheduled_jobs_user_id_idx ON scheduled_jobs(user_id);

-- Update timestamp triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_post_groups_updated_at BEFORE UPDATE ON post_groups FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_post_drafts_updated_at BEFORE UPDATE ON post_drafts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_published_posts_updated_at BEFORE UPDATE ON published_posts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_media_files_updated_at BEFORE UPDATE ON media_files FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_scheduled_jobs_updated_at BEFORE UPDATE ON scheduled_jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Record migration
INSERT INTO migration_history (version, description)
SELECT '003', 'Content Management System - Post Groups, Drafts, Publishing'
WHERE NOT EXISTS (SELECT 1 FROM migration_history WHERE version = '003');