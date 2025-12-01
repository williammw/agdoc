# Media Validation & Security Skill

You are an expert in media file validation, security, and handling user uploads safely.

## File Validation Strategy

### Multi-Layer Validation

1. **Extension Check** - Quick first filter
2. **MIME Type Check** - Content-Type header
3. **Magic Bytes** - Read file signature
4. **FFprobe Validation** - Verify actual media content

### Supported Formats

#### Images
```python
IMAGE_FORMATS = {
    'jpg': {'mime': 'image/jpeg', 'magic': [b'\xFF\xD8\xFF']},
    'jpeg': {'mime': 'image/jpeg', 'magic': [b'\xFF\xD8\xFF']},
    'png': {'mime': 'image/png', 'magic': [b'\x89PNG\r\n\x1a\n']},
    'webp': {'mime': 'image/webp', 'magic': [b'RIFF', b'WEBP']},
    'gif': {'mime': 'image/gif', 'magic': [b'GIF87a', b'GIF89a']},
    'bmp': {'mime': 'image/bmp', 'magic': [b'BM']},
    'tiff': {'mime': 'image/tiff', 'magic': [b'II*\x00', b'MM\x00*']},
}
```

#### Videos
```python
VIDEO_FORMATS = {
    'mp4': {'mime': 'video/mp4', 'magic': [b'ftyp']},
    'avi': {'mime': 'video/x-msvideo', 'magic': [b'RIFF', b'AVI ']},
    'mov': {'mime': 'video/quicktime', 'magic': [b'moov', b'mdat', b'ftyp']},
    'mkv': {'mime': 'video/x-matroska', 'magic': [b'\x1A\x45\xDF\xA3']},
    'webm': {'mime': 'video/webm', 'magic': [b'\x1A\x45\xDF\xA3']},
    'flv': {'mime': 'video/x-flv', 'magic': [b'FLV\x01']},
    'wmv': {'mime': 'video/x-ms-wmv', 'magic': [b'\x30\x26\xB2\x75']},
}
```

#### Audio
```python
AUDIO_FORMATS = {
    'mp3': {'mime': 'audio/mpeg', 'magic': [b'ID3', b'\xFF\xFB']},
    'wav': {'mime': 'audio/wav', 'magic': [b'RIFF', b'WAVE']},
    'flac': {'mime': 'audio/flac', 'magic': [b'fLaC']},
    'aac': {'mime': 'audio/aac', 'magic': [b'\xFF\xF1', b'\xFF\xF9']},
    'ogg': {'mime': 'audio/ogg', 'magic': [b'OggS']},
    'm4a': {'mime': 'audio/mp4', 'magic': [b'ftyp']},
}
```

## Validation Implementation

### Magic Bytes Validation
```python
import os

def validate_magic_bytes(file_path: str, expected_format: str) -> bool:
    """Validate file by checking magic bytes"""
    format_data = IMAGE_FORMATS.get(expected_format) or \
                  VIDEO_FORMATS.get(expected_format) or \
                  AUDIO_FORMATS.get(expected_format)

    if not format_data:
        return False

    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)  # Read first 32 bytes

        for magic in format_data['magic']:
            if magic in header:
                return True

        return False
    except Exception:
        return False
```

### FFprobe Validation
```python
import subprocess
import json

def validate_media_with_ffprobe(file_path: str, media_type: str) -> dict:
    """
    Validate media file using ffprobe
    Returns metadata if valid, raises exception if invalid
    """
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        file_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise ValueError("Invalid media file")

        data = json.loads(result.stdout)

        # Validate has expected stream type
        if media_type == 'video':
            if not any(s['codec_type'] == 'video' for s in data['streams']):
                raise ValueError("No video stream found")
        elif media_type == 'audio':
            if not any(s['codec_type'] == 'audio' for s in data['streams']):
                raise ValueError("No audio stream found")
        elif media_type == 'image':
            if not any(s['codec_type'] == 'video' for s in data['streams']):
                raise ValueError("Not a valid image file")

        return {
            'valid': True,
            'format': data['format']['format_name'],
            'duration': float(data['format'].get('duration', 0)),
            'size': int(data['format']['size']),
            'streams': [{
                'type': s['codec_type'],
                'codec': s['codec_name'],
                'width': s.get('width'),
                'height': s.get('height'),
                'duration': s.get('duration')
            } for s in data['streams']]
        }

    except subprocess.TimeoutExpired:
        raise ValueError("File validation timeout")
    except json.JSONDecodeError:
        raise ValueError("Invalid media file")
    except Exception as e:
        raise ValueError(f"Validation failed: {str(e)}")
```

