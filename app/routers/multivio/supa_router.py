"""
Supabase Router - Direct CRUD operations for testing Supabase adapter
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
from app.dependencies import get_current_user, get_database, get_supabase_client
import json
import traceback

router = APIRouter()
logger = logging.getLogger(__name__)

# Pydantic models


class NoteBase(BaseModel):
    title: str
    content: Optional[str] = None
    is_pinned: Optional[bool] = False


class NoteCreate(NoteBase):
    pass


class NoteUpdate(NoteBase):
    title: Optional[str] = None

    class Config:
        extra = "ignore"


class NoteResponse(NoteBase):
    id: int
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# Test endpoint to verify Supabase connection


@router.get("/connection-test")
async def test_connection(
    db=Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Test Supabase connection and adapter functionality"""
    try:
        # Test the connection with a simple query
        result = await db.fetch_one("SELECT current_timestamp as time")

        # Get user info to test authentication is working
        user_query = """
        SELECT id, email, username 
        FROM mo_user_info 
        WHERE id = :user_id
        """

        user_info = await db.fetch_one(
            query=user_query,
            values={"user_id": current_user.get('uid', current_user.get('id'))}
        )

        return {
            "status": "success",
            "timestamp": result.get("time") if result else None,
            "user": {
                "id": user_info.get("id") if user_info else None,
                "username": user_info.get("username") if user_info else None
            },
            "adapter_mode": "direct_access" if getattr(db, "use_direct_access", False) else "rpc"
        }
    except Exception as e:
        logger.error(f"Error testing connection: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Connection test failed: {str(e)}")

# CRUD operations for notes


