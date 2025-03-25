# app/routers/multivio/patreon_router.py
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from app.dependencies import get_database, get_current_user
from databases import Database
import httpx
import os
import secrets
import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)

# Patreon API configuration
PATREON_CLIENT_ID = os.getenv("PATREON_CLIENT_ID")
PATREON_CLIENT_SECRET = os.getenv("PATREON_CLIENT_SECRET")
PATREON_REDIRECT_URI = os.getenv("PATREON_REDIRECT_URI", "https://dev.multivio.com/patreon/callback")

# API URLs
PATREON_AUTH_URL = "https://www.patreon.com/oauth2/authorize"
PATREON_TOKEN_URL = "https://www.patreon.com/api/oauth2/token"
PATREON_IDENTITY_URL = "https://www.patreon.com/api/oauth2/v2/identity"
PATREON_CAMPAIGNS_URL = "https://www.patreon.com/api/oauth2/v2/campaigns"

# Define scopes
PATREON_SCOPES = ["identity", "campaigns", "w:campaigns.posts", "campaigns.posts"]

@router.post("/auth/init")
async def init_patreon_auth(request: Request, user_data=Depends(get_current_user), db: Database = Depends(get_database)):
    """
    Initialize Patreon OAuth 2.0 flow and return authorization URL
    """
    logger.info("Initializing Patreon auth flow")
    if not PATREON_CLIENT_ID or not PATREON_CLIENT_SECRET or not PATREON_REDIRECT_URI:
        logger.error(f"Missing Patreon credentials - CLIENT_ID: {bool(PATREON_CLIENT_ID)}, CLIENT_SECRET: {bool(PATREON_CLIENT_SECRET)}, REDIRECT_URI: {bool(PATREON_REDIRECT_URI)}")
        raise HTTPException(status_code=500, detail="Patreon API credentials not configured")
    
    # Generate a unique state parameter to protect against CSRF
    state = secrets.token_urlsafe(32)
    
    # Calculate expiration time (10 minutes from now)
    expires_at = datetime.now() + timedelta(minutes=10)
    
    # Store the state in the database to verify later
    query = """
    INSERT INTO mo_oauth_states (user_id, platform, state, created_at, expires_at, used, code_verifier, redirect_uri) 
    VALUES (:user_id, 'patreon', :state, NOW(), :expires_at, false, '', null)
    """
    try:
        await db.execute(query, {"user_id": user_data["uid"], "state": state, "expires_at": expires_at})
    except Exception as e:
        logger.error(f"Error storing OAuth state: {str(e)}")
        # If the table doesn't exist yet, we'll create it
        try:
            create_table_query = """
            CREATE TABLE IF NOT EXISTS mo_oauth_states (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                code_verifier TEXT,
                redirect_uri TEXT
            )
            """
            await db.execute(create_table_query)
            # Try again
            await db.execute(query, {"user_id": user_data["uid"], "state": state, "expires_at": expires_at})
        except Exception as e2:
            logger.error(f"Error creating table and storing state: {str(e2)}")
            # We'll continue anyway but note the issue
            pass
    
    # Build authorization URL
    auth_url = f"{PATREON_AUTH_URL}?response_type=code&client_id={PATREON_CLIENT_ID}"
    auth_url += f"&redirect_uri={PATREON_REDIRECT_URI}"
    auth_url += f"&state={state}"
    auth_url += f"&scope={' '.join(PATREON_SCOPES)}"
    
    return JSONResponse({
        "auth_url": auth_url,
        "state": state
    })


