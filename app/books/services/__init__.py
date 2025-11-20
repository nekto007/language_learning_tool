"""
Books services module - business logic layer

Architecture:
- book_service.py: Book CRUD, progress tracking, bookmarks
"""

from .book_service import BookService

__all__ = [
    'BookService',
]
