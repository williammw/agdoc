from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from app.dependencies import get_current_user, get_database
from databases import Database
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import httpx
import logging
import traceback
from datetime import datetime, timezone
import json
import uuid
import base64
import tempfile
import boto3

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

# Configure R2 client
s3_client = boto3.client('s3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name='weur')
bucket_name = 'multivio'

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
            steps = data.get("steps", 24)  # Default to 10 steps
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
    db: Database,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None
):
    try:
        logger.info(f"Starting image generation task {task_id}")
        
        # Call together.ai API
        result = await call_together_api("images/generations", api_data)
        
        # Process the result
        now = datetime.now(timezone.utc)
        generated_images = []
        
        # Generate timestamp for folder structure
        timestamp_folder = now.strftime('%Y/%m/%d')
        
        for i, img_data in enumerate(result.get("data", [])):
            image_url = img_data.get("url")
            
            if image_url:
                # Generate a unique ID
                image_id = str(uuid.uuid4())
                timestamp_file = now.strftime('%Y-%m-%d_%H-%M-%S')
                name = f"Flux_image_{timestamp_file}_{i+1}.png"
                
                # Check if it's a base64 data URL
                if image_url.startswith('data:image/'):
                    try:
                        # Extract the base64 data
                        base64_data = image_url.split(',')[1]
                        image_data = base64.b64decode(base64_data)
                        
                        # Define the path in R2
                        r2_key = f"flux-images/{user_id}/{timestamp_folder}/{image_id}.png"
                        
                        # Create a temporary file for the image
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                            temp_file.write(image_data)
                            temp_file_path = temp_file.name
                        
                        try:
                            # Upload the file to R2
                            with open(temp_file_path, 'rb') as file_to_upload:
                                s3_client.upload_fileobj(
                                    file_to_upload,
                                    bucket_name,
                                    r2_key,
                                    ExtraArgs={
                                        "ContentType": "image/png", 
                                        "ACL": "public-read"
                                    }
                                )
                            
                            # Update the image URL to the R2 URL
                            image_url = f"https://{CDN_DOMAIN}/{r2_key}"
                            logger.info(f"Uploaded image to R2: {image_url}")
                            
                            # Get file size
                            file_size = os.path.getsize(temp_file_path)
                        finally:
                            # Clean up the temporary file
                            os.unlink(temp_file_path)
                    except Exception as e:
                        logger.error(f"Error uploading to R2: {str(e)}")
                        # Continue with the base64 URL if upload fails
                        file_size = len(image_data) if 'image_data' in locals() else 0
                else:
                    file_size = 0  # We don't know the file size
                
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
                        "file_size": file_size,
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
        
        # Update the conversation message if we have conversation_id and message_id
        if conversation_id and message_id and generated_images:
            try:
                # Use the first generated image for the conversation
                first_image = generated_images[0]
                image_url = first_image.get("url")
                prompt = first_image.get("prompt", "")
                
                logger.info(f"Updating conversation {conversation_id}, message {message_id} with image URL: {image_url}")
                
                # Create a message that references the image
                # Use markdown image syntax: ![alt text](url)
                message_content = f"![Generated image for: {prompt}]({image_url})"
                
                # Create metadata with image information
                metadata = {
                    "is_image": True,
                    "image_task_id": task_id,
                    "image_id": first_image.get("id"),
                    "image_url": image_url,
                    "prompt": prompt,
                    "status": "completed"
                }
                
                # Check if various columns exist
                check_image_url_query = """
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'mo_llm_messages' AND column_name = 'image_url'
                """
                has_image_url = await db.fetch_one(check_image_url_query)
                
                check_metadata_query = """
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'mo_llm_messages' AND column_name = 'metadata'
                """
                has_metadata = await db.fetch_one(check_metadata_query)
                
                check_updated_at_query = """
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'mo_llm_messages' AND column_name = 'updated_at'
                """
                has_updated_at = await db.fetch_one(check_updated_at_query)
                
                # First check if the message exists
                check_msg_query = "SELECT id FROM mo_llm_messages WHERE id = :message_id AND conversation_id = :conversation_id"
                existing_msg = await db.fetch_one(
                    query=check_msg_query,
                    values={
                        "message_id": message_id,
                        "conversation_id": conversation_id
                    }
                )
                
                if not existing_msg:
                    logger.warning(f"Message {message_id} not found in conversation {conversation_id}. Creating new message.")
                    # If message doesn't exist, create it
                    insert_fields = [
                        "id", "conversation_id", "role", "content", "created_at", "metadata"
                    ]
                    insert_values = {
                        "id": message_id,
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": message_content,
                        "created_at": now,
                        "metadata": json.dumps(metadata)
                    }
                    
                    # Add image_url if the column exists
                    if has_image_url:
                        insert_fields.append("image_url")
                        insert_values["image_url"] = image_url
                    
                    # Build dynamic query based on available columns
                    fields_str = ", ".join(insert_fields)
                    placeholders_str = ", ".join([f":{field}" for field in insert_fields])
                    
                    insert_query = f"""
                    INSERT INTO mo_llm_messages (
                        {fields_str}
                    ) VALUES (
                        {placeholders_str}
                    )
                    """
                    
                    await db.execute(query=insert_query, values=insert_values)
                else:
                    # Update the existing message with appropriate fields
                    update_fields = ["content"]
                    update_values = {
                        "content": message_content,
                        "message_id": message_id,
                        "conversation_id": conversation_id
                    }
                    
                    # Log the update operation to help debug any issues
                    logger.info(f"Updating message {message_id} in conversation {conversation_id} with image content")
                    
                    # Add metadata if the column exists
                    if has_metadata:
                        update_fields.append("metadata")
                        update_values["metadata"] = json.dumps(metadata)
                    
                    # Add image_url if the column exists
                    if has_image_url:
                        update_fields.append("image_url")
                        update_values["image_url"] = image_url
                    
                    # Add updated_at if the column exists
                    if has_updated_at:
                        update_fields.append("updated_at")
                        update_values["updated_at"] = now
                    
                    # Build the update query dynamically
                    set_clause = ", ".join([f"{field} = :{field}" for field in update_fields])
                    update_query = f"""
                    UPDATE mo_llm_messages 
                    SET {set_clause}
                    WHERE id = :message_id AND conversation_id = :conversation_id
                    """
                    
                    await db.execute(query=update_query, values=update_values)
                
                logger.info(f"Successfully updated conversation message with image URL and metadata")
            except Exception as e:
                logger.error(f"Error updating conversation message: {str(e)}")
                logger.error(traceback.format_exc())
                # Continue even if message update fails
        
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
            "steps":24,  # Default steps parameter
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
