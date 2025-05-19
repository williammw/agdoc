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

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "moddatetime";

-- Create update_timestamp function
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create users table
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

-- Create user_info table
CREATE TABLE IF NOT EXISTS public.user_info (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    plan_type VARCHAR(50) DEFAULT 'free',
    monthly_post_quota INTEGER DEFAULT 10,
    remaining_posts INTEGER DEFAULT 10,
    subscription_id VARCHAR(255),
    subscription_status VARCHAR(50),
    subscription_end_date TIMESTAMP WITH TIME ZONE,
    last_quota_reset TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    preferences JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT user_info_user_id_key UNIQUE (user_id)
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON public.users(firebase_uid);
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON public.users(username);

CREATE INDEX IF NOT EXISTS idx_user_info_user_id ON public.user_info(user_id);
CREATE INDEX IF NOT EXISTS idx_user_info_plan_type ON public.user_info(plan_type);
CREATE INDEX IF NOT EXISTS idx_user_info_subscription_status ON public.user_info(subscription_status);

-- Set up automatic timestamp updates
CREATE TRIGGER users_update_timestamp
BEFORE UPDATE ON public.users
FOR EACH ROW
EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER user_info_update_timestamp
BEFORE UPDATE ON public.user_info
FOR EACH ROW
EXECUTE FUNCTION update_timestamp();

-- Enable RLS (Row Level Security)
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_info ENABLE ROW LEVEL SECURITY;

-- Create policies for users table
CREATE POLICY users_read_own ON public.users 
    FOR SELECT 
    USING (auth.uid()::text = firebase_uid);

CREATE POLICY users_update_own ON public.users 
    FOR UPDATE 
    USING (auth.uid()::text = firebase_uid);

CREATE POLICY users_admin_all ON public.users 
    FOR ALL 
    USING (auth.jwt() ? 'admin_access');

CREATE POLICY users_insert ON public.users 
    FOR INSERT 
    WITH CHECK (true);

-- Create policies for user_info table
CREATE POLICY user_info_read_own ON public.user_info 
    FOR SELECT 
    USING (user_id IN (SELECT id FROM public.users WHERE firebase_uid = auth.uid()::text));

CREATE POLICY user_info_update_own ON public.user_info 
    FOR UPDATE 
    USING (user_id IN (SELECT id FROM public.users WHERE firebase_uid = auth.uid()::text));

CREATE POLICY user_info_admin_all ON public.user_info 
    FOR ALL 
    USING (auth.jwt() ? 'admin_access');

CREATE POLICY user_info_insert ON public.user_info 
    FOR INSERT 
    WITH CHECK (true);

-- Commit transaction
COMMIT; 