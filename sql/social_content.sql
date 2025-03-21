-- social_content.sql
-- Tables for tracking social media content (posts, media, etc.)

-- Social media posts table
CREATE TABLE mo_social_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    account_id UUID NOT NULL REFERENCES mo_social_accounts(id) ON DELETE CASCADE,
    platform mo_social_platform NOT NULL,
    platform_post_id VARCHAR(255),
    content TEXT,
    title VARCHAR(255),
    post_type VARCHAR(50) DEFAULT 'status',
    privacy VARCHAR(20) DEFAULT 'public',
    hashtags TEXT[],
    mentions TEXT[],
    media_count INTEGER DEFAULT 0,
    url VARCHAR(512),
    engagement_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'draft',
    is_crossposted BOOLEAN DEFAULT FALSE,
    original_post_id UUID REFERENCES mo_social_posts(id) ON DELETE SET NULL,
    scheduled_for TIMESTAMP WITH TIME ZONE,
    published_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for social posts
CREATE INDEX idx_social_posts_user_id ON mo_social_posts(user_id);
CREATE INDEX idx_social_posts_account_id ON mo_social_posts(account_id);
CREATE INDEX idx_social_posts_platform ON mo_social_posts(platform);
CREATE INDEX idx_social_posts_status ON mo_social_posts(status);
CREATE INDEX idx_social_posts_scheduled_for ON mo_social_posts(scheduled_for) 
    WHERE scheduled_for IS NOT NULL;

-- Foreign key to user table
ALTER TABLE mo_social_posts 
ADD CONSTRAINT mo_social_posts_user_id_fkey
FOREIGN KEY (user_id) REFERENCES mo_user_info(id) ON DELETE CASCADE;

-- Trigger for updated_at
CREATE TRIGGER update_social_posts_updated_at
BEFORE UPDATE ON mo_social_posts
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Social media assets table (images, videos)
CREATE TABLE mo_social_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    platform mo_social_platform,
    platform_asset_id VARCHAR(255),
    account_id UUID REFERENCES mo_social_accounts(id) ON DELETE SET NULL,
    post_id UUID REFERENCES mo_social_posts(id) ON DELETE SET NULL,
    asset_type VARCHAR(20) NOT NULL, -- image, video, document, etc.
    filename VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    thumbnail_url TEXT,
    cdn_url TEXT,
    size_bytes BIGINT,
    width INTEGER,
    height INTEGER,
    duration_seconds FLOAT,
    mime_type VARCHAR(100),
    description TEXT,
    alt_text TEXT,
    processing_status mo_processing_status DEFAULT 'pending',
    processing_error TEXT,
    original_url TEXT,
    is_temp BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    folder_id UUID,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for social assets
CREATE INDEX idx_social_assets_user_id ON mo_social_assets(user_id);
CREATE INDEX idx_social_assets_post_id ON mo_social_assets(post_id) WHERE post_id IS NOT NULL;
CREATE INDEX idx_social_assets_account_id ON mo_social_assets(account_id) WHERE account_id IS NOT NULL;
CREATE INDEX idx_social_assets_processing_status ON mo_social_assets(processing_status);

-- Foreign key to user table
ALTER TABLE mo_social_assets
ADD CONSTRAINT mo_social_assets_user_id_fkey
FOREIGN KEY (user_id) REFERENCES mo_user_info(id) ON DELETE CASCADE;

-- Trigger for updated_at
CREATE TRIGGER update_social_assets_updated_at
BEFORE UPDATE ON mo_social_assets
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Post analytics table
CREATE TABLE mo_social_post_analytics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES mo_social_posts(id) ON DELETE CASCADE,
    platform mo_social_platform NOT NULL,
    impressions INTEGER DEFAULT 0,
    reach INTEGER DEFAULT 0,
    engagement INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    video_views INTEGER DEFAULT 0,
    snapshot_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    raw_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for post analytics
CREATE INDEX idx_social_post_analytics_post_id ON mo_social_post_analytics(post_id);
CREATE INDEX idx_social_post_analytics_platform ON mo_social_post_analytics(platform);
CREATE INDEX idx_social_post_analytics_snapshot_time ON mo_social_post_analytics(snapshot_time);

-- Media folders for organizing assets
CREATE TABLE mo_media_folders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL REFERENCES mo_user_info(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    parent_id UUID REFERENCES mo_media_folders(id) ON DELETE CASCADE,
    is_default BOOLEAN DEFAULT FALSE,
    is_system BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Ensure unique folder names per user and parent
    UNIQUE (user_id, parent_id, name, is_deleted)
);

-- Indexes for media folders
CREATE INDEX idx_media_folders_user_id ON mo_media_folders(user_id);
CREATE INDEX idx_media_folders_parent_id ON mo_media_folders(parent_id) WHERE parent_id IS NOT NULL;

-- Trigger for updated_at
CREATE TRIGGER update_media_folders_updated_at
BEFORE UPDATE ON mo_media_folders
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();