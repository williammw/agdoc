from contextlib import asynccontextmanager
from .database import database


@asynccontextmanager
async def app_lifespan(app):
    # Connect to the database or perform other startup tasks
    await database.connect()
    yield
    # Disconnect from the database or clean up other resources
    await database.disconnect()
