-- users.sql
-- Schema definition for the users table

-- Create users table for authentication and profiles
CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    firebase_uid VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE,
    full_name VARCHAR(255),
    avatar_url TEXT,
    email_verified BOOLEAN DEFAULT false,
    auth_provider VARCHAR(50) DEFAULT 'email',
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON public.users(firebase_uid);
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON public.users(username);

-- Add RLS (Row Level Security) policies
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- Policy to allow users to read their own data
CREATE POLICY users_read_own ON public.users 
    FOR SELECT 
    USING (auth.uid()::text = firebase_uid);

-- Policy to allow users to update their own data
CREATE POLICY users_update_own ON public.users 
    FOR UPDATE 
    USING (auth.uid()::text = firebase_uid);

-- Policy to allow system/admin access for all operations
CREATE POLICY users_admin_all ON public.users 
    FOR ALL 
    USING (auth.jwt() ? 'admin_access');

-- Policy to allow insert for new users
CREATE POLICY users_insert ON public.users 
    FOR INSERT 
    WITH CHECK (true);

-- Create a trigger to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_update_timestamp
BEFORE UPDATE ON public.users
FOR EACH ROW
EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE users IS 'Stores user account information';
COMMENT ON COLUMN users.id IS 'Primary key for user';
COMMENT ON COLUMN users.firebase_uid IS 'Firebase authentication UID';
COMMENT ON COLUMN users.email IS 'User email address';
COMMENT ON COLUMN users.username IS 'Unique username for display';
COMMENT ON COLUMN users.full_name IS 'User full name';
COMMENT ON COLUMN users.avatar_url IS 'URL to user avatar/profile picture';
COMMENT ON COLUMN users.email_verified IS 'Whether email has been verified';
COMMENT ON COLUMN users.auth_provider IS 'Authentication provider (email, google, etc.)';
COMMENT ON COLUMN users.is_active IS 'Whether user account is active';
COMMENT ON COLUMN users.created_at IS 'Timestamp when user was created';
COMMENT ON COLUMN users.updated_at IS 'Timestamp when user was last updated'; 