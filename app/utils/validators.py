"""
Common validation utilities for enum-typed request parameters.
"""
from datetime import date
from enum import Enum
from typing import Optional, Tuple, Type


def parse_date_param(raw: Optional[str]) -> Tuple[Optional[date], Optional[str]]:
    """Parse an ISO-8601 date string (YYYY-MM-DD) from a request parameter.

    Returns (date_obj, None) on success, (None, error_message) on failure.
    Returns (None, None) when *raw* is None (param absent).
    """
    if raw is None:
        return None, None
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, f"Invalid date format: '{raw}'. Expected YYYY-MM-DD."


def validate_enum(value: str, enum_cls: Type[Enum]) -> bool:
    """Return True if *value* is a valid member value of *enum_cls*."""
    try:
        enum_cls(value)
        return True
    except ValueError:
        return False


class WordStatus(str, Enum):
    """Valid string values for user-word status."""
    NEW = 'new'
    LEARNING = 'learning'
    REVIEW = 'review'
    MASTERED = 'mastered'


class LessonStatus(str, Enum):
    """Valid string values for lesson progress status."""
    NOT_STARTED = 'not_started'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
