#firebase_admin_config.py
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth
from fastapi import HTTPException

# Load environment variables from .env file
load_dotenv()
cute = os.getenv('FIREBASE_PRIVATE_KEY').replace('***', '\n')
# print(cute)


def get_firebase_cred():
    firebase_cred = {
        "type": os.getenv('FIREBASE_TYPE'),
        "project_id": os.getenv('FIREBASE_PROJECT_ID'),
        "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID'),
        "private_key": cute,
        "client_email": os.getenv('FIREBASE_CLIENT_EMAIL'),
        "client_id": os.getenv('FIREBASE_CLIENT_ID'),
        "auth_uri": os.getenv('FIREBASE_AUTH_URI'),
        "token_uri": os.getenv('FIREBASE_TOKEN_URI'),
        "auth_provider_x509_cert_url": os.getenv('FIREBASE_AUTH_PROVIDER_X509_CERT_URL'),
        "client_x509_cert_url": os.getenv('FIREBASE_CLIENT_X509_CERT_URL'),
        "universe_domain": os.getenv('FIREBASE_UNIVERSE_DOMAIN')
    }
    return firebase_cred


# Load Firebase credentials
firebase_cred = get_firebase_cred()

# Initialize the Firebase Admin SDK
cred = credentials.Certificate(firebase_cred)
firebase_admin.initialize_app(cred)


def verify_token(token):
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
# SC 30106.59