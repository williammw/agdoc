#!/usr/bin/env python3
"""
Migration script to update existing social connections for multi-account support

This script:
1. Updates existing connections to set is_primary=true
2. Sets appropriate account labels based on metadata
3. Sets account types based on provider
"""

import os
import sys
from datetime import datetime
import json

# Add parent directory to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.database import get_db


def migrate_existing_connections():
    """
    Migrate existing social connections to multi-account format
    """
    # Get database connection
    db = get_db(admin_access=True)()
    
    try:
        # Get all existing connections
        response = db.table('social_connections').select('*').execute()
        connections = response.data if response.data else []
        
        print(f"Found {len(connections)} existing connections to migrate")
        
        for conn in connections:
            try:
                # Prepare update data
                update_data = {}
                
                # Set is_primary to true for all existing connections
                # (they were the only ones before multi-account support)
                if conn.get('is_primary') is None:
                    update_data['is_primary'] = True
                
                # Extract account label from metadata
                metadata = conn.get('metadata', {})
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}
                
                if not conn.get('account_label'):
                    # Try to extract a meaningful label
                    account_label = None
                    
                    if metadata:
                        # Check various metadata structures
                        account_label = (
                            metadata.get('name') or 
                            metadata.get('username') or
                            metadata.get('profile', {}).get('name') or
                            metadata.get('profile', {}).get('username')
                        )
                    
                    if not account_label:
                        # Fall back to provider name
                        account_label = f"{conn['provider'].capitalize()} Account"
                    
                    update_data['account_label'] = account_label
                
                # Set account type based on provider
                if not conn.get('account_type'):
                    provider = conn['provider']
                    if provider == 'instagram':
                        update_data['account_type'] = 'business'
                    elif provider == 'youtube':
                        update_data['account_type'] = 'channel'
                    elif provider == 'facebook' and metadata.get('pages'):
                        # If there are pages, this might be a business account
                        update_data['account_type'] = 'business'
                    else:
                        update_data['account_type'] = 'personal'
                
                # Only update if there are changes
                if update_data:
                    update_data['updated_at'] = datetime.utcnow().isoformat()
                    
                    result = db.table('social_connections').update(update_data).eq('id', conn['id']).execute()
                    
                    print(f"✓ Updated {conn['provider']} connection for user {conn['user_id']}: {update_data}")
                else:
                    print(f"- Skipped {conn['provider']} connection for user {conn['user_id']} (already migrated)")
                    
            except Exception as e:
                print(f"✗ Error migrating connection {conn['id']}: {e}")
                continue
        
        print(f"\nMigration completed successfully!")
        
        # Print summary
        summary_response = db.table('social_connections').select('provider, count').execute()
        if summary_response.data:
            print("\nConnection Summary:")
            for provider_data in summary_response.data:
                print(f"  {provider_data['provider']}: {provider_data['count']} connections")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        raise
    finally:
        # Note: Supabase client doesn't need explicit close
        pass


def verify_migration():
    """
    Verify that the migration was successful
    """
    db = get_db(admin_access=True)()
    
    try:
        # Check for connections without is_primary set
        response = db.table('social_connections').select('count').is_('is_primary', 'null').execute()
        if response.data and response.data[0]['count'] > 0:
            print(f"⚠️  Warning: Found {response.data[0]['count']} connections without is_primary set")
        
        # Check for connections without account_label
        response = db.table('social_connections').select('count').is_('account_label', 'null').execute()
        if response.data and response.data[0]['count'] > 0:
            print(f"⚠️  Warning: Found {response.data[0]['count']} connections without account_label")
        
        # Check for connections without account_type
        response = db.table('social_connections').select('count').is_('account_type', 'null').execute()
        if response.data and response.data[0]['count'] > 0:
            print(f"⚠️  Warning: Found {response.data[0]['count']} connections without account_type")
        
        print("\n✓ Migration verification complete")
        
    except Exception as e:
        print(f"Verification failed: {e}")


if __name__ == "__main__":
    print("Starting multi-account migration...")
    print("=" * 50)
    
    migrate_existing_connections()
    
    print("\nVerifying migration...")
    print("=" * 50)
    
    verify_migration()
    
    print("\nDone!")