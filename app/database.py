# database.py
from databases import Database
import os
from dotenv import load_dotenv
from fastapi import FastAPI
# Your database and router imports re
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
database = Database(DATABASE_URL)

