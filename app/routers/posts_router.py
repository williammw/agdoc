from itertools import groupby
import mimetypes
from asyncpg.exceptions import UndefinedColumnError
import traceback
import asyncpg
from fastapi.logger import logger
from fastapi import Form, HTTPException
from fastapi import Form
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Header, Query, BackgroundTasks
from app.dependencies import get_database, verify_token
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

from app.routers.auth2_router import UserResponse


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

async def upload_media(file: UploadFile, post_id: str, index: int) -> dict:
    try:
        bucket_name = os.getenv('R2_BUCKET_NAME')
        file_extension = os.path.splitext(file.filename)[1]
        object_name = f"posts/{post_id}/{index}{file_extension}"

        # Determine media type
        media_type = 'video' if file.content_type.startswith(
            'video/') else 'image'

        # Reset file pointer to the beginning
        await file.seek(0)

        # Upload to Cloudflare R2
        s3.upload_fileobj(
            file.file,
            bucket_name,
            object_name,
            ExtraArgs={'ContentType': file.content_type}
        )

        media_url = f"https://{os.getenv('R2_DEV_URL')}/{object_name}"
        logger.info(f"Media uploaded successfully: {media_url}")

        return {"url": media_url, "type": media_type}
    except Exception as e:
        logger.error(f"Failed to upload media: {str(e)}")
        raise


class PostCreate(BaseModel):
    content: constr(max_length=5000)  # type: ignore # Limit content length


class MediaItem(BaseModel):
    media_url: str
    media_type: str
    order_index: int


class PostResponse(BaseModel):
    id: str
    user_id: str
    content: str
    # image_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    likes_count: int = 0
    comments_count: int = 0
    media: List[MediaItem] = []

    class Config:
        from_attributes = True



ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'} # Allowed image file extensions
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


@router.get("/{post_id}", response_model=PostResponse, operation_id="get_single_post")
async def get_post(
    post_id: str,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    query = "SELECT * FROM posts WHERE user_id = :post_id"
    result = await db.fetch_one(query=query, values={"post_id": post_id})

    if result is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return PostResponse(**result)


@router.get("/", response_model=List[PostResponse])
async def get_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        # Verify token
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    query = "SELECT * FROM posts ORDER BY created_at DESC LIMIT :limit OFFSET :skip"
    results = await db.fetch_all(query=query, values={"skip": skip, "limit": limit})

    return [PostResponse(**result) for result in results]


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
        "updated_at": datetime.utcnow()
    }

    result = await db.fetch_one(query=query, values=values)

    if result is None:
        raise HTTPException(
            status_code=404, detail="Post not found or you don't have permission to update it")

    return PostResponse(**result)


