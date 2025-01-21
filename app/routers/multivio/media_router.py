from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict
from pydantic import BaseModel
from datetime import datetime
import logging
from app.dependencies import get_current_user, get_database
from databases import Database

logger = logging.getLogger(__name__)

# Models


class MediaBase(BaseModel):
    name: str
    type: str
    size: Optional[int] = None
    url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    folder_id: Optional[str] = None
    metadata: Optional[Dict] = None


class MediaCreate(MediaBase):
    pass


class MediaUpdate(BaseModel):
    name: Optional[str] = None
    folder_id: Optional[str] = None
    metadata: Optional[Dict] = None


class MediaFile(MediaBase):
    id: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0
    is_deleted: bool = False

    class Config:
        from_attributes = True


router = APIRouter()


@router.get("/files", response_model=dict)
async def get_files(
    folder_id: Optional[str] = None,
    type: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query(
        "created_at", regex="^(name|created_at|date|size|usage)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get files with filtering, sorting and pagination"""
    try:
        # Build base query
        conditions = ["created_by = :user_id", "is_deleted = false"]
        params = {"user_id": current_user["uid"]}

        # Add filters
        if folder_id:
            conditions.append("folder_id = :folder_id")
            params["folder_id"] = folder_id

        if type:
            conditions.append("type = :type")
            params["type"] = type

        if search:
            conditions.append("name ILIKE :search")
            params["search"] = f"%{search}%"

        # Build WHERE clause
        where_clause = " AND ".join(conditions)

        # Map sort fields
        sort_field_map = {
            "name": "name",
            "created_at": "created_at",
            "date": "created_at",
            "size": "size",
            "usage": "usage_count"
        }
        sort_field = sort_field_map.get(sort_by, "created_at")

        # Get total count
        count_query = f"""
        SELECT COUNT(*) as total
        FROM mo_assets
        WHERE {where_clause}
        """
        count = await db.fetch_one(count_query, params)
        total = count["total"] if count else 0

        # Get files with pagination
        query = f"""
        SELECT *
        FROM mo_assets
        WHERE {where_clause}
        ORDER BY {sort_field} {sort_order}
        LIMIT :limit OFFSET :offset
        """

        params["limit"] = limit
        params["offset"] = (page - 1) * limit

        files = await db.fetch_all(query, params)

        return {
            "files": [dict(f) for f in files],
            "total": total
        }

    except Exception as e:
        logger.error(f"Error in get_files: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files/{file_id}", response_model=MediaFile)
async def get_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get a specific file"""
    try:
        query = """
        SELECT * FROM mo_assets
        WHERE id = :file_id 
        AND created_by = :user_id 
        AND is_deleted = false
        """

        file = await db.fetch_one(
            query=query,
            values={
                "file_id": file_id,
                "user_id": current_user["uid"]
            }
        )

        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        return dict(file)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/files/{file_id}", response_model=MediaFile)
async def update_file(
    file_id: str,
    file: MediaUpdate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Update a file"""
    try:
        # Verify file exists and belongs to user
        verify_query = """
        SELECT id FROM mo_assets 
        WHERE id = :file_id 
        AND created_by = :user_id 
        AND is_deleted = false
        """
        exists = await db.fetch_one(
            query=verify_query,
            values={
                "file_id": file_id,
                "user_id": current_user["uid"]
            }
        )
        if not exists:
            raise HTTPException(status_code=404, detail="File not found")

        # Verify folder if specified
        if file.folder_id:
            folder_query = """
            SELECT id FROM mo_folders 
            WHERE id = :folder_id 
            AND created_by = :user_id 
            AND is_deleted = false
            """
            folder = await db.fetch_one(
                query=folder_query,
                values={
                    "folder_id": file.folder_id,
                    "user_id": current_user["uid"]
                }
            )
            if not folder:
                raise HTTPException(status_code=404, detail="Folder not found")

        # Update the file
        update_parts = []
        values = {
            "file_id": file_id,
            "user_id": current_user["uid"]
        }

        if file.name is not None:
            update_parts.append("name = :name")
            values["name"] = file.name

        if file.folder_id is not None:
            update_parts.append("folder_id = :folder_id")
            values["folder_id"] = file.folder_id

        if file.metadata is not None:
            update_parts.append("metadata = :metadata")
            values["metadata"] = file.metadata

        if not update_parts:
            return await get_file(file_id, current_user, db)

        update_parts.append("updated_at = CURRENT_TIMESTAMP")
        update_query = f"""
        UPDATE mo_assets 
        SET {", ".join(update_parts)}
        WHERE id = :file_id 
        AND created_by = :user_id
        AND is_deleted = false
        RETURNING *
        """

        result = await db.fetch_one(update_query, values)
        if not result:
            raise HTTPException(status_code=404, detail="File not found")

        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/files")
async def delete_files(
    file_ids: List[str],
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Soft delete multiple files"""
    try:
        # Verify files exist and belong to user
        verify_query = """
        SELECT id FROM mo_assets
        WHERE id = ANY(:file_ids)
        AND created_by = :user_id
        AND is_deleted = false
        """
        files = await db.fetch_all(
            verify_query,
            {"file_ids": file_ids, "user_id": current_user["uid"]}
        )

        if len(files) != len(file_ids):
            raise HTTPException(
                status_code=404, detail="One or more files not found")

        # Soft delete the files
        delete_query = """
        UPDATE mo_assets
        SET 
            is_deleted = true,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ANY(:file_ids)
        AND created_by = :user_id
        AND is_deleted = false
        """

        await db.execute(
            delete_query,
            {"file_ids": file_ids, "user_id": current_user["uid"]}
        )

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_files: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/move")
async def move_files(
    file_ids: List[str],
    folder_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Move files to a different folder"""
    try:
        # Verify files exist and belong to user
        verify_query = """
        SELECT id FROM mo_assets
        WHERE id = ANY(:file_ids)
        AND created_by = :user_id
        AND is_deleted = false
        """
        files = await db.fetch_all(
            verify_query,
            {"file_ids": file_ids, "user_id": current_user["uid"]}
        )

        if len(files) != len(file_ids):
            raise HTTPException(
                status_code=404, detail="One or more files not found")

        # Verify target folder if specified
        if folder_id:
            folder_query = """
            SELECT id FROM mo_folders
            WHERE id = :folder_id
            AND created_by = :user_id
            AND is_deleted = false
            """
            folder = await db.fetch_one(
                folder_query,
                {"folder_id": folder_id, "user_id": current_user["uid"]}
            )
            if not folder:
                raise HTTPException(
                    status_code=404, detail="Target folder not found")

        # Move the files
        move_query = """
        UPDATE mo_assets
        SET 
            folder_id = :folder_id,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ANY(:file_ids)
        AND created_by = :user_id
        AND is_deleted = false
        """

        await db.execute(
            move_query,
            {
                "file_ids": file_ids,
                "folder_id": folder_id,
                "user_id": current_user["uid"]
            }
        )

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in move_files: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
