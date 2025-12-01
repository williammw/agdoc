# API Architect Skill

You are an API design expert specialized in creating well-structured, RESTful APIs with FastAPI.

## API Design Principles

### RESTful Design
- Use appropriate HTTP methods (GET, POST, PUT, DELETE, PATCH)
- Use plural nouns for resources (`/images`, `/videos`, `/jobs`)
- Use nested routes for relationships (`/jobs/{id}/result`)
- Return appropriate status codes
- Use consistent response formats

### Endpoint Structure
```
/api/v1/
  ├── /images
  │   ├── POST /resize
  │   ├── POST /crop
  │   ├── POST /filter
  │   ├── POST /convert
  │   └── POST /combine
  ├── /videos
  │   ├── POST /resize
  │   ├── POST /crop
  │   ├── POST /trim
  │   ├── POST /subtitle
  │   ├── POST /combine
  │   ├── POST /convert
  │   └── POST /thumbnail
  ├── /audio
  │   ├── POST /extract
  │   ├── POST /convert
  │   └── POST /normalize
  └── /jobs
      ├── GET /{job_id}
      ├── GET /{job_id}/status
      ├── GET /{job_id}/download
      └── DELETE /{job_id}
```

## Request/Response Patterns

### Synchronous (Quick Operations)
```json
POST /api/v1/images/resize
Request:
{
  "file": "base64_or_url",
  "width": 800,
  "height": 600,
  "maintain_aspect": true
}

Response (200 OK):
{
  "success": true,
  "output_url": "https://...",
  "metadata": {
    "original_size": [1920, 1080],
    "new_size": [800, 450],
    "format": "jpg"
  }
}
```

### Asynchronous (Long Operations)
```json
POST /api/v1/videos/convert
Request:
{
  "file_url": "https://...",
  "output_format": "mp4",
  "quality": "high"
}

Response (202 Accepted):
{
  "job_id": "abc123",
  "status": "processing",
  "message": "Video conversion started",
  "status_url": "/api/v1/jobs/abc123/status"
}

GET /api/v1/jobs/abc123/status
Response (200 OK):
{
  "job_id": "abc123",
  "status": "completed",  // or "processing", "failed", "pending"
  "progress": 100,
  "result_url": "/api/v1/jobs/abc123/download",
  "metadata": {...}
}
```

## FastAPI Best Practices

### Pydantic Models
```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

class ImageResizeRequest(BaseModel):
    width: int = Field(..., gt=0, le=4096)
    height: Optional[int] = Field(None, gt=0, le=4096)
    maintain_aspect: bool = True
    format: Optional[Literal["jpg", "png", "webp"]] = None

class JobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    progress: int = Field(0, ge=0, le=100)
    result_url: Optional[str] = None
    error: Optional[str] = None
```

### File Upload Handling
```python
from fastapi import UploadFile, File, Form

@app.post("/api/v1/images/resize")
async def resize_image(
    file: UploadFile = File(...),
    width: int = Form(...),
    height: Optional[int] = Form(None)
):
    # Save file temporarily
    # Process with FFmpeg
    # Return result
    pass
```

### Error Handling
```python
from fastapi import HTTPException

# Standard error responses
raise HTTPException(status_code=400, detail="Invalid image format")
raise HTTPException(status_code=413, detail="File too large")
raise HTTPException(status_code=422, detail="Invalid parameters")
raise HTTPException(status_code=500, detail="Processing failed")
```

### Background Tasks
```python
from fastapi import BackgroundTasks

@app.post("/api/v1/videos/convert")
async def convert_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    job_id = generate_job_id()
    background_tasks.add_task(process_video, job_id, file)
    return {"job_id": job_id, "status": "processing"}
```

## Response Standards

### Success Response
```json
{
  "success": true,
  "data": {...},
  "message": "Operation completed successfully"
}
```

### Error Response
```json
{
  "success": false,
  "error": {
    "code": "INVALID_FORMAT",
    "message": "Unsupported image format",
    "details": "Only JPG, PNG, and WebP are supported"
  }
}
```

## Configuration

### Environment Variables
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Settings
    API_VERSION: str = "v1"
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB

    # Storage
    UPLOAD_DIR: str = "/tmp/uploads"
    OUTPUT_DIR: str = "/tmp/outputs"

    # Processing
    MAX_WORKERS: int = 4
    JOB_TIMEOUT: int = 300  # 5 minutes

    # Cleanup
    FILE_RETENTION_HOURS: int = 24

    class Config:
        env_file = ".env"
```

## Documentation

FastAPI auto-generates OpenAPI docs. Enhance with:
```python
@app.post(
    "/api/v1/images/resize",
    summary="Resize an image",
    description="Resize image while optionally maintaining aspect ratio",
    response_description="Returns the processed image URL",
    tags=["Images"]
)
async def resize_image(...):
    pass
```

## Security

1. **Rate Limiting** - Use slowapi or similar
2. **Authentication** - API keys or JWT tokens
3. **CORS** - Configure allowed origins
4. **File Validation** - Check magic bytes, not just extensions
5. **Input Sanitization** - Validate all user inputs
6. **Resource Limits** - Set max file size, processing time
