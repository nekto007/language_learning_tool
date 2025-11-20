"""
Book Service - business logic for book management

Responsibilities:
- Book CRUD operations
- Book processing status tracking
- Chapter and content management
- Vocabulary extraction
"""
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import joinedload

from app.utils.db import db
from app.books.models import Book, Chapter, Bookmark
from app.words.models import CollectionWords


class BookService:
    """Service for managing books"""

    @classmethod
    def get_user_books(cls, user_id: int, limit: int = None) -> List[Book]:
        """Get all books for user"""
        query = Book.query.filter_by(user_id=user_id).order_by(Book.created_at.desc())
        if limit:
            query = query.limit(limit)
        return query.all()

    @classmethod
    def get_book_with_chapters(cls, book_id: int) -> Optional[Book]:
        """Get book with chapters eager loaded"""
        return Book.query.options(
            joinedload(Book.chapters)
        ).get(book_id)

    @classmethod
    def create_book(cls, user_id: int, title: str, author: str = None,
                   language: str = 'en', description: str = None) -> Book:
        """Create a new book"""
        book = Book(
            user_id=user_id,
            title=title,
            author=author,
            language=language,
            description=description
        )
        db.session.add(book)
        db.session.commit()
        return book

    @classmethod
    def update_book(cls, book_id: int, user_id: int, **kwargs) -> Tuple[bool, Optional[str]]:
        """Update book details"""
        book = Book.query.get(book_id)

        if not book:
            return False, "Книга не найдена"

        if book.user_id != user_id:
            return False, "Нет доступа к этой книге"

        # Update allowed fields
        allowed_fields = ['title', 'author', 'description', 'language', 'cover_image']
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                setattr(book, field, value)

        db.session.commit()
        return True, None

    @classmethod
    def delete_book(cls, book_id: int, user_id: int) -> Tuple[bool, Optional[str]]:
        """Delete a book"""
        book = Book.query.get(book_id)

        if not book:
            return False, "Книга не найдена"

        if book.user_id != user_id:
            return False, "Нет доступа к этой книге"

        db.session.delete(book)
        db.session.commit()
        return True, None

    @classmethod
    def get_book_progress(cls, book_id: int, user_id: int) -> Dict:
        """
        Calculate reading progress for book

        Returns:
            Dictionary with progress statistics
        """
        from app.books.models import UserChapterProgress

        book = Book.query.get(book_id)
        if not book:
            return None

        total_chapters = Chapter.query.filter_by(book_id=book_id).count()

        if total_chapters == 0:
            return {
                'total_chapters': 0,
                'completed_chapters': 0,
                'progress_percent': 0
            }

        completed = UserChapterProgress.query.filter_by(
            user_id=user_id,
            book_id=book_id,
            completed=True
        ).count()

        return {
            'total_chapters': total_chapters,
            'completed_chapters': completed,
            'progress_percent': int((completed / total_chapters) * 100)
        }

    @classmethod
    def get_book_vocabulary(cls, book_id: int, user_id: int, limit: int = 50) -> List[Dict]:
        """
        Get vocabulary for book with user status

        Args:
            book_id: Book ID
            user_id: User ID
            limit: Maximum words to return

        Returns:
            List of word dictionaries with status
        """
        from app.study.models import UserWord
        from app.books.models import word_book_link

        # Get words for book
        words = db.session.query(CollectionWords).join(
            word_book_link,
            CollectionWords.id == word_book_link.c.word_id
        ).filter(
            word_book_link.c.book_id == book_id
        ).limit(limit).all()

        if not words:
            return []

        # Bulk load user word statuses
        word_ids = [w.id for w in words]
        user_words = UserWord.query.filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(word_ids)
        ).all()

        user_word_map = {uw.word_id: uw.status for uw in user_words}

        # Build result
        result = []
        for word in words:
            result.append({
                'id': word.id,
                'english': word.english_word,
                'russian': word.russian_word,
                'status': user_word_map.get(word.id, 'new'),
                'level': word.level,
                'frequency_rank': word.frequency_rank
            })

        return result

    @classmethod
    def create_bookmark(cls, user_id: int, book_id: int, chapter_id: int,
                       position: int, note: str = None) -> Bookmark:
        """Create a bookmark"""
        bookmark = Bookmark(
            user_id=user_id,
            book_id=book_id,
            chapter_id=chapter_id,
            position=position,
            note=note
        )
        db.session.add(bookmark)
        db.session.commit()
        return bookmark

    @classmethod
    def get_user_bookmarks(cls, user_id: int, book_id: int = None) -> List[Bookmark]:
        """Get user's bookmarks"""
        query = Bookmark.query.filter_by(user_id=user_id)

        if book_id:
            query = query.filter_by(book_id=book_id)

        return query.order_by(Bookmark.created_at.desc()).all()

    @classmethod
    def delete_bookmark(cls, bookmark_id: int, user_id: int) -> Tuple[bool, Optional[str]]:
        """Delete a bookmark"""
        bookmark = Bookmark.query.get(bookmark_id)

        if not bookmark:
            return False, "Закладка не найдена"

        if bookmark.user_id != user_id:
            return False, "Нет доступа к этой закладке"

        db.session.delete(bookmark)
        db.session.commit()
        return True, None
