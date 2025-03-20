"""
Copy and paste this debug endpoint at the end of your linkedin_router.py file
to help diagnose the issue with LinkedIn OAuth.
"""

@router.get("/debug-config")
async def debug_linkedin_config():
    """Debug LinkedIn OAuth configuration"""
    try:
        # Verify environment variables are loaded correctly
        config = {
            "client_id": CLIENT_ID[:5] + "..." if CLIENT_ID else None,
            "client_id_length": len(CLIENT_ID) if CLIENT_ID else 0,
            "client_secret_set": bool(CLIENT_SECRET),
            "client_secret_length": len(CLIENT_SECRET) if CLIENT_SECRET else 0,
            "redirect_uri": REDIRECT_URI,
            "environment": ENVIRONMENT,
            "token_endpoint": ENDPOINTS["token"],
            "auth_endpoint": ENDPOINTS["auth"],
        }
        
        # Check if credentials start/end with whitespace (common error)
        if CLIENT_ID and (CLIENT_ID.strip() != CLIENT_ID):
            config["warning"] = "CLIENT_ID contains leading or trailing whitespace"
        if CLIENT_SECRET and (CLIENT_SECRET.strip() != CLIENT_SECRET):
            config["warning"] = "CLIENT_SECRET contains leading or trailing whitespace"
            
        # Test connection to LinkedIn API
        try:
            # Simple test with invalid token to see if we can reach the API
            response = requests.get(
                "https://api.linkedin.com/v2/me", 
                headers={"Authorization": "Bearer invalid_token_just_testing_connectivity"},
                timeout=5
            )
            config["api_connectivity"] = {
                "status_code": response.status_code,
                "reason": response.reason
            }
            
            # Test a dummy token request with valid credentials (but invalid code)
            test_data = {
                "grant_type": "authorization_code",
                "code": "dummy_code",
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            }
            
            token_response = requests.post(
                ENDPOINTS["token"],
                data=test_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=5
            )
            
            config["token_endpoint_response"] = {
                "status_code": token_response.status_code,
                "reason": token_response.reason,
                "body": token_response.text[:200] + "..." if len(token_response.text) > 200 else token_response.text
            }
            
        except Exception as e:
            config["api_connectivity"] = {"error": str(e)}
        
        # Check redirect URI format
        if REDIRECT_URI:
            if not REDIRECT_URI.startswith("https://"):
                config["redirect_warning"] = "Redirect URI should use HTTPS"
            
            if " " in REDIRECT_URI:
                config["redirect_warning"] = "Redirect URI contains spaces"
        
        return config
    except Exception as e:
        return {"error": str(e)}
