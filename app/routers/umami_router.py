from fastapi import APIRouter

router = APIRouter()


@router.get("/greeting")
async def greeting():
    return {"message": "Hello from Umami!"}
