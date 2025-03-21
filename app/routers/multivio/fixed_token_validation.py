
async def validate_token(
    account_id: str,
    current_user: dict,
    db
):
    """Validate user's Twitter token without making unnecessary API calls"""
    try:
        query = """
        SELECT access_token, refresh_token, expires_at
        FROM mo_social_accounts 
        WHERE id = :account_id 
        AND user_id = :user_id 
        AND platform = 'twitter'
        """

        account = await db.fetch_one(
            query=query,
            values={
                "account_id": account_id,
                "user_id": current_user["uid"]
            }
        )

        if not account:
            return {"valid": False, "error": "Account not found"}

        # Check if token is expired or about to expire (within 5 minutes)
        from datetime import datetime, timezone, timedelta
        import logging
        logger = logging.getLogger(__name__)
        
        now = datetime.now(timezone.utc)
        is_expired = account["expires_at"] and account["expires_at"] <= now + timedelta(minutes=5)

        if is_expired and account["refresh_token"]:
            try:
                # Refresh the token
                from app.routers.multivio.twitter_router import refresh_token as refresh_token_fn
                refresh_result = await refresh_token_fn(account_id, current_user, db)
                return {
                    "valid": True,
                    "access_token": refresh_result["access_token"]
                }
            except Exception as e:
                logger.error(f"Token refresh failed: {str(e)}")
                return {"valid": False, "error": "Token refresh failed"}
                
        # If not expired, return the existing token without validating against Twitter API
        # This avoids unnecessary API calls that could lead to rate limiting
        return {
            "valid": True, 
            "access_token": account["access_token"]
        }

    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        return {
            "valid": False,
            "error": f"Token validation failed: {str(e)}"
        }
