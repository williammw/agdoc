
# fix_conversations.py
import os
import asyncio
from databases import Database
from dotenv import load_dotenv
import uuid

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

async def fix_database():
    # Connect to the database
    db = Database(DATABASE_URL)
    await db.connect()
    
    try:
        # 1. First check for missing content entries
        orphaned_query = """
        SELECT c.id, c.chat_id, c.user_id 
        FROM mo_llm_conversations c
        LEFT JOIN mo_chat m ON c.chat_id = m.uuid
        WHERE m.uuid IS NULL AND c.chat_id IS NOT NULL
        """
        orphaned = await db.fetch_all(orphaned_query)
        
        if orphaned:
            print(f"Found {len(orphaned)} orphaned conversations. Creating missing content entries...")
            
            for row in orphaned:
                chat_id = row['chat_id']
                user_id = row['user_id']
                
                # Create a new content entry for this orphaned conversation
                try:
                    # First check if a content with this UUID already exists
                    check_query = "SELECT uuid FROM mo_chat WHERE uuid = :uuid"
                    existing = await db.fetch_one(check_query, {"uuid": chat_id})
                    
                    if not existing:
                        # Content doesn't exist, create it
                        insert_query = """
                        INSERT INTO mo_chat 
                        (uuid, firebase_uid, name, description, route, status) 
                        VALUES 
                        (:uuid, :firebase_uid, :name, :description, :route, 'draft')
                        RETURNING uuid
                        """
                        
                        values = {
                            "uuid": chat_id,
                            "firebase_uid": user_id,
                            "name": f"Recovered Content {chat_id[:8]}",
                            "description": "Automatically recovered content for orphaned conversation",
                            "route": f"recovered-{uuid.uuid4().hex[:8]}"  # Generate unique route
                        }
                        
                        result = await db.fetch_one(insert_query, values)
                        print(f"  Created content entry: {result['uuid']} for conversation {row['id']}")
                    else:
                        print(f"  Content {chat_id} already exists")
                        
                except Exception as e:
                    print(f"  Error creating content for {chat_id}: {str(e)}")
        else:
            print("No orphaned conversations found.")
            
        # 2. Fix any null chat_id values
        null_query = """
        SELECT COUNT(*) FROM mo_llm_conversations 
        WHERE chat_id IS NULL
        """
        null_count = await db.fetch_one(null_query)
        
        if null_count[0] > 0:
            print(f"\nFound {null_count[0]} conversations with NULL chat_id")
            
            # Option to fix these by creating content entries for them
            print("To fix these, run the script with the --fix-null flag")
        
        print("\nDatabase check completed")
        
    finally:
        await db.disconnect()

if __name__ == "__main__":
    asyncio.run(fix_database())
