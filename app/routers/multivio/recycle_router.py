from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List
from pydantic import BaseModel
from app.dependencies import get_current_user, get_database
from datetime import datetime
from urllib.parse import urlparse, unquote
import re

router = APIRouter(tags=["recycle"])


class DeletedAssetResponse(BaseModel):
    id: str
    created_by: str
    name: str
    url: str
    public_url: str | None
    created_at: datetime
    updated_at: datetime
    file_size: int
    content_type: str
    is_deleted: bool


def extract_r2_key_from_url(url: str) -> str:
    """Extract R2 key from CDN URL."""
    try:
        # Parse the URL and get the path
        parsed = urlparse(url)
        path = unquote(parsed.path)

        # The path should start with /uploads/
        if not path.startswith('/uploads/'):
            raise ValueError("Invalid URL format")

        # Remove leading slash and return the key
        # This gives us: uploads/user_id/year/month/day/file_id.ext
        return path[1:]
    except Exception as e:
        raise ValueError(f"Failed to extract R2 key: {str(e)}")


@router.get("/assets", response_model=List[DeletedAssetResponse])
async def get_deleted_assets(
    current_user: dict = Depends(get_current_user),
    db: dict = Depends(get_database)
):
    """Get all deleted assets for the current user."""
    query = """
        SELECT id, created_by, name, url, public_url, 
               created_at, updated_at, file_size, content_type, is_deleted
        FROM mo_assets 
        WHERE created_by = :created_by AND is_deleted = true
        ORDER BY updated_at DESC
    """
    values = {"created_by": current_user["id"]}

    result = await db.fetch_all(query, values)
    return [DeletedAssetResponse(**dict(row)) for row in result]


@router.post("/restore")
async def restore_assets(
    asset_ids: List[str] = Body(..., embed=True),
    current_user: dict = Depends(get_current_user),
    db: dict = Depends(get_database)
):
    """Restore deleted assets."""
    check_query = """
        SELECT COUNT(*) 
        FROM mo_assets 
        WHERE id = ANY(:asset_ids) AND created_by = :created_by AND is_deleted = true
    """
    check_values = {"asset_ids": asset_ids, "created_by": current_user["id"]}
    count = await db.fetch_val(check_query, check_values)

    if count != len(asset_ids):
        raise HTTPException(
            status_code=403, detail="Unauthorized access to some assets")

    update_query = """
        UPDATE mo_assets 
        SET is_deleted = false
        WHERE id = ANY(:asset_ids) AND created_by = :created_by
        RETURNING id
    """
    update_values = {"asset_ids": asset_ids, "created_by": current_user["id"]}

    updated = await db.fetch_all(update_query, update_values)

    if not updated:
        raise HTTPException(
            status_code=404, detail="No assets found to restore")

    return {"message": "Assets restored successfully", "restored_count": len(updated)}


@router.delete("/permanent")
async def permanently_delete_assets(
    asset_ids: List[str] = Body(..., embed=True),
    current_user: dict = Depends(get_current_user),
    db: dict = Depends(get_database)
):
    """Permanently delete assets."""
    # First get assets info for R2 cleanup
    fetch_query = """
        SELECT id, url 
        FROM mo_assets 
        WHERE id = ANY(:asset_ids) AND created_by = :created_by AND is_deleted = true
    """
    fetch_values = {"asset_ids": asset_ids, "created_by": current_user["id"]}
    assets = await db.fetch_all(fetch_query, fetch_values)

    if not assets:
        raise HTTPException(
            status_code=404, detail="No assets found to delete")

    # Clean up R2 storage
    from app.services.r2_service import CloudflareR2Handler
    r2_handler = CloudflareR2Handler()

    deletion_errors = []
    for asset in assets:
        try:
            r2_key = extract_r2_key_from_url(asset["url"])
            await r2_handler.delete_asset(r2_key)
        except Exception as e:
            deletion_errors.append({
                "asset_id": asset["id"],
                "error": str(e)
            })
            # Log the error but continue with database deletion
            print(f"Error deleting from R2: {str(e)}")

    # Delete from database
    delete_query = """
        DELETE FROM mo_assets 
        WHERE id = ANY(:asset_ids) AND created_by = :created_by
        RETURNING id
    """
    delete_values = {"asset_ids": asset_ids, "created_by": current_user["id"]}

    deleted = await db.fetch_all(delete_query, delete_values)

    response = {
        "message": "Assets permanently deleted",
        "deleted_count": len(deleted),
        "deleted_ids": [row["id"] for row in deleted]
    }

    if deletion_errors:
        response["r2_deletion_errors"] = deletion_errors

    return response
