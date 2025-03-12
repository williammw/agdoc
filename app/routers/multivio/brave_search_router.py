# brave_search_router.py
import os
import httpx
import logging
import json
from typing import Optional, Dict, Any, List

# Configure logging
logger = logging.getLogger(__name__)

# Environment variables
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1"

async def perform_web_search(query: str, count: int = 10, offset: int = 0) -> Dict[str, Any]:
    """Perform a Brave web search and return results"""
    try:
        if not BRAVE_API_KEY:
            raise ValueError("Brave Search API key not configured")
            
        # Set up headers
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_API_KEY
        }
        
        # Set up query parameters
        params = {
            "q": query,
            "count": min(count, 20),  # Ensure within limits
            "offset": offset
        }
        
        logger.info(f"Performing web search for query: '{query}'")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BRAVE_SEARCH_URL}/web/search",
                headers=headers,
                params=params
            )
            
            if response.status_code != 200:
                logger.error(f"Brave Search API error: {response.text}")
                raise ValueError(f"Search API request failed with status {response.status_code}")
            
            results = response.json()
            logger.info(f"Web search completed successfully with {len(results.get('web', {}).get('results', []))} results")
            return results
            
    except Exception as e:
        logger.error(f"Error in perform_web_search: {str(e)}")
        raise

async def perform_local_search(query: str, location: Optional[str] = None, count: int = 5) -> Dict[str, Any]:
    """Perform a Brave local search for businesses and places"""
    try:
        if not BRAVE_API_KEY:
            raise ValueError("Brave Search API key not configured")
            
        # Set up headers
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_API_KEY
        }
        
        # Set up query parameters
        params = {
            "q": query,
            "count": min(count, 20)  # Ensure within limits
        }
        
        if location:
            params["location"] = location
        
        logger.info(f"Performing local search for query: '{query}' near '{location or 'unspecified location'}'")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BRAVE_SEARCH_URL}/local/search",
                headers=headers,
                params=params
            )
            
            if response.status_code != 200:
                logger.error(f"Brave Local Search API error: {response.text}")
                raise ValueError(f"Local search API request failed with status {response.status_code}")
                
            # Handle fallback to web search if no local results
            results = response.json()
            places = results.get("local", {}).get("places", [])
            logger.info(f"Local search completed with {len(places)} places")
            
            if not places:
                logger.info("No local results found, falling back to web search")
                return await perform_web_search(query, count)
                
            return results
            
    except Exception as e:
        logger.error(f"Error in perform_local_search: {str(e)}")
        raise

def format_web_results_for_llm(search_results: Dict[str, Any]) -> str:
    """Format web search results for LLM consumption with improved structure"""
    if not search_results or "web" not in search_results or "results" not in search_results["web"]:
        return "No search results found."
        
    results = search_results["web"]["results"]
    if not results:
        return "No search results found."
    
    formatted_text = ""
    
    # Add any featured snippet if available
    if "featured_snippet" in search_results["web"]:
        snippet = search_results["web"]["featured_snippet"]
        formatted_text += "FEATURED SNIPPET:\n"
        formatted_text += f"Title: {snippet.get('title', 'No Title')}\n"
        formatted_text += f"Description: {snippet.get('description', 'No description')}\n"
        formatted_text += f"URL: {snippet.get('url', 'No URL')}\n\n"
    
    # Add web results with clear structure
    formatted_text += "SEARCH RESULTS:\n\n"
    
    for i, result in enumerate(results, 1):
        # Get title, ensuring it's not None
        title = result.get('title', 'No Title')
        if not title:
            title = 'No Title'
            
        # Get URL, ensuring it's not None    
        url = result.get('url', 'No URL')
        if not url:
            url = 'No URL'
            
        # Get description, ensuring it's not None
        description = result.get('description', 'No description available')
        if not description:
            description = 'No description available'
        
        # Format the result with clear structure
        formatted_text += f"[{i}] {title}\n"
        formatted_text += f"URL: {url}\n"
        formatted_text += f"Description: {description}\n"
        
        # Add date if available
        if "age" in result:
            formatted_text += f"Date: {result['age']}\n"
            
        formatted_text += "\n"
    
    # Add news results if available
    if "news" in search_results and "results" in search_results["news"]:
        news_results = search_results["news"]["results"]
        if news_results:
            formatted_text += "\nNEWS RESULTS:\n\n"
            for i, news in enumerate(news_results, 1):
                formatted_text += f"[{i}] {news.get('title', 'No Title')}\n"
                formatted_text += f"URL: {news.get('url', 'No URL')}\n"
                formatted_text += f"Source: {news.get('source', 'Unknown source')}\n"
                if "age" in news:
                    formatted_text += f"Published: {news['age']}\n"
                if "description" in news:
                    formatted_text += f"Summary: {news['description']}\n"
                formatted_text += "\n"
    
    return formatted_text

