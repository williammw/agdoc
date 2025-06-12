-- Migration 004: Unified Posts Table
-- This migration creates a unified posts table to replace the dual-table approach
-- of post_groups + post_drafts for better performance

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create the unified posts table
CREATE TABLE IF NOT EXISTS posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Basic post information
    name VARCHAR(255) NOT NULL,
    content_mode VARCHAR(20) DEFAULT 'universal' CHECK (content_mode IN ('universal', 'specific')),
    
    -- Content data (from post_drafts)
    universal_content TEXT,
    universal_metadata JSONB DEFAULT '{}'::jsonb,
    platform_content JSONB DEFAULT '{}'::jsonb,
    
    -- Platform and media data
    platforms JSONB DEFAULT '[]'::jsonb, -- Array of platform objects
    media_files JSONB DEFAULT '[]'::jsonb, -- Array of media file objects
    
    -- Scheduling
    schedule_date TIMESTAMPTZ,
    
    -- Status tracking
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'scheduled', 'publishing', 'published', 'failed')),
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS posts_user_id_idx ON posts(user_id);
CREATE INDEX IF NOT EXISTS posts_status_idx ON posts(status);
CREATE INDEX IF NOT EXISTS posts_created_at_idx ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS posts_schedule_date_idx ON posts(schedule_date) WHERE status = 'scheduled';

-- Add GIN indexes for JSONB columns for efficient querying
CREATE INDEX IF NOT EXISTS posts_universal_metadata_gin_idx ON posts USING GIN (universal_metadata);
CREATE INDEX IF NOT EXISTS posts_platform_content_gin_idx ON posts USING GIN (platform_content);
CREATE INDEX IF NOT EXISTS posts_platforms_gin_idx ON posts USING GIN (platforms);
CREATE INDEX IF NOT EXISTS posts_media_files_gin_idx ON posts USING GIN (media_files);

-- Create update timestamp trigger
CREATE TRIGGER update_posts_updated_at 
    BEFORE UPDATE ON posts 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Create a function to migrate data from the dual-table approach
CREATE OR REPLACE FUNCTION migrate_to_unified_posts()
RETURNS void AS $$
DECLARE
    group_record RECORD;
    draft_record RECORD;
    platforms_json JSONB := '[]'::jsonb;
    media_files_json JSONB := '[]'::jsonb;
    universal_metadata_json JSONB := '{}'::jsonb;
BEGIN
    RAISE NOTICE 'Starting migration from post_groups + post_drafts to unified posts table...';
    
    -- Loop through all post groups
    FOR group_record IN 
        SELECT * FROM post_groups 
        ORDER BY created_at ASC
    LOOP
        -- Reset for each group
        platforms_json := '[]'::jsonb;
        media_files_json := '[]'::jsonb;
        universal_metadata_json := '{}'::jsonb;
        
        -- Find the most recent draft for this group to get content data
        SELECT * INTO draft_record
        FROM post_drafts 
        WHERE user_id = group_record.user_id 
        AND post_group_id = group_record.id
        ORDER BY created_at DESC 
        LIMIT 1;
        
        -- If we have draft data, extract the structured data
        IF draft_record IS NOT NULL THEN
            -- Try to parse existing JSONB fields or use defaults
            BEGIN
                -- Parse selected_platforms if it exists and is valid JSON
                IF draft_record.selected_platforms IS NOT NULL AND draft_record.selected_platforms != '' THEN
                    platforms_json := draft_record.selected_platforms::jsonb;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                platforms_json := '[]'::jsonb;
            END;
            
            BEGIN
                -- Parse media_files if it exists and is valid JSON
                IF draft_record.media_files IS NOT NULL AND draft_record.media_files != '' THEN
                    media_files_json := draft_record.media_files::jsonb;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                media_files_json := '[]'::jsonb;
            END;
            
            BEGIN
                -- Parse universal_metadata if it exists and is valid JSON
                IF draft_record.universal_metadata IS NOT NULL AND draft_record.universal_metadata != '' THEN
                    universal_metadata_json := draft_record.universal_metadata::jsonb;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                universal_metadata_json := '{}'::jsonb;
            END;
        END IF;
        
        -- Insert into unified posts table
        INSERT INTO posts (
            id,
            user_id,
            name,
            content_mode,
            universal_content,
            universal_metadata,
            platform_content,
            platforms,
            media_files,
            schedule_date,
            status,
            created_at,
            updated_at
        ) VALUES (
            group_record.id, -- Keep the same UUID
            group_record.user_id,
            group_record.name,
            group_record.content_mode,
            COALESCE(draft_record.universal_content, ''),
            universal_metadata_json,
            COALESCE(draft_record.account_specific_content::jsonb, '{}'::jsonb),
            platforms_json,
            media_files_json,
            draft_record.schedule_date,
            COALESCE(draft_record.status, 'draft'),
            group_record.created_at,
            GREATEST(group_record.updated_at, COALESCE(draft_record.updated_at, group_record.updated_at))
        )
        ON CONFLICT (id) DO NOTHING; -- Skip if already exists
        
        RAISE NOTICE 'Migrated post group: % (ID: %)', group_record.name, group_record.id;
    END LOOP;
    
    RAISE NOTICE 'Migration completed successfully!';
END;
$$ LANGUAGE plpgsql;

-- Record migration
INSERT INTO migration_history (version, description)
SELECT '004', 'Unified Posts Table - Replaces post_groups + post_drafts dual-table approach'
WHERE NOT EXISTS (SELECT 1 FROM migration_history WHERE version = '004');

-- Note: The migration function is created but not executed automatically
-- Run the following command manually after verifying the migration:
-- SELECT migrate_to_unified_posts();