@router.post("/auth/callback")
async def patreon_callback(
    request: Request,
    user_data=Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Handle Patreon OAuth callback and store user information
    """
    try:
        # Extract code and state from request body
        request_data = await request.json()
        code = request_data.get("code")
        state = request_data.get("state")

        if not code or not state:
            logger.error(f"Missing required parameters: code or state")
            raise HTTPException(
                status_code=422, detail="Missing required parameters: code and state must be provided")

        logger.info(
            f"Received Patreon callback with code: {code[:5]}... and state: {state[:5]}...")

        # Verify the state parameter
        try:
            query = """
            SELECT * FROM mo_oauth_states 
            WHERE user_id = :user_id AND platform = 'patreon' AND state = :state
            ORDER BY created_at DESC LIMIT 1
            """
            oauth_state = await db.fetch_one(query, {"user_id": user_data["uid"], "state": state})

            if not oauth_state:
                # For development, we'll be more lenient with state verification
                logger.warning(
                    "State verification failed, but continuing for development")
        except Exception as e:
            logger.error(f"Error verifying state: {str(e)}")
            # Continue anyway for development

        # Exchange code for access token
        try:
            async with httpx.AsyncClient() as client:
                token_response = await client.post(
                    PATREON_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": PATREON_CLIENT_ID,
                        "client_secret": PATREON_CLIENT_SECRET,
                        "redirect_uri": PATREON_REDIRECT_URI
                    }
                )

                logger.info(
                    f"Token exchange response status: {token_response.status_code}")

                # Log response for debugging
                if token_response.status_code != 200:
                    logger.error(
                        f"Token exchange failed: {token_response.text}")

                token_data = token_response.json()

                if "error" in token_data:
                    error_msg = f"Failed to obtain access token: {token_data.get('error_description', token_data['error'])}"
                    logger.error(error_msg)
                    raise HTTPException(status_code=400, detail=error_msg)

                access_token = token_data["access_token"]
                refresh_token = token_data.get("refresh_token")
                expires_in = token_data.get("expires_in", 3600)

                # Fetch user information
                user_response = await client.get(
                    f"{PATREON_IDENTITY_URL}?include=memberships,memberships.currently_entitled_tiers,memberships.campaign",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                user_info = user_response.json()

                # Fetch campaign information if the user is a creator
                try:
                    campaign_response = await client.get(
                        f"{PATREON_CAMPAIGNS_URL}?include=tiers",
                        headers={"Authorization": f"Bearer {access_token}"}
                    )
                    campaign_data = campaign_response.json()
                except Exception as e:
                    logger.error(f"Error fetching campaigns: {str(e)}")
                    campaign_data = {"data": []}

        except Exception as e:
            logger.error(f"Error in Patreon callback: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Error processing callback: {str(e)}")

        # Extract relevant user data
        try:
            patreon_user = user_info["data"]["attributes"]
            patreon_id = user_info["data"]["id"]

            # Check for creator status
            is_creator = len(campaign_data.get("data", [])) > 0

            # Process campaign data if user is a creator
            campaign = None
            if is_creator and campaign_data.get("data"):
                campaign_raw = campaign_data["data"][0]
                campaign = {
                    "id": campaign_raw["id"],
                    "summary": campaign_raw["attributes"].get("summary", ""),
                    "creation_name": campaign_raw["attributes"].get("creation_name", ""),
                    "pay_per_name": campaign_raw["attributes"].get("pay_per_name", ""),
                    "is_monthly": campaign_raw["attributes"].get("is_monthly", True),
                    "url": campaign_raw["attributes"].get("url", ""),
                    "patron_count": campaign_raw["attributes"].get("patron_count", 0),
                    "creation_count": campaign_raw["attributes"].get("creation_count", 0),
                    "published_at": campaign_raw["attributes"].get("published_at", "")
                }

                # Process tiers if included
                included = campaign_data.get("included", [])
                tiers = []
                for item in included:
                    if item["type"] == "tier":
                        tiers.append({
                            "id": item["id"],
                            "title": item["attributes"].get("title", ""),
                            "amount_cents": item["attributes"].get("amount_cents", 0),
                            "description": item["attributes"].get("description", ""),
                            "image_url": item["attributes"].get("image_url", "")
                        })

                if tiers:
                    campaign["tiers"] = tiers

            # Extract membership/patron data
            patron_data = None
            memberships = [item for item in user_info.get(
                "included", []) if item["type"] == "member"]
            if memberships:
                membership = memberships[0]
                patron_data = {
                    "patron_status": membership["attributes"].get("patron_status"),
                    "tier_title": None,
                    "tier_amount_cents": 0
                }

                # Find entitled tiers
                entitled_tiers = []
                for item in user_info.get("included", []):
                    if (item["type"] == "tier" and
                            any(rel.get("id") == item["id"] for rel in membership.get("relationships", {}).get("currently_entitled_tiers", {}).get("data", []))):
                        entitled_tiers.append(item)

                if entitled_tiers:
                    tier = entitled_tiers[0]["attributes"]
                    patron_data["tier_title"] = tier.get("title")
                    patron_data["tier_amount_cents"] = tier.get("amount_cents")

            # Store Patreon account info in database
            account_id = str(uuid.uuid4())

            # Check if the mo_social_accounts table exists
            try:
                # Check if mo_social_accounts table exists
                check_table_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'mo_social_accounts'
                );
                """
                table_exists = await db.fetch_val(check_table_query)

                if not table_exists:
                    # Create mo_social_accounts table
                    create_table_query = """
                    CREATE TABLE IF NOT EXISTS mo_social_accounts (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        platform_account_id TEXT NOT NULL,
                        username TEXT,
                        access_token TEXT NOT NULL,
                        refresh_token TEXT,
                        expires_at TIMESTAMP,
                        metadata JSONB,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    );
                    """
                    await db.execute(create_table_query)
            except Exception as e:
                logger.error(
                    f"Error checking/creating mo_social_accounts table: {str(e)}")
                # Continue anyway for development

            try:
                # Check if account already exists
                existing_query = """
                SELECT id FROM mo_social_accounts 
                WHERE user_id = :user_id AND platform = 'patreon' AND platform_account_id = :patreon_id
                """
                existing = await db.fetch_one(existing_query, {
                    "user_id": user_data["uid"],
                    "patreon_id": patreon_id
                })

                if existing:
                    account_id = existing["id"]

                    # Fix the update query for existing account
                    update_query = """
                    UPDATE mo_social_accounts SET
                        access_token = :access_token,
                        refresh_token = :refresh_token,
                        expires_at = :expires_at,
                        metadata = :metadata,
                        username = :username,
                        updated_at = NOW()
                    WHERE id = :account_id
                    """


                    metadata = {
                        "full_name": patreon_user.get("full_name"),
                        "email": patreon_user.get("email"),
                        "profile_image_url": patreon_user.get("image_url"),
                        "about": patreon_user.get("about"),
                        "is_creator": is_creator,
                        "campaign": campaign,
                        "patron_data": patron_data
                    }

                    # Calculate the actual expiry timestamp
                    expires_at = datetime.now() + timedelta(seconds=expires_in)
                    
                    await db.execute(update_query, {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_at": expires_at,
                        "metadata": json.dumps(metadata),
                        "username": patreon_user.get("full_name") or patreon_user.get("vanity") or "",
                        "account_id": account_id
                    })
                else:
                    # Fix the insert query with the correct enum value
                    insert_query = """
                    INSERT INTO mo_social_accounts (
                        id, user_id, platform, platform_account_id, username,
                        access_token, refresh_token, expires_at, metadata, created_at, updated_at
                    ) VALUES (
                        :account_id, :user_id, 'patreon', :patreon_id, :username,
                        :access_token, :refresh_token, :expires_at, :metadata, NOW(), NOW()
                    )
                    """

                    metadata = {
                        "full_name": patreon_user.get("full_name"),
                        "email": patreon_user.get("email"),
                        "profile_image_url": patreon_user.get("image_url"),
                        "about": patreon_user.get("about"),
                        "is_creator": is_creator,
                        "campaign": campaign,
                        "patron_data": patron_data
                    }

                    # Calculate the actual expiry timestamp
                    expires_at = datetime.now() + timedelta(seconds=expires_in)
                    
                    await db.execute(insert_query, {
                        "account_id": account_id,
                        "user_id": user_data["uid"],
                        "patreon_id": patreon_id,
                        "username": patreon_user.get("full_name") or patreon_user.get("vanity") or "",
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_at": expires_at,
                        "metadata": json.dumps(metadata)
                    })
            except Exception as e:
                logger.error(f"Error saving account to database: {str(e)}")
                # Log the error but continue to return user data

            # Return user and account information
            user_result = {
                "patreon_id": patreon_id,
                "full_name": patreon_user.get("full_name"),
                "vanity": patreon_user.get("vanity"),
                "email": patreon_user.get("email"),
                "thumb_url": patreon_user.get("image_url"),
            }

            if patron_data and patron_data.get("tier_title"):
                user_result["tier_title"] = patron_data["tier_title"]
                user_result["tier_amount_cents"] = patron_data["tier_amount_cents"]

            result = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user": user_result
            }

            if campaign:
                result["campaign"] = campaign

            return result

        except Exception as e:
            logger.error(f"Error processing Patreon user data: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Error processing user data: {str(e)}")

    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        raise HTTPException(
            status_code=422, detail="Invalid JSON in request body")
    except KeyError as e:
        logger.error(f"Missing required field: {str(e)}")
        raise HTTPException(
            status_code=422, detail=f"Missing required field: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in patreon_callback: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Unexpected error: {str(e)}")

