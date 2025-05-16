-- 001_initial_schema.sql
-- Initial database schema migration for Multivio API
-- Version: 1.0.0
-- Date: 2024-07-18

-- Start transaction
BEGIN;

-- Create migration_history table to track versions
CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

-- Version tracking
INSERT INTO migration_history (version, description)
VALUES ('1.0.0', 'Initial schema creation');

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    firebase_uid TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE,
    full_name TEXT,
    avatar_url TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    auth_provider TEXT DEFAULT 'email',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- Create user_info table
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

-- Create indexes for user_info table
CREATE INDEX IF NOT EXISTS idx_user_info_user_id ON user_info(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_info_unique_user ON user_info(user_id);

-- Create timestamp update functions and triggers
CREATE OR REPLACE FUNCTION update_users_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_update_timestamp
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_users_timestamp();

CREATE OR REPLACE FUNCTION update_user_info_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_info_update_timestamp
BEFORE UPDATE ON user_info
FOR EACH ROW
EXECUTE FUNCTION update_user_info_timestamp();

-- Commit transaction
COMMIT; 