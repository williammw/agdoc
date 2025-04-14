from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta, date
import logging
from app.dependencies import get_current_user, get_database
from databases import Database
import boto3
import os
import uuid
import json
import asyncio
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


class ImageGenerationRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None
    size: str = "1024x1024"
    model: str = "flux"
    num_images: int = Field(1, ge=1, le=4)
    folder_id: Optional[str] = None
    disable_safety_checker: bool = True


class ImageGenerationResponse(BaseModel):
    task_id: str
    status: str = "processing"
    public_url: Optional[str] = None


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

async def check_and_update_quota(db: Database, user_id: str) -> bool:
    """Check if user has remaining quota and update usage."""
    # Check if user has a quota record
    query = """
    SELECT * FROM mo_image_quotas WHERE user_id = :user_id
    """
    quota = await db.fetch_one(query=query, values={"user_id": user_id})
    
    today = date.today()
    
    # If no quota record exists, create one
    if not quota:
        insert_query = """
        INSERT INTO mo_image_quotas 
        (user_id, daily_limit, daily_used, monthly_limit, monthly_used, last_reset_date)
        VALUES (:user_id, 10, 0, 100, 0, :today)
        RETURNING *
        """
        quota = await db.fetch_one(
            query=insert_query, 
            values={"user_id": user_id, "today": today}
        )
    
    # Convert to dict for easier access
    quota = dict(quota)
    
    # Check if we need to reset daily counter
    if quota["last_reset_date"] < today:
        update_query = """
        UPDATE mo_image_quotas
        SET daily_used = 0, last_reset_date = :today
        WHERE user_id = :user_id
        RETURNING *
        """
        quota = await db.fetch_one(
            query=update_query,
            values={"user_id": user_id, "today": today}
        )
        quota = dict(quota)
    
    # Check if we need to reset monthly counter (first day of month)
    if today.day == 1 and quota["last_reset_date"].month != today.month:
        update_query = """
        UPDATE mo_image_quotas
        SET monthly_used = 0
        WHERE user_id = :user_id
        RETURNING *
        """
        quota = await db.fetch_one(
            query=update_query,
            values={"user_id": user_id}
        )
        quota = dict(quota)
    
    # Check if user has exceeded quotas
    if quota["daily_used"] >= quota["daily_limit"]:
        return False
    
    if quota["monthly_used"] >= quota["monthly_limit"]:
        return False
    
    # Update usage counters
    update_query = """
    UPDATE mo_image_quotas
    SET daily_used = daily_used + 1, monthly_used = monthly_used + 1
    WHERE user_id = :user_id
    """
    await db.execute(query=update_query, values={"user_id": user_id})
    
    return True

