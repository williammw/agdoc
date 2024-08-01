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



from app.routers.auth2_router import UserResponse


router = APIRouter()

# Initialize S3 client
s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY')
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class PostCreate(BaseModel):
    content: constr(max_length=5000)  # type: ignore # Limit content length


class PostResponse(BaseModel):
    id: str
    user_id: str
    content: str
    image_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True



ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif'}
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

    # Check file content
    file_content = file.file.read(11)  # Read first 11 bytes
    file.file.seek(0)
    file_type = imghdr.what(None, file_content)
    if file_type not in ['jpeg', 'png', 'gif']:
        raise HTTPException(status_code=400, detail="Invalid image file")

    return True



@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: str,
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

    query = "SELECT * FROM posts WHERE id = :post_id"
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


@router.put("/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: str,
    post_update: PostUpdate,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        # Verify token
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    # Sanitize content
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


@router.delete("/{post_id}", status_code=204)
async def delete_post(
    post_id: str,
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    try:
        # Verify token
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

    # If the post had an image, you might want to delete it from R2 here
    # This would require keeping track of which posts have images, or attempting to delete for all posts

    return None  # 204 No Content

    from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header, Query

router = APIRouter()

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


class PostResponse(BaseModel):
    id: str
    user_id: str
    content: str
    image_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    likes_count: int
    comments_count: int

# ... (keep existing functions like validate_image)

@router.post("/{post_id}/like", response_model=PostResponse)
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


@router.get("/user/{user_id}", response_model=List[PostResponse])
async def get_user_posts(
    user_id: str,
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
    SELECT * FROM posts 
    WHERE user_id = :user_id 
    ORDER BY created_at DESC 
    LIMIT :limit OFFSET :skip
    """
    posts = await db.fetch_all(query, values={"user_id": user_id, "limit": limit, "skip": skip})

    return [PostResponse(**post) for post in posts]


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
        "created_at": datetime.utcnow()
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


@router.get("/feed", response_model=List[PostResponse])
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
    likes_count: int
    comments_count: int
    rich_media: Optional[RichMedia]

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


@router.post("/", response_model=PostResponseWithMedia)
async def create_post(
    background_tasks: BackgroundTasks,
    post: PostCreate = Form(...),
    image: Optional[UploadFile] = File(None),
    authorization: str = Header(...),
    db: Database = Depends(get_database),
):
    print("Creating post")
    try:
        # Verify token
        token = authorization.split("Bearer ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    post_id = str(uuid.uuid4())[:28]
    image_url = None

    if image:
        validate_image(image)
        # Upload image to Cloudflare R2
        bucket_name = os.getenv('R2_BUCKET_NAME')
        object_name = f"posts/{post_id}/{image.filename}"
        try:
            s3.upload_fileobj(image.file, bucket_name, object_name)
            image_url = f"https://{os.getenv('R2_DEV_URL')}/{object_name}"
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to upload image: {str(e)}")

    # Sanitize content
    sanitized_content = bleach.clean(post.content)

    # Extract rich media
    rich_media = extract_rich_media(sanitized_content)

    query = """
    INSERT INTO posts (id, user_id, content, image_url, created_at, updated_at, likes_count, comments_count, rich_media)
    VALUES (:id, :user_id, :content, :image_url, :created_at, :updated_at, 0, 0, :rich_media)
    RETURNING *
    """
    values = {
        "id": post_id,
        "user_id": user_id,
        "content": sanitized_content,
        "image_url": image_url,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "rich_media": rich_media.model_dump_json() if rich_media else None
    }

    try:
        result = await db.fetch_one(query=query, values=values)

        # Extract and save hashtags
        background_tasks.add_task(
            extract_and_save_hashtags, db, post_id, sanitized_content)

        # Initialize post analytics
        background_tasks.add_task(update_post_analytics, db, post_id)

        return PostResponseWithMedia(**result)
    except Exception as e:
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
            "created_at": datetime.utcnow()
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
    query = """
    INSERT INTO post_analytics (post_id, view_count, share_count, engagement_rate)
    VALUES (:post_id, :view_increment, :share_increment, 0)
    ON CONFLICT (post_id) DO UPDATE
    SET view_count = post_analytics.view_count + :view_increment,
        share_count = post_analytics.share_count + :share_increment,
        engagement_rate = (post_analytics.view_count + post_analytics.share_count + EXCLUDED.view_count + EXCLUDED.share_increment)::float / 
                          (SELECT followers_count FROM users WHERE id = (SELECT user_id FROM posts WHERE id = :post_id))
    """
    await db.execute(query, {"post_id": post_id, "view_increment": view_increment, "share_increment": share_increment})




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




