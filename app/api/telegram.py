"""API endpoints for Telegram bot integration"""

import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import desc

from app import csrf
from app.auth.models import User
from app.books.models import Chapter, Book, UserChapterProgress
from app.curriculum.models import Lessons, LessonProgress
from app.telegram.decorators import telegram_auth_required
from app.utils.db import db

api_telegram = Blueprint('api_telegram', __name__)


@api_telegram.route('/telegram/latest-grammar', methods=['GET'])
@csrf.exempt
@telegram_auth_required('read')
def get_latest_grammar(token, user):
    """Rate limiting applied: 20 per minute"""
    from app import limiter
    limiter.limit("20 per minute")(lambda: None)()
    """
    Get the latest grammar lesson the user studied

    Returns the most recently studied grammar lesson with its content
    """
    try:
        # Find the latest grammar lesson that the user has started or completed
        latest_progress = (
            LessonProgress.query
            .join(Lessons)
            .filter(
                LessonProgress.user_id == user.id,
                Lessons.type == 'grammar',
                LessonProgress.status.in_(['in_progress', 'completed'])
            )
            .order_by(desc(LessonProgress.last_activity))
            .first()
        )

        if not latest_progress:
            return jsonify({
                'success': False,
                'error': 'No grammar lessons found',
                'status_code': 404
            }), 404

        lesson = latest_progress.lesson
        module = lesson.module
        level = module.level

        # Format the response
        response_data = {
            'success': True,
            'lesson': {
                'id': lesson.id,
                'title': lesson.title,
                'description': lesson.description,
                'content': lesson.content,
                'type': lesson.type,
                'number': lesson.number,
                'module': {
                    'id': module.id,
                    'title': module.title,
                    'number': module.number,
                    'level': {
                        'code': level.code,
                        'name': level.name
                    }
                },
                'progress': {
                    'status': latest_progress.status,
                    'score': latest_progress.rounded_score,
                    'last_activity': latest_progress.last_activity.isoformat() if latest_progress.last_activity else None,
                    'completed_at': latest_progress.completed_at.isoformat() if latest_progress.completed_at else None
                }
            }
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/book-excerpt', methods=['GET'])
@csrf.exempt
@telegram_auth_required('read')
def get_book_excerpt(token, user):
    """Rate limiting applied: 30 per minute"""
    from app import limiter
    limiter.limit("30 per minute")(lambda: None)()
    """
    Get a random excerpt from books

    Query parameters:
    - book_id (optional): Specific book ID
    - length (optional): Length of excerpt in characters (default: 500, max: 2000)
    - min_length (optional): Minimum length of chapter text to select from (default: 1000)

    Returns a random excerpt from a book chapter
    """
    try:
        book_id = request.args.get('book_id', type=int)
        excerpt_length = min(int(request.args.get('length', 500)), 2000)
        min_chapter_length = int(request.args.get('min_length', 1000))

        # Build query for chapters
        query = Chapter.query

        if book_id:
            # Get specific book
            query = query.filter(Chapter.book_id == book_id)

        # Filter chapters that are long enough to provide meaningful excerpts
        query = query.filter(Chapter.words >= min_chapter_length // 5)  # Roughly 5 chars per word

        # Get all matching chapters
        chapters = query.all()

        if not chapters:
            return jsonify({
                'success': False,
                'error': 'No suitable chapters found',
                'status_code': 404
            }), 404

        # Select a random chapter
        chapter = random.choice(chapters)

        # Get the text
        text = chapter.text_raw

        if len(text) <= excerpt_length:
            # If chapter is shorter than requested length, return the whole chapter
            excerpt = text
            start_pos = 0
        else:
            # Get a random position that leaves enough room for the excerpt
            max_start = len(text) - excerpt_length
            start_pos = random.randint(0, max_start)

            # Try to start at a sentence boundary
            # Look for '. ' after the random position
            sentence_start = text.find('. ', start_pos)
            if sentence_start != -1 and sentence_start - start_pos < 200:
                start_pos = sentence_start + 2

            # Extract excerpt
            end_pos = start_pos + excerpt_length
            excerpt = text[start_pos:end_pos]

            # Try to end at a sentence boundary
            last_period = excerpt.rfind('. ')
            if last_period > excerpt_length * 0.7:  # Only if we're at least 70% through
                excerpt = excerpt[:last_period + 1]

        # Prepare response
        response_data = {
            'success': True,
            'excerpt': {
                'text': excerpt,
                'length': len(excerpt),
                'start_position': start_pos,
                'chapter': {
                    'id': chapter.id,
                    'number': chapter.chap_num,
                    'title': chapter.title,
                    'total_words': chapter.words
                },
                'book': {
                    'id': chapter.book.id,
                    'title': chapter.book.title,
                    'author': chapter.book.author,
                    'level': chapter.book.level,
                    'cover_image': chapter.book.cover_image
                }
            }
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/generate-token', methods=['POST'])
@csrf.exempt
def generate_token():
    """
    Generate a new Telegram API token for a user

    Requires username and password for authentication
    Returns the new token with expiration and scope

    Rate limits:
    - 3 per hour per IP (token generation is rare)
    - 2 per day per username (prevent token spam)

    SECURITY: Uses new TelegramToken model with:
    - 90-day expiration
    - Scoped permissions (read, write)
    - Revocation support
    """
    from app import limiter
    from app.telegram.models import TelegramToken
    from app.utils.rate_limit_helpers import get_username_key

    @limiter.limit("3 per hour")
    @limiter.limit("2 per day", key_func=lambda: get_username_key())
    def _generate_token_impl():
        try:
            if not request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Invalid JSON format',
                    'status_code': 400
                }), 400

            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
            scope = data.get('scope', 'read,write')  # Default: read + write
            device_name = data.get('device_name', 'Telegram Bot')

            if not username or not password:
                return jsonify({
                    'success': False,
                    'error': 'Missing username or password',
                    'status_code': 400
                }), 400

            # Authenticate user
            user = User.query.filter_by(username=username).first()
            if not user or not user.check_password(password):
                return jsonify({
                    'success': False,
                    'error': 'Invalid credentials',
                    'status_code': 401
                }), 401

            # Validate scope
            valid_scopes = {'read', 'write', 'admin'}
            requested_scopes = set(scope.split(','))
            if not requested_scopes.issubset(valid_scopes):
                return jsonify({
                    'success': False,
                    'error': f'Invalid scope. Valid scopes: {", ".join(valid_scopes)}',
                    'status_code': 400
                }), 400

            # Create new token with proper security
            user_agent = request.headers.get('User-Agent', 'Unknown')
            token_obj = TelegramToken.create_token(
                user_id=user.id,
                scope=scope,
                expires_in_days=90,
                device_name=device_name,
                user_agent=user_agent
            )

            return jsonify({
                'success': True,
                'token': token_obj.token,
                'token_id': token_obj.id,
                'username': user.username,
                'user_id': user.id,
                'scope': token_obj.scope,
                'expires_at': token_obj.expires_at.isoformat(),
                'message': 'Save this token securely! It won\'t be shown again.'
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e),
                'status_code': 500
            }), 500

    return _generate_token_impl()


