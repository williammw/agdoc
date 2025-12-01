# AI Content Generation & Transformation

## 🤖 Overview

The Multivio backend includes comprehensive AI-powered content generation and transformation capabilities using **Grok AI** from xAI. The system supports multiple AI models, real-time streaming, and platform-specific content optimization.

### Key Features

- **Content Transformation**: Rewrite content for different platforms, tones, and lengths
- **Content Generation**: Create original content from prompts and requirements
- **Platform Optimization**: Automatically adapt content for Twitter, LinkedIn, Facebook, etc.
- **Streaming Responses**: Real-time content generation with Server-Sent Events
- **Multi-Model Support**: Grok-4, Grok-3-Mini, and other Grok models
- **Authentication Integration**: Firebase authentication with user context

---

## 🔧 Configuration

### Environment Variables

```bash
# Required AI Configuration
GROK_API_KEY=your_grok_api_key_here

# Optional: Additional AI Providers
TOGETHER_API_KEY=your_together_api_key
OPENAI_API_KEY=your_openai_api_key

# AI Service Configuration
AI_DEFAULT_MODEL=grok-3-mini
AI_MAX_TOKENS=2000
AI_REQUEST_TIMEOUT=30
AI_MAX_RETRIES=3
```

### Getting a Grok API Key

1. Visit [X.AI Console](https://console.x.ai/)
2. Create an account or sign in
3. Navigate to API Keys section
4. Generate a new API key
5. Add the key to your environment variables

---

## 📝 API Endpoints

### 1. Content Transformation
```
POST /api/v1/ai/transform
```

Transform existing content according to specified parameters.

#### Request Body
```json
{
  "content": "Your original content here",
  "transformation_type": "platform_optimize",
  "target_platform": "twitter",
  "target_tone": "professional",
  "target_length": 280,
  "additional_instructions": "Make it more engaging",
  "model": "grok-3-mini",
  "stream": false
}
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | ✅ | Original content to transform |
| `transformation_type` | string | ✅ | Type of transformation |
| `target_platform` | string | ❌ | Target social media platform |
| `target_tone` | string | ❌ | Desired tone (professional, casual, etc.) |
| `target_length` | integer | ❌ | Target character/word count |
| `additional_instructions` | string | ❌ | Extra transformation instructions |
| `model` | string | ❌ | AI model to use (default: grok-3-mini) |
| `stream` | boolean | ❌ | Enable streaming response (default: false) |

#### Transformation Types

| Type | Description | Example |
|------|-------------|---------|
| `platform_optimize` | Optimize for specific platform | Twitter character limits, LinkedIn tone |
| `tone_change` | Change content tone | Professional → Casual |
| `length_adjust` | Adjust content length | Shorten or expand content |
| `hashtag_add` | Add relevant hashtags | Include trending hashtags |
| `rewrite` | Complete rewrite | Fresh language, same meaning |
| `summarize` | Create summary | Concise version of long content |
| `expand` | Add details | Elaborate on key points |

#### Response (Non-Streaming)
```json
{
  "original_content": "Your original content here",
  "transformed_content": "Transformed content optimized for Twitter...",
  "transformation_type": "platform_optimize",
  "target_platform": "twitter",
  "suggestions": [
    "Consider adding an emoji",
    "Include a call-to-action"
  ],
  "reasoning": "Optimized for Twitter's 280 character limit and engagement patterns",
  "model_used": "grok-3-mini",
  "processing_time": 1.23,
  "character_count": 275,
  "word_count": 45
}
```

#### Streaming Response
```javascript
// Client-side handling
const eventSource = new EventSource('/api/v1/ai/transform', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    content: "Your content",
    stream: true
  })
});

