# from fastapi import APIRouter, HTTPException
# from app.database import database
# # from app.services.redis_cache import redis_cache

# router = APIRouter()


# @router.get("/")
# # @redis_cache(expire=3600)
# async def search_database(query: str):
#     try:
#         query = f"""
#         SELECT * FROM food_items 
#         WHERE name ILIKE '%{query}%' 
#         OR description ILIKE '%{query}%'
#         LIMIT 10
#         """
#         results = await database.fetch_all(query)
#         return [dict(result) for result in results]
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
