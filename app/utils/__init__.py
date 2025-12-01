"""
Utility functions for the social media manager backend
"""

import re
from datetime import datetime, timezone
from typing import Union, Optional


def parse_datetime_safe(date_str: Union[str, datetime, None]) -> Optional[datetime]:
    """
    Safely parse datetime strings with proper microseconds handling.
    
    This function handles the issue where datetime.fromisoformat() fails when
    microseconds have fewer than 6 digits (e.g., '.3034' instead of '.303400').
    
    Args:
        date_str: The datetime string, datetime object, or None to parse
        
    Returns:
        datetime object or None if parsing fails
        
    Examples:
        >>> parse_datetime_safe('2025-06-04T08:40:25.3034+00:00')
        datetime.datetime(2025, 6, 4, 8, 40, 25, 303400, tzinfo=datetime.timezone.utc)
        
        >>> parse_datetime_safe('2025-06-04T08:40:25Z')
        datetime.datetime(2025, 6, 4, 8, 40, 25, tzinfo=datetime.timezone.utc)
    """
    if date_str is None:
        return None
        
    if isinstance(date_str, datetime):
        return date_str
        
    if not isinstance(date_str, str):
        return None
    
    try:
        # Normalize timezone format
        normalized_str = date_str.replace('Z', '+00:00')
        
        try:
            # Try direct parsing first
            return datetime.fromisoformat(normalized_str)
        except ValueError:
            # Handle microseconds format issues by normalizing to 6 digits
            # Find microseconds pattern and pad with zeros if needed
            normalized_str = re.sub(
                r'\.(\d{1,6})', 
                lambda m: f'.{m.group(1).ljust(6, "0")}', 
                normalized_str
            )
            return datetime.fromisoformat(normalized_str)
            
    except ValueError:
        try:
            # Try parsing as Unix timestamp
            return datetime.fromtimestamp(int(date_str), tz=timezone.utc)
        except (ValueError, TypeError):
            return None