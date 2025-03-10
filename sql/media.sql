-- Create UUID extension if not exists
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create mo_folders table
CREATE TABLE mo_folders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    parent_id UUID REFERENCES mo_folders(id),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

-- Create mo_assets table
CREATE TABLE mo_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,
    size BIGINT,
    url TEXT NOT NULL,
    thumbnail_url TEXT,
    width INTEGER,
    height INTEGER,
    folder_id UUID REFERENCES mo_folders(id),
    metadata JSONB DEFAULT '{}',
    usage_count INTEGER DEFAULT 0,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

-- Create indexes
CREATE INDEX idx_mo_folders_parent_id ON mo_folders(parent_id) WHERE NOT is_deleted;
CREATE INDEX idx_mo_folders_created_by ON mo_folders(created_by) WHERE NOT is_deleted;
CREATE INDEX idx_mo_assets_folder_id ON mo_assets(folder_id) WHERE NOT is_deleted;
CREATE INDEX idx_mo_assets_created_by ON mo_assets(created_by) WHERE NOT is_deleted;
CREATE INDEX idx_mo_assets_type ON mo_assets(type) WHERE NOT is_deleted;
CREATE INDEX idx_mo_assets_name ON mo_assets(name) WHERE NOT is_deleted;


-- 21 Jan 2025 alter
ALTER TABLE mo_assets
ADD COLUMN IF NOT EXISTS processing_status TEXT DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS processing_error TEXT,
ADD COLUMN IF NOT EXISTS content_type TEXT,
ADD COLUMN IF NOT EXISTS original_name TEXT,
ADD COLUMN IF NOT EXISTS file_size BIGINT,
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;

-- Add constraints
ALTER TABLE mo_assets
ALTER COLUMN content_type SET NOT NULL,
ALTER COLUMN original_name SET NOT NULL,
ALTER COLUMN file_size SET NOT NULL;

-- Add index for faster status queries
CREATE INDEX IF NOT EXISTS idx_mo_assets_processing_status 
ON mo_assets(processing_status);

-- Add check constraint for valid status values
ALTER TABLE mo_assets
ADD CONSTRAINT chk_processing_status 
CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed'));


ALTER TABLE mo_assets 
ALTER COLUMN created_by TYPE TEXT;