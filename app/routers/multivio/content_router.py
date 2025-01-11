from fastapi import APIRouter, Depends, HTTPException
from databases import Database
from typing import List, Dict, Optional
from uuid import uuid4
import logging
from app.dependencies import get_current_user, get_database
from app.models.content_model import ContentCreate, ContentUpdate, ContentResponse, ContentVersion

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/content", response_model=ContentResponse)
async def create_content(
    content: ContentCreate,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        query = """
        INSERT INTO mo_content (
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

@router.get("/content/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: int,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        query = """
        SELECT * FROM mo_content 
        WHERE id = :content_id AND firebase_uid = :firebase_uid
        """
        
        result = await db.fetch_one(
            query=query,
            values={"content_id": content_id, "firebase_uid": current_user["uid"]}
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Content not found")
            
        return dict(result)

    except Exception as e:
        logger.error(f"Error in get_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/content", response_model=List[ContentResponse])
async def list_content(
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database),
    status: Optional[str] = None
):
    try:
        if status:
            query = """
            SELECT * FROM mo_content 
            WHERE firebase_uid = :firebase_uid AND status = :status
            ORDER BY created_at DESC
            """
            values = {"firebase_uid": current_user["uid"], "status": status}
        else:
            query = """
            SELECT * FROM mo_content 
            WHERE firebase_uid = :firebase_uid
            ORDER BY created_at DESC
            """
            values = {"firebase_uid": current_user["uid"]}
        
        results = await db.fetch_all(query=query, values=values)
        return [dict(row) for row in results]

    except Exception as e:
        logger.error(f"Error in list_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/content/{content_id}", response_model=ContentResponse)
async def update_content(
    content_id: int,
    content: ContentUpdate,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # First check if content exists and belongs to user
        check_query = """
        SELECT id FROM mo_content 
        WHERE id = :content_id AND firebase_uid = :firebase_uid
        """
        exists = await db.fetch_one(
            query=check_query,
            values={"content_id": content_id, "firebase_uid": current_user["uid"]}
        )
        
        if not exists:
            raise HTTPException(status_code=404, detail="Content not found")

        # Build update query dynamically based on provided fields
        update_fields = []
        values = {"content_id": content_id, "firebase_uid": current_user["uid"]}
        
        for field, value in content.dict(exclude_unset=True).items():
            if value is not None:
                update_fields.append(f"{field} = :{field}")
                values[field] = value

        if not update_fields:
            return await get_content(content_id, current_user, db)

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        update_query = f"""
        UPDATE mo_content 
        SET {", ".join(update_fields)}
        WHERE id = :content_id AND firebase_uid = :firebase_uid
        RETURNING *
        """
        
        result = await db.fetch_one(query=update_query, values=values)
        return dict(result)

    except Exception as e:
        logger.error(f"Error in update_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
@router.delete("/content/{content_id}")
async def delete_content(
    content_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # First check if content exists and belongs to user
        check_query = """
        SELECT id FROM mo_content 
        WHERE CAST(id AS TEXT) = :content_id AND firebase_uid = :firebase_uid
        """
        exists = await db.fetch_one(
            query=check_query,
            values={"content_id": content_id, "firebase_uid": current_user["uid"]}
        )
        
        if not exists:
            raise HTTPException(status_code=404, detail="Content not found")

        # Delete associated versions first (due to foreign key constraint)
        delete_versions_query = """
        DELETE FROM mo_content_version 
        WHERE CAST(content_id AS TEXT) = :content_id AND firebase_uid = :firebase_uid
        """
        await db.execute(
            query=delete_versions_query,
            values={"content_id": content_id, "firebase_uid": current_user["uid"]}
        )

        # Delete associated social posts
        delete_posts_query = """
        DELETE FROM mo_social_post 
        WHERE CAST(content_id AS TEXT) = :content_id AND firebase_uid = :firebase_uid
        """
        await db.execute(
            query=delete_posts_query,
            values={"content_id": content_id, "firebase_uid": current_user["uid"]}
        )

        # Finally delete the content
        delete_query = """
        DELETE FROM mo_content 
        WHERE CAST(id AS TEXT) = :content_id AND firebase_uid = :firebase_uid
        """
        await db.execute(
            query=delete_query,
            values={"content_id": content_id, "firebase_uid": current_user["uid"]}
        )

        return {"message": "Content deleted successfully"}

    except Exception as e:
        logger.error(f"Error in delete_content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/content/{content_id}/version")
async def create_content_version(
    content_id: int,
    version_data: ContentVersion,
    current_user: Dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    try:
        # Check if content exists and belongs to user
        check_query = """
        SELECT id FROM mo_content 
        WHERE id = :content_id AND firebase_uid = :firebase_uid
        """
        exists = await db.fetch_one(
            query=check_query,
            values={"content_id": content_id, "firebase_uid": current_user["uid"]}
        )
        
        if not exists:
            raise HTTPException(status_code=404, detail="Content not found")

        # Create new version
        insert_query = """
        INSERT INTO mo_content_version (
            content_id,
            firebase_uid,
            version,
            content_data
        ) VALUES (
            :content_id,
            :firebase_uid,
            :version,
            :content_data
        ) RETURNING *
        """
        
        values = {
            "content_id": content_id,
            "firebase_uid": current_user["uid"],
            "version": version_data.version,
            "content_data": version_data.content_data
        }
        
        result = await db.fetch_one(query=insert_query, values=values)
        return dict(result)

    except Exception as e:
        logger.error(f"Error in create_content_version: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)) 