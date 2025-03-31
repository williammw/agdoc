"""
Router for handling intent detection feedback and improvement.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from app.dependencies import get_current_user, get_database
from databases import Database
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import uuid
import logging
from datetime import datetime, timezone
import json
from app.routers.multivio.commands.intent_detector import store_intent_feedback, MultilingualIntentDetector

# Initialize router
router = APIRouter()
logger = logging.getLogger(__name__)


class IntentFeedbackRequest(BaseModel):
    """Request model for providing feedback on intent detection."""
    message_id: str
    correct_intent: str
    feedback: Optional[str] = None


class AddIntentExampleRequest(BaseModel):
    """Request model for adding new examples to an intent."""
    intent: str
    examples: List[str]


@router.post("/feedback")
async def intent_feedback(
    request: IntentFeedbackRequest,
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Record feedback about intent detection for a message."""
    # Get the original message and detected intents
    message_query = """
    SELECT content, metadata 
    FROM mo_llm_messages 
    WHERE id = :message_id
    """

    message = await db.fetch_one(
        query=message_query,
        values={"message_id": request.message_id}
    )

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # Extract detected intents from metadata
    detected_intents = {}
    if message["metadata"]:
        try:
            metadata = json.loads(message["metadata"])
            if "detected_intents" in metadata:
                detected_intents = {"intents": metadata["detected_intents"]}
        except:
            pass

    # Store the feedback
    feedback_id = str(uuid.uuid4())
    feedback_query = """
    INSERT INTO mo_intent_feedback (
        id, message_id, user_id, correct_intent, detected_intents, 
        feedback, created_at
    ) VALUES (
        :id, :message_id, :user_id, :correct_intent, :detected_intents,
        :feedback, CURRENT_TIMESTAMP
    ) RETURNING id
    """

    values = {
        "id": feedback_id,
        "message_id": request.message_id,
        "user_id": current_user.get("id") or current_user.get("uid"),
        "correct_intent": request.correct_intent,
        "detected_intents": json.dumps(detected_intents),
        "feedback": request.feedback or ""
    }

    try:
        result = await db.fetch_one(query=feedback_query, values=values)

        if result:
            # If the feedback suggests a new example, try to add it to the model
            message_content = message["content"]
            if message_content and request.correct_intent:
                try:
                    # Try to add the message as an example for the correct intent
                    detector = MultilingualIntentDetector.get_instance()
                    if detector:
                        detector.add_examples(
                            request.correct_intent, [message_content])
                        logger.info(
                            f"Added new example for intent {request.correct_intent}")
                except Exception as e:
                    logger.error(
                        f"Error adding example to intent model: {str(e)}")

            return {
                "id": feedback_id,
                "message": "Feedback recorded successfully",
                "improved_model": True
            }
        else:
            return {
                "message": "Failed to record feedback",
                "improved_model": False
            }
    except Exception as e:
        logger.error(f"Error recording intent feedback: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add-examples")
async def add_intent_examples(
    request: AddIntentExampleRequest,
    current_user: dict = Depends(get_current_user)
):
    """Add new examples for an intent to improve detection."""
    try:
        detector = MultilingualIntentDetector.get_instance()
        if not detector:
            return {
                "message": "Multilingual detector not available",
                "success": False
            }

        # Add the examples
        detector.add_examples(request.intent, request.examples)

        return {
            "message": f"Added {len(request.examples)} examples to {request.intent}",
            "success": True,
            "examples_added": len(request.examples)
        }
    except Exception as e:
        logger.error(f"Error adding intent examples: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def intent_stats(
    db: Database = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """Get statistics on intent detection."""
    try:
        # Count feedbacks by correct intent
        feedback_stats_query = """
        SELECT 
            correct_intent, 
            COUNT(*) as count
        FROM mo_intent_feedback
        GROUP BY correct_intent
        ORDER BY count DESC
        """

        feedback_stats = await db.fetch_all(query=feedback_stats_query)

        # Get recent messages with intents
        recent_query = """
        SELECT 
            id, 
            content, 
            metadata,
            created_at
        FROM mo_llm_messages
        WHERE role = 'user' AND metadata IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 50
        """

        recent_messages = await db.fetch_all(query=recent_query)

        # Process messages to extract intents
        intents_by_day = {}
        intent_counts = {}

        for msg in recent_messages:
            try:
                metadata = json.loads(
                    msg["metadata"]) if msg["metadata"] else {}
                intents = metadata.get("detected_intents", [])

                # Get day only from timestamp
                day = msg["created_at"].strftime("%Y-%m-%d")

                # Add to daily stats
                if day not in intents_by_day:
                    intents_by_day[day] = {}

                # Count intents
                for intent in intents:
                    # Daily stats
                    if intent not in intents_by_day[day]:
                        intents_by_day[day][intent] = 0
                    intents_by_day[day][intent] += 1

                    # Overall stats
                    if intent not in intent_counts:
                        intent_counts[intent] = 0
                    intent_counts[intent] += 1
            except:
                pass

        return {
            "intent_counts": intent_counts,
            "intents_by_day": intents_by_day,
            "feedback_stats": [dict(row) for row in feedback_stats]
        }
    except Exception as e:
        logger.error(f"Error getting intent stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
