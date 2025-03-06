
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
                error TEXT
            );
            CREATE INDEX idx_ai_tasks_created_by ON mo_ai_tasks(created_by);
            CREATE INDEX idx_ai_tasks_status ON mo_ai_tasks(status);