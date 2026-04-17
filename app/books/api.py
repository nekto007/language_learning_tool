# app/books/api.py
# API endpoints for the books module (extracted from routes.py)

import collections
import inspect
import logging
import os
import sys

from datetime import UTC, datetime

from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

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
    """Serve audio file for a book chapter."""
    from flask import send_file
    chapter = Chapter.query.filter_by(book_id=book_id, chap_num=chapter_num).first_or_404()
    if not chapter.audio_url:
        return 'No audio available', 404
    # Resolve path relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    audio_path = os.path.join(project_root, chapter.audio_url)
    if not os.path.isfile(audio_path):
        logger.warning(f"Audio file not found: {audio_path}")
        return 'Audio file not found', 404
    return send_file(audio_path, mimetype='audio/mpeg')


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
    from app.study.xp_service import XPService

    data = request.json
    book_id = data.get('book_id')
    position = data.get('position', 0)  # 0.0 to 1.0
    chapter_num = data.get('chapter', 1)

    if not book_id:
        return jsonify({'success': False, 'message': 'Missing book_id'}), 400

    # Get chapter
    chapter = Chapter.query.filter_by(book_id=book_id, chap_num=chapter_num).first()
    if not chapter:
        return jsonify({'success': False, 'message': 'Chapter not found'}), 404

    # Check if chapter was previously incomplete
    progress = UserChapterProgress.query.filter_by(
        user_id=current_user.id,
        chapter_id=chapter.id
    ).first()

    was_incomplete = not progress or progress.offset_pct < 1.0

    # Update or create progress
    if not progress:
        progress = UserChapterProgress(
            user_id=current_user.id,
            chapter_id=chapter.id,
            offset_pct=position
        )
        db.session.add(progress)
    else:
        progress.offset_pct = position
        progress.updated_at = datetime.now(UTC)

    db.session.commit()

    response_data = {'success': True}

    # Award XP if chapter just completed (was incomplete, now complete)
    if was_incomplete and position >= 1.0:
        xp_breakdown = XPService.calculate_book_chapter_xp()
        user_xp = XPService.award_xp(current_user.id, xp_breakdown['total_xp'])

        response_data.update({
            'chapter_completed': True,
            'xp_earned': xp_breakdown['total_xp'],
            'total_xp': user_xp.total_xp,
            'level': user_xp.level
        })

    return jsonify(response_data)
