"""API endpoints for Telegram bot integration"""

import random
import uuid
from datetime import datetime, date, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import desc, func

from app import csrf
from app.auth.models import User
from app.books.models import Chapter, Book, UserChapterProgress
from app.curriculum.models import Module, Lessons, LessonProgress, CEFRLevel
from app.telegram.decorators import telegram_auth_required
from app.telegram.models import TelegramUser, BotDailyProgress, LinkCode
from app.words.models import CollectionWords, Collection
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


# ============================================================================
# Telegram Bot API Endpoints
# ============================================================================

@api_telegram.route('/telegram/bot/register', methods=['POST'])
@csrf.exempt
def bot_register():
    """
    Register a new Telegram user or update existing one.

    Called by the bot when user sends /start.

    Body:
    - telegram_id (required): Telegram user ID
    - username (optional): Telegram username
    - first_name (optional): User's first name
    - last_name (optional): User's last name
    - language_code (optional): User's language preference

    Returns:
        TelegramUser data with registration status
    """
    from app import limiter

    @limiter.limit("30 per minute")
    def _register_impl():
        try:
            if not request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Invalid JSON format',
                    'status_code': 400
                }), 400

            data = request.get_json()
            telegram_id = data.get('telegram_id')

            if not telegram_id:
                return jsonify({
                    'success': False,
                    'error': 'telegram_id is required',
                    'status_code': 400
                }), 400

            # Get or create TelegramUser
            tg_user = TelegramUser.get_or_create(
                telegram_id=telegram_id,
                username=data.get('username'),
                first_name=data.get('first_name'),
                last_name=data.get('last_name'),
                language_code=data.get('language_code', 'ru')
            )

            is_new = tg_user.created_at.date() == date.today()
            is_linked = tg_user.user_id is not None

            return jsonify({
                'success': True,
                'is_new': is_new,
                'is_linked': is_linked,
                'user': {
                    'id': tg_user.id,
                    'telegram_id': tg_user.telegram_id,
                    'username': tg_user.username,
                    'first_name': tg_user.first_name,
                    'streak_days': tg_user.streak_days,
                    'total_xp': tg_user.total_xp,
                    'current_module_id': tg_user.current_module_id,
                    'current_day': tg_user.current_day,
                    'reminders_enabled': tg_user.reminders_enabled,
                    'reminder_time': tg_user.reminder_time.strftime('%H:%M') if tg_user.reminder_time else '09:00'
                }
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e),
                'status_code': 500
            }), 500

    return _register_impl()


@api_telegram.route('/telegram/bot/link-account', methods=['POST'])
@csrf.exempt
def bot_link_account():
    """
    Link Telegram account to website user via link code.

    Body:
    - telegram_id (required): Telegram user ID
    - link_code (required): Code generated on website

    Returns:
        Success status and linked user info
    """
    from app import limiter

    @limiter.limit("10 per minute")
    def _link_impl():
        try:
            if not request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Invalid JSON format',
                    'status_code': 400
                }), 400

            data = request.get_json()
            telegram_id = data.get('telegram_id')
            code = data.get('link_code')

            if not telegram_id or not code:
                return jsonify({
                    'success': False,
                    'error': 'telegram_id and link_code are required',
                    'status_code': 400
                }), 400

            # Get TelegramUser
            tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
            if not tg_user:
                return jsonify({
                    'success': False,
                    'error': 'Telegram user not registered. Use /start first.',
                    'status_code': 404
                }), 404

            if tg_user.user_id:
                return jsonify({
                    'success': False,
                    'error': 'Account already linked',
                    'status_code': 400
                }), 400

            # Verify link code
            link_code = LinkCode.get_valid_code(code)
            if not link_code:
                return jsonify({
                    'success': False,
                    'error': 'Invalid or expired link code',
                    'status_code': 400
                }), 400

            # Link accounts
            tg_user.link_account(link_code.user_id)
            link_code.use()

            user = User.query.get(link_code.user_id)

            return jsonify({
                'success': True,
                'message': 'Account linked successfully',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'telegram_user_id': tg_user.id
                }
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e),
                'status_code': 500
            }), 500

    return _link_impl()


