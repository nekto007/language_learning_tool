# app/books/helpers.py

from sqlalchemy import desc
from app.books.models import Book, Chapter, UserChapterProgress
from app.utils.db import db

def get_user_reading_progress(user_id):
    """Get user's current reading progress across all books"""
    # Get the most recently read chapter
    latest_progress = db.session.query(
        UserChapterProgress, Chapter, Book
    ).join(
        Chapter, UserChapterProgress.chapter_id == Chapter.id
    ).join(
        Book, Chapter.book_id == Book.id
    ).filter(
        UserChapterProgress.user_id == user_id
    ).order_by(
        desc(UserChapterProgress.updated_at)
    ).first()
    
    if not latest_progress:
        return None
    
    progress, chapter, book = latest_progress
    
    # Get total chapters for the book
    total_chapters = Chapter.query.filter_by(book_id=book.id).count()
    
    # Calculate overall book progress
    chapters_before = Chapter.query.filter_by(
        book_id=book.id
    ).filter(
        Chapter.chap_num < chapter.chap_num
    ).count()
    
    # Overall progress = (completed chapters + current chapter progress) / total chapters
    overall_progress = (chapters_before + progress.offset_pct) / total_chapters if total_chapters > 0 else 0
    
    return {
        'book': book,
        'current_chapter': chapter,
        'chapter_progress': progress.offset_pct,
        'overall_progress': overall_progress,
        'total_chapters': total_chapters,
        'last_read': progress.updated_at
    }

def get_recent_books(user_id, limit=5):
    """Get recently read books for a user"""
    recent_books = db.session.query(
        Book, 
        db.func.max(UserChapterProgress.updated_at).label('last_read')
    ).join(
        Chapter, Book.id == Chapter.book_id
    ).join(
        UserChapterProgress, Chapter.id == UserChapterProgress.chapter_id
    ).filter(
        UserChapterProgress.user_id == user_id
    ).group_by(
        Book.id
    ).order_by(
        desc('last_read')
    ).limit(limit).all()
    
    results = []
    for book, last_read in recent_books:
        # Get current reading position
        current_progress = db.session.query(
            UserChapterProgress, Chapter
        ).join(
            Chapter, UserChapterProgress.chapter_id == Chapter.id
        ).filter(
            Chapter.book_id == book.id,
            UserChapterProgress.user_id == user_id
        ).order_by(
            desc(UserChapterProgress.updated_at)
        ).first()
        
        if current_progress:
            progress, chapter = current_progress
            results.append({
                'book': book,
                'current_chapter': chapter,
                'last_read': last_read
            })
    
    return results