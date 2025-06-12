#!/usr/bin/env python3
"""
Quick test script to verify the unified posts API JSON parsing fix
"""

import json

# Test the safe_json_parse function
def safe_json_parse(value, default):
    """Safely parse JSON strings to Python objects"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    elif value is None:
        return default
    else:
        return value

# Test cases that match the actual database data
test_cases = [
    # Test JSON string parsing (what's currently in the database)
    {
        'universal_metadata': '{}',
        'platform_content': '{}',
        'platforms': '[{"provider": "facebook", "accountId": "451556294717299", "displayName": "I Am Testing"}]',
        'media_files': '[{"id": "fe29c9c1-4bce-469d-9a45-4904c126649c", "type": "image"}]'
    },
    # Test already parsed objects
    {
        'universal_metadata': {},
        'platform_content': {},
        'platforms': [],
        'media_files': []
    },
    # Test None values
    {
        'universal_metadata': None,
        'platform_content': None,
        'platforms': None,
        'media_files': None
    }
]

def transform_post_data(post):
    """Transform post data from database to API response format"""
    return {
        **post,
        'universal_metadata': safe_json_parse(post.get('universal_metadata'), {}),
        'platform_content': safe_json_parse(post.get('platform_content'), {}),
        'platforms': safe_json_parse(post.get('platforms'), []),
        'media_files': safe_json_parse(post.get('media_files'), []),
    }

# Run tests
for i, test_case in enumerate(test_cases):
    print(f"\n=== Test Case {i + 1} ===")
    print("Input:", test_case)
    
    try:
        result = transform_post_data(test_case)
        print("Output:", result)
        print("Success: ✅")
        
        # Validate types
        assert isinstance(result['universal_metadata'], dict), "universal_metadata should be dict"
        assert isinstance(result['platform_content'], dict), "platform_content should be dict"
        assert isinstance(result['platforms'], list), "platforms should be list"
        assert isinstance(result['media_files'], list), "media_files should be list"
        print("Type validation: ✅")
        
    except Exception as e:
        print(f"Error: ❌ {e}")

print("\n=== All tests completed ===")