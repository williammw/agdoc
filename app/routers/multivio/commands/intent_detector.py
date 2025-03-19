"""
Intent detection utilities for identifying command types from user messages.
"""
import re
from typing import List, Dict, Any, Set, Tuple
import logging

logger = logging.getLogger(__name__)

# Intent detection patterns
# These are based on the existing patterns from smart_router.py but optimized for multi-intent detection

# Search patterns
SEARCH_PATTERNS = [
    r"(?i)search\s+for",
    r"(?i)search\s+the\s+(web|internet)",  # Removed '\s+for' requirement
    r"(?i)find\s+information\s+(about|on)",
    r"(?i)look\s+up",
    r"(?i)find\s+(me\s+)?(some\s+)?information",
    # Added to match "find me top 10 news"
    r"(?i)find\s+(me\s+)?(some\s+)?(top|best|latest)",
    r"(?i)what\s+are\s+the\s+latest",
    r"(?i)tell\s+me\s+about\s+recent",
    r"(?i)what\s+(is|are|was|were)",
    r"(?i)tell\s+me\s+about",
    r"(?i)where\s+(is|can\s+I\s+find)",
    r"(?i)how\s+(to|do|does|can|could)",
    r"(?i)(latest|recent)\s+news\s+(about|on)",
    r"(?i)who\s+(is|was)",
    r"(?i)when\s+(is|was|did)",
    r"(?i)why\s+(is|are|do|does)",
    r"(?i)(top|best)\s+\d+",  # Added to match "top 10 news"
    # Added to match "news happened in Hong Kong"
    r"(?i)news\s+(about|in|from|happened)",
    r"(?i)news.*?today",  # Added to match "news happened in Hong Kong today"
]

# Local search patterns
LOCAL_SEARCH_PATTERNS = [
    r"(?i)near\s+me",
    r"(?i)nearby",
    r"(?i)in\s+(my|this)\s+area",
    r"(?i)close\s+to",
    r"(?i)restaurants\s+in",
    r"(?i)businesses\s+in",
    r"(?i)places\s+in",
    r"(?i)within\s+\d+\s+(miles|kilometers)",
    r"(?i)stores\s+in",
    r"(?i)services\s+in",
    r"(?i)find\s+a\s+(place|restaurant|store|hotel)",
]

# Image generation patterns
IMAGE_PATTERNS = [
    r"(?i)create\s+(?:an\s+)?image",  # More general pattern without "of"
    r"(?i)generate\s+(?:an\s+)?image",
    r"(?i)show\s+(?:me\s+)?(?:an\s+)?image",
    r"(?i)make\s+(?:an\s+)?image",
    r"(?i)draw\s+(?:an\s+)?image",
    r"(?i)create\s+(?:a\s+)?picture",
    r"(?i)generate\s+(?:a\s+)?picture",
    r"(?i)visualize",
    r"(?i)illustrate",
    r"(?i)image\s+of",  # Even more general pattern
    r"(?i)picture\s+of",
]

# Browser automation / puppeteer patterns
PUPPETEER_PATTERNS = [
    r"(?i)browse\s+(to|the|site)",
    r"(?i)navigate\s+to",
    r"(?i)go\s+to\s+(the\s+)?(website|site|page)",
    r"(?i)visit\s+(the\s+)?(website|site|page)",
    r"(?i)open\s+(the\s+)?(website|site|page)",
    r"(?i)take\s+a\s+screenshot",
    r"(?i)capture\s+(the\s+)?(screen|page)",
    r"(?i)click\s+on",
    r"(?i)interact\s+with",
    r"(?i)fill\s+(in|out)",
    r"(?i)type\s+into",
    r"(?i)scrape\s+(the|this)",
    r"(?i)extract\s+(content|data)",
]

# Social media content patterns
SOCIAL_MEDIA_PATTERNS = [
    # Platform references - add IG as Instagram abbreviation
    r"(?i)\b(facebook|fb|instagram|ig|twitter|x\.com|threads|linkedin|tiktok|youtube)\b",

    # Content types
    r"(?i)\b(post|tweet|reel|story|caption|video)\b",

    # Actions - make more flexible for various phrasings
    r"(?i)(create|write|draft|schedule|make)\s+(a|an|my|some)?\s*(post|tweet|content|update)",
    r"(?i)social\s+media\s+(content|strategy|post|campaign)",
    
    # Platform-specific content
    r"(?i)(instagram|ig|facebook|fb|twitter)\s*(post|story|reel|tweet)",

    # Engagement/metrics references
    r"(?i)(engagement|followers|likes|shares|comments)",

    # Marketing terms
    r"(?i)(hashtag|audience|content\s+calendar|brand\s+voice)",

    # Explicit requests
    r"(?i)help\s+(me|with)\s+(my)?\s+social\s+media",
]

