-- Conversations Table
CREATE TABLE mo_llm_conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL REFERENCES mo_user_info(id),
    title TEXT,
    model_id VARCHAR(50) NOT NULL,  -- e.g., 'grok-2-1212'
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

-- Messages Table  
CREATE TABLE mo_llm_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES mo_llm_conversations(id),
    role VARCHAR(20) NOT NULL,  -- 'user', 'assistant', 'system', 'function'
    content TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB,
    tokens_used INTEGER,
    function_call JSONB  -- For storing function call information
);

-- Function Calls Table
CREATE TABLE mo_llm_function_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    message_id UUID NOT NULL REFERENCES mo_llm_messages(id),
    function_name VARCHAR(100) NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,
    status VARCHAR(20) NOT NULL,  -- 'pending', 'success', 'failed'
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

--  additional for mo_llm_conversations
-- Migration script to add chat_id to mo_llm_conversations

-- Add the column with character varying(36) type to match mo_chat.uuid
ALTER TABLE mo_llm_conversations
ADD COLUMN chat_id character varying(36) NULL;

-- Add foreign key constraint
ALTER TABLE mo_llm_conversations
ADD CONSTRAINT fk_content_id
    FOREIGN KEY (chat_id)
    REFERENCES mo_chat (uuid)
    ON DELETE SET NULL;

-- Add index for performance
CREATE INDEX idx_conversations_content_id ON mo_llm_conversations (chat_id);