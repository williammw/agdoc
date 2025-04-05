# session_router.py
from fastapi import APIRouter, Request, Depends, Response
from app.dependencies import get_current_user
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/clear")
async def clear_session(request: Request, response: Response, current_user=Depends(get_current_user)):
    """
    Clear the current user's session data and reset conversation state
    """
    try:
        user_id = current_user.get("uid", "unknown")
        logger.info(f"Clearing session for user {user_id}")
        
        # Clear the session data
        request.session.clear()
        
        # Set a new session cookie
        response.set_cookie(
            key="session",
            value="",  # Empty value
            max_age=0,  # Expire immediately
            httponly=True,
            samesite="lax",
            secure=True
        )
        
        logger.info(f"Session successfully cleared for user {user_id}")
        return {"status": "success", "message": "Session cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing session: {str(e)}")
        return {"status": "error", "message": "Failed to clear session"}

@router.get("/status")
async def session_status(request: Request, current_user=Depends(get_current_user)):
    """
    Get the current session status and information
    """
    try:
        user_id = current_user.get("uid", "unknown")
        
        # Get session info for debugging
        session_keys = list(request.session.keys())
        session_info = {
            "num_keys": len(session_keys),
            "keys": session_keys[:10] if len(session_keys) > 10 else session_keys  # Limit keys for privacy
        }
        
        logger.info(f"Session status for user {user_id}: {session_info}")
        return {
            "status": "success", 
            "user_id": user_id,
            "session_info": session_info
        }
    except Exception as e:
        logger.error(f"Error getting session status: {str(e)}")
        return {"status": "error", "message": "Failed to get session status"}
