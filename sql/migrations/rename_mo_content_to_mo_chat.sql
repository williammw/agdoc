-- Migration script to rename mo_chat to mo_chat
-- Created: April 20, 2025

-- Begin transaction
BEGIN;

-- Rename the main table
ALTER TABLE mo_chat RENAME TO mo_chat;

-- Rename related tables
ALTER TABLE mo_content_version RENAME TO mo_chat_version;

-- Rename foreign key constraints for mo_chat_version
ALTER TABLE mo_chat_version 
  DROP CONSTRAINT mo_content_version_content_id_firebase_uid_fkey;

ALTER TABLE mo_chat_version
  ADD CONSTRAINT mo_chat_version_chat_id_firebase_uid_fkey
  FOREIGN KEY (chat_id, firebase_uid) 
  REFERENCES mo_chat(id, firebase_uid);

-- Rename column in mo_chat_version
ALTER TABLE mo_chat_version
  RENAME COLUMN chat_id TO chat_id;

-- Handle the mo_social_post table references
ALTER TABLE mo_social_post
  DROP CONSTRAINT mo_social_post_content_id_firebase_uid_fkey;

ALTER TABLE mo_social_post
  ADD CONSTRAINT mo_social_post_chat_id_firebase_uid_fkey
  FOREIGN KEY (chat_id, firebase_uid)
  REFERENCES mo_chat(id, firebase_uid);

ALTER TABLE mo_social_post
  DROP CONSTRAINT mo_social_post_content_version_id_firebase_uid_fkey;

ALTER TABLE mo_social_post 
  ADD CONSTRAINT mo_social_post_chat_version_id_firebase_uid_fkey
  FOREIGN KEY (content_version_id, firebase_uid)
  REFERENCES mo_chat_version(id, firebase_uid);

-- Rename columns in mo_social_post
ALTER TABLE mo_social_post
  RENAME COLUMN chat_id TO chat_id;

ALTER TABLE mo_social_post
  RENAME COLUMN content_version_id TO chat_version_id;

-- Rename indexes
ALTER INDEX idx_content_firebase_uid RENAME TO idx_chat_firebase_uid;
ALTER INDEX idx_content_status RENAME TO idx_chat_status;
ALTER INDEX idx_content_version_content_id RENAME TO idx_chat_version_chat_id;
ALTER INDEX idx_social_post_content_id RENAME TO idx_social_post_chat_id;

-- End transaction
COMMIT;
