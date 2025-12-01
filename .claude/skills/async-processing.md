# Async Processing Skill

You are an expert in asynchronous task processing and job queue management.

## Task Queue Architecture

### Why Async Processing?

Media processing operations (especially video) can take seconds to minutes. Async processing:
- Prevents request timeouts
- Allows concurrent processing
- Provides progress tracking
- Enables retry mechanisms
- Improves user experience

### Architecture Options

#### 1. Simple Background Tasks (FastAPI Built-in)
**Best for**: Quick operations (< 30 seconds)
```python
from fastapi import BackgroundTasks

@app.post("/process")
async def process(background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    background_tasks.add_task(process_media, job_id)
    return {"job_id": job_id}
```

**Limitations**:
- No persistence across restarts
- No distributed processing
- Limited to single worker

#### 2. Redis + Simple Queue
**Best for**: Medium complexity, single server
```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, db=0)

# Queue job
def queue_job(job_id, params):
    redis_client.lpush('media_queue', json.dumps({
        'job_id': job_id,
        'params': params,
        'status': 'pending'
    }))

# Worker processes queue
def worker():
    while True:
        job = redis_client.brpop('media_queue', timeout=5)
        if job:
            process_job(json.loads(job[1]))
```

#### 3. Celery + Redis/RabbitMQ
**Best for**: Complex, distributed systems
```python
from celery import Celery

celery_app = Celery('tasks', broker='redis://localhost:6379/0')

@celery_app.task(bind=True)
def process_video(self, job_id, params):
    # Update progress
    self.update_state(state='PROGRESS', meta={'progress': 50})
    # Process video
    return result
```

## Recommended: Redis-based Simple Queue

For this media processing API, I recommend a **Redis-based approach**:
- Lightweight and fast
- Built-in data structures (hashes for job status)
- TTL for automatic cleanup
- Pub/Sub for real-time updates
- Easy to scale

### Implementation Pattern

```python
import redis
import json
from datetime import datetime, timedelta
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class JobQueue:
    def __init__(self):
        self.redis = redis.Redis(
            host='localhost',
            port=6379,
            db=0,
            decode_responses=True
        )

    def create_job(self, job_id: str, job_type: str, params: dict):
        """Create a new job"""
        job_data = {
            'job_id': job_id,
            'type': job_type,
            'params': json.dumps(params),
            'status': JobStatus.PENDING,
            'progress': 0,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        # Store job details
        self.redis.hset(f'job:{job_id}', mapping=job_data)
        # Set expiry (24 hours)
        self.redis.expire(f'job:{job_id}', 86400)
        # Add to processing queue
        self.redis.lpush('job_queue', job_id)

        return job_id

    def get_job(self, job_id: str):
        """Get job status and details"""
        job_data = self.redis.hgetall(f'job:{job_id}')
        if not job_data:
            return None
        return {
            **job_data,
            'params': json.loads(job_data.get('params', '{}'))
        }

    def update_job(self, job_id: str, status: JobStatus = None,
                   progress: int = None, result_url: str = None,
                   error: str = None):
        """Update job status"""
        updates = {'updated_at': datetime.utcnow().isoformat()}

        if status:
            updates['status'] = status
        if progress is not None:
            updates['progress'] = progress
        if result_url:
            updates['result_url'] = result_url
        if error:
            updates['error'] = error

        self.redis.hset(f'job:{job_id}', mapping=updates)

    def get_next_job(self):
        """Get next job from queue (blocking)"""
        job_id = self.redis.brpop('job_queue', timeout=5)
        if job_id:
            return job_id[1]
        return None
```

### Worker Process

```python
import asyncio
from job_queue import JobQueue, JobStatus
from media_processor import process_media

async def worker():
    """Background worker process"""
    queue = JobQueue()

    while True:
        try:
            # Get next job
            job_id = queue.get_next_job()
            if not job_id:
                await asyncio.sleep(1)
                continue

            # Get job details
            job = queue.get_job(job_id)
            if not job:
                continue

            # Update status
            queue.update_job(job_id, status=JobStatus.PROCESSING, progress=0)

            # Process based on job type
            result = await process_media(
                job_id=job_id,
                job_type=job['type'],
                params=job['params'],
                progress_callback=lambda p: queue.update_job(job_id, progress=p)
            )

            # Update with result
            queue.update_job(
                job_id,
                status=JobStatus.COMPLETED,
                progress=100,
                result_url=result['url']
            )

        except Exception as e:
            # Handle failure
            queue.update_job(
                job_id,
                status=JobStatus.FAILED,
                error=str(e)
            )
            print(f"Job {job_id} failed: {e}")

        await asyncio.sleep(0.1)

if __name__ == "__main__":
    asyncio.run(worker())
```

### FastAPI Integration

```python
from fastapi import FastAPI, UploadFile, File
from job_queue import JobQueue
import uuid

app = FastAPI()
queue = JobQueue()

@app.post("/api/v1/videos/resize")
async def resize_video(
    file: UploadFile = File(...),
    width: int = 1280,
    height: int = 720
):
    # Save uploaded file
    file_path = await save_upload(file)

    # Create job
    job_id = str(uuid.uuid4())
    queue.create_job(
        job_id=job_id,
        job_type='video_resize',
        params={
            'input_path': file_path,
            'width': width,
            'height': height
        }
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "status_url": f"/api/v1/jobs/{job_id}"
    }

@app.get("/api/v1/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job['status'],
        "progress": int(job.get('progress', 0)),
        "result_url": job.get('result_url'),
        "error": job.get('error')
    }
```

## Progress Tracking

### FFmpeg Progress Parsing
```python
import re
import subprocess

def run_ffmpeg_with_progress(cmd, job_id, queue, duration):
    """Run FFmpeg and track progress"""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )

    for line in process.stdout:
        # Parse time progress
        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
        if time_match and duration:
            h, m, s = time_match.groups()
            current = int(h) * 3600 + int(m) * 60 + float(s)
            progress = int((current / duration) * 100)
            queue.update_job(job_id, progress=min(progress, 99))

    process.wait()
    return process.returncode
```

## Best Practices

1. **Job ID Generation** - Use UUID4 for unique IDs
2. **TTL/Expiry** - Auto-delete old jobs (24-48 hours)
3. **Cleanup** - Delete temporary files after job completion
4. **Retries** - Implement retry logic for transient failures
5. **Timeouts** - Set max processing time per job
6. **Monitoring** - Log queue length, processing times
7. **Graceful Shutdown** - Handle SIGTERM properly
8. **Health Checks** - Endpoint to check worker status

## Starting the Worker

```bash
# Run worker as separate process
python worker.py

# Or use supervisor/systemd for production
# supervisord.conf
[program:media_worker]
command=python /app/worker.py
directory=/app
autostart=true
autorestart=true
stderr_logfile=/var/log/worker.err.log
stdout_logfile=/var/log/worker.out.log
```

## Scaling

- **Horizontal**: Run multiple worker processes
- **Vertical**: Increase worker resources
- **Queue Priority**: Separate queues for different job types
- **Load Balancing**: Distribute jobs across workers
