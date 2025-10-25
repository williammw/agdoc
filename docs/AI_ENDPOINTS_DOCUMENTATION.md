# AI Endpoints Documentation

## Overview

This implementation adds AI-powered content generation and transformation capabilities to the Multivio social media management application using the Grok API from X.AI.

## Features

### 🤖 Content Transformation
- **Platform Optimization**: Adapt content for specific social media platforms
- **Tone Adjustment**: Change content tone (professional, casual, humorous, etc.)
- **Length Adjustment**: Resize content to meet platform requirements
- **Hashtag Suggestions**: Add relevant hashtags to content
- **Content Rewriting**: Complete rewrite with fresh language
- **Summarization**: Create concise summaries
- **Content Expansion**: Add details and insights

### 🎯 Content Generation
- **AI-Powered Creation**: Generate original content from prompts
- **Platform-Specific**: Optimized for each social media platform
- **Tone Control**: Professional, casual, friendly, humorous, etc.
- **Hashtag Integration**: Automatic hashtag suggestions
- **Call-to-Action**: Optional CTA integration
- **Context-Aware**: Use additional context for better results

### ⚡ Advanced Features
- **Streaming Responses**: Real-time content generation with Server-Sent Events
- **Multiple AI Models**: Support for different Grok models (Grok-4, Grok-3-Mini, etc.)
- **Authentication**: Integrated with existing Firebase authentication
- **Error Handling**: Comprehensive error handling and fallbacks
- **Platform Guidelines**: Built-in knowledge of platform best practices

## API Endpoints

### 1. Content Transformation
```
POST /api/v1/ai/transform
```

Transform existing content according to specified parameters.

**Request Body:**
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

**Response:**
```json
{
  "original_content": "...",
  "transformed_content": "...",
  "transformation_type": "platform_optimize",
  "target_platform": "twitter",
  "suggestions": [...],
  "reasoning": "...",
  "model_used": "grok-3-mini",
  "processing_time": 1.23,
  "character_count": 275,
  "word_count": 45
}
```

### 2. Content Generation
```
POST /api/v1/ai/generate
```

Generate new content from prompts and requirements.

**Request Body:**
```json
{
  "prompt": "Write about AI in social media",
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

**Response:**
```json
{
  "generated_content": "...",
  "prompt_used": "...",
  "target_platform": "linkedin",
  "suggestions": [...],
  "hashtags": ["#AI", "#SocialMedia", "#Technology"],
  "reasoning": "...",
  "model_used": "grok-4",
  "processing_time": 2.45,
  "character_count": 487,
  "word_count": 78
}
```

### 3. Streaming Responses

Both transform and generate endpoints support streaming by setting `"stream": true` in the request. Responses are sent as Server-Sent Events:

```
Content-Type: text/event-stream

data: {"chunk_id": "chunk_0", "content": "AI is revolutionizing", "is_complete": false}

data: {"chunk_id": "chunk_1", "content": " social media marketing", "is_complete": false}

data: {"chunk_id": "chunk_2", "content": "", "is_complete": true}
```

### 4. Utility Endpoints

#### List Available Models
```
GET /api/v1/ai/models
```

Returns information about available Grok models and their capabilities.

#### List Supported Platforms
```
GET /api/v1/ai/platforms
```

Returns supported social media platforms and their optimization guidelines.

#### Service Health Check
```
GET /api/v1/ai/health
```

Check AI service configuration and status.

#### Test Service
```
POST /api/v1/ai/test
```

Perform a basic test of the AI service functionality.

## Supported Platforms

### 🐦 Twitter/X
- **Character Limit**: 280
- **Optimization**: Engaging hooks, 2-3 hashtags, thread format
- **Best For**: Quick updates, news, conversations

### 💼 LinkedIn
- **Character Limit**: 3,000
- **Optimization**: Professional tone, industry keywords, insights
- **Best For**: Professional content, thought leadership

### 📘 Facebook
- **Character Limit**: 63,206 (optimal: 100-300 words)
- **Optimization**: Conversational tone, community engagement
- **Best For**: Community building, discussions

### 📸 Instagram
- **Character Limit**: 2,200
- **Optimization**: Visual-first, emojis, up to 30 hashtags
- **Best For**: Visual storytelling, lifestyle content

### 🧵 Threads
- **Character Limit**: 500
- **Optimization**: Conversational, discussion-friendly
- **Best For**: Quick thoughts, discussions

### 🎥 YouTube
- **Character Limit**: 5,000
- **Optimization**: SEO keywords, timestamps, CTAs
- **Best For**: Video descriptions, detailed explanations

### 🎵 TikTok
- **Character Limit**: 4,000
- **Optimization**: Trend-aware, punchy, popular hashtags
- **Best For**: Video descriptions, trending content

## AI Models

### Grok-4 (grok-4)
- **Capability**: Latest and most advanced
- **Max Tokens**: 4,000
- **Best For**: Complex transformations, creative writing, detailed analysis
- **Speed**: Moderate

### Grok-3-Mini (grok-3-mini) [Default]
- **Capability**: Fast and efficient
- **Max Tokens**: 2,000
- **Best For**: Quick transformations, hashtag generation, tone adjustment
- **Speed**: Fast

### Grok-Beta (grok-beta)
- **Capability**: Experimental features
- **Max Tokens**: 3,000
- **Best For**: Experimental features, creative content
- **Speed**: Moderate

### Grok-2 (grok-2-1212)
- **Capability**: Stable and reliable
- **Max Tokens**: 3,000
- **Best For**: Professional content, platform optimization
- **Speed**: Moderate

### Grok-2-Mini (grok-2-mini-1212)
- **Capability**: Lightweight version
- **Max Tokens**: 1,500
- **Best For**: Simple transformations, quick generation
- **Speed**: Fast

## Configuration

### Environment Variables

```bash
# Required for AI functionality
GROK_API_KEY=your_grok_api_key_here

