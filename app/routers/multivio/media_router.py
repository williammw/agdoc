
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import List, Optional, Dict
from pydantic import BaseModel
from datetime import datetime
import logging
from app.dependencies import get_current_user, get_database
from databases import Database
import boto3
import os
import uuid
import json
logger = logging.getLogger(__name__)

# Configure R2 client
s3_client = boto3.client('s3',
                         endpoint_url=os.getenv('R2_ENDPOINT_URL'),
                         aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                         aws_secret_access_key=os.getenv(
                             'R2_SECRET_ACCESS_KEY'),
                         region_name='weur')
bucket_name = 'multivio'

# Note: R2 CORS must be configured in Cloudflare dashboard

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "/usr/bin/ffmpeg")
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "cdn.multivio.com")

ALLOWED_TYPES = {
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp'],
    'video': ['.mp4', '.webm', '.mov']
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

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


class PresignedUrlRequest(BaseModel):
    filename: str
    content_type: str
    folder_id: Optional[str] = None


def configure_r2_cors():
    cors_configuration = {
        'CORSRules': [{
            'AllowedHeaders': ['*'],
            'AllowedMethods': ['GET', 'PUT', 'HEAD'],
            'AllowedOrigins': ['https://dev.multivio.com', 'http://localhost:5173'],
            'ExposeHeaders': ['ETag'],
            'MaxAgeSeconds': 3000
        }]
    }

    try:
        s3_client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration=cors_configuration
        )
        print("Successfully configured CORS on R2 bucket")
    except Exception as e:
        print(f"Error configuring CORS: {str(e)}")



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
    file_ids: List[str] = Body(...),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Delete multiple files"""
    try:
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
            raise HTTPException(status_code=404, detail="One or more files not found")

        await db.execute(
            """
            UPDATE mo_assets
            SET is_deleted = true, updated_at = CURRENT_TIMESTAMP
            WHERE id = ANY(:file_ids) AND created_by = :user_id
            """,
            {"file_ids": file_ids, "user_id": current_user["uid"]}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_files: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/move-files")
async def move_files(
    payload: dict = Body(...),  # This will parse the request body
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Move files to a different folder"""
    try:
        file_ids = payload.get("fileIds", [])
        folder_id = payload.get("folderId")

        if not file_ids:
            raise HTTPException(status_code=400, detail="No files specified")

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

@router.post("/upload/presigned")
async def get_presigned_url(
    request: PresignedUrlRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Generate unique key
        timestamp = datetime.now().strftime('%Y/%m/%d')
        asset_id = str(uuid.uuid4())
        ext = os.path.splitext(request.filename)[1].lower()
        key = f"uploads/{current_user['uid']}/{timestamp}/{asset_id}{ext}"

        try:
            # Generate presigned URL for PUT
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod='put_object',
                Params={
                    'Bucket': bucket_name,
                    'Key': key,
                    'ContentType': request.content_type
                },
                ExpiresIn=3600
            )

            logger.info(f"Generated presigned URL: {presigned_url}")

            # Insert record
            query = """
                INSERT INTO mo_assets (
                    id, name, type, url, content_type, original_name,
                    file_size, folder_id, created_by, processing_status,
                    is_deleted, created_at, updated_at
                ) VALUES (
                    :id, :name, :type, :url, :content_type, :original_name,
                    :file_size, :folder_id, :created_by, :processing_status,
                    false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """

            values = {
                "id": asset_id,
                "name": request.filename,
                "type": request.content_type.split('/')[0],
                "url": f"https://{CDN_DOMAIN}/{key}",
                "content_type": request.content_type,
                "original_name": request.filename,
                "file_size": 0,
                "folder_id": request.folder_id,
                "created_by": current_user["uid"],
                "processing_status": 'pending'
            }

            await db.execute(query, values)

            return {
                "url": presigned_url,
                "asset_id": asset_id,
                "public_url": f"https://{CDN_DOMAIN}/{key}"
            }

        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate upload URL: {str(e)}"
            )

    except Exception as e:
        logger.error(f"Error in get_presigned_url: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_media_file(asset_id: str, key: str, content_type: str, db: Database = Depends(get_database)):
    try:
        # Download from R2
        local_path = f"/tmp/{os.path.basename(key)}"
        s3_client.download_file(bucket_name, key, local_path)

        metadata = {}
        thumbnail_key = None

        if content_type.startswith('image/'):
            # Process image
            metadata = process_image(local_path)
            thumbnail_key = generate_image_thumbnail(local_path, key)
        elif content_type.startswith('video/'):
            # Process video
            metadata = process_video(local_path)
            thumbnail_key = generate_video_thumbnail(local_path, key)

        # Update asset with metadata
        await db.execute("""
            UPDATE mo_assets 
            SET processing_status = 'completed',
                metadata = $1,
                thumbnail_url = $2
            WHERE id = $3
            """,
                json.dumps(metadata),
                f"https://{CDN_DOMAIN}/{thumbnail_key}" if thumbnail_key else None,
                asset_id
                )

    except Exception as e:
        # Update asset with error
        await db.execute("""
            UPDATE mo_assets 
            SET processing_status = 'failed',
                processing_error = $1
            WHERE id = $2
            """,
                str(e), asset_id
                )
    finally:
        # Cleanup
        if os.path.exists(local_path):
            os.remove(local_path)


@router.get("/test-r2-cors")
async def test_r2_cors():
    try:
        # Get current CORS configuration
        cors = s3_client.get_bucket_cors(Bucket=bucket_name)
        return {"current_cors_config": cors}
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}




@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str, 
    current_user: dict = Depends(get_current_user), 
    db: Database = Depends(get_database)
):
    """Delete a single file"""
    try:
        # Verify file exists and belongs to user
        file = await db.fetch_one(
            "SELECT id FROM mo_assets WHERE id = :file_id AND created_by = :user_id AND is_deleted = false",
            {"file_id": file_id, "user_id": current_user["uid"]}
        )

        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        # Soft delete
        await db.execute(
            """
            UPDATE mo_assets 
            SET is_deleted = true, updated_at = CURRENT_TIMESTAMP 
            WHERE id = :file_id AND created_by = :user_id
            """,
            {"file_id": file_id, "user_id": current_user["uid"]}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))