"""
Formatting utilities for the Docker Orchestration System.
"""

from datetime import datetime
from typing import Optional


def format_time(timestamp: Optional[float]) -> str:
    """
    Format a Unix timestamp as a human-readable string.
    
    Args:
        timestamp: Unix timestamp in seconds, or None
        
    Returns:
        str: Formatted time string, or empty string if timestamp is None
    """
    if timestamp is None:
        return ""
    
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')


def bytes_to_human(size_bytes: int) -> str:
    """
    Convert bytes to a human-readable string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        str: Human-readable size string
    """
    if size_bytes == 0:
        return "0B"
    
    size_name = ("B", "KB", "MB", "GB", "TB", "PB")
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024
        i += 1
    
    return f"{size_bytes:.2f}{size_name[i]}"


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds as a human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        str: Formatted duration string
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {int(seconds)}s"
    
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{int(hours)}h {int(minutes)}m"
    
    days, hours = divmod(hours, 24)
    return f"{int(days)}d {int(hours)}h"