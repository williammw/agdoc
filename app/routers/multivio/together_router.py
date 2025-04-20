from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from app.routers.ws_router import broadcast_to_conversation
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
import asyncio

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
    message_id: Optional[str] = None,
    streaming_generator = None
):
    try:
        logger.info(f"Starting image generation task {task_id}")
        
        # Update to 10% progress stage
        try:
            # Create a unique path for this stage
            timestamp_folder = datetime.now(timezone.utc).strftime('%Y/%m/%d')
            stage_path = f"generations/{task_id}/10_percent.png"
            
            # Update stage record
            stage_query = """
            INSERT INTO mo_image_stages
            (task_id, stage_number, completion_percentage, image_path, image_url)
            VALUES (:task_id, 2, 10, :image_path, NULL)
            ON CONFLICT (task_id, stage_number) 
            DO UPDATE SET completion_percentage = 10, image_path = :image_path
            """
            await db.execute(
                query=stage_query,
                values={
                    "task_id": task_id,
                    "image_path": stage_path
                }
            )
            
            # Update main task status
            update_query = """
            UPDATE mo_ai_tasks 
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = :task_id
            """
            await db.execute(query=update_query, values={"task_id": task_id})
        except Exception as e:
            logger.error(f"Error updating 10% stage: {str(e)}")
        
        # Simulate initial processing time (in production this would be actual processing time)
        await asyncio.sleep(1)
        
        # Update to 50% progress stage
        try:
            # Create a unique path for this stage
            stage_path = f"generations/{task_id}/50_percent.png"
            
            # Update stage record
            stage_query = """
            INSERT INTO mo_image_stages
            (task_id, stage_number, completion_percentage, image_path, image_url)
            VALUES (:task_id, 3, 50, :image_path, NULL)
            ON CONFLICT (task_id, stage_number) 
            DO UPDATE SET completion_percentage = 50, image_path = :image_path
            """
            await db.execute(
                query=stage_query,
                values={
                    "task_id": task_id,
                    "image_path": stage_path
                }
            )
        except Exception as e:
            logger.error(f"Error updating 50% stage: {str(e)}")
        
        # Simulate more processing time
        await asyncio.sleep(2)
        
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
                        "original_name": name
                    }
                )
                
                generated_images.append({
                    "id": image_id,
                    "url": image_url,
                    "prompt": api_data["prompt"],
                    "model": api_data["model"],
                    "created_at": now.isoformat()
                })
                
                # Update the 100% progress stage
                try:
                    final_stage_query = """
                    INSERT INTO mo_image_stages
                    (task_id, stage_number, completion_percentage, image_path, image_url)
                    VALUES (:task_id, 4, 100, :image_path, :image_url)
                    ON CONFLICT (task_id, stage_number) 
                    DO UPDATE SET completion_percentage = 100, 
                                 image_path = :image_path,
                                 image_url = :image_url
                    """
                    await db.execute(
                        query=final_stage_query,
                        values={
                            "task_id": task_id,
                            "image_path": r2_key,
                            "image_url": image_url
                        }
                    )
                except Exception as e:
                    logger.error(f"Error updating final stage: {str(e)}")
        
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
                
                # IMPORTANT: Update the database FIRST before sending WebSocket notification
                # Create a message that references the image
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
                
                # Flag to track if update succeeded
                update_succeeded = False
                
                if not existing_msg:
                    logger.warning(f"Message {message_id} not found in conversation {conversation_id}. Creating new message.")
                    # If message doesn't exist, create it
                    
                    # Use detailed logging to track what's happening
                    logger.info(f"Attempting to update message {message_id} in conversation {conversation_id} with image URL: {image_url}")
                    
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
                    update_succeeded = True
                    
                    # Add this after the database operation
                    logger.info(f"Successfully created new message with image: message_id={message_id}, image_url={image_url}")
                    
                    # Force a notification to ensure frontend knows about the new message
                    try:
                        await broadcast_to_conversation(
                            conversation_id,
                            {
                                "type": "message_created",
                                "messageId": message_id,
                                "message": {
                                    "id": message_id,
                                    "role": "assistant",
                                    "content": message_content,
                                    "metadata": metadata,
                                    "image_url": image_url,
                                    "created_at": now.isoformat()
                                }
                            }
                        )
                        logger.info(f"Sent message_created WebSocket notification for new image message in conversation {conversation_id}")
                    except Exception as ws_error:
                        logger.error(f"WebSocket notification error for new message: {str(ws_error)}")
                else:
                    # Update the existing message with appropriate fields
                    update_fields = ["content"]
                    update_values = {
                        "content": message_content,
                        "message_id": message_id,
                        "conversation_id": conversation_id
                    }
                    
                    # Use detailed logging to track what's happening
                    logger.info(f"Attempting to update message {message_id} in conversation {conversation_id} with image URL: {image_url}")
                    
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
                    update_succeeded = True
                    
                    # Add this after the database operation
                    logger.info(f"Successfully updated message with image: message_id={message_id}, image_url={image_url}")
                    
                    # Force a notification to ensure frontend knows about the update
                    try:
                        await broadcast_to_conversation(
                            conversation_id,
                            {
                                "type": "message_update",
                                "messageId": message_id,
                                "updates": {
                                    "content": message_content,
                                    "metadata": metadata,
                                    "image_url": image_url
                                }
                            }
                        )
                        logger.info(f"Sent message_update WebSocket notification for updated image in conversation {conversation_id}")
                    except Exception as ws_error:
                        logger.error(f"WebSocket notification error for message update: {str(ws_error)}")
                
                # Send additional notification even though we are using REST polling as a fallback mechanism
                # This helps ensure the frontend gets notified about the image being ready
                if update_succeeded:
                    try:
                        # Create an image_ready event to notify clients
                        image_data = {
                            "type": "image_ready",
                            "task_id": task_id,
                            "message_id": message_id,
                            "conversation_id": conversation_id,
                            "image_url": image_url,
                            "image_id": first_image.get("id"),
                            "prompt": prompt
                        }
                        
                        # Broadcast to the conversation
                        await broadcast_to_conversation(conversation_id, image_data)
                        logger.info(f"Sent image_ready WebSocket notification for task {task_id}")
                    except Exception as ws_error:
                        logger.error(f"WebSocket notification error for image_ready: {str(ws_error)}")
                
                logger.info(f"Successfully updated conversation message with image URL and metadata")
            except Exception as e:
                logger.error(f"Error updating message with image: {str(e)}")
                logger.error(traceback.format_exc())
                # Continue even if message update fails
        
        # Send completed status through streaming generator if available
        if streaming_generator:
            try:
                for img in generated_images:
                    # We need to handle various formats to ensure compatibility
                    try:
                        # 1. First signal in the old format for compatibility
                        await streaming_generator.asend({
                            "type": "image_generation",
                            "status": "completed",
                            "task_id": task_id,
                            "image_url": img["url"],
                            "image_id": img["id"],
                            "prompt": img["prompt"],
                            "message_id": message_id
                        })
                        
                        # Add small delay between sends
                        await asyncio.sleep(0.1)
                        
                        # 2. Second signal in the dedicated image_ready format
                        await streaming_generator.asend({
                            "type": "image_ready",
                            "task_id": task_id,
                            "image_url": img["url"],
                            "image_id": img["id"],
                            "prompt": img["prompt"],
                            "message_id": message_id
                        })
                        
                        # Add small delay between sends
                        await asyncio.sleep(0.1)
                        
                        # 3. Third signal as a legacy format for backward compatibility
                        await streaming_generator.asend({
                            "image_generation_complete": True,
                            "image_url": img["url"],
                            "task_id": task_id,
                            "message_id": message_id
                        })
                    except Exception as send_error:
                        logger.error(f"Error sending image completion event: {str(send_error)}")
                        # Continue to the next image even if one send fails
                    
                    logger.info(f"Sent completed image signals to streaming generator for task {task_id}")
                    
                    # Small delay between signals to prevent overwhelming
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error sending completion to streaming generator: {str(e)}")
                
        logger.info(f"Completed image generation task {task_id} with {len(generated_images)} images")
        
    except Exception as e:
        logger.error(f"Error in image generation task: {str(e)}")
        
        # Notify through streaming generator if available
        if streaming_generator:
            try:
                # Send failure signal in multiple formats for redundancy
                try:
                    # 1. Standard format
                    await streaming_generator.asend({
                        "type": "image_generation",
                        "status": "failed",
                        "task_id": task_id,
                        "error": str(e)
                    })
                    
                    # Add small delay between sends
                    await asyncio.sleep(0.1)
                    
                    # 2. Dedicated image_failed event
                    await streaming_generator.asend({
                        "type": "image_failed",
                        "task_id": task_id,
                        "error": str(e)
                    })
                    
                    # Add small delay between sends
                    await asyncio.sleep(0.1)
                    
                    # 3. Legacy format
                    await streaming_generator.asend({
                        "image_generation_failed": True,
                        "task_id": task_id,
                        "error": str(e)
                    })
                except Exception as send_error:
                    logger.error(f"Error sending failure notification: {str(send_error)}")
                    # Continue even if sends fail
                
                logger.info(f"Sent 'failed' status signals to streaming generator for task {task_id}")
            except Exception as gen_error:
                logger.error(f"Error sending failure to streaming generator: {str(gen_error)}")
        
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
            
            # Add a failed stage entry
            try:
                failed_stage_query = """
                INSERT INTO mo_image_stages
                (task_id, stage_number, completion_percentage, image_path, image_url)
                VALUES (:task_id, 99, 0, '', NULL)
                ON CONFLICT (task_id, stage_number) DO NOTHING
                """
                await db.execute(
                    query=failed_stage_query,
                    values={"task_id": task_id}
                )
            except Exception as stage_error:
                logger.error(f"Error adding failed stage: {str(stage_error)}")
            
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
    db: Database = Depends(get_database),
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None
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
        
        # Create placeholder message if we have conversation_id and message_id
        if conversation_id and message_id:
            try:
                # Create metadata with pending status
                metadata = {
                    "is_image": True,
                    "image_task_id": task_id,
                    "imageGenerationStatus": "pending",
                    "prompt": request.prompt
                }
                
                now = datetime.now(timezone.utc)
                
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
                    # Create a new message with pending status
                    insert_query = """
                    INSERT INTO mo_llm_messages (
                        id, conversation_id, role, content, created_at, metadata
                    ) VALUES (
                        :id, :conversation_id, :role, :content, :created_at, :metadata
                    )
                    """
                    
                    await db.execute(
                        query=insert_query,
                        values={
                            "id": message_id,
                            "conversation_id": conversation_id,
                            "role": "assistant",
                            "content": f"Generating image of {request.prompt}...",
                            "created_at": now,
                            "metadata": json.dumps(metadata)
                        }
                    )
                else:
                    # Update existing message with pending status
                    update_query = """
                    UPDATE mo_llm_messages
                    SET content = :content,
                        metadata = :metadata
                    WHERE id = :message_id AND conversation_id = :conversation_id
                    """
                    
                    await db.execute(
                        query=update_query,
                        values={
                            "content": f"Generating image of {request.prompt}...",
                            "metadata": json.dumps(metadata),
                            "message_id": message_id,
                            "conversation_id": conversation_id
                        }
                    )
                
                # Send a WebSocket notification about the pending image
                try:
                    await broadcast_to_conversation(
                        conversation_id,
                        {
                            "type": "message_update",
                            "messageId": message_id,
                            "updates": {
                                "content": f"Generating image of {request.prompt}...",
                                "status": "pending",
                                "metadata": metadata
                            }
                        }
                    )
                    logger.info(f"Sent pending status WebSocket notification for image in conversation {conversation_id}")
                except Exception as ws_error:
                    logger.error(f"WebSocket notification error for pending status: {str(ws_error)}")
            except Exception as e:
                logger.error(f"Error creating pending image message: {str(e)}")
                # Continue even if message creation fails
        
        # Start background task
        background_tasks.add_task(
            generate_image_task,
            task_id,
            api_data,
            current_user["uid"],
            request.folder_id,
            db,
            conversation_id,
            message_id,
            None  # No streaming generator for direct endpoint calls
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
