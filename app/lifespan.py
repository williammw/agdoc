# app/lifespan.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .database import database, supabase
import traceback

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def cleanup_expired_logs():
    """Cleanup expired request logs"""
    try:
        # Use our database adapter to execute SQL
        cleanup_query = """
        DELETE FROM mo_request_logs
        WHERE created_at < NOW() - INTERVAL '30 days'
        """
        
        result = await database.execute(cleanup_query)
        logger.info(f"Cleaned up expired request logs")
    except Exception as e:
        logger.error(f"Error cleaning up request logs: {str(e)}")
        logger.error(traceback.format_exc())


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    try:
        # Log that Supabase client is ready
        logger.info("Supabase client initialized")

        # Test database connection using our adapter's check method
        connection_ok = await database.check_connection()
        if connection_ok:
            logger.info("✅ Database connection verified successfully")
        else:
            logger.warning("⚠️ Database connection test failed")
            
            # Try a basic table query as fallback
            try:
                # Try a basic query to check connection
                # Note: Using 'id' instead of 'count(*)' which isn't supported in the select method
                response = supabase.table('mo_user_info').select('id').limit(1).execute()
                if hasattr(response, 'data'):
                    logger.info(f"✅ Successfully connected to database")
                else:
                    logger.error(f"❌ Database table query failed")
            except Exception as e:
                logger.error(f"❌ Fatal database connection error: {str(e)}")
                logger.error(traceback.format_exc())

        # Start the scheduler
        scheduler.add_job(
            cleanup_expired_logs,
            'interval',
            hours=1,
            id='cleanup_request_logs'
        )
        scheduler.start()
        logger.info("Started scheduler for request log cleanup")

        # Yield control back to the app
        yield
    finally:
        # Shutdown the scheduler
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Shutdown scheduler")

        # No disconnection needed for Supabase client
        logger.info("Application shutdown complete")
