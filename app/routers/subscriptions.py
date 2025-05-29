import os
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Body
import stripe

from app.dependencies.auth import get_current_user, db_admin
from app.utils.database import get_user_by_email, update_user

# Initialize Stripe with your secret key
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

router = APIRouter(
    prefix="/api/v1/subscriptions",
    tags=["subscriptions"]
)

@router.post("/activate")
async def activate_subscription(
    data: Dict[str, Any] = Body(...),
    supabase = Depends(db_admin)
):
    """
    Handle subscription activation from Stripe webhook
    
    This endpoint is called by the frontend webhook handler to update
    user subscription status in the database.
    """
    try:
        email = data.get("email")
        stripe_customer_id = data.get("stripe_customer_id")
        stripe_session_id = data.get("stripe_session_id")
        subscription_id = data.get("subscription_id")
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required"
            )
        
        # Get user by email
        user = await get_user_by_email(supabase, email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Get subscription details from Stripe if subscription_id is provided
        plan_name = "basic"  # Default
        if subscription_id:
            try:
                subscription = stripe.Subscription.retrieve(subscription_id)
                # Get the price from the subscription
                if subscription.items.data:
                    price_id = subscription.items.data[0].price.id
                    # Map price IDs to plan names using environment variables
                    price_to_plan = {
                        os.getenv("STRIPE_BASIC_PRICE_ID"): "basic",         # $9/month
                        os.getenv("STRIPE_PRO_PRICE_ID"): "pro",             # $29/month
                        os.getenv("STRIPE_ENTERPRISE_PRICE_ID"): "enterprise" # $99/month
                    }
                    # Remove None keys if environment variables are not set
                    price_to_plan = {k: v for k, v in price_to_plan.items() if k is not None}
                    plan_name = price_to_plan.get(price_id, "basic")
            except Exception as e:
                print(f"Error retrieving subscription from Stripe: {e}")
        
        # Update user subscription in database
        updates = {
            "stripe_customer_id": stripe_customer_id,
            "subscription_status": "active",
            "subscription_id": subscription_id,
            "plan_name": plan_name,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        updated_user = await update_user(supabase, user["id"], updates)
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user subscription"
            )
        
        # Also update user_info table with new plan limits
        plan_limits = {
            "free": {"monthly_post_quota": 10},
            "basic": {"monthly_post_quota": 100},
            "pro": {"monthly_post_quota": -1},  # -1 = unlimited
            "enterprise": {"monthly_post_quota": -1}
        }
        
        quota = plan_limits.get(plan_name, {"monthly_post_quota": 10})["monthly_post_quota"]
        
        # Update user_info table
        try:
            user_info_response = supabase.table("user_info").update({
                "plan_type": plan_name,
                "monthly_post_quota": quota,
                "remaining_posts": quota if quota > 0 else 99999,  # Large number for unlimited
                "updated_at": datetime.utcnow().isoformat()
            }).eq("user_id", user["id"]).execute()
            
            print(f"Updated user_info for user {user['id']}: {user_info_response.data}")
        except Exception as e:
            print(f"Error updating user_info: {e}")
        
        # Record subscription history
        try:
            history_data = {
                "user_email": email,
                "stripe_subscription_id": subscription_id,
                "plan_name": plan_name,
                "status": "active",
                "created_at": datetime.utcnow().isoformat()
            }
            
            if subscription_id:
                # Get more details from Stripe
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    history_data.update({
                        "amount_paid": subscription.items.data[0].price.unit_amount if subscription.items.data else 0,
                        "currency": subscription.items.data[0].price.currency if subscription.items.data else "usd",
                        "period_start": datetime.fromtimestamp(subscription.current_period_start).isoformat(),
                        "period_end": datetime.fromtimestamp(subscription.current_period_end).isoformat()
                    })
                except Exception as e:
                    print(f"Error getting subscription details for history: {e}")
            
            supabase.table("subscription_history").insert(history_data).execute()
        except Exception as e:
            print(f"Error recording subscription history: {e}")
        
        return {
            "success": True, 
            "message": "Subscription activated successfully",
            "user_id": user["id"],
            "plan_name": plan_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in activate_subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate subscription: {str(e)}"
        )

@router.get("/status")
async def get_subscription_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """
    Get current user's subscription status
    
    Returns subscription information for the authenticated user.
    """
    try:
        # Get user info which includes plan details
        user_info_response = supabase.table("user_info").select("*").eq("user_id", current_user["id"]).execute()
        
        result = {
            "user_id": current_user["id"],
            "email": current_user["email"],
            "subscription_status": current_user.get("subscription_status", "free"),
            "plan_name": current_user.get("plan_name", "free"),
            "stripe_customer_id": current_user.get("stripe_customer_id"),
            "subscription_id": current_user.get("subscription_id")
        }
        
        if user_info_response.data:
            user_info = user_info_response.data[0]
            result.update({
                "monthly_post_quota": user_info.get("monthly_post_quota", 10),
                "remaining_posts": user_info.get("remaining_posts", 10),
                "plan_type": user_info.get("plan_type", "free")
            })
        
        # If user has a Stripe subscription, get latest details
        if current_user.get("stripe_customer_id") and current_user.get("subscription_id"):
            try:
                subscription = stripe.Subscription.retrieve(current_user["subscription_id"])
                result.update({
                    "stripe_status": subscription.status,
                    "current_period_end": datetime.fromtimestamp(subscription.current_period_end).isoformat(),
                    "cancel_at_period_end": subscription.cancel_at_period_end
                })
            except Exception as e:
                print(f"Error retrieving Stripe subscription: {e}")
        
        return result
        
    except Exception as e:
        print(f"Error getting subscription status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get subscription status: {str(e)}"
        )

@router.post("/cancel")
async def cancel_subscription(
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """
    Cancel user's subscription (mark for cancellation at period end)
    """
    try:
        subscription_id = current_user.get("subscription_id")
        
        if not subscription_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active subscription found"
            )
        
        # Cancel subscription in Stripe (at period end)
        try:
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
        except Exception as e:
            print(f"Error canceling Stripe subscription: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel subscription with Stripe"
            )
        
        # Update user record
        updates = {
            "subscription_status": "canceling",
            "updated_at": datetime.utcnow().isoformat()
        }
        
        updated_user = await update_user(supabase, current_user["id"], updates)
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user subscription status"
            )
        
        # Record in history
        try:
            supabase.table("subscription_history").insert({
                "user_email": current_user["email"],
                "stripe_subscription_id": subscription_id,
                "plan_name": current_user.get("plan_name", "unknown"),
                "status": "canceling",
                "created_at": datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            print(f"Error recording cancellation in history: {e}")
        
        return {
            "success": True,
            "message": "Subscription will be canceled at the end of the current billing period",
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "current_period_end": datetime.fromtimestamp(subscription.current_period_end).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error canceling subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel subscription: {str(e)}"
        )

@router.get("/history")
async def get_subscription_history(
    current_user: Dict[str, Any] = Depends(get_current_user),
    supabase = Depends(db_admin)
):
    """
    Get subscription history for the current user
    """
    try:
        response = supabase.table("subscription_history").select("*").eq(
            "user_email", current_user["email"]
        ).order("created_at", desc=True).execute()
        
        return {
            "history": response.data if response.data else []
        }
        
    except Exception as e:
        print(f"Error getting subscription history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get subscription history: {str(e)}"
        )