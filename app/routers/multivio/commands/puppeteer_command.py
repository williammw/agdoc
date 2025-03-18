"""
Browser automation/puppeteer command implementation for the pipeline pattern.
"""
from .base import Command, CommandFactory
from typing import Dict, Any, Optional
import logging
import re
import json
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)

@CommandFactory.register("puppeteer")
class PuppeteerCommand(Command):
    """Command for browser automation with puppeteer."""
    
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        Determine if this command should execute based on context.
        """
        # Check if the intent is present
        intents = context.get("intents", {})
        if "puppeteer" in intents:
            return intents["puppeteer"]["confidence"] > 0.3
            
        # Check message for puppeteer keywords
        message = context.get("message", "")
        if not message:
            return False
            
        puppeteer_keywords = [
            "browse to", "navigate to", "go to", "visit", "open website", 
            "take a screenshot", "capture screen", "scrape"
        ]
        return any(keyword in message.lower() for keyword in puppeteer_keywords)
    
    def extract_url(self, message: str) -> Optional[str]:
        """Extract URL from user message"""
        # Try to extract URL from message
        url_pattern = r'https?://[^\s>)"]+|www\.[^\s>)"]+\.[^\s>)"]+|[a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+(/\S*)?'
        url_match = re.search(url_pattern, message)
        if url_match:
            target_url = url_match.group(0)
            # Add protocol if needed
            if target_url.startswith('www.'):
                target_url = 'https://' + target_url
            elif not target_url.startswith(('http://', 'https://')):
                target_url = 'https://' + target_url
            return target_url
            
        # Try to extract domain/website name
        domain_pattern = r'\b(?:browse to|navigate to|go to|visit|open)\s+(?:the\s+)?(?:website\s+)?([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(?:\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})*(?:\.[a-zA-Z]{2,})+)'
        domain_match = re.search(domain_pattern, message, re.IGNORECASE)
        if domain_match:
            return "https://" + domain_match.group(1)
            
        # Try to find any word that looks like a domain
        domain_words_pattern = r'\b([a-zA-Z0-9][-a-zA-Z0-9]{0,62}\.(?:com|org|net|edu|gov|io|app|ai|co|me|info|biz))\b'
        domain_words_match = re.search(domain_words_pattern, message)
        if domain_words_match:
            return "https://" + domain_words_match.group(1)
            
        return None
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the puppeteer command.
        """
        # Get message from context
        message = context.get("message", "")
        
        # Extract URL from message
        target_url = None
        intents = context.get("intents", {})
        if "puppeteer" in intents and "url" in intents["puppeteer"]:
            target_url = intents["puppeteer"]["url"]
        
        if not target_url:
            target_url = self.extract_url(message)
        
        if not target_url:
            # If no URL found, try domain extraction from context
            domain_pattern = r'(?:about|for|of|from)\s+([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(?:\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})*(?:\.[a-zA-Z]{2,})+)'
            domain_match = re.search(domain_pattern, message, re.IGNORECASE)
            if domain_match:
                target_url = "https://" + domain_match.group(1)
            else:
                error_msg = "No URL found in message"
                logger.warning(error_msg)
                context["errors"] = context.get("errors", []) + [{"command": self.name, "error": error_msg}]
                return context
        
        logger.info(f"PuppeteerCommand executing for URL: {target_url}")
        
        try:
            # Import the execute_puppeteer_function from puppeteer_router
            from app.routers.multivio.puppeteer_router import execute_puppeteer_function
            
            # Navigate to the URL
            logger.info(f"Navigating to URL: {target_url}")
            navigation_result = execute_puppeteer_function("puppeteer_navigate", url=target_url)
            
            # Take a screenshot
            screenshot_name = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            screenshot_result = execute_puppeteer_function("puppeteer_screenshot", name=screenshot_name)
            
            # Extract page content using JavaScript
            content_script = """
                function getMainContent() {
                    // Try to find main content
                    const selectors = ['main', 'article', '#content', '.content', '.main-content'];
                    for (const selector of selectors) {
                        const element = document.querySelector(selector);
                        if (element) return element.innerText;
                    }
                    // Fall back to body text
                    return document.body.innerText;
                }
                return getMainContent();
            """
            page_content = execute_puppeteer_function("puppeteer_evaluate", script=content_script)
            
            # Try to get the page title
            title_script = "document.title"
            page_title = execute_puppeteer_function("puppeteer_evaluate", script=title_script)
            
            # Trim content if it's too large
            if page_content and len(page_content) > 8000:
                page_content = page_content[:8000] + "... [content truncated]"
                
            # Create puppeteer context for LLM consumption
            puppeteer_context = f"""
                # WEB PAGE CONTENT

                I've navigated to {target_url} and found the following:

                Title: {page_title or 'Unknown Title'}

                Content:
                {page_content or "No content could be extracted from this page."}

                I've also taken a screenshot named '{screenshot_name}'.

                When answering the user's question:
                1. Use the content from this page to provide information
                2. Describe what I found on the page
                3. If the content doesn't address their question completely, clearly state this
            """
            
            # Add to context
            context["puppeteer_result"] = {
                "url": target_url,
                "title": page_title,
                "content": page_content,
                "screenshot": screenshot_name
            }
            
            # Add to results collection
            context["results"].append({
                "type": "puppeteer",
                "url": target_url,
                "title": page_title,
                "screenshot": screenshot_name
            })
            
            # Add the puppeteer context to system prompts
            if "system_prompts" not in context:
                context["system_prompts"] = []
                
            context["system_prompts"].append({
                "type": "puppeteer",
                "content": puppeteer_context
            })
            
            # Record info in the database if conversation_id is provided
            conversation_id = context.get("conversation_id")
            db = context.get("db")
            if conversation_id and db:
                try:
                    # Add puppeteer system message
                    await db.execute(
                        """
                        INSERT INTO mo_llm_messages (
                            id, conversation_id, role, content, created_at, metadata
                        ) VALUES (
                            :id, :conversation_id, :role, :content, :created_at, :metadata
                        )
                        """,
                        {
                            "id": str(uuid.uuid4()),
                            "conversation_id": conversation_id,
                            "role": "system",
                            "content": puppeteer_context,
                            "created_at": datetime.now(timezone.utc),
                            "metadata": json.dumps({
                                "puppeteer_navigation": True,
                                "url": target_url,
                                "screenshot": screenshot_name
                            })
                        }
                    )
                except Exception as db_error:
                    logger.error(f"Error recording puppeteer message: {str(db_error)}")
            
            return context
            
        except Exception as e:
            logger.error(f"Error in PuppeteerCommand: {str(e)}")
            
            # Add error to context
            if "errors" not in context:
                context["errors"] = []
                
            context["errors"].append({
                "command": self.name,
                "error": str(e)
            })
            
            return context
