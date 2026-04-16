"""
Common validation utilities for enum-typed request parameters.
"""
from enum import Enum
from typing import Type


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
