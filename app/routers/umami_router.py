# umami_router.py is a FastAPI router that defines the routes for the Umami service.
from fastapi import APIRouter

router = APIRouter()


@router.get("/greeting")
async def greeting():
    return {"message": "Hello from Umami!"}
