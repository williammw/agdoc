from fastapi import APIRouter, Depends, HTTPException
from typing import Dict
from databases import Database
import logging
import json  # Add this import
import datetime
from app.dependencies import get_current_user, get_database

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/users")
async def create_or_update_user(    
    user_data: dict,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Create or update a user profile when they sign in via Firebase"""
    try:
        # Validate required fields
        required_fields = ['id', 'email']
        for field in required_fields:
            if not user_data.get(field):
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required field: {field}"
                )

        # Ensure the Firebase UID matches the token
        if user_data['id'] != current_user['uid']:
            raise HTTPException(
                status_code=403,
                detail="User ID mismatch"
            )

        # Check if user exists
        query = "SELECT id FROM mo_user_info WHERE id = :user_id"
        exists = await db.fetch_one(query=query, values={"user_id": user_data['id']})

        if exists:
            # Update existing user
            update_query = """
            UPDATE mo_user_info 
            SET 
                email = :email,
                username = :username,
                full_name = :full_name,
                updated_at = CURRENT_TIMESTAMP,
                last_login_at = CURRENT_TIMESTAMP
            WHERE id = :id
            RETURNING *
            """
        else:
            # Create new user
            update_query = """
            INSERT INTO mo_user_info (
                id,
                email,
                username,
                full_name,
                plan_type,
                monthly_post_quota,
                remaining_posts,
                language_preference,
                timezone,
                notification_preferences,
                is_active,
                is_verified,
                created_at,
                updated_at,
                last_login_at
            ) VALUES (
                :id,
                :email,
                :username,
                :full_name,
                'free',
                50,
                50,
                'en',
                'UTC',
                :notification_preferences,
                true,
                true,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            RETURNING *
            """

        # Serialize the notification_preferences to a JSON string
        default_notifications = {"email": True, "push": True}
        
        values = {
            "id": user_data['id'],
            "email": user_data.get('email', ''),
            "username": user_data.get('username') or user_data['email'].split('@')[0],
            "full_name": user_data.get('full_name', ''),
            "notification_preferences": json.dumps(default_notifications)  # Convert dict to JSON string
        }

        try:
            result = await db.fetch_one(update_query, values)
            if not result:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to create/update user record"
                )
            
            # Convert the result to a dict and parse the notification_preferences back to dict
            result_dict = dict(result)
            if isinstance(result_dict.get('notification_preferences'), str):
                result_dict['notification_preferences'] = json.loads(result_dict['notification_preferences'])
            
            return result_dict

        except Exception as db_error:
            logger.error(f"Database error: {str(db_error)}")
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {str(db_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_or_update_user: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )