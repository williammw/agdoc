CREATE TABLE process_tasks (
    id UUID PRIMARY KEY,
    related_id UUID,
    task_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    progress INTEGER DEFAULT 0,
    result_url TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_process_tasks_related_id ON process_tasks(related_id);
CREATE INDEX idx_process_tasks_status ON process_tasks(status);

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to call the function
CREATE TRIGGER update_process_task_modtime
    BEFORE UPDATE ON process_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();