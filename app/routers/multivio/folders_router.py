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


@router.put("/modify/{folder_id}", response_model=Folder)
async def update_folder(
    folder_id: str,
    folder: FolderUpdate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Update a folder"""
    try:
        # Debug log
        logger.debug(f"Updating folder: {folder_id} with data: {folder}")

        # Verify folder exists and belongs to user
        verify_query = """
        SELECT * FROM mo_folders 
        WHERE id = :folder_id 
        AND created_by = :user_id 
        AND is_deleted = false
        """
        existing_folder = await db.fetch_one(
            query=verify_query,
            values={
                "folder_id": folder_id,
                "user_id": current_user["uid"]
            }
        )
        if not existing_folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        # Verify parent folder if specified
        if folder.parent_id:
            # Prevent setting parent to self
            if str(folder.parent_id) == folder_id:
                raise HTTPException(
                    status_code=400, detail="Folder cannot be its own parent")

            parent_query = """
            SELECT id FROM mo_folders 
            WHERE id = :parent_id 
            AND created_by = :user_id 
            AND is_deleted = false
            """
            parent = await db.fetch_one(
                query=parent_query,
                values={
                    "parent_id": str(folder.parent_id),
                    "user_id": current_user["uid"]
                }
            )
            if not parent:
                raise HTTPException(
                    status_code=404, detail="Parent folder not found")

        # Build update query dynamically based on provided fields
        update_parts = []
        values = {
            "folder_id": folder_id,
            "user_id": current_user["uid"]
        }

        if folder.name is not None:
            update_parts.append("name = :name")
            values["name"] = folder.name

        if folder.parent_id is not None:
            update_parts.append("parent_id = :parent_id")
            values["parent_id"] = str(folder.parent_id)

        update_parts.append("updated_at = CURRENT_TIMESTAMP")

        update_query = f"""
        UPDATE mo_folders 
        SET {', '.join(update_parts)}
        WHERE id = :folder_id 
        AND created_by = :user_id
        AND is_deleted = false
        RETURNING *
        """

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


@router.delete("/upload/{file_id}")
async def delete_file(file_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    try:
        # First check if file exists and belongs to user
        file = await db.fetch_one(
            "SELECT id FROM mo_assets WHERE id = $1 AND created_by = $2 AND is_deleted = false",
            (file_id, current_user["id"])  # Pass parameters as a tuple
        )

        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        # Then update is_deleted
        await db.execute(
            "UPDATE mo_assets SET is_deleted = true WHERE id = $1 AND created_by = $2",
            (file_id, current_user["id"])  # Pass parameters as a tuple
        )

        return {"success": True}
    except Exception as e:
        print(f"Delete error: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete file: {str(e)}")

