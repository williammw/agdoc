-- schema.sql
-- Main schema file for the Multivio API database
-- This file lists all tables and their relationships

-- Table structure version
-- Increment this version whenever schema changes
CREATE OR REPLACE FUNCTION get_schema_version() RETURNS TEXT AS $$
BEGIN
    RETURN '1.0.0';
END;
$$ LANGUAGE plpgsql;

-- Schema initialization order
-- Tables should be created in this order to respect references:

-- 1. users.sql
--    Core user accounts table
--    Primary storage for authentication and user identity

-- 2. user_info.sql
--    App-specific user information
--    Stores subscription plans, quotas, and usage data
--    References users table

-- Table relationships:
-- users ← user_info (one-to-one)

-- Migration history table
CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

-- Initial migration record
INSERT INTO migration_history (version, description)
SELECT '1.0.0', 'Initial schema creation'
WHERE NOT EXISTS (SELECT 1 FROM migration_history WHERE version = '1.0.0');

-- Schema health check
CREATE OR REPLACE FUNCTION check_schema_health() RETURNS TABLE(
    table_name TEXT,
    table_exists BOOLEAN,
    row_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 'users'::TEXT, EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'users'), (SELECT COUNT(*) FROM users)
    UNION
    SELECT 'user_info'::TEXT, EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'user_info'), (SELECT COUNT(*) FROM user_info);
END;
$$ LANGUAGE plpgsql; 