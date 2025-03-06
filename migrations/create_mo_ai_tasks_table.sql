-- Migration to create mo_ai_tasks table for AI task tracking

-- Check if the table already exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'mo_ai_tasks'
    ) THEN
        -- Create the table for AI tasks
        CREATE TABLE mo_ai_tasks (
            id VARCHAR(36) PRIMARY KEY,
            type VARCHAR(50) NOT NULL,
            parameters JSONB NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_by VARCHAR(255) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at TIMESTAMP WITH TIME ZONE,
            result JSONB,
            error TEXT,
            FOREIGN KEY (created_by) REFERENCES mo_user_info(id) ON DELETE CASCADE
        );

        -- Create indexes for better performance
        CREATE INDEX idx_ai_tasks_created_by ON mo_ai_tasks(created_by);
        CREATE INDEX idx_ai_tasks_status ON mo_ai_tasks(status);
        CREATE INDEX idx_ai_tasks_type ON mo_ai_tasks(type);
        CREATE INDEX idx_ai_tasks_created_at ON mo_ai_tasks(created_at);
    END IF;
END
$$;