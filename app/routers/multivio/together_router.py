from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from app.dependencies import get_current_user, get_database
from databases import Database
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import httpx
import logging
from datetime import datetime, timezone
import json
import uuid
import base64

# Import the official Together Python package
try:
    from together import Together
    TOGETHER_CLIENT_AVAILABLE = True
except ImportError:
    TOGETHER_CLIENT_AVAILABLE = False
    logging.getLogger(__name__).warning("Together Python package not installed. Falling back to HTTP requests.")

router = APIRouter(tags=["together"])
logger = logging.getLogger(__name__)

# Environment variables
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
TOGETHER_API_BASE = "https://api.together.ai/v1"
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "cdn.multivio.com")

# Initialize Together client if available
together_client = Together(api_key=TOGETHER_API_KEY) if TOGETHER_CLIENT_AVAILABLE and TOGETHER_API_KEY else None

# Models for request/response
class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt for image generation")
    negative_prompt: Optional[str] = Field(None, description="Negative prompt to guide what not to include")
    size: str = Field("1024x1024", description="Size of the generated image")
    model: str = Field("black-forest-labs/FLUX.1-dev",
                       description="Model to use for generation")
    num_images: int = Field(1, description="Number of images to generate", ge=1, le=4)
    folder_id: Optional[str] = None
    disable_safety_checker: bool = Field(True, description="Whether to disable the safety checker")

class ImageGenerationResponse(BaseModel):
    task_id: str = Field(..., description="ID of the generation task")
    status: str = Field("processing", description="Status of the generation task")

class GeneratedImage(BaseModel):
    id: str
    url: str
    prompt: str
    model: str
    created_at: datetime

class ImageGenerationResult(BaseModel):
    images: List[GeneratedImage]
    status: str = Field("completed", description="Status of the generation task")

# Helper function to call together.ai API
async def call_together_api(endpoint: str, data: Dict, method: str = "POST"):
    if not TOGETHER_API_KEY:
        raise HTTPException(status_code=500, detail="TOGETHER_API_KEY not configured")
    
    # If we have the Together client and it's an image generation request, use it
    if TOGETHER_CLIENT_AVAILABLE and together_client and endpoint == "images/generations":
        try:
            # Map the data to the expected format for the official client
            prompt = data.get("prompt", "")
            model = "black-forest-labs/FLUX.1-dev"  # Use the correct model ID
            n = data.get("n", 1)
            steps = data.get("steps", 10)  # Default to 10 steps
            width = data.get("width", 1024)  # Default width
            height = data.get("height", 1024)  # Default height
            disable_safety_checker = data.get("disable_safety_checker", True)  # Add safety checker option
            
            # Call the client in a sync manner (create_task would be better in production)
            response = together_client.images.generate(
                prompt=prompt,
                model=model,
                n=n,
                steps=steps,
                width=width,
                height=height,
                disable_safety_checker=disable_safety_checker,  # Pass the parameter
                response_format="b64_json"  # Get base64 encoded images
            )
            
            # Transform response to match the expected format
            result = {"data": []}
            for item in response.data:
                # Create a data URL from base64 data
                image_url = f"data:image/png;base64,{item.b64_json}"
                result["data"].append({"url": image_url})
            
            return result
            
        except Exception as e:
            logger.error(f"Together client error: {str(e)}")
            # Fall back to HTTP request method
    
    # Fallback to HTTP requests method
    url = f"{TOGETHER_API_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Update model name if it's "flux" to the correct format
    if endpoint == "images/generations" and data.get("model") == "flux":
        data["model"] = "black-forest-labs/FLUX.1-dev"
    
    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=data, headers=headers)
            elif method == "GET":
                response = await client.get(url, params=data, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {"error": "Unknown error"}
                error_message = error_data.get("error", {}).get("message", "API call failed") if isinstance(error_data.get("error"), dict) else error_data.get("error", "API call failed")
                logger.error(f"Together API error: {error_message}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_message
                )
            
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"API request failed: {str(e)}")