eventSource.onmessage = (event) => {
  const chunk = JSON.parse(event.data);
  if (chunk.is_complete) {
    eventSource.close();
  } else {
    // Append chunk.content to UI
    updateUI(chunk.content);
  }
};
```

---

### 2. Content Generation
```
POST /api/v1/ai/generate
```

Generate new content from prompts and requirements.

#### Request Body
```json
{
  "prompt": "Write a LinkedIn post about AI in social media",
  "topic": "Artificial Intelligence",
  "target_platform": "linkedin",
  "content_tone": "professional",
  "target_length": 500,
  "include_hashtags": true,
  "include_call_to_action": true,
  "context": "For a tech company audience",
  "model": "grok-4",
  "stream": false
}
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | ✅ | Content generation prompt |
| `topic` | string | ❌ | Main topic or theme |
| `target_platform` | string | ❌ | Target social platform |
| `content_tone` | string | ❌ | Desired tone |
| `target_length` | integer | ❌ | Target length |
| `include_hashtags` | boolean | ❌ | Include hashtags |
| `include_call_to_action` | boolean | ❌ | Include CTA |
| `context` | string | ❌ | Additional context |
| `model` | string | ❌ | AI model to use |
| `stream` | boolean | ❌ | Enable streaming |

#### Supported Tones
- `professional` - Business, corporate tone
- `casual` - Friendly, conversational
- `humorous` - Funny, light-hearted
- `engaging` - Interactive, community-focused
- `educational` - Informative, teaching tone
- `promotional` - Marketing, sales-focused

#### Response
```json
{
  "generated_content": "🚀 Exciting developments in AI are revolutionizing social media marketing. From intelligent content creation to predictive analytics, businesses now have powerful tools to enhance their online presence and engagement.\n\n#AI #SocialMedia #DigitalMarketing",
  "prompt_used": "Write a LinkedIn post about AI in social media",
  "target_platform": "linkedin",
  "suggestions": [
    "Consider adding a relevant statistic",
    "Link to a case study or example"
  ],
  "hashtags": ["#AI", "#SocialMedia", "#DigitalMarketing"],
  "reasoning": "Generated professional content suitable for LinkedIn's business audience",
  "model_used": "grok-4",
  "processing_time": 2.45,
  "character_count": 487,
  "word_count": 78
}
```

---

### 3. Available Models
```
GET /api/v1/ai/models
```

Get information about available AI models.

#### Response
```json
{
  "models": [
    {
      "id": "grok-4",
      "name": "Grok-4",
      "capability": "Latest and most advanced",
      "max_tokens": 4000,
      "best_for": ["Complex transformations", "Creative writing", "Detailed analysis"],
      "speed": "moderate"
    },
    {
      "id": "grok-3-mini",
      "name": "Grok-3-Mini",
      "capability": "Fast and efficient",
      "max_tokens": 2000,
      "best_for": ["Quick transformations", "Hashtag generation", "Tone adjustment"],
      "speed": "fast"
    },
    {
      "id": "grok-beta",
      "name": "Grok-Beta",
      "capability": "Experimental features",
      "max_tokens": 3000,
      "best_for": ["Experimental features", "Creative content"],
      "speed": "moderate"
    }
  ],
  "default_model": "grok-3-mini"
}
```

---

### 4. Supported Platforms
```
GET /api/v1/ai/platforms
```

Get platform-specific optimization guidelines.

#### Response
```json
{
  "platforms": {
    "twitter": {
      "name": "Twitter/X",
      "character_limit": 280,
      "optimization": {
        "hooks": "Engaging first sentence",
        "hashtags": "2-3 relevant hashtags",
        "format": "Thread format for long content",
        "best_for": "Quick updates, news, conversations"
      }
    },
    "linkedin": {
      "name": "LinkedIn",
      "character_limit": 3000,
      "optimization": {
        "tone": "Professional and insightful",
        "structure": "Industry insights, value-driven",
        "hashtags": "1-2 industry-specific hashtags",
        "best_for": "Professional content, thought leadership"
      }
    },
    "facebook": {
      "name": "Facebook",
      "character_limit": null,
      "optimization": {
        "tone": "Conversational and community-focused",
        "media": "High engagement with images/videos",
        "questions": "Include questions for engagement",
        "best_for": "Community building, discussions"
      }
    }
  }
}
```

---

