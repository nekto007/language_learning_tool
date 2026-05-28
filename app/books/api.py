# app/books/api.py
# API endpoints for the books module (extracted from routes.py)

import collections
import inspect
import logging
import os
import sys

from datetime import UTC, datetime
from typing import Optional

import re as _re

from flask import Blueprint, Response, jsonify, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import csrf
from app.books.models import Bookmark, Chapter
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import CollectionWords

books_api = Blueprint('books_api', __name__)

morph = None

logger = logging.getLogger(__name__)


def get_word_base_form(word):
    """
    Simple function to get the base form of a word without using NLTK
    Returns a tuple (base_form, form_type) or (None, None) if not found
    """
    word = word.lower().strip()

    # Dictionary of irregular verbs (past -> base form)
    irregular_verbs_local = {
        # Past forms -> base form
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

        # Past participle forms -> base form
        'gone': 'go', 'seen': 'see', 'eaten': 'eat', 'drunk': 'drink',
        'spoken': 'speak', 'driven': 'drive', 'flown': 'fly', 'grown': 'grow',
        'known': 'know', 'run': 'run', 'come': 'come', 'taken': 'take',
        'given': 'give', 'found': 'find', 'thought': 'think', 'told': 'tell',
        'become': 'become', 'felt': 'feel', 'stood': 'stand', 'heard': 'hear',
        'brought': 'bring', 'bought': 'buy', 'caught': 'catch', 'taught': 'teach',
        'sold': 'sell', 'built': 'build', 'sent': 'send', 'spent': 'spend',
        'fallen': 'fall', 'met': 'meet', 'paid': 'pay', 'said': 'say',
        'understood': 'understand', 'kept': 'keep', 'left': 'leave',
    }

    # Check for irregular verbs
    if word in irregular_verbs_local:
        return irregular_verbs_local[word], 'past_tense'

    # Check for regular patterns:

    # 1. Check for -ing form
    if word.endswith('ing') and len(word) > 4:
        # Try removing 'ing'
        base_form = word[:-3]

        # Check for doubled consonant (running -> run)
        if len(base_form) >= 2 and base_form[-1] == base_form[-2]:
            base_form_single = base_form[:-1]
            return base_form_single, 'continuous'

        # Try with 'e' (writing -> write)
        base_form_e = base_form + 'e'
        if len(base_form) <= 4:
            return base_form_e, 'continuous'

        return base_form, 'continuous'

    # 2. Check for -ed form
    if word.endswith('ed') and len(word) > 3:
        # Try removing 'ed'
        base_form = word[:-2]

        # Check for doubled consonant (stopped -> stop)
        if len(base_form) >= 2 and base_form[-1] == base_form[-2]:
            base_form_single = base_form[:-1]
            return base_form_single, 'past_tense'

        # Try with 'e' (liked -> like)
        base_form_e = word[:-1]  # Just remove 'd'
        if len(base_form) <= 4:
            return base_form_e, 'past_tense'

        return base_form, 'past_tense'

    # 3. Check for plural nouns
    if word.endswith('s') and not word.endswith('ss') and len(word) > 2:
        # Regular plural (cars -> car)
        base_form = word[:-1]

        # Check for -ies (flies -> fly)
        if word.endswith('ies'):
            base_form_ies = word[:-3] + 'y'
            return base_form_ies, 'plural'

        # Check for -es (boxes -> box)
        if word.endswith('es'):
            base_form_es = word[:-2]
            return base_form_es, 'plural'

        return base_form, 'plural'

    # 4. Check for adjective comparatives and superlatives
    if word.endswith('er') and len(word) > 3:
        # Comparative (bigger -> big)
        base_form = word[:-2]

        # Check for doubled consonant
        if len(base_form) >= 2 and base_form[-1] == base_form[-2]:
            base_form_single = base_form[:-1]
            return base_form_single, 'comparative'

        # Special case for -ier (easier -> easy)
        if word.endswith('ier'):
            base_form_y = word[:-3] + 'y'
            return base_form_y, 'comparative'

        return base_form, 'comparative'

    if word.endswith('est') and len(word) > 4:
        # Superlative (biggest -> big)
        base_form = word[:-3]

        # Check for doubled consonant
        if len(base_form) >= 2 and base_form[-1] == base_form[-2]:
            base_form_single = base_form[:-1]
            return base_form_single, 'superlative'

        # Special case for -iest (easiest -> easy)
        if word.endswith('iest'):
            base_form_y = word[:-4] + 'y'
            return base_form_y, 'superlative'

        return base_form, 'superlative'

    # No transformation found
    return None, None


def patch_inspect_module():
    """
    Добавляет обратную совместимость с inspect.getargspec для pymorphy2
    """
    try:
        # Проверяем, есть ли getargspec в модуле inspect
        if not hasattr(inspect, 'getargspec'):
            logger.info("Применяем патч для inspect.getargspec")

            # Создаем совместимую версию getargspec на основе getfullargspec
            def getargspec_compat(func):
                full = inspect.getfullargspec(func)
                return inspect.ArgSpec(
                    args=full.args,
                    varargs=full.varargs,
                    keywords=full.varkw,
                    defaults=full.defaults
                )

            # Добавляем в модуль inspect
            inspect.getargspec = getargspec_compat

            # Создаем класс для совместимости
            if not hasattr(inspect, 'ArgSpec'):
                inspect.ArgSpec = collections.namedtuple(
                    'ArgSpec', ['args', 'varargs', 'keywords', 'defaults']
                )

            logger.info("Патч для inspect.getargspec успешно применен")
            return True
        else:
            logger.info("inspect.getargspec уже присутствует")
            return True
    except Exception as e:
        logger.error(f"Ошибка при применении патча inspect.getargspec: {str(e)}")
        return False


