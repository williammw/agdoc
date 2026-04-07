-- Video processing jobs table (for slideshow, subtitle burn, etc.)
-- Mirrors the export_jobs pattern but for video-specific operations.

CREATE TABLE IF NOT EXISTS video_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'slideshow',  -- 'slideshow', 'subtitle_burn', etc.
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    progress INTEGER DEFAULT 0,
    progress_stage TEXT,
    params JSONB,              -- job-specific parameters (slides, effects, etc.)
    output_url TEXT,            -- CDN URL of completed video
    download_url TEXT,          -- Same as output_url (compat)
    error TEXT,
    duration_seconds FLOAT,
    file_size_bytes BIGINT,
    processing_time_seconds FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Index for worker queue polling
CREATE INDEX IF NOT EXISTS idx_video_jobs_status_created ON video_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_video_jobs_user ON video_jobs (user_id);
