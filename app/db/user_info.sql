-- user_info.sql
-- Schema definition for the user_info table, which stores app-specific user data

-- Create user_info table for additional user information and subscription details
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
CREATE INDEX IF NOT EXISTS idx_user_info_user_id ON public.user_info(user_id);
CREATE INDEX IF NOT EXISTS idx_user_info_plan_type ON public.user_info(plan_type);
CREATE INDEX IF NOT EXISTS idx_user_info_subscription_status ON public.user_info(subscription_status);

-- Add RLS (Row Level Security) policies
ALTER TABLE public.user_info ENABLE ROW LEVEL SECURITY;

-- Policy to allow users to read their own info
CREATE POLICY user_info_read_own ON public.user_info 
    FOR SELECT 
    USING (user_id IN (SELECT id FROM public.users WHERE firebase_uid = auth.uid()::text));

-- Policy to allow users to update their own preferences
CREATE POLICY user_info_update_own ON public.user_info 
    FOR UPDATE 
    USING (user_id IN (SELECT id FROM public.users WHERE firebase_uid = auth.uid()::text));

-- Policy to allow system/admin access for all operations
CREATE POLICY user_info_admin_all ON public.user_info 
    FOR ALL 
    USING (auth.jwt() ? 'admin_access');

-- Policy to allow insert for new user info
CREATE POLICY user_info_insert ON public.user_info 
    FOR INSERT 
    WITH CHECK (true);

-- Create a trigger to automatically update updated_at timestamp
CREATE TRIGGER user_info_update_timestamp
BEFORE UPDATE ON public.user_info
FOR EACH ROW
EXECUTE FUNCTION update_timestamp();

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