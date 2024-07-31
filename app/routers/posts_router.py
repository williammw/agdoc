from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from app.dependencies import get_database, verify_token
from databases import Database
from pydantic import BaseModel, constr
from datetime import datetime
import uuid
import boto3
import os
from fastapi.security import OAuth2PasswordBearer
from typing import Optional
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


@router.post("/")
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
            raise HTTPException(status_code=500, detail=str(e))

    # Sanitize content
    sanitized_content = bleach.clean(post.content)

    query = """
    INSERT INTO posts (id, user_id, content, image_url, created_at, updated_at)
    VALUES (:id, :user_id, :content, :image_url, :created_at, :updated_at)
    """
    values = {
        "id": post_id,
        "user_id": user_id,
        "content": sanitized_content,
        "image_url": image_url,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    await db.execute(query=query, values=values)

    return {"message": "Post created successfully", "post_id": post_id, "image_url": image_url}
