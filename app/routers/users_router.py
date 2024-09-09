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
    SELECT u.id, u.username, u.full_name, u.bio, u.avatar_url, u.cover_image, u.status, u.last_username_change,
           COALESCE(l.likes_count, 0) as likes_count,
           COALESCE(f.followers_count, 0) as followers_count,
           COALESCE(f2.following_count, 0) as following_count
    FROM users u
    LEFT JOIN (
        SELECT user_id, COUNT(*) as likes_count
        FROM likes
        GROUP BY user_id
    ) l ON l.user_id = u.id
    LEFT JOIN (
        SELECT followed_id, COUNT(*) as followers_count
        FROM followers
        GROUP BY followed_id
    ) f ON f.followed_id = u.id
    LEFT JOIN (
        SELECT follower_id, COUNT(*) as following_count
        FROM followers
        GROUP BY follower_id
    ) f2 ON f2.follower_id = u.id
    WHERE u.username = :username
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
            "status": user["status"],
            "last_username_change": user["last_username_change"],
            "likes_count": user["likes_count"],
            "followers_count": user["followers_count"],
            "following_count": user["following_count"]
        }
    else:
        raise HTTPException(status_code=404, detail="User not found")



# social function follow / unfollow / block / unblock


@router.post("/follow/{user_id}")
async def follow_user(user_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    if current_user['uid'] == user_id:
        raise HTTPException(
            status_code=400, detail="You cannot follow yourself")

    query = """
    INSERT INTO followers (follower_id, followed_id)
    VALUES (:follower_id, :followed_id)
    ON CONFLICT (follower_id, followed_id) DO NOTHING
    """
    values = {"follower_id": current_user['uid'], "followed_id": user_id}

    await db.execute(query=query, values=values)
    return {"message": "User followed successfully"}


@router.post("/unfollow/{user_id}")
async def unfollow_user(user_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    DELETE FROM followers
    WHERE follower_id = :follower_id AND followed_id = :followed_id
    """
    values = {"follower_id": current_user['uid'], "followed_id": user_id}

    await db.execute(query=query, values=values)
    return {"message": "User unfollowed successfully"}


@router.post("/block/{user_id}")
async def block_user(user_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    if current_user['uid'] == user_id:
        raise HTTPException(
            status_code=400, detail="You cannot block yourself")

    query = """
    INSERT INTO blocks (blocker_id, blocked_id)
    VALUES (:blocker_id, :blocked_id)
    ON CONFLICT (blocker_id, blocked_id) DO NOTHING
    """
    values = {"blocker_id": current_user['uid'], "blocked_id": user_id}

    await db.execute(query=query, values=values)

    # Remove any existing follow relationship
    unfollow_query = """
    DELETE FROM followers
    WHERE (follower_id = :user1 AND followed_id = :user2)
    OR (follower_id = :user2 AND followed_id = :user1)
    """
    unfollow_values = {"user1": current_user['uid'], "user2": user_id}
    await db.execute(query=unfollow_query, values=unfollow_values)

    return {"message": "User blocked successfully"}


@router.post("/unblock/{user_id}")
async def unblock_user(user_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    DELETE FROM blocks
    WHERE blocker_id = :blocker_id AND blocked_id = :blocked_id
    """
    values = {"blocker_id": current_user['uid'], "blocked_id": user_id}

    await db.execute(query=query, values=values)
    return {"message": "User unblocked successfully"}


@router.get("/is_following/{user_id}")
async def is_following(user_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    SELECT EXISTS(
        SELECT 1 FROM followers
        WHERE follower_id = :follower_id AND followed_id = :followed_id
    )
    """
    values = {"follower_id": current_user['uid'], "followed_id": user_id}

    result = await db.fetch_val(query=query, values=values)
    return {"is_following": result}


@router.get("/is_blocked/{user_id}")
async def is_blocked(user_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    SELECT EXISTS(
        SELECT 1 FROM blocks
        WHERE blocker_id = :blocker_id AND blocked_id = :blocked_id
    )
    """
    values = {"blocker_id": current_user['uid'], "blocked_id": user_id}

    result = await db.fetch_val(query=query, values=values)
    return {"is_blocked": result}


@router.get("/followers")
async def get_followers(current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    SELECT u.id, u.username, u.full_name, u.avatar_url
    FROM followers f
    JOIN users u ON f.follower_id = u.id
    WHERE f.followed_id = :user_id
    """
    values = {"user_id": current_user['uid']}

    followers = await db.fetch_all(query=query, values=values)
    return {"followers": followers}


@router.get("/following")
async def get_following(current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    SELECT u.id, u.username, u.full_name, u.avatar_url
    FROM followers f
    JOIN users u ON f.followed_id = u.id
    WHERE f.follower_id = :user_id
    """
    values = {"user_id": current_user['uid']}

    following = await db.fetch_all(query=query, values=values)
    return {"following": following}
