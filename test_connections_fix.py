#!/usr/bin/env python3
"""
Test script to verify the social connections endpoint fix.
This script can be run to test the API endpoint directly.
"""

import os
import sys
import requests
import json
from pathlib import Path

# Add the app directory to Python path
app_dir = Path(__file__).parent / "app"
sys.path.insert(0, str(app_dir))

def test_connections_endpoint():
    """Test the /api/v1/social-connections/connections endpoint"""
    
    # Configuration
    base_url = "https://api.multivio.com"  # Replace with your actual API URL
    endpoint = f"{base_url}/api/v1/social-connections/connections"
    
    # You'll need to replace this with a valid authorization token
    token = "YOUR_FIREBASE_TOKEN_HERE"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("Testing social connections endpoint...")
    print(f"URL: {endpoint}")
    
    try:
        # Test without tokens
        print("\n1. Testing without tokens...")
        response = requests.get(endpoint, headers=headers)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("✅ Success - endpoint responds correctly without tokens")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"❌ Error: {response.text}")
        
        # Test with tokens
        print("\n2. Testing with include_tokens=true...")
        response = requests.get(f"{endpoint}?include_tokens=true", headers=headers)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("✅ Success - endpoint responds correctly with tokens")
            data = response.json()
            # Don't print the actual tokens for security
            print(f"Number of connections: {len(data)}")
            for conn in data:
                provider = conn.get('provider', 'unknown')
                has_access = bool(conn.get('access_token'))
                has_refresh = bool(conn.get('refresh_token'))
                print(f"  - {provider}: access_token={has_access}, refresh_token={has_refresh}")
        else:
            print(f"❌ Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Exception occurred: {str(e)}")

def test_encryption_functions():
    """Test the encryption/decryption functions"""
    print("\n3. Testing encryption functions...")
    
    try:
        from app.utils.encryption import encrypt_token, decrypt_token
        
        # Test normal case
        test_token = "test_access_token_12345"
        encrypted = encrypt_token(test_token)
        decrypted = decrypt_token(encrypted)
        
        if decrypted == test_token:
            print("✅ Encryption/decryption works correctly")
        else:
            print("❌ Encryption/decryption failed")
        
        # Test edge cases
        print("Testing edge cases...")
        
        # Test None input
        result = encrypt_token(None)
        if result is None:
            print("✅ encrypt_token handles None correctly")
        else:
            print("❌ encrypt_token doesn't handle None correctly")
        
        result = decrypt_token(None)
        if result is None:
            print("✅ decrypt_token handles None correctly")
        else:
            print("❌ decrypt_token doesn't handle None correctly")
        
        # Test empty string
        result = encrypt_token("")
        if result is None:
            print("✅ encrypt_token handles empty string correctly")
        else:
            print("❌ encrypt_token doesn't handle empty string correctly")
        
        # Test invalid encrypted data
        result = decrypt_token("invalid_encrypted_data")
        if result is None:
            print("✅ decrypt_token handles invalid data correctly")
        else:
            print("❌ decrypt_token doesn't handle invalid data correctly")
            
    except ImportError as e:
        print(f"❌ Cannot import encryption functions: {e}")
    except Exception as e:
        print(f"❌ Error testing encryption: {e}")

if __name__ == "__main__":
    print("🔧 Social Connections API Fix Test")
    print("=" * 50)
    
    print("\nIMPORTANT: Before running this test:")
    print("1. Update the base_url variable with your actual API URL")
    print("2. Replace YOUR_FIREBASE_TOKEN_HERE with a valid Firebase token")
    print("3. Ensure your API server is running")
    
    # Test encryption functions first
    test_encryption_functions()
    
    # Ask user if they want to test the API endpoint
    response = input("\nDo you want to test the API endpoint? (y/N): ")
    if response.lower() in ['y', 'yes']:
        test_connections_endpoint()
    else:
        print("Skipping API endpoint test.")
    
    print("\n" + "=" * 50)
    print("Test completed!")