@router.delete("/{post_id}", status_code=204, operation_id="delete_post")
async def delete_post(
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

    query = "DELETE FROM posts WHERE id = :post_id AND user_id = :user_id"
    result = await db.execute(query=query, values={"post_id": post_id, "user_id": user_id})

    if result == 0:
        raise HTTPException(
            status_code=404, detail="Post not found or you don't have permission to delete it")

    return None



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

@router.post("/{post_id}/like", response_model=PostResponse, operation_id="like_post")
async def like_post(
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

    async with db.transaction():
        # Check if the user has already liked the post
        check_query = "SELECT id FROM post_likes WHERE user_id = :user_id AND post_id = :post_id"
        existing_like = await db.fetch_one(check_query, values={"user_id": user_id, "post_id": post_id})

        if existing_like:
            # Unlike the post
            delete_query = "DELETE FROM post_likes WHERE user_id = :user_id AND post_id = :post_id"
            await db.execute(delete_query, values={"user_id": user_id, "post_id": post_id})

            update_query = """
            UPDATE posts SET likes_count = likes_count - 1
            WHERE id = :post_id RETURNING *
            """
        else:
            # Like the post
            like_id = str(uuid.uuid4())[:28]
            insert_query = """
            INSERT INTO post_likes (id, user_id, post_id, created_at)
            VALUES (:id, :user_id, :post_id, :created_at)
            """
            await db.execute(insert_query, values={
                "id": like_id,
                "user_id": user_id,
                "post_id": post_id,
                "created_at": datetime.utcnow()
            })

            update_query = """
            UPDATE posts SET likes_count = likes_count + 1
            WHERE id = :post_id RETURNING *
            """

        updated_post = await db.fetch_one(update_query, values={"post_id": post_id})

        if not updated_post:
            raise HTTPException(status_code=404, detail="Post not found")

        return PostResponse(**updated_post)


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


@router.get("/user/{user_id}", response_model=List[PostResponse], operation_id="get_user_posts")
async def get_user_posts(
    user_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        token = authorization.split("Bearer ")[1]
        verify_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    # Fetch posts with media in a single query
    query = """
    SELECT p.id, p.user_id, p.content, p.created_at, p.updated_at, 
           p.likes_count, p.comments_count,
           pm.media_url, pm.media_type, pm.order_index
    FROM posts p
    LEFT JOIN post_media pm ON p.id = pm.post_id
    WHERE p.user_id = :user_id 
    ORDER BY p.created_at DESC, pm.order_index ASC
    LIMIT :limit OFFSET :skip
    """
    rows = await db.fetch_all(query, values={"user_id": user_id, "limit": limit, "skip": skip})

    # Group the results by post
    result = []
    for post_id, group in groupby(rows, key=lambda x: x['id']):
        group_list = list(group)
        post = group_list[0]
        post_dict = {
            'id': post['id'],
            'user_id': post['user_id'],
            'content': post['content'],
            'created_at': post['created_at'],
            'updated_at': post['updated_at'],
            'likes_count': post['likes_count'],
            'comments_count': post['comments_count'],
            'media': [
                MediaItem(
                    media_url=row['media_url'], media_type=row['media_type'], order_index=row['order_index'])
                for row in group_list
                if row['media_url'] is not None
            ]
        }
        result.append(PostResponse(**post_dict))

    return result


class NotificationResponse(BaseModel):
    id: str
    type: str
    content: str
    related_id: Optional[str]
    is_read: bool
    created_at: datetime

# ... (keep existing model classes)


async def create_notification(db: Database, user_id: str, type: str, content: str, related_id: Optional[str] = None):
    notification_id = str(uuid.uuid4())[:28]
    query = """
    INSERT INTO notifications (id, user_id, type, content, related_id, created_at)
    VALUES (:id, :user_id, :type, :content, :related_id, :created_at)
    """
    values = {
        "id": notification_id,
        "user_id": user_id,
        "type": type,
        "content": content,
        "related_id": related_id,
        "created_at": datetime.now()
    }
    await db.execute(query, values=values)

# ... (keep existing functions)


@router.post("/{post_id}/like", response_model=PostResponse)
async def like_post(
    post_id: str,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    # ... (keep existing like_post logic)

    # Add notification for post like
    post_query = "SELECT user_id FROM posts WHERE id = :post_id"
    post = await db.fetch_one(post_query, values={"post_id": post_id})
    if post and post['user_id'] != user_id:
        await create_notification(
            db,
            post['user_id'],
            "like",
            f"User liked your post",
            post_id
        )

    return PostResponse(**updated_post)




@router.put("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: str,
    comment_update: CommentCreate,
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

    sanitized_content = bleach.clean(comment_update.content)

    query = """
    UPDATE comments 
    SET content = :content, updated_at = :updated_at
    WHERE id = :comment_id AND user_id = :user_id
    RETURNING *
    """
    values = {
        "comment_id": comment_id,
        "user_id": user_id,
        "content": sanitized_content,
        "updated_at": datetime.utcnow()
    }

    updated_comment = await db.fetch_one(query, values=values)

    if not updated_comment:
        raise HTTPException(
            status_code=404, detail="Comment not found or you don't have permission to update it")

    return CommentResponse(**updated_comment)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
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

    async with db.transaction():
        # Get the post_id before deleting the comment
        post_query = "SELECT post_id FROM comments WHERE id = :comment_id"
        comment = await db.fetch_one(post_query, values={"comment_id": comment_id})

        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")

        delete_query = "DELETE FROM comments WHERE id = :comment_id AND user_id = :user_id"
        result = await db.execute(delete_query, values={"comment_id": comment_id, "user_id": user_id})

        if result == 0:
            raise HTTPException(
                status_code=404, detail="Comment not found or you don't have permission to delete it")

        # Update comment count on the post
        update_query = """
        UPDATE posts SET comments_count = comments_count - 1
        WHERE id = :post_id
        """
        await db.execute(update_query, values={"post_id": comment['post_id']})

    return None  # 204 No Content


@router.get("/feed", response_model=List[PostResponse], operation_id="get_feed")
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

    # This is a basic feed algorithm. It gets posts from users that the current user follows,
    # as well as the user's own posts, ordered by creation time.
    query = """
    SELECT p.* FROM posts p
    JOIN user_followers uf ON p.user_id = uf.followed_id
    WHERE uf.follower_id = :user_id
    UNION
    SELECT * FROM posts WHERE user_id = :user_id
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :skip
    """
    posts = await db.fetch_all(query, values={"user_id": user_id, "limit": limit, "skip": skip})

    return [PostResponse(**post) for post in posts]


@router.get("/notifications", response_model=List[NotificationResponse])
async def get_notifications(
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

    query = """
    SELECT * FROM notifications
    WHERE user_id = :user_id
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :skip
    """
    notifications = await db.fetch_all(query, values={"user_id": user_id, "limit": limit, "skip": skip})

    return [NotificationResponse(**notification) for notification in notifications]


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_as_read(
    notification_id: str,
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

    query = """
    UPDATE notifications
    SET is_read = TRUE
    WHERE id = :notification_id AND user_id = :user_id
    RETURNING *
    """
    updated_notification = await db.fetch_one(query, values={"notification_id": notification_id, "user_id": user_id})

    if not updated_notification:
        raise HTTPException(
            status_code=404, detail="Notification not found or you don't have permission to update it")

    return NotificationResponse(**updated_notification)


class SharedPostCreate(BaseModel):
    original_post_id: str
    content: Optional[constr(max_length=1000)]


class SharedPostResponse(BaseModel):
    id: str
    user_id: str
    original_post_id: str
    content: Optional[str]
    created_at: datetime
    original_post: PostResponse


class RichMedia(BaseModel):
    type: str  # 'link', 'video', 'image'
    url: HttpUrl
    title: Optional[str]
    description: Optional[str]
    thumbnail: Optional[HttpUrl]


class PostCreateWithMedia(PostCreate):
    rich_media: Optional[RichMedia]


class PostResponseWithMedia(BaseModel):
    id: str
    user_id: str
    content: str
    image_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    likes_count: Optional[int] = 0
    comments_count: Optional[int] = 0
    rich_media: Optional[dict] = None  # Changed from RichMedia to dict

    class Config:
        from_attributes = True

# ... (keep existing functions)


def extract_rich_media(content: str) -> Optional[RichMedia]:
    urls = re.findall(r'(https?://\S+)', content)
    if not urls:
        return None

    url = urls[0]
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        og_title = soup.find('meta', property='og:title')
        og_description = soup.find('meta', property='og:description')
        og_image = soup.find('meta', property='og:image')
        og_type = soup.find('meta', property='og:type')

        media_type = 'link'
        if og_type:
            if og_type['content'] == 'video':
                media_type = 'video'
            elif og_type['content'] == 'image':
                media_type = 'image'

        return RichMedia(
            type=media_type,
            url=url,
            title=og_title['content'] if og_title else None,
            description=og_description['content'] if og_description else None,
            thumbnail=og_image['content'] if og_image else None
        )
    except Exception as e:
        print(f"Error extracting rich media: {str(e)}")
        return None


@router.post("/", response_model=dict)
async def create_post(
    background_tasks: BackgroundTasks,
    content: str = Form(...),
    media: List[UploadFile] = File(None),
    authorization: str = Header(...),
    db: Database = Depends(get_database),
):
    try:
        # Verify token
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
        logger.info(f"User authenticated: {user_id}")
    except Exception as e:
        logger.error(f"Authorization error: {str(e)}")
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    try:
        post_id = str(uuid.uuid4())[:28]
        sanitized_content = bleach.clean(content)
        logger.info(f"Creating post: {post_id}")

        media_data = []
        if media:
            logger.info(f"Received {len(media)} media files")
            for index, file in enumerate(media):
                try:
                    media_info = await upload_media(file, post_id, index)
                    media_data.append(media_info)
                except Exception as e:
                    logger.error(
                        f"Media upload error for file {index}: {str(e)}")
        else:
            logger.info("No media files received")

        # Insert post
        post_query = """
        INSERT INTO posts (id, user_id, content, created_at, updated_at)
        VALUES (:id, :user_id, :content, :created_at, :updated_at)
        RETURNING *
        """
        post_values = {
            "id": post_id,
            "user_id": user_id,
            "content": sanitized_content,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        post_result = await db.fetch_one(query=post_query, values=post_values)
        logger.info(f"Post inserted: {post_id}")

        # Insert media
        if media_data:
            media_query = """
            INSERT INTO post_media (post_id, media_url, media_type, order_index)
            VALUES (:post_id, :media_url, :media_type, :order_index)
            """
            for index, media_info in enumerate(media_data):
                media_values = {
                    "post_id": post_id,
                    "media_url": media_info['url'],
                    "media_type": media_info['type'],
                    "order_index": index
                }
                await db.execute(query=media_query, values=media_values)
            logger.info(
                f"Inserted {len(media_data)} media entries for post {post_id}")
        else:
            logger.info(f"No media entries to insert for post {post_id}")

        # Fetch media for response
        media_result = await db.fetch_all(
            "SELECT media_url, media_type FROM post_media WHERE post_id = :post_id ORDER BY order_index",
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

