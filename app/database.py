from databases import Database
import os

from fastapi import FastAPI
# Your database and router imports re

DATABASE_URL = os.getenv('DATABASE_URL')
database = Database(DATABASE_URL)