# Background task for image generation
async def generate_image_task(
    task_id: str,
    api_data: Dict[str, Any], 
    user_id: str,
    folder_id: Optional[str],
    db: Database
):
    try:
        logger.info(f"Starting image generation task {task_id}")
        
        # Call together.ai API
        result = await call_together_api("images/generations", api_data)
        
        # Process the result
        now = datetime.now(timezone.utc)
        generated_images = []
        
        for i, img_data in enumerate(result.get("data", [])):
            image_url = img_data.get("url")
            
            if image_url:
                # Generate a unique ID
                image_id = str(uuid.uuid4())
                
                # Store in assets table
                asset_query = """
                INSERT INTO mo_assets (
                    id, name, type, url, content_type, file_size, folder_id, 
                    created_by, processing_status, metadata, is_deleted, created_at, updated_at,
                    original_name
                ) VALUES (
                    :id, :name, :type, :url, :content_type, :file_size, :folder_id,
                    :created_by, :processing_status, :metadata, false, :created_at, :created_at,
                    :original_name
                )
                """
                
                timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')
                name = f"Flux_image_{timestamp}_{i+1}.png"
                metadata = {
                    "prompt": api_data["prompt"],
                    "model": api_data["model"],
                    "source": "together_ai",
                    "generation_task_id": task_id
                }
                
                await db.execute(
                    query=asset_query,
                    values={
                        "id": image_id,
                        "name": name,
                        "type": "image",
                        "url": image_url,
                        "content_type": "image/png",
                        "file_size": 0,  # We don't know the file size yet
                        "folder_id": folder_id,
                        "created_by": user_id,
                        "processing_status": "completed",
                        "metadata": json.dumps(metadata),
                        "created_at": now,
                        "original_name": name  # Set original_name to the same as name
                    }
                )
                
                generated_images.append({
                    "id": image_id,
                    "url": image_url,
                    "prompt": api_data["prompt"],
                    "model": api_data["model"],
                    "created_at": now.isoformat()
                })
        
        # Update task status
        task_query = """
        UPDATE mo_ai_tasks 
        SET status = :status, 
            result = :result,
            completed_at = :completed_at,
            updated_at = :updated_at
        WHERE id = :task_id AND created_by = :user_id
        """
        
        await db.execute(
            query=task_query,
            values={
                "status": "completed",
                "result": json.dumps({"images": generated_images}),
                "completed_at": now,
                "updated_at": now,
                "task_id": task_id,
                "user_id": user_id
            }
        )
        
        logger.info(f"Completed image generation task {task_id} with {len(generated_images)} images")
        
    except Exception as e:
        logger.error(f"Error in image generation task: {str(e)}")
        
        # Update task status to failed
        try:
            await db.execute(
                """
                UPDATE mo_ai_tasks 
                SET status = 'failed', 
                    error = :error,
                    updated_at = :updated_at
                WHERE id = :task_id AND created_by = :user_id
                """,
                {
                    "error": str(e),
                    "updated_at": datetime.now(timezone.utc),
                    "task_id": task_id,
                    "user_id": user_id
                }
            )
        except Exception as db_error:
            logger.error(f"Failed to update task status: {str(db_error)}")

