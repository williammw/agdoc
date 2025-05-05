# database.py
import os
import logging
import traceback
import json
from typing import Dict, Any, List, Optional, AsyncGenerator, Union
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from supabase import create_client, Client
from postgrest.exceptions import APIError

load_dotenv()
logger = logging.getLogger(__name__)

# Get Supabase credentials from environment variables
SUPABASE_URL = os.getenv('VITE_SUPABASE_URL')
# Try to use service role key first, fall back to anon key if not available
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', os.getenv('VITE_SUPABASE_ANON_KEY'))

if not SUPABASE_KEY or not SUPABASE_URL:
    logger.error("Supabase credentials not found. Check your environment variables.")
    raise ValueError("Missing Supabase credentials in environment variables")

if SUPABASE_KEY == os.getenv('VITE_SUPABASE_ANON_KEY'):
    logger.warning("Using ANON key instead of SERVICE ROLE key. Some operations may fail.")

# Create Supabase client
supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

class SupabaseTransaction:
    """A transaction context manager for compatibility"""
    
    def __init__(self, client: Client):
        self.client = client
        self.is_committed = False
        self.is_rolled_back = False
        
    async def __aenter__(self):
        # Begin transaction - currently just a placeholder as Supabase JS client
        # doesn't explicitly support transactions
        logger.info("Starting transaction (simulated)")
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # An exception occurred, rollback
            await self.rollback()
            return False  # Allow exception to propagate
        
        if not self.is_committed and not self.is_rolled_back:
            # Transaction was neither committed nor rolled back
            await self.commit()
        return False
    
    async def commit(self):
        """Commit the transaction"""
        if self.is_committed or self.is_rolled_back:
            raise ValueError("Transaction already committed or rolled back")
        
        logger.info("Committing transaction (simulated)")
        self.is_committed = True
    
    async def rollback(self):
        """Rollback the transaction"""
        if self.is_committed or self.is_rolled_back:
            raise ValueError("Transaction already committed or rolled back")
        
        logger.info("Rolling back transaction (simulated)")
        self.is_rolled_back = True

