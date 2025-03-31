"""
Router for handling general message feedback (thumbs up/down).
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from app.dependencies import get_current_user, get_database
from databases import Database
from typing import Optional
from pydantic import BaseModel
import uuid
import logging
from datetime import datetime, timezone
import json

# Initialize router
router = APIRouter()
logger = logging.getLogger(__name__)


class MessageFeedbackRequest(BaseModel):
    """Request model for providing thumbs up/down feedback on a message."""
    message_id: str
    feedback_type: str  # 'positive' or 'negative'
    comment: Optional[str] = None


@router.post("/message")
async def submit_message_feedback(
    request: MessageFeedbackRequest,
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Record thumbs up/down feedback for a message."""
    # Validate the message exists
    message_query = """
    SELECT id, content, role, metadata 
    FROM mo_llm_messages 
    WHERE id = :message_id
    """

    message = await db.fetch_one(
        query=message_query,
        values={"message_id": request.message_id}
    )

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Validate feedback type
    if request.feedback_type not in ['positive', 'negative']:
        raise HTTPException(status_code=400, detail="Invalid feedback type. Must be 'positive' or 'negative'")

    # Store the feedback
    feedback_id = str(uuid.uuid4())
    
    feedback_query = """
    INSERT INTO mo_message_feedback (
        id, message_id, user_id, feedback_type, 
        comment, created_at
    ) VALUES (
        :id, :message_id, :user_id, :feedback_type,
        :comment, CURRENT_TIMESTAMP
    ) RETURNING id
    """

    values = {
        "id": feedback_id,
        "message_id": request.message_id,
        "user_id": current_user.get("id") or current_user.get("uid"),
        "feedback_type": request.feedback_type,
        "comment": request.comment or ""
    }

    try:
        result = await db.fetch_one(query=feedback_query, values=values)

        if result:
            return {
                "id": feedback_id,
                "message": f"Feedback recorded successfully",
                "success": True
            }
        else:
            return {
                "message": "Failed to record feedback",
                "success": False
            }
    except Exception as e:
        logger.error(f"Error recording message feedback: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def feedback_stats(
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Get statistics on message feedback."""
    try:
        # Count feedbacks by type
        feedback_stats_query = """
        SELECT 
            feedback_type, 
            COUNT(*) as count
        FROM mo_message_feedback
        GROUP BY feedback_type
        """

        feedback_stats = await db.fetch_all(query=feedback_stats_query)
        
        # Get feedback by date
        feedback_by_date_query = """
        SELECT 
            DATE(created_at) as date,
            feedback_type,
            COUNT(*) as count
        FROM mo_message_feedback
        GROUP BY DATE(created_at), feedback_type
        ORDER BY date DESC
        """

        feedback_by_date_raw = await db.fetch_all(query=feedback_by_date_query)
        
        # Convert to a more usable format
        positive_count = 0
        negative_count = 0
        feedback_by_date = {}
        
        for stat in feedback_stats:
            if stat['feedback_type'] == 'positive':
                positive_count = stat['count']
            elif stat['feedback_type'] == 'negative':
                negative_count = stat['count']
        
        for row in feedback_by_date_raw:
            date_str = row['date'].strftime('%Y-%m-%d')
            
            if date_str not in feedback_by_date:
                feedback_by_date[date_str] = {'positive': 0, 'negative': 0}
            
            feedback_by_date[date_str][row['feedback_type']] = row['count']
        
        return {
            "positive_count": positive_count,
            "negative_count": negative_count,
            "feedback_by_date": feedback_by_date
        }
    except Exception as e:
        logger.error(f"Error getting feedback stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
