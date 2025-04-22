from flask import Blueprint, jsonify
from flask_login import current_user
from sqlalchemy import func

from app.api.auth import api_login_required
from app.books.models import Book
from app.utils.db import db

api_books = Blueprint('api_books', __name__)


@api_books.route('/books', methods=['GET'])
@api_login_required
def get_books():
    books_query = db.select(Book)
    books = db.session.execute(books_query).scalars().all()

    book_list = [{
        'id': book.id,
        'title': book.title,
        'total_words': book.total_words,
        'unique_words': book.unique_words,
        'scrape_date': book.scrape_date.isoformat() if book.scrape_date else None
    } for book in books]

    return jsonify({'books': book_list})


@api_books.route('/books/<int:book_id>', methods=['GET'])
@api_login_required
def get_book(book_id):
    book = Book.query.get_or_404(book_id)

    # Get word stats for this book using the new UserWord model
    from app.utils.db import word_book_link
    from app.words.models import CollectionWords
    from app.study.models import UserWord

    # Получаем статистику слов по статусам
    word_stats_query = db.select(
        UserWord.status,
        func.count().label('count')
    ).join(
        word_book_link,
        UserWord.word_id == word_book_link.c.word_id
    ).where(
        (word_book_link.c.book_id == book_id) &
        (UserWord.user_id == current_user.id)
    ).group_by(
        UserWord.status
    )

    word_stats_result = db.session.execute(word_stats_query).all()

    # Инициализируем словарь с возможными статусами
    word_stats = {
        'new': 0,
        'learning': 0,
        'review': 0,
        'mastered': 0
    }

    # Заполняем статистику по результатам запроса
    for status, count in word_stats_result:
        if status in word_stats:
            word_stats[status] = count

    # Считаем слова без статуса как "new"
    new_words_query = db.select(func.count()).select_from(
        word_book_link.join(
            CollectionWords,
            word_book_link.c.word_id == CollectionWords.id
        ).outerjoin(
            UserWord,
            (word_book_link.c.word_id == UserWord.word_id) &
            (UserWord.user_id == current_user.id)
        )
    ).where(
        (word_book_link.c.book_id == book_id) &
        (UserWord.id == None)
    )

    new_words_count = db.session.execute(new_words_query).scalar() or 0
    word_stats['new'] += new_words_count

    return jsonify({
        'id': book.id,
        'title': book.title,
        'total_words': book.total_words,
        'unique_words': book.unique_words,
        'scrape_date': book.scrape_date.isoformat() if book.scrape_date else None,
        'word_stats': word_stats
    })
