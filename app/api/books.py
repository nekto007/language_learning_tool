from flask import Blueprint, jsonify, url_for, request
from flask_login import current_user
from sqlalchemy import func
import logging
from datetime import timezone, datetime

from app import csrf
from app.api.auth import api_login_required
from app.books.models import Book, ReadingProgress
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
        
        print(f"DEBUG: Audio processing - listening: {word_entry.listening}, get_download: {word_entry.get_download}, has_audio: {has_audio}, audio_url: {audio_url}")

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


@csrf.exempt
@api_books.route('/save-reading-position', methods=['POST'])
@api_login_required
def save_reading_position():
    """
    API for saving reading position (mobile reader) with rate limiting
    """
    from flask import request, session
    from app.books.models import ReadingProgress
    from datetime import datetime, timedelta
    import time
    
    data = request.get_json()
    book_id = data.get('book_id')
    position = data.get('position')

    if not book_id or position is None:
        return jsonify({'success': False, 'error': 'Missing required data'}), 400

    # Rate limiting: max 1 save per 3 seconds per user per book
    rate_limit_key = f'save_position_{current_user.id}_{book_id}'
    current_time = time.time()
    
    if rate_limit_key in session:
        last_save_time = session[rate_limit_key]
        if current_time - last_save_time < 3:  # 3 seconds minimum between saves
            logger.info(f"Rate limiting save position for user {current_user.id}, book {book_id}")
            return jsonify({'success': False, 'error': 'Rate limited'}), 429
    
    session[rate_limit_key] = current_time

    try:
        # Get or create reading progress
        progress = ReadingProgress.query.filter_by(
            user_id=current_user.id,
            book_id=book_id
        ).first()

        # Don't save if position hasn't changed significantly (server-side check)
        if progress and abs(progress.position - position) < 10:
            logger.debug(f"Position unchanged for user {current_user.id}, book {book_id}")
            return jsonify({'success': True, 'message': 'Position unchanged'})

        if not progress:
            progress = ReadingProgress(
                user_id=current_user.id,
                book_id=book_id,
                position=position
            )
            db.session.add(progress)
            logger.info(f"Created new reading progress for user {current_user.id}, book {book_id}")
        else:
            progress.position = position
            progress.last_read = datetime.now(timezone.utc)
            logger.debug(f"Updated reading position to {position} for user {current_user.id}, book {book_id}")

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving reading position: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# Reading Session Management API (Book Integration)
# ============================================================================

