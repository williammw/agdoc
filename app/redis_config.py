# # redis_config.py
# import aioredis
# import os

# REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

# async def get_redis():
#     redis = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
#     try:
#         yield redis
#     finally:
#         await redis.close()
