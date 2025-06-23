#!/usr/bin/env python3
"""
Debug script to test token retrieval directly
"""
import asyncio
import os
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from app.utils.database import get_database
from app.utils.encryption import decrypt_token

async def test_token_retrieval():
    """Test token retrieval for user 5 facebook accounts"""
    try:
        # Get database connection with admin access
        db = get_database(admin_access=True)
        print("✓ Database connection established")
        
        # Query for facebook connections
        user_id = 5
        provider = 'facebook'
        
        response = db.table('social_connections').select('*').eq(
            'user_id', user_id
        ).eq('provider', provider).execute()
        
        print(f"\n📊 Found {len(response.data)} facebook connections for user {user_id}")
        
        for conn in response.data:
            account_id = conn['provider_account_id']
            account_label = conn.get('account_label', 'No label')
            encrypted_token = conn['access_token']
            
            print(f"\n🔍 Testing account: {account_id} ({account_label})")
            print(f"   Encrypted token exists: {bool(encrypted_token)}")
            print(f"   Encrypted token length: {len(encrypted_token) if encrypted_token else 0}")
            
            if encrypted_token:
                try:
                    decrypted_token = decrypt_token(encrypted_token)
                    print(f"   ✓ Decryption successful: {bool(decrypted_token)}")
                    print(f"   ✓ Decrypted token length: {len(decrypted_token) if decrypted_token else 0}")
                    
                    if decrypted_token:
                        # Show first and last few characters for verification
                        if len(decrypted_token) > 10:
                            preview = f"{decrypted_token[:8]}...{decrypted_token[-4:]}"
                        else:
                            preview = decrypted_token[:4] + "..."
                        print(f"   ✓ Token preview: {preview}")
                    else:
                        print("   ❌ Decryption returned None")
                        
                except Exception as e:
                    print(f"   ❌ Decryption failed: {str(e)}")
            else:
                print("   ❌ No encrypted token found")
        
        print(f"\n🧪 Testing platform publisher query...")
        
        # Test the exact query that PlatformPublisher uses
        test_accounts = ['451556294717299', '539614105905675']
        
        for account_id in test_accounts:
            print(f"\n🔍 Testing PlatformPublisher query for account: {account_id}")
            
            response = db.table('social_connections').select('access_token, provider_account_id').eq(
                'user_id', user_id
            ).eq('provider', provider).eq('provider_account_id', str(account_id)).execute()
            
            print(f"   Query result: {len(response.data)} records found")
            if response.data:
                token = response.data[0]['access_token']
                found_id = response.data[0]['provider_account_id'] 
                print(f"   Found account ID: {found_id}")
                print(f"   Token exists: {bool(token)}")
                
                if token:
                    try:
                        decrypted = decrypt_token(token)
                        print(f"   ✓ Token can be decrypted: {bool(decrypted)}")
                    except Exception as e:
                        print(f"   ❌ Decryption error: {str(e)}")
            else:
                print("   ❌ No records found for this account ID")
                
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_token_retrieval())