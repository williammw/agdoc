import os
import pathlib
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

# Get Supabase configuration from environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Base directory for SQL files
DB_DIR = pathlib.Path(__file__).parent.parent / "db"

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Supabase client initialized successfully")
except Exception as e:
    print(f"Failed to initialize Supabase client: {e}")
    supabase = None

# Database dependency for FastAPI
async def get_database():
    """Get a Supabase client instance"""
    if not supabase:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection error: Supabase client not initialized"
        )
    return supabase

# User database operations
async def get_user_by_firebase_uid(client, firebase_uid: str) -> Optional[Dict[str, Any]]:
    """Get user by Firebase UID"""
    try:
        response = client.table('users').select('*').eq('firebase_uid', firebase_uid).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching user by firebase_uid: {e}")
        return None

async def get_user_by_email(client, email: str) -> Optional[Dict[str, Any]]:
    """Get user by email"""
    try:
        response = client.table('users').select('*').eq('email', email).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching user by email: {e}")
        return None

async def create_user(client, user_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new user in the database"""
    try:
        # Set default username if not provided
        if 'username' not in user_data or not user_data['username']:
            user_data['username'] = user_data.get('email', '').split('@')[0]
        
        # Insert user data
        response = client.table('users').insert(
            {
                'firebase_uid': user_data.get('firebase_uid'),
                'email': user_data.get('email'),
                'username': user_data.get('username'),
                'full_name': user_data.get('full_name'),
                'avatar_url': user_data.get('avatar_url'),
                'email_verified': user_data.get('email_verified', False),
                'auth_provider': user_data.get('auth_provider', 'email'),
                'is_active': user_data.get('is_active', True)
            }
        ).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error creating user: {e}")
        return None

async def update_user(client, user_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update user data"""
    try:
        # Filter out None values
        update_data = {k: v for k, v in updates.items() if v is not None}
        
        if not update_data:
            return None  # No updates to perform
        
        response = client.table('users').update(update_data).eq('id', user_id).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error updating user: {e}")
        return None

async def update_user_by_firebase_uid(client, firebase_uid: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update user data by Firebase UID"""
    try:
        # Filter out None values
        update_data = {k: v for k, v in updates.items() if v is not None}
        
        if not update_data:
            return None  # No updates to perform
        
        response = client.table('users').update(update_data).eq('firebase_uid', firebase_uid).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error updating user by firebase_uid: {e}")
        return None

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

# Function to initialize the database tables if they don't exist
async def initialize_database():
    """Initialize database tables using the Supabase SQL editor or manual execution"""
    if not supabase:
        print("Cannot initialize database: Supabase client not initialized")
        return
        
    try:
        # Check if the users table exists first
        try:
            # Just trying to select from users table to see if it exists
            test_response = supabase.table('users').select('id').limit(1).execute()
            print("Users table already exists")
            
            # If we got here, the table exists, so we can return
            return
        except Exception as e:
            # Table might not exist, or other error
            print(f"Users table check result: {e}")
            print("Proceeding with table creation...")
        
        # Read the SQL initialization files
        initial_migration_sql = read_sql_file('migrations/001_initial_schema.sql')
        users_sql = read_sql_file('users.sql')
        user_info_sql = read_sql_file('user_info.sql')
        
        # Print the instructions for manual SQL execution
        print("\n===== DATABASE INITIALIZATION INSTRUCTIONS =====")
        print("Please execute the following SQL in the Supabase SQL Editor:")
        print("\n1. Create the initial schema:")
        if initial_migration_sql:
            print(initial_migration_sql)
        else:
            print("\n2. Create the users table:")
            if users_sql:
                print(users_sql)
            
            print("\n3. Create the user_info table:")
            if user_info_sql:
                print(user_info_sql)
                
        print("\n===== END DATABASE INITIALIZATION INSTRUCTIONS =====")
        print("\nAfter executing these SQL statements, restart the application.")
        
    except Exception as e:
        print(f"Database initialization error: {e}")
        print("Please manually initialize the database using the SQL files in app/db/ directory") 