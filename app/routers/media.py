from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from typing import List, Optional, Dict, Any
import uuid
import os
import json
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
import aiofiles
import tempfile
from PIL import Image
import io

from app.dependencies.auth import get_current_user
from app.utils.database import get_db
from app.utils.encryption import encrypt_token, decrypt_token

router = APIRouter(
    prefix="/api/v1/media",
    tags=["media"],
    dependencies=[Depends(get_current_user)]
)

# Create database dependency with admin access
db_admin = get_db(admin_access=True)

# Cloudflare R2 Configuration
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "cdn.multivio.com")

# Initialize R2 client
r2_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name='auto'  # Cloudflare R2 uses 'auto'
)

def get_platform_compatibility(file_type: str) -> List[str]:
    """Get list of platforms that support this file type"""
    if file_type.startswith('image/'):
        return ['twitter', 'facebook', 'instagram', 'linkedin', 'threads']
    elif file_type.startswith('video/'):
        return ['twitter', 'facebook', 'instagram', 'linkedin', 'youtube', 'threads']
    else:
        return []

def validate_file(file: UploadFile) -> Dict[str, Any]:
    """Validate uploaded file"""
    # File size limits (100MB for general files, 4GB for videos on some platforms)
    max_size = 100 * 1024 * 1024  # 100MB default
    
    if file.content_type and file.content_type.startswith('video/'):
        max_size = 4000 * 1024 * 1024  # 4GB for videos
    
    if hasattr(file.file, 'seek'):
        # Get file size
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        if file_size > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {max_size / (1024*1024):.0f}MB"
            )
    
    # Validate file type
    allowed_types = [
        'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
        'video/mp4', 'video/mov', 'video/avi', 'video/quicktime', 'video/webm'
    ]
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file.content_type} not supported"
        )
    
    return {
        "file_size": file_size if hasattr(file.file, 'seek') else 0,
        "file_type": file.content_type,
        "platform_compatibility": get_platform_compatibility(file.content_type)
    }

async def upload_to_r2(file_content: bytes, key: str, content_type: str) -> str:
    """Upload file to Cloudflare R2"""
    try:
        print(f"Uploading to R2: Bucket={R2_BUCKET_NAME}, Key={key}, ContentType={content_type}")
        print(f"R2 Endpoint: {R2_ENDPOINT_URL}")
        
        response = r2_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=file_content,
            ContentType=content_type
        )
        
        print(f"R2 Upload Response: {response}")
        # For now, return the CDN URL but also log the R2 public URL for debugging
        cdn_url = f"https://{CDN_DOMAIN}/{key}"
        
        # Also calculate R2 public URL for debugging
        account_id = R2_ENDPOINT_URL.split('//')[1].split('.')[0] if R2_ENDPOINT_URL else ''
        r2_public_url = f"https://{R2_BUCKET_NAME}.{account_id}.r2.cloudflarestorage.com/{key}"
        
        print(f"CDN URL: {cdn_url}")
        print(f"R2 Public URL (alternative): {r2_public_url}")
        print(f"R2 Dev URL (alternative): https://{R2_BUCKET_NAME}.r2.dev/{key}")
        
        # Return CDN URL since it's properly configured
        return cdn_url
    except ClientError as e:
        print(f"Error uploading to R2: {e}")
        print(f"Error details: {e.response}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file to storage"
        )

async def generate_thumbnail(file_content: bytes, file_type: str) -> Optional[bytes]:
    """Generate thumbnail for image files"""
    if not file_type.startswith('image/'):
        return None
    
    try:
        # Open image
        image = Image.open(io.BytesIO(file_content))
        
        # Create thumbnail (400x400 max, maintain aspect ratio)
        image.thumbnail((400, 400), Image.Resampling.LANCZOS)
        
        # Convert to RGB if necessary (for JPEG output)
        if image.mode in ('RGBA', 'P'):
            image = image.convert('RGB')
        
        # Save to bytes
        thumb_buffer = io.BytesIO()
        image.save(thumb_buffer, format='JPEG', quality=85, optimize=True)
        return thumb_buffer.getvalue()
    
    except Exception as e:
        print(f"Error generating thumbnail: {e}")
        return None

