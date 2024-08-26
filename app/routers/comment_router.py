from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user, get_database
from databases import Database
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

router = APIRouter()


class CommentCreate(BaseModel):
    post_id: str
    content: str
    parent_id: Optional[uuid.UUID] = None


class CommentUpdate(BaseModel):
    content: str


class CommentResponse(BaseModel):
    id: uuid.UUID
    post_id: str
    user_id: str
    parent_id: Optional[uuid.UUID]
    content: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


@router.post("/", response_model=CommentResponse)
async def create_comment(
    comment: CommentCreate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    query = """
    INSERT INTO comments (post_id, user_id, parent_id, content)
    VALUES (:post_id, :user_id, :parent_id, :content)
    RETURNING *
    """
    values = {
        "post_id": comment.post_id,
        "user_id": current_user["id"],
        "parent_id": comment.parent_id,
        "content": comment.content
    }
    result = await db.fetch_one(query=query, values=values)
    return CommentResponse(**result)


@router.get("/{comment_id}", response_model=CommentResponse)
async def get_comment(
    comment_id: uuid.UUID,
    db: Database = Depends(get_database)
):
    query = "SELECT * FROM comments WHERE id = :comment_id AND NOT is_deleted"
    result = await db.fetch_one(query=query, values={"comment_id": comment_id})
    if result is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return CommentResponse(**result)


@router.get("/{post_id}/comments", response_model=list[CommentResponse])
async def get_comments_for_post(
    post_id: str,
    db: Database = Depends(get_database)
):
    query = "SELECT * FROM comments WHERE post_id = :post_id AND NOT is_deleted ORDER BY created_at"
    results = await db.fetch_all(query=query, values={"post_id": post_id})
    return [CommentResponse(**result) for result in results]


@router.put("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: uuid.UUID,
    comment_update: CommentUpdate,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    query = """
    UPDATE comments
    SET content = :content, updated_at = CURRENT_TIMESTAMP
    WHERE id = :comment_id AND user_id = :user_id AND NOT is_deleted
    RETURNING *
    """
    values = {
        "comment_id": comment_id,
        "user_id": current_user["id"],
        "content": comment_update.content
    }
    result = await db.fetch_one(query=query, values=values)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Comment not found or you're not authorized to update it")
    return CommentResponse(**result)


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    query = """
    UPDATE comments
    SET is_deleted = TRUE
    WHERE id = :comment_id AND user_id = :user_id
    """
    values = {"comment_id": comment_id, "user_id": current_user["id"]}
    result = await db.execute(query=query, values=values)
    if result == 0:
        raise HTTPException(
            status_code=404, detail="Comment not found or you're not authorized to delete it")
