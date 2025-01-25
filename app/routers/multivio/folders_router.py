from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
import logging
from app.dependencies import get_current_user, get_database
from databases import Database

logger = logging.getLogger(__name__)

# Models
class FolderBase(BaseModel):
    name: str
    parent_id: Optional[str] = None

class FolderCreate(FolderBase):
    pass

class FolderUpdate(FolderBase):
    name: Optional[str] = None
    parent_id: Optional[UUID] = None

class FolderPosition(BaseModel):
    id: str
    position: int

class FolderPositionUpdate(BaseModel):
    positions: List[FolderPosition]

class Folder(FolderBase):
    id: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    position: int = 0
    is_deleted: bool = False

router = APIRouter()

@router.get("", response_model=List[Folder])
async def get_folders(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get all folders for the current user"""
    try:
        query = """
        SELECT 
            f.*,
            COUNT(a.id) as file_count
        FROM mo_folders f
        LEFT JOIN mo_assets a ON a.folder_id = f.id AND a.is_deleted = false
        WHERE f.created_by = :user_id 
        AND f.is_deleted = false
        GROUP BY f.id
        ORDER BY f.position ASC, f.created_at DESC
        """

        folders = await db.fetch_all(
            query=query,
            values={"user_id": current_user["uid"]}
        )

        return [dict(folder) for folder in folders]

    except Exception as e:
        logger.error(f"Error in get_folders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/positions")
async def update_folder_positions(
    positions: FolderPositionUpdate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Update multiple folder positions"""
    try:
        # Verify all folders exist and belong to user
        folder_ids = [p.id for p in positions.positions]
        verify_query = """
        SELECT id FROM mo_folders 
        WHERE id = ANY(:folder_ids)
        AND created_by = :user_id 
        AND is_deleted = false
        """
        existing_folders = await db.fetch_all(
            query=verify_query,
            values={
                "folder_ids": folder_ids,
                "user_id": current_user["uid"]
            }
        )
        
        if len(existing_folders) != len(folder_ids):
            raise HTTPException(status_code=404, detail="One or more folders not found")

        # Update positions using a transaction
        async with db.transaction():
            for position in positions.positions:
                update_query = """
                UPDATE mo_folders 
                SET 
                    position = :position,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :folder_id 
                AND created_by = :user_id
                AND is_deleted = false
                """
                
                await db.execute(
                    update_query,
                    values={
                        "position": position.position,
                        "folder_id": position.id,
                        "user_id": current_user["uid"]
                    }
                )

        return {"success": True}

    except Exception as e:
        logger.error(f"Error in update_folder_positions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/folders/{folder_id}", response_model=Folder)
async def get_folder(
    folder_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get a specific folder"""
    try:
        query = """
        SELECT 
            f.*,
            COUNT(a.id) as file_count
        FROM mo_folders f
        LEFT JOIN mo_assets a ON a.folder_id = f.id AND a.is_deleted = false
        WHERE f.id = :folder_id 
        AND f.created_by = :user_id 
        AND f.is_deleted = false
        GROUP BY f.id
        """

        folder = await db.fetch_one(
            query=query,
            values={
                "folder_id": folder_id,
                "user_id": current_user["uid"]
            }
        )

        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        return dict(folder)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_folder: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
async def create_folder(
    folder: FolderCreate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Create a new folder"""
    try:
        # Get highest position
        max_position_query = """
        SELECT COALESCE(MAX(position), -1) as max_position
        FROM mo_folders
        WHERE created_by = :user_id
        AND is_deleted = false
        """
        result = await db.fetch_one(
            query=max_position_query,
            values={"user_id": current_user["uid"]}
        )
        next_position = result['max_position'] + 1

        # Validate parent folder exists if specified
        if folder.parent_id:
            parent_query = """
            SELECT id FROM mo_folders 
            WHERE id = :parent_id 
            AND created_by = :user_id 
            AND is_deleted = false
            """
            parent = await db.fetch_one(
                query=parent_query,
                values={
                    "parent_id": folder.parent_id,
                    "user_id": current_user["uid"]
                }
            )
            if not parent:
                raise HTTPException(
                    status_code=404, detail="Parent folder not found")

        # Insert new folder with generated UUID
        query = """
        INSERT INTO mo_folders (
            id,
            name,
            parent_id,
            created_by,
            created_at,
            updated_at,
            position,
            is_deleted
        ) VALUES (
            gen_random_uuid(),
            :name,
            :parent_id,
            :user_id,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            :position,
            false
        ) RETURNING *
        """

        values = {
            "name": folder.name,
            "parent_id": folder.parent_id,
            "user_id": current_user["uid"],
            "position": next_position
        }

        result = await db.fetch_one(query=query, values=values)

        return {
            "id": result["id"],
            "name": result["name"],
            "parentId": result["parent_id"],
            "position": result["position"],
            "createdBy": result["created_by"],
            "createdAt": result["created_at"],
            "updatedAt": result["updated_at"]
        }

    except Exception as e:
        logger.error(f"Error in create_folder: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/folders/{folder_id}", response_model=Folder)
async def update_folder(
    folder_id: UUID,
    folder: FolderUpdate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Update a folder"""
    try:
        # Verify folder exists and belongs to user
        verify_query = """
        SELECT id FROM mo_folders 
        WHERE id = :folder_id 
        AND created_by = :user_id 
        AND is_deleted = false
        """
        exists = await db.fetch_one(
            query=verify_query,
            values={
                "folder_id": folder_id,
                "user_id": current_user["uid"]
            }
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Folder not found")

        # Verify parent folder if specified
        if folder.parent_id:
            parent_query = """
            SELECT id FROM mo_folders 
            WHERE id = :parent_id 
            AND created_by = :user_id 
            AND is_deleted = false
            """
            parent = await db.fetch_one(
                query=parent_query,
                values={
                    "parent_id": folder.parent_id,
                    "user_id": current_user["uid"]
                }
            )
            if not parent:
                raise HTTPException(
                    status_code=404, detail="Parent folder not found")

        # Update the folder
        update_query = """
        UPDATE mo_folders 
        SET 
            name = COALESCE(:name, name),
            parent_id = COALESCE(:parent_id, parent_id),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :folder_id 
        AND created_by = :user_id
        AND is_deleted = false
        RETURNING *
        """

        values = {
            "folder_id": folder_id,
            "user_id": current_user["uid"],
            "name": folder.name,
            "parent_id": folder.parent_id
        }

        result = await db.fetch_one(update_query, values)
        if not result:
            raise HTTPException(status_code=404, detail="Folder not found")

        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_folder: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Soft delete a folder"""
    try:
        # Verify folder exists and belongs to user
        verify_query = """
        SELECT id FROM mo_folders 
        WHERE id = :folder_id 
        AND created_by = :user_id 
        AND is_deleted = false
        """
        exists = await db.fetch_one(
            query=verify_query,
            values={
                "folder_id": folder_id,
                "user_id": current_user["uid"]
            }
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Folder not found")

        # Soft delete the folder
        delete_query = """
        UPDATE mo_folders 
        SET 
            is_deleted = true,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :folder_id 
        AND created_by = :user_id
        AND is_deleted = false
        """

        await db.execute(
            delete_query,
            values={
                "folder_id": folder_id,
                "user_id": current_user["uid"]
            }
        )

        return {"success": True}

    except Exception as e:
        logger.error(f"Error in delete_folder: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
