from fastapi import APIRouter, Depends, HTTPException
from databases import Database
from typing import List, Dict, Optional
from uuid import uuid4
import logging
from app.dependencies import get_current_user, get_database
from app.models.content_model import ContentCreate, ContentUpdate, ContentResponse, ContentVersion

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/chat", response_model=ContentResponse)
async def create_content(
    content: ContentCreate,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        query = """
        INSERT INTO mo_chat (
            uuid,
            firebase_uid,
            name,
            description,
            route,
            status
        ) VALUES (
            :uuid,
            :firebase_uid,
            :name,
            :description,
            :route,
            :status
        ) RETURNING *
        """
        
        values = {
            "uuid": str(uuid4()),
            "firebase_uid": current_user["uid"],
            "name": content.name,
            "description": content.description,
            "route": content.route,
            "status": content.status
        }
        
        result = await db.fetch_one(query=query, values=values)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to create content")
            
        return dict(result)

    except Exception as e:
        logger.error(f"Error in create_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat/{chat_id}", response_model=ContentResponse)
async def get_content(
    chat_id: int,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        query = """
        SELECT * FROM mo_chat 
        WHERE id = :chat_id AND firebase_uid = :firebase_uid
        """
        
        result = await db.fetch_one(
            query=query,
            values={"chat_id": chat_id, "firebase_uid": current_user["uid"]}
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Content not found")
            
        return dict(result)

    except Exception as e:
        logger.error(f"Error in get_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat", response_model=List[ContentResponse])
async def list_content(
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    status: Optional[str] = None,
    limit: int = 40,
    offset: int = 0
):
    try:
        # Base query for counting total records
        count_query = """
        SELECT COUNT(*) as total FROM mo_chat 
        WHERE firebase_uid = :firebase_uid 
        """
        
        count_values = {"firebase_uid": current_user["uid"]}
        
        if status:
            count_query += " AND status = :status"
            count_values["status"] = status

        # Get total count
        total_result = await db.fetch_one(query=count_query, values=count_values)
        total_count = total_result["total"] if total_result else 0
        
        # Main query with pagination
        if status:
            query = """
            SELECT * FROM mo_chat 
            WHERE firebase_uid = :firebase_uid AND status = :status
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
            values = {
                "firebase_uid": current_user["uid"], 
                "status": status, 
                "limit": limit, 
                "offset": offset
            }
        else:
            query = """
            SELECT * FROM mo_chat 
            WHERE firebase_uid = :firebase_uid AND status = 'draft'
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
            values = {
                "firebase_uid": current_user["uid"],
                "limit": limit,
                "offset": offset
            }
        
        results = await db.fetch_all(query=query, values=values)
        
        # Add pagination metadata to response headers (not part of the JSON response)
        response_data = [dict(row) for row in results]
        
        # Return paginated results with metadata
        return response_data

    except Exception as e:
        logger.error(f"Error in list_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/chat/{chat_id}", response_model=ContentResponse)
async def update_content(
    chat_id: int,
    content: ContentUpdate,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # First check if content exists and belongs to user
        check_query = """
        SELECT id FROM mo_chat 
        WHERE id = :chat_id AND firebase_uid = :firebase_uid
        """
        exists = await db.fetch_one(
            query=check_query,
            values={"chat_id": chat_id, "firebase_uid": current_user["uid"]}
        )
        
        if not exists:
            raise HTTPException(status_code=404, detail="Content not found")

        # Build update query dynamically based on provided fields
        update_fields = []
        values = {"chat_id": chat_id, "firebase_uid": current_user["uid"]}
        
        for field, value in content.dict(exclude_unset=True).items():
            if value is not None:
                update_fields.append(f"{field} = :{field}")
                values[field] = value

        if not update_fields:
            return await get_content(chat_id, current_user, db)

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        update_query = f"""
        UPDATE mo_chat 
        SET {", ".join(update_fields)}
        WHERE id = :chat_id AND firebase_uid = :firebase_uid
        RETURNING *
        """
        
        result = await db.fetch_one(query=update_query, values=values)
        return dict(result)

    except Exception as e:
        logger.error(f"Error in update_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
@router.patch("/chat/{chat_id}", response_model=ContentResponse)
async def patch_content(
    chat_id: int,
    content: ContentUpdate,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # First check if content exists and belongs to user
        check_query = """
        SELECT id FROM mo_chat 
        WHERE id = :chat_id AND firebase_uid = :firebase_uid
        """
        exists = await db.fetch_one(
            query=check_query,
            values={"chat_id": chat_id, "firebase_uid": current_user["uid"]}
        )
        
        if not exists:
            raise HTTPException(status_code=404, detail="Content not found")

        # Build update query dynamically based on provided fields
        update_fields = []
        values = {"chat_id": chat_id, "firebase_uid": current_user["uid"]}
        
        for field, value in content.dict(exclude_unset=True).items():
            if value is not None:
                update_fields.append(f"{field} = :{field}")
                values[field] = value

        if not update_fields:
            return await get_content(chat_id, current_user, db)

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        update_query = f"""
        UPDATE mo_chat 
        SET {', '.join(update_fields)}
        WHERE id = :chat_id AND firebase_uid = :firebase_uid
        RETURNING *
        """
        
        result = await db.fetch_one(query=update_query, values=values)
        return dict(result)

    except Exception as e:
        logger.error(f"Error in patch_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/chat/{chat_id}")
async def delete_content(
    chat_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # First check if content exists and belongs to user
        check_query = """
        SELECT uuid FROM mo_chat 
        WHERE CAST(id AS TEXT) = :chat_id AND firebase_uid = :firebase_uid
        """
        content_result = await db.fetch_one(
            query=check_query,
            values={"chat_id": chat_id, "firebase_uid": current_user["uid"]}
        )
        
        if not content_result:
            raise HTTPException(status_code=404, detail="Content not found")
        
        content_uuid = content_result["uuid"]
        
        # Begin transaction for consistent deletion
        transaction = await db.transaction()
        try:
            # Step 1: Delete LLM messages associated with conversations linked to this content
            delete_messages_query = """
            DELETE FROM mo_llm_messages 
            WHERE conversation_id IN (
                SELECT v.id FROM mo_llm_conversations v
                WHERE v.chat_id = :content_uuid
            )
            """
            await db.execute(
                query=delete_messages_query,
                values={"content_uuid": content_uuid}
            )
            
            # Step 2: Delete LLM conversations associated with this content
            delete_conversations_query = """
            DELETE FROM mo_llm_conversations
            WHERE chat_id = :content_uuid
            """
            await db.execute(
                query=delete_conversations_query,
                values={"content_uuid": content_uuid}
            )
            
            # Step 3: Delete associated versions (due to foreign key constraint)
            delete_versions_query = """
            DELETE FROM mo_content_version 
            WHERE CAST(chat_id AS TEXT) = :chat_id AND firebase_uid = :firebase_uid
            """
            await db.execute(
                query=delete_versions_query,
                values={"chat_id": chat_id, "firebase_uid": current_user["uid"]}
            )
            
            # Step 4: Finally delete the content
            delete_query = """
            DELETE FROM mo_chat 
            WHERE CAST(id AS TEXT) = :chat_id AND firebase_uid = :firebase_uid
            """
            await db.execute(
                query=delete_query,
                values={"chat_id": chat_id, "firebase_uid": current_user["uid"]}
            )
            
            # Commit the transaction
            await transaction.commit()
            
        except Exception as e:
            # Rollback in case of error
            await transaction.rollback()
            raise e

        return {"message": "Content deleted successfully"}

    except Exception as e:
        logger.error(f"Error in delete_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/{chat_id}/version")
async def create_content_version(
    chat_id: int,
    version_data: ContentVersion,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Check if content exists and belongs to user
        check_query = """
        SELECT id FROM mo_chat 
        WHERE id = :chat_id AND firebase_uid = :firebase_uid
        """
        exists = await db.fetch_one(
            query=check_query,
            values={"chat_id": chat_id, "firebase_uid": current_user["uid"]}
        )
        
        if not exists:
            raise HTTPException(status_code=404, detail="Content not found")

        # Create new version
        insert_query = """
        INSERT INTO mo_content_version (
            chat_id,
            firebase_uid,
            version,
            content_data
        ) VALUES (
            :chat_id,
            :firebase_uid,
            :version,
            :content_data
        ) RETURNING *
        """
        
        values = {
            "chat_id": chat_id,
            "firebase_uid": current_user["uid"],
            "version": version_data.version,
            "content_data": version_data.content_data
        }
        
        result = await db.fetch_one(query=insert_query, values=values)
        return dict(result)

    except Exception as e:
        logger.error(f"Error in create_content_version: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)) 