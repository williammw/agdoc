-- Track progressive image stages (10%, 50%, 100%)
CREATE TABLE mo_image_stages (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(36) REFERENCES mo_ai_tasks(id),
    stage_number INT NOT NULL,
    completion_percentage INT NOT NULL,
    image_path TEXT NOT NULL,
    image_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, stage_number)
);
