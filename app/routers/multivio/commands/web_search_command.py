"""
Web search command implementation for the pipeline pattern.
"""
from .base import Command, CommandFactory
from typing import Dict, Any
import logging
import re
from app.routers.multivio.brave_search_router import (
    perform_web_search, 
    format_web_results_for_llm
)

logger = logging.getLogger(__name__)

@CommandFactory.register("web_search")
class WebSearchCommand(Command):
    """Command for performing web searches."""
    
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        Determine if this command should execute based on context.
        """
        # Check if web search is explicitly enabled
        if context.get("perform_web_search", False):
            return True
            
        # Check if web search is in the intents
        intents = context.get("intents", {})
        if "web_search" in intents:
            return intents["web_search"]["confidence"] > 0.3
            
        # Check message for search-related keywords
        message = context.get("message", "")
        if not message:
            return False
            
        search_keywords = ["search", "find", "look up", "what is", "how to"]
        return any(keyword in message.lower() for keyword in search_keywords)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the web search command.
        """
        # Get search query from context
        intents = context.get("intents", {})
        if "web_search" in intents and "query" in intents["web_search"]:
            query = intents["web_search"]["query"]
        else:
            query = context.get("message", "")
        
        logger.info(f"WebSearchCommand executing with query: '{query}'")
        
        # Perform the search
        try:
            search_results = await perform_web_search(query)
            formatted_results = format_web_results_for_llm(search_results)
            
            # Add results to context
            context["web_search_results"] = {
                "raw": search_results,
                "formatted": formatted_results
            }
            
            # Add to general results collection
            context["results"].append({
                "type": "web_search",
                "query": query,
                "content": formatted_results
            })
            
            # Create a system prompt for the search results
            search_instruction = f"""
            # WEB SEARCH RESULTS

            I've performed a web search for "{query}" and found the following results:

            {formatted_results}

            When answering the user's question:
            1. Use these search results to provide up-to-date information
            2. Cite specific sources from the results when appropriate
            3. If the search results don't provide enough information, clearly state this and use your general knowledge
            4. Synthesize information from multiple sources if relevant
            """
            
            # Add the search system prompt to the context
            if "system_prompts" not in context:
                context["system_prompts"] = []
                
            context["system_prompts"].append({
                "type": "web_search",
                "content": search_instruction
            })
            
            return context
            
        except Exception as e:
            logger.error(f"Error in WebSearchCommand: {str(e)}")
            
            # Add error to context
            if "errors" not in context:
                context["errors"] = []
                
            context["errors"].append({
                "command": self.name,
                "error": str(e)
            })
            
            return context