### Complete Validator
```python
from fastapi import UploadFile, HTTPException
import magic  # python-magic

class MediaValidator:
    def __init__(self, max_file_size: int = 100 * 1024 * 1024):  # 100MB
        self.max_file_size = max_file_size

    async def validate_upload(
        self,
        file: UploadFile,
        allowed_types: list,
        media_category: str  # 'image', 'video', 'audio'
    ) -> dict:
        """Complete validation of uploaded file"""

        # 1. Check file size
        file.file.seek(0, 2)  # Seek to end
        size = file.file.tell()
        file.file.seek(0)  # Reset

        if size > self.max_file_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max size: {self.max_file_size / 1024 / 1024}MB"
            )

        if size == 0:
            raise HTTPException(status_code=400, detail="Empty file")

        # 2. Check extension
        ext = file.filename.split('.')[-1].lower() if '.' in file.filename else ''
        if ext not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format. Allowed: {', '.join(allowed_types)}"
            )

        # 3. Save temporarily
        temp_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
        with open(temp_path, 'wb') as f:
            content = await file.read()
            f.write(content)

        try:
            # 4. Check magic bytes
            if not validate_magic_bytes(temp_path, ext):
                raise HTTPException(
                    status_code=400,
                    detail="File content doesn't match extension"
                )

            # 5. Validate with ffprobe
            metadata = validate_media_with_ffprobe(temp_path, media_category)

            return {
                'temp_path': temp_path,
                'original_name': file.filename,
                'size': size,
                'format': ext,
                'metadata': metadata
            }

        except ValueError as e:
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            os.remove(temp_path)
            raise HTTPException(status_code=500, detail="Validation failed")
```

## Security Best Practices

### 1. File Size Limits
```python
# Different limits for different media types
SIZE_LIMITS = {
    'image': 10 * 1024 * 1024,   # 10MB
    'video': 500 * 1024 * 1024,  # 500MB
    'audio': 50 * 1024 * 1024,   # 50MB
}
```

### 2. Filename Sanitization
```python
import re
import uuid

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal"""
    # Remove any path components
    filename = os.path.basename(filename)
    # Remove special characters
    filename = re.sub(r'[^\w\s.-]', '', filename)
    # Limit length
    name, ext = os.path.splitext(filename)
    name = name[:50]
    return f"{name}{ext}"

def generate_safe_filename(original_filename: str) -> str:
    """Generate unique safe filename"""
    ext = os.path.splitext(original_filename)[1]
    return f"{uuid.uuid4()}{ext}"
```

### 3. Path Validation
```python
def validate_path(path: str, base_dir: str) -> str:
    """Ensure path is within base directory"""
    abs_base = os.path.abspath(base_dir)
    abs_path = os.path.abspath(path)

    if not abs_path.startswith(abs_base):
        raise ValueError("Invalid path: outside base directory")

    return abs_path
```

### 4. Content Validation
```python
def validate_image_content(file_path: str) -> bool:
    """Additional image validation using Pillow"""
    try:
        from PIL import Image
        img = Image.open(file_path)
        img.verify()  # Verify it's a valid image
        return True
    except Exception:
        return False
```

### 5. Resource Limits
```python
import resource
import signal

def set_resource_limits():
    """Set resource limits for FFmpeg processes"""
    # CPU time limit (5 minutes)
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    # Memory limit (1GB)
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

def timeout_handler(signum, frame):
    raise TimeoutError("Processing timeout")

def run_with_timeout(func, timeout=300):
    """Run function with timeout"""
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    try:
        result = func()
        signal.alarm(0)
        return result
    except TimeoutError:
        raise
```

## File Cleanup Strategy

```python
from datetime import datetime, timedelta
import os
import glob

class FileCleanup:
    def __init__(self, temp_dir: str, output_dir: str):
        self.temp_dir = temp_dir
        self.output_dir = output_dir

    def cleanup_old_files(self, hours: int = 24):
        """Remove files older than specified hours"""
        cutoff = datetime.now() - timedelta(hours=hours)

        for directory in [self.temp_dir, self.output_dir]:
            for file_path in glob.glob(f"{directory}/*"):
                try:
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_time < cutoff:
                        os.remove(file_path)
                        print(f"Cleaned up: {file_path}")
                except Exception as e:
                    print(f"Error cleaning {file_path}: {e}")

    def cleanup_job_files(self, job_id: str):
        """Clean up all files associated with a job"""
        patterns = [
            f"{self.temp_dir}/*{job_id}*",
            f"{self.output_dir}/*{job_id}*"
        ]

        for pattern in patterns:
            for file_path in glob.glob(pattern):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error removing {file_path}: {e}")
```

## Error Messages

User-friendly error messages:
```python
ERROR_MESSAGES = {
    'invalid_format': 'Unsupported file format. Please upload a valid media file.',
    'file_too_large': 'File is too large. Maximum size is {max_size}MB.',
    'corrupted_file': 'File appears to be corrupted or incomplete.',
    'no_video_stream': 'Video file must contain a video stream.',
    'no_audio_stream': 'Audio file must contain an audio stream.',
    'processing_failed': 'Failed to process media file. Please try a different file.',
}
```

## FastAPI Dependency
```python
from fastapi import Depends

validator = MediaValidator(max_file_size=100 * 1024 * 1024)

async def validate_image_upload(file: UploadFile = File(...)):
    return await validator.validate_upload(
        file,
        allowed_types=['jpg', 'jpeg', 'png', 'webp', 'gif'],
        media_category='image'
    )

async def validate_video_upload(file: UploadFile = File(...)):
    return await validator.validate_upload(
        file,
        allowed_types=['mp4', 'mov', 'avi', 'webm', 'mkv'],
        media_category='video'
    )

# Use in endpoints
@app.post("/api/v1/images/resize")
async def resize_image(validated_file = Depends(validate_image_upload)):
    # validated_file contains temp_path, metadata, etc.
    pass
```