@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    purpose: str = Form("social_media_post"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """Upload media file to R2 storage"""
    
    try:
        # Validate file
        validation_result = validate_file(file)
        
        # Read file content
        file_content = await file.read()
        actual_file_size = len(file_content)
        
        # Generate unique filename and R2 key
        file_id = str(uuid.uuid4())
        file_extension = os.path.splitext(file.filename or "")[1]
        temp_key = f"social-media/uploads/{current_user['id']}/temp/{file_id}_{file.filename}"
        
        # Upload main file to R2
        cdn_url = await upload_to_r2(file_content, temp_key, file.content_type)
        
        # Generate and upload thumbnail for images
        thumbnail_url = None
        if file.content_type.startswith('image/'):
            thumbnail_content = await generate_thumbnail(file_content, file.content_type)
            if thumbnail_content:
                thumb_key = f"social-media/uploads/{current_user['id']}/thumbnails/{file_id}_thumb.jpg"
                thumbnail_url = await upload_to_r2(thumbnail_content, thumb_key, "image/jpeg")
        
        # Get image metadata
        metadata = {}
        if file.content_type.startswith('image/'):
            try:
                image = Image.open(io.BytesIO(file_content))
                metadata = {
                    "width": image.width,
                    "height": image.height,
                    "format": image.format,
                    "mode": image.mode
                }
            except Exception as e:
                print(f"Error getting image metadata: {e}")
        
        # Create database record
        media_record = {
            "user_id": current_user["id"],
            "original_filename": file.filename or f"upload{file_extension}",
            "file_type": file.content_type,
            "file_size": actual_file_size,
            "r2_key": temp_key,
            "cdn_url": cdn_url,
            "thumbnail_url": thumbnail_url,
            "metadata": metadata,
            "processing_status": "completed" if file.content_type.startswith('image/') else "pending"
        }
        
        result = supabase.table("media_files").insert(media_record).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create media record in database"
            )
        
        media_id = result.data[0]["id"]
        
        # For videos, queue processing job (placeholder for now)
        if file.content_type.startswith('video/'):
            processing_job = {
                "media_file_id": media_id,
                "job_type": "thumbnail",
                "status": "pending"
            }
            supabase.table("media_processing_jobs").insert(processing_job).execute()
        
        return {
            "id": media_id,
            "original_filename": file.filename,
            "file_type": file.content_type,
            "file_size": actual_file_size,
            "cdn_url": cdn_url,
            "thumbnail_url": thumbnail_url,
            "processing_status": media_record["processing_status"],
            "platform_compatibility": validation_result["platform_compatibility"],
            "metadata": metadata
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error uploading media: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload media file: {str(e)}"
        )

@router.get("/status/{media_id}")
async def get_media_status(
    media_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """Check media processing status"""
    
    try:
        # Get media file
        media_response = supabase.table("media_files").select("*").eq("id", media_id).eq("user_id", current_user["id"]).execute()
        
        if not media_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media file not found"
            )
        
        media_file = media_response.data[0]
        
        # Get processing jobs
        jobs_response = supabase.table("media_processing_jobs").select("*").eq("media_file_id", media_id).execute()
        
        return {
            "media_file": media_file,
            "processing_jobs": jobs_response.data or []
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting media status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get media status: {str(e)}"
        )

@router.get("/library")
async def get_media_library(
    limit: int = 50,
    offset: int = 0,
    file_type: Optional[str] = None,  # 'image' or 'video'
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """Get user's media library"""
    
    try:
        # Build query
        query = supabase.table("media_files").select("*").eq("user_id", current_user["id"])
        
        # Filter by file type if specified
        if file_type == 'image':
            query = query.like("file_type", "image/%")
        elif file_type == 'video':
            query = query.like("file_type", "video/%")
        
        # Apply pagination and ordering
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        
        result = query.execute()
        
        return {
            "media_files": result.data or [],
            "count": len(result.data or []),
            "has_more": len(result.data or []) == limit
        }
        
    except Exception as e:
        print(f"Error getting media library: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get media library: {str(e)}"
        )

@router.delete("/{media_id}")
async def delete_media(
    media_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """Delete media file"""
    
    try:
        # Get media file to ensure ownership and get R2 keys
        media_response = supabase.table("media_files").select("*").eq("id", media_id).eq("user_id", current_user["id"]).execute()
        
        if not media_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media file not found"
            )
        
        media_file = media_response.data[0]
        
        # Delete from R2 storage
        try:
            # Delete main file
            r2_client.delete_object(Bucket=R2_BUCKET_NAME, Key=media_file["r2_key"])
            
            # Delete thumbnail if exists
            if media_file.get("thumbnail_url"):
                thumb_key = media_file["thumbnail_url"].replace(f"https://{CDN_DOMAIN}/", "")
                r2_client.delete_object(Bucket=R2_BUCKET_NAME, Key=thumb_key)
                
        except ClientError as e:
            print(f"Error deleting from R2: {e}")
            # Continue with database deletion even if R2 deletion fails
        
        # Delete from database (this will cascade to processing jobs and variants)
        supabase.table("media_files").delete().eq("id", media_id).execute()
        
        return {"message": "Media file deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting media: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete media file: {str(e)}"
        )

@router.get("/variants/{media_id}")
async def get_media_variants(
    media_id: str,
    platform: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """Get platform-specific variants of a media file"""
    
    try:
        # Verify media file ownership
        media_response = supabase.table("media_files").select("id").eq("id", media_id).eq("user_id", current_user["id"]).execute()
        
        if not media_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media file not found"
            )
        
        # Get variants
        query = supabase.table("media_variants").select("*").eq("media_file_id", media_id)
        
        if platform:
            query = query.eq("platform", platform)
        
        result = query.execute()
        
        return {
            "media_id": media_id,
            "variants": result.data or []
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting media variants: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get media variants: {str(e)}"
        )