# Existing app configuration
NEXTAUTH_URL=https://dev.multivio.com
NEXT_PUBLIC_API_URL=https://dev.ohmeowkase.com
# ... other existing variables
```

### Getting a Grok API Key

1. Visit [X.AI Console](https://console.x.ai/)
2. Create an account or sign in
3. Generate an API key
4. Add the key to your environment variables

## Implementation Details

### File Structure

```
app/
├── models/
│   └── ai.py                 # Pydantic models for AI endpoints
├── services/
│   └── ai_service.py         # Grok API integration service
├── routers/
│   └── ai.py                 # FastAPI router with AI endpoints
└── main.py                   # Updated to include AI router
```

### Key Components

1. **Models (`app/models/ai.py`)**:
   - Request/response models
   - Enums for platforms, tones, transformations
   - Streaming chunk models
   - Error response models

2. **Service (`app/services/ai_service.py`)**:
   - Grok API integration
   - Async HTTP client with httpx
   - Streaming response handling
   - Platform-specific prompt engineering
   - Error handling and retries

3. **Router (`app/routers/ai.py`)**:
   - FastAPI endpoints
   - Authentication integration
   - Streaming response formatting
   - Request validation
   - Error handling

### Security Features

- **Authentication Required**: All endpoints require Firebase authentication
- **Input Validation**: Comprehensive request validation with Pydantic
- **Rate Limiting**: Inherits from existing FastAPI rate limiting
- **Error Handling**: Sanitized error responses
- **API Key Security**: Environment variable configuration

### Performance Optimizations

- **Async/Await**: Fully asynchronous implementation
- **Streaming**: Real-time response streaming for better UX
- **Connection Pooling**: httpx client with connection reuse
- **Timeout Management**: Configurable request timeouts
- **Model Selection**: Choose optimal model for task requirements

## Usage Examples

### Frontend Integration

```javascript
// Transform content
const transformContent = async (content, options) => {
  const response = await fetch('/api/v1/ai/transform', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${firebaseToken}`
    },
    body: JSON.stringify({
      content,
      transformation_type: 'platform_optimize',
      target_platform: 'twitter',
      ...options
    })
  });
  
  return response.json();
};

// Stream content generation
const streamGenerate = (prompt, onChunk) => {
  const eventSource = new EventSource('/api/v1/ai/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${firebaseToken}`
    },
    body: JSON.stringify({
      prompt,
      stream: true
    })
  });
  
  eventSource.onmessage = (event) => {
    const chunk = JSON.parse(event.data);
    onChunk(chunk);
    
    if (chunk.is_complete) {
      eventSource.close();
    }
  };
};
```

### Python Client

```python
import httpx

async def transform_content(content, token):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            'https://dev.ohmeowkase.com/api/v1/ai/transform',
            headers={'Authorization': f'Bearer {token}'},
            json={
                'content': content,
                'transformation_type': 'platform_optimize',
                'target_platform': 'linkedin'
            }
        )
        return response.json()
```

## Testing

### Unit Tests
Run the included test script to verify implementation:
```bash
cd /path/to/agdoc
python test_ai_endpoints.py
```

### Manual Testing
1. Start the FastAPI server: `uvicorn app.main:app --reload`
2. Visit `http://localhost:8000/docs` for interactive API documentation
3. Test endpoints with sample requests

### Health Check
```bash
curl -X GET "http://localhost:8000/api/v1/ai/health" \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN"
```

## Error Handling

The implementation includes comprehensive error handling:

- **API Key Missing**: Returns 500 with configuration error
- **Grok API Errors**: Proxies Grok API error responses
- **Network Timeouts**: Returns 504 Gateway Timeout
- **Validation Errors**: Returns 422 with detailed field errors
- **Authentication Errors**: Returns 401 Unauthorized
- **Rate Limiting**: Returns 429 Too Many Requests

## Monitoring and Logging

- **Structured Logging**: JSON-formatted logs with request IDs
- **Performance Metrics**: Processing time tracking
- **Error Tracking**: Detailed error logging with stack traces
- **Usage Analytics**: User and endpoint usage tracking

## Future Enhancements

### Planned Features
- **Content Templates**: Pre-built templates for common use cases
- **A/B Testing**: Generate multiple content variations
- **Sentiment Analysis**: Analyze content sentiment
- **Brand Voice**: Maintain consistent brand voice across content
- **Content Calendar**: AI-powered content scheduling suggestions
- **Image Generation**: AI-generated images to accompany text
- **Video Script Generation**: Scripts for video content
- **Translation**: Multi-language content generation

### Performance Improvements
- **Caching**: Cache common transformations
- **Background Jobs**: Queue long-running AI tasks
- **Load Balancing**: Distribute AI requests across multiple providers
- **Edge Computing**: Deploy AI processing closer to users

## Support

For issues or questions regarding the AI endpoints:

1. Check the health endpoint: `/api/v1/ai/health`
2. Review the logs for error details
3. Verify GROK_API_KEY configuration
4. Test with the `/api/v1/ai/test` endpoint

## Contributing

When contributing to the AI functionality:

1. Follow existing FastAPI patterns
2. Add comprehensive type hints
3. Include input validation
4. Write unit tests
5. Update documentation
6. Test with multiple AI models
7. Verify streaming functionality

---

**Last Updated**: December 2024
**API Version**: v1
**Status**: Production Ready ✅