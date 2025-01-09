-- Create mo_user_info table
CREATE TABLE IF NOT EXISTS mo_user_info (
    id VARCHAR(255) PRIMARY KEY,  -- Firebase UID
    email VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    plan_type VARCHAR(50) DEFAULT 'free',
    monthly_post_quota INTEGER DEFAULT 50,
    remaining_posts INTEGER DEFAULT 50,
    language_preference VARCHAR(10) DEFAULT 'en',
    timezone VARCHAR(50) DEFAULT 'UTC',
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_mo_user_info_email ON mo_user_info(email);
CREATE INDEX IF NOT EXISTS idx_mo_user_info_username ON mo_user_info(username);

-- Add unique constraint on email
ALTER TABLE mo_user_info ADD CONSTRAINT uq_mo_user_info_email UNIQUE (email);

-- Add unique constraint on username
ALTER TABLE mo_user_info ADD CONSTRAINT uq_mo_user_info_username UNIQUE (username);

-- Add comments
COMMENT ON TABLE mo_user_info IS 'Stores user information for the Multivio application';
COMMENT ON COLUMN mo_user_info.id IS 'Firebase UID used as primary key';
COMMENT ON COLUMN mo_user_info.email IS 'User email address';
COMMENT ON COLUMN mo_user_info.username IS 'Unique username';
COMMENT ON COLUMN mo_user_info.full_name IS 'User full name';
COMMENT ON COLUMN mo_user_info.plan_type IS 'Subscription plan type (free, premium, etc.)';
COMMENT ON COLUMN mo_user_info.monthly_post_quota IS 'Number of posts allowed per month';
COMMENT ON COLUMN mo_user_info.remaining_posts IS 'Remaining posts for current month';
COMMENT ON COLUMN mo_user_info.language_preference IS 'Preferred language code';
COMMENT ON COLUMN mo_user_info.timezone IS 'User timezone';
COMMENT ON COLUMN mo_user_info.is_active IS 'Whether the user account is active';
COMMENT ON COLUMN mo_user_info.is_verified IS 'Whether the user email is verified';
COMMENT ON COLUMN mo_user_info.created_at IS 'Account creation timestamp';
COMMENT ON COLUMN mo_user_info.updated_at IS 'Last update timestamp';
COMMENT ON COLUMN mo_user_info.last_login_at IS 'Last login timestamp';

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_mo_user_info_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to automatically update updated_at
CREATE TRIGGER update_mo_user_info_updated_at
    BEFORE UPDATE ON mo_user_info
    FOR EACH ROW
    EXECUTE FUNCTION update_mo_user_info_updated_at();

-- Sample data for testing (optional)
INSERT INTO mo_user_info (id, email, username, full_name)
VALUES 
    ('test_uid_1', 'test1@example.com', 'testuser1', 'Test User One'),
    ('test_uid_2', 'test2@example.com', 'testuser2', 'Test User Two')
ON CONFLICT (id) DO NOTHING;




ALTER TABLE mo_user_info
ADD COLUMN firebase_display_name VARCHAR(255),
ADD COLUMN firebase_photo_url TEXT,
ADD COLUMN is_email_verified BOOLEAN DEFAULT FALSE;

ALTER TABLE mo_user_info ADD COLUMN country_code VARCHAR(10);