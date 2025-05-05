from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta, date
import logging
from app.dependencies import get_current_user, get_database
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
    db = Depends(get_database)
):
    """Get files with filtering, sorting and pagination"""
    try:
        # Build base query
        query = db.table("mo_assets").select("*").eq("created_by", current_user["uid"]).eq("is_deleted", False)

        # Add filters
        if folder_id:
            query = query.eq("folder_id", folder_id)
        
        if type:
            query = query.eq("type", type)
            
        if search:
            query = query.ilike("name", f"%{search}%")
        
        # Get count for pagination with a separate query
        count_query = db.table("mo_assets").select("id").eq("created_by", current_user["uid"]).eq("is_deleted", False)
        
        # Apply the same filters to count query
        if folder_id:
            count_query = count_query.eq("folder_id", folder_id)
        
        if type:
            count_query = count_query.eq("type", type)
            
        if search:
            count_query = count_query.ilike("name", f"%{search}%")
        
        # Execute count query - synchronous, not awaitable
        count_result = count_query.execute()
        total = len(count_result.data) if count_result.data else 0
        
        # Map sort fields
        sort_field_map = {
            "name": "name",
            "created_at": "created_at",
            "date": "created_at",
            "size": "size",
            "usage": "usage_count"
        }
        sort_field = sort_field_map.get(sort_by, "created_at")
        
        # Apply sorting and pagination
        query = query.order(sort_field, desc=(sort_order.lower() == "desc"))
        query = query.range((page-1)*limit, page*limit-1)
        
        # Execute the query - synchronous, not awaitable
        result = query.execute()
        
        return {
            "files": result.data,
            "total": total
        }
    except Exception as e:
        logger.error(f"Error in get_files: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files/{file_id}", response_model=MediaFile)
async def get_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """Get a specific file"""
    try:
        result = db.table("mo_assets").select("*").eq("id", file_id) \
            .eq("created_by", current_user["uid"]).eq("is_deleted", False).single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="File not found")

        return result.data

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
    db = Depends(get_database)
):
    """Update a file"""
    try:
        # Verify file exists and belongs to user
        exists = db.table("mo_assets").select("id").eq("id", file_id) \
            .eq("created_by", current_user["uid"]).eq("is_deleted", False).execute()
            
        if not exists.data:
            raise HTTPException(status_code=404, detail="File not found")

        # Verify folder if specified
        if file.folder_id:
            folder = db.table("mo_folders").select("id").eq("id", file.folder_id) \
                .eq("created_by", current_user["uid"]).eq("is_deleted", False).execute()
                
            if not folder.data:
                raise HTTPException(status_code=404, detail="Folder not found")

        # Prepare update data
        update_data = {}
        
        if file.name is not None:
            update_data["name"] = file.name
            
        if file.folder_id is not None:
            update_data["folder_id"] = file.folder_id
            
        if file.metadata is not None:
            update_data["metadata"] = file.metadata
            
        if not update_data:
            return await get_file(file_id, current_user, db)
            
        # Add updated timestamp
        update_data["updated_at"] = datetime.now().isoformat()
        
        # Perform update
        result = db.table("mo_assets").update(update_data).eq("id", file_id) \
            .eq("created_by", current_user["uid"]).eq("is_deleted", False).single().execute()
            
        if not result.data:
            raise HTTPException(status_code=404, detail="File not found")
            
        return result.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/files")
