"""
Middleware to handle HTTPS redirects when behind a proxy (DigitalOcean App Platform)
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import logging

logger = logging.getLogger(__name__)

class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle X-Forwarded headers from proxy/load balancer
    This fixes the HTTP redirect issue on DigitalOcean App Platform
    """
    
    async def dispatch(self, request: Request, call_next):
        # Check X-Forwarded headers
        forwarded_proto = request.headers.get("X-Forwarded-Proto")
        forwarded_host = request.headers.get("X-Forwarded-Host")
        
        # If we're behind a proxy that uses HTTPS, update the URL scheme
        if forwarded_proto == "https":
            # Override the URL scheme to HTTPS
            request.scope["scheme"] = "https"
            
        # If there's a forwarded host, use it
        if forwarded_host:
            request.scope["server"] = (forwarded_host, 443 if forwarded_proto == "https" else 80)
            
        # Log for debugging
        logger.debug(f"Request URL: {request.url}")
        logger.debug(f"Forwarded Proto: {forwarded_proto}")
        logger.debug(f"Forwarded Host: {forwarded_host}")
        
        response = await call_next(request)
        return response