# Create/check mo_ai_tasks table
async def ensure_ai_tasks_table(db: Database):
    try:
        # Check if table exists
        check_query = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_name = 'mo_ai_tasks'
        );
        """
        result = await db.fetch_one(check_query)
        
        if not result or not result[0]:
            # Create the table
            create_query = """
            CREATE TABLE mo_ai_tasks (
                id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(50) NOT NULL,
                parameters JSONB NOT NULL,
                status VARCHAR(20) NOT NULL,
                created_by VARCHAR(255) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                completed_at TIMESTAMP WITH TIME ZONE,
                result JSONB,
                error TEXT
            );
            CREATE INDEX idx_ai_tasks_created_by ON mo_ai_tasks(created_by);
            CREATE INDEX idx_ai_tasks_status ON mo_ai_tasks(status);
            """
            await db.execute(create_query)
            logger.info("Created mo_ai_tasks table")
    except Exception as e:
        logger.error(f"Error ensuring ai_tasks table: {str(e)}")
        # Don't raise exception - let the operation fail more gracefully later if needed

# Endpoint for generating images with Flux
@router.post("/generate-image", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Ensure tasks table exists
        await ensure_ai_tasks_table(db)
        
        # Create a task ID
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Prepare request data for together.ai
        api_data = {
            "prompt": request.prompt,
            "model": "black-forest-labs/FLUX.1-dev",  # Use correct model ID
            "n": request.num_images,
            "steps": 10,  # Default steps parameter
            "disable_safety_checker": request.disable_safety_checker  # Add safety checker option
        }
        
        # Add optional parameters
        if request.negative_prompt:
            api_data["negative_prompt"] = request.negative_prompt
        
        if request.size:
            width, height = map(int, request.size.split("x"))
            api_data["width"] = width
            api_data["height"] = height
            
        logger.info(f"Image generation request with model: {api_data['model']}")
        
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
            "created_by": current_user["uid"],
            "created_at": now,
            "updated_at": now
        }
        
        await db.execute(query=query, values=values)
        
        # Start background task
        background_tasks.add_task(
            generate_image_task,
            task_id,
            api_data,
            current_user["uid"],
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

# Endpoint to check the status of a generation task
@router.get("/generation-task/{task_id}", response_model=ImageGenerationResult)
async def get_generation_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        query = """
        SELECT id, type, parameters, status, result, error, 
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE id = :task_id AND created_by = :user_id
        """
        
        task = await db.fetch_one(
            query=query,
            values={
                "task_id": task_id,
                "user_id": current_user["uid"]
            }
        )
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task_dict = dict(task)
        
        if task_dict["status"] == "completed" and task_dict["result"]:
            # Parse the result JSON
            result_data = json.loads(task_dict["result"])
            
            # Convert the image data to GeneratedImage objects
            images = []
            for img in result_data.get("images", []):
                images.append(GeneratedImage(
                    id=img["id"],
                    url=img["url"],
                    prompt=img["prompt"],
                    model=img["model"],
                    created_at=datetime.fromisoformat(img["created_at"])
                ))
            
            return ImageGenerationResult(
                images=images,
                status=task_dict["status"]
            )
        elif task_dict["status"] == "failed":
            raise HTTPException(
                status_code=400,
                detail=f"Image generation failed: {task_dict.get('error', 'Unknown error')}"
            )
        else:
            # Still processing
            return ImageGenerationResult(
                images=[],
                status=task_dict["status"]
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking generation task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint to list all generation tasks for the user
@router.get("/generation-tasks")
async def list_generation_tasks(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    limit: int = 10,
    offset: int = 0
):
    try:
        query = """
        SELECT id, type, parameters, status, error,
               created_at AT TIME ZONE 'UTC' as created_at,
               completed_at AT TIME ZONE 'UTC' as completed_at
        FROM mo_ai_tasks 
        WHERE created_by = :user_id
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """
        
        tasks = await db.fetch_all(
            query=query,
            values={
                "user_id": current_user["uid"],
                "limit": limit,
                "offset": offset
            }
        )
        
        # Get total count
        count_query = """
        SELECT COUNT(*) FROM mo_ai_tasks WHERE created_by = :user_id
        """
        
        count_result = await db.fetch_one(
            query=count_query,
            values={"user_id": current_user["uid"]}
        )
        
        total_count = count_result[0] if count_result else 0
        
        # Convert to list of dicts and parse parameters
        task_list = []
        for task in tasks:
            task_dict = dict(task)
            if task_dict.get("parameters"):
                task_dict["parameters"] = json.loads(task_dict["parameters"])
            task_list.append(task_dict)
        
        return {
            "tasks": task_list,
            "total": total_count,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error(f"Error listing generation tasks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
