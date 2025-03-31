"""
Intent detection utilities for identifying command types from user messages.
Enhanced with multilingual support using transformer models.
"""
import re
from typing import List, Dict, Any, Set, Tuple, Optional, Union
import logging
import torch
import os
from langdetect import detect
import json

# Check if we're in a context where we can import transformers
try:
    from transformers import AutoTokenizer, AutoModel
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logging.warning("Transformers library not available. Multilingual detection disabled.")

logger = logging.getLogger(__name__)

# Intent detection patterns (keeping the original patterns for fallback)
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

# Add calculation patterns
CALCULATION_PATTERNS = [
    r"(?i)what\s+is\s+\d+\s*[\+\-\*\/\^\%]\s*\d+",  # What is 10+10
    r"(?i)calculate\s+\d+\s*[\+\-\*\/\^\%]\s*\d+",  # Calculate 10+10
    r"(?i)compute\s+\d+\s*[\+\-\*\/\^\%]\s*\d+",    # Compute 10+10
    r"(?i)solve\s+\d+\s*[\+\-\*\/\^\%]\s*\d+",      # Solve 10+10
    r"(?i)\d+\s*[\+\-\*\/\^\%]\s*\d+\s*=",          # 10+10 =
    r"(?i)^[\d\s\+\-\*\/\^\%\(\)\.]+$",             # Just a math expression like 10+10
    r"(?i)(\d+)\s*squared",                         # 10 squared
    r"(?i)square\s+root\s+of\s+(\d+)",              # Square root of 10
    r"(?i)cube\s+of\s+(\d+)",                       # Cube of 10
    r"(?i)(\d+)\s*cubed",                           # 10 cubed
    r"(?i)factorial\s+of\s+(\d+)",                  # Factorial of 10
    r"(?i)(\d+)\s*factorial",                       # 10 factorial
    r"(?i)log\s+of\s+(\d+)",                        # Log of 10
    r"(?i)sin\s+of\s+(\d+)",                        # Sin of 10
    r"(?i)cos\s+of\s+(\d+)",                        # Cos of 10
    r"(?i)tan\s+of\s+(\d+)",                        # Tan of 10
]

# Add multilingual intent examples for the transformer model
INTENT_EXAMPLES = {
    "web_search": [
        "search for digital marketing trends",
        "find information about social media algorithms",
        "what are the best practices for SEO",
        "buscar tendencias de marketing digital",
        "rechercher des informations sur les médias sociaux",
        "查找有关社交媒体的信息"
    ],
    "local_search": [
        "find restaurants near me", 
        "locate coffee shops nearby",
        "places to visit in New York",
        "restaurantes cerca de mí",
        "cafés à proximité",
        "在我附近找餐厅"
    ],
    "image_generation": [
        "create an image for my Instagram post",
        "generate a picture of a product showcase",
        "make a visual for my social campaign",
        "generar una imagen para mi publicación",
        "créer une image pour mon post",
        "为我的社交媒体生成图片"
    ],
    "puppeteer": [
        "visit the website example.com",
        "go to facebook and take a screenshot",
        "navigate to twitter and click on login",
        "visitar el sitio web example.com",
        "aller sur facebook et prendre une capture d'écran",
        "导航到twitter并点击登录"
    ],
    "social_media": [
        "create a tweet about our new feature",
        "write an Instagram caption for this photo",
        "help me with a LinkedIn post about industry trends",
        "draft Facebook content for our product launch",
        "crear una publicación para Instagram sobre nuestro producto",
        "rédiger un post LinkedIn sur notre entreprise",
        "为我们的产品发布写一条推文"
    ],
    "conversation": [
        "hello",
        "hi there",
        "hey",
        "good morning",
        "how are you",
        "nice to meet you",
        "what's up",
        "hola",
        "bonjour",
        "你好",
        "help",
        "thank you",
        "thanks"
    ],
    "calculation": [
        "what is 10+10",
        "calculate 5*8",
        "10/2",
        "square root of 16",
        "14 squared",
        "log of 100",
        "15+25-10",
        "3^4",
        "solve 45/5",
        "factorial of 5"
    ]
}

