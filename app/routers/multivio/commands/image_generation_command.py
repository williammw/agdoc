"""
Image generation command implementation for the pipeline pattern.
"""
from .base import Command, CommandFactory
from typing import Dict, Any
import logging
import re
import uuid
from datetime import datetime, timezone

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
            # Create a task ID
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
                "parameters": "{" +
                    f'"prompt": "{prompt}", ' +
                    f'"model": "flux", ' +
                    f'"num_images": 1, ' +
                    f'"disable_safety_checker": true' +
                "}",
                "status": "processing",
                "created_by": current_user["uid"],
                "created_at": now,
                "updated_at": now
            }
            
            await db.execute(query=query, values=values)
            
            # Store message ID for later reference
            message_id = None
            
            # Record the message in conversation if conversation_id is provided
            if conversation_id:
                try:
                    # Add assistant message (placeholder)
                    message_id = str(uuid.uuid4())
                    
                    # Check if the table has an image_url column
                    check_image_url_query = """
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'mo_llm_messages' AND column_name = 'image_url'
                    """
                    has_image_url = await db.fetch_one(check_image_url_query)
                    
                    # Determine columns and values based on schema
                    insert_fields = [
                        "id", "conversation_id", "role", "content", "created_at", "metadata"
                    ]
                    
                    insert_values = {
                        "id": message_id,
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": f"Generating image of {prompt}...",
                        "created_at": now,
                        "metadata": "{" +
                            f'"is_image": true, ' +
                            f'"image_task_id": "{task_id}", ' +
                            f'"prompt": "{prompt}", ' +
                            f'"status": "generating"' +
                        "}"
                    }
                    
                    # Add image_url placeholder if the column exists
                    if has_image_url:
                        insert_fields.append("image_url")
                        # Will be updated when image is ready
                        insert_values["image_url"] = "pending" 
                        
                    # Build dynamic query
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
                except Exception as e:
                    logger.error(f"Error recording messages in stream chat: {str(e)}")
                    # Continue even if message recording fails
            
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
                message_id
            )
            
            # Add to context
            context["image_generation"] = {
                "task_id": task_id,
                "prompt": prompt,
                "status": "processing"
            }
            
            # Add to results collection
            context["results"].append({
                "type": "image_generation",
                "task_id": task_id,
                "prompt": prompt,
                "status": "processing"
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
