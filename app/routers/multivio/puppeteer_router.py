# puppeteer_router.py
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from app.dependencies import get_current_user
import logging
from typing import Optional, Dict, Any, List, Callable
import json
import importlib

router = APIRouter(tags=["puppeteer"])
logger = logging.getLogger(__name__)

# Request Models


class NavigateRequest(BaseModel):
    url: HttpUrl


class ScreenshotRequest(BaseModel):
    name: str
    selector: Optional[str] = None
    width: Optional[int] = 800
    height: Optional[int] = 600


class ClickRequest(BaseModel):
    selector: str


class FillRequest(BaseModel):
    selector: str
    value: str


class SelectRequest(BaseModel):
    selector: str
    value: str


class HoverRequest(BaseModel):
    selector: str


class EvaluateRequest(BaseModel):
    script: str


class WebSearchAndScrapeRequest(BaseModel):
    query: str
    count: Optional[int] = 5
    scrape_count: Optional[int] = 1
    selectors: Optional[List[str]] = [
        "article", "main", ".content", "#content"]

# Response Models


class PuppeteerResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ScrapedContent(BaseModel):
    url: str
    title: str
    content: str
    html: Optional[str] = None
    error: Optional[str] = None


class WebSearchAndScrapeResponse(BaseModel):
    search_results: List[Dict[str, Any]]
    scraped_content: List[ScrapedContent]

# Define a function to safely execute the puppeteer functions


def execute_puppeteer_function(function_name: str, **kwargs):
    """
    This function dynamically accesses and executes the puppeteer functions
    that are available as tools in the system.
    """
    try:
        # Try different ways to access the functions
        # Method 1: Try to import from a module
        try:
            module = importlib.import_module("app.services.puppeteer")
            func = getattr(module, function_name)
            return func(**kwargs)
        except (ImportError, AttributeError):
            pass

        # Method 2: Try to access from the global scope
        try:
            import builtins
            func = getattr(builtins, function_name)
            return func(**kwargs)
        except AttributeError:
            pass

        # Method 3: Look for it in the current globals
        globals_dict = globals()
        if function_name in globals_dict:
            func = globals_dict[function_name]
            return func(**kwargs)

        # If all methods fail, raise an exception
        raise ImportError(f"Cannot find the function {function_name}")

    except Exception as e:
        logger.error(f"Error executing {function_name}: {str(e)}")
        raise ValueError(f"Error executing {function_name}: {str(e)}")


