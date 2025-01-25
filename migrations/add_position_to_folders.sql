-- Add position column to mo_folders table
ALTER TABLE mo_folders ADD COLUMN IF NOT EXISTS position INTEGER DEFAULT 0;

-- Update existing folders with sequential positions based on creation date
WITH numbered_folders AS (
  SELECT id, ROW_NUMBER() OVER (PARTITION BY created_by ORDER BY created_at) - 1 as new_position
  FROM mo_folders
  WHERE is_deleted = false
)
UPDATE mo_folders f
SET position = n.new_position
FROM numbered_folders n
WHERE f.id = n.id;