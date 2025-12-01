# Database Schema

This directory contains SQL schema definitions for the Multivio API database.

## Structure

- `schema.sql`: Main schema file with version and relationship information
- `users.sql`: Schema for the users table
- `user_info.sql`: Schema for the user_info table
- `migrations/`: Directory containing versioned migration scripts

## Migration Files

Migration files are named with a sequential number prefix and description:

- `001_initial_schema.sql`: Initial database schema
- `002_feature_x.sql`: (Example) Adds tables/columns for Feature X
- etc.

## How to Apply Migrations

### Using Supabase Dashboard

1. Log in to your Supabase project
2. Go to the SQL Editor
3. Copy and paste the migration script
4. Execute the script

### Using Supabase CLI

```bash
# Install Supabase CLI if not already installed
npm install -g supabase

# Link to your Supabase project
supabase link --project-ref your-project-ref

# Run migration
supabase db push
```

## Schema Version

The current schema version is tracked in the `schema.sql` file and in the `migration_history` table.

## Adding New Tables

When adding new tables:

1. Create a new `.sql` file with the table name
2. Create a new migration file in the `migrations/` directory
3. Update `schema.sql` to include the new table
4. Apply the migration

## Relationships

Current table relationships:

```
users ← user_info (one-to-one)
```

## Indexes

Indexes are created for frequently queried columns to improve performance.

## Triggers

Automatic timestamp updates are implemented using triggers for `updated_at` columns. 