# app/utils/idempotency.py
import json
import logging
from typing import Optional, Callable, Any
from databases import Database
from fastapi import Header, Depends
from functools import wraps

from ..dependencies import get_database

logger = logging.getLogger(__name__)


async def process_with_idempotency(
    idempotency_key: Optional[str],
    endpoint: str,
    request_data: dict,
    db: Database,
    processing_func: Callable
) -> Any:
    """
    Process a request with idempotency support
    
    Args:
        idempotency_key: A unique key for this request
        endpoint: API endpoint being called
        request_data: Request data for logging
        db: Database connection
        processing_func: Async function that processes the request
        
    Returns:
        The result of processing_func or the cached result
    """
    if not idempotency_key:
        return await processing_func()

    # Check for existing result
    query = """
    SELECT result FROM mo_request_log
    WHERE idempotency_key = :key AND endpoint = :endpoint
    """
    existing = await db.fetch_one(
        query=query,
        values={"key": idempotency_key, "endpoint": endpoint}
    )

    if existing and existing["result"]:
        logger.info(
            f"Using cached result for idempotency key {idempotency_key}")
        return json.loads(existing["result"])

    # Process the request
    result = await processing_func()

    # Store the result
    store_query = """
    INSERT INTO mo_request_log (idempotency_key, endpoint, request_data, result)
    VALUES (:key, :endpoint, :request_data, :result)
    ON CONFLICT (idempotency_key) 
    DO UPDATE SET result = :result, request_data = :request_data
    """
    await db.execute(
        query=store_query,
        values={
            "key": idempotency_key,
            "endpoint": endpoint,
            "request_data": json.dumps(request_data),
            "result": json.dumps(result)
        }
    )

    return result


def idempotent(endpoint_name: str):
    """
    Decorator for FastAPI endpoints to make them idempotent
    
    Args:
        endpoint_name: A name for this endpoint
    
    Usage:
        @router.post("/my-endpoint")
        @idempotent("my-endpoint")
        async def my_endpoint(
            request: MyModel,
            idempotency_key: Optional[str] = Header(None),
            db: Database = Depends(get_database)
        ):
            # Your endpoint logic here
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract idempotency_key and db from kwargs
            idempotency_key = kwargs.get('idempotency_key')
            db = kwargs.get('db')

            # Get the request data by finding the Pydantic model
            request_data = {}
            for arg in args:
                if hasattr(arg, 'dict'):
                    request_data = arg.dict()
                    break

            for value in kwargs.values():
                if hasattr(value, 'dict'):
                    request_data = value.dict()
                    break

            async def process():
                return await func(*args, **kwargs)

            return await process_with_idempotency(
                idempotency_key,
                endpoint_name,
                request_data,
                db,
                process
            )
        return wrapper
    return decorator
