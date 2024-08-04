# import json
# from fastapi import APIRouter, HTTPException, BackgroundTasks
# import boto3
# from botocore.config import Config
# # from app.config import settings
# from app import database
# from app.services import video_analyzer
# from app.services.video_processing import video_processing_service
# import os

# router = APIRouter()

# s3 = boto3.client('s3',
#                   endpoint_url=os.getenv('R2_ENDPOINT_URL'),
#                   aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
#                   aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
#                   config=Config(signature_version='s3v4')
#                   )


# # s3 = boto3.client(
# #     's3',
# #     endpoint_url=os.getenv('R2_ENDPOINT_URL'),
# #     aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
# #     aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
# #     region_name='weur'
# # )

# @router.get("/{video_id}")
# async def get_video_url(video_id: str):
#     try:
#         url = s3.generate_presigned_url('get_object',
#                                         Params={
#                                             'Bucket': os.getenv('R2_BUCKET_NAME'), 'Key': video_id},
#                                         ExpiresIn=3600
#                                         )
#         return {"url": url}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/{video_id}/analyze")
# async def analyze_video(video_id: str, background_tasks: BackgroundTasks):
#     try:
#         video_path = f"/tmp/{video_id}"
#         s3.download_file(os.getenv('R2_BUCKET_NAME'), video_id, video_path)

#         analyzer = video_analyzer(video_path, video_id)
#         background_tasks.add_task(analyzer.analyze_video)

#         return {"message": "Video analysis started"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/{video_id}/analysis")
# async def get_video_analysis(video_id: str):
#     try:
#         query = """
#         SELECT timestamp, objects
#         FROM video_analysis
#         WHERE video_id = :video_id
#         ORDER BY timestamp
#         """
#         results = await database.fetch_all(query=query, values={'video_id': video_id})
#         return [{'timestamp': r['timestamp'], 'objects': json.loads(r['objects'])} for r in results]
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.post("/{video_id}/process")
# async def process_video(video_id: str, background_tasks: BackgroundTasks):
#     try:
#         video_path = f"/tmp/{video_id}"
#         s3.download_file(os.getenv('R2_BUCKET_NAME'), video_id, video_path)

#         background_tasks.add_task(
#             video_processing_service.process_video, video_path)

#         return {"message": "Video processing started"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