### 5. Service Health Check
```
GET /api/v1/ai/health
```

Check AI service configuration and status.

#### Response
```json
{
  "status": "healthy",
  "grok_api_configured": true,
  "models_available": ["grok-4", "grok-3-mini", "grok-beta"],
  "default_model": "grok-3-mini",
  "last_health_check": "2024-12-22T10:30:00Z",
  "response_time_ms": 245
}
```

---

### 6. Service Test
```
POST /api/v1/ai/test
```

Perform a basic test of AI service functionality.

#### Request Body
```json
{
  "model": "grok-3-mini",
  "test_type": "basic"
}
```

#### Response
```json
{
  "success": true,
  "test_result": "AI service is working correctly",
  "model_tested": "grok-3-mini",
  "response_time": 1.2,
  "sample_output": "Hello! I'm Grok, an AI built by xAI."
}
```

---

## 🏗️ Implementation Architecture

### Service Layer

**AI Service (`app/services/ai_service.py`):**
```python
class AIService:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
        )
        self.api_key = os.getenv("GROK_API_KEY")
        self.base_url = "https://api.x.ai/v1"

    async def transform_content(
        self,
        content: str,
        transformation_type: str,
        **kwargs
    ) -> dict:
        """Transform content using AI"""

        prompt = self._build_transformation_prompt(
            content, transformation_type, **kwargs
        )

        response = await self._call_grok_api(prompt, **kwargs)

        return self._parse_transformation_response(response, **kwargs)

    async def generate_content(
        self,
        prompt: str,
        **kwargs
    ) -> dict:
        """Generate new content using AI"""

        enhanced_prompt = self._enhance_generation_prompt(prompt, **kwargs)

        response = await self._call_grok_api(enhanced_prompt, **kwargs)

        return self._parse_generation_response(response, **kwargs)
```

### Router Layer

**AI Router (`app/routers/ai.py`):**
```python
@router.post("/transform")
async def transform_content(
    request: TransformRequest,
    current_user: dict = Depends(get_current_user)
) -> TransformResponse:
    """Transform existing content"""

    try:
        if request.stream:
            return StreamingResponse(
                ai_service.stream_transform(request),
                media_type="text/event-stream"
            )

        result = await ai_service.transform_content(
            content=request.content,
            transformation_type=request.transformation_type,
            **request.dict(exclude={'content', 'transformation_type', 'stream'})
        )

        return TransformResponse(**result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"AI transformation failed: {str(e)}"
        )
```

### Data Models

**Request/Response Models (`app/models/ai.py`):**
```python
class TransformRequest(BaseModel):
    content: str
    transformation_type: str = "platform_optimize"
    target_platform: Optional[str] = None
    target_tone: Optional[str] = None
    target_length: Optional[int] = None
    additional_instructions: Optional[str] = None
    model: str = "grok-3-mini"
    stream: bool = False

class TransformResponse(BaseModel):
    original_content: str
    transformed_content: str
    transformation_type: str
    target_platform: Optional[str]
    suggestions: List[str] = []
    reasoning: str
    model_used: str
    processing_time: float
    character_count: int
    word_count: int
```

---

## 🎯 Platform-Specific Optimization

### Twitter/X Optimization

```python
def optimize_for_twitter(content: str, **kwargs) -> dict:
    """Optimize content for Twitter's constraints and best practices"""

    # Character limit check
    if len(content) > 280:
        content = content[:277] + "..."

    suggestions = []

    # Check for engagement hooks
    if not content.startswith(('🚀', '💡', '🤔', '❓', '🔥')):
        suggestions.append("Consider starting with an emoji for better engagement")

    # Hashtag analysis
    hashtags = re.findall(r'#\w+', content)
    if len(hashtags) == 0:
        suggestions.append("Consider adding 1-2 relevant hashtags")
    elif len(hashtags) > 3:
        suggestions.append("Too many hashtags - consider reducing to 2-3")

    return {
        "optimized_content": content,
        "suggestions": suggestions,
        "character_count": len(content),
        "hashtags_count": len(hashtags)
    }
```

