#!/usr/bin/env python3
"""
Supabase Database Initialization Script
---------------------------------------

This script reads SQL files and prints them for manual execution in the Supabase SQL Editor.
It can also execute the SQL directly if configured with the right credentials.

Usage:
    python init_db.py [--execute]

Arguments:
    --execute    Execute SQL directly (requires SUPABASE_URL and SUPABASE_KEY env variables)
                 Without this flag, SQL will only be printed for manual execution
"""

import os
import sys
import pathlib
from typing import List, Optional

# Try to import Supabase client
try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# Base directory for SQL files
DB_DIR = pathlib.Path(__file__).parent


def read_sql_file(filename: str) -> str:
    """Read SQL file content"""
    file_path = DB_DIR / filename
    try:
        with open(file_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"SQL file not found: {file_path}")
        return ""
    except Exception as e:
        print(f"Error reading SQL file {file_path}: {e}")
        return ""


def get_migration_files() -> List[str]:
    """Get list of migration files in order"""
    migrations_dir = DB_DIR / "migrations"
    if not migrations_dir.exists():
        print(f"Migrations directory not found: {migrations_dir}")
        return []
    
    try:
        # Get all SQL files and sort them by name
        return sorted([f.name for f in migrations_dir.glob("*.sql")])
    except Exception as e:
        print(f"Error listing migration files: {e}")
        return []


def execute_sql_supabase(sql: str) -> bool:
    """Execute SQL using Supabase client"""
    if not SUPABASE_AVAILABLE:
        print("Supabase client not available. Install with: pip install supabase")
        return False
    
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        return False
    
    try:
        client = create_client(url, key)
        
        # For some versions of Supabase, you might need to use different RPC methods
        # Try different methods that might be available
        try:
            # First try postgrest-js query interface
            client.table('users').select('id').limit(1).execute()
            print("Using postgREST interface")
            
            # Since direct SQL execution is not universally available through the
            # Python client without a custom RPC function, 
            # we'll just print instructions in this case
            print("\nWARNING: Direct SQL execution not available in this client.")
            print("Please execute the following SQL manually in the SQL Editor:")
            print("\n" + sql)
            return False
            
        except Exception:
            # Then try RPC with execute_sql
            try:
                client.rpc('execute_sql', {'sql': sql}).execute()
                print("Successfully executed SQL via execute_sql RPC")
                return True
            except Exception:
                # Finally try execute_sql_query if available
                try:
                    client.rpc('execute_sql_query', {'query': sql}).execute()
                    print("Successfully executed SQL via execute_sql_query RPC")
                    return True
                except Exception as e:
                    print(f"Failed to execute SQL: {e}")
                    return False
                
    except Exception as e:
        print(f"Supabase client error: {e}")
        return False


def print_migration_sql() -> None:
    """Print SQL from migration files for manual execution"""
    migration_files = get_migration_files()
    
    if not migration_files:
        print("No migration files found. Using individual schema files.")
        users_sql = read_sql_file('users.sql')
        user_info_sql = read_sql_file('user_info.sql')
        schema_sql = read_sql_file('schema.sql')
        
        print("\n===== DATABASE INITIALIZATION INSTRUCTIONS =====")
        print("Please execute the following SQL in the Supabase SQL Editor:")
        
        print("\n1. Create schema utilities:")
        if schema_sql:
            print(schema_sql)
        
        print("\n2. Create the users table:")
        if users_sql:
            print(users_sql)
        
        print("\n3. Create the user_info table:")
        if user_info_sql:
            print(user_info_sql)
    else:
        print(f"Found {len(migration_files)} migration files.")
        print("\n===== DATABASE INITIALIZATION INSTRUCTIONS =====")
        print("Please execute the following SQL in the Supabase SQL Editor:")
        
        for i, file in enumerate(migration_files, 1):
            sql = read_sql_file(f"migrations/{file}")
            if sql:
                print(f"\n{i}. Execute migration {file}:")
                print(sql)
    
    print("\n===== END DATABASE INITIALIZATION INSTRUCTIONS =====")


def execute_migrations() -> bool:
    """Execute all migrations using Supabase client"""
    if not SUPABASE_AVAILABLE:
        print("Supabase client not available. Install with: pip install supabase")
        return False
    
    migration_files = get_migration_files()
    
    if not migration_files:
        print("No migration files found. Using individual schema files.")
        users_sql = read_sql_file('users.sql')
        user_info_sql = read_sql_file('user_info.sql')
        schema_sql = read_sql_file('schema.sql')
        
        success = True
        
        if schema_sql:
            print("\nExecuting schema utilities...")
            if not execute_sql_supabase(schema_sql):
                success = False
        
        if users_sql:
            print("\nExecuting users table creation...")
            if not execute_sql_supabase(users_sql):
                success = False
        
        if user_info_sql:
            print("\nExecuting user_info table creation...")
            if not execute_sql_supabase(user_info_sql):
                success = False
        
        return success
    else:
        print(f"Found {len(migration_files)} migration files.")
        success = True
        
        for file in migration_files:
            sql = read_sql_file(f"migrations/{file}")
            if sql:
                print(f"\nExecuting migration {file}...")
                if not execute_sql_supabase(sql):
                    success = False
        
        return success


if __name__ == "__main__":
    execute_mode = "--execute" in sys.argv
    
    if execute_mode:
        print("Running in execute mode. Will attempt to run SQL directly.")
        if execute_migrations():
            print("\nDatabase initialization complete.")
        else:
            print("\nFailed to initialize database. Check the logs above.")
            sys.exit(1)
    else:
        print_migration_sql()
        print("\nTo execute SQL directly, run: python init_db.py --execute") 