# # chat_router.py
# from fastapi import APIRouter, HTTPException, Depends
# from sqlalchemy.orm import Session
# from pydantic import BaseModel
# from app.dependencies import get_current_user
# from app.database import database
# from app.models.models import Chat, User
# from typing import List
# router = APIRouter()


# class ChatCreate(BaseModel):
#     name: str


# @router.post("/chats/", response_model=ChatCreate)
# async def create_chat(chat: ChatCreate, current_user: User = Depends(get_current_user)):
#     query = "INSERT INTO chats (name, user_id) VALUES (:name, :user_id) RETURNING id"
#     values = {"name": chat.name, "user_id": current_user["id"]}
#     chat_id = await database.execute(query=query, values=values)
#     return {"id": chat_id, "name": chat.name}


# @router.get("/chats/", response_model=List[ChatCreate])
# async def read_chats(skip: int = 0, limit: int = 10, current_user: User = Depends(get_current_user)):
#     query = "SELECT * FROM chats WHERE user_id = :user_id LIMIT :limit OFFSET :skip"
#     values = {"user_id": current_user["id"], "skip": skip, "limit": limit}
#     chats = await database.fetch_all(query=query, values=values)
#     return chats


# @router.put("/chats/{chat_id}/", response_model=ChatCreate)
# async def update_chat(chat_id: int, chat: ChatCreate, current_user: User = Depends(get_current_user)):
#     query = "UPDATE chats SET name = :name WHERE id = :chat_id AND user_id = :user_id"
#     values = {"name": chat.name, "chat_id": chat_id,
#               "user_id": current_user["id"]}
#     result = await database.execute(query=query, values=values)
#     if not result:
#         raise HTTPException(status_code=404, detail="Chat not found")
#     return {"id": chat_id, "name": chat.name}


# @router.delete("/chats/{chat_id}/")
# async def delete_chat(chat_id: int, current_user: User = Depends(get_current_user)):
#     query = "DELETE FROM chats WHERE id = :chat_id AND user_id = :user_id"
#     values = {"chat_id": chat_id, "user_id": current_user["id"]}
#     result = await database.execute(query=query, values=values)
#     if not result:
#         raise HTTPException(status_code=404, detail="Chat not found")
#     return {"message": "Chat deleted successfully"}
