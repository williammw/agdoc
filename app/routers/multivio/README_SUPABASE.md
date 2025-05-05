# Supabase Integration

This document explains how to set up and use the Supabase integration in this project.

## Setup

1. Create a Supabase account and project at [https://supabase.com](https://supabase.com)

2. Get your Supabase URL and anon key from your project dashboard:
   - Go to Settings > API
   - Copy the Project URL and anon/public key

3. Add the following environment variables to your `.env` file:
   ```
   VITE_SUPABASE_URL=https://your-project-id.supabase.co
   VITE_SUPABASE_ANON_KEY=your-supabase-anon-key
   ```

4. Create a test table in your Supabase project:
   - Go to SQL Editor
   - Execute the following SQL:
   ```sql
   CREATE TABLE public.test_items (
       id SERIAL PRIMARY KEY,
       name TEXT NOT NULL,
       description TEXT,
       created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW())
   );
   
   -- Set up Row Level Security (RLS)
   ALTER TABLE public.test_items ENABLE ROW LEVEL SECURITY;
   
   -- Create policies
   CREATE POLICY "Allow anonymous SELECT" ON public.test_items
       FOR SELECT USING (true);
       
   CREATE POLICY "Allow anonymous INSERT" ON public.test_items
       FOR INSERT WITH CHECK (true);
       
   CREATE POLICY "Allow anonymous UPDATE" ON public.test_items
       FOR UPDATE USING (true) WITH CHECK (true);
       
   CREATE POLICY "Allow anonymous DELETE" ON public.test_items
       FOR DELETE USING (true);
   ```

   Alternatively, you can call the setup endpoint which will check if the table exists:
   ```
   POST /api/v1/supabase/setup
   ```
   If the table doesn't exist, it will provide the SQL needed to create it.

## Usage

The Supabase router provides basic CRUD operations for testing:

- `GET /api/v1/supabase/test` - Get all test items
- `POST /api/v1/supabase/test` - Create a new test item
  ```json
  {
    "name": "Test Item",
    "description": "This is a test item"
  }
  ```
- `PUT /api/v1/supabase/test/{item_id}` - Update a test item
  ```json
  {
    "name": "Updated Test Item",
    "description": "This is an updated test item"
  }
  ```
- `DELETE /api/v1/supabase/test/{item_id}` - Delete a test item

There's also a health check endpoint:
- `GET /api/v1/supabase/health` - Check Supabase connection

## Troubleshooting

If you encounter errors:

1. Verify your environment variables are set correctly
2. Check your Supabase project is active
3. Ensure your table structure matches the expected schema (404 errors typically indicate the table doesn't exist)
4. Check network connectivity to Supabase

### Common Error: "relation \"public.test_items\" does not exist"

This error occurs when the table hasn't been created yet. To fix it:

1. Go to your Supabase dashboard SQL Editor
2. Create a new query with the SQL provided in the setup section
3. Run the query to create the table

### Row Level Security (RLS) Issues

If you're getting 401 or 403 errors, it might be related to Row Level Security:

1. Go to Authentication > Policies in your Supabase dashboard
2. Make sure you have the correct policies for the test_items table
3. The SQL above sets up permissive policies allowing anonymous access for testing

## Extending

To use Supabase in other routers:

```python
from app.routers.multivio.supa_router import SupabaseClient, get_supabase_client

# In your FastAPI endpoint
@router.get("/my-endpoint")
async def my_endpoint(client: SupabaseClient = Depends(get_supabase_client)):
    # Use the client
    data = await client.select("your_table")
    return data
``` 