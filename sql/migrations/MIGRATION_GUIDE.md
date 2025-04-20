# Database Migration Guide: mo_chat to mo_chat

This guide explains how to safely migrate from the `mo_chat` table structure to the new `mo_chat` table structure.

## Prerequisites

- Access to your PostgreSQL database
- A recent backup of your database
- Sufficient permissions to modify tables and constraints

## Migration Steps

### 1. Create a Database Backup

```bash
pg_dump -U your_username -d your_database > pre_migration_backup.sql
```

### 2. Apply the Migration Script in Development Environment

```bash
psql -U your_username -d your_dev_database -f ./sql/migrations/rename_mo_content_to_mo_chat.sql
```

### 3. Verify the Migration

After running the migration script, verify that:
- Tables were renamed correctly
- Foreign key constraints are working
- Indexes were renamed

```sql
-- Check if tables exist
SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'mo_chat');
SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'mo_chat_version');

-- Check foreign key constraints
SELECT
    tc.constraint_name, tc.table_name, kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM
    information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
    JOIN information_schema.constraint_column_usage AS ccu
      ON ccu.constraint_name = tc.constraint_name
WHERE constraint_type = 'FOREIGN KEY' AND tc.table_name='mo_chat_version';
```

### 4. Apply Migration to Production

Once verified in development, apply to production:

```bash
pg_dump -U your_username -d your_production_database > pre_prod_migration_backup.sql
psql -U your_username -d your_production_database -f ./sql/migrations/rename_mo_content_to_mo_chat.sql
```

## Rollback Plan

If issues are encountered, you can restore from the backup:

```bash
psql -U your_username -d your_database < pre_migration_backup.sql
```

## Notes

- This migration preserves all data
- Only table and column names are changed
- The structure remains the same
- Make sure all application code is updated to use the new table names before deploying the migration
