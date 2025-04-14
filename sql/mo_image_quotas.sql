
-- Track user quotas for image generation
CREATE TABLE mo_image_quotas (
    user_id VARCHAR(255) PRIMARY KEY,
    daily_limit INT NOT NULL DEFAULT 10,
    daily_used INT NOT NULL DEFAULT 0,
    monthly_limit INT NOT NULL DEFAULT 100,
    monthly_used INT NOT NULL DEFAULT 0,
    last_reset_date DATE NOT NULL DEFAULT CURRENT_DATE
);