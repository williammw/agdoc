# In your FastAPI backend (e.g., main.py or users.py)

from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user, get_database
from databases import Database

router = APIRouter()


@router.get("/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    SELECT id, username, full_name, bio, avatar_url, cover_image, status
    FROM users
    WHERE id = :id
    """
    user = await db.fetch_one(query=query, values={"id": current_user["id"]})

    if user:
        return {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "bio": user["bio"],
            "avatar_url": user["avatar_url"],
            "cover_image": user["cover_image"],
            "status": user["status"]
        }
    else:
        raise HTTPException(status_code=404, detail="User profile not found")


@router.get("/me/{username}")
async def get_public_user_profile(username: str, db: Database = Depends(get_database)):
    query = """
    SELECT id, username, full_name, bio, avatar_url, cover_image, status
    FROM users
    WHERE username = :username
    """
    user = await db.fetch_one(query=query, values={"username": username})

    if user:
        return {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "bio": user["bio"],
            "avatar_url": user["avatar_url"],
            "cover_image": user["cover_image"],
            "status":user["status"]
        }
    else:
        raise HTTPException(status_code=404, detail="User not found")