# Патчим модуль inspect для совместимости с pymorphy2
if sys.version_info >= (3, 11):
    try:
        patch_result = patch_inspect_module()
        logger.info(f"Результат патча inspect: {patch_result}")
    except Exception as e:
        logger.error(f"Ошибка при попытке применить патч: {str(e)}")

# Глобальная переменная для хранения анализатора
morph = None


def setup_morphology():
    """
    Настройка инструментов морфологического анализа с обходом проблем совместимости
    """
    global morph

    try:
        # Проверяем версию Python
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        logger.info(f"Версия Python: {python_version}")

        # Пробуем импортировать pymorphy2
        import pymorphy2
        logger.info(f"Pymorphy2 версия: {pymorphy2.__version__}")

        # Пробуем создать анализатор
        try:
            morph = pymorphy2.MorphAnalyzer()
            logger.info("Pymorphy2 инициализирован успешно")
            return True
        except Exception as e:
            logger.error(f"Ошибка при создании MorphAnalyzer: {str(e)}")
            logger.error("Попробуем использовать нашу реализацию без pymorphy2")
            return False

    except ImportError as e:
        logger.warning(f"Ошибка импорта pymorphy2: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при инициализации pymorphy2: {str(e)}")
        return False


# Словарь для хранения английских неправильных глаголов
irregular_verbs = {
    # Past forms -> base form
    'was': 'be', 'were': 'be', 'been': 'be',
    'went': 'go', 'saw': 'see', 'ate': 'eat', 'drank': 'drink',
    'spoke': 'speak', 'drove': 'drive', 'flew': 'fly', 'grew': 'grow',
    'knew': 'know', 'ran': 'run', 'came': 'come', 'took': 'take',
    'gave': 'give', 'found': 'find', 'thought': 'think', 'told': 'tell',
    'became': 'become', 'felt': 'feel', 'stood': 'stand', 'heard': 'hear',
    'brought': 'bring', 'bought': 'buy', 'caught': 'catch', 'taught': 'teach',
    # Past participle forms -> base form
    'gone': 'go', 'seen': 'see', 'eaten': 'eat', 'drunk': 'drink',
    'spoken': 'speak', 'driven': 'drive', 'flown': 'fly', 'grown': 'grow',
    'known': 'know', 'run': 'run', 'come': 'come', 'taken': 'take',
    'given': 'give', 'found': 'find', 'thought': 'think', 'told': 'tell'
}

# Запускаем инициализацию при импорте модуля
pymorphy2_available = setup_morphology()
logger.info(f"Pymorphy2 доступен: {pymorphy2_available}")
# Если pymorphy2 недоступен, предупреждаем пользователя
if not pymorphy2_available:
    logger.warning("Работа без pymorphy2: анализ русской морфологии будет ограничен")


@books_api.route('/audio/<int:book_id>/chapter/<int:chapter_num>')
@login_required
def serve_chapter_audio(book_id: int, chapter_num: int):
    """Serve audio file for a book chapter with Range request support."""
    chapter = Chapter.query.filter_by(book_id=book_id, chap_num=chapter_num).first_or_404()
    book = chapter.book
    if not book.is_published and not current_user.is_admin:
        return 'Not found', 404
    if not chapter.audio_url:
        return 'No audio available', 404
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    audio_path = os.path.realpath(os.path.join(project_root, chapter.audio_url))
    if not audio_path.startswith(os.path.realpath(project_root) + os.sep):
        return 'Not found', 404
    if not os.path.isfile(audio_path):
        logger.warning(f"Audio file not found: {audio_path}")
        return 'Audio file not found', 404

    file_size = os.path.getsize(audio_path)
    mimetype = 'audio/mpeg'
    range_header = request.headers.get('Range')

    if not range_header:
        resp = send_file(audio_path, mimetype=mimetype, conditional=True)
        resp.headers['Accept-Ranges'] = 'bytes'
        return resp

    m = _re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not m:
        return Response(status=400, headers={'Content-Range': f'bytes */{file_size}'})

    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1

    if start > end or start >= file_size:
        return Response(status=416, headers={'Content-Range': f'bytes */{file_size}'})

    end = min(end, file_size - 1)
    length = end - start + 1

    with open(audio_path, 'rb') as f:
        f.seek(start)
        data = f.read(length)

    return Response(
        data,
        status=206,
        mimetype=mimetype,
        headers={
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
        },
    )