def detect_intents(message: str) -> Dict[str, Dict[str, Any]]:
    """
    Detect multiple intents from a user message.
    
    Args:
        message: The user message to analyze
        
    Returns:
        Dictionary of intent types and their confidence scores/metadata
    """
    intents = {}
    
    # Check for web search intent
    search_score = _calculate_pattern_score(message, SEARCH_PATTERNS)
    if search_score > 0.2:  # Threshold for considering this intent
        search_data = _extract_search_data(message)
        intents["web_search"] = {
            "confidence": search_score,
            "query": search_data.get("query", message),
            "details": search_data
        }
    
    # Check for local search intent
    local_search_score = _calculate_pattern_score(message, LOCAL_SEARCH_PATTERNS)
    if local_search_score > 0.2:
        local_search_data = _extract_local_search_data(message)
        intents["local_search"] = {
            "confidence": local_search_score,
            "query": local_search_data.get("query", message),
            "location": local_search_data.get("location"),
            "details": local_search_data
        }
    
    # Check for image generation intent
    image_score = _calculate_pattern_score(message, IMAGE_PATTERNS)
    if image_score > 0.2:
        image_data = _extract_image_data(message)
        intents["image_generation"] = {
            "confidence": image_score,
            "prompt": image_data.get("prompt", message),
            "details": image_data
        }
    
    # Check for puppeteer/browser automation intent
    puppeteer_score = _calculate_pattern_score(message, PUPPETEER_PATTERNS)
    if puppeteer_score > 0.2:
        puppeteer_data = _extract_puppeteer_data(message)
        intents["puppeteer"] = {
            "confidence": puppeteer_score,
            "url": puppeteer_data.get("url"),
            "details": puppeteer_data
        }
    
    # Check for social media intent
    social_media_score = _calculate_pattern_score(message, SOCIAL_MEDIA_PATTERNS)
    if social_media_score > 0.2:
        social_media_data = _extract_social_media_data(message)
        intents["social_media"] = {
            "confidence": social_media_score,
            "platforms": social_media_data.get("platforms", []),
            "details": social_media_data
        }
    
    # Always include general knowledge with lower confidence as fallback
    if not intents:
        intents["general_knowledge"] = {
            "confidence": 1.0,
            "query": message
        }
    else:
        intents["general_knowledge"] = {
            "confidence": 0.2,  # Low confidence as it's a fallback
            "query": message
        }
    
    return intents

