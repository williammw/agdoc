-- Create media table
CREATE TABLE IF NOT EXISTS mo_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(100) NOT NULL,
    size BIGINT NOT NULL,
    url TEXT NOT NULL,
    thumbnail_url TEXT,
    folder_id UUID REFERENCES mo_folders(id),
    created_by VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT false
);

-- Create file stats table for image/video metadata
CREATE TABLE IF NOT EXISTS mo_file_stats (
    file_id UUID PRIMARY KEY REFERENCES mo_media(id),
    width INTEGER,
    height INTEGER,
    duration FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_media_created_by ON mo_media(created_by);
CREATE INDEX IF NOT EXISTS idx_media_folder_id ON mo_media(folder_id);
CREATE INDEX IF NOT EXISTS idx_media_created_at ON mo_media(created_at);