@router.post("/generate-image", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Initiate image generation process with REST approach."""
    try:
        # Check user quota
        user_id = current_user["uid"]
        has_quota = await check_and_update_quota(db, user_id)
        
        if not has_quota:
            raise HTTPException(
                status_code=429,
                detail="You have reached your daily or monthly image generation limit"
            )
        
        # Create a task ID
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Prepare API data for together.ai
        api_data = {
            "prompt": request.prompt,
            "model": request.model,
            "n": request.num_images,
            "disable_safety_checker": request.disable_safety_checker
        }
        
        # Add optional parameters
        if request.negative_prompt:
            api_data["negative_prompt"] = request.negative_prompt
        
        if request.size:
            width, height = map(int, request.size.split("x"))
            api_data["width"] = width
            api_data["height"] = height
        
        # Store the task in the database
        query = """
        INSERT INTO mo_ai_tasks (
            id, type, parameters, status, created_by, created_at, updated_at
        ) VALUES (
            :id, :type, :parameters, :status, :created_by, :created_at, :updated_at
        )
        """
        
        values = {
            "id": task_id,
            "type": "image_generation",
            "parameters": json.dumps({
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "size": request.size,
                "model": request.model,
                "num_images": request.num_images,
                "folder_id": request.folder_id,
                "disable_safety_checker": request.disable_safety_checker
            }),
            "status": "processing",
            "created_by": user_id,
            "created_at": now,
            "updated_at": now
        }
        
        await db.execute(query=query, values=values)
        
        # Create initial stage record at 0%
        stage_query = """
        INSERT INTO mo_image_stages
        (task_id, stage_number, completion_percentage, image_path, image_url)
        VALUES (:task_id, 1, 0, '', NULL)
        """
        await db.execute(
            query=stage_query,
            values={
                "task_id": task_id
            }
        )
        
        # Import the image generation task to avoid circular imports
        from app.routers.multivio.together_router import generate_image_task
        
        # Start background task
        background_tasks.add_task(
            generate_image_task,
            task_id,
            api_data,
            user_id,
            request.folder_id,
            db
        )
        
        return ImageGenerationResponse(
            task_id=task_id,
            status="processing"
        )
        
    except Exception as e:
        logger.error(f"Error initiating image generation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/image-status/{task_id}")
async def get_image_status(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get the status of an image generation task."""
    try:
        # Query the task table for the task
        query = """
        SELECT id, type, parameters, status, result, error, 
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE id = :task_id
        """
        
        task = await db.fetch_one(
            query=query,
            values={
                "task_id": task_id
            }
        )
        
        if not task:
            raise HTTPException(status_code=404, detail="Image generation task not found")
        
        task_dict = dict(task)
        
        # Get the latest stage information
        stages_query = """
        SELECT * FROM mo_image_stages
        WHERE task_id = :task_id
        ORDER BY completion_percentage DESC
        LIMIT 1
        """
        
        stage = await db.fetch_one(
            query=stages_query,
            values={"task_id": task_id}
        )
        
        stage_dict = dict(stage) if stage else {}
        
        if task_dict["status"] == "completed" and task_dict["result"]:
            # Parse the result JSON
            result_data = json.loads(task_dict["result"])
            
            # Get the first image from the result
            image = result_data.get("images", [])[0] if result_data.get("images") else None
            
            if image:
                return {
                    "status": "completed",
                    "image_url": image["url"],
                    "image_id": image["id"],
                    "prompt": image["prompt"],
                    "model": image["model"],
                    "created_at": task_dict["created_at"].isoformat() if task_dict["created_at"] else None,
                    "completed_at": task_dict["completed_at"].isoformat() if task_dict["completed_at"] else None
                }
            else:
                # Result exists but no images found
                return {
                    "status": "failed",
                    "error": "No images found in completed result"
                }
                
        elif task_dict["status"] == "failed":
            return {
                "status": "failed",
                "error": task_dict.get("error", "Unknown error occurred during image generation")
            }
        else:
            # Still processing - return stage information
            return {
                "status": "processing",
                "completion": stage_dict.get("completion_percentage", 0),
                "image_url": stage_dict.get("image_url", None),
                "message": "Image generation is still in progress"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting image status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/images/history")
async def get_image_history(
    limit: int = 10,
    offset: int = 0,
    user = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """Get user's image generation history."""
    user_id = user.get("uid")
    
    query = """
    SELECT t.id, t.parameters, t.status, t.created_at, t.result
    FROM mo_ai_tasks t
    WHERE t.type = 'image_generation' AND t.created_by = :user_id
    ORDER BY t.created_at DESC
    LIMIT :limit OFFSET :offset
    """
    
    history_items = await db.fetch_all(
        query=query,
        values={"user_id": user_id, "limit": limit, "offset": offset}
    )
    
    count_query = """
    SELECT COUNT(*) as total
    FROM mo_ai_tasks
    WHERE type = 'image_generation' AND created_by = :user_id
    """
    count = await db.fetch_val(query=count_query, values={"user_id": user_id}, column="total")
    
    # Process history items
    processed_items = []
    for item in history_items:
        item_dict = dict(item)
        
        # Parse the parameters
        try:
            if isinstance(item_dict["parameters"], str):
                item_dict["parameters"] = json.loads(item_dict["parameters"])
        except:
            pass
            
        # Parse the result if completed
        if item_dict["status"] == "completed" and item_dict.get("result"):
            try:
                if isinstance(item_dict["result"], str):
                    result_data = json.loads(item_dict["result"])
                    # Extract just the first image for the overview
                    if "images" in result_data and len(result_data["images"]) > 0:
                        item_dict["image"] = result_data["images"][0]
            except:
                pass
                
        processed_items.append(item_dict)
    
    return {
        "images": processed_items,
        "total": count,
        "limit": limit,
        "offset": offset
    }