def format_local_results_for_llm(search_results: Dict[str, Any]) -> str:
    """Format local search results for LLM consumption with improved structure"""
    formatted_text = "LOCAL SEARCH RESULTS:\n\n"
    
    # Handle local results
    if "local" in search_results and "places" in search_results["local"]:
        for i, place in enumerate(search_results["local"]["places"], 1):
            formatted_text += f"[{i}] {place.get('name', 'No Name')}\n"
            if place.get("address"):
                formatted_text += f"   Address: {place['address']}\n"
            if place.get("phone"):
                formatted_text += f"   Phone: {place['phone']}\n"
            if place.get("rating"):
                formatted_text += f"   Rating: {place['rating']}/5 ({place.get('reviews_count', 0)} reviews)\n"
            formatted_text += "\n"
    else:
        formatted_text += "No local businesses found.\n\n"
        
        # Include any web results as fallback
        if "web" in search_results and "results" in search_results["web"]:
            formatted_text += "WEB SEARCH RESULTS INSTEAD:\n\n"
            for i, result in enumerate(search_results["web"]["results"], 1):
                formatted_text += f"[{i}] {result.get('title', 'No Title')}\n"
                formatted_text += f"   URL: {result.get('url', 'No URL')}\n"
                formatted_text += f"   {result.get('description', 'No description available')}\n\n"
    
    return formatted_text# brave_search_router.py
import os
import httpx
import logging
import json
from typing import Optional, Dict, Any, List
from fastapi import APIRouter
# Configure logging
logger = logging.getLogger(__name__)

# Environment variables
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1"

router = APIRouter()

async def perform_web_search(query: str, count: int = 10, offset: int = 0) -> Dict[str, Any]:
    """Perform a Brave web search and return results"""
    try:
        if not BRAVE_API_KEY:
            raise ValueError("Brave Search API key not configured")

        # Set up headers
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_API_KEY
        }

        # Set up query parameters
        params = {
            "q": query,
            "count": min(count, 20),  # Ensure within limits
            "offset": offset
        }

        logger.info(f"Performing web search for query: '{query}'")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BRAVE_SEARCH_URL}/web/search",
                headers=headers,
                params=params
            )

            if response.status_code != 200:
                logger.error(f"Brave Search API error: {response.text}")
                raise ValueError(
                    f"Search API request failed with status {response.status_code}")

            results = response.json()
            logger.info(
                f"Web search completed successfully with {len(results.get('web', {}).get('results', []))} results")
            return results

    except Exception as e:
        logger.error(f"Error in perform_web_search: {str(e)}")
        raise


async def perform_local_search(query: str, location: Optional[str] = None, count: int = 5) -> Dict[str, Any]:
    """Perform a Brave local search for businesses and places"""
    try:
        if not BRAVE_API_KEY:
            raise ValueError("Brave Search API key not configured")

        # Set up headers
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_API_KEY
        }

        # Set up query parameters
        params = {
            "q": query,
            "count": min(count, 20)  # Ensure within limits
        }

        if location:
            params["location"] = location

        logger.info(
            f"Performing local search for query: '{query}' near '{location or 'unspecified location'}'")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BRAVE_SEARCH_URL}/local/search",
                headers=headers,
                params=params
            )

            if response.status_code != 200:
                logger.error(f"Brave Local Search API error: {response.text}")
                raise ValueError(
                    f"Local search API request failed with status {response.status_code}")

            # Handle fallback to web search if no local results
            results = response.json()
            places = results.get("local", {}).get("places", [])
            logger.info(f"Local search completed with {len(places)} places")

            if not places:
                logger.info(
                    "No local results found, falling back to web search")
                return await perform_web_search(query, count)

            return results

    except Exception as e:
        logger.error(f"Error in perform_local_search: {str(e)}")
        raise


