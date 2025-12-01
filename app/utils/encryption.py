import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# Get encryption key from environment or generate one
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(f"Warning: ENCRYPTION_KEY not found in environment. Generated temporary key: {ENCRYPTION_KEY}")

fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt_token(token: str) -> str:
    """Encrypt a token string"""
    if not token:
        return None
    try:
        return fernet.encrypt(token.encode()).decode()
    except Exception as e:
        print(f"Error encrypting token: {e}")
        raise

def decrypt_token(encrypted_token: str) -> str:
    """Decrypt an encrypted token string"""
    if not encrypted_token:
        return None
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        print(f"Error decrypting token: {e}")
        # Return None instead of raising to prevent 500 errors
        return None 