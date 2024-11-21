from itertools import groupby
import json
import mimetypes
from asyncpg.exceptions import UndefinedColumnError
import traceback
import asyncpg
from fastapi.logger import logger
from fastapi import Form, HTTPException
from fastapi import Form
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Header, Query, BackgroundTasks, Request
from app.dependencies import get_current_user, get_database, verify_token
from databases import Database
from pydantic import BaseModel, constr, HttpUrl
from datetime import datetime, timedelta
import uuid
import boto3
import os
from fastapi.security import OAuth2PasswordBearer
from typing import Optional, List
import bleach
import imghdr
import re
from urllib.parse import urlparse
import requests
import sys
from bs4 import BeautifulSoup
import logging
from PIL import Image

from botocore.exceptions import ClientError

# from app.routers.auth2_router import UserResponse
from app.models.modelapp import UserResponse
# from app.routers.cdn_router import upload_to_cloudflare
from app.utils.cloudflare import delete_file_from_r2, upload_to_r2
# from app.utils.cloudflare import upload_to_cloudflare


from pydantic import BaseModel
from app.models.modelapp import SharedPostResponse, SharedPostCreate, SharedPostResponse, PostResponse, CommentResponse, MediaItem, User, UserInteraction, UserInteractionResponse, PostResponseWithMedia, ReportCreate, ReportResponse
from app.routers.videos_router import upload_and_convert_video

class SharedPostCreate(BaseModel):
    # Add the fields you need for creating a shared post
    original_post_id: int
    # Add other fields as necessary


router = APIRouter()
logger = logging.getLogger(__name__)


# Initialize S3 client
s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name='weur'
)
bucket_name = 'umami'

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# async def upload_media(file: UploadFile, post_id: str, index: int):
#     print('upload_media')
#     try:
#         bucket_name = os.getenv('R2_BUCKET_NAME')
#         file_extension = os.path.splitext(file.filename)[1]
#         object_name = f"posts/{post_id}/{index}{file_extension}"

#         file.file.seek(0)
#         s3.upload_fileobj(
#             file.file,
#             bucket_name,
#             object_name,
#             ExtraArgs={'ContentType': file.content_type}
#         )

#         media_url = f"https://{os.getenv('R2_DEV_URL')}/{object_name}"
#         logger.info(f"Media uploaded successfully: {media_url}")
#         return media_url
#     except Exception as e:
#         logger.error(f"Failed to upload media: {str(e)}")
#         raise

async def upload_media(file: UploadFile, user_id: str, dimensions: dict) -> dict:
    try:
        r2_response = await upload_to_r2(file, user_id)
        if not r2_response.get('url'):
            raise ValueError("No URL returned from R2 upload")
        return {
            'url': r2_response['url'],
            'type': file.content_type,
            'width': dimensions.get('width'),
            'height': dimensions.get('height'),
            'aspect_ratio': dimensions.get('width') / dimensions.get('height') if dimensions.get('width') and dimensions.get('height') else None
        }
    except Exception as e:
        logger.error(f"Error uploading media to R2: {str(e)}")
        raise




ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png',
                      '.gif', '.webp'}  # Allowed image file extensions
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_image(file: UploadFile) -> bool:
    # Check file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="File type not allowed")

    # Check file size
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size too large")

    # Check file content using Pillow
    try:
        file.file.seek(0)
        image = Image.open(file.file)
        image.verify()  # Verify that it is an image
        if image.format.lower() not in ['jpeg', 'png', 'gif', 'webp']:
            raise HTTPException(
                status_code=400, detail="Invalid image file format")
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid image file: {str(e)}")
    finally:
        file.file.seek(0)  # Reset file pointer after verification

    return True


