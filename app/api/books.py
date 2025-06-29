import gzip
import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, make_response, request, url_for
from flask_login import current_user
from sqlalchemy import func

from app import csrf
from app.api.auth import api_login_required
from app.books.models import Book, Chapter, UserChapterProgress, Task, Block
from app.curriculum.cache import cached
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)

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
        'created_at': book.created_at.isoformat() if book.created_at else None
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
        'created_at': book.created_at.isoformat() if book.created_at else None,
        'word_stats': word_stats
    })


# ============================================================================
# Chapter-based Reading API
# ============================================================================

@api_books.route('/books/<slug>/chapters', methods=['GET'])
@api_login_required
@cached(timeout=3600, key_prefix='book_chapters_by_slug')  # Cache for 1 hour
def get_book_chapters_by_slug(slug):
    """
    Get all chapters for a book by slug
    Returns: [{"id": 12, "num": 1, "title": "The Boy...", "words": 4526, "audio_url": null}, ...]
    """
    book = Book.query.filter_by(slug=slug).first_or_404()

    chapters = Chapter.query.filter_by(book_id=book.id).order_by(Chapter.chap_num).all()

    return jsonify([{
        'id': ch.id,
        'num': ch.chap_num,
        'title': ch.title,
        'words': ch.words,
        'audio_url': ch.audio_url
    } for ch in chapters])


@api_books.route('/books/<int:book_id>/chapters', methods=['GET'])
@api_login_required
@cached(timeout=3600, key_prefix='book_chapters')  # Cache for 1 hour
def get_book_chapters(book_id):
    """
    Get all chapters for a book
    Returns: [{"id": 12, "num": 1, "title": "The Boy...", "words": 4526, "audio_url": null}, ...]
    """
    book = Book.query.get_or_404(book_id)

    chapters = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.chap_num).all()

    return jsonify([{
        'id': ch.id,
        'num': ch.chap_num,
        'title': ch.title,
        'words': ch.words,
        'audio_url': ch.audio_url
    } for ch in chapters])


@api_books.route('/books/<int:book_id>/chapters/<int:chapter_num>', methods=['GET'])
@api_login_required
def get_chapter_content(book_id, chapter_num):
    """
    Get chapter content with navigation info
    Returns: {"id": 12, "num": 1, "text": "...", "next": 2, "prev": null}
    """
    chapter = Chapter.query.filter_by(
        book_id=book_id,
        chap_num=chapter_num
    ).first_or_404()

    # Get next and previous chapter numbers
    next_chapter = Chapter.query.filter_by(
        book_id=book_id,
        chap_num=chapter_num + 1
    ).first()

    prev_chapter = Chapter.query.filter_by(
        book_id=book_id,
        chap_num=chapter_num - 1
    ).first()

    response_data = {
        'id': chapter.id,
        'num': chapter.chap_num,
        'title': chapter.title,
        'text': chapter.text_raw,
        'next': next_chapter.chap_num if next_chapter else None,
        'prev': prev_chapter.chap_num if prev_chapter else None
    }

    # Check if client accepts gzip
    if 'gzip' in request.headers.get('Accept-Encoding', ''):
        # Compress response
        json_str = json.dumps(response_data)
        compressed = gzip.compress(json_str.encode('utf-8'))

        response = make_response(compressed)
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Content-Type'] = 'application/json'
        return response

    return jsonify(response_data)


