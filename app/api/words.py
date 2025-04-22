from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy import func, or_

from app.api.auth import api_login_required
from app.utils.db import db
from app.words.models import CollectionWords

api_words = Blueprint('api_words', __name__)


@api_words.route('/words', methods=['GET'])
@api_login_required
def get_words():
    # Get query parameters
    status = request.args.get('status', type=int)
    book_id = request.args.get('book_id', type=int)
    letter = request.args.get('letter')
    search = request.args.get('search')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Base query
    query = db.select(CollectionWords)

    # Apply filters
    if status is not None:
        from app.study.models import UserWord
        from app.utils.db import status_to_string

        status_str = status_to_string(status)

        # Используем только новую систему
        new_system_words = db.session.query(UserWord.word_id).filter(
            UserWord.user_id == current_user.id,
            UserWord.status == status_str
        ).subquery()

        query = query.filter(CollectionWords.id.in_(new_system_words))

    if book_id is not None:
        from app.utils.db import word_book_link
        query = query.join(
            word_book_link,
            CollectionWords.id == word_book_link.c.word_id
        ).where(word_book_link.c.book_id == book_id)

    if letter:
        query = query.where(CollectionWords.english_word.like(f"{letter}%"))

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                CollectionWords.english_word.like(search_term),
                CollectionWords.russian_word.like(search_term)
            )
        )

    # Get total count
    count_query = db.select(func.count()).select_from(query.subquery())
    total = db.session.execute(count_query).scalar()

    # Apply pagination
    query = query.limit(per_page).offset((page - 1) * per_page)

    # Execute query
    words = db.session.execute(query).scalars().all()

    # Calculate total pages
    total_pages = (total + per_page - 1) // per_page

    # Format response
    word_list = []
    for word in words:
        word_status = current_user.get_word_status(word.id)

        word_list.append({
            'id': word.id,
            'english_word': word.english_word,
            'russian_word': word.russian_word,
            'status': word_status,
            'get_download': word.get_download,
            'sentences': word.sentences
        })

    return jsonify({
        'words': word_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@api_words.route('/words/<int:word_id>', methods=['GET'])
@api_login_required
def get_word(word_id):
    word = CollectionWords.query.get_or_404(word_id)

    # Get books containing this word
    from app.utils.db import word_book_link
    from app.books.models import Book

    books_query = db.select(Book, word_book_link.c.frequency) \
        .join(word_book_link, Book.id == word_book_link.c.book_id) \
        .where(word_book_link.c.word_id == word_id)

    books_result = db.session.execute(books_query).all()

    books = [{
        'id': book.id,
        'title': book.title,
        'frequency': frequency
    } for book, frequency in books_result]

    # Get user's status for this word
    status = current_user.get_word_status(word_id)

    return jsonify({
        'id': word.id,
        'english_word': word.english_word,
        'russian_word': word.russian_word,
        'listening': word.listening,
        'sentences': word.sentences,
        'level': word.level,
        'brown': word.brown,
        'get_download': word.get_download,
        'status': status,
        'books': books
    })


@api_words.route('/update-word-status', methods=['POST'])
@api_login_required
def update_word_status():
    if not request.is_json:
        return jsonify({
            'success': False,
            'error': 'Invalid JSON format',
            'status_code': 400
        }), 400

    data = request.get_json()
    word_id = data.get('word_id')
    status = data.get('status')

    if not word_id or status is None:
        return jsonify({
            'success': False,
            'error': 'Missing word_id or status',
            'status_code': 400
        }), 400

    word = CollectionWords.query.get(word_id)
    if not word:
        return jsonify({
            'success': False,
            'error': 'Word not found',
            'status_code': 404
        }), 404

    try:
        # Уже используется метод User.set_word_status, который мы обновили
        current_user.set_word_status(word_id, status)
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_words.route('/batch-update-status', methods=['POST'])
@api_login_required
def batch_update_status():
    if not request.is_json:
        return jsonify({
            'success': False,
            'error': 'Invalid JSON format',
            'status_code': 400
        }), 400

    data = request.get_json()
    word_ids = data.get('word_ids', [])
    status = data.get('status')

    if not word_ids or status is None:
        return jsonify({
            'success': False,
            'error': 'Missing word_ids or status',
            'status_code': 400
        }), 400

    try:
        # Verify all words exist
        words = CollectionWords.query.filter(CollectionWords.id.in_(word_ids)).all()
        existing_ids = [word.id for word in words]

        if len(existing_ids) != len(word_ids):
            missing_ids = set(word_ids) - set(existing_ids)
            return jsonify({
                'success': False,
                'error': f'Some words not found: {missing_ids}',
                'status_code': 404
            }), 404

        # Update statuses
        for word_id in word_ids:
            current_user.set_word_status(word_id, status)

        return jsonify({
            'success': True,
            'updated_count': len(word_ids),
            'total_count': len(word_ids)
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500
