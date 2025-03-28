# app/lifespan.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .database import database

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def cleanup_expired_logs():
    """Cleanup expired request logs"""
    try:
        query = "DELETE FROM mo_request_log WHERE expires_at < NOW()"
        result = await database.execute(query)
        logger.info(f"Cleaned up expired request logs")
    except Exception as e:
        logger.error(f"Error cleaning up request logs: {str(e)}")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    try:
        # Connect to the database
        await database.connect()
        logger.info("Connected to database")

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

        # Disconnect from the database
        await database.disconnect()
        logger.info("Disconnected from database")