@router.post("/notes", response_model=NoteResponse)
async def create_note(
    note: NoteCreate,
    db=Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Create a new note"""
    try:
        user_id = current_user.get('uid', current_user.get('id'))

        query = """
        INSERT INTO mo_notes (
            user_id, title, content, is_pinned
        ) VALUES (
            :user_id, :title, :content, :is_pinned
        ) RETURNING id, user_id, title, content, is_pinned, created_at, updated_at
        """

        values = {
            "user_id": user_id,
            "title": note.title,
            "content": note.content,
            "is_pinned": note.is_pinned
        }

        result = await db.fetch_one(query=query, values=values)

        if not result:
            raise HTTPException(
                status_code=500, detail="Failed to create note")

        return dict(result)

    except Exception as e:
        logger.error(f"Error creating note: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notes", response_model=List[NoteResponse])
async def list_notes(
    db=Depends(get_database),
    current_user: dict = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100)
):
    """List all notes for the current user"""
    try:
        user_id = current_user.get('uid', current_user.get('id'))

        query = """
        SELECT id, user_id, title, content, is_pinned, created_at, updated_at
        FROM mo_notes
        WHERE user_id = :user_id
        ORDER BY is_pinned DESC, updated_at DESC
        LIMIT :limit OFFSET :skip
        """

        values = {
            "user_id": user_id,
            "limit": limit,
            "skip": skip
        }

        results = await db.fetch_all(query=query, values=values)

        # Also get total count for pagination
        count_query = """
        SELECT COUNT(*) as total
        FROM mo_notes
        WHERE user_id = :user_id
        """

        count_result = await db.fetch_one(query=count_query, values={"user_id": user_id})
        total = count_result.get("total", 0) if count_result else 0

        return [dict(result) for result in results]

    except Exception as e:
        logger.error(f"Error listing notes: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: int,
    db=Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Get a specific note"""
    try:
        user_id = current_user.get('uid', current_user.get('id'))

        query = """
        SELECT id, user_id, title, content, is_pinned, created_at, updated_at
        FROM mo_notes
        WHERE id = :note_id AND user_id = :user_id
        """

        values = {
            "note_id": note_id,
            "user_id": user_id
        }

        result = await db.fetch_one(query=query, values=values)

        if not result:
            raise HTTPException(status_code=404, detail="Note not found")

        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting note: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: int,
    note: NoteUpdate,
    db=Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Update a note"""
    try:
        user_id = current_user.get('uid', current_user.get('id'))

        # First check if the note exists and belongs to the user
        check_query = """
        SELECT id FROM mo_notes
        WHERE id = :note_id AND user_id = :user_id
        """

        exists = await db.fetch_one(
            query=check_query,
            values={"note_id": note_id, "user_id": user_id}
        )

        if not exists:
            raise HTTPException(
                status_code=404, detail="Note not found or you don't have permission to modify it")

        # Build dynamic update query based on provided fields
        update_fields = []
        values = {"note_id": note_id, "user_id": user_id}

        for field, value in note.dict(exclude_unset=True).items():
            if value is not None:
                update_fields.append(f"{field} = :{field}")
                values[field] = value

        # Always update the updated_at timestamp
        update_fields.append("updated_at = CURRENT_TIMESTAMP")

        if not update_fields:
            # Nothing to update, just return the current note
            return await get_note(note_id, db, current_user)

        update_query = f"""
        UPDATE mo_notes
        SET {", ".join(update_fields)}
        WHERE id = :note_id AND user_id = :user_id
        RETURNING id, user_id, title, content, is_pinned, created_at, updated_at
        """

        result = await db.fetch_one(query=update_query, values=values)

        if not result:
            raise HTTPException(
                status_code=500, detail="Failed to update note")

        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating note: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int,
    db=Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Delete a note"""
    try:
        user_id = current_user.get('uid', current_user.get('id'))

        # First check if the note exists and belongs to the user
        check_query = """
        SELECT id FROM mo_notes
        WHERE id = :note_id AND user_id = :user_id
        """

        exists = await db.fetch_one(
            query=check_query,
            values={"note_id": note_id, "user_id": user_id}
        )

        if not exists:
            raise HTTPException(
                status_code=404, detail="Note not found or you don't have permission to delete it")

        delete_query = """
        DELETE FROM mo_notes
        WHERE id = :note_id AND user_id = :user_id
        """

        await db.execute(query=delete_query, values={"note_id": note_id, "user_id": user_id})

        return {"message": "Note deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting note: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# Direct Supabase client testing (for advanced operations)


@router.get("/direct-test")
async def test_direct_supabase(
    supabase=Depends(get_supabase_client),
    current_user: dict = Depends(get_current_user)
):
    """Test direct Supabase client operations"""
    try:
        # Use the raw Supabase client to perform operations
        response = supabase.table('mo_user_info').select(
            'id, username').limit(5).execute()

        return {
            "status": "success",
            "data": response.data if hasattr(response, 'data') else None,
            "user_id": current_user.get('uid', current_user.get('id'))
        }
    except Exception as e:
        logger.error(f"Error in direct Supabase test: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Direct Supabase test failed: {str(e)}")

# Raw SQL test endpoint


@router.post("/execute-sql")
async def execute_sql(
    query: str,
    db=Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Test executing raw SQL (admin only)"""
    try:
        # Security check - only allow certain users to execute raw SQL
        user_id = current_user.get('uid', current_user.get('id'))

        # Check if user is admin
        admin_check_query = """
        SELECT is_admin FROM mo_user_info 
        WHERE id = :user_id AND is_admin = TRUE
        """

        is_admin = await db.fetch_one(
            query=admin_check_query,
            values={"user_id": user_id}
        )

        if not is_admin:
            raise HTTPException(
                status_code=403, detail="Only admin users can execute raw SQL")

        # Security check - only allow SELECT queries
        if not query.strip().upper().startswith('SELECT'):
            raise HTTPException(
                status_code=403, detail="Only SELECT queries are allowed")

        # Execute the query
        results = await db.fetch_all(query=query)

        return [dict(result) for result in results]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing SQL: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