async def delete_files(
    file_ids: List[str] = Body(...),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """Delete multiple files"""
    try:
        # Verify files exist and belong to user
        files = db.table("mo_assets").select("id").in_("id", file_ids) \
            .eq("created_by", current_user["uid"]).eq("is_deleted", False).execute()
            
        if len(files.data) != len(file_ids):
            raise HTTPException(status_code=404, detail="One or more files not found")

        # Perform soft delete
        update_data = {
            "is_deleted": True,
            "updated_at": datetime.now().isoformat()
        }
        
        db.table("mo_assets").update(update_data).in_("id", file_ids) \
            .eq("created_by", current_user["uid"]).execute()

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
    db = Depends(get_database)
):
    """Move files to a different folder"""
    try:
        file_ids = payload.get("fileIds", [])
        folder_id = payload.get("folderId")

        if not file_ids:
            raise HTTPException(status_code=400, detail="No files specified")

        # Verify files exist and belong to user
        files = db.table("mo_assets").select("id").in_("id", file_ids) \
            .eq("created_by", current_user["uid"]).eq("is_deleted", False).execute()
            
        if len(files.data) != len(file_ids):
            raise HTTPException(status_code=404, detail="One or more files not found")

        # Verify target folder if specified
        if folder_id:
            folder = db.table("mo_folders").select("id").eq("id", folder_id) \
                .eq("created_by", current_user["uid"]).eq("is_deleted", False).execute()
                
            if not folder.data:
                raise HTTPException(status_code=404, detail="Target folder not found")

        # Move files
        update_data = {
            "folder_id": folder_id,
            "updated_at": datetime.now().isoformat()
        }
        
        db.table("mo_assets").update(update_data).in_("id", file_ids) \
            .eq("created_by", current_user["uid"]).eq("is_deleted", False).execute()

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
    db = Depends(get_database)
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
            asset_data = {
                "id": asset_id,
                "name": request.filename,
                "type": request.content_type.split('/')[0],
                "url": f"https://{CDN_DOMAIN}/{key}",
                "content_type": request.content_type,
                "original_name": request.filename,
                "file_size": 0,
                "folder_id": request.folder_id,
                "created_by": current_user["uid"],
                "processing_status": 'pending',
                "is_deleted": False,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

            db.table("mo_assets").insert(asset_data).execute()

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

async def process_media_file(asset_id: str, key: str, content_type: str, db = Depends(get_database)):
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
        update_data = {
            "processing_status": "completed",
            "metadata": metadata
        }
        
        if thumbnail_key:
            update_data["thumbnail_url"] = f"https://{CDN_DOMAIN}/{thumbnail_key}"
            
        await db.table("mo_assets").update(update_data).eq("id", asset_id).execute()

    except Exception as e:
        # Update asset with error
        await db.table("mo_assets").update({
            "processing_status": "failed",
            "processing_error": str(e)
        }).eq("id", asset_id).execute()
    finally:
        # Cleanup
        if os.path.exists(local_path):
            os.remove(local_path)


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str, 
    current_user: dict = Depends(get_current_user), 
    db = Depends(get_database)
):
    """Delete a single file"""
    try:
        # Verify file exists and belongs to user
        file = db.table("mo_assets").select("id").eq("id", file_id) \
            .eq("created_by", current_user["uid"]).eq("is_deleted", False).execute()

        if not file.data:
            raise HTTPException(status_code=404, detail="File not found")

        # Soft delete
        db.table("mo_assets").update({
            "is_deleted": True,
            "updated_at": datetime.now().isoformat()
        }).eq("id", file_id).eq("created_by", current_user["uid"]).execute()

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def check_and_update_quota(db, user_id: str) -> bool:
    """Check if user has remaining quota and update usage."""
    # Check if user has a quota record
    quota_result = db.table("mo_image_quotas").select("*").eq("user_id", user_id).execute()
    
    today = date.today()
    
    # If no quota record exists, create one
    if not quota_result.data:
        new_quota = {
            "user_id": user_id,
            "daily_limit": 10,
            "daily_used": 0,
            "monthly_limit": 100,
            "monthly_used": 0,
            "last_reset_date": today.isoformat()
        }
        
        quota_result = db.table("mo_image_quotas").insert(new_quota).select().execute()
        quota = quota_result.data[0] if quota_result.data else None
    else:
        quota = quota_result.data[0]
    
    # Parse date string to date object if it's a string
    last_reset_date = quota["last_reset_date"]
    if isinstance(last_reset_date, str):
        last_reset_date = date.fromisoformat(last_reset_date)
    
    # Check if we need to reset daily counter
    if last_reset_date < today:
        db.table("mo_image_quotas").update({
            "daily_used": 0,
            "last_reset_date": today.isoformat()
        }).eq("user_id", user_id).execute()
        
        # Refresh quota data
        quota_result = db.table("mo_image_quotas").select("*").eq("user_id", user_id).execute()
        quota = quota_result.data[0]
    
    # Check if we need to reset monthly counter (first day of month)
    if today.day == 1 and last_reset_date.month != today.month:
        db.table("mo_image_quotas").update({
            "monthly_used": 0
        }).eq("user_id", user_id).execute()
        
        # Refresh quota data
        quota_result = db.table("mo_image_quotas").select("*").eq("user_id", user_id).execute()
        quota = quota_result.data[0]
    
    # Check if user has exceeded quotas
    if quota["daily_used"] >= quota["daily_limit"] or quota["monthly_used"] >= quota["monthly_limit"]:
        return False
    
    # Update usage counters
    db.table("mo_image_quotas").update({
        "daily_used": quota["daily_used"] + 1,
        "monthly_used": quota["monthly_used"] + 1
    }).eq("user_id", user_id).execute()
    
    return True