class MultilingualIntentDetector:
    """Multilingual intent detector using transformer models."""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance."""
        if cls._instance is None and TRANSFORMERS_AVAILABLE:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize the multilingual intent detector with pre-trained model."""
        # Only initialize if transformers is available
        if not TRANSFORMERS_AVAILABLE:
            logger.warning("Cannot initialize MultilingualIntentDetector: transformers library not available")
            return
            
        self.model_name = os.environ.get(
            "INTENT_MODEL_NAME", 
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        logger.info(f"Loading multilingual model: {self.model_name}")
        
        try:
            # Load once at initialization time
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name)
            
            # Precompute embeddings for all examples
            self.intent_embeddings = {}
            for intent, examples in INTENT_EXAMPLES.items():
                self.intent_embeddings[intent] = self._encode_texts(examples)
                
            logger.info("Multilingual intent detector initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize multilingual model: {str(e)}")
            # If model fails to load, we'll fall back to regex patterns
            self.model = None
            self.tokenizer = None
            
    def _encode_texts(self, texts):
        """Encode a list of texts to embeddings."""
        # Tokenize
        encoded_input = self.tokenizer(texts, padding=True, truncation=True, 
                                      max_length=128, return_tensors='pt')
        
        # Get model output
        with torch.no_grad():
            model_output = self.model(**encoded_input)
            
        # Mean pooling
        attention_mask = encoded_input['attention_mask']
        token_embeddings = model_output[0]
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        return sum_embeddings / sum_mask
    
    def detect_intents(self, message: str) -> Dict[str, Any]:
        """Detect intents from message using multilingual embeddings."""
        if not self.model or not self.tokenizer:
            logger.warning("Multilingual model not available, falling back to regex")
            return detect_intents_regex(message)
            
        # Try to detect language
        try:
            language = detect(message)
        except:
            language = "unknown"
            
        logger.debug(f"Detected language: {language} for message: '{message[:30]}...'")
        
        # Encode the message
        message_embedding = self._encode_texts([message])
        
        # Calculate similarities with all intent examples
        results = {}
        for intent, embeddings in self.intent_embeddings.items():
            # Calculate cosine similarities
            similarities = torch.nn.functional.cosine_similarity(message_embedding, embeddings)
            max_similarity, idx = torch.max(similarities, dim=0)
            confidence = float(max_similarity)
            
            # Only include intents with sufficient confidence
            if confidence > 0.65:
                # Use existing parameter extraction functions
                intent_data = extract_intent_data(message, intent)
                
                # Add to results
                best_example = INTENT_EXAMPLES[intent][idx.item()]
                results[intent] = {
                    "confidence": confidence,
                    "language": language,
                    "matched_example": best_example,
                    **intent_data
                }
        
        # Special case for calculations - prioritize over web search
        if "calculation" in results and "web_search" in results:
            if _is_simple_math_query(message):
                # Remove web search if this is clearly a calculation
                del results["web_search"]
                # Boost calculation confidence
                results["calculation"]["confidence"] = max(results["calculation"]["confidence"], 0.9)
        
        # If no intents detected with high confidence, fall back to regex
        if not results:
            logger.debug("No high-confidence intents found, falling back to regex")
            return detect_intents_regex(message)
            
        return results
        
    def add_examples(self, intent: str, new_examples: list):
        """Add new examples to an intent and update embeddings."""
        if intent not in INTENT_EXAMPLES:
            INTENT_EXAMPLES[intent] = []
            
        # Add new examples
        INTENT_EXAMPLES[intent].extend(new_examples)
        
        # Update embeddings
        self.intent_embeddings[intent] = self._encode_texts(INTENT_EXAMPLES[intent])
        
        logger.info(f"Added {len(new_examples)} examples to intent '{intent}'")

def detect_intents(message: str) -> Dict[str, Any]:
    """
    Detect multiple intents from a user message using multilingual approach with
    fallback to regex patterns.
    
    Args:
        message: The user message to analyze
        
    Returns:
        Dictionary of intent types and their confidence scores/metadata
    """
    # Try to use multilingual detection if available
    if TRANSFORMERS_AVAILABLE:
        detector = MultilingualIntentDetector.get_instance()
        if detector and hasattr(detector, 'model') and detector.model is not None:
            try:
                intents = detector.detect_intents(message)
                # Add fallback for empty intents or very simple messages
                if not intents and len(message.strip()) < 20:
                    intents["conversation"] = {
                        "confidence": 0.7,
                        "query": message,
                        "type": "general_conversation"
                    }
                return intents
            except Exception as e:
                logger.error(f"Error in multilingual intent detection: {str(e)}")
                logger.info("Falling back to regex intent detection")
    
    # Fallback to regex-based detection
    intents = detect_intents_regex(message)
    
    # Add fallback for empty intents
    if not intents:
        intents["conversation"] = {
            "confidence": 0.7,
            "query": message,
            "type": "general_conversation"
        }
    
    return intents

# Helper to check if this is just a simple math query that shouldn't trigger web search
def _is_simple_math_query(message: str) -> bool:
    """Determine if a message is just a simple math query."""
    message = message.lower().strip()
    
    # Check if it starts with 'what is' and ends with a math expression
    if message.startswith("what is ") or message.startswith("what's "):
        rest = message[8:] if message.startswith("what is ") else message[7:]
        # Check if the rest is mostly just numbers and math operators
        return bool(re.match(r'^[\d\s\+\-\*\/\^\%\(\)\.]+\??$', rest))
        
    # Check if the entire message is just math
    return bool(re.match(r'^[\d\s\+\-\*\/\^\%\(\)\.]+$', message))

