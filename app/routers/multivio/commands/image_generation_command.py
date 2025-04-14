"""
Image generation command implementation for the pipeline pattern.
Updated to use REST-based approach instead of WebSockets.
"""
from .base import Command, CommandFactory
from typing import Dict, Any
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import json

logger = logging.getLogger(__name__)

@CommandFactory.register("image_generation")
class ImageGenerationCommand(Command):
    """Command for generating images."""
    
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        Determine if this command should execute based on context.
        """
        # Check if the intent is present
        intents = context.get("intents", {})
        if "image_generation" in intents:
            return intents["image_generation"]["confidence"] > 0.3
            
        # Check message for image generation keywords
        message = context.get("message", "")
        if not message:
            return False
            
        image_keywords = [
            "create an image", "generate an image", "draw", "picture of",
            "image of", "make an image", "show me an image"
        ]
        return any(keyword in message.lower() for keyword in image_keywords)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the image generation command.
        """
        # Get image prompt from context
        intents = context.get("intents", {})
        if "image_generation" in intents and "prompt" in intents["image_generation"]:
            prompt = intents["image_generation"]["prompt"]
        else:
            # Extract prompt from message
            message = context.get("message", "")
            # Look for common patterns
            pattern = r"(?:create|generate|make|draw|show me)(?:\s+an?)?\s+(?:image|picture)(?:\s+of)?\s+(.*)"
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                prompt = match.group(1).strip()
            else:
                # Use full message as prompt if no pattern matches
                prompt = message
        
        logger.info(f"ImageGenerationCommand executing with prompt: '{prompt}'")
        
        # Get needed dependencies from context
        db = context.get("db")
        background_tasks = context.get("background_tasks")
        current_user = context.get("current_user")
        conversation_id = context.get("conversation_id")
        
        if not all([db, background_tasks, current_user]):
            error_msg = "Missing required dependencies: db, background_tasks, or current_user"
            logger.error(error_msg)
            if "errors" not in context:
                context["errors"] = []
            context["errors"].append({
                "command": self.name,
                "error": error_msg
            })
            return context
        
        try:
            # ENHANCEMENT: Check for recently generated images with similar prompt from the same user
            recent_time = datetime.now(timezone.utc) - timedelta(hours=24)  # Look back 24 hours
            similar_images_query = """
            SELECT t.id, t.result
            FROM mo_ai_tasks t
            WHERE t.type = 'image_generation'
              AND t.created_by = :user_id
              AND t.status = 'completed'
              AND t.created_at > :recent_time
              AND t.result IS NOT NULL
              AND t.parameters::text ILIKE :prompt_pattern
            ORDER BY t.created_at DESC
            LIMIT 1
            """
            
            # Use SQL pattern matching to find similar prompts
            prompt_pattern = f"%{prompt}%"
            
            similar_image = await db.fetch_one(
                query=similar_images_query,
                values={
                    "user_id": current_user["uid"],
                    "recent_time": recent_time,
                    "prompt_pattern": prompt_pattern
                }
            )
            
            # Check if we found a similar image we can reuse
            if similar_image and similar_image["result"]:
                try:
                    # Parse the result as JSON
                    result_data = json.loads(similar_image["result"])
                    if "images" in result_data and len(result_data["images"]) > 0:
                        similar_image_data = result_data["images"][0]
                        image_url = similar_image_data.get("url")
                        image_id = similar_image_data.get("id")
                        
                        if image_url and image_id:
                            logger.info(f"Found similar previously generated image: {image_id}")
                            
                            # Add to context that we're reusing an image
                            context["image_generation"] = {
                                "task_id": similar_image["id"],
                                "prompt": prompt,
                                "status": "completed",
                                "image_url": image_url,
                                "image_id": image_id,
                                "reused": True
                            }
                            
                            # Add to results collection with image URL already available
                            context["results"].append({
                                "type": "image_generation",
                                "task_id": similar_image["id"],
                                "prompt": prompt,
                                "status": "completed",
                                "image_url": image_url,
                                "image_id": image_id,
                                "reused": True,
                                "poll_endpoint": None  # No polling needed for reused image
                            })
                            
                            # Return context - we don't need to generate a new image
                            return context
                except Exception as e:
                    logger.error(f"Error processing similar image: {str(e)}")
                    # Continue with normal flow if we can't reuse
            
            # Create a task ID for new image generation
            task_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            
            # Prepare API data
            api_data = {
                "prompt": prompt,
                "model": "flux",  # Use default model
                "n": 1,  # Generate 1 image
                "disable_safety_checker": True  # Add safety checker option
            }
            
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
                    "prompt": prompt,
                    "model": "flux",
                    "num_images": 1,
                    "disable_safety_checker": True
                }),
                "status": "processing",
                "created_by": current_user["uid"],
                "created_at": now,
                "updated_at": now
            }
            
            await db.execute(query=query, values=values)
            
            # Import the image generation task to avoid circular imports
            from app.routers.multivio.together_router import generate_image_task
            
            # Start background task
            background_tasks.add_task(
                generate_image_task,
                task_id,
                api_data,
                current_user["uid"],
                None,  # No folder_id for chat-based images
                db,
                conversation_id,
                None  # No message_id
            )
            
            # Add to context
            context["image_generation"] = {
                "task_id": task_id,
                "prompt": prompt,
                "status": "processing",
                "poll_endpoint": f"/api/v1/pipeline/image/{task_id}"  # Use the compatible endpoint
            }
            
            # Add to results collection
            context["results"].append({
                "type": "image_generation",
                "task_id": task_id,
                "prompt": prompt,
                "status": "processing",
                "poll_endpoint": f"/api/v1/pipeline/image/{task_id}"  # Use the compatible endpoint
            })
            
            return context
            
        except Exception as e:
            logger.error(f"Error in ImageGenerationCommand: {str(e)}")
            
            # Add error to context
            if "errors" not in context:
                context["errors"] = []
                
            context["errors"].append({
                "command": self.name,
                "error": str(e)
            })
            
            return context
