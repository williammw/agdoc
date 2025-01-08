-- Create table for user profile information
CREATE TABLE IF NOT EXISTS mo_user_info (
    id VARCHAR(255) PRIMARY KEY,  -- Firebase UID
    email VARCHAR(255) NOT NULL,
    username VARCHAR(255),
    full_name VARCHAR(255),
    phone_number VARCHAR(50),
    plan_type VARCHAR(50) DEFAULT 'free',  -- free, pro, business, enterprise
    plan_valid_until TIMESTAMP WITH TIME ZONE,
    monthly_post_quota INTEGER DEFAULT 50,
    remaining_posts INTEGER DEFAULT 50,
    quota_reset_date TIMESTAMP WITH TIME ZONE,
    timezone VARCHAR(50) DEFAULT 'UTC',
    company_name VARCHAR(255),
    company_size VARCHAR(50),
    industry VARCHAR(100),
    language_preference VARCHAR(50) DEFAULT 'en',
    notification_preferences JSONB DEFAULT '{"email": true, "push": true}',
    api_key VARCHAR(255),
    api_key_created_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false,
    subscription_id VARCHAR(255),  -- For payment system reference
    payment_method JSONB,
    billing_address JSONB,
    CONSTRAINT valid_plan CHECK (plan_type IN ('free', 'pro', 'business', 'enterprise')),
    CONSTRAINT valid_quota CHECK (monthly_post_quota >= 0 AND remaining_posts >= 0)
);

-- Create trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;   
END;
$$ language 'plpgsql';

CREATE TRIGGER update_user_info_updated_at
    BEFORE UPDATE ON mo_user_info
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create index for faster lookups
CREATE INDEX idx_user_info_email ON mo_user_info(email);
CREATE INDEX idx_user_info_plan_type ON mo_user_info(plan_type);
CREATE INDEX idx_user_info_plan_valid_until ON mo_user_info(plan_valid_until);
