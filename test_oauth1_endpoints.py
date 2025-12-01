#!/usr/bin/env python3
"""
Test script for Twitter OAuth 1.0a endpoints
Run this to test the new endpoints without actually making requests to Twitter
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def test_oauth1_signature_generation():
    """Test the OAuth 1.0a signature generation function"""
    try:
        from app.routers.social_connections import _generate_oauth1_signature, _generate_oauth1_header
        
        # Test parameters (example from Twitter documentation)
        method = "POST"
        url = "https://api.twitter.com/oauth/request_token"
        params = {
            'oauth_consumer_key': 'test_consumer_key',
            'oauth_nonce': 'test_nonce',
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': '1640995200',
            'oauth_version': '1.0',
            'oauth_callback': 'https://example.com/callback'
        }
        consumer_secret = "test_consumer_secret"
        
        # Generate signature
        signature = _generate_oauth1_signature(method, url, params, consumer_secret)
        
        print("✅ OAuth 1.0a signature generation test passed")
        print(f"   Generated signature: {signature[:20]}...")
        
        # Test header generation
        header = _generate_oauth1_header(
            method=method,
            url=url,
            consumer_key='test_consumer_key',
            consumer_secret=consumer_secret,
            additional_params={'oauth_callback': 'https://example.com/callback'}
        )
        
        print("✅ OAuth 1.0a header generation test passed")
        print(f"   Generated header: OAuth {header[6:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ OAuth 1.0a generation test failed: {str(e)}")
        return False

def test_imports():
    """Test that all required imports work"""
    try:
        from app.routers.social_connections import router
        from app.routers.social_connections import twitter_oauth1_initiate, twitter_oauth1_callback, twitter_oauth1_status
        
        print("✅ All imports test passed")
        print(f"   Router loaded with {len(router.routes)} routes")
        
        # Check if our new routes are in the router
        route_paths = [route.path for route in router.routes if hasattr(route, 'path')]
        oauth1_routes = [path for path in route_paths if 'twitter-oauth1' in path]
        
        print(f"   Found {len(oauth1_routes)} OAuth 1.0a routes:")
        for route in oauth1_routes:
            print(f"     - {route}")
        
        return True
        
    except Exception as e:
        print(f"❌ Imports test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("🧪 Testing Twitter OAuth 1.0a Implementation")
    print("=" * 50)
    
    tests = [
        ("Imports", test_imports),
        ("OAuth 1.0a Signature Generation", test_oauth1_signature_generation),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 Running {test_name} test...")
        if test_func():
            passed += 1
        else:
            print(f"   Test failed!")
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! OAuth 1.0a implementation looks good.")
        return True
    else:
        print("❌ Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)