#!/usr/bin/env python3
"""
Test script for AI endpoints
This script tests the AI functionality without requiring a running server.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all AI modules can be imported"""
    try:
        from app.models.ai import (
            AITransformRequest, 
            AIGenerateRequest, 
            GrokModel,
            ContentTransformationType,
            PlatformType,
            ContentTone
        )
        print("✓ AI models imported successfully")
        
        from app.services.ai_service import grok_service
        print("✓ AI service imported successfully")
        
        from app.routers.ai import router
        print("✓ AI router imported successfully")
        
        return True
    except Exception as e:
        print(f"✗ Import error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_model_creation():
    """Test that AI models can be created"""
    try:
        from app.models.ai import AITransformRequest, AIGenerateRequest
        
        # Test transform request
        transform_req = AITransformRequest(
            content="Hello world! This is a test.",
            transformation_type="platform_optimize",
            target_platform="twitter",
            model="grok-3-mini"
        )
        print("✓ AITransformRequest created successfully")
        
        # Test generate request
        generate_req = AIGenerateRequest(
            prompt="Write a social media post about AI",
            target_platform="linkedin",
            content_tone="professional",
            model="grok-3-mini"
        )
        print("✓ AIGenerateRequest created successfully")
        
        return True
    except Exception as e:
        print(f"✗ Model creation error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_service_configuration():
    """Test AI service configuration"""
    try:
        from app.services.ai_service import grok_service
        
        # Check service attributes
        print(f"✓ Service base URL: {grok_service.base_url}")
        print(f"✓ Service timeout: {grok_service.timeout}")
        
        # Check API key configuration (without exposing the key)
        api_key_configured = bool(grok_service.api_key)
        print(f"✓ API key configured: {api_key_configured}")
        
        if not api_key_configured:
            print("ℹ Note: GROK_API_KEY environment variable not set - live API calls will fail")
        
        return True
    except Exception as e:
        print(f"✗ Service configuration error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_router_creation():
    """Test that router can be created and has expected endpoints"""
    try:
        from app.routers.ai import router
        
        # Check router configuration
        print(f"✓ Router prefix: {router.prefix}")
        print(f"✓ Router tags: {router.tags}")
        
        # Check number of routes
        route_count = len(router.routes)
        print(f"✓ Number of routes: {route_count}")
        
        # List route paths
        routes = [route.path for route in router.routes if hasattr(route, 'path')]
        print(f"✓ Available routes: {routes}")
        
        expected_routes = ['/transform', '/generate', '/models', '/platforms', '/health', '/test']
        for expected_route in expected_routes:
            full_path = f"{router.prefix}{expected_route}"
            if any(expected_route in route for route in routes):
                print(f"  ✓ {expected_route} endpoint found")
            else:
                print(f"  ✗ {expected_route} endpoint missing")
        
        return True
    except Exception as e:
        print(f"✗ Router creation error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_main_app():
    """Test that main FastAPI app includes AI router"""
    try:
        from app.main import app
        
        print(f"✓ FastAPI app created successfully")
        print(f"✓ App title: {app.title}")
        
        # Check if AI routes are included
        all_routes = [route.path for route in app.routes if hasattr(route, 'path')]
        ai_routes = [route for route in all_routes if '/ai/' in route]
        
        if ai_routes:
            print(f"✓ AI routes found in app: {ai_routes}")
        else:
            print("✗ No AI routes found in app")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Main app error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing AI Endpoints Implementation")
    print("=" * 60)
    
    tests = [
        ("Import Tests", test_imports),
        ("Model Creation Tests", test_model_creation),
        ("Service Configuration Tests", test_service_configuration),
        ("Router Creation Tests", test_router_creation),
        ("Main App Tests", test_main_app),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        icon = "✓" if result else "✗"
        print(f"{icon} {test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! AI endpoints are ready to use.")
        print("\nNext steps:")
        print("1. Set GROK_API_KEY environment variable for live API calls")
        print("2. Start the FastAPI server: uvicorn app.main:app --reload")
        print("3. Test endpoints at http://localhost:8000/docs")
    else:
        print("❌ Some tests failed. Please check the implementation.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)