@api_telegram.route('/telegram/books', methods=['GET'])
@csrf.exempt
@telegram_auth_required('read')
def get_books(token, user):
    """
    Get list of available books

    Returns all books in the database
    """
    try:
        books = Book.query.all()

        books_data = [{
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'level': book.level,
            'chapters_count': book.chapters_cnt,
            'total_words': book.words_total,
            'unique_words': book.unique_words,
            'summary': book.summary,
            'cover_image': book.cover_image
        } for book in books]

        return jsonify({
            'success': True,
            'books': books_data,
            'count': len(books_data)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/read-next', methods=['GET'])
@csrf.exempt
@telegram_auth_required('read')
def read_next(token, user):
    """Rate limiting applied: 60 per minute"""
    from app import limiter
    limiter.limit("60 per minute")(lambda: None)()
    """
    Get next fragment of a book for sequential reading

    Query parameters:
    - book_id (required): Book ID to read
    - length (optional): Length of fragment in characters (default: 1000, max: 3000)

    Returns next fragment based on user's reading progress
    Automatically tracks progress and moves to next chapter when current one is finished
    """
    try:
        book_id = request.args.get('book_id', type=int)
        fragment_length = min(int(request.args.get('length', 1000)), 3000)

        if not book_id:
            return jsonify({
                'success': False,
                'error': 'book_id parameter is required',
                'status_code': 400
            }), 400

        # Get book and verify it exists
        book = Book.query.get(book_id)
        if not book:
            return jsonify({
                'success': False,
                'error': 'Book not found',
                'status_code': 404
            }), 404

        # Get all chapters for this book, ordered by chapter number
        chapters = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.chap_num).all()

        if not chapters:
            return jsonify({
                'success': False,
                'error': 'No chapters found for this book',
                'status_code': 404
            }), 404

        # Find current reading position
        current_progress = (
            UserChapterProgress.query
            .filter_by(user_id=user.id)
            .join(Chapter)
            .filter(Chapter.book_id == book_id)
            .order_by(desc(UserChapterProgress.updated_at))
            .first()
        )

        # Determine current chapter and position
        if current_progress:
            current_chapter = current_progress.chapter
            current_offset_pct = current_progress.offset_pct

            # If current chapter is finished, move to next chapter
            if current_offset_pct >= 1.0:
                current_chapter_index = next(
                    (i for i, ch in enumerate(chapters) if ch.id == current_chapter.id),
                    None
                )

                if current_chapter_index is not None and current_chapter_index + 1 < len(chapters):
                    # Move to next chapter
                    current_chapter = chapters[current_chapter_index + 1]
                    current_offset_pct = 0.0
                else:
                    # Book is finished
                    return jsonify({
                        'success': True,
                        'finished': True,
                        'message': 'You have finished reading this book!',
                        'book': {
                            'id': book.id,
                            'title': book.title,
                            'author': book.author
                        }
                    })
        else:
            # Start from the beginning
            current_chapter = chapters[0]
            current_offset_pct = 0.0

        # Get the text and calculate position
        text = current_chapter.text_raw
        text_length = len(text)
        start_pos = int(text_length * current_offset_pct)

        # Extract fragment
        end_pos = min(start_pos + fragment_length, text_length)
        fragment = text[start_pos:end_pos]

        # Try to end at sentence boundary if not at the end of chapter
        if end_pos < text_length:
            last_period = fragment.rfind('. ')
            if last_period > len(fragment) * 0.6:  # At least 60% through
                fragment = fragment[:last_period + 1]
                end_pos = start_pos + last_period + 1

        # Calculate new offset percentage
        new_offset_pct = min(end_pos / text_length, 1.0)

        # Update or create progress record
        progress = UserChapterProgress.query.filter_by(
            user_id=user.id,
            chapter_id=current_chapter.id
        ).first()

        if progress:
            progress.offset_pct = new_offset_pct
            progress.updated_at = datetime.now(timezone.utc)
        else:
            progress = UserChapterProgress(
                user_id=user.id,
                chapter_id=current_chapter.id,
                offset_pct=new_offset_pct,
                updated_at=datetime.now(timezone.utc)
            )
            db.session.add(progress)

        db.session.commit()

        # Calculate overall book progress
        chapter_index = next((i for i, ch in enumerate(chapters) if ch.id == current_chapter.id), 0)
        overall_progress = ((chapter_index + new_offset_pct) / len(chapters)) * 100

        # Prepare response
        response_data = {
            'success': True,
            'finished': False,
            'fragment': {
                'text': fragment,
                'length': len(fragment),
                'chapter': {
                    'id': current_chapter.id,
                    'number': current_chapter.chap_num,
                    'title': current_chapter.title,
                    'progress_pct': round(new_offset_pct * 100, 1),
                    'is_chapter_finished': new_offset_pct >= 1.0
                },
                'book': {
                    'id': book.id,
                    'title': book.title,
                    'author': book.author,
                    'total_chapters': len(chapters),
                    'current_chapter': chapter_index + 1,
                    'overall_progress_pct': round(overall_progress, 1)
                }
            }
        }

        return jsonify(response_data)

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/reading-progress', methods=['GET'])
@csrf.exempt
@telegram_auth_required('read')
def get_reading_progress(token, user):
    """
    Get reading progress for all books or a specific book

    Query parameters:
    - book_id (optional): Specific book ID to get progress for

    Returns user's reading progress
    """
    try:
        book_id = request.args.get('book_id', type=int)

        if book_id:
            # Get progress for specific book
            book = Book.query.get(book_id)
            if not book:
                return jsonify({
                    'success': False,
                    'error': 'Book not found',
                    'status_code': 404
                }), 404

            # Get all chapters
            chapters = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.chap_num).all()
            total_chapters = len(chapters)

            # Get user's progress for this book
            progress_records = (
                UserChapterProgress.query
                .filter_by(user_id=user.id)
                .join(Chapter)
                .filter(Chapter.book_id == book_id)
                .all()
            )

            # Calculate progress
            if progress_records:
                # Find latest chapter being read
                latest_progress = max(progress_records, key=lambda p: p.updated_at)
                current_chapter_num = latest_progress.chapter.chap_num
                current_chapter_offset = latest_progress.offset_pct

                # Calculate overall progress
                chapters_completed = len([p for p in progress_records if p.offset_pct >= 1.0])
                overall_progress = ((chapters_completed + (current_chapter_offset if current_chapter_offset < 1.0 else 0)) / total_chapters) * 100

                return jsonify({
                    'success': True,
                    'book': {
                        'id': book.id,
                        'title': book.title,
                        'author': book.author,
                        'total_chapters': total_chapters
                    },
                    'progress': {
                        'current_chapter': current_chapter_num,
                        'current_chapter_progress_pct': round(current_chapter_offset * 100, 1),
                        'chapters_completed': chapters_completed,
                        'overall_progress_pct': round(overall_progress, 1),
                        'last_read': latest_progress.updated_at.isoformat()
                    }
                })
            else:
                # No progress yet
                return jsonify({
                    'success': True,
                    'book': {
                        'id': book.id,
                        'title': book.title,
                        'author': book.author,
                        'total_chapters': total_chapters
                    },
                    'progress': {
                        'current_chapter': 0,
                        'current_chapter_progress_pct': 0,
                        'chapters_completed': 0,
                        'overall_progress_pct': 0,
                        'last_read': None
                    }
                })

        else:
            # Get progress for all books
            progress_records = (
                UserChapterProgress.query
                .filter_by(user_id=user.id)
                .join(Chapter)
                .join(Book)
                .all()
            )

            # Group by book
            books_progress = {}
            for progress in progress_records:
                book = progress.chapter.book
                if book.id not in books_progress:
                    total_chapters = Chapter.query.filter_by(book_id=book.id).count()
                    books_progress[book.id] = {
                        'book': {
                            'id': book.id,
                            'title': book.title,
                            'author': book.author,
                            'total_chapters': total_chapters
                        },
                        'chapters_read': [],
                        'last_updated': progress.updated_at
                    }

                books_progress[book.id]['chapters_read'].append({
                    'chapter_num': progress.chapter.chap_num,
                    'progress_pct': round(progress.offset_pct * 100, 1)
                })

                if progress.updated_at > books_progress[book.id]['last_updated']:
                    books_progress[book.id]['last_updated'] = progress.updated_at

            # Calculate overall progress for each book
            result = []
            for book_id, data in books_progress.items():
                chapters_completed = len([ch for ch in data['chapters_read'] if ch['progress_pct'] >= 100])
                overall_progress = (chapters_completed / data['book']['total_chapters']) * 100

                result.append({
                    'book': data['book'],
                    'progress': {
                        'chapters_completed': chapters_completed,
                        'overall_progress_pct': round(overall_progress, 1),
                        'last_read': data['last_updated'].isoformat()
                    }
                })

            return jsonify({
                'success': True,
                'books': result,
                'count': len(result)
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/start-book', methods=['POST'])
@csrf.exempt
@telegram_auth_required('write')
def start_book(token, user):
    """
    Start reading a book from the beginning (reset progress)

    Body:
    - book_id (required): Book ID to start reading

    Returns confirmation
    """
    try:
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Invalid JSON format',
                'status_code': 400
            }), 400

        data = request.get_json()
        book_id = data.get('book_id')

        if not book_id:
            return jsonify({
                'success': False,
                'error': 'book_id is required',
                'status_code': 400
            }), 400

        # Verify book exists
        book = Book.query.get(book_id)
        if not book:
            return jsonify({
                'success': False,
                'error': 'Book not found',
                'status_code': 404
            }), 404

        # Delete all existing progress for this book
        # First get all chapter IDs for this book
        chapter_ids = [ch.id for ch in Chapter.query.filter_by(book_id=book_id).all()]

        # Delete progress for these chapters
        if chapter_ids:
            UserChapterProgress.query.filter(
                UserChapterProgress.user_id == user.id,
                UserChapterProgress.chapter_id.in_(chapter_ids)
            ).delete(synchronize_session=False)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Started reading "{book.title}"',
            'book': {
                'id': book.id,
                'title': book.title,
                'author': book.author,
                'chapters_count': book.chapters_cnt
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500