def format_web_results_for_llm(search_results: Dict[str, Any]) -> str:
    """Format web search results for LLM consumption with improved structure"""
    if not search_results or "web" not in search_results or "results" not in search_results["web"]:
        return "No search results found."

    results = search_results["web"]["results"]
    if not results:
        return "No search results found."

    formatted_text = ""

    # Add any featured snippet if available
    if "featured_snippet" in search_results["web"]:
        snippet = search_results["web"]["featured_snippet"]
        formatted_text += "FEATURED SNIPPET:\n"
        formatted_text += f"Title: {snippet.get('title', 'No Title')}\n"
        formatted_text += f"Description: {snippet.get('description', 'No description')}\n"
        formatted_text += f"URL: {snippet.get('url', 'No URL')}\n\n"

    # Add web results with clear structure
    formatted_text += "SEARCH RESULTS:\n\n"

    for i, result in enumerate(results, 1):
        # Get title, ensuring it's not None
        title = result.get('title', 'No Title')
        if not title:
            title = 'No Title'

        # Get URL, ensuring it's not None
        url = result.get('url', 'No URL')
        if not url:
            url = 'No URL'

        # Get description, ensuring it's not None
        description = result.get('description', 'No description available')
        if not description:
            description = 'No description available'

        # Format the result with clear structure
        formatted_text += f"[{i}] {title}\n"
        formatted_text += f"URL: {url}\n"
        formatted_text += f"Description: {description}\n"

        # Add date if available
        if "age" in result:
            formatted_text += f"Date: {result['age']}\n"

        formatted_text += "\n"

    # Add news results if available
    if "news" in search_results and "results" in search_results["news"]:
        news_results = search_results["news"]["results"]
        if news_results:
            formatted_text += "\nNEWS RESULTS:\n\n"
            for i, news in enumerate(news_results, 1):
                formatted_text += f"[{i}] {news.get('title', 'No Title')}\n"
                formatted_text += f"URL: {news.get('url', 'No URL')}\n"
                formatted_text += f"Source: {news.get('source', 'Unknown source')}\n"
                if "age" in news:
                    formatted_text += f"Published: {news['age']}\n"
                if "description" in news:
                    formatted_text += f"Summary: {news['description']}\n"
                formatted_text += "\n"

    return formatted_text


def format_local_results_for_llm(search_results: Dict[str, Any]) -> str:
    """Format local search results for LLM consumption"""
    formatted_text = "LOCAL SEARCH RESULTS:\n\n"

    # Handle local results
    if "local" in search_results and "places" in search_results["local"]:
        for i, place in enumerate(search_results["local"]["places"], 1):
            formatted_text += f"{i}. {place.get('name', 'No Name')}\n"
            if place.get("address"):
                formatted_text += f"   Address: {place['address']}\n"
            if place.get("phone"):
                formatted_text += f"   Phone: {place['phone']}\n"
            if place.get("rating"):
                formatted_text += f"   Rating: {place['rating']}/5 ({place.get('reviews_count', 0)} reviews)\n"
            formatted_text += "\n"
    else:
        formatted_text += "No local businesses found.\n\n"

        # Include any web results as fallback
        if "web" in search_results and "results" in search_results["web"]:
            formatted_text += "WEB SEARCH RESULTS INSTEAD:\n\n"
            for i, result in enumerate(search_results["web"]["results"], 1):
                formatted_text += f"{i}. {result.get('title', 'No Title')}\n"
                formatted_text += f"   URL: {result.get('url', 'No URL')}\n"
                formatted_text += f"   {result.get('description', 'No description available')}\n\n"

    return formatted_text