### LinkedIn Optimization

```python
def optimize_for_linkedin(content: str, **kwargs) -> dict:
    """Optimize content for LinkedIn's professional audience"""

    suggestions = []

    # Check for professional tone
    professional_indicators = ['team', 'industry', 'professional', 'business', 'career']
    has_professional_tone = any(word in content.lower() for word in professional_indicators)

    if not has_professional_tone:
        suggestions.append("Consider adding industry insights or professional context")

    # Check length - LinkedIn favors detailed content
    if len(content) < 100:
        suggestions.append("LinkedIn posts perform better with more detailed content")

    # Hashtag strategy for LinkedIn
    hashtags = re.findall(r'#\w+', content)
    if len(hashtags) > 2:
        suggestions.append("LinkedIn prefers 1-2 highly relevant hashtags over many")

    return {
        "optimized_content": content,
        "suggestions": suggestions,
        "word_count": len(content.split()),
        "professional_score": 0.8 if has_professional_tone else 0.5
    }
```

---

## 📊 Usage Analytics

### AI Usage Tracking

**Database table for AI usage:**
```sql
CREATE TABLE ai_usage (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id INTEGER NOT NULL REFERENCES users(id),
  endpoint VARCHAR(50) NOT NULL, -- transform, generate
  model_used VARCHAR(50) NOT NULL,
  tokens_used INTEGER,
  processing_time DECIMAL(5,2),
  success BOOLEAN DEFAULT true,
  error_message TEXT,
  platform_target VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for analytics
CREATE INDEX idx_ai_usage_user_id ON ai_usage(user_id);
CREATE INDEX idx_ai_usage_endpoint ON ai_usage(endpoint);
CREATE INDEX idx_ai_usage_created_at ON ai_usage(created_at);
```

### Analytics Queries

**Popular AI features:**
```sql
SELECT
  endpoint,
  COUNT(*) as total_requests,
  COUNT(*) FILTER (WHERE success = true) as successful_requests,
  ROUND(
    AVG(processing_time)::numeric, 2
  ) as avg_processing_time,
  ROUND(
    AVG(tokens_used)::numeric, 2
  ) as avg_tokens_used
FROM ai_usage
WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY endpoint
ORDER BY total_requests DESC;
```

**Platform-specific usage:**
```sql
SELECT
  platform_target,
  COUNT(*) as requests,
  COUNT(DISTINCT user_id) as unique_users
FROM ai_usage
WHERE platform_target IS NOT NULL
  AND created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY platform_target
ORDER BY requests DESC;
```

---

## 🔒 Security & Rate Limiting

### Authentication
- All AI endpoints require Firebase authentication
- User context passed to AI service for personalization
- API keys encrypted and securely stored

### Rate Limiting
```python
# AI-specific rate limits
AI_RATE_LIMITS = {
    'transform': '50/minute',    # Content transformations
    'generate': '30/minute',     # Content generation
    'models': '100/minute',      # Model information
    'platforms': '100/minute',   # Platform data
    'health': '60/minute'        # Health checks
}
```

### Input Validation
- Content length limits (max 10,000 characters)
- Prompt injection protection
- Malformed request filtering
- XSS and injection attack prevention

---

## 🧪 Testing

### Unit Tests

