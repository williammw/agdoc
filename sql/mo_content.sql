-- Content table to store the main content information
CREATE TABLE mo_content (
    id SERIAL,
    uuid VARCHAR(36) NOT NULL,
    firebase_uid VARCHAR(128) NOT NULL,  -- Firebase user ID as primary reference
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    route VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'draft',  -- draft, published, archived
    PRIMARY KEY (id, firebase_uid),
    UNIQUE(uuid),
    UNIQUE(route),
    FOREIGN KEY (firebase_uid) REFERENCES mo_user_info(id)
);

-- Content version table to keep track of content revisions
CREATE TABLE mo_content_version (
    id SERIAL,
    content_id INTEGER NOT NULL,
    firebase_uid VARCHAR(128) NOT NULL,  -- Firebase user ID for ownership
    version INTEGER NOT NULL,
    content_data JSONB NOT NULL,  -- Store the actual content data
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, firebase_uid),
    FOREIGN KEY (content_id, firebase_uid) REFERENCES mo_content(id, firebase_uid)
);

-- Social media posts table to track posts for each content
CREATE TABLE mo_social_post (
    id SERIAL,
    content_id INTEGER NOT NULL,
    firebase_uid VARCHAR(128) NOT NULL,  -- Firebase user ID for ownership
    content_version_id INTEGER NOT NULL,
    platform VARCHAR(50) NOT NULL,  -- facebook, twitter, instagram, etc.
    platform_account_id VARCHAR(255) NOT NULL,  -- ID of the social media account
    post_status VARCHAR(50) DEFAULT 'draft',  -- draft, scheduled, published, failed
    scheduled_time TIMESTAMP WITH TIME ZONE,
    published_time TIMESTAMP WITH TIME ZONE,
    platform_post_id VARCHAR(255),  -- ID of the post on the platform
    post_data JSONB,  -- Platform-specific post data
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, firebase_uid),
    FOREIGN KEY (content_id, firebase_uid) REFERENCES mo_content(id, firebase_uid),
    FOREIGN KEY (content_version_id, firebase_uid) REFERENCES mo_content_version(id, firebase_uid)
);

-- Create indexes for better query performance
CREATE INDEX idx_content_firebase_uid ON mo_content(firebase_uid);
CREATE INDEX idx_content_status ON mo_content(status);
CREATE INDEX idx_content_version_content_id ON mo_content_version(content_id, firebase_uid);
CREATE INDEX idx_social_post_content_id ON mo_social_post(content_id, firebase_uid);
CREATE INDEX idx_social_post_platform ON mo_social_post(platform);
CREATE INDEX idx_social_post_status ON mo_social_post(post_status);


ALTER TABLE mo_social_accounts
ADD COLUMN oauth1_token TEXT,
ADD COLUMN oauth1_token_secret TEXT;

CREATE INDEX idx_social_accounts_oauth1 ON mo_social_accounts(oauth1_token) WHERE oauth1_token IS NOT NULL;