@csrf.exempt
@api_books.route('/reading-session/start', methods=['POST'])
@api_login_required
def start_reading_session():
    """Start a new reading session for a module lesson"""
    data = request.get_json()
    
    required_fields = ['book_id', 'start_position', 'end_position']
    missing_fields = [field for field in required_fields if data.get(field) is None]
    
    if missing_fields:
        return jsonify({
            'success': False, 
            'error': f'Missing required fields: {missing_fields}'
        }), 400
    
    try:
        # Note: Since we don't have the ReadingSession model implemented yet,
        # we'll use a simplified approach with the existing ReadingProgress model
        book_id = data['book_id']
        start_position = data['start_position']
        end_position = data['end_position']
        module_id = data.get('module_id')
        lesson_id = data.get('lesson_id')
        
        # Validate book exists
        book = Book.query.get(book_id)
        if not book:
            return jsonify({'success': False, 'error': 'Book not found'}), 404
        
        # Get or create reading progress
        progress = ReadingProgress.query.filter_by(
            user_id=current_user.id,
            book_id=book_id
        ).first()
        
        if not progress:
            progress = ReadingProgress(
                user_id=current_user.id,
                book_id=book_id,
                position=start_position
            )
            db.session.add(progress)
        else:
            # Update position if starting from a specific point
            progress.position = start_position
            progress.last_read = datetime.now(timezone.utc)
        
        db.session.commit()
        
        # Generate a temporary session ID (in real implementation, this would be a proper ReadingSession)
        session_id = f"{current_user.id}_{book_id}_{int(datetime.now().timestamp())}"
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'book_title': book.title,
            'start_position': start_position,
            'end_position': end_position,
            'reading_features': {
                'click_translate': True,
                'vocabulary_highlighting': True,
                'progress_saving': True,
                'note_taking': True
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error starting reading session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@csrf.exempt
@api_books.route('/reading-session/<session_id>/progress', methods=['PUT'])
@api_login_required
def update_reading_progress(session_id):
    """Update reading progress during a session"""
    data = request.get_json()
    
    current_position = data.get('current_position')
    if current_position is None:
        return jsonify({'success': False, 'error': 'current_position is required'}), 400
    
    try:
        # Parse session_id to get book_id (simplified approach)
        parts = session_id.split('_')
        if len(parts) < 2:
            return jsonify({'success': False, 'error': 'Invalid session_id'}), 400
        
        book_id = int(parts[1])
        
        # Update reading progress
        progress = ReadingProgress.query.filter_by(
            user_id=current_user.id,
            book_id=book_id
        ).first()
        
        if not progress:
            return jsonify({'success': False, 'error': 'Reading session not found'}), 404
        
        progress.position = current_position
        progress.last_read = datetime.now(timezone.utc)
        
        # Track vocabulary interactions if provided
        vocabulary_interactions = data.get('vocabulary_interactions', [])
        words_looked_up = len(vocabulary_interactions)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'current_position': current_position,
            'words_looked_up': words_looked_up
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating reading progress: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@csrf.exempt
@api_books.route('/reading-session/<session_id>/complete', methods=['POST'])
@api_login_required
def complete_reading_session(session_id):
    """Complete a reading session and process vocabulary"""
    data = request.get_json()
    
    try:
        # Parse session_id to get book_id
        parts = session_id.split('_')
        if len(parts) < 2:
            return jsonify({'success': False, 'error': 'Invalid session_id'}), 400
        
        book_id = int(parts[1])
        
        # Get session data
        final_position = data.get('final_position')
        duration_minutes = data.get('duration_minutes', 0)
        comprehension_score = data.get('comprehension_score')
        vocabulary_learned = data.get('vocabulary_learned', [])
        notes = data.get('notes', '')
        
        # Update reading progress
        progress = ReadingProgress.query.filter_by(
            user_id=current_user.id,
            book_id=book_id
        ).first()
        
        if progress and final_position:
            progress.position = final_position
            progress.last_read = datetime.now(timezone.utc)
        
        # Process vocabulary learned during reading
        words_added = 0
        for word_id in vocabulary_learned:
            try:
                word_entry = CollectionWords.query.get(word_id)
                if word_entry and current_user.get_word_status(word_id) == 0:
                    current_user.set_word_status(word_id, 1)  # Add to learning queue
                    words_added += 1
            except Exception as e:
                logger.warning(f"Failed to add word {word_id} to learning queue: {e}")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'session_completed': True,
            'words_learned': words_added,
            'final_position': final_position,
            'duration_minutes': duration_minutes,
            'next_lesson_available': True  # This would be determined by curriculum logic
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error completing reading session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_books.route('/reading-session/<session_id>/vocabulary', methods=['GET'])
@api_login_required
def get_session_vocabulary(session_id):
    """Get vocabulary extracted from a reading session"""
    try:
        # Parse session_id to get book_id
        parts = session_id.split('_')
        if len(parts) < 2:
            return jsonify({'success': False, 'error': 'Invalid session_id'}), 400
        
        book_id = int(parts[1])
        
        # Get position range from query parameters
        start_pos = request.args.get('start_position', type=int)
        end_pos = request.args.get('end_position', type=int)
        
        # In a real implementation, this would extract vocabulary from the book segment
        # For now, we'll return a mock response
        vocabulary_words = [
            {
                'word_id': 1,
                'word': 'marlin',
                'translation': 'марлин',
                'frequency_in_segment': 5,
                'difficulty_level': 'B1',
                'context_sentence': 'The great marlin that he had hooked.',
                'already_known': False
            },
            {
                'word_id': 2,
                'word': 'struggle',
                'translation': 'борьба',
                'frequency_in_segment': 3,
                'difficulty_level': 'B1',
                'context_sentence': 'His struggle with the fish was legendary.',
                'already_known': False
            }
        ]
        
        return jsonify({
            'success': True,
            'vocabulary_words': vocabulary_words,
            'total_words': len(vocabulary_words),
            'new_words': len([w for w in vocabulary_words if not w['already_known']])
        })
        
    except Exception as e:
        logger.error(f"Error getting session vocabulary: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
