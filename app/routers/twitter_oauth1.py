"""
OAuth 1.0a implementation for Twitter media uploads
"""

import base64
import hashlib
import hmac
import time
import urllib.parse
import os
from typing import Dict, Optional

# Twitter OAuth 1.0a credentials
TWITTER_CONSUMER_KEY = os.getenv("TWITTER_CONSUMER_API_KEY")
TWITTER_CONSUMER_SECRET = os.getenv("TWITTER_CONSUMER_API_SECRET")

def generate_oauth1_signature(
    method: str, 
    url: str, 
    params: Dict[str, str],
    consumer_secret: str,
    token_secret: Optional[str] = None
) -> str:
    """Generate OAuth 1.0a signature"""
    # Create parameter string
    param_string = "&".join([
        f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}" 
        for k, v in sorted(params.items())
    ])
    
    # Create signature base string
    base_string = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_string, safe='')}"
    
    # Create signing key
    signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&{urllib.parse.quote(token_secret or '', safe='')}"
    
    # Generate signature
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    
    return signature

def create_oauth1_header(
    method: str,
    url: str,
    oauth_token: str,
    oauth_token_secret: str,
    additional_params: Optional[Dict[str, str]] = None
) -> str:
    """Create OAuth 1.0a authorization header"""
    oauth_params = {
        'oauth_consumer_key': TWITTER_CONSUMER_KEY,
        'oauth_token': oauth_token,
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_nonce': hashlib.md5(f"{time.time()}{os.urandom(8).hex()}".encode()).hexdigest(),
        'oauth_version': '1.0'
    }
    
    # Add additional parameters for signature calculation
    all_params = oauth_params.copy()
    if additional_params:
        all_params.update(additional_params)
    
    # Generate signature
    signature = generate_oauth1_signature(
        method, 
        url, 
        all_params,
        TWITTER_CONSUMER_SECRET,
        oauth_token_secret
    )
    oauth_params['oauth_signature'] = signature
    
    # Create header
    auth_header = 'OAuth ' + ', '.join([
        f'{k}="{urllib.parse.quote(str(v), safe="")}"' 
        for k, v in oauth_params.items()
    ])
    
    return auth_header