def detect_intents_regex(message: str) -> Dict[str, Any]:
    """
    Detect multiple intents from a user message using regex patterns.
    Legacy implementation kept for fallback and compatibility.
    
    Args:
        message: The user message to analyze
        
    Returns:
        Dictionary of intent types and their confidence scores/metadata
    """
    intents = {}
    
    # Check for calculation intent
    calculation_score = _calculate_pattern_score(message, CALCULATION_PATTERNS)
    if calculation_score > 0.3:
        # For calculation, we prioritize it over web search for math expressions
        calculation_data = {"expression": message}
        intents["calculation"] = {
            "confidence": max(calculation_score, 0.8),  # Higher confidence for calculations
            "expression": message,
            "details": calculation_data
        }
    
    # Check for web search intent
    search_score = _calculate_pattern_score(message, SEARCH_PATTERNS)
    if search_score > 0.2:  # Threshold for considering this intent
        search_data = _extract_search_data(message)
        intents["web_search"] = {
            "confidence": search_score,
            "query": search_data.get("query", message),
            "details": search_data
        }
        
        # If we have a calculation intent with high confidence, remove web_search
        # if it's likely just a simple math query
        if "calculation" in intents and calculation_score > 0.7:
            if _is_simple_math_query(message):
                del intents["web_search"]
    
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
    
    # Check for conversation/greeting patterns
    # Simple regex patterns for greetings
    GREETING_PATTERNS = [
        r"(?i)^(hi|hello|hey|greetings)(\s|$)",
        r"(?i)^good\s+(morning|afternoon|evening|day)(\s|$)",
        r"(?i)^(how are you|what's up|howdy)(\s|$)",
        r"(?i)^(thanks|thank you)(\s|$)",
        r"(?i)^(hola|bonjour|ciao|hallo|你好|こんにちは)(\s|$)"
    ]
    
    greeting_score = _calculate_pattern_score(message, GREETING_PATTERNS)
    if greeting_score > 0.3 or (len(message.strip()) < 10 and len(message.strip().split()) <= 3):
        intents["conversation"] = {
            "confidence": max(greeting_score, 0.7),  # At least 0.7 confidence for short messages
            "query": message,
            "type": "greeting"
        }
    
    # Calculate general knowledge confidence based on other intents
    specialized_intents = list(intents.keys())
    
    # If we have specialized intents with high confidence, reduce general knowledge confidence
    if specialized_intents:
        # Check if specialized intents cover the message comprehensively
        has_high_confidence = any(intents[intent]["confidence"] > 0.7 for intent in specialized_intents)
        has_comprehensive_coverage = (("web_search" in intents or "local_search" in intents) and 
                                     "social_media" in intents)
        
        if has_high_confidence and has_comprehensive_coverage:
            # Low confidence when specialized intents cover the message well
            general_knowledge_confidence = 0.2
        elif has_high_confidence or has_comprehensive_coverage:
            # Medium confidence when partial coverage
            general_knowledge_confidence = 0.5
        else:
            # Higher confidence when specialized intents don't cover well
            general_knowledge_confidence = 0.8
    else:
        # Maximum confidence when no specialized intents
        general_knowledge_confidence = 1.0
    
    # Add general knowledge with adjusted confidence if no other intents were detected
    if not intents:
        intents["general_knowledge"] = {
            "confidence": general_knowledge_confidence,
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
        "general_knowledge": lambda msg: {"query": msg},
        "conversation": lambda msg: {"query": msg},
        "calculation": lambda msg: {"expression": msg}
    }
    
    if intent_type not in intent_extractors:
        return {"error": f"Unknown intent type: {intent_type}"}
    
    return intent_extractors[intent_type](message)

def store_intent_feedback(db, message_id: str, user_id: str, correct_intent: str, 
                          feedback: str, detected_intents: Dict[str, Any]) -> bool:
    """
    Store feedback about intent detection for future improvements.
    
    Args:
        db: Database connection
        message_id: The ID of the message
        user_id: The ID of the user providing feedback
        correct_intent: The correct intent that should have been detected
        feedback: Additional feedback text
        detected_intents: The originally detected intents
        
    Returns:
        True if feedback was stored successfully, False otherwise
    """
    try:
        query = """
        INSERT INTO mo_intent_feedback (
            message_id, user_id, correct_intent, detected_intents, feedback, created_at
        ) VALUES (
            :message_id, :user_id, :correct_intent, :detected_intents, :feedback, CURRENT_TIMESTAMP
        )
        """
        
        values = {
            "message_id": message_id,
            "user_id": user_id,
            "correct_intent": correct_intent,
            "detected_intents": json.dumps(detected_intents),
            "feedback": feedback
        }
        
        db.execute(query, values)
        return True
    except Exception as e:
        logger.error(f"Error storing intent feedback: {str(e)}")
        return False

# Initialize the multilingual detector if transformers is available
if TRANSFORMERS_AVAILABLE:
    try:
        # Initialize in background or on first use
        MultilingualIntentDetector.get_instance()
    except Exception as e:
        logger.error(f"Failed to initialize multilingual detector: {str(e)}")