```python
@pytest.mark.asyncio
async def test_content_transformation():
    """Test AI content transformation"""
    ai_service = AIService()

    result = await ai_service.transform_content(
        content="Hello world",
        transformation_type="platform_optimize",
        target_platform="twitter"
    )

    assert "transformed_content" in result
    assert result["target_platform"] == "twitter"
    assert len(result["transformed_content"]) <= 280

@pytest.mark.asyncio
async def test_content_generation():
    """Test AI content generation"""
    ai_service = AIService()

    result = await ai_service.generate_content(
        prompt="Write about AI",
        target_platform="linkedin"
    )

    assert "generated_content" in result
    assert len(result["generated_content"]) > 0
    assert "AI" in result["generated_content"] or "artificial intelligence" in result["generated_content"]
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_ai_endpoints_integration(client, test_user):
    """Test AI endpoints with authentication"""

    # Test transformation
    transform_response = await client.post(
        "/api/v1/ai/transform",
        json={
            "content": "Test content",
            "transformation_type": "platform_optimize",
            "target_platform": "twitter"
        },
        headers={"Authorization": f"Bearer {test_user['token']}"}
    )

    assert transform_response.status_code == 200
    result = transform_response.json()
    assert "transformed_content" in result

    # Test generation
    generate_response = await client.post(
        "/api/v1/ai/generate",
        json={
            "prompt": "Write a short post",
            "target_platform": "twitter"
        },
        headers={"Authorization": f"Bearer {test_user['token']}"}
    )

    assert generate_response.status_code == 200
    result = generate_response.json()
    assert "generated_content" in result
```

### Manual Testing Script

The included `test_ai_endpoints.py` script provides comprehensive testing:

```bash
# Test all AI endpoints
python test_ai_endpoints.py

# Test with specific model
python test_ai_endpoints.py --model grok-4

# Test streaming functionality
python test_ai_endpoints.py --stream
```

---

## 📈 Performance Monitoring

### Response Time Tracking

```python
class AIMetrics:
    def __init__(self):
        self.requests_total = 0
        self.requests_success = 0
        self.requests_failed = 0
        self.response_times = []

    async def track_request(self, endpoint: str, start_time: float,
                          success: bool, response_time: float):
        """Track AI request metrics"""
        self.requests_total += 1

        if success:
            self.requests_success += 1
        else:
            self.requests_failed += 1

        self.response_times.append(response_time)

        # Log metrics
        logger.info(f"AI Request: {endpoint}", extra={
            "endpoint": endpoint,
            "success": success,
            "response_time": response_time,
            "avg_response_time": sum(self.response_times) / len(self.response_times)
        })
```

### Error Tracking

```python
class AIErrorTracker:
    def __init__(self):
        self.errors_by_type = {}
        self.errors_by_model = {}
        self.rate_limit_hits = 0

    async def track_error(self, error_type: str, model: str, error: Exception):
        """Track AI service errors"""

        # Categorize errors
        if "rate limit" in str(error).lower():
            self.rate_limit_hits += 1
            error_category = "rate_limit"
        elif "timeout" in str(error).lower():
            error_category = "timeout"
        elif "authentication" in str(error).lower():
            error_category = "auth"
        else:
            error_category = "other"

        # Track by type
        if error_category not in self.errors_by_type:
            self.errors_by_type[error_category] = 0
        self.errors_by_type[error_category] += 1

        # Track by model
        if model not in self.errors_by_model:
            self.errors_by_model[model] = 0
        self.errors_by_model[model] += 1

        # Log error
        logger.error(f"AI Error: {error_category}", extra={
            "error_type": error_category,
            "model": model,
            "error_message": str(error)
        })
```

---

## 🚀 Future Enhancements

### Planned Features

- **Content Templates**: Pre-built templates for common use cases
- **A/B Testing**: Generate multiple content variations for testing
- **Content Calendar**: AI-powered content scheduling suggestions
- **Brand Voice**: Maintain consistent brand voice across content
- **Multi-language Support**: Content generation in multiple languages
- **Image Generation**: AI-generated images to accompany text
- **Video Script Generation**: Scripts for video content creation

### Performance Improvements

- **Caching**: Cache common transformations and prompts
- **Background Jobs**: Queue long-running AI tasks
- **Load Balancing**: Distribute requests across multiple AI providers
- **Edge Computing**: Deploy AI processing closer to users

### Advanced Features

- **Sentiment Analysis**: Analyze content sentiment and tone
- **Content Scoring**: Rate content quality and engagement potential
- **Trend Analysis**: Incorporate trending topics and hashtags
- **Competitor Analysis**: Generate content based on competitor strategies

---

**Version**: 3.0.1
**Last Updated**: September 2025
**AI Provider**: Grok (xAI) ✅
**Status**: Production Ready