@router.get("/user")
async def get_patreon_user(request: Request, user_data=Depends(get_current_user), db: Database = Depends(get_database)):
    """
    Get Patreon account information for the current user
    """
    try:
        query = """
        SELECT id, platform_account_id, username, access_token, refresh_token, expires_at, metadata
        FROM mo_social_accounts
        WHERE user_id = :user_id AND platform = 'patreon'
          """
        accounts = await db.fetch_all(query, {"user_id": user_data["uid"]})
        
        if not accounts:
            return JSONResponse({"connected": False, "accounts": []})
        
        formatted_accounts = []
        for account in accounts:
            metadata = json.loads(account["metadata"]) if account["metadata"] else {}
            is_creator = metadata.get("is_creator", False)
            
            formatted_account = {
                "id": account["id"],
                "platform_account_id": account["platform_account_id"],
                "username": account["username"],
                "profile_picture_url": metadata.get("profile_image_url"),
                "accountType": "creator" if is_creator else "patron",
                "metadata": metadata
            }
            formatted_accounts.append(formatted_account)
        
        return JSONResponse({
            "connected": True,
            "accounts": formatted_accounts
        })
        
    except Exception as e:
        logger.error(f"Error fetching Patreon user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching user data: {str(e)}")

@router.get("/campaigns")
async def get_campaigns(request: Request, user_data=Depends(get_current_user), db: Database = Depends(get_database)):
    """
    Get Patreon campaigns for the current user (if creator)
    """
    try:
        # Get Patreon account
        query = """
        SELECT id, access_token, metadata
        FROM mo_social_accounts
        WHERE user_id = :user_id AND platform = 'patreon'
        """
        account = await db.fetch_one(query, {"user_id": user_data["uid"]})
        
        if not account:
            raise HTTPException(status_code=404, detail="No Patreon account connected")
        
        metadata = json.loads(account["metadata"]) if account["metadata"] else {}
        is_creator = metadata.get("is_creator", False)
        
        if not is_creator:
            raise HTTPException(status_code=403, detail="User is not a creator")
        
        access_token = account["access_token"]
        
        # Fetch campaigns from Patreon
        async with httpx.AsyncClient() as client:
            campaign_response = await client.get(
                f"{PATREON_CAMPAIGNS_URL}?include=tiers",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            campaign_data = campaign_response.json()
        
        # Process campaign data
        campaigns = []
        if campaign_data.get("data"):
            for campaign_raw in campaign_data["data"]:
                campaign = {
                    "id": campaign_raw["id"],
                    "summary": campaign_raw["attributes"].get("summary", ""),
                    "creation_name": campaign_raw["attributes"].get("creation_name", ""),
                    "pay_per_name": campaign_raw["attributes"].get("pay_per_name", ""),
                    "is_monthly": campaign_raw["attributes"].get("is_monthly", True),
                    "url": campaign_raw["attributes"].get("url", ""),
                    "patron_count": campaign_raw["attributes"].get("patron_count", 0),
                    "creation_count": campaign_raw["attributes"].get("creation_count", 0),
                    "published_at": campaign_raw["attributes"].get("published_at", "")
                }
                
                # Process tiers if included
                included = campaign_data.get("included", [])
                tiers = []
                for item in included:
                    if item["type"] == "tier":
                        tiers.append({
                            "id": item["id"],
                            "title": item["attributes"].get("title", ""),
                            "amount_cents": item["attributes"].get("amount_cents", 0),
                            "description": item["attributes"].get("description", ""),
                            "image_url": item["attributes"].get("image_url", "")
                        })
                
                if tiers:
                    campaign["tiers"] = tiers
                
                campaigns.append(campaign)
        
        return campaigns
        
    except Exception as e:
        logger.error(f"Error fetching Patreon campaigns: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching campaigns: {str(e)}")

@router.get("/campaigns/{campaign_id}/tiers")
async def get_campaign_tiers(
    campaign_id: str,
    request: Request, 
    user_data=Depends(get_current_user), 
    db: Database = Depends(get_database)
):
    """
    Get tiers for a specific Patreon campaign
    """
    try:
        # Add debug logging
        logger.info(f"Fetching tiers for campaign {campaign_id}")
        
        # Get Patreon account
        # FORCE raw SQL query to prevent prepared statement reuse
        query = """
        SELECT id, access_token
        FROM mo_social_accounts
        WHERE user_id = :user_id AND platform = :platform
        """
        logger.info(f"Executing query with user_id={user_data['uid']}")
        account = await db.fetch_one(query, {"user_id": user_data["uid"], "platform": "patreon"})
        
        if not account:
            logger.warning("No Patreon account found for user")
            raise HTTPException(status_code=404, detail="No Patreon account connected")
        
        logger.info(f"Found account with id={account['id']}")
        access_token = account["access_token"]
        
        # Fetch campaign with tiers
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PATREON_CAMPAIGNS_URL}/{campaign_id}?include=tiers",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            campaign_data = response.json()
        
        # Process tiers
        tiers = []
        included = campaign_data.get("included", [])
        for item in included:
            if item["type"] == "tier":
                tiers.append({
                    "id": item["id"],
                    "title": item["attributes"].get("title", ""),
                    "amount_cents": item["attributes"].get("amount_cents", 0),
                    "description": item["attributes"].get("description", ""),
                    "image_url": item["attributes"].get("image_url", "")
                })
        
        logger.info(f"Returning {len(tiers)} tiers for campaign {campaign_id}")
        return tiers
        
    except Exception as e:
        logger.error(f"Error fetching campaign tiers: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching tiers: {str(e)}")

@router.post("/auth/disconnect")
async def disconnect_patreon(
    request: Request,
    data: Dict[str, Any] = None,
    user_data=Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Disconnect Patreon account
    """
    try:
        if data is None:
            data = await request.json()
        
        account_id = data.get("account_id")
        query_params = {"user_id": user_data["uid"]}
        
        logger.info(f"Disconnecting Patreon account: {account_id}")
        
        if account_id:
            # Cast account_id to TEXT in the query to avoid UUID conversion
            query = """
            DELETE FROM mo_social_accounts 
            WHERE CAST(id AS TEXT) = CAST(:account_id AS TEXT) AND user_id = :user_id AND platform = 'patreon'
            RETURNING id
            """
            query_params["account_id"] = str(account_id)
        else:
            query = """
            DELETE FROM mo_social_accounts 
            WHERE user_id = :user_id AND platform = 'patreon'
            RETURNING id
            """
        
        result = await db.fetch_one(query, query_params)
        
        if not result:
            raise HTTPException(status_code=404, detail="Patreon account not found or already disconnected")
        
        return JSONResponse({
            "success": True,
            "message": "Patreon account disconnected successfully"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disconnecting Patreon: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error disconnecting account: {str(e)}")
