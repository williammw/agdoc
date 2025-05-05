# Supabase Migration Guide

## Overview
This document outlines the migration from a direct PostgreSQL connection to Supabase.

## Prerequisites
1. Create a Supabase project at [https://app.supabase.io/](https://app.supabase.io/)
2. Obtain your Supabase URL and API key

## Environment Variables
Add the following environment variables to your `.env` file:

```
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-api-key
```

## Database Migration
1. Export your existing PostgreSQL database schema
2. Import the schema into your Supabase database
3. Migrate your data to Supabase

## Stored Procedures
Run the SQL scripts in the `migrations` directory to create necessary stored procedures:

```bash
psql -h db.your-project-id.supabase.co -U postgres -d postgres -f migrations/create_cleanup_expired_logs_function.sql
```

## Code Changes
The following files have been updated to use Supabase:
- `app/database.py`: Initializes the Supabase client
- `app/lifespan.py`: Updates app lifecycle management
- `app/dependencies.py`: Updates database dependencies and user management

## Best Practices
- Use Supabase's Row Level Security (RLS) for enhanced security
- Leverage Supabase realtime features for subscriptions
- Use Supabase Auth when possible instead of Firebase Auth

## Additional Steps
1. Test all endpoints thoroughly after migration
2. Update client-side code to use Supabase client if applicable 