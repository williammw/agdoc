"""
Timezone utilities for enterprise scheduling
"""

from datetime import datetime
from typing import Optional
import pytz

# Common timezones for social media scheduling
COMMON_TIMEZONES = {
    'America/New_York': 'Eastern Time',
    'America/Chicago': 'Central Time', 
    'America/Denver': 'Mountain Time',
    'America/Los_Angeles': 'Pacific Time',
    'Europe/London': 'London Time',
    'Europe/Paris': 'Central European Time',
    'Asia/Tokyo': 'Japan Time',
    'Asia/Shanghai': 'China Time',
    'Australia/Sydney': 'Sydney Time',
    'UTC': 'Coordinated Universal Time'
}

def convert_timezone(dt: datetime, from_tz: str, to_tz: str) -> datetime:
    """
    Convert datetime from one timezone to another
    
    Args:
        dt: The datetime to convert
        from_tz: Source timezone (e.g., 'UTC', 'America/New_York')
        to_tz: Target timezone
        
    Returns:
        Converted datetime
    """
    if from_tz == to_tz:
        return dt
        
    try:
        from_timezone = pytz.timezone(from_tz)
        to_timezone = pytz.timezone(to_tz)
        
        # If datetime is naive, assume it's in the from_tz
        if dt.tzinfo is None:
            localized_dt = from_timezone.localize(dt)
        else:
            localized_dt = dt
            
        # Convert to target timezone
        converted_dt = localized_dt.astimezone(to_timezone)
        
        # Return as naive datetime (remove timezone info)
        return converted_dt.replace(tzinfo=None)
        
    except Exception:
        # If conversion fails, return original datetime
        return dt

def get_user_timezone(user_id: Optional[str] = None) -> str:
    """
    Get user's preferred timezone
    For now returns UTC, but could be extended to store user preferences
    
    Args:
        user_id: Optional user ID to look up timezone preference
        
    Returns:
        Timezone string (e.g., 'UTC', 'America/New_York')
    """
    # TODO: Implement user timezone preference storage
    # For now, default to UTC
    return 'UTC'

def format_timezone_offset(timezone_str: str) -> str:
    """
    Get timezone offset string for display
    
    Args:
        timezone_str: Timezone name (e.g., 'America/New_York')
        
    Returns:
        Offset string (e.g., '-05:00', '+09:00')
    """
    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        offset = now.strftime('%z')
        
        # Format as +/-HH:MM
        if len(offset) == 5:
            return f"{offset[:3]}:{offset[3:]}"
        return offset
        
    except Exception:
        return '+00:00'

def is_valid_timezone(timezone_str: str) -> bool:
    """
    Check if timezone string is valid
    
    Args:
        timezone_str: Timezone to validate
        
    Returns:
        True if valid timezone
    """
    try:
        pytz.timezone(timezone_str)
        return True
    except Exception:
        return False

def get_timezone_choices() -> dict:
    """
    Get common timezone choices for UI
    
    Returns:
        Dict mapping timezone names to display labels
    """
    choices = {}
    for tz_name, display_name in COMMON_TIMEZONES.items():
        offset = format_timezone_offset(tz_name)
        choices[tz_name] = f"{display_name} ({offset})"
    
    return choices