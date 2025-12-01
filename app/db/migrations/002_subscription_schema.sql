-- Migration: Add subscription fields to users table and create subscription_history
-- Execute this SQL in your Supabase SQL Editor

-- Add subscription-related columns to users table
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50) DEFAULT 'free',
ADD COLUMN IF NOT EXISTS subscription_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS plan_name VARCHAR(50) DEFAULT 'free',
ADD COLUMN IF NOT EXISTS subscription_end_date TIMESTAMPTZ;

-- Create subscription_history table (if it doesn't exist)
CREATE TABLE IF NOT EXISTS subscription_history (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_email VARCHAR(255) NOT NULL,
  stripe_subscription_id VARCHAR(255),
  plan_name VARCHAR(50),
  status VARCHAR(50),
  amount_paid INTEGER, -- in cents
  currency VARCHAR(3) DEFAULT 'usd',
  period_start TIMESTAMPTZ,
  period_end TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_subscription_history_user_email ON subscription_history(user_email);
CREATE INDEX IF NOT EXISTS idx_subscription_history_stripe_id ON subscription_history(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer ON users(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_users_subscription_status ON users(subscription_status);

-- Add RLS (Row Level Security) policies for subscription_history
ALTER TABLE subscription_history ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own subscription history
CREATE POLICY "Users can view own subscription history" ON subscription_history
  FOR SELECT USING (auth.email() = user_email);

-- Policy: Only authenticated users can insert subscription history (for webhook handlers)
CREATE POLICY "Service role can manage subscription history" ON subscription_history
  FOR ALL USING (auth.role() = 'service_role');

-- Update user_info table to include plan-specific quotas
ALTER TABLE user_info 
ADD COLUMN IF NOT EXISTS plan_type VARCHAR(50) DEFAULT 'free',
ADD COLUMN IF NOT EXISTS monthly_post_quota INTEGER DEFAULT 10,
ADD COLUMN IF NOT EXISTS remaining_posts INTEGER DEFAULT 10;

-- Create or update plan limits based on subscription type
-- This will be handled by the application logic, but here are the default values:
-- free: 10 posts/month
-- basic: 100 posts/month  
-- pro: unlimited (-1)
-- enterprise: unlimited (-1)

-- Add comments for documentation
COMMENT ON COLUMN users.stripe_customer_id IS 'Stripe customer ID for billing';
COMMENT ON COLUMN users.subscription_status IS 'Current subscription status: free, active, canceling, canceled';
COMMENT ON COLUMN users.subscription_id IS 'Stripe subscription ID';
COMMENT ON COLUMN users.plan_name IS 'Subscription plan: free, basic, pro, enterprise';
COMMENT ON TABLE subscription_history IS 'Historical record of all subscription changes';
COMMENT ON COLUMN user_info.plan_type IS 'Current plan type affecting feature access';
COMMENT ON COLUMN user_info.monthly_post_quota IS 'Maximum posts allowed per month (-1 = unlimited)';
COMMENT ON COLUMN user_info.remaining_posts IS 'Posts remaining in current month';

-- Function to reset monthly post quotas (can be called by cron job)
CREATE OR REPLACE FUNCTION reset_monthly_quotas()
RETURNS void AS $$
BEGIN
  UPDATE user_info 
  SET remaining_posts = CASE 
    WHEN monthly_post_quota = -1 THEN 99999  -- Unlimited
    ELSE monthly_post_quota 
  END
  WHERE plan_type IN ('basic', 'pro', 'enterprise');
  
  -- Reset free users to 10 posts
  UPDATE user_info 
  SET remaining_posts = 10
  WHERE plan_type = 'free' OR plan_type IS NULL;
END;
$$ LANGUAGE plpgsql;