@books_api.route('/api/translate', methods=['POST'])
@login_required
def api_translate():
    """
    API for word translation (optimized reader)
    With lemmatization support for plurals, verb forms, etc.
    """
    data = request.get_json()
    word = data.get('word', '').strip().lower()

    if not word:
        return jsonify({'success': False, 'error': 'Word is required'}), 400

    try:
        # Search for exact match first
        word_entry = CollectionWords.query.filter_by(english_word=word).first()

        # If not found, try lemmatization (base forms)
        if not word_entry:
            word_variants = []

            # Irregular verbs
            if word in irregular_verbs:
                word_variants.append(irregular_verbs[word])

            # -ing forms
            if word.endswith('ing') and len(word) > 4:
                base = word[:-3]
                word_variants.extend([base, base + 'e'])
                if len(base) >= 2 and base[-1] == base[-2]:
                    word_variants.append(base[:-1])

            # -ed forms
            if word.endswith('ed') and len(word) > 3:
                word_variants.extend([word[:-2], word[:-1]])
                base = word[:-2]
                if len(base) >= 2 and base[-1] == base[-2]:
                    word_variants.append(base[:-1])

            # Plural -s, -es, -ies
            if word.endswith('s') and not word.endswith('ss') and len(word) > 2:
                word_variants.append(word[:-1])
                if word.endswith('es') and len(word) > 3:
                    word_variants.append(word[:-2])
                if word.endswith('ies') and len(word) > 4:
                    word_variants.append(word[:-3] + 'y')

            # -er comparative
            if word.endswith('er') and len(word) > 3:
                word_variants.append(word[:-2])
                if word.endswith('ier'):
                    word_variants.append(word[:-3] + 'y')

            # -est superlative
            if word.endswith('est') and len(word) > 4:
                word_variants.append(word[:-3])
                if word.endswith('iest'):
                    word_variants.append(word[:-4] + 'y')

            # Search for variants
            if word_variants:
                word_entry = CollectionWords.query.filter(
                    CollectionWords.english_word.in_(word_variants)
                ).first()

        if word_entry and word_entry.russian_word:
            return jsonify({
                'success': True,
                'translation': word_entry.russian_word,
                'word': word,
                'word_id': word_entry.id,
                'sentences': word_entry.sentences or ''
            })
        else:
            return jsonify({
                'success': True,
                'translation': 'Перевод не найден',
                'word': word,
                'word_id': None
            })

    except Exception as e:
        logger.error(f'Error looking up word: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to look up word'}), 500