@router.get("/{post_id}")
async def get_post_detail(post_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = """
    SELECT p.*, u.username, u.avatar_url
    FROM posts p
    JOIN users u ON p.user_id = u.id
    WHERE p.id = :post_id
    """
    post = await db.fetch_one(query=query, values={"post_id": post_id})

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Privacy checks
    if post['user_id'] != current_user["id"]:
        if post['privacy_setting'] == 'private':
            raise HTTPException(
                status_code=403, detail="You don't have permission to view this post")
        elif post['privacy_setting'] == 'followers':
            is_following = await check_if_following(db, current_user["id"], post['user_id'])
            if not is_following:
                raise HTTPException(
                    status_code=403, detail="You don't have permission to view this post")
        elif post['privacy_setting'] == 'mutual_followers':
            is_mutual_follow = await check_if_mutual_follow(db, current_user["id"], post['user_id'])
            if not is_mutual_follow:
                raise HTTPException(
                    status_code=403, detail="You don't have permission to view this post")

    media_query = """
    SELECT media_url, media_type, order_index, cloudflare_info
    FROM post_media
    WHERE post_id = :post_id
    ORDER BY order_index
    """
    media = await db.fetch_all(query=media_query, values={"post_id": post_id})

    comments_query = """
    SELECT c.*, u.username, u.avatar_url
    FROM comments c
    JOIN users u ON c.user_id = u.id
    WHERE c.post_id = :post_id
    ORDER BY c.created_at DESC
    """
    comments = await db.fetch_all(query=comments_query, values={"post_id": post_id})

    return {
        **post,
        "media": media,
        "comments": comments,
        "user": {
            "username": post["username"],
            "avatar_url": post["avatar_url"]
        }
    }




class PostUpdate(BaseModel):
    content: constr(max_length=5000)


@router.put("/{post_id}", response_model=PostResponse, operation_id="update_post")
async def update_post(
    post_id: str,
    post_update: PostUpdate,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    sanitized_content = bleach.clean(post_update.content)

    query = """
    UPDATE posts 
    SET content = :content, updated_at = :updated_at
    WHERE id = :post_id AND user_id = :user_id
    RETURNING *
    """
    values = {
        "post_id": post_id,
        "user_id": user_id,
        "content": sanitized_content,
        "updated_at": datetime.now()
    }

    result = await db.fetch_one(query=query, values=values)

    if result is None:
        raise HTTPException(
            status_code=404, detail="Post not found or you don't have permission to update it")

    return PostResponse(**result)


class PrivacyUpdate(BaseModel):
    privacy_setting: str


@router.patch("/{post_id}/privacy")
async def update_post_privacy(
    post_id: str,
    privacy_update: PrivacyUpdate,
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    # Check if the post exists and belongs to the current user
    query = """
    SELECT * FROM posts WHERE id = :post_id AND user_id = :user_id
    """
    post = await db.fetch_one(query=query, values={"post_id": post_id, "user_id": current_user['id']})

    if not post:
        raise HTTPException(
            status_code=404, detail="Post not found or you don't have permission to modify it")

    # Update the post's privacy setting
    update_query = """
    UPDATE posts
    SET privacy_setting = :privacy_setting
    WHERE id = :post_id
    RETURNING *
    """
    updated_post = await db.fetch_one(
        query=update_query,
        values={
            "post_id": post_id,
            "privacy_setting": privacy_update.privacy_setting
        }
    )

    return updated_post


@router.delete("/{post_id}")
async def delete_post(post_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    async with db.transaction():
        # Verify the post belongs to the current user
        post = await db.fetch_one("SELECT * FROM posts WHERE id = :id AND user_id = :user_id",
                                  values={"id": post_id, "user_id": current_user["id"]})
        if not post:
            raise HTTPException(
                status_code=404, detail="Post not found or you don't have permission to delete it")

        try:
            # Fetch media URLs associated with the post
            media_records = await db.fetch_all("SELECT media_url FROM post_media WHERE post_id = :post_id",
                                               values={"post_id": post_id})

            # Delete media files from Cloudflare R2
            for media in media_records:
                await delete_file_from_r2(media['media_url'])

            # Delete the post (this will cascade to delete post_media records)
            await db.execute("DELETE FROM posts WHERE id = :id", values={"id": post_id})

            return {"message": "Post and associated media deleted successfully"}
        except Exception as e:
            print(f"Error deleting post and media: {str(e)}")
            raise HTTPException(
                status_code=500, detail="An error occurred while deleting the post and media")


# ... (keep existing imports and configurations)


class CommentCreate(BaseModel):
    content: constr(max_length=1000)


class CommentResponse(BaseModel):
    id: str
    user_id: str
    post_id: str
    content: str
    created_at: datetime
    updated_at: datetime


# ... (keep existing functions like validate_image)


@router.post("/{post_id}/comments", response_model=CommentResponse)
async def create_comment(
    post_id: str,
    comment: CommentCreate,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    comment_id = str(uuid.uuid4())[:28]
    sanitized_content = bleach.clean(comment.content)

    async with db.transaction():
        insert_query = """
        INSERT INTO comments (id, user_id, post_id, content, created_at, updated_at)
        VALUES (:id, :user_id, :post_id, :content, :created_at, :updated_at)
        RETURNING *
        """
        values = {
            "id": comment_id,
            "user_id": user_id,
            "post_id": post_id,
            "content": sanitized_content,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        new_comment = await db.fetch_one(insert_query, values=values)

        # Update comment count on the post
        update_query = """
        UPDATE posts SET comments_count = comments_count + 1
        WHERE id = :post_id
        """
        await db.execute(update_query, values={"post_id": post_id})

    return CommentResponse(**new_comment)


@router.get("/{post_id}/comments", response_model=List[CommentResponse])
async def get_post_comments(
    post_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    query = """
    SELECT * FROM comments 
    WHERE post_id = :post_id 
    ORDER BY created_at DESC 
    LIMIT :limit OFFSET :skip
    """
    comments = await db.fetch_all(query, values={"post_id": post_id, "limit": limit, "skip": skip})

    return [CommentResponse(**comment) for comment in comments]


@router.get("/user/{username}", response_model=List[PostResponse])
async def get_user_posts(
    username: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        # Verify token
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
        logger.info(f"User authenticated: {user_id}")

        post_id = str(uuid.uuid4())[:28]
        sanitized_content = bleach.clean(content)
        logger.info(f"Creating post: {post_id}")

        logger.info(f"Content: {content}")
        logger.info(f"Privacy setting: {privacy_setting}")
        logger.info(f"Media count: {media_count}")

        form_data = await request.form()
        media_data = []

        for i in range(media_count):
            media_file = form_data.get(f'media_{i}')
            media_dimensions = form_data.get(f'media_dimensions_{i}')
            media_info = form_data.get(f'media_info_{i}')

            if media_file:
                dimensions = json.loads(media_dimensions)
                media_info = await upload_media(media_file, user_id, dimensions)
                media_data.append(media_info)
            elif media_info:
                video_info = json.loads(media_info)
                media_data.append(video_info)

        # Insert post
        post_query = """
        INSERT INTO posts (id, user_id, content, privacy_setting, created_at, updated_at)
        VALUES (:id, :user_id, :content, :privacy_setting, :created_at, :updated_at)
        RETURNING *
        """
        post_values = {
            "id": post_id,
            "user_id": user_id,
            "content": sanitized_content,
            "privacy_setting": privacy_setting,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        post_result = await db.fetch_one(query=post_query, values=post_values)
        logger.info(f"Post inserted: {post_id}")
        logger.info(f"MEDIA INFO: {media_data}")

        # Insert media
        if media_data:
            media_query = """
            INSERT INTO post_media (post_id, media_url, media_type, order_index, width, height, aspect_ratio, cloudflare_info)
            VALUES (:post_id, :media_url, :media_type, :order_index, :width, :height, :aspect_ratio, :cloudflare_info)
            """
            for index, media_info in enumerate(media_data):
                media_values = {
                    "post_id": post_id,
                    "media_url": media_info.get('url') or media_info.get('mp4_file_url'),
                    "media_type": media_info['type'],
                    "order_index": index,
                    "width": media_info.get('width'),
                    "height": media_info.get('height'),
                    "aspect_ratio": media_info.get('width') / media_info.get('height') if media_info.get('width') and media_info.get('height') else None,
                    "cloudflare_info": json.dumps(media_info) if media_info['type'] == 'video' else None
                }
                await db.execute(query=media_query, values=media_values)
            logger.info(
                f"Inserted {len(media_data)} media entries for post {post_id}")

        # Fetch media for response
        media_result = await db.fetch_all(
            "SELECT media_url, media_type, width, height, aspect_ratio, cloudflare_info FROM post_media WHERE post_id = :post_id ORDER BY order_index",
            values={"post_id": post_id}
        )
        logger.info(f"Fetched {len(media_result)} media entries for response")

        # Combine post and media data
        response_data = dict(post_result)
        response_data['media'] = [dict(m) for m in media_result]

        logger.info(f"Returning response for post {post_id}")
        return response_data

    except Exception as e:
        logger.error(f"Error creating post: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create post: {str(e)}")


@router.post("/share", response_model=SharedPostResponse)
async def share_post(
    shared_post: SharedPostCreate,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    share_id = str(uuid.uuid4())[:28]

    async with db.transaction():
        # Create shared post
        insert_query = """
        INSERT INTO shared_posts (id, user_id, original_post_id, content, created_at)
        VALUES (:id, :user_id, :original_post_id, :content, :created_at)
        RETURNING *
        """
        values = {
            "id": share_id,
            "user_id": user_id,
            "original_post_id": shared_post.original_post_id,
            "content": shared_post.content,
            "created_at": datetime.now()
        }
        new_share = await db.fetch_one(insert_query, values=values)

        # Fetch original post
        original_post_query = "SELECT * FROM posts WHERE id = :post_id"
        original_post = await db.fetch_one(original_post_query, values={"post_id": shared_post.original_post_id})

        if not original_post:
            raise HTTPException(
                status_code=404, detail="Original post not found")

        # Create notification for original post owner
        await create_notification(
            db,
            original_post['user_id'],
            "share",
            f"User shared your post",
            shared_post.original_post_id
        )

    return SharedPostResponse(
        **new_share,
        original_post=PostResponse(**original_post)
    )


@router.get("/search", response_model=List[PostResponseWithMedia])
async def search_posts(
    query: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    search_query = """
    SELECT * FROM posts
    WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :query)
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :skip
    """
    posts = await db.fetch_all(search_query, values={"query": query, "limit": limit, "skip": skip})

    return [PostResponseWithMedia(**post) for post in posts]


@router.get("/users/search", response_model=List[UserResponse])
async def search_users(
    query: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    search_query = """
    SELECT * FROM users
    WHERE username ILIKE :query OR full_name ILIKE :query
    ORDER BY username
    LIMIT :limit OFFSET :skip
    """
    users = await db.fetch_all(search_query, values={"query": f"%{query}%", "limit": limit, "skip": skip})

    return [UserResponse(**user) for user in users]


@router.get("/feed", response_model=List[PostResponseWithMedia])
async def get_feed(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    # Enhanced feed algorithm
    query = """
    WITH user_interactions AS (
        SELECT post_id, COUNT(*) as interaction_count
        FROM (
            SELECT post_id FROM post_likes WHERE user_id = :user_id
            UNION ALL
            SELECT post_id FROM comments WHERE user_id = :user_id
        ) interactions
        GROUP BY post_id
    )
    SELECT p.*, COALESCE(ui.interaction_count, 0) as user_interaction_count
    FROM posts p
    LEFT JOIN user_interactions ui ON p.id = ui.post_id
    WHERE p.user_id IN (
        SELECT followed_id FROM user_followers WHERE follower_id = :user_id
    ) OR p.user_id = :user_id
    ORDER BY 
        CASE WHEN p.user_id = :user_id THEN 1 ELSE 0 END DESC,
        user_interaction_count DESC,
        p.created_at DESC
    LIMIT :limit OFFSET :skip
    """
    posts = await db.fetch_all(query, values={"user_id": user_id, "limit": limit, "skip": skip})

    return [PostResponseWithMedia(**post) for post in posts]


class ReportCreate(BaseModel):
    reported_id: str
    content_type: str  # 'post', 'comment', or 'user'
    reason: str


class ReportResponse(BaseModel):
    id: str
    reporter_id: str
    reported_id: str
    content_type: str
    reason: str
    status: str
    created_at: datetime
    updated_at: datetime


class PostAnalytics(BaseModel):
    view_count: int
    share_count: int
    engagement_rate: float


class HashtagResponse(BaseModel):
    id: str
    name: str
    use_count: int
    last_used_at: datetime

# ... (keep existing model classes and functions)


async def extract_and_save_hashtags(db: Database, post_id: str, content: str):
    hashtags = re.findall(r'#(\w+)', content)
    for hashtag in set(hashtags):  # Use set to remove duplicates
        # Try to get existing hashtag or create a new one
        query = """
        INSERT INTO hashtags (id, name, use_count, last_used_at)
        VALUES (:id, :name, 1, :last_used_at)
        ON CONFLICT (name) DO UPDATE
        SET use_count = hashtags.use_count + 1,
            last_used_at = EXCLUDED.last_used_at
        RETURNING id
        """
        values = {
            "id": str(uuid.uuid4())[:28],
            "name": hashtag,
            "last_used_at": datetime.utcnow()
        }
        result = await db.fetch_one(query, values)

        # Link hashtag to post
        link_query = """
        INSERT INTO post_hashtags (post_id, hashtag_id)
        VALUES (:post_id, :hashtag_id)
        ON CONFLICT DO NOTHING
        """
        await db.execute(link_query, {"post_id": post_id, "hashtag_id": result['id']})


async def update_post_analytics(db: Database, post_id: str, view_increment: int = 0, share_increment: int = 0):
    try:
        # Check which columns exist
        columns = []
        values = {"post_id": post_id}

        try:
            await db.fetch_one("SELECT view_count FROM post_analytics LIMIT 1")
            columns.append(
                "view_count = COALESCE(post_analytics.view_count, 0) + :view_increment")
            values["view_increment"] = view_increment
        except asyncpg.exceptions.UndefinedColumnError:
            pass

        try:
            await db.fetch_one("SELECT share_count FROM post_analytics LIMIT 1")
            columns.append(
                "share_count = COALESCE(post_analytics.share_count, 0) + :share_increment")
            values["share_increment"] = share_increment
        except asyncpg.exceptions.UndefinedColumnError:
            pass

        if not columns:
            logger.warning("No analytics columns found. Skipping update.")
            return

        # Construct the query
        query = f"""
        INSERT INTO post_analytics (post_id, {', '.join(col.split('=')[0].strip() for col in columns)})
        VALUES (:post_id, {', '.join([f':view_increment' if 'view_count' in col else f':share_increment' for col in columns])})
        ON CONFLICT (post_id) DO UPDATE
        SET {', '.join(columns)}
        """

        await db.execute(query, values)

    except Exception as e:
        logger.error(f"Error updating post analytics: {str(e)}")
        logger.error(traceback.format_exc())


@router.post("/report", response_model=ReportResponse)
async def report_content(
    report: ReportCreate,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        reporter_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    report_id = str(uuid.uuid4())[:28]
    query = """
    INSERT INTO reports (id, reporter_id, reported_id, content_type, reason, created_at, updated_at)
    VALUES (:id, :reporter_id, :reported_id, :content_type, :reason, :created_at, :updated_at)
    RETURNING *
    """
    values = {
        "id": report_id,
        "reporter_id": reporter_id,
        "reported_id": report.reported_id,
        "content_type": report.content_type,
        "reason": report.reason,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    result = await db.fetch_one(query, values)

    return ReportResponse(**result)


@router.get("/analytics/{post_id}", response_model=PostAnalytics)
async def get_post_analytics(
    post_id: str,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    # Check if the user is the owner of the post
    post_query = "SELECT user_id FROM posts WHERE id = :post_id"
    post = await db.fetch_one(post_query, {"post_id": post_id})
    if not post or post['user_id'] != user_id:
        raise HTTPException(
            status_code=403, detail="You don't have permission to view these analytics")

    query = "SELECT * FROM post_analytics WHERE post_id = :post_id"
    result = await db.fetch_one(query, {"post_id": post_id})

    if not result:
        raise HTTPException(
            status_code=404, detail="Analytics not found for this post")

    return PostAnalytics(**result)


@router.get("/trending_hashtags", response_model=List[HashtagResponse])
async def get_trending_hashtags(
    limit: int = Query(10, ge=1, le=50),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    query = """
    SELECT * FROM hashtags
    ORDER BY use_count DESC, last_used_at DESC
    LIMIT :limit
    """
    results = await db.fetch_all(query, {"limit": limit})

    return [HashtagResponse(**result) for result in results]


@router.get("/hashtag/{hashtag_name}", response_model=List[PostResponseWithMedia])
async def get_posts_by_hashtag(
    hashtag_name: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    query = """
    SELECT p.* FROM posts p
    JOIN post_hashtags ph ON p.id = ph.post_id
    JOIN hashtags h ON ph.hashtag_id = h.id
    WHERE h.name = :hashtag_name
    ORDER BY p.created_at DESC
    LIMIT :limit OFFSET :skip
    """
    results = await db.fetch_all(query, {"hashtag_name": hashtag_name, "limit": limit, "skip": skip})

    return [PostResponseWithMedia(**result) for result in results]

# ... (keep existing endpoints)


# async def check_if_following(db: Database, follower_id: str, followed_id: str) -> bool:
#     query = """
#     SELECT 1 FROM followers
#     WHERE follower_id = :follower_id AND followed_id = :followed_id
#     """
#     result = await db.fetch_one(query=query, values={
#         "follower_id": follower_id,
#         "followed_id": followed_id
#     })
#     return result is not None

@router.get("/{user_id}/all", response_model=List[PostResponse])
async def get_all_user_posts(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    logger.info(f"current['uid']: {current_user['uid']} user_id: {user_id}")
    if current_user['uid'] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to view these posts")

    query = """
    SELECT p.*, 
        COALESCE(json_agg(
            json_build_object(
                'id', pm.id,
                'media_url', pm.media_url,
                'media_type', pm.media_type,
                'width', pm.width,
                'height', pm.height,
                'aspect_ratio', pm.aspect_ratio,
                'cloudflare_info', pm.cloudflare_info,
                'status', COALESCE(pm.status, 'completed'),
                'task_id', pm.task_id
            ) ORDER BY pm.order_index
        ) FILTER (WHERE pm.id IS NOT NULL), '[]'::json) as media
    FROM posts p
    LEFT JOIN post_media pm ON p.id = pm.post_id
    WHERE p.user_id = :user_id
    GROUP BY p.id
    ORDER BY p.created_at DESC
    """
    results = await db.fetch_all(query=query, values={"user_id": user_id})

    return [PostResponse(**{**result, 'media': json.loads(result['media'])}) for result in results]


@router.get("/{user_id}/visible", response_model=List[PostResponse])
async def get_visible_user_posts(
    user_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        # Verify token and get current user
        token = authorization.split("Bearer ")[1]
        current_user = verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    # Check if the current user is following the target user
    is_following = await check_if_following(db, current_user['uid'], user_id)

    # Check if there's a mutual follow relationship
    is_mutual_follow = is_following and await check_if_following(db, user_id, current_user['uid'])

    query = """
    SELECT p.*, 
        COALESCE(json_agg(
            json_build_object(
                'id', pm.id, 
                'media_url', pm.media_url, 
                'media_type', pm.media_type,
                'order_index', pm.order_index,
                'aspect_ratio', pm.aspect_ratio,                
                'width', pm.width,
                'height', pm.height,
                'cloudflare_info', pm.cloudflare_info
            ) ORDER BY pm.order_index
        ) FILTER (WHERE pm.id IS NOT NULL), '[]') AS media,
        CASE WHEN l.user_id IS NOT NULL THEN TRUE ELSE FALSE END as liked_by_user,
        COALESCE(p.likes_count, 0) as likes_count
    FROM posts p
    LEFT JOIN post_media pm ON p.id = pm.post_id
    LEFT JOIN likes l ON p.id = l.post_id AND l.user_id = :current_user_id
    WHERE p.user_id = :user_id AND (
        p.privacy_setting = 'public'
        OR (p.privacy_setting = 'followers' AND :is_following = TRUE)
        OR (p.privacy_setting = 'mutual_followers' AND :is_mutual_follow = TRUE)
        OR (p.user_id = :current_user_id)  -- This allows the user to see their own private posts
    )
    GROUP BY p.id, l.user_id
    ORDER BY p.created_at DESC 
    LIMIT :limit OFFSET :skip
    """

    print(query)
    results = await db.fetch_all(query=query, values={
        "user_id": user_id,
        "current_user_id": current_user['uid'],
        "is_following": is_following,
        "is_mutual_follow": is_mutual_follow,
        "skip": skip,
        "limit": limit
    })

    return [PostResponse(**{**result, 'media': json.loads(result['media'])}) for result in results]

# Update the original endpoint as well


@router.get("/", response_model=List[PostResponse])
async def get_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        # Verify token and get user_id
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    query = """
    SELECT 
        p.*,
        COALESCE(json_agg(
            json_build_object(
                'id', pm.id, 
                'media_url', pm.media_url, 
                'media_type', pm.media_type,
                'order_index', pm.order_index,
                'aspect_ratio', pm.aspect_ratio,
                'width', pm.width,
                'height', pm.height,
                'cloudflare_info', pm.cloudflare_info
            ) ORDER BY pm.order_index
        ) FILTER (WHERE pm.id IS NOT NULL), '[]') AS media,
        CASE WHEN l.user_id IS NOT NULL THEN TRUE ELSE FALSE END as liked_by_user,
        COALESCE(p.likes_count, 0) as likes_count
    FROM posts p
    LEFT JOIN post_media pm ON p.id = pm.post_id
    LEFT JOIN likes l ON p.id = l.post_id AND l.user_id = :user_id
    GROUP BY p.id, l.user_id
    ORDER BY p.created_at DESC 
    LIMIT :limit OFFSET :skip
    """

    results = await db.fetch_all(query=query, values={"user_id": user_id, "skip": skip, "limit": limit})

    return [PostResponse(**{
        **result,
        'media': json.loads(result['media']),
        'liked_by_user': result['liked_by_user'],
        'likes_count': result['likes_count']
    }) for result in results]


@router.get("/feed", response_model=List[PostResponse])
async def get_user_feed(
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    query = """
    SELECT p.id, p.user_id, p.content, p.created_at, p.updated_at, p.privacy_setting
    FROM posts p
    JOIN followers f ON p.user_id = f.followed_id
    WHERE f.follower_id = :user_id
    AND (
        p.privacy_setting = 'public'
        OR (p.privacy_setting = 'followers')
        OR (p.privacy_setting = 'mutual_followers' AND EXISTS (
            SELECT 1 FROM followers 
            WHERE follower_id = p.user_id AND followed_id = :user_id
        ))
    )
    ORDER BY p.created_at DESC
    LIMIT :limit OFFSET :offset
    """
    results = await db.fetch_all(query=query, values={
        "user_id": current_user["id"],
        "limit": limit,
        "offset": offset
    })
    return [PostResponse(**result) for result in results]


# Helper functions for checking follower status
async def check_if_following(db: Database, follower_id: str, followed_id: str) -> bool:
    query = """
    SELECT EXISTS(
        SELECT 1 FROM followers 
        WHERE follower_id = :follower_id AND followed_id = :followed_id
    )
    """
    result = await db.fetch_val(query=query, values={"follower_id": follower_id, "followed_id": followed_id})
    return result


async def check_if_mutual_follow(db: Database, user1_id: str, user2_id: str) -> bool:
    query = """
    SELECT EXISTS(
        SELECT 1 FROM followers f1
        JOIN followers f2 ON f1.follower_id = f2.followed_id AND f1.followed_id = f2.follower_id
        WHERE f1.follower_id = :user1_id AND f1.followed_id = :user2_id
    )
    """
    result = await db.fetch_val(query=query, values={"user1_id": user1_id, "user2_id": user2_id})
    return result


@router.post("/{post_id}/like")
async def like_post(post_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    async with db.transaction():
        try:
            # Check if the like already exists
            check_query = "SELECT 1 FROM likes WHERE post_id = :post_id AND user_id = :user_id"
            existing_like = await db.fetch_one(check_query, values={"post_id": post_id, "user_id": current_user["id"]})

            if existing_like:
                # Like exists, so remove it (unlike)
                delete_query = "DELETE FROM likes WHERE post_id = :post_id AND user_id = :user_id"
                await db.execute(delete_query, values={"post_id": post_id, "user_id": current_user["id"]})

                # Decrement likes count
                update_query = "UPDATE posts SET likes_count = likes_count - 1 WHERE id = :post_id"
                await db.execute(update_query, values={"post_id": post_id})

                action = "unliked"
            else:
                # Like doesn't exist, so add it
                insert_query = "INSERT INTO likes (post_id, user_id) VALUES (:post_id, :user_id)"
                await db.execute(insert_query, values={"post_id": post_id, "user_id": current_user["id"]})

                # Increment likes count
                update_query = "UPDATE posts SET likes_count = likes_count + 1 WHERE id = :post_id"
                await db.execute(update_query, values={"post_id": post_id})

                action = "liked"

            # Fetch updated post details
            post_query = """
            SELECT p.*, 
                CASE WHEN l.user_id IS NOT NULL THEN TRUE ELSE FALSE END as liked_by_user,
                (SELECT COUNT(*) FROM likes WHERE post_id = p.id) as likes_count
            FROM posts p
            LEFT JOIN likes l ON p.id = l.post_id AND l.user_id = :user_id
            WHERE p.id = :post_id
            """
            updated_post = await db.fetch_one(post_query, values={"post_id": post_id, "user_id": current_user["id"]})

            if not updated_post:
                raise HTTPException(status_code=404, detail="Post not found")

            # Convert datetime fields to ISO format strings
            updated_post = dict(updated_post)
            updated_post['created_at'] = updated_post['created_at'].isoformat()
            updated_post['updated_at'] = updated_post['updated_at'].isoformat()

            return {
                "message": f"Post {action} successfully",
                "post": updated_post
            }

        except Exception as e:
            print(f"Error in like_post: {str(e)}")
            raise HTTPException(
                status_code=500, detail="An error occurred while processing the request")


@router.delete("/{post_id}/like")
async def unlike_post(post_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    async with db.transaction():
        # Remove like from likes table
        query = "DELETE FROM likes WHERE post_id = :post_id AND user_id = :user_id"
        result = await db.execute(query=query, values={"post_id": post_id, "user_id": current_user["id"]})

        if result == 0:
            raise HTTPException(status_code=400, detail="Post not liked")

        # Decrement likes count in posts table
        query = "UPDATE posts SET likes_count = likes_count - 1 WHERE id = :post_id"
        await db.execute(query=query, values={"post_id": post_id})

    return {"message": "Post unliked successfully"}


@router.get("/{post_id}/likes")
async def get_post_likes(post_id: str, db: Database = Depends(get_database)):
    query = "SELECT likes_count FROM posts WHERE id = :post_id"
    result = await db.fetch_one(query=query, values={"post_id": post_id})

    if result is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return {"likes": result["likes_count"]}


@router.get("/posts/{post_id}/liked")
async def check_post_liked(post_id: str, current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    query = "SELECT 1 FROM likes WHERE post_id = :post_id AND user_id = :user_id"
    result = await db.fetch_one(query=query, values={"post_id": post_id, "user_id": current_user["id"]})
    return {"liked": result is not None}


async def process_video_upload(db: Database, user_id: str, file: UploadFile, post_id: str):
    try:
        # Call the upload_and_convert_video function
        result = await upload_and_convert_video(BackgroundTasks(), file, user_id, db)
        
        # Extract the task_id from the JSONResponse
        response_content = json.loads(result.body.decode('utf-8'))
        task_id = response_content.get("task_id")
        
        if not task_id:
            raise ValueError("Task ID not found in the response")
        
        # Update the post with the task_id
        update_query = """
        UPDATE posts SET video_processing_task_id = :task_id, status = 'processing'
        WHERE id = :post_id
        """
        await db.execute(update_query, {"task_id": task_id, "post_id": post_id})
        
        return response_content
        
    except Exception as e:
        logger.error(f"Error processing video upload: {str(e)}")
        # Update post status to indicate error
        error_update_query = """
        UPDATE posts SET status = 'error', error_message = :error_message
        WHERE id = :post_id
        """
        await db.execute(error_update_query, {"error_message": str(e), "post_id": post_id})
        raise


@router.post("/", response_model=PostResponse)
async def create_post(
    background_tasks: BackgroundTasks,
    request: Request,
    authorization: str = Header(...),
    db: Database = Depends(get_database),
):
    try:
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']

        form_data = await request.form()
        
        content = form_data.get('content', '')
        privacy_setting = form_data.get('privacy_setting', 'public')
        
        post_id = str(uuid.uuid4())[:28]
        sanitized_content = bleach.clean(content)

        media_data = []
        media_count = int(form_data.get('media_co`unt', 0))

        async with db.transaction():
            # Insert post
            post_query = """
            INSERT INTO posts (id, user_id, content, privacy_setting, created_at, updated_at, status)
            VALUES (:id, :user_id, :content, :privacy_setting, :created_at, :updated_at, :status)
            RETURNING *
            """
            post_values = {
                "id": post_id,
                "user_id": user_id,
                "content": sanitized_content,
                "privacy_setting": privacy_setting,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "status": "processing"  # Initial status
            }
            post_result = await db.fetch_one(query=post_query, values=post_values)

            for i in range(media_count):
                media_file = form_data.get(f'media_{i}')
                if media_file:
                    if media_file.content_type.startswith('video'):
                        # For video files, prepare for background processing
                        task_id = str(uuid.uuid4())
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        unique_id = str(uuid.uuid4())
                        original_file_extension = os.path.splitext(media_file.filename)[1]
                        original_filename = f"{timestamp}_{unique_id}{original_file_extension}"
                        mp4_filename = f"{timestamp}_{unique_id}.mp4"
                        thumbnail_filename = f"{timestamp}_{unique_id}_thumbnail.jpg"
                        folder = f"media/{datetime.now().strftime('%Y/%m/%d')}"
                        original_file_key = f"{folder}/{original_filename}"
                        mp4_file_key = f"{folder}/{mp4_filename}"
                        thumbnail_file_key = f"{folder}/{thumbnail_filename}"

                        # Upload the original file to R2
                        s3.upload_fileobj(
                            media_file.file,
                            bucket_name,
                            original_file_key,
                            ExtraArgs={"ContentType": media_file.content_type, "ACL": "public-read"}
                        )

                        # Create a new task in the process_tasks table
                        task_query = """
                        INSERT INTO process_tasks (id, related_id, user_id, task_type, status, progress)
                        VALUES (:id, :related_id, :user_id, :task_type, :status, :progress)
                        """
                        task_values = {
                            "id": task_id,
                            "related_id": post_id,  # Changed from user_id to post_id
                            "user_id": user_id,     # Added user_id
                            "task_type": "video_conversion",
                            "status": "pending",
                            "progress": 0
                        }
                        await db.execute(task_query, task_values)

                        # Add the background task
                        background_tasks.add_task(
                            upload_and_convert_video,
                            db,
                            task_id,
                            original_file_key,
                            mp4_file_key,
                            thumbnail_file_key
                        )

                        media_data.append({
                            'type': 'video',
                            'task_id': task_id,
                            'status': 'processing',
                            'url': original_file_key
                        })
                    else:
                        # For image files, process as before
                        media_info = await upload_media(media_file, user_id, {})
                        media_data.append(media_info)

            # Insert media
            if media_data:
                media_query = """
                INSERT INTO post_media (post_id, media_url, media_type, order_index, width, height, aspect_ratio, cloudflare_info, status, task_id)
                VALUES (:post_id, :media_url, :media_type, :order_index, :width, :height, :aspect_ratio, :cloudflare_info, :status, :task_id)
                RETURNING id
                """
                for index, media_info in enumerate(media_data):
                    media_values = {
                        "post_id": post_id,
                        "media_url": media_info.get('url'),
                        "media_type": media_info['type'],
                        "order_index": index,
                        "width": media_info.get('width'),
                        "height": media_info.get('height'),
                        "aspect_ratio": media_info.get('width') / media_info.get('height') if media_info.get('width') and media_info.get('height') else None,
                        "cloudflare_info": json.dumps(media_info) if media_info['type'] == 'video' else None,
                        "status": media_info.get('status', 'completed'),
                        "task_id": str(media_info.get('task_id')) if media_info.get('task_id') else None
                    }
                    result = await db.fetch_one(query=media_query, values=media_values)
                    media_info['id'] = result['id']

            # Extract and save hashtags
            await extract_and_save_hashtags(db, post_id, sanitized_content)

        # Fetch media for response
        media_result = await db.fetch_all(
            "SELECT id, media_url, media_type, width, height, aspect_ratio, cloudflare_info, status, task_id FROM post_media WHERE post_id = :post_id ORDER BY order_index",
            values={"post_id": post_id}
        )

        # Combine post and media data
        response_data = dict(post_result)
        response_data['media'] = [
            {
                **dict(m),
                'cloudflare_info': json.loads(m['cloudflare_info']) if m['cloudflare_info'] else None,
                'task_id': str(m['task_id']) if m['task_id'] else None
            } for m in media_result
        ]

        return PostResponse(**response_data)

    except Exception as e:
        logger.error(f"Error creating post: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create post: {str(e)}")