class SupabaseDatabase:
    """Adapter to make Supabase client compatible with databases package interface"""
    
    def __init__(self, client: Client):
        self.client = client
        self.use_direct_access = False  # Flag to switch between RPC and direct table access
    
    def table(self, table_name: str):
        """Direct access to Supabase table query builder"""
        return self.client.table(table_name)
        
    async def check_connection(self):
        """Check if the database connection is working"""
        try:
            # First try to use RPC
            response = self.client.rpc('check_connection').execute()
            
            # Different error checking - we need to check if data exists
            if hasattr(response, 'data') and response.data:
                self.use_direct_access = False
                return True
                
            # If RPC fails, try direct table access
            logger.warning("RPC check_connection failed, trying direct table access")
            self.use_direct_access = True
            
            # Use a simple query that doesn't require count
            response = self.client.table('mo_user_info').select('id').limit(1).execute()
            return hasattr(response, 'data')
        except Exception as e:
            logger.error(f"Database connection check failed: {str(e)}")
            return False
    
    async def fetch_one(self, query: str, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a SQL query and return a single row"""
        try:
            if self.use_direct_access:
                # Try to parse the query and use direct table access
                return await self._direct_access_fetch_one(query, values)
            
            # Use Supabase RPC to execute a raw query
            response = self.client.rpc(
                'execute_sql_query_single', 
                {'query': self._prepare_query(query, values)}
            ).execute()
            
            # Check for errors by examining the response structure
            if hasattr(response, 'error') and response.error:
                logger.error(f"SQL error in fetch_one: {response.error}")
                # Try fallback if RPC fails
                if not self.use_direct_access:
                    logger.warning("RPC failed, trying direct table access")
                    self.use_direct_access = True
                    return await self._direct_access_fetch_one(query, values)
                raise Exception(f"SQL error: {response.error}")
                
            # Return the first row or None
            if hasattr(response, 'data'):
                if response.data and isinstance(response.data, dict):
                    return response.data
                elif response.data and isinstance(response.data, list) and len(response.data) > 0:
                    return response.data[0]
            return {}
        except Exception as e:
            logger.error(f"Error in fetch_one: {str(e)}")
            logger.error(f"Query: {query}")
            logger.error(f"Values: {values}")
            logger.error(traceback.format_exc())
            raise
    
    async def _direct_access_fetch_one(self, query: str, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Attempt to execute a query using direct table access"""
        # Very simple SQL parser to extract table and conditions for SELECT
        # This is a fallback and only handles simple queries
        try:
            query = query.strip()
            
            # Handle simple SELECT query
            if query.upper().startswith('SELECT '):
                # Try to extract table name
                from_pos = query.upper().find(' FROM ')
                if from_pos > 0:
                    # Extract the table name
                    rest = query[from_pos + 6:].strip()
                    table_end = rest.find(' ')
                    if table_end > 0:
                        table_name = rest[:table_end].strip()
                    else:
                        table_name = rest.strip()
                    
                    # Extract columns
                    columns = query[7:from_pos].strip()
                    if columns == '*':
                        # Select all columns
                        query_builder = self.client.table(table_name).select('*')
                    else:
                        # Select specific columns
                        query_builder = self.client.table(table_name).select(columns)
                    
                    # Extract WHERE conditions if present
                    where_pos = query.upper().find(' WHERE ')
                    if where_pos > 0 and values:
                        # We have WHERE conditions and values
                        # Apply filters based on values
                        for key, value in values.items():
                            query_builder = query_builder.eq(key, value)
                    
                    # Execute query
                    response = query_builder.limit(1).execute()
                    
                    # Return the first row or empty dict
                    if hasattr(response, 'data') and response.data and len(response.data) > 0:
                        return response.data[0]
                    return {}
            
            # For queries we can't parse, return empty result
            logger.warning(f"Unable to parse query for direct access: {query}")
            return {}
        except Exception as e:
            logger.error(f"Error in direct access fetch_one: {str(e)}")
            return {}
    
    async def fetch_all(self, query: str, values: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a SQL query and return all rows"""
        try:
            if self.use_direct_access:
                # Try to parse the query and use direct table access
                return await self._direct_access_fetch_all(query, values)
            
            # Use Supabase RPC to execute a raw query
            response = self.client.rpc(
                'execute_sql_query', 
                {'query': self._prepare_query(query, values)}
            ).execute()
            
            # Check for errors by examining the response structure
            if hasattr(response, 'error') and response.error:
                logger.error(f"SQL error in fetch_all: {response.error}")
                # Try fallback if RPC fails
                if not self.use_direct_access:
                    logger.warning("RPC failed, trying direct table access")
                    self.use_direct_access = True
                    return await self._direct_access_fetch_all(query, values)
                raise Exception(f"SQL error: {response.error}")
                
            # Return all rows or empty list
            if hasattr(response, 'data') and response.data:
                return response.data if isinstance(response.data, list) else [response.data]
            return []
        except Exception as e:
            logger.error(f"Error in fetch_all: {str(e)}")
            logger.error(f"Query: {query}")
            logger.error(f"Values: {values}")
            logger.error(traceback.format_exc())
            raise
    
    async def _direct_access_fetch_all(self, query: str, values: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Attempt to execute a query using direct table access"""
        # Very simple SQL parser to extract table and conditions for SELECT
        # This is a fallback and only handles simple queries
        try:
            query = query.strip()
            
            # Handle simple SELECT query
            if query.upper().startswith('SELECT '):
                # Try to extract table name
                from_pos = query.upper().find(' FROM ')
                if from_pos > 0:
                    # Extract the table name
                    rest = query[from_pos + 6:].strip()
                    table_end = rest.find(' ')
                    if table_end > 0:
                        table_name = rest[:table_end].strip()
                    else:
                        table_name = rest.strip()
                    
                    # Extract columns
                    columns = query[7:from_pos].strip()
                    if columns == '*':
                        # Select all columns
                        query_builder = self.client.table(table_name).select('*')
                    else:
                        # Select specific columns
                        query_builder = self.client.table(table_name).select(columns)
                    
                    # Extract WHERE conditions if present
                    where_pos = query.upper().find(' WHERE ')
                    if where_pos > 0 and values:
                        # We have WHERE conditions and values
                        # Apply filters based on values
                        for key, value in values.items():
                            query_builder = query_builder.eq(key, value)
                    
                    # Execute query
                    response = query_builder.execute()
                    
                    # Return all rows or empty list
                    if hasattr(response, 'data') and response.data:
                        return response.data
                    return []
            
            # For queries we can't parse, return empty result
            logger.warning(f"Unable to parse query for direct access: {query}")
            return []
        except Exception as e:
            logger.error(f"Error in direct access fetch_all: {str(e)}")
            return []
    
    async def execute(self, query: str, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a SQL query and return the result"""
        try:
            if self.use_direct_access:
                # Try to parse the query and use direct table access
                return await self._direct_access_execute(query, values)
            
            # Use Supabase RPC to execute a raw query
            response = self.client.rpc(
                'execute_sql_statement', 
                {'query': self._prepare_query(query, values)}
            ).execute()
            
            # Check for errors by examining the response structure
            if hasattr(response, 'error') and response.error:
                logger.error(f"SQL error in execute: {response.error}")
                # Try fallback if RPC fails
                if not self.use_direct_access:
                    logger.warning("RPC failed, trying direct table access")
                    self.use_direct_access = True
                    return await self._direct_access_execute(query, values)
                raise Exception(f"SQL error: {response.error}")
                
            # Return the result
            if hasattr(response, 'data') and response.data:
                return response.data
            return {}
        except Exception as e:
            logger.error(f"Error in execute: {str(e)}")
            logger.error(f"Query: {query}")
            logger.error(f"Values: {values}")
            logger.error(traceback.format_exc())
            raise
    
    async def _direct_access_execute(self, query: str, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Attempt to execute a query using direct table access"""
        # Very simple SQL parser to handle basic INSERT, UPDATE, DELETE queries
        try:
            query = query.strip()
            
            # Handle INSERT
            if query.upper().startswith('INSERT INTO '):
                # Extract table name
                rest = query[12:].strip()
                table_end = rest.find(' ')
                if table_end > 0:
                    table_name = rest[:table_end].strip()
                else:
                    table_name = rest.strip()
                
                # For INSERT, use values directly
                if values:
                    response = self.client.table(table_name).insert(values).execute()
                    if hasattr(response, 'error') and response.error:
                        logger.error(f"Direct access INSERT error: {response.error}")
                        return {"error": str(response.error)}
                    return {"affected_rows": len(response.data) if hasattr(response, 'data') and response.data else 0}
            
            # Handle UPDATE
            elif query.upper().startswith('UPDATE '):
                # Extract table name
                rest = query[7:].strip()
                table_end = rest.find(' ')
                if table_end > 0:
                    table_name = rest[:table_end].strip()
                else:
                    table_name = rest.strip()
                
                # Extract SET and WHERE parts
                set_pos = query.upper().find(' SET ')
                where_pos = query.upper().find(' WHERE ')
                
                if set_pos > 0 and values:
                    # Extract data to update from values
                    update_data = {}
                    filter_data = {}
                    
                    for key, value in values.items():
                        if where_pos > 0 and key in query[where_pos:]:
                            # This key is used in WHERE clause
                            filter_data[key] = value
                        else:
                            # This key is used in SET clause
                            update_data[key] = value
                    
                    # Build query
                    query_builder = self.client.table(table_name).update(update_data)
                    
                    # Apply filters
                    for key, value in filter_data.items():
                        query_builder = query_builder.eq(key, value)
                    
                    # Execute
                    response = query_builder.execute()
                    
                    if hasattr(response, 'error') and response.error:
                        logger.error(f"Direct access UPDATE error: {response.error}")
                        return {"error": str(response.error)}
                    return {"affected_rows": len(response.data) if hasattr(response, 'data') and response.data else 0}
            
            # Handle DELETE
            elif query.upper().startswith('DELETE FROM '):
                # Extract table name
                rest = query[12:].strip()
                table_end = rest.find(' ')
                if table_end > 0:
                    table_name = rest[:table_end].strip()
                else:
                    table_name = rest.strip()
                
                # Extract WHERE conditions
                where_pos = query.upper().find(' WHERE ')
                
                if where_pos > 0 and values:
                    # Build query
                    query_builder = self.client.table(table_name).delete()
                    
                    # Apply filters
                    for key, value in values.items():
                        query_builder = query_builder.eq(key, value)
                    
                    # Execute
                    response = query_builder.execute()
                    
                    if hasattr(response, 'error') and response.error:
                        logger.error(f"Direct access DELETE error: {response.error}")
                        return {"error": str(response.error)}
                    return {"affected_rows": len(response.data) if hasattr(response, 'data') and response.data else 0}
            
            # For queries we can't parse, return empty result
            logger.warning(f"Unable to parse query for direct access: {query}")
            return {"affected_rows": 0}
        except Exception as e:
            logger.error(f"Error in direct access execute: {str(e)}")
            return {"error": str(e)}
    
    async def transaction(self) -> SupabaseTransaction:
        """Return a transaction context manager"""
        return SupabaseTransaction(self.client)
    
    def _prepare_query(self, query: str, values: Optional[Dict[str, Any]] = None) -> str:
        """
        Replace :param placeholders with PostgreSQL $1, $2, etc. parameters.
        This is necessary because Supabase doesn't support named parameters.
        """
        if not values:
            return query
            
        # Simple implementation - might need to be improved for complex cases
        prepared_query = query
        for i, (key, value) in enumerate(values.items(), start=1):
            placeholder = f":{key}"
            if isinstance(value, str):
                # Escape single quotes in string values
                escaped_value = value.replace("'", "''")
                prepared_query = prepared_query.replace(placeholder, f"'{escaped_value}'")
            elif value is None:
                prepared_query = prepared_query.replace(placeholder, "NULL")
            else:
                prepared_query = prepared_query.replace(placeholder, str(value))
                
        return prepared_query

# Create and export the adapter instance
database = SupabaseDatabase(supabase_client)

# Also export the raw Supabase client for direct access when needed
supabase = supabase_client