@api_telegram.route('/telegram/bot/generate-link-code', methods=['POST'])
@csrf.exempt
@telegram_auth_required('write')
def generate_link_code(token, user):
    """
    Generate a link code for connecting Telegram account.

    Called from website when user wants to link their Telegram.

    Returns:
        Link code valid for 15 minutes
    """
    try:
        link_code = LinkCode.generate_code(user.id, expires_in_minutes=15)

        return jsonify({
            'success': True,
            'code': link_code.code,
            'expires_at': link_code.expires_at.isoformat(),
            'message': 'Enter this code in Telegram bot using /link command'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/daily-plan/<int:telegram_id>', methods=['GET'])
@csrf.exempt
def get_daily_plan(telegram_id):
    """
    Get today's learning plan for Telegram user.

    Returns only lessons for the current day (not all 12).

    Day structure (12 lessons → 6 days):
    - Day 1: vocabulary, flashcards
    - Day 2: grammar, quiz
    - Day 3: reading, listening_quiz
    - Day 4: dialogue_completion, ordering_quiz
    - Day 5: flashcards (review), translation_quiz
    - Day 6: listening_immersion, final_test

    Returns:
        Module info, tasks for current day, streak, XP
    """
    try:
        tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
        if not tg_user:
            return jsonify({
                'success': False,
                'error': 'User not found',
                'status_code': 404
            }), 404

        # Get or assign current module
        if not tg_user.current_module_id:
            # Assign first module (A1 Level, Module 1)
            first_level = CEFRLevel.query.filter_by(code='A1').first()
            if first_level:
                first_module = Module.query.filter_by(level_id=first_level.id, number=1).first()
                if first_module:
                    tg_user.current_module_id = first_module.id
                    db.session.commit()

        module = tg_user.current_module
        module_data = None

        if module:
            module_data = {
                'id': module.id,
                'title': module.title,
                'number': module.number,
                'level': module.level.code if module.level else None,
                'level_name': module.level.name if module.level else None
            }

        # Get today's progress
        today_progress = tg_user.get_today_progress()

        # Get tasks for current day (using new day-based structure)
        tasks = today_progress.get_tasks_for_day()

        return jsonify({
            'success': True,
            'module': module_data,
            'day': tg_user.current_day,
            'total_days': 6,
            'tasks': tasks,
            'streak': tg_user.streak_days,
            'xp_today': today_progress.xp_earned,
            'xp_total': tg_user.total_xp,
            'progress_percent': today_progress.progress_percent,
            'is_completed': today_progress.is_completed
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/vocabulary/<int:module_id>', methods=['GET'])
@csrf.exempt
def get_vocabulary(module_id):
    """
    Get vocabulary cards for a module.

    Query params:
    - limit (optional): Max cards to return (default: 10)

    Returns:
        Vocabulary cards with translations and audio
    """
    try:
        module = Module.query.get(module_id)
        if not module:
            return jsonify({
                'success': False,
                'error': 'Module not found',
                'status_code': 404
            }), 404

        limit = request.args.get('limit', 10, type=int)

        # Find vocabulary lessons in this module
        vocab_lessons = Lessons.query.filter_by(
            module_id=module_id,
            type='vocabulary'
        ).all()

        cards = []

        for lesson in vocab_lessons:
            if lesson.collection_id:
                # Get words from collection
                collection = Collection.query.get(lesson.collection_id)
                if collection:
                    words = collection.words[:limit - len(cards)] if collection.words else []
                    for word in words:
                        cards.append({
                            'id': word.id,
                            'front': word.english_word,
                            'back': word.russian_word,
                            'audio_url': f'/static/audio/{word.listening}' if word.listening else None,
                            'example': word.sentences.split('|')[0] if word.sentences else None,
                            'level': word.level
                        })
                        if len(cards) >= limit:
                            break

            # Also check lesson content for embedded vocabulary
            if lesson.content and isinstance(lesson.content, dict):
                # Check both 'vocabulary' and 'words' keys (data may use either)
                vocab_items = lesson.content.get('vocabulary', []) or lesson.content.get('words', [])
                for item in vocab_items:
                    if len(cards) >= limit:
                        break
                    cards.append({
                        'id': item.get('id', f"lesson_{lesson.id}_{len(cards)}"),
                        'front': item.get('word', item.get('english', item.get('front', ''))),
                        'back': item.get('translation', item.get('russian', item.get('back', ''))),
                        'audio_url': item.get('audio'),
                        'example': item.get('example', item.get('usage', '')),
                        'pronunciation': item.get('pronunciation', ''),
                        'level': module.level.code if module.level else None
                    })

            if len(cards) >= limit:
                break

        return jsonify({
            'success': True,
            'module_id': module_id,
            'module_title': module.title,
            'cards': cards,
            'count': len(cards)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


# Store quiz sessions in memory (could use Redis for production)
_quiz_sessions = {}


@api_telegram.route('/telegram/bot/quiz/<int:module_id>', methods=['GET'])
@csrf.exempt
def get_quiz(module_id):
    """
    Generate a quiz for a module.

    Query params:
    - count (optional): Number of questions (default: 5)
    - telegram_id (required): Telegram user ID for session tracking

    Returns:
        Quiz questions with options
    """
    try:
        module = Module.query.get(module_id)
        if not module:
            return jsonify({
                'success': False,
                'error': 'Module not found',
                'status_code': 404
            }), 404

        telegram_id = request.args.get('telegram_id', type=int)
        if not telegram_id:
            return jsonify({
                'success': False,
                'error': 'telegram_id is required',
                'status_code': 400
            }), 400

        count = request.args.get('count', 5, type=int)

        # Find quiz lessons in this module
        quiz_lessons = Lessons.query.filter_by(
            module_id=module_id,
            type='quiz'
        ).all()

        questions = []

        for lesson in quiz_lessons:
            if lesson.content and isinstance(lesson.content, dict):
                quiz_items = lesson.content.get('questions', [])
                for item in quiz_items:
                    if len(questions) >= count:
                        break
                    questions.append({
                        'id': len(questions) + 1,
                        'type': item.get('type', 'multiple_choice'),
                        'question': item.get('question', item.get('text', '')),
                        'options': item.get('options', []),
                        'correct': item.get('correct', item.get('answer', ''))
                    })

            if len(questions) >= count:
                break

        # If not enough questions from quiz lessons, generate from vocabulary
        if len(questions) < count:
            vocab_lessons = Lessons.query.filter_by(
                module_id=module_id,
                type='vocabulary'
            ).all()

            for lesson in vocab_lessons:
                if lesson.collection_id:
                    collection = Collection.query.get(lesson.collection_id)
                    if collection and collection.words:
                        words = list(collection.words)
                        random.shuffle(words)

                        for word in words:
                            if len(questions) >= count:
                                break

                            # Generate translation question
                            other_words = [w for w in words if w.id != word.id][:3]
                            options = [word.russian_word] + [w.russian_word for w in other_words]
                            random.shuffle(options)

                            questions.append({
                                'id': len(questions) + 1,
                                'type': 'translation',
                                'question': f'Переведите: "{word.english_word}"',
                                'options': options,
                                'correct': word.russian_word
                            })

                if len(questions) >= count:
                    break

        # Create quiz session
        quiz_id = str(uuid.uuid4())
        _quiz_sessions[quiz_id] = {
            'telegram_id': telegram_id,
            'module_id': module_id,
            'questions': questions,
            'created_at': datetime.now(timezone.utc)
        }

        # Remove correct answers from response
        questions_for_response = []
        for q in questions:
            questions_for_response.append({
                'id': q['id'],
                'type': q['type'],
                'question': q['question'],
                'options': q['options']
            })

        return jsonify({
            'success': True,
            'quiz_id': quiz_id,
            'module_id': module_id,
            'module_title': module.title,
            'questions': questions_for_response,
            'count': len(questions_for_response)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/quiz/submit', methods=['POST'])
@csrf.exempt
def submit_quiz():
    """
    Submit quiz answers and get results.

    Body:
    - telegram_id (required): Telegram user ID
    - quiz_id (required): Quiz session ID
    - answers (required): Dict of question_id -> answer

    Returns:
        Score, correct answers count, XP earned
    """
    from app import limiter

    @limiter.limit("20 per minute")
    def _submit_impl():
        try:
            if not request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Invalid JSON format',
                    'status_code': 400
                }), 400

            data = request.get_json()
            telegram_id = data.get('telegram_id')
            quiz_id = data.get('quiz_id')
            answers = data.get('answers', {})

            if not telegram_id or not quiz_id:
                return jsonify({
                    'success': False,
                    'error': 'telegram_id and quiz_id are required',
                    'status_code': 400
                }), 400

            # Get quiz session
            quiz_session = _quiz_sessions.get(quiz_id)
            if not quiz_session:
                return jsonify({
                    'success': False,
                    'error': 'Quiz session not found or expired',
                    'status_code': 404
                }), 404

            if quiz_session['telegram_id'] != telegram_id:
                return jsonify({
                    'success': False,
                    'error': 'Quiz does not belong to this user',
                    'status_code': 403
                }), 403

            # Calculate score
            questions = quiz_session['questions']
            correct = 0
            total = len(questions)
            results = []

            for q in questions:
                q_id = str(q['id'])
                user_answer = answers.get(q_id)
                is_correct = user_answer == q['correct']
                if is_correct:
                    correct += 1

                results.append({
                    'id': q['id'],
                    'question': q['question'],
                    'your_answer': user_answer,
                    'correct_answer': q['correct'],
                    'is_correct': is_correct
                })

            score = round((correct / total) * 100) if total > 0 else 0

            # Update progress
            tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
            xp_earned = 0
            streak_updated = False

            if tg_user:
                today_progress = tg_user.get_today_progress()
                xp_earned = today_progress.complete_quiz(score, correct, total)

                # Update streak if not already updated today
                if tg_user.last_activity_date != date.today():
                    tg_user.update_streak()
                    streak_updated = True

            # Clean up session
            del _quiz_sessions[quiz_id]

            return jsonify({
                'success': True,
                'score': score,
                'correct': correct,
                'total': total,
                'xp_earned': xp_earned,
                'streak_updated': streak_updated,
                'streak_days': tg_user.streak_days if tg_user else 0,
                'results': results
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e),
                'status_code': 500
            }), 500

    return _submit_impl()


@api_telegram.route('/telegram/bot/complete-vocabulary', methods=['POST'])
@csrf.exempt
def complete_vocabulary():
    """
    Mark vocabulary session as completed.

    Body:
    - telegram_id (required): Telegram user ID
    - cards_count (required): Number of cards studied

    Returns:
        XP earned, streak info
    """
    try:
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Invalid JSON format',
                'status_code': 400
            }), 400

        data = request.get_json()
        telegram_id = data.get('telegram_id')
        cards_count = data.get('cards_count', 0)

        if not telegram_id:
            return jsonify({
                'success': False,
                'error': 'telegram_id is required',
                'status_code': 400
            }), 400

        tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
        if not tg_user:
            return jsonify({
                'success': False,
                'error': 'User not found',
                'status_code': 404
            }), 404

        today_progress = tg_user.get_today_progress()
        xp_earned = today_progress.complete_vocabulary(cards_count)

        # Update streak if not already updated today
        streak_updated = False
        if tg_user.last_activity_date != date.today():
            tg_user.update_streak()
            streak_updated = True

        return jsonify({
            'success': True,
            'xp_earned': xp_earned,
            'streak_updated': streak_updated,
            'streak_days': tg_user.streak_days,
            'total_xp': tg_user.total_xp,
            'day_completed': today_progress.is_completed
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/progress/<int:telegram_id>', methods=['GET'])
@csrf.exempt
def get_progress(telegram_id):
    """
    Get user's overall progress and statistics.

    Returns:
        Streak, XP, current module, recent activity
    """
    try:
        tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
        if not tg_user:
            return jsonify({
                'success': False,
                'error': 'User not found',
                'status_code': 404
            }), 404

        # Get recent daily progress
        recent_progress = BotDailyProgress.query.filter_by(
            telegram_user_id=tg_user.id
        ).order_by(desc(BotDailyProgress.date)).limit(7).all()

        recent_days = []
        for p in recent_progress:
            recent_days.append({
                'date': p.date.isoformat(),
                'vocabulary_completed': p.vocabulary_completed,
                'quiz_completed': p.quiz_completed,
                'quiz_score': p.quiz_score,
                'xp_earned': p.xp_earned,
                'is_completed': p.is_completed
            })

        # Current module info
        module_info = None
        if tg_user.current_module:
            module = tg_user.current_module
            module_info = {
                'id': module.id,
                'title': module.title,
                'number': module.number,
                'level': module.level.code if module.level else None,
                'current_day': tg_user.current_day
            }

        # Calculate total days studied
        total_days_studied = BotDailyProgress.query.filter(
            BotDailyProgress.telegram_user_id == tg_user.id,
            BotDailyProgress.vocabulary_completed == True
        ).count()

        return jsonify({
            'success': True,
            'user': {
                'telegram_id': tg_user.telegram_id,
                'username': tg_user.username,
                'first_name': tg_user.first_name,
                'is_linked': tg_user.user_id is not None
            },
            'stats': {
                'streak_days': tg_user.streak_days,
                'total_xp': tg_user.total_xp,
                'total_days_studied': total_days_studied,
                'last_activity': tg_user.last_activity_date.isoformat() if tg_user.last_activity_date else None
            },
            'current_module': module_info,
            'recent_days': recent_days
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/settings/<int:telegram_id>', methods=['GET'])
@csrf.exempt
def get_settings(telegram_id):
    """
    Get user's bot settings.

    Returns:
        Reminder settings, timezone
    """
    try:
        tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
        if not tg_user:
            return jsonify({
                'success': False,
                'error': 'User not found',
                'status_code': 404
            }), 404

        return jsonify({
            'success': True,
            'settings': {
                'reminders_enabled': tg_user.reminders_enabled,
                'reminder_time': tg_user.reminder_time.strftime('%H:%M') if tg_user.reminder_time else '09:00',
                'timezone': tg_user.timezone,
                'language_code': tg_user.language_code
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/settings/<int:telegram_id>', methods=['POST'])
@csrf.exempt
def update_settings(telegram_id):
    """
    Update user's bot settings.

    Body:
    - reminders_enabled (optional): Boolean
    - reminder_time (optional): Time string "HH:MM"
    - timezone (optional): Timezone string

    Returns:
        Updated settings
    """
    try:
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Invalid JSON format',
                'status_code': 400
            }), 400

        tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
        if not tg_user:
            return jsonify({
                'success': False,
                'error': 'User not found',
                'status_code': 404
            }), 404

        data = request.get_json()

        if 'reminders_enabled' in data:
            tg_user.reminders_enabled = bool(data['reminders_enabled'])

        if 'reminder_time' in data:
            try:
                time_obj = datetime.strptime(data['reminder_time'], '%H:%M').time()
                tg_user.reminder_time = time_obj
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': 'Invalid time format. Use HH:MM',
                    'status_code': 400
                }), 400

        if 'timezone' in data:
            tg_user.timezone = data['timezone']

        db.session.commit()

        return jsonify({
            'success': True,
            'settings': {
                'reminders_enabled': tg_user.reminders_enabled,
                'reminder_time': tg_user.reminder_time.strftime('%H:%M') if tg_user.reminder_time else '09:00',
                'timezone': tg_user.timezone,
                'language_code': tg_user.language_code
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/users-for-reminder', methods=['GET'])
@csrf.exempt
def get_users_for_reminder():
    """
    Get users who should receive reminder at current time.

    Query params:
    - hour (required): Current hour (0-23)
    - minute (optional): Current minute (default: 0)

    Returns:
        List of telegram_ids to send reminders to
    """
    try:
        hour = request.args.get('hour', type=int)
        minute = request.args.get('minute', 0, type=int)

        if hour is None:
            return jsonify({
                'success': False,
                'error': 'hour parameter is required',
                'status_code': 400
            }), 400

        # Build time to check
        check_time = datetime.strptime(f'{hour:02d}:{minute:02d}', '%H:%M').time()

        # Get users with reminders enabled at this time
        users = TelegramUser.query.filter(
            TelegramUser.reminders_enabled == True,
            TelegramUser.reminder_time == check_time
        ).all()

        # Filter users who haven't completed today's tasks
        users_to_notify = []
        today = date.today()

        for user in users:
            progress = BotDailyProgress.query.filter_by(
                telegram_user_id=user.id,
                date=today
            ).first()

            # Notify if no progress or incomplete
            if not progress or not progress.is_completed:
                users_to_notify.append({
                    'telegram_id': user.telegram_id,
                    'first_name': user.first_name,
                    'streak_days': user.streak_days,
                    'has_started_today': progress is not None
                })

        return jsonify({
            'success': True,
            'users': users_to_notify,
            'count': len(users_to_notify)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/advance-module', methods=['POST'])
@csrf.exempt
def advance_module():
    """
    Advance user to next day/module.

    Body:
    - telegram_id (required): Telegram user ID

    Returns:
        New module/day info
    """
    try:
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Invalid JSON format',
                'status_code': 400
            }), 400

        data = request.get_json()
        telegram_id = data.get('telegram_id')

        if not telegram_id:
            return jsonify({
                'success': False,
                'error': 'telegram_id is required',
                'status_code': 400
            }), 400

        tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
        if not tg_user:
            return jsonify({
                'success': False,
                'error': 'User not found',
                'status_code': 404
            }), 404

        # Advance day
        if tg_user.current_day < 6:
            tg_user.current_day += 1
            db.session.commit()

            return jsonify({
                'success': True,
                'advanced': 'day',
                'current_day': tg_user.current_day,
                'module_id': tg_user.current_module_id,
                'module_title': tg_user.current_module.title if tg_user.current_module else None
            })

        # Day 6 completed, advance to next module
        current_module = tg_user.current_module
        if current_module:
            # Find next module in same level
            next_module = Module.query.filter(
                Module.level_id == current_module.level_id,
                Module.number > current_module.number
            ).order_by(Module.number).first()

            if not next_module:
                # Try next level
                next_level = CEFRLevel.query.filter(
                    CEFRLevel.order > current_module.level.order
                ).order_by(CEFRLevel.order).first()

                if next_level:
                    next_module = Module.query.filter_by(
                        level_id=next_level.id,
                        number=1
                    ).first()

            if next_module:
                tg_user.current_module_id = next_module.id
                tg_user.current_day = 1
                db.session.commit()

                return jsonify({
                    'success': True,
                    'advanced': 'module',
                    'current_day': tg_user.current_day,
                    'module_id': next_module.id,
                    'module_title': next_module.title,
                    'module_number': next_module.number,
                    'level': next_module.level.code if next_module.level else None
                })

        return jsonify({
            'success': True,
            'advanced': 'none',
            'message': 'Congratulations! You have completed all modules!',
            'current_day': tg_user.current_day,
            'module_id': tg_user.current_module_id
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/lesson/<int:module_id>/<lesson_type>', methods=['GET'])
@csrf.exempt
def get_lesson_content(module_id, lesson_type):
    """
    Get lesson content for a specific type in a module.

    Args:
        module_id: Module ID
        lesson_type: Type of lesson (grammar, reading, vocabulary, etc.)

    Returns:
        Lesson content formatted for Telegram display
    """
    try:
        module = Module.query.get(module_id)
        if not module:
            return jsonify({
                'success': False,
                'error': 'Module not found',
                'status_code': 404
            }), 404

        # Find lesson of this type in module
        lesson = Lessons.query.filter_by(
            module_id=module_id,
            type=lesson_type
        ).first()

        if not lesson:
            return jsonify({
                'success': False,
                'error': f'Lesson of type {lesson_type} not found',
                'status_code': 404
            }), 404

        # Format response based on lesson type
        response = {
            'success': True,
            'lesson': {
                'id': lesson.id,
                'type': lesson.type,
                'title': lesson.title,
                'description': lesson.description,
                'module': {
                    'id': module.id,
                    'title': module.title,
                    'level': module.level.code if module.level else None
                }
            }
        }

        # Add type-specific content
        content = lesson.content or {}

        if lesson_type == 'grammar':
            response['lesson']['content'] = {
                'rules': content.get('rules', []),
                'examples': content.get('examples', []),
                'explanation': content.get('explanation', ''),
                'tips': content.get('tips', [])
            }

        elif lesson_type == 'reading':
            response['lesson']['content'] = {
                'text': content.get('text', ''),
                'title': content.get('title', lesson.title),
                'questions': content.get('questions', []),
                'vocabulary_hints': content.get('vocabulary_hints', [])
            }

        elif lesson_type in ['listening_quiz', 'listening_immersion']:
            response['lesson']['content'] = {
                'audio_url': content.get('audio_url', ''),
                'transcript': content.get('transcript', ''),
                'questions': content.get('questions', []),
                'duration': content.get('duration', 0)
            }

        elif lesson_type == 'dialogue_completion':
            response['lesson']['content'] = {
                'dialogue': content.get('dialogue', []),
                'blanks': content.get('blanks', []),
                'options': content.get('options', []),
                'context': content.get('context', '')
            }

        elif lesson_type in ['quiz', 'ordering_quiz', 'translation_quiz', 'final_test']:
            questions = content.get('questions', [])
            # Don't send correct answers in response
            questions_safe = []
            for q in questions:
                questions_safe.append({
                    'id': q.get('id', len(questions_safe) + 1),
                    'type': q.get('type', 'multiple_choice'),
                    'question': q.get('question', q.get('text', '')),
                    'options': q.get('options', [])
                })
            response['lesson']['content'] = {
                'questions': questions_safe,
                'count': len(questions_safe)
            }

        else:
            response['lesson']['content'] = content

        return jsonify(response)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/complete-lesson', methods=['POST'])
@csrf.exempt
def complete_lesson():
    """
    Mark a specific lesson as completed.

    Body:
    - telegram_id (required): Telegram user ID
    - lesson_type (required): Type of lesson completed
    - score (optional): Score if applicable
    - correct (optional): Number of correct answers
    - total (optional): Total questions
    - cards_count (optional): Number of cards studied

    Returns:
        XP earned, streak info, day completion status
    """
    from app import limiter

    @limiter.limit("30 per minute")
    def _complete_impl():
        try:
            if not request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Invalid JSON format',
                    'status_code': 400
                }), 400

            data = request.get_json()
            telegram_id = data.get('telegram_id')
            lesson_type = data.get('lesson_type')

            if not telegram_id or not lesson_type:
                return jsonify({
                    'success': False,
                    'error': 'telegram_id and lesson_type are required',
                    'status_code': 400
                }), 400

            tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
            if not tg_user:
                return jsonify({
                    'success': False,
                    'error': 'User not found',
                    'status_code': 404
                }), 404

            today_progress = tg_user.get_today_progress()

            # Extract optional data
            kwargs = {}
            if 'score' in data:
                kwargs['score'] = data['score']
            if 'correct' in data:
                kwargs['correct'] = data['correct']
            if 'total' in data:
                kwargs['total'] = data['total']
            if 'cards_count' in data:
                kwargs['cards_count'] = data['cards_count']

            # Complete the lesson
            xp_earned = today_progress.complete_lesson(lesson_type, **kwargs)

            # Update streak if not already updated today
            streak_updated = False
            if tg_user.last_activity_date != date.today():
                tg_user.update_streak()
                streak_updated = True

            return jsonify({
                'success': True,
                'xp_earned': xp_earned,
                'streak_updated': streak_updated,
                'streak_days': tg_user.streak_days,
                'total_xp': tg_user.total_xp,
                'day_completed': today_progress.is_completed,
                'day_progress_percent': today_progress.progress_percent,
                'tasks': today_progress.get_tasks_for_day()
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e),
                'status_code': 500
            }), 500

    return _complete_impl()


@api_telegram.route('/telegram/bot/grammar/<int:module_id>', methods=['GET'])
@csrf.exempt
def get_grammar(module_id):
    """
    Get grammar lesson content for a module.

    Returns:
        Grammar rules, examples, and explanations formatted for Telegram
    """
    try:
        module = Module.query.get(module_id)
        if not module:
            return jsonify({
                'success': False,
                'error': 'Module not found',
                'status_code': 404
            }), 404

        # Find grammar lesson
        grammar_lesson = Lessons.query.filter_by(
            module_id=module_id,
            type='grammar'
        ).first()

        if not grammar_lesson:
            return jsonify({
                'success': False,
                'error': 'Grammar lesson not found',
                'status_code': 404
            }), 404

        content = grammar_lesson.content or {}

        return jsonify({
            'success': True,
            'module_id': module_id,
            'module_title': module.title,
            'lesson': {
                'id': grammar_lesson.id,
                'title': grammar_lesson.title,
                'description': grammar_lesson.description
            },
            'grammar': {
                'topic': content.get('topic', grammar_lesson.title),
                'explanation': content.get('explanation', ''),
                'rules': content.get('rules', []),
                'examples': content.get('examples', []),
                'tips': content.get('tips', []),
                'exercises': content.get('exercises', [])
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


@api_telegram.route('/telegram/bot/reading/<int:module_id>', methods=['GET'])
@csrf.exempt
def get_reading(module_id):
    """
    Get reading lesson content for a module.

    Returns:
        Reading text, title, and comprehension questions
    """
    try:
        module = Module.query.get(module_id)
        if not module:
            return jsonify({
                'success': False,
                'error': 'Module not found',
                'status_code': 404
            }), 404

        # Find reading lesson
        reading_lesson = Lessons.query.filter_by(
            module_id=module_id,
            type='reading'
        ).first()

        if not reading_lesson:
            return jsonify({
                'success': False,
                'error': 'Reading lesson not found',
                'status_code': 404
            }), 404

        content = reading_lesson.content or {}

        return jsonify({
            'success': True,
            'module_id': module_id,
            'module_title': module.title,
            'lesson': {
                'id': reading_lesson.id,
                'title': reading_lesson.title,
                'description': reading_lesson.description
            },
            'reading': {
                'title': content.get('title', reading_lesson.title),
                'text': content.get('text', ''),
                'word_count': len(content.get('text', '').split()),
                'vocabulary_hints': content.get('vocabulary_hints', []),
                'questions': content.get('questions', [])
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500
