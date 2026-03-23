"""
Utility helper functions.
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def format_response(success: bool, data=None, error: str | None = None) -> dict:
    """Standard API response envelope."""
    return {
        "success": success,
        "data": data,
        "error": error,
        "timestamp": utc_now().isoformat(),
    }
