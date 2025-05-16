import os
from typing import Dict, Optional, Any

import firebase_admin
from firebase_admin import credentials, auth
from fastapi import HTTPException, status

# Initialize Firebase Admin SDK
try:
    # Check for service account JSON path first
    credentials_path = os.getenv("FIREBASE_ADMIN_CREDENTIALS_PATH")
    if credentials_path and os.path.exists(credentials_path):
        # Use the JSON file if it exists
        print(f"Initializing Firebase with credentials file at {credentials_path}")
        cred = credentials.Certificate(credentials_path)
        firebase_app = firebase_admin.initialize_app(cred)
    elif os.getenv("FIREBASE_SERVICE_ACCOUNT"):
        # If service account credentials are provided as an environment variable
        import json
        service_account_info = json.loads(os.getenv("FIREBASE_SERVICE_ACCOUNT", "{}"))
        cred = credentials.Certificate(service_account_info)
        # Initialize with explicit project ID from service account
        firebase_app = firebase_admin.initialize_app(cred)
    elif all([
        os.getenv("FIREBASE_TYPE"),
        os.getenv("FIREBASE_PROJECT_ID"),
        os.getenv("FIREBASE_PRIVATE_KEY_ID"),
        os.getenv("FIREBASE_PRIVATE_KEY"),
        os.getenv("FIREBASE_CLIENT_EMAIL"),
        os.getenv("FIREBASE_CLIENT_ID")
    ]):
        # Construct service account from individual variables
        print("Initializing Firebase with environment variables")
        
        # Fix the private key format
        # 1. Remove the ***
        # 2. Replace escaped newlines with actual newlines if needed
        # 3. Remove quotes if present
        private_key = os.getenv("FIREBASE_PRIVATE_KEY", "")
        private_key = private_key.replace("***", "")
        
        # Check if the key has proper newlines, if not, add them
        if '\n' not in private_key and 'PRIVATE KEY' in private_key:
            # Add proper newline formatting
            parts = private_key.split("-----")
            if len(parts) >= 3:
                # Reconstruct with proper newlines
                private_key = f"-----{parts[1]}-----\n{parts[2]}\n-----{parts[3]}-----\n"
        
        # Remove any surrounding quotes
        if private_key.startswith('"') and private_key.endswith('"'):
            private_key = private_key[1:-1]
        
        print(f"Private key formatted: {private_key[:20]}...{private_key[-20:] if len(private_key) > 40 else ''}")
        
        service_account_info = {
            "type": os.getenv("FIREBASE_TYPE"),
            "project_id": os.getenv("FIREBASE_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": private_key,
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": os.getenv("FIREBASE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": os.getenv("FIREBASE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
            "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL", "https://www.googleapis.com/oauth2/v1/certs"),
            "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL", ""),
            "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN", "googleapis.com")
        }
        
        try:
            cred = credentials.Certificate(service_account_info)
            firebase_app = firebase_admin.initialize_app(cred)
            print("Successfully initialized Firebase with environment variables")
        except Exception as cert_error:
            print(f"Error creating credential from environment variables: {cert_error}")
            
            # Fallback to the service account file if it exists
            if os.path.exists("/Volumes/ExtremeSSD/workspaces/realworld-workspaces/agdoc/config/serviceAccountKey.json"):
                print("Falling back to service account file")
                cred = credentials.Certificate("/Volumes/ExtremeSSD/workspaces/realworld-workspaces/agdoc/config/serviceAccountKey.json")
                firebase_app = firebase_admin.initialize_app(cred)
            else:
                raise cert_error
    elif os.getenv("GOOGLE_CLOUD_PROJECT"):
        # If project ID is set in environment
        cred = credentials.ApplicationDefault()
        firebase_app = firebase_admin.initialize_app(cred, {
            'projectId': os.getenv("GOOGLE_CLOUD_PROJECT")
        })
    else:
        # Try to use service account JSON file directly as a last resort
        service_account_path = "/Volumes/ExtremeSSD/workspaces/realworld-workspaces/agdoc/config/serviceAccountKey.json"
        if os.path.exists(service_account_path):
            print(f"Using service account file at {service_account_path}")
            cred = credentials.Certificate(service_account_path)
            firebase_app = firebase_admin.initialize_app(cred)
        else:
            # Last attempt to use application default credentials
            project_id = os.getenv("FIREBASE_PROJECT_ID")
            if not project_id:
                raise ValueError("FIREBASE_PROJECT_ID environment variable is required")
            
            cred = credentials.ApplicationDefault()
            firebase_app = firebase_admin.initialize_app(cred, {
                'projectId': project_id
            })
            print("Using Application Default Credentials")
except Exception as e:
    print(f"Firebase initialization error: {e}")
    raise Exception(f"Failed to initialize Firebase: {str(e)}")

async def verify_firebase_token(token: str) -> Dict[str, Any]:
    """
    Verify a Firebase ID token and return the decoded token with user claims
    
    Args:
        token: The Firebase ID token to verify (with or without 'Bearer ' prefix)
        
    Returns:
        The decoded token with user information
        
    Raises:
        HTTPException: If the token is invalid or expired
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Remove 'Bearer ' prefix if present
    if token.startswith("Bearer "):
        token = token[7:]
    
    try:
        # Verify the token
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.RevokedIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication error: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get Firebase user by email"""
    try:
        user = auth.get_user_by_email(email)
        return user.__dict__
    except auth.UserNotFoundError:
        return None
    except Exception as e:
        print(f"Error getting user by email: {e}")
        return None

async def get_user_by_uid(uid: str) -> Optional[Dict[str, Any]]:
    """Get Firebase user by UID"""
    try:
        user = auth.get_user(uid)
        return user.__dict__
    except auth.UserNotFoundError:
        return None
    except Exception as e:
        print(f"Error getting user by UID: {e}")
        return None 