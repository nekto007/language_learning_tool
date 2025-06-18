from flask import Blueprint, jsonify, url_for
from flask_login import current_user
from sqlalchemy import func
import logging
from datetime import timezone

from app import csrf
from app.api.auth import api_login_required
from app.books.models import Book
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