@router.post("/navigate", response_model=PuppeteerResponse)
async def navigate(
    request: NavigateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Navigate to a URL using Puppeteer"""
    try:
        logger.info(f"Navigating to URL: {request.url}")

        # Use the execute_puppeteer_function to call puppeteer_navigate
        result = execute_puppeteer_function(
            "puppeteer_navigate", url=str(request.url))

        return PuppeteerResponse(
            success=True,
            message=f"Successfully navigated to {request.url}",
            data={"url": str(request.url), "result": result}
        )
    except Exception as e:
        logger.error(f"Error navigating to URL: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Navigation failed: {str(e)}")


@router.post("/screenshot", response_model=PuppeteerResponse)
async def take_screenshot(
    request: ScreenshotRequest,
    current_user: dict = Depends(get_current_user)
):
    """Take a screenshot of the current page or a specific element"""
    try:
        logger.info(f"Taking screenshot: {request.name}")

        screenshot_params = {
            "name": request.name,
            "width": request.width,
            "height": request.height
        }

        if request.selector:
            screenshot_params["selector"] = request.selector

        result = execute_puppeteer_function(
            "puppeteer_screenshot", **screenshot_params)

        return PuppeteerResponse(
            success=True,
            message=f"Screenshot taken: {request.name}",
            data={"screenshot_params": screenshot_params, "result": result}
        )
    except Exception as e:
        logger.error(f"Error taking screenshot: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Screenshot failed: {str(e)}")


@router.post("/click", response_model=PuppeteerResponse)
async def click_element(
    request: ClickRequest,
    current_user: dict = Depends(get_current_user)
):
    """Click an element on the page"""
    try:
        logger.info(f"Clicking element: {request.selector}")
        result = execute_puppeteer_function(
            "puppeteer_click", selector=request.selector)

        return PuppeteerResponse(
            success=True,
            message=f"Clicked element: {request.selector}",
            data={"result": result}
        )
    except Exception as e:
        logger.error(f"Error clicking element: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Click operation failed: {str(e)}")


@router.post("/fill", response_model=PuppeteerResponse)
async def fill_input(
    request: FillRequest,
    current_user: dict = Depends(get_current_user)
):
    """Fill an input field"""
    try:
        logger.info(f"Filling input field: {request.selector}")
        result = execute_puppeteer_function(
            "puppeteer_fill", selector=request.selector, value=request.value)

        return PuppeteerResponse(
            success=True,
            message=f"Filled input field: {request.selector}",
            data={"result": result}
        )
    except Exception as e:
        logger.error(f"Error filling input: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fill operation failed: {str(e)}")


@router.post("/select", response_model=PuppeteerResponse)
async def select_option(
    request: SelectRequest,
    current_user: dict = Depends(get_current_user)
):
    """Select an option from a dropdown"""
    try:
        logger.info(f"Selecting option from: {request.selector}")
        result = execute_puppeteer_function(
            "puppeteer_select", selector=request.selector, value=request.value)

        return PuppeteerResponse(
            success=True,
            message=f"Selected option from: {request.selector}",
            data={"result": result}
        )
    except Exception as e:
        logger.error(f"Error selecting option: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Select operation failed: {str(e)}")


@router.post("/hover", response_model=PuppeteerResponse)
async def hover_element(
    request: HoverRequest,
    current_user: dict = Depends(get_current_user)
):
    """Hover over an element"""
    try:
        logger.info(f"Hovering over element: {request.selector}")
        result = execute_puppeteer_function(
            "puppeteer_hover", selector=request.selector)

        return PuppeteerResponse(
            success=True,
            message=f"Hovered over element: {request.selector}",
            data={"result": result}
        )
    except Exception as e:
        logger.error(f"Error hovering element: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Hover operation failed: {str(e)}")


@router.post("/evaluate", response_model=PuppeteerResponse)
async def evaluate_script(
    request: EvaluateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Execute JavaScript in the browser console"""
    try:
        logger.info("Evaluating JavaScript")
        result = execute_puppeteer_function(
            "puppeteer_evaluate", script=request.script)

        return PuppeteerResponse(
            success=True,
            message="JavaScript executed successfully",
            data={"result": result}
        )
    except Exception as e:
        logger.error(f"Error evaluating JavaScript: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"JavaScript execution failed: {str(e)}")


@router.post("/search-and-scrape", response_model=WebSearchAndScrapeResponse)
async def search_and_scrape(
    request: WebSearchAndScrapeRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Search the web and scrape content from top results"""
    try:
        logger.info(f"Performing web search for: {request.query}")

        # Use dynamic import for brave_web_search
        try:
            # Try importing directly
            from app.routers.multivio.brave_search_router import brave_web_search
        except ImportError:
            # If that fails, try using execute function helper
            brave_web_search = lambda **kwargs: execute_puppeteer_function(
                "brave_web_search", **kwargs)

        # Perform the web search
        search_response = brave_web_search(
            query=request.query, count=request.count)

        # Parse the search results - handle different possible formats
        if isinstance(search_response, dict) and "results" in search_response:
            search_results = search_response["results"]
        elif isinstance(search_response, list):
            search_results = search_response
        else:
            search_results = [search_response]

        # Initialize list for scraped content
        scraped_content = []

        # Get the top N results to scrape
        top_results = search_results[:request.scrape_count]

        # For each result, navigate and extract content
        for result in top_results:
            try:
                # Handle different search result formats
                if isinstance(result, dict):
                    url = result.get("url")
                    title = result.get("title")
                else:
                    url = getattr(result, "url", "Unknown URL")
                    title = getattr(result, "title", "Unknown Title")

                # Navigate to the page
                execute_puppeteer_function("puppeteer_navigate", url=url)

                # Extract content - try each selector
                content = ""
                for selector in request.selectors:
                    try:
                        script = f"""
                            const element = document.querySelector('{selector}');
                            if (element) {{ 
                                return element.textContent.trim();
                            }}
                            return null;
                        """
                        extracted = execute_puppeteer_function(
                            "puppeteer_evaluate", script=script)
                        if extracted:
                            content = extracted
                            break
                    except Exception:
                        continue

                # If no content was found with the selectors, try getting all body text
                if not content:
                    content = execute_puppeteer_function("puppeteer_evaluate",
                                                         script="document.body.textContent.trim()")

                # Get HTML for debugging
                html = execute_puppeteer_function("puppeteer_evaluate",
                                                  script="document.documentElement.outerHTML")

                # Take a screenshot for reference (optional)
                screenshot_name = f"search_result_{len(scraped_content)}"
                try:
                    execute_puppeteer_function(
                        "puppeteer_screenshot", name=screenshot_name)
                except Exception as screenshot_error:
                    logger.warning(
                        f"Screenshot failed: {str(screenshot_error)}")

                # Add content to results
                scraped_content.append(ScrapedContent(
                    url=url,
                    title=title,
                    # Limit content size
                    content=content[:10000] if content else "",
                    html=html[:20000] if html else None,  # Limit HTML size
                    error=None
                ))

            except Exception as e:
                logger.error(
                    f"Error scraping content from {url if 'url' in locals() else 'unknown URL'}: {str(e)}")
                # Add error entry
                scraped_content.append(ScrapedContent(
                    url=url if 'url' in locals() else "unknown",
                    title=title if 'title' in locals() else "unknown",
                    content="",
                    error=str(e)
                ))

        return WebSearchAndScrapeResponse(
            search_results=search_results,
            scraped_content=scraped_content
        )

    except Exception as e:
        logger.error(f"Error in search and scrape: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Search and scrape failed: {str(e)}")