@csrf.exempt
@api_books.route('/progress', methods=['PATCH'])
@api_login_required
def update_chapter_progress():
    """
    Update reading progress
    Expects: {"book_id": 1, "chapter_id": 12, "offset_pct": 0.5}
    """
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    book_id = data.get('book_id')
    chapter_id = data.get('chapter_id')
    offset_pct = data.get('offset_pct')

    if book_id is None or chapter_id is None or offset_pct is None:
        return jsonify({'success': False, 'error': 'Missing required fields: book_id, chapter_id, offset_pct'}), 400

    # Validate offset percentage
    if not 0 <= offset_pct <= 1:
        return jsonify({'success': False, 'error': 'offset_pct must be between 0 and 1'}), 400

    # Verify chapter exists and belongs to book
    chapter = Chapter.query.get_or_404(chapter_id)
    if chapter.book_id != book_id:
        return jsonify({'success': False, 'error': 'Chapter does not belong to the specified book'}), 400

    try:
        # Update or create progress
        progress = UserChapterProgress.query.filter_by(
            user_id=current_user.id,
            chapter_id=chapter_id
        ).first()

        if progress:
            progress.offset_pct = offset_pct
            progress.updated_at = datetime.now(timezone.utc)
        else:
            progress = UserChapterProgress(
                user_id=current_user.id,
                chapter_id=chapter_id,
                offset_pct=offset_pct
            )
            db.session.add(progress)

        db.session.commit()

        return jsonify({
            'success': True,
            'chapter_id': chapter_id,
            'offset_pct': offset_pct
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating chapter progress: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_books.route('/books/<int:book_id>/progress', methods=['GET'])
@api_login_required
def get_book_chapter_progress(book_id):
    """
    Get user's reading progress for a book
    Returns current chapter and offset
    """
    book = Book.query.get_or_404(book_id)

    # Get all progress for this book's chapters
    progress_records = db.session.query(
        UserChapterProgress, Chapter
    ).join(
        Chapter, UserChapterProgress.chapter_id == Chapter.id
    ).filter(
        Chapter.book_id == book_id,
        UserChapterProgress.user_id == current_user.id
    ).order_by(
        UserChapterProgress.updated_at.desc()
    ).all()

    if not progress_records:
        # No progress yet, start from beginning
        first_chapter = Chapter.query.filter_by(
            book_id=book_id
        ).order_by(Chapter.chap_num).first()

        return jsonify({
            'current_chapter': first_chapter.chap_num if first_chapter else 1,
            'offset_pct': 0,
            'chapters_read': []
        })

    # Get most recent progress
    latest_progress, latest_chapter = progress_records[0]

    # Get list of chapters with progress
    chapters_progress = [{
        'chapter_num': ch.chap_num,
        'offset_pct': p.offset_pct,
        'updated_at': p.updated_at.isoformat()
    } for p, ch in progress_records]

    return jsonify({
        'current_chapter': latest_chapter.chap_num,
        'offset_pct': latest_progress.offset_pct,
        'chapters_read': chapters_progress
    })


@api_books.route('/word-translation/<word>', methods=['GET'])
@api_login_required
def get_word_translation(word):
    """
    API для получения перевода слова с определением его формы
    """
    logger.info(f"API word-translation called for word: {word}")
    print(f"DEBUG: API Translation called for word: {word}")

    word = word.lower().strip()
    original_word = word

    # Dictionary of irregular verbs
    irregular_verbs = {
        'was': 'be', 'were': 'be', 'been': 'be',
        'went': 'go', 'saw': 'see', 'ate': 'eat', 'drank': 'drink',
        'spoke': 'speak', 'drove': 'drive', 'flew': 'fly', 'grew': 'grow',
        'knew': 'know', 'ran': 'run', 'came': 'come', 'took': 'take',
        'gave': 'give', 'found': 'find', 'thought': 'think', 'told': 'tell',
        'became': 'become', 'felt': 'feel', 'stood': 'stand', 'heard': 'hear',
        'brought': 'bring', 'bought': 'buy', 'caught': 'catch', 'taught': 'teach',
        'sold': 'sell', 'built': 'build', 'sent': 'send', 'spent': 'spend',
        'fell': 'fall', 'met': 'meet', 'paid': 'pay', 'said': 'say',
        'understood': 'understand', 'kept': 'keep', 'left': 'leave',
        'gone': 'go', 'seen': 'see', 'eaten': 'eat', 'drunk': 'drink',
        'spoken': 'speak', 'driven': 'drive', 'flown': 'fly', 'grown': 'grow',
        'known': 'know', 'taken': 'take', 'given': 'give', 'written': 'write',
        'done': 'do', 'made': 'make', 'had': 'have', 'got': 'get',
        'began': 'begin', 'begun': 'begin', 'broke': 'break', 'broken': 'break',
        'chose': 'choose', 'chosen': 'choose', 'came': 'come', 'did': 'do'
    }

    # Ищем слово в базе
    word_entry = CollectionWords.query.filter_by(english_word=word).first()

    # Отслеживаем информацию о форме слова
    word_form_info = None

    # Если слово не найдено, пробуем найти его базовую форму
    if not word_entry:
        logger.debug(f"Слово '{word}' не найдено в базе, пробуем определить форму")

        # Проверяем на неправильные глаголы
        if word in irregular_verbs:
            base_form = irregular_verbs[word]
            logger.debug(f"Найден неправильный глагол: {word} -> {base_form}")
            word_entry = CollectionWords.query.filter_by(english_word=base_form).first()
            if word_entry:
                word_form_info = {'type': 'past_tense', 'base_form': base_form}

        # Если всё ещё не нашли, проверяем другие формы
        if not word_entry:
            # Проверка на -ing форму
            if word.endswith('ing') and len(word) > 4:
                base_form = word[:-3]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                if not word_entry:
                    base_form_e = base_form + 'e'
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_e).first()
                    if word_entry:
                        base_form = base_form_e

                if not word_entry and len(base_form) >= 2 and base_form[-1] == base_form[-2]:
                    base_form_single = base_form[:-1]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_single).first()
                    if word_entry:
                        base_form = base_form_single

                if word_entry:
                    word_form_info = {'type': 'continuous', 'base_form': base_form}

            # Проверка на -ed форму
            if not word_entry and word.endswith('ed') and len(word) > 3:
                base_form = word[:-2]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                if not word_entry:
                    base_form_e = word[:-1]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_e).first()
                    if word_entry:
                        base_form = base_form_e

                if not word_entry and len(base_form) >= 2 and base_form[-1] == base_form[-2]:
                    base_form_single = base_form[:-1]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_single).first()
                    if word_entry:
                        base_form = base_form_single

                if word_entry:
                    word_form_info = {'type': 'past_tense', 'base_form': base_form}

            # Проверка на множественное число
            if not word_entry and word.endswith('s') and not word.endswith('ss') and len(word) > 2:
                base_form = word[:-1]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                if not word_entry and word.endswith('es'):
                    base_form_es = word[:-2]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_es).first()
                    if word_entry:
                        base_form = base_form_es

                if not word_entry and word.endswith('ies'):
                    base_form_ies = word[:-3] + 'y'
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_ies).first()
                    if word_entry:
                        base_form = base_form_ies

                if word_entry:
                    word_form_info = {'type': 'plural', 'base_form': base_form}

    if word_entry:
        # Получаем статус слова для пользователя
        status = current_user.get_word_status(word_entry.id)

        # Проверяем наличие аудио - должно быть и listening и get_download = 1
        has_audio = False
        audio_url = None

        if word_entry.listening and word_entry.get_download == 1:
            audio_filename = word_entry.listening

            # Обрабатываем формат [sound:filename.mp3]
            if audio_filename.startswith('[sound:') and audio_filename.endswith(']'):
                audio_filename = audio_filename[7:-1]  # Убираем [sound: и ]
                has_audio = True
                audio_url = url_for('static', filename=f'audio/{audio_filename}')

            # Обрабатываем формат audio/filename.mp3
            elif audio_filename.startswith('audio/') and audio_filename.endswith('.mp3'):
                audio_filename = audio_filename[6:-4]
                has_audio = True
                audio_url = url_for('static', filename=f'audio/{audio_filename}.mp3')

            # Обрабатываем прямой формат filename.mp3
            elif audio_filename.endswith('.mp3'):
                has_audio = True
                audio_url = url_for('static', filename=f'audio/{audio_filename}')

        print(
            f"DEBUG: Audio processing - listening: {word_entry.listening}, get_download: {word_entry.get_download}, has_audio: {has_audio}, audio_url: {audio_url}")

        # Определяем текст для отображения информации о форме
        form_text = None
        if word_form_info:
            form_type = word_form_info['type']
            if form_type == 'past_tense':
                form_text = 'прошедшее время от'
            elif form_type == 'continuous':
                form_text = 'длительная форма от'
            elif form_type == 'plural':
                form_text = 'множественное число от'

        response = {
            'word': original_word,
            'translation': word_entry.russian_word,
            'in_dictionary': True,
            'id': word_entry.id,
            'status': status,
            'has_audio': has_audio,
            'audio_url': audio_url,
            'is_form': word_form_info is not None,
            'form_text': form_text,
            'base_form': word_form_info['base_form'] if word_form_info else None
        }

        print(f"DEBUG: Translation found: {response}")
        return jsonify(response)
    else:
        print(f"DEBUG: Translation not found for word: {original_word}")
        return jsonify({
            'word': original_word,
            'translation': None,
            'in_dictionary': False
        })


