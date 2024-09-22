# from collections import defaultdict
# from datetime import datetime, timedelta
# import subprocess
# import uuid
# from celery import Celery
# from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, HTTPException, Header, Request, UploadFile
# from fastapi.responses import FileResponse
# from fastapi_limiter import FastAPILimiter
# from fastapi_limiter.depends import RateLimiter
# from pydantic import BaseModel
# import redis
# from starlette.responses import JSONResponse
# import boto3
# import os
# import logging
# from app.dependencies import get_current_user
# from app.firebase_admin_config import verify_token

# router = APIRouter()
# # Set up logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# s3_client = boto3.client('s3',
#                         endpoint_url=os.getenv('R2_ENDPOINT_URL'),
#                         aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
#                         aws_secret_access_key=os.getenv(
#                             'R2_SECRET_ACCESS_KEY'),
#                         region_name='weur'
#                         )
# bucket_name = 'umami'


# # Update this if your ffmpeg path is different "",
# FFMPEG_PATH = os.getenv("FFMPEG_PATH", "/usr/bin/ffmpeg")


# # Redis setup for rate limiting
# # Celery setup
# REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
# celery_app = Celery('tasks', broker=REDIS_URL)

# try:
#     redis_client = redis.from_url(REDIS_URL)
#     redis_client.ping()  # Test the connection
#     USE_REDIS = True
#     logger.info("Successfully connected to Redis")
# except redis.ConnectionError:
#     USE_REDIS = False
#     logger.warning(
#         "Failed to connect to Redis. Using in-memory rate limiting.")


# class InMemoryRateLimiter:
#     def __init__(self):
#         self.requests = defaultdict(list)

#     async def limit(self, key: str, times: int, seconds: int):
#         now = datetime.now()
#         self.requests[key] = [t for t in self.requests[key]
#                               if t > now - timedelta(seconds=seconds)]
#         if len(self.requests[key]) >= times:
#             raise HTTPException(status_code=429, detail="Rate limit exceeded")
#         self.requests[key].append(now)


# class RateLimiter:
#     def __init__(self, times: int, seconds: int):
#         self.times = times
#         self.seconds = seconds
#         self.in_memory_limiter = InMemoryRateLimiter()

#     async def __call__(self, request: Request):
#         if USE_REDIS:
#             return await self.redis_limit(request)
#         else:
#             return await self.in_memory_limit(request)

#     async def redis_limit(self, request: Request):
#         client_ip = request.client.host
#         key = f"rate_limit:{client_ip}"
#         current = redis_client.get(key)

#         if current is not None and int(current) >= self.times:
#             raise HTTPException(status_code=429, detail="Rate limit exceeded")

#         pipe = redis_client.pipeline()
#         pipe.incr(key)
#         pipe.expire(key, self.seconds)
#         pipe.execute()

#     async def in_memory_limit(self, request: Request):
#         client_ip = request.client.host
#         await self.in_memory_limiter.limit(client_ip, self.times, self.seconds)


# rate_limit = RateLimiter(times=10, seconds=60)



# class ConvertRequest(BaseModel):
#     filename: str


# # Set up logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)


# class ConvertRequest(BaseModel):
#     file_key: str
#     unique_id: str


# @celery_app.task
# async def convert_video_task(input_path: str, output_path: str):
#     command = [
#         FFMPEG_PATH,
#         "-i", input_path,
#         "-c:v", "libx264",
#         "-c:a", "aac",
#         "-strict", "experimental",
#         output_path
#     ]
#     try:
#         result = subprocess.run(command, check=True, capture_output=True, text=True)
#         logger.info(f"FFmpeg stdout: {result.stdout}")
#         logger.info(f"FFmpeg stderr: {result.stderr}")
#     except subprocess.CalledProcessError as e:
#         logger.error(f"FFmpeg conversion failed: {str(e)}")
#         logger.error(f"FFmpeg stderr: {e.stderr}")
#         raise Exception(f"Video conversion failed: {str(e)}")




# @router.post("/upload-and-convert")
# async def upload_and_convert_video(
#     request: Request,
#     file: UploadFile = File(...),
#     authorization: str = Header(...),
#     background_tasks: BackgroundTasks = BackgroundTasks(),
#     limiter: None = Depends(rate_limit)
# ):
#     try:
#         token = authorization.split("Bearer ")[1]
#         decoded_token = verify_token(token)
#         user_id = decoded_token['uid']
#     except Exception as e:
#         raise HTTPException(
#             status_code=401, detail="Invalid authorization token")

#     try:
#         timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
#         unique_id = str(uuid.uuid4())
#         original_file_extension = os.path.splitext(file.filename)[1]
#         original_filename = f"{timestamp}_{unique_id}{original_file_extension}"
#         mp4_filename = f"{timestamp}_{unique_id}.mp4"

#         folder = f"{user_id}/videos"
#         original_file_key = f"{folder}/{original_filename}"
#         mp4_file_key = f"{folder}/{mp4_filename}"

#         # Upload the original file to R2
#         s3_client.upload_fileobj(
#             file.file,
#             bucket_name,
#             original_file_key,
#             ExtraArgs={"ContentType": file.content_type, "ACL": "public-read"}
#         )

#         original_file_url = f"https://{os.getenv('R2_DEV_URL')}/{original_file_key.replace('/', '%2F')}"

#         # If the file is not already MP4, queue the conversion task
#         if original_file_extension.lower() != '.mp4':
#             convert_video_task.delay(original_file_key, mp4_file_key)
#             mp4_file_url = f"https://{os.getenv('R2_DEV_URL')}/{mp4_file_key.replace('/', '%2F')}"
#             conversion_status = "pending"
#         else:
#             mp4_file_url = original_file_url
#             conversion_status = "not_needed"

#         return JSONResponse({
#             "original_file_url": original_file_url,
#             "mp4_file_url": mp4_file_url,
#             "conversion_status": conversion_status
#         })

#     except Exception as e:
#         logger.error(f"File upload failed: {str(e)}")
#         raise HTTPException(
#             status_code=500, detail=f"File upload failed: {str(e)}")
