-- user_info.sql
-- Schema definition for the user_info table, which stores app-specific user data

CREATE TABLE IF NOT EXISTS user_info (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_type TEXT DEFAULT 'free',
    monthly_post_quota INTEGER DEFAULT 10,
    remaining_posts INTEGER DEFAULT 10,
    last_quota_reset TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index on user_id for faster lookup
CREATE INDEX IF NOT EXISTS idx_user_info_user_id ON user_info(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_info_unique_user ON user_info(user_id);

-- Create trigger to update the updated_at timestamp automatically
CREATE OR REPLACE FUNCTION update_user_info_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS user_info_update_timestamp ON user_info;
CREATE TRIGGER user_info_update_timestamp
BEFORE UPDATE ON user_info
FOR EACH ROW
EXECUTE FUNCTION update_user_info_timestamp();

-- Comments
COMMENT ON TABLE user_info IS 'Stores app-specific user information such as subscription plans and quotas';
COMMENT ON COLUMN user_info.id IS 'Primary key for user_info';
COMMENT ON COLUMN user_info.user_id IS 'Foreign key to users table';
COMMENT ON COLUMN user_info.plan_type IS 'Subscription plan type (free, premium, etc.)';
COMMENT ON COLUMN user_info.monthly_post_quota IS 'Monthly quota for posts';
COMMENT ON COLUMN user_info.remaining_posts IS 'Remaining posts for current period';
COMMENT ON COLUMN user_info.last_quota_reset IS 'Timestamp of last quota reset';
COMMENT ON COLUMN user_info.created_at IS 'Timestamp when record was created';
COMMENT ON COLUMN user_info.updated_at IS 'Timestamp when record was last updated'; 