@csrf.exempt
@api_books.route('/add-to-learning', methods=['POST'])
@api_login_required
def add_to_learning():
    """
    API для добавления слова в очередь изучения
    """
    from flask import request

    data = request.get_json()
    word_id = data.get('word_id')

    if not word_id:
        return jsonify({'success': False, 'error': 'Word ID is required'}), 400

    word_entry = CollectionWords.query.get(word_id)

    if not word_entry:
        return jsonify({'success': False, 'error': 'Word not found in dictionary'}), 404

    # Получаем текущий статус слова
    current_status = current_user.get_word_status(word_id)

    # Если слово ещё не в изучении (статус 0), добавляем его (статус 1)
    if current_status == 0:
        current_user.set_word_status(word_id, 1)  # 1 = queued for learning
        print(f"DEBUG: Added word {word_entry.english_word} to learning queue")
        return jsonify({
            'success': True,
            'message': 'Word added to learning queue',
            'new_status': 1
        })
    else:
        # Слово уже имеет статус
        return jsonify({
            'success': True,
            'message': 'Word is already in your list',
            'status': current_status
        })


@api_books.route('/book/<int:book_id>/content', methods=['GET'])
@api_login_required
def get_book_content(book_id):
    """Get book content for reading assignment"""
    start_position = request.args.get('start_position', type=int, default=0)
    end_position = request.args.get('end_position', type=int)

    try:
        book = Book.query.get_or_404(book_id)

        # In a real implementation, this would extract the actual book content
        # For now, return mock content structure
        mock_content = {
            'book_id': book_id,
            'title': book.title,
            'start_position': start_position,
            'end_position': end_position,
            'content_html': '<p>Sample book content would go here...</p>',
            'vocabulary_highlights': [
                {'word': 'marlin', 'position': 50, 'definition': 'large marine fish'},
                {'word': 'struggle', 'position': 150, 'definition': 'difficult effort'}
            ],
            'interactive_elements': [
                {
                    'position': 100,
                    'type': 'comprehension_check',
                    'question': 'How long has Santiago been without a fish?',
                    'answer': '84 days'
                }
            ]
        }

        return jsonify({
            'success': True,
            'content': mock_content
        })

    except Exception as e:
        logger.error(f"Error getting book content: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_books.route('/tasks/<int:task_id>', methods=['GET'])
@api_login_required
def get_task(task_id):
    """
    Get task by ID with its payload
    Returns task data for frontend consumption
    """
    try:
        task = Task.query.get_or_404(task_id)
        
        return jsonify({
            'success': True,
            'task': {
                'id': task.id,
                'block_id': task.block_id,
                'task_type': task.task_type,
                'payload': task.payload,
                'created_at': task.created_at.isoformat() if task.created_at else None
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_books.route('/blocks/<int:block_id>/tasks', methods=['GET'])
@api_login_required
def get_block_tasks(block_id):
    """
    Get all tasks for a specific block
    Returns list of tasks with their types and IDs
    """
    try:
        tasks = Task.query.filter_by(block_id=block_id).all()
        
        task_list = []
        for task in tasks:
            task_list.append({
                'id': task.id,
                'task_type': task.task_type,
                'created_at': task.created_at.isoformat() if task.created_at else None
            })
        
        return jsonify({
            'success': True,
            'block_id': block_id,
            'tasks': task_list
        })
        
    except Exception as e:
        logger.error(f"Error getting tasks for block {block_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_books.route('/blocks/<int:block_id>', methods=['GET'])
@api_login_required
def get_block(block_id):
    """
    Get block information with task types
    Returns block title and available task types
    """
    try:
        block = Block.query.get_or_404(block_id)
        
        # Get task types for this block
        tasks = Task.query.filter_by(block_id=block_id).all()
        task_types = [task.task_type for task in tasks]
        
        return jsonify({
            'success': True,
            'block': {
                'id': block.id,
                'block_num': block.block_num,
                'grammar_key': block.grammar_key,
                'focus_vocab': block.focus_vocab,
                'task_types': task_types,
                'created_at': block.created_at.isoformat() if block.created_at else None
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting block {block_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_books.route('/chapters/<int:chapter_id>', methods=['GET'])
@api_login_required
def get_chapter_by_id(chapter_id):
    """
    Get chapter by ID with text and audio URL
    Returns text_raw and audio_url
    """
    try:
        chapter = Chapter.query.get_or_404(chapter_id)
        
        return jsonify({
            'success': True,
            'chapter': {
                'id': chapter.id,
                'num': chapter.chap_num,
                'title': chapter.title,
                'text_raw': chapter.text_raw,
                'audio_url': chapter.audio_url,
                'words': chapter.words,
                'book_id': chapter.book_id
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting chapter {chapter_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
