# lifespan.py
from contextlib import asynccontextmanager
from .database import database

@asynccontextmanager
async def app_lifespan(app):
    try:
        await database.connect()
        yield
    finally:
        await database.disconnect()
