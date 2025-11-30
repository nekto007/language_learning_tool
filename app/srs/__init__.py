# app/srs/__init__.py
"""
Unified SRS (Spaced Repetition System) module.
Provides consistent SRS behavior across all entry points:
- /study (flashcards)
- /book-courses (vocabulary lessons)
- /curriculum (lessons)
"""

from app.srs.constants import (
    RATING_DONT_KNOW,
    RATING_DOUBT,
    RATING_KNOW,
    MAX_SESSION_ATTEMPTS,
    REQUEUE_RANGE_DONT_KNOW,
    REQUEUE_RANGE_DOUBT,
)
from app.srs.service import UnifiedSRSService

__all__ = [
    'UnifiedSRSService',
    'RATING_DONT_KNOW',
    'RATING_DOUBT',
    'RATING_KNOW',
    'MAX_SESSION_ATTEMPTS',
    'REQUEUE_RANGE_DONT_KNOW',
    'REQUEUE_RANGE_DOUBT',
]
