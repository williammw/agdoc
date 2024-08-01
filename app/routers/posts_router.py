from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Header
from app.dependencies import get_database, verify_token
from databases import Database
from pydantic import BaseModel, constr
from datetime import datetime
import uuid
import boto3
import os
from fastapi.security import OAuth2PasswordBearer
from typing import List, Optional
import bleach
import imghdr


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
    content: constr(max_length=5000)  # Limit content length


class PostResponse(BaseModel):
    id: str
    user_id: str
    content: str
    image_url: Optional[str]
    created_at: datetime
    updated_at: datetime



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


@router.post("/", response_model=PostResponse)
async def create_post(
    post: PostCreate,
    image: Optional[UploadFile] = File(None),
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

    query = """
    INSERT INTO posts (id, user_id, content, image_url, created_at, updated_at)
    VALUES (:id, :user_id, :content, :image_url, :created_at, :updated_at)
    RETURNING *
    """
    values = {
        "id": post_id,
        "user_id": user_id,
        "content": sanitized_content,
        "image_url": image_url,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    try:
        result = await db.fetch_one(query=query, values=values)
        return PostResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create post: {str(e)}")


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


@router.post("/", response_model=PostResponse)
async def create_post(
    post: PostCreate,
    image: Optional[UploadFile] = File(None),
    authorization: str = Header(...),
    db: Database = Depends(get_database)
):
    # ... (keep existing create_post logic)
    # Update the query to include likes_count and comments_count
    query = """
    INSERT INTO posts (id, user_id, content, image_url, created_at, updated_at, likes_count, comments_count)
    VALUES (:id, :user_id, :content, :image_url, :created_at, :updated_at, 0, 0)
    RETURNING *
    """
    # ... (rest of the function remains the same)


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