@router.post("/generate-image", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """Initiate image generation process with REST approach."""
    try:
        # Check user quota
        user_id = current_user["uid"]
        has_quota = check_and_update_quota(db, user_id)
        
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
        task_data = {
            "id": task_id,
            "type": "image_generation",
            "parameters": {
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "size": request.size,
                "model": request.model,
                "num_images": request.num_images,
                "folder_id": request.folder_id,
                "disable_safety_checker": request.disable_safety_checker
            },
            "status": "processing",
            "created_by": user_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        db.table("mo_ai_tasks").insert(task_data).execute()
        
        # Create initial stage record at 0%
        stage_data = {
            "task_id": task_id,
            "stage_number": 1,
            "completion_percentage": 0,
            "image_path": "",
            "image_url": None
        }
        
        db.table("mo_image_stages").insert(stage_data).execute()
        
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
    db = Depends(get_database)
):
    """Get the status of an image generation task."""
    try:
        # Query the task table for the task
        task_result = db.table("mo_ai_tasks").select(
            "id, type, parameters, status, result, error, created_at, completed_at"
        ).eq("id", task_id).execute()
        
        if not task_result.data:
            raise HTTPException(status_code=404, detail="Image generation task not found")
        
        task = task_result.data[0]
        
        # Get the latest stage information
        stage_result = db.table("mo_image_stages").select("*").eq("task_id", task_id) \
            .order("completion_percentage", desc=True).limit(1).execute()
        
        stage = stage_result.data[0] if stage_result.data else {}
        
        if task["status"] == "completed" and task["result"]:
            # Parse the result JSON
            result_data = task["result"]
            
            # Get the first image from the result
            image = result_data.get("images", [])[0] if result_data.get("images") else None
            
            if image:
                return {
                    "status": "completed",
                    "image_url": image["url"],
                    "image_id": image["id"],
                    "prompt": image["prompt"],
                    "model": image["model"],
                    "created_at": task["created_at"],
                    "completed_at": task["completed_at"]
                }
            else:
                # Result exists but no images found
                return {
                    "status": "failed",
                    "error": "No images found in completed result"
                }
                
        elif task["status"] == "failed":
            return {
                "status": "failed",
                "error": task.get("error", "Unknown error occurred during image generation")
            }
        else:
            # Still processing - return stage information
            return {
                "status": "processing",
                "completion": stage.get("completion_percentage", 0),
                "image_url": stage.get("image_url"),
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
    db = Depends(get_database)
):
    """Get user's image generation history."""
    user_id = user.get("uid")
    
    # Get history items with pagination
    history_result = db.table("mo_ai_tasks").select("id, parameters, status, created_at, result") \
        .eq("type", "image_generation").eq("created_by", user_id) \
        .order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    
    # Get total count
    count_result = db.table("mo_ai_tasks").select("id") \
        .eq("type", "image_generation").eq("created_by", user_id).execute()
    
    total = len(count_result.data) if count_result.data else 0
    
    # Process history items
    processed_items = []
    for item in history_result.data:
        # Parse the result if completed
        if item["status"] == "completed" and item.get("result"):
            result_data = item["result"]
            
            # Extract just the first image for the overview
            if "images" in result_data and len(result_data["images"]) > 0:
                item["image"] = result_data["images"][0]
                
        processed_items.append(item)
    
    return {
        "images": processed_items,
        "total": total,
        "limit": limit,
        "offset": offset
    }