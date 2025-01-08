from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Optional
from databases import Database
import logging
import json
from datetime import datetime
from app.dependencies import get_current_user, get_database
from pydantic import BaseModel, EmailStr
from typing import Dict, Optional

class UserCreate(BaseModel):
    id: str
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    timezone: Optional[str] = None
    notification_preferences: Optional[Dict] = None

class NotificationPreferences(BaseModel):
    email: bool = True
    push: bool = True

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get user profile by ID"""
    try:
        if user_id != current_user['uid']:
            raise HTTPException(status_code=403, detail="Access denied")

        query = """
        SELECT 
            id,
            email,
            username,
            full_name,
            phone_number,
            plan_type,
            monthly_post_quota,
            remaining_posts,
            timezone,
            notification_preferences,
            api_key,
            plan_valid_until,
            is_active,
            is_verified,
            created_at,
            updated_at,
            last_login_at
        FROM mo_user_info 
        WHERE id = :user_id
        """
        
        result = await db.fetch_one(query=query, values={"user_id": user_id})
        
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
            
        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users")
async def create_or_update_user(
    user_data: UserCreate,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Create or update a user profile when they sign in via Firebase"""
    try:
        if user_data.id != current_user['uid']:
            raise HTTPException(status_code=403, detail="User ID mismatch")

        # Check if user exists
        query = "SELECT id FROM mo_user_info WHERE id = :user_id"
        exists = await db.fetch_one(query=query, values={"user_id": user_data.id})

        if exists:
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
            update_query = """
            INSERT INTO mo_user_info (
                id,
                email,
                username,
                full_name,
                phone_number,
                plan_type,
                monthly_post_quota,
                remaining_posts,
                timezone,
                notification_preferences,
                language_preference,
                api_key,
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
                NULL,
                'free',
                50,
                50,
                'UTC',
                :notification_preferences,
                'en',
                NULL,
                true,
                true,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            RETURNING *
            """

        values = {
            "id": user_data.id,
            "email": user_data.email,
            "username": user_data.username or user_data.email.split('@')[0],
            "full_name": user_data.full_name or "",
            "notification_preferences": json.dumps({
                "email": True,
                "push": True
            })
        }

        result = await db.fetch_one(update_query, values)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to create/update user record")
        
        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_or_update_user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Update an existing user profile"""
    try:
        if user_id != current_user['uid']:
            raise HTTPException(status_code=403, detail="Access denied")

        update_query = """
        UPDATE mo_user_info 
        SET 
            email = COALESCE(:email, email),
            username = COALESCE(:username, username),
            full_name = COALESCE(:full_name, full_name),
            phone_number = COALESCE(:phone_number, phone_number),
            timezone = COALESCE(:timezone, timezone),
            notification_preferences = COALESCE(:notification_preferences, notification_preferences),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
        RETURNING *
        """

        values = {
            "id": user_id,
            "email": user_data.email,
            "username": user_data.username,
            "full_name": user_data.full_name,
            "phone_number": user_data.phone_number,
            "timezone": user_data.timezone,
            "notification_preferences": json.dumps(user_data.notification_preferences) if user_data.notification_preferences else None
        }

        result = await db.fetch_one(update_query, values)
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
        
        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/{user_id}/api-key")
async def generate_api_key(
    user_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Generate a new API key for the user"""
    try:
        if user_id != current_user['uid']:
            raise HTTPException(status_code=403, detail="Access denied")

        # Generate a new API key (you might want to use a more secure method)
        import secrets
        new_api_key = secrets.token_urlsafe(32)

        update_query = """
        UPDATE mo_user_info 
        SET 
            api_key = :api_key,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
        RETURNING *
        """

        result = await db.fetch_one(update_query, {"id": user_id, "api_key": new_api_key})
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
        
        return dict(result)

    except Exception as e:
        logger.error(f"Error generating API key: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/users/{user_id}/api-key")
async def revoke_api_key(
    user_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Revoke the user's API key"""
    try:
        if user_id != current_user['uid']:
            raise HTTPException(status_code=403, detail="Access denied")

        update_query = """
        UPDATE mo_user_info 
        SET 
            api_key = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
        RETURNING *
        """

        result = await db.fetch_one(update_query, {"id": user_id})
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
        
        return dict(result)

    except Exception as e:
        logger.error(f"Error revoking API key: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/quota")
async def get_user_quota(
    user_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get user's quota information"""
    try:
        if user_id != current_user['uid']:
            raise HTTPException(status_code=403, detail="Access denied")

        query = """
        SELECT 
            monthly_post_quota,
            remaining_posts,
            quota_reset_date
        FROM mo_user_info 
        WHERE id = :user_id
        """
        
        result = await db.fetch_one(query=query, values={"user_id": user_id})
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
            
        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_user_quota: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))