@books_api.route('/api/add-word-to-learning', methods=['POST'])
@login_required
def add_word_to_learning():
    """
    API for adding word to learning list (optimized reader)
    """
    data = request.get_json()
    word = data.get('word', '').strip().lower()

    if not word:
        return jsonify({'success': False, 'error': 'Word is required'}), 400

    try:
        # Normalize word to lowercase
        word_normalized = word.lower().strip()

        # Check if word exists in dictionary
        word_entry = CollectionWords.query.filter_by(english_word=word_normalized).first()

        if not word_entry:
            # Create new word entry
            word_entry = CollectionWords(
                english_word=word_normalized,
                russian_word='',  # Will be filled later
                level='A1'  # Default level
            )
            db.session.add(word_entry)

        # Check if user already has this word in learning
        user_word = UserWord.query.filter_by(
            user_id=current_user.id,
            word_id=word_entry.id
        ).first()

        if not user_word:
            # Add to user's learning list
            user_word = UserWord(
                user_id=current_user.id,
                word_id=word_entry.id,
                status='learning',  # Learning status as string
                date_added=datetime.now(UTC)
            )
            db.session.add(user_word)

        # Add word to "Reading Vocabulary" deck
        from app.study.models import QuizDeck, QuizDeckWord

        # Find or create "Reading Vocabulary" deck
        deck_title = "Слова из чтения"
        reading_deck = QuizDeck.query.filter_by(
            user_id=current_user.id,
            title=deck_title
        ).first()

        if not reading_deck:
            reading_deck = QuizDeck(
                title=deck_title,
                description="Слова, добавленные во время чтения книг и уроков",
                user_id=current_user.id,
                is_public=False
            )
            db.session.add(reading_deck)
            db.session.flush()  # Get deck ID

        # Check if word already in deck
        existing_deck_word = QuizDeckWord.query.filter_by(
            deck_id=reading_deck.id,
            word_id=word_entry.id
        ).first()

        if not existing_deck_word:
            # Get max order index
            max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter(
                QuizDeckWord.deck_id == reading_deck.id
            ).scalar() or 0

            # Add word to deck
            deck_word = QuizDeckWord(
                deck_id=reading_deck.id,
                word_id=word_entry.id,
                order_index=max_order + 1
            )
            db.session.add(deck_word)

        db.session.commit()

        return jsonify({'success': True, 'message': f'Word "{word}" added to learning list'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@books_api.route('/api/bookmarks/<int:book_id>')
@login_required
def get_bookmarks(book_id):
    """
    API for getting bookmarks for a book
    """
    try:
        bookmarks = Bookmark.query.filter_by(
            user_id=current_user.id,
            book_id=book_id
        ).order_by(Bookmark.position).all()

        bookmarks_data = [{
            'id': bookmark.id,
            'name': bookmark.name,
            'position': bookmark.position,
            'context': bookmark.context or '',
            'created_at': bookmark.created_at.isoformat()
        } for bookmark in bookmarks]

        return jsonify(bookmarks_data)

    except Exception as e:
        logger.error(f'Error loading bookmarks for book {book_id}: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to load bookmarks'}), 500


@books_api.route('/api/bookmarks', methods=['POST'])
@login_required
def save_bookmark():
    """
    API for saving a bookmark
    """
    data = request.get_json()
    book_id = data.get('book_id')
    name = data.get('name', '').strip()
    position = data.get('position', 0)
    context = data.get('context', '')

    if not book_id or not name:
        return jsonify({'success': False, 'error': 'Book ID and name are required'}), 400

    try:
        bookmark = Bookmark(
            user_id=current_user.id,
            book_id=book_id,
            name=name,
            position=position,
            context=context,
            created_at=datetime.now(UTC)
        )

        db.session.add(bookmark)
        db.session.commit()

        return jsonify({'success': True, 'id': bookmark.id})

    except Exception as e:
        db.session.rollback()
        logger.error(f'Error saving bookmark: {e}', exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to save bookmark'}), 500


@books_api.route('/api/test', methods=['GET'])
@login_required
def api_test():
    """Test API endpoint"""
    return jsonify({'status': 'ok', 'message': 'API is working'})


@books_api.route('/books/api/word-translation/<word>', methods=['GET'])
@login_required
def get_word_translation(word):
    """
    API для получения перевода слова с определением его формы
    Работает полностью без использования pymorphy2, но с продвинутым
    анализом форм слов на основе правил
    """
    # Логгируем запрос для отладки
    logger.info(f"API word-translation called for word: {word}")

    word = word.lower().strip()
    original_word = word

    # Отслеживаем, используем ли мы другую форму слова
    word_form_info = None

    # Собираем все возможные варианты базовых форм для одного bulk-запроса
    word_variants = [(word, None, None)]  # (variant, form_type, base_form)

    # Проверяем на неправильные глаголы
    if word in irregular_verbs:
        base_form = irregular_verbs[word]
        word_variants.append((base_form, 'past_tense', base_form))

    # Формы -ing
    if word.endswith('ing') and len(word) > 4:
        base_ing = word[:-3]
        word_variants.append((base_ing, 'continuous', base_ing))
        word_variants.append((base_ing + 'e', 'continuous', base_ing + 'e'))
        if len(base_ing) >= 2 and base_ing[-1] == base_ing[-2]:
            word_variants.append((base_ing[:-1], 'continuous', base_ing[:-1]))

    # Формы -ed
    if word.endswith('ed') and len(word) > 3:
        base_ed = word[:-2]
        word_variants.append((base_ed, 'past_tense', base_ed))
        word_variants.append((word[:-1], 'past_tense', word[:-1]))
        if len(base_ed) >= 2 and base_ed[-1] == base_ed[-2]:
            word_variants.append((base_ed[:-1], 'past_tense', base_ed[:-1]))

    # Множественное число
    if word.endswith('s') and not word.endswith('ss') and len(word) > 2:
        word_variants.append((word[:-1], 'plural', word[:-1]))
        if word.endswith('es'):
            word_variants.append((word[:-2], 'plural', word[:-2]))
        if word.endswith('ies'):
            word_variants.append((word[:-3] + 'y', 'plural', word[:-3] + 'y'))

    # Сравнительная степень -er
    if word.endswith('er') and len(word) > 3:
        base_er = word[:-2]
        word_variants.append((base_er, 'comparative', base_er))
        if len(base_er) >= 2 and base_er[-1] == base_er[-2]:
            word_variants.append((base_er[:-1], 'comparative', base_er[:-1]))
        if word.endswith('ier'):
            word_variants.append((word[:-3] + 'y', 'comparative', word[:-3] + 'y'))

    # Превосходная степень -est
    if word.endswith('est') and len(word) > 4:
        base_est = word[:-3]
        word_variants.append((base_est, 'superlative', base_est))
        if len(base_est) >= 2 and base_est[-1] == base_est[-2]:
            word_variants.append((base_est[:-1], 'superlative', base_est[:-1]))
        if word.endswith('iest'):
            word_variants.append((word[:-4] + 'y', 'superlative', word[:-4] + 'y'))

    # Один bulk-запрос для всех вариантов
    variant_words = [v[0] for v in word_variants]
    found_words = CollectionWords.query.filter(
        CollectionWords.english_word.in_(variant_words)
    ).all()

    # Создаём словарь найденных слов
    found_dict = {w.english_word: w for w in found_words}

    # Ищем первое совпадение в приоритетном порядке
    word_entry = None
    for variant, form_type, base_form in word_variants:
        if variant in found_dict:
            word_entry = found_dict[variant]
            if form_type:
                word_form_info = {'type': form_type, 'base_form': base_form}
                logger.debug(f"Нашли форму {form_type}: {word} -> {base_form}")
            break

    # Возвращаем перевод с дополнительной информацией о форме слова, если она есть
    if word_entry:
        # Получаем статус слова для пользователя
        status = current_user.get_word_status(word_entry.id)
        russian_translation = word_entry.russian_word

        # Добавляем продвинутые правила для русских слов без использования pymorphy2
        translation_variants = []

        # Пытаемся создать формы для русских слов на основе расширенных правил
        if russian_translation:
            # Разбиваем перевод на отдельные слова (если есть несколько через запятую)
            rus_words = [w.strip() for w in russian_translation.split(',')]

            for rus_word in rus_words:
                if not rus_word or len(rus_word) < 3:
                    continue  # Пропускаем слишком короткие слова

                # Используем правила для существительных
                if rus_word.endswith('а'):
                    # Женский род, первое склонение
                    if len(translation_variants) < 3:
                        plural = rus_word[:-1] + 'ы'  # стена -> стены
                        if rus_word[-2] in 'гкхжшщч':
                            plural = rus_word[:-1] + 'и'  # книга -> книги
                        translation_variants.append(f"{plural} (мн.ч.)")

                elif rus_word.endswith('я'):
                    if len(translation_variants) < 3:
                        plural = rus_word[:-1] + 'и'  # неделя -> недели
                        translation_variants.append(f"{plural} (мн.ч.)")

                elif rus_word.endswith('ь'):
                    if len(translation_variants) < 3:
                        plural = rus_word[:-1] + 'и'  # дверь -> двери
                        translation_variants.append(f"{plural} (мн.ч.)")

                elif rus_word.endswith('й'):
                    if len(translation_variants) < 3:
                        plural = rus_word[:-1] + 'и'  # музей -> музеи
                        translation_variants.append(f"{plural} (мн.ч.)")

                elif rus_word.endswith('о') or rus_word.endswith('е'):
                    if len(translation_variants) < 3:
                        if rus_word.endswith('о'):
                            plural = rus_word[:-1] + 'а'  # окно -> окна
                        else:
                            plural = rus_word[:-1] + 'я'  # поле -> поля
                        translation_variants.append(f"{plural} (мн.ч.)")

                # Добавляем правила для глаголов
                elif rus_word.endswith('ть'):
                    if len(translation_variants) < 3:
                        past_m = rus_word[:-2] + 'л'  # делать -> делал
                        translation_variants.append(f"{past_m} (прош. м.р.)")

                        if rus_word.endswith('ать'):
                            pres_1 = rus_word[:-3] + 'аю'  # делать -> делаю
                            translation_variants.append(f"{pres_1} (наст.)")
                        elif rus_word.endswith('ять'):
                            pres_1 = rus_word[:-3] + 'яю'  # гулять -> гуляю
                            translation_variants.append(f"{pres_1} (наст.)")
                        elif rus_word.endswith('еть'):
                            pres_1 = rus_word[:-3] + 'ею'  # болеть -> болею
                            translation_variants.append(f"{pres_1} (наст.)")
                        elif rus_word.endswith('ить'):
                            pres_1 = rus_word[:-3] + 'лю'  # любить -> люблю
                            translation_variants.append(f"{pres_1} (наст.)")

                # Ограничиваем количество вариантов до 3
                if len(translation_variants) >= 3:
                    break

        # Определяем текст для отображения информации о форме
        form_text = None
        if word_form_info:
            form_type = word_form_info['type']
            if form_type == 'past_tense':
                form_text = 'прошедшее время от'
            elif form_type == 'verb_form':
                form_text = 'форма глагола'
            elif form_type == 'plural':
                form_text = 'множественное число от'
            elif form_type == 'comparative':
                form_text = 'сравнительная степень от'
            elif form_type == 'superlative':
                form_text = 'превосходная степень от'
            elif form_type == 'continuous':
                form_text = 'длительная форма от'

        # Проверяем наличие аудио
        audio_url = None
        has_audio = word_entry.get_download == 1 and word_entry.listening
        if has_audio:
            audio_filename = word_entry.listening
            if audio_filename.startswith('audio/') and audio_filename.endswith('.mp3'):
                audio_filename = audio_filename[6:-4]  # Убираем 'audio/' и '.mp3'
                audio_url = url_for('static', filename=f'audio/{audio_filename}.mp3')

        # Проверяем, есть ли слово в колоде "Слова из чтения"
        from app.study.models import QuizDeck, QuizDeckWord
        in_reading_deck = False
        reading_deck = QuizDeck.query.filter_by(
            user_id=current_user.id,
            title="Слова из чтения"
        ).first()
        if reading_deck:
            in_reading_deck = QuizDeckWord.query.filter_by(
                deck_id=reading_deck.id,
                word_id=word_entry.id
            ).first() is not None

        # Формируем JSON-ответ
        response = {
            'word': original_word,
            'translation': russian_translation,
            'in_dictionary': True,
            'id': word_entry.id,
            'status': status,
            'is_form': word_form_info is not None,
            'form_text': form_text,
            'base_form': word_form_info['base_form'] if word_form_info else None,
            'has_audio': has_audio,
            'audio_url': audio_url,
            'in_reading_deck': in_reading_deck,
        }

        # Добавляем варианты перевода, если они есть
        if translation_variants:
            response['translation_variants'] = translation_variants

        logger.debug(f"Перевод найден: {response}")
        return jsonify(response)
    else:
        logger.debug(f"Перевод не найден для слова: {original_word}")
        return jsonify({
            'word': original_word,
            'translation': None,
            'in_dictionary': False
        })


@books_api.route('/api/add-to-learning', methods=['POST'])
@login_required
def add_to_learning():
    """API для добавления слова в очередь изучения и колоду 'Слова из чтения'"""
    from app.study.models import QuizDeck, QuizDeckWord

    data = request.get_json()
    word_id = data.get('word_id')

    if not word_id:
        return jsonify({'success': False, 'error': 'Word ID is required'}), 400

    word_entry = CollectionWords.query.get(word_id)

    if not word_entry:
        return jsonify({'success': False, 'error': 'Word not found in dictionary'}), 404

    current_status = current_user.get_word_status(word_id)
    was_new = current_status == 0

    # Если слово ещё не в изучении, добавляем
    if was_new:
        current_user.set_word_status(word_id, 1)  # 1 = queued for learning

    # Всегда добавляем в колоду "Слова из чтения" (даже если слово уже изучается)
    deck_title = "Слова из чтения"
    reading_deck = QuizDeck.query.filter_by(
        user_id=current_user.id,
        title=deck_title
    ).first()

    if not reading_deck:
        reading_deck = QuizDeck(
            title=deck_title,
            description="Слова, добавленные во время чтения книг и уроков",
            user_id=current_user.id,
            is_public=False
        )
        db.session.add(reading_deck)
        db.session.flush()

    # Проверяем, нет ли уже слова в колоде
    existing = QuizDeckWord.query.filter_by(
        deck_id=reading_deck.id,
        word_id=word_id
    ).first()

    added_to_deck = False
    if not existing:
        max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter(
            QuizDeckWord.deck_id == reading_deck.id
        ).scalar() or 0

        deck_word = QuizDeckWord(
            deck_id=reading_deck.id,
            word_id=word_id,
            order_index=max_order + 1
        )
        db.session.add(deck_word)
        added_to_deck = True

    db.session.commit()

    # Формируем ответ
    if was_new:
        return jsonify({
            'success': True,
            'message': 'Word added to learning queue',
            'new_status': 1
        })
    elif added_to_deck:
        return jsonify({
            'success': True,
            'message': 'Word added to reading deck',
            'status': current_status
        })
    else:
        return jsonify({
            'success': True,
            'message': 'Word is already in your list',
            'status': current_status
        })


@books_api.route('/api/save-reading-position', methods=['POST'])
@login_required
def save_reading_position():
    """
    Save user's reading position and award XP for chapter completion
    """
    from app.books.models import UserChapterProgress, Chapter

    data = request.json
    book_id = data.get('book_id')
    position = data.get('position', 0)  # 0.0 to 1.0
    chapter_num = data.get('chapter', 1)

    if not book_id:
        return jsonify({'success': False, 'message': 'Missing book_id'}), 400

    try:
        book_id = int(book_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid book_id'}), 400

    try:
        position = max(0.0, min(1.0, float(position)))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid position'}), 400

    # Get chapter
    chapter = Chapter.query.filter_by(book_id=book_id, chap_num=chapter_num).first()
    if not chapter:
        return jsonify({'success': False, 'message': 'Chapter not found'}), 404
    if not chapter.book.is_published and not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Chapter not found'}), 404

    # Lock existing progress row to serialize concurrent updates from
    # two tabs completing the same chapter. First insert wins via PK;
    # second request sees the row and advances offset_pct only.
    progress = (
        db.session.query(UserChapterProgress)
        .filter_by(user_id=current_user.id, chapter_id=chapter.id)
        .with_for_update()
        .first()
    )

    was_incomplete = not progress or progress.offset_pct < 1.0
    previous_offset = progress.offset_pct if progress else 0.0

    if not progress:
        try:
            with db.session.begin_nested():
                progress = UserChapterProgress(
                    user_id=current_user.id,
                    chapter_id=chapter.id,
                    offset_pct=position
                )
                db.session.add(progress)
        except IntegrityError:
            progress = (
                db.session.query(UserChapterProgress)
                .filter_by(user_id=current_user.id, chapter_id=chapter.id)
                .with_for_update()
                .first()
            )
            previous_offset = progress.offset_pct if progress else 0.0
            was_incomplete = not progress or progress.offset_pct < 1.0
            if progress:
                progress.offset_pct = max(progress.offset_pct or 0.0, position)
                progress.updated_at = datetime.now(UTC)
        db.session.flush()
    else:
        progress.offset_pct = max(progress.offset_pct or 0.0, position)
        progress.updated_at = datetime.now(UTC)
        db.session.flush()

    response_data = {'success': True}

    chapter_completed = was_incomplete and position >= 1.0
    chapter_xp_award = None
    if chapter_completed:
        from app.achievements.xp_service import award_book_chapter_xp_idempotent
        from app.utils.time_utils import get_user_local_date

        # Inlined former XPService.calculate_book_chapter_xp (constant 50 XP).
        BOOK_CHAPTER_XP = 50
        chapter_xp_award = award_book_chapter_xp_idempotent(
            user_id=current_user.id,
            book_id=book_id,
            chapter_id=chapter.id,
            xp=BOOK_CHAPTER_XP,
            for_date=get_user_local_date(current_user.id, db),
            db_session=db,
        )

    # Linear plan: award book-reading slot XP once per day when the
    # reading slot's completion threshold is crossed. Gated on the
    # user's UserReadingPreference — progress in any other book does
    # not satisfy the slot, matching the dashboard semantics "read
    # your chosen book today". Wrapped in a savepoint so a linear-path
    # failure doesn't roll back the book_chapter XP, keeping the outer
    # transaction atomic at the endpoint boundary.
    try:
        from app.daily_plan.linear.slots.reading_slot import (
            READ_PROGRESS_THRESHOLD,
            get_user_reading_preference,
        )
        from app.daily_plan.linear.xp import (
            maybe_award_book_reading_xp,
            maybe_award_linear_perfect_day,
        )
        # The reader auto-saves every ~3 seconds, so each save's delta is
        # tiny — gating on per-save delta would never fire for users reading
        # incrementally. Use the aggregated daily-target check (5min active
        # reading + 2% offset advance summed across pause-cycled sessions
        # today), plus absolute position past the threshold and forward
        # progress this save. This unifies XP and slot completion under the
        # same daily target.
        advanced = position - previous_offset
        if position >= READ_PROGRESS_THRESHOLD and advanced > 0:
            pref = get_user_reading_preference(current_user.id, db)
            if pref is not None and pref.book_id == book_id:
                from app.books.reading_session import is_daily_reading_target_met_today
                if is_daily_reading_target_met_today(current_user.id, book_id, db):
                    with db.session.begin_nested():
                        if maybe_award_book_reading_xp(current_user.id, db_session=db) is not None:
                            maybe_award_linear_perfect_day(current_user.id, db_session=db)
    except Exception:
        logger.warning(
            "linear_xp: book-reading award failed user=%s",
            current_user.id, exc_info=True,
        )

    # Book milestone (off-band notification, transient). Only checked when a
    # chapter just transitioned to fully completed — saves per-tick overhead.
    if chapter_completed:
        try:
            from app.books.progress import compute_book_progress_percent
            from app.daily_plan.milestones import check_book_milestone
            percent = compute_book_progress_percent(current_user.id, book_id, db)
            check_book_milestone(current_user.id, book_id, percent, db)
        except Exception:
            logger.warning(
                "book milestone check failed user=%s book=%s",
                current_user.id, book_id, exc_info=True,
            )

    db.session.commit()

    if chapter_completed:
        from app.achievements.xp_service import get_level_info
        from app.achievements.models import UserStatistics

        stats = UserStatistics.query.filter_by(user_id=current_user.id).first()
        total_xp = stats.total_xp if stats else 0
        level_info = get_level_info(total_xp)

        response_data.update({
            'chapter_completed': True,
            'xp_earned': chapter_xp_award.xp_awarded if chapter_xp_award else 0,
            'total_xp': total_xp,
            'level': level_info.current_level,
        })

    return jsonify(response_data)


# ============================================================================
# Reading session — time-on-page tracking for the linear plan reading slot
# ============================================================================

@books_api.route('/api/books/reading-session/start', methods=['POST'])
@login_required
def reading_session_start():
    """Open a reading session. Frontend calls this on chapter scroll-in."""
    from app.api.errors import api_error
    from app.books.reading_session import start_session

    data = request.get_json(silent=True) or {}
    chapter_id = data.get('chapter_id')
    if not chapter_id:
        return api_error('missing_chapter_id', 'chapter_id is required', 400)
    try:
        chapter_id = int(chapter_id)
    except (TypeError, ValueError):
        return api_error('invalid_chapter_id', 'invalid chapter_id', 400)

    chapter = Chapter.query.get(chapter_id)
    if chapter is None:
        return api_error('not_found', 'chapter not found', 404)
    if not chapter.book.is_published and not current_user.is_admin:
        return api_error('not_found', 'chapter not found', 404)

    session = start_session(current_user.id, chapter_id, db)
    db.session.commit()

    # Surface today's accumulated reading time for the book so the client
    # timer can seed itself instead of resetting to 00:00 on every chapter
    # transition.
    from app.books.reading_session import get_book_reading_seconds_today
    book_seconds_today = get_book_reading_seconds_today(
        current_user.id, chapter.book_id, db,
    )
    return jsonify({
        'success': True,
        'session_id': session.id,
        'book_seconds_today': book_seconds_today,
    })


@books_api.route('/api/books/reading-session/end', methods=['POST'])
@csrf.exempt
@login_required
def reading_session_end():
    """Close a reading session. Frontend calls this on page-leave/scroll-out.

    On `pagehide` the browser uses `navigator.sendBeacon`, which forces
    Content-Type to text/plain (or multipart). We accept both JSON and
    text/plain bodies and parse them as JSON. CSRF is exempted because the
    endpoint is gated by `@login_required` (session cookie required) and only
    operates on a session whose ownership is verified server-side.
    """
    import json as _json

    from app.api.errors import api_error
    from app.books.reading_session import end_session

    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(cache=False, as_text=True) or ''
        if raw:
            try:
                data = _json.loads(raw)
            except (ValueError, TypeError):
                data = None
    if not isinstance(data, dict):
        data = {}
    session_id = data.get('session_id')
    if not session_id:
        return api_error('missing_session_id', 'session_id is required', 400)
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return api_error('invalid_session_id', 'invalid session_id', 400)

    from app.books.reading_session import UserReadingSession

    existing = db.session.get(UserReadingSession, session_id)
    if existing is None:
        return api_error('not_found', 'session not found', 404)
    if existing.user_id != current_user.id:
        return api_error('forbidden', 'session does not belong to current user', 403)

    raw_hint = data.get('current_offset_pct')
    current_offset_hint: Optional[float] = None
    if raw_hint is not None:
        try:
            current_offset_hint = float(raw_hint)
        except (TypeError, ValueError):
            return api_error(
                'invalid_offset_delta',
                'current_offset_pct must be a number between 0 and 1',
                400,
            )
        if current_offset_hint < 0.0 or current_offset_hint > 1.0:
            return api_error(
                'invalid_offset_delta',
                'current_offset_pct must be between 0 and 1',
                400,
            )

    # Capture pre-close persisted offset so we can detect when the unload
    # hint is what pushes the chapter to 1.0. The /progress save path owns
    # chapter-completion XP, but a user who scrolls to 1.0 inside the
    # final 3s debounce window may leave before that fires — without this
    # check the hint silently writes 1.0 and the completion event/XP is
    # lost forever (later saves see was_incomplete=False).
    from app.books.models import UserChapterProgress

    pre_progress = (
        db.session.query(UserChapterProgress)
        .filter_by(user_id=current_user.id, chapter_id=existing.chapter_id)
        .first()
    )
    pre_offset = pre_progress.offset_pct if pre_progress else 0.0

    # Capture pre-close daily target state so we can detect the False→True
    # transition and fire vocab-pull for the first qualifying session today.
    was_target_met = False
    _pre_chapter = Chapter.query.get(existing.chapter_id)
    if _pre_chapter is not None:
        from app.books.reading_session import is_daily_reading_target_met_today as _check_target
        was_target_met = _check_target(current_user.id, _pre_chapter.book_id, db)

    session = end_session(session_id, db, current_offset_pct=current_offset_hint)
    db.session.commit()

    chapter = Chapter.query.get(session.chapter_id)
    post_progress = (
        db.session.query(UserChapterProgress)
        .filter_by(user_id=current_user.id, chapter_id=session.chapter_id)
        .first()
    )
    post_offset = post_progress.offset_pct if post_progress else 0.0

    if chapter is not None and pre_offset < 1.0 and post_offset >= 1.0:
        try:
            from app.achievements.xp_service import award_book_chapter_xp_idempotent
            from app.utils.time_utils import get_user_local_date

            BOOK_CHAPTER_XP = 50
            award_book_chapter_xp_idempotent(
                user_id=current_user.id,
                book_id=chapter.book_id,
                chapter_id=chapter.id,
                xp=BOOK_CHAPTER_XP,
                for_date=get_user_local_date(current_user.id, db),
                db_session=db,
            )
            db.session.commit()
        except Exception:
            logger.warning(
                "chapter_xp: hint-completed award failed user=%s chapter=%s",
                current_user.id, chapter.id, exc_info=True,
            )
            db.session.rollback()

    # Closing the session may itself push the user past the daily reading
    # target; re-run the slot-award check so a qualifying day credits the
    # reading slot without waiting for the next progress save.
    reading_slot_completed = False
    try:
        from app.daily_plan.linear.slots.reading_slot import get_user_reading_preference
        from app.daily_plan.linear.xp import (
            maybe_award_book_reading_xp,
            maybe_award_linear_perfect_day,
        )
        from app.books.reading_session import is_daily_reading_target_met_today

        chapter = Chapter.query.get(session.chapter_id)
        # Daily target = 5min active reading + 2% offset advance in any
        # chapter of the user's selected book today, aggregated across
        # pause-cycled sessions. The reader debounces progress saves by 3s,
        # so on page-leave the persisted offset may still trail the
        # session's own snapshot+hint; we already applied the hint above,
        # so the aggregated check sees the current authoritative state.
        if chapter is not None:
            pref = get_user_reading_preference(current_user.id, db)
            if pref is not None and pref.book_id == chapter.book_id:
                if is_daily_reading_target_met_today(current_user.id, chapter.book_id, db):
                    if maybe_award_book_reading_xp(current_user.id, db_session=db) is not None:
                        maybe_award_linear_perfect_day(current_user.id, db_session=db)
                        db.session.commit()
                        reading_slot_completed = True
    except Exception:
        logger.warning(
            "linear_xp: reading-session-end award failed user=%s",
            current_user.id, exc_info=True,
        )
        db.session.rollback()

    # Compute banner state for the client. Banner is gated on the
    # currently-read book matching the user's reading preference: the
    # daily-plan reading slot is per-preference, and a misleading
    # "норма выполнена" on a non-preference book would not actually
    # close the slot on the dashboard.
    from app.books.reading_session import compute_chapter_daily_target_state
    from app.daily_plan.linear.slots.reading_slot import get_user_reading_preference as _get_pref

    banner_state = 'none'
    daily_target_met_today = False
    chapter_completed_in_session = False
    state = None
    try:
        pref_for_banner = _get_pref(current_user.id, db)
        is_preference_book = (
            chapter is not None
            and pref_for_banner is not None
            and pref_for_banner.book_id == chapter.book_id
        )
        if is_preference_book:
            # Per-book daily target: checked before state computation so that
            # an exception in compute_chapter_daily_target_state does not
            # silently suppress the vocab-pull that follows.
            daily_target_met_today = is_daily_reading_target_met_today(
                current_user.id, chapter.book_id, db
            )
            state = compute_chapter_daily_target_state(
                current_user.id, session.chapter_id, db
            )
            chapter_completed_in_session = state['chapter_completed_today']
            if daily_target_met_today and chapter_completed_in_session:
                banner_state = 'both'
            elif daily_target_met_today:
                banner_state = 'daily_target'
            elif chapter_completed_in_session:
                banner_state = 'chapter_completed'
    except Exception:
        logger.warning(
            "reading-banner: state compute failed user=%s session=%s",
            current_user.id, session.id, exc_info=True,
        )

    # Vocab pull: on daily-target transition (False → True) extract unlearned
    # words from the just-read chapter slice and queue them as SRS cards.
    queued_vocab_count = 0
    if not was_target_met and daily_target_met_today and chapter is not None:
        try:
            from app.books.vocab_pull import extract_chapter_vocab, queue_vocab_as_srs
            start_off = state['earliest_start_offset'] if state else 0.0
            end_off = state['current_offset'] if state else 1.0
            words = extract_chapter_vocab(
                session.chapter_id, start_off, end_off, current_user.id, db
            )
            queued_vocab_count = queue_vocab_as_srs(words, current_user.id, db)
            if queued_vocab_count:
                db.session.commit()
        except Exception:
            logger.warning(
                "vocab_pull: failed user=%s chapter=%s",
                current_user.id, session.chapter_id, exc_info=True,
            )
            db.session.rollback()

    # Daily-plan context for the banner CTAs. When the reader was opened
    # from a daily-plan slot link (?from=linear_plan&slot=book) and the
    # Referer survives the XHR, build_lesson_context resolves the next
    # plan slot; otherwise dashboard-only CTAs are used.
    next_slot_url = None
    next_slot_title = None
    dashboard_url = None
    try:
        from flask import url_for as _url_for
        from app.daily_plan.linear.lesson_context import build_lesson_context
        ctx = build_lesson_context(current_user.id, db)
        dashboard_url = ctx.dashboard_url
        if ctx.is_daily_plan:
            next_slot_url = ctx.next_slot_url
            next_slot_title = ctx.next_slot_title
        else:
            dashboard_url = _url_for('words.dashboard')
    except Exception:
        logger.warning(
            "reading-banner: lesson-context build failed user=%s",
            current_user.id, exc_info=True,
        )

    return jsonify({
        'success': True,
        'session_id': session.id,
        'duration_seconds': session.duration_seconds(),
        'reading_slot_completed': reading_slot_completed,
        'daily_target_met': daily_target_met_today,
        'chapter_completed_in_session': chapter_completed_in_session,
        'banner_state': banner_state,
        'next_slot_url': next_slot_url,
        'next_slot_title': next_slot_title,
        'dashboard_url': dashboard_url,
        'queued_vocab_count': queued_vocab_count,
    })
