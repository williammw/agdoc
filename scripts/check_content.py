
# check_content.py
import os
import asyncio
from databases import Database
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

async def check_database():
    # Connect to the database
    db = Database(DATABASE_URL)
    await db.connect()
    
    try:
        # Check content entries
        content_query = "SELECT COUNT(*) FROM mo_content"
        content_count = await db.fetch_one(content_query)
        print(f"Total content entries: {content_count[0]}")
        
        # Check conversation entries
        convo_query = "SELECT COUNT(*) FROM mo_llm_conversations"
        convo_count = await db.fetch_one(convo_query)
        print(f"Total conversation entries: {convo_count[0]}")
        
        # Check failing content_ids
        orphaned_query = """
        SELECT c.id, c.content_id, c.user_id 
        FROM mo_llm_conversations c
        LEFT JOIN mo_content m ON c.content_id = m.uuid
        WHERE m.uuid IS NULL AND c.content_id IS NOT NULL
        LIMIT 10
        """
        orphaned = await db.fetch_all(orphaned_query)
        
        if orphaned:
            print("\nFound orphaned conversations (content doesn't exist):")
            for row in orphaned:
                print(f"  Conversation ID: {row['id']}, Content ID: {row['content_id']}, User ID: {row['user_id']}")
        else:
            print("\nNo orphaned conversations found.")
            
        # Check for errors in recent conversations
        error_query = """
        SELECT c.id, c.content_id, c.user_id, c.created_at
        FROM mo_llm_conversations c
        ORDER BY c.created_at DESC
        LIMIT 5
        """
        recent = await db.fetch_all(error_query)
        
        print("\nMost recent conversation attempts:")
        for row in recent:
            print(f"  ID: {row['id']}, Content: {row['content_id']}, User: {row['user_id']}, Created: {row['created_at']}")
        
    finally:
        await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check_database())