def _calculate_pattern_score(message: str, patterns: List[str]) -> float:
    """
    Calculate a confidence score for a set of patterns.
    
    Args:
        message: The message to analyze
        patterns: List of regex patterns to match
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    matches = 0
    for pattern in patterns:
        if re.search(pattern, message, re.IGNORECASE):
            matches += 1
    
    # Calculate score based on number of matches and pattern set size
    if matches == 0:
        return 0.0
    
    # More matches means higher confidence, but diminishing returns
    return min(0.3 + (matches / len(patterns)) * 0.7, 1.0)
    
def _extract_search_data(message: str) -> Dict[str, Any]:
    """Extract search-related data from the message."""
    # Define search prefixes to look for
    search_prefixes = [
        "search the internet for",
        "search the web for",
        "search for",
        "find information about",
        "find information on",
        "look up",
        "tell me about",
        "what is",
        "what are",
        "how to",
        "how do I",
    ]
    
    # Clean up and lowercase the message
    cleaned_message = message.strip()
    lower_text = cleaned_message.lower()
    
    query = message  # Default to full message
    
    # Look for each prefix
    for prefix in search_prefixes:
        if prefix in lower_text:
            # Extract everything after the prefix
            query_start = lower_text.find(prefix) + len(prefix)
            query = cleaned_message[query_start:].strip()
            
            # Skip "me" if it's the first word after a search command
            if query.lower().startswith("me "):
                query = query[3:].strip()
                
            # Remove trailing punctuation and brackets
            query = re.sub(r'[.!?\[\]\(\)\{\}]+$', '', query).strip()
            break
    
    return {
        "query": query
    }

def _extract_local_search_data(message: str) -> Dict[str, Any]:
    """Extract local search related data from the message."""
    search_data = _extract_search_data(message)
    
    # Try to extract location
    location_patterns = [
        r"(?i)in\s+([A-Za-z\s]+)",
        r"(?i)near\s+([A-Za-z\s]+)",
        r"(?i)around\s+([A-Za-z\s]+)",
        r"(?i)close\s+to\s+([A-Za-z\s]+)"
    ]
    
    location = None
    for pattern in location_patterns:
        match = re.search(pattern, message)
        if match:
            potential_location = match.group(1).strip()
            # Filter out common non-location words
            non_locations = ["me", "here", "there", "my area", "this area"]
            if potential_location.lower() not in non_locations:
                location = potential_location
                break
    
    search_data["location"] = location
    return search_data

def _extract_image_data(message: str) -> Dict[str, Any]:
    """Extract image generation related data from the message."""
    prompt = message  # Default to full message
    
    # Try to extract prompt
    for pattern in IMAGE_PATTERNS:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            # Extract everything after the matched pattern
            prompt_start = match.end()
            prompt = message[prompt_start:].strip()
            # Remove leading 'of' or 'showing' if present
            prompt = re.sub(r'^(of|showing)\s+', '', prompt)
            break
    
    return {
        "prompt": prompt
    }

def _extract_puppeteer_data(message: str) -> Dict[str, Any]:
    """Extract browser automation related data from the message."""
    # Try to extract URL from message
    url_pattern = r'https?://[^\s>)"]+|www\.[^\s>)"]+\.[^\s>)"]+|[a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+(/\S*)?'
    url_match = re.search(url_pattern, message)
    
    url = None
    if url_match:
        url = url_match.group(0)
        # Add protocol if needed
        if url.startswith('www.'):
            url = 'https://' + url
        elif not url.startswith(('http://', 'https://')):
            url = 'https://' + url
    else:
        # Try to extract domain/website name
        domain_pattern = r'\b(?:browse to|navigate to|go to|visit|open)\s+(?:the\s+)?(?:website\s+)?([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(?:\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})*(?:\.[a-zA-Z]{2,})+)'
        domain_match = re.search(domain_pattern, message, re.IGNORECASE)
        if domain_match:
            url = "https://" + domain_match.group(1)
        else:
            # Try to find any word that looks like a domain
            domain_words_pattern = r'\b([a-zA-Z0-9][-a-zA-Z0-9]{0,62}\.(?:com|org|net|edu|gov|io|app|ai|co|me|info|biz))\b'
            domain_words_match = re.search(domain_words_pattern, message)
            if domain_words_match:
                url = "https://" + domain_words_match.group(1)
    
    return {
        "url": url,
        "action": "navigate"  # Default action is navigation, could be expanded for clicks, etc.
    }

def _extract_social_media_data(message: str) -> Dict[str, Any]:
    """Extract social media related data from the message."""
    # Platform detection
    platform_patterns = {
        "facebook": r"(?i)\b(facebook|fb)\b",
        "instagram": r"(?i)\b(instagram|ig)\b",
        "twitter": r"(?i)\b(twitter|x\.com|tweet)\b",
        "threads": r"(?i)\bthreads\b",
        "linkedin": r"(?i)\blinkedin\b",
        "tiktok": r"(?i)\btiktok\b",
        "youtube": r"(?i)\byoutube\b"
    }
    
    platforms = []
    for platform, pattern in platform_patterns.items():
        if re.search(pattern, message, re.IGNORECASE):
            platforms.append(platform)
    
    # If no specific platforms mentioned, return all platforms
    if not platforms:
        platforms = list(platform_patterns.keys())
    
    # Content type detection
    content_type_patterns = {
        "post": r"(?i)\bpost\b",
        "video": r"(?i)\bvideo\b",
        "reel": r"(?i)\breel\b",
        "story": r"(?i)\bstory\b",
        "tweet": r"(?i)\btweet\b"
    }
    
    content_types = []
    for content_type, pattern in content_type_patterns.items():
        if re.search(pattern, message, re.IGNORECASE):
            content_types.append(content_type)
    
    # Default content type if none detected
    if not content_types:
        content_types = ["post"]
    
    return {
        "platforms": platforms,
        "content_types": content_types,
        "prompt": message  # Use the full message as the prompt for content generation
    }

def extract_intent_data(message: str, intent_type: str) -> Dict[str, Any]:
    """
    Extract data for a specific intent type from a message.
    
    Args:
        message: The user message
        intent_type: The type of intent to extract data for
        
    Returns:
        Dictionary with extracted data for the intent
    """
    intent_extractors = {
        "web_search": _extract_search_data,
        "local_search": _extract_local_search_data,
        "image_generation": _extract_image_data,
        "puppeteer": _extract_puppeteer_data,
        "social_media": _extract_social_media_data,
        "general_knowledge": lambda msg: {"query": msg}
    }
    
    if intent_type not in intent_extractors:
        return {"error": f"Unknown intent type: {intent_type}"}
    
    return intent_extractors[intent_type](message)
