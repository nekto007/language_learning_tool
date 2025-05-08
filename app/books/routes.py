# app/books/routes.py

import inspect
import logging
import os
import re
import sys
import threading
import uuid
from datetime import datetime

from PIL import Image
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename
from wtforms.fields.choices import SelectField
from wtforms.fields.simple import StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional

from app.books.forms import BookContentForm
from app.books.models import Book, ReadingProgress
from app.books.parsers import process_uploaded_book
from app.books.processors import enqueue_book_processing, process_book_words
from app.study.models import UserWord
from app.utils.db import db, word_book_link
from app.utils.decorators import admin_required
from app.words.models import CollectionWords

books = Blueprint('books', __name__)

project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_dir not in sys.path:
    sys.path.append(project_dir)

morph = None

logger = logging.getLogger(__name__)

# Configuration for book cover images
COVER_UPLOAD_FOLDER = 'app/static/uploads/covers'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_COVER_WIDTH = 400
MAX_COVER_HEIGHT = 600
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Ensure upload directory exists
os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    """Check if the file has an allowed extension"""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_cover_image(file):
    """
    Сохраняет и обрабатывает обложку книги

    Args:
        file: Объект загруженного файла

    Returns:
        str: Имя сохраненного файла или None в случае ошибки
    """
    # Проверяем, что file не None и имеет атрибут filename
    if not file or not hasattr(file, 'filename'):
        return None

    if file and allowed_file(file.filename):
        # Проверка размера файла
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_FILE_SIZE:
            flash('File size exceeds maximum limit of 5MB', 'danger')
            return None

        try:
            # Генерация уникального имени файла
            original_filename = secure_filename(file.filename)
            extension = original_filename.rsplit('.', 1)[1].lower()
            unique_filename = f"{uuid.uuid4().hex}.{extension}"
            filepath = os.path.join(COVER_UPLOAD_FOLDER, unique_filename)

            # Создаем директорию, если она не существует
            os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)

            # Сохраняем исходный файл временно
            file.save(filepath)

            # Обрабатываем изображение с Pillow
            with Image.open(filepath) as img:
                # Преобразуем в RGB, если необходимо
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3] if img.split()[3] else None)
                    img = background

                # Изменяем размер при необходимости, сохраняя пропорции
                img_width, img_height = img.size
                if img_width > MAX_COVER_WIDTH or img_height > MAX_COVER_HEIGHT:
                    ratio = min(MAX_COVER_WIDTH / img_width, MAX_COVER_HEIGHT / img_height)
                    new_width = int(img_width * ratio)
                    new_height = int(img_height * ratio)
                    img = img.resize((new_width, new_height), Image.LANCZOS)

                # Сохраняем обработанное изображение
                img.save(filepath, quality=85, optimize=True)

            return f"uploads/covers/{unique_filename}"

        except Exception as e:
            logger.error(f"Error processing cover image: {str(e)}")
            # Очищаем временный файл при ошибке
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except:
                    pass
            return None

    return None


@books.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_book():
    """
    Страница для добавления новой книги
    """
    form = BookContentForm()

    if form.validate_on_submit():
        try:
            # Создаем новую книгу с основными данными
            new_book = Book(
                title=form.title.data,
                author=form.author.data,
                level=form.level.data,
                scrape_date=datetime.utcnow()
            )

            # Обрабатываем обложку, если она загружена
            if form.cover_image.data and hasattr(form.cover_image.data, 'filename'):
                cover_filename = save_cover_image(form.cover_image.data)
                if cover_filename:
                    new_book.cover_image = cover_filename

            # Если был загружен файл контента, обрабатываем его
            if form.file.data and hasattr(form.file.data, 'filename'):
                try:
                    # Обрабатываем файл с помощью функции из parsers.py
                    result = process_uploaded_book(
                        file=form.file.data,
                        title=form.title.data,
                        format_type=form.format_type.data
                    )

                    # Сохраняем результаты
                    new_book.content = result['content']
                    new_book.total_words = result['word_count']
                    new_book.unique_words = result['unique_words']

                except Exception as e:
                    flash(f'Error processing file: {str(e)}', 'danger')
                    return render_template('books/add.html', form=form)

            elif form.content.data:
                # Если контент был введен вручную
                content = form.content.data

                # Нормализуем текст
                content = re.sub(r'\s+', ' ', content)

                # Преобразуем простой текст в HTML с форматированием абзацев
                paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
                content_html = '<p>' + '</p><p>'.join(paragraphs) + '</p>'

                # Подсчитываем статистику слов
                words = re.findall(r'\b[a-zA-Z]+\b', content.lower())
                new_book.content = content_html
                new_book.total_words = len(words)
                new_book.unique_words = len(set(words))

            # Сохраняем книгу в базу данных
            db.session.add(new_book)
            db.session.commit()

            # ВАЖНО: Теперь запускаем обработку слов в отдельном потоке без ожидания
            if new_book.content:
                # Сохраняем ID книги и запускаем обработку асинхронно в отдельном потоке
                book_id = new_book.id

                # Используем исключительно threading.Thread с daemon=True
                def start_processing():
                    try:
                        # Используем простую постановку в очередь
                        process_book_words(new_book.id, new_book.content)
                    except Exception as e:
                        logger.error(f"Ошибка при запуске обработки слов: {str(e)}")

                # Запускаем поток и не ждем его завершения
                processing_thread = threading.Thread(target=start_processing)
                processing_thread.daemon = True
                processing_thread.start()

                # Сразу возвращаем ответ пользователю
                flash('Book added successfully! Word processing has been started in the background.', 'success')
            else:
                flash('Book added successfully!', 'success')

            return redirect(url_for('books.book_details', book_id=new_book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error saving book: {str(e)}', 'danger')

    return render_template('books/add.html', form=form)


# 2. Аналогично модифицируем метод edit_book_content
@books.route('/content/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book_content(book_id):
    """
    Страница для редактирования содержимого книги
    """
    book = Book.query.get_or_404(book_id)
    form = BookContentForm(obj=book)

    if form.validate_on_submit():
        try:
            # Обновляем основные данные книги
            book.title = form.title.data
            book.author = form.author.data
            book.level = form.level.data

            # Процесс обложки книги
            if form.cover_image.data and hasattr(form.cover_image.data, 'filename'):
                cover_filename = save_cover_image(form.cover_image.data)
                if cover_filename:
                    # Удаляем старую обложку, если она существует
                    if book.cover_image:
                        old_cover_path = os.path.join(COVER_UPLOAD_FOLDER, book.cover_image)
                        if os.path.exists(old_cover_path):
                            try:
                                os.remove(old_cover_path)
                            except Exception as e:
                                logger.error(f"Error removing old cover: {str(e)}")

                    book.cover_image = cover_filename

            # Обработка файла содержимого книги
            content_changed = False
            old_content = book.content

            if form.file.data and hasattr(form.file.data, 'filename'):
                try:
                    # Обрабатываем файл
                    result = process_uploaded_book(
                        file=form.file.data,
                        title=form.title.data,
                        format_type=form.format_type.data
                    )

                    # Сохраняем результаты
                    book.content = result['content']
                    book.total_words = result['word_count']
                    book.unique_words = result['unique_words']
                    content_changed = True

                except Exception as e:
                    flash(f'Error processing file: {str(e)}', 'danger')
                    return render_template('books/add.html', form=form, book=book)

            elif form.content.data:
                # Если контент был отредактирован вручную
                content = form.content.data

                # Проверяем, изменился ли контент
                if content != old_content:
                    # Преобразуем простой текст в HTML с форматированием абзацев, если это не HTML
                    if not content.strip().startswith('<'):
                        content_html = '<p>' + '</p><p>'.join(content.split('\n\n')) + '</p>'
                        content_html = content_html.replace('\n', '<br>')
                    else:
                        content_html = content

                    # Подсчитываем статистику слов
                    words = re.findall(r'\b[a-zA-Z]+\b', re.sub(r'<[^>]+>', '', content).lower())
                    book.content = content_html
                    book.total_words = len(words)
                    book.unique_words = len(set(words))
                    content_changed = True

            # Сохраняем изменения
            db.session.commit()

            # ВАЖНО: Теперь запускаем обработку слов в отдельном потоке без ожидания
            if content_changed and book.content:
                # Запускаем обработку асинхронно в отдельном потоке
                book_content = book.content  # Сохраняем копию контента

                def start_processing():
                    try:
                        # Используем простую постановку в очередь
                        enqueue_book_processing(book_id, book_content)
                    except Exception as e:
                        logger.error(f"Ошибка при запуске обработки слов: {str(e)}")

                # Запускаем поток и не ждем его завершения
                processing_thread = threading.Thread(target=start_processing)
                processing_thread.daemon = True
                processing_thread.start()

                # Сразу возвращаем ответ пользователю
                flash('Book content updated successfully! Word processing has been started in the background.',
                      'success')
            else:
                flash('Book content updated successfully!', 'success')

            return redirect(url_for('books.book_details', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating book: {str(e)}', 'danger')

    # Заполняем форму существующими данными
    if not form.content.data and book.content:
        form.content.data = book.content

    return render_template('books/add.html', form=form, book=book, is_edit=True)


@books.route('/reprocess-words/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def reprocess_book_words(book_id):
    """
    Запускает повторную обработку слов для существующей книги
    """
    book = Book.query.get_or_404(book_id)

    if not book.content:
        flash('This book has no content to process.', 'warning')
        return redirect(url_for('books.book_details', book_id=book_id))

    # Запускаем обработку слов
    processing_result = enqueue_book_processing(book.id, book.content)

    if processing_result.get("status") == "already_processing":
        flash('This book is already being processed.', 'info')
    elif processing_result.get("async", False):
        flash('Word processing has been queued in background.', 'success')
    elif processing_result.get("sync", False) and processing_result.get("status") == "success":
        flash('Words were processed successfully!', 'success')
    else:
        flash(f'Word processing: {processing_result.get("message", "started")}', 'info')

    return redirect(url_for('books.book_details', book_id=book_id))


@books.route('/upload-cover/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def upload_cover(book_id):
    """
    API для загрузки обложки книги
    """
    book = Book.query.get_or_404(book_id)

    if 'cover_image' not in request.files:
        flash('No file selected', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

    file = request.files['cover_image']

    if file.filename == '':
        flash('No file selected', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

    # Проверяем, что файл имеет атрибут filename
    if not hasattr(file, 'filename'):
        flash('Invalid file object', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

    # Обрабатываем и сохраняем обложку
    cover_filename = save_cover_image(file)

    if cover_filename:
        # Удаляем старую обложку, если она существует
        if book.cover_image:
            old_cover_path = os.path.join(COVER_UPLOAD_FOLDER, book.cover_image)
            if os.path.exists(old_cover_path):
                try:
                    os.remove(old_cover_path)
                except Exception as e:
                    logger.error(f"Error removing old cover: {str(e)}")

        # Обновляем обложку книги в базе данных
        book.cover_image = cover_filename
        db.session.commit()
        flash('Book cover updated successfully!', 'success')

    return redirect(url_for('books.book_details', book_id=book_id))


@books.route('/read/<int:book_id>')
@login_required
def read_book(book_id):
    """
    Page for reading a book
    """
    book = Book.query.get_or_404(book_id)

    # Check if content exists
    if not book.content:
        flash('This book has no content yet. Please add content first.', 'warning')
        return redirect(url_for('books.edit_book_content', book_id=book.id))

    # Get or create reading progress
    progress = ReadingProgress.query.filter_by(
        user_id=current_user.id,
        book_id=book_id
    ).first()

    if not progress:
        progress = ReadingProgress(
            user_id=current_user.id,
            book_id=book_id
        )
        db.session.add(progress)
        db.session.commit()
    else:
        # Update last read date
        progress.last_read = datetime.utcnow()
        db.session.commit()

    return render_template('books/read.html', book=book, progress=progress)


@books.route('/api/save-progress', methods=['POST'])
@login_required
def save_progress():
    """
    API for saving reading progress
    """
    data = request.get_json()
    book_id = data.get('book_id')
    position = data.get('position')

    if not book_id or position is None:
        return jsonify({'success': False, 'error': 'Missing required data'}), 400

    progress = ReadingProgress.query.filter_by(
        user_id=current_user.id,
        book_id=book_id
    ).first()

    if not progress:
        progress = ReadingProgress(
            user_id=current_user.id,
            book_id=book_id
        )
        db.session.add(progress)

    progress.position = position
    progress.last_read = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True})


def get_word_base_form(word):
    """
    Simple function to get the base form of a word without using NLTK
    Returns a tuple (base_form, form_type) or (None, None) if not found
    """
    word = word.lower().strip()

    # Dictionary of irregular verbs (past -> base form)
    irregular_verbs = {
        # Past forms -> base form
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
    if word in irregular_verbs:
        return irregular_verbs[word], 'past_tense'

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
        # В идеале здесь нужно проверить в словаре, но для простого решения
        # предполагаем, что если слово короткое и не имеет двойной согласной,
        # то нужно добавить 'e'
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
        import collections

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


@books.route('/api/word-translation/<word>')
@login_required
def get_word_translation(word):
    """
    API для получения перевода слова с определением его формы
    Работает полностью без использования pymorphy2, но с продвинутым
    анализом форм слов на основе правил
    """
    # Логгируем запрос для отладки
    logger.debug(f"Запрос перевода слова: {word}")

    word = word.lower().strip()
    original_word = word

    # Сначала пробуем найти точное совпадение в базе
    word_entry = CollectionWords.query.filter_by(english_word=word).first()

    # Отслеживаем, используем ли мы другую форму слова
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

        # Если всё ещё не нашли, используем морфологические правила
        if not word_entry:
            logger.debug(f"Используем морфологические правила для '{word}'")

            # 1. Проверяем на формы -ing
            if word.endswith('ing') and len(word) > 4:
                # Пробуем удалить 'ing'
                base_form = word[:-3]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                # Пробуем с 'e' (writing -> write)
                if not word_entry:
                    base_form_e = base_form + 'e'
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_e).first()
                    if word_entry:
                        base_form = base_form_e

                # Пробуем с двойными согласными (running -> run)
                if not word_entry and len(base_form) >= 2 and base_form[-1] == base_form[-2]:
                    base_form_single = base_form[:-1]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_single).first()
                    if word_entry:
                        base_form = base_form_single

                if word_entry:
                    logger.debug(f"Нашли -ing форму: {word} -> {base_form}")
                    word_form_info = {'type': 'continuous', 'base_form': base_form}

            # 2. Проверяем на формы -ed
            if not word_entry and word.endswith('ed') and len(word) > 3:
                # Пробуем удалить 'ed'
                base_form = word[:-2]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                # Пробуем с 'e' (liked -> like)
                if not word_entry:
                    base_form_e = word[:-1]  # Убираем только 'd'
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_e).first()
                    if word_entry:
                        base_form = base_form_e

                # Пробуем с двойными согласными (stopped -> stop)
                if not word_entry and len(base_form) >= 2 and base_form[-1] == base_form[-2]:
                    base_form_single = base_form[:-1]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_single).first()
                    if word_entry:
                        base_form = base_form_single

                if word_entry:
                    logger.debug(f"Нашли -ed форму: {word} -> {base_form}")
                    word_form_info = {'type': 'past_tense', 'base_form': base_form}

            # 3. Проверяем на множественное число
            if not word_entry and word.endswith('s') and not word.endswith('ss') and len(word) > 2:
                # Регулярное множественное число (cars -> car)
                base_form = word[:-1]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                # Проверяем на -es (boxes -> box)
                if not word_entry and word.endswith('es'):
                    base_form_es = word[:-2]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_es).first()
                    if word_entry:
                        base_form = base_form_es

                # Проверяем на -ies (flies -> fly)
                if not word_entry and word.endswith('ies'):
                    base_form_ies = word[:-3] + 'y'
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_ies).first()
                    if word_entry:
                        base_form = base_form_ies

                if word_entry:
                    logger.debug(f"Нашли множественное число: {word} -> {base_form}")
                    word_form_info = {'type': 'plural', 'base_form': base_form}

            # 4. Проверяем на сравнительную и превосходную степени прилагательных
            if not word_entry and word.endswith('er') and len(word) > 3:
                # Сравнительная степень (bigger -> big)
                base_form = word[:-2]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                # Проверяем на двойную согласную
                if not word_entry and len(base_form) >= 2 and base_form[-1] == base_form[-2]:
                    base_form_single = base_form[:-1]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_single).first()
                    if word_entry:
                        base_form = base_form_single

                # Проверяем на -ier (easier -> easy)
                if not word_entry and word.endswith('ier'):
                    base_form_y = word[:-3] + 'y'
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_y).first()
                    if word_entry:
                        base_form = base_form_y

                if word_entry:
                    logger.debug(f"Нашли сравнительную степень: {word} -> {base_form}")
                    word_form_info = {'type': 'comparative', 'base_form': base_form}

            if not word_entry and word.endswith('est') and len(word) > 4:
                # Превосходная степень (biggest -> big)
                base_form = word[:-3]
                word_entry = CollectionWords.query.filter_by(english_word=base_form).first()

                # Проверяем на двойную согласную
                if not word_entry and len(base_form) >= 2 and base_form[-1] == base_form[-2]:
                    base_form_single = base_form[:-1]
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_single).first()
                    if word_entry:
                        base_form = base_form_single

                # Проверяем на -iest (easiest -> easy)
                if not word_entry and word.endswith('iest'):
                    base_form_y = word[:-4] + 'y'
                    word_entry = CollectionWords.query.filter_by(english_word=base_form_y).first()
                    if word_entry:
                        base_form = base_form_y

                if word_entry:
                    logger.debug(f"Нашли превосходную степень: {word} -> {base_form}")
                    word_form_info = {'type': 'superlative', 'base_form': base_form}

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
                    # Женский род, первое склонение с мягким знаком
                    if len(translation_variants) < 3:
                        plural = rus_word[:-1] + 'и'  # неделя -> недели
                        translation_variants.append(f"{plural} (мн.ч.)")

                elif rus_word.endswith('ь'):
                    # Мужской или женский род, третье склонение
                    if len(translation_variants) < 3:
                        plural = rus_word[:-1] + 'и'  # дверь -> двери
                        translation_variants.append(f"{plural} (мн.ч.)")

                elif rus_word.endswith('й'):
                    # Мужской род с й на конце
                    if len(translation_variants) < 3:
                        plural = rus_word[:-1] + 'и'  # музей -> музеи
                        translation_variants.append(f"{plural} (мн.ч.)")

                elif rus_word.endswith('о') or rus_word.endswith('е'):
                    # Средний род
                    if len(translation_variants) < 3:
                        if rus_word.endswith('о'):
                            plural = rus_word[:-1] + 'а'  # окно -> окна
                        else:
                            plural = rus_word[:-1] + 'я'  # поле -> поля
                        translation_variants.append(f"{plural} (мн.ч.)")

                # Добавляем правила для глаголов
                elif rus_word.endswith('ть'):
                    # Это может быть глагол в инфинитиве
                    if len(translation_variants) < 3:
                        # Прошедшее время, мужской род
                        past_m = rus_word[:-2] + 'л'  # делать -> делал
                        translation_variants.append(f"{past_m} (прош. м.р.)")

                        # Настоящее время, 1-е лицо ед. число
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
            # Форматируем информацию о форме для отображения
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
        }

        # Добавляем варианты перевода, если они есть
        if translation_variants:
            response['translation_variants'] = translation_variants

        # Логируем успешный перевод
        logger.debug(f"Перевод найден: {response}")
        return jsonify(response)
    else:
        logger.debug(f"Перевод не найден для слова: {original_word}")
        return jsonify({
            'word': original_word,
            'translation': None,
            'in_dictionary': False
        })


@books.route('/api/add-to-learning', methods=['POST'])
@login_required
def add_to_learning():
    """
    API for adding a word to the learning queue
    """
    data = request.get_json()
    word_id = data.get('word_id')

    if not word_id:
        return jsonify({'success': False, 'error': 'Word ID is required'}), 400

    word_entry = CollectionWords.query.get(word_id)

    if not word_entry:
        return jsonify({'success': False, 'error': 'Word not found in dictionary'}), 404

    # Get current word status
    current_status = current_user.get_word_status(word_id)

    # If the word is not yet queued for learning (status 0), add it (status 2)
    if current_status == 0:
        current_user.set_word_status(word_id, 1)  # 1 = queued for learning
        return jsonify({
            'success': True,
            'message': 'Word added to learning queue',
            'new_status': 1
        })
    else:
        # Word already has a status
        return jsonify({
            'success': True,
            'message': 'Word is already in your list',
            'status': current_status
        })


@books.route('/books')
@login_required
def book_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    # Get sorting parameters
    sort_by = request.args.get('sort', 'title')
    sort_order = request.args.get('order', 'asc')

    # Get filter parameters
    search_query = request.args.get('search', '')
    level_filter = request.args.get('level', '')
    letter_filter = request.args.get('letter', '')

    # Build base query
    query = db.select(Book)

    # Apply filters
    if search_query:
        search_term = f"%{search_query}%"
        # Search in both title and author
        query = query.where(
            db.or_(
                Book.title.ilike(search_term),
                Book.author.ilike(search_term)
            )
        )

    if level_filter:
        query = query.where(Book.level == level_filter)

    if letter_filter:
        # Filter by first letter of title
        query = query.where(Book.title.ilike(f"{letter_filter}%"))

    # Apply sorting
    if sort_by == 'title':
        query = query.order_by(Book.title.desc() if sort_order == 'desc' else Book.title)
    elif sort_by == 'author':
        query = query.order_by(Book.author.desc() if sort_order == 'desc' else Book.author)
    elif sort_by == 'level':
        query = query.order_by(Book.level.desc() if sort_order == 'desc' else Book.level)
    elif sort_by == 'unique_words':
        query = query.order_by(Book.unique_words.desc() if sort_order == 'desc' else Book.unique_words)
    else:
        # Default sorting
        query = query.order_by(Book.title)
        sort_by = 'title'
        sort_order = 'asc'

    # Execute paginated query
    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    book_items = pagination.items

    # Get word stats for each book
    book_stats = {}
    for book in book_items:
        # Обновляем запрос статистики на использование новой модели UserWord
        words_status_query = db.select(
            func.count().label('count'),
            UserWord.status
        ).select_from(
            word_book_link
        ).join(
            UserWord,
            (word_book_link.c.word_id == UserWord.word_id) &
            (UserWord.user_id == current_user.id)
        ).where(
            word_book_link.c.book_id == book.id
        ).group_by(
            UserWord.status
        )

        word_status_counts = db.session.execute(words_status_query).all()

        # Initialize statistics
        stats = {
            'total': book.unique_words,
            'new': book.unique_words,  # По умолчанию все слова считаем новыми, потом вычтем изученные
            'learning': 0,
            'review': 0,  # Добавляем статус 'review'
            'mastered': 0
        }

        # Обновляем статистику с учетом строковых статусов вместо числовых
        for count, status in word_status_counts:
            if status in stats:
                stats[status] = count
                # Если у слова есть статус (кроме 'new'), вычитаем из 'new'
                if status != 'new':
                    stats['new'] -= count

        book_stats[book.id] = stats

    return render_template(
        'books/list.html',
        books=book_items,
        pagination=pagination,
        book_stats=book_stats,
        sort_by=sort_by,
        sort_order=sort_order
    )


@books.route('/books/<int:book_id>')
@login_required
def book_details(book_id):
    book = Book.query.get_or_404(book_id)

    # Получаем статистику по словам используя новую модель UserWord
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

    status_counts = db.session.execute(word_stats_query).all()

    # Инициализируем словарь статистики
    word_stats = {
        'total': book.unique_words,
        'new': book.unique_words,  # По умолчанию все слова считаем новыми, потом вычтем изученные
        'learning': 0,
        'review': 0,   # Добавляем статус 'review'
        'mastered': 0
    }

    # Обновляем статистику с реальными данными
    for status, count in status_counts:
        if status in word_stats:
            word_stats[status] = count
            # Если у слова есть статус, вычитаем его из 'new'
            if status != 'new':
                word_stats['new'] -= count

    # Расчет процента прогресса
    if book.unique_words > 0:
        progress = int(((word_stats['mastered']) / book.unique_words) * 100)
    else:
        progress = 0

    # Get most frequent words in this book
    frequent_words_query = db.select(
        CollectionWords,
        word_book_link.c.frequency
    ).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).where(
        word_book_link.c.book_id == book_id
    ).order_by(
        desc(word_book_link.c.frequency)
    ).limit(20)

    frequent_words = db.session.execute(frequent_words_query).all()

    # Get word statuses
    word_statuses = {}
    for word, _ in frequent_words:
        word_statuses[word.id] = current_user.get_word_status(word.id)

    return render_template(
        'books/details.html',
        book=book,
        word_stats=word_stats,
        progress=progress,
        frequent_words=frequent_words,
        word_statuses=word_statuses
    )


@books.route('/books/<int:book_id>/words')
@login_required
def book_words(book_id):
    book = Book.query.get_or_404(book_id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    status = request.args.get('status', type=int)

    query = db.session.query(CollectionWords, word_book_link.c.frequency).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).filter(
        word_book_link.c.book_id == book_id
    )

    # Фильтрация по статусу
    if status is not None:
        from app.study.models import UserWord
        from app.utils.db import status_to_string

        status_str = status_to_string(status)

        if status == 0:  # Новые слова
            # Слова без записи в UserWord
            subquery = db.select(UserWord.word_id).where(
                UserWord.user_id == current_user.id
            ).scalar_subquery()

            query = query.where(CollectionWords.id.not_in(subquery))
        else:
            # Слова с определенным статусом
            query = query.join(
                UserWord,
                (CollectionWords.id == UserWord.word_id) &
                (UserWord.user_id == current_user.id)
            ).where(UserWord.status == status_str)

    # Apply sorting
    sort_by = request.args.get('sort', 'frequency')
    sort_order = request.args.get('order', 'desc')

    if sort_by == 'frequency':
        query = query.order_by(
            desc(word_book_link.c.frequency) if sort_order == 'desc'
            else word_book_link.c.frequency
        )
    elif sort_by == 'english_word':
        query = query.order_by(
            CollectionWords.english_word.desc() if sort_order == 'desc'
            else CollectionWords.english_word
        )
    elif sort_by == 'level':
        query = query.order_by(
            CollectionWords.level.desc() if sort_order == 'desc'
            else CollectionWords.level
        )

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    book_words = pagination.items

    word_statuses = {}

    for item in book_words:
        word = item[0]

        word_statuses[word.id] = current_user.get_word_status(word.id)

    return render_template(
        'books/words.html',
        book=book,
        book_words=book_words,
        pagination=pagination,
        word_statuses=word_statuses,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order
    )


@books.route('/books/<int:book_id>/add-to-queue', methods=['POST'])
@login_required
def add_book_to_queue(book_id):
    book = Book.query.get_or_404(book_id)

    # Находим слова этой книги, которые еще не в изучении
    words_query = db.select(
        CollectionWords.id
    ).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).where(
        word_book_link.c.book_id == book_id
    ).outerjoin(
        UserWord,
        (CollectionWords.id == UserWord.word_id) &
        (UserWord.user_id == current_user.id)
    ).where(
        UserWord.id.is_(None)  # Слова без записи в UserWord
    )

    word_ids = [row[0] for row in db.session.execute(words_query).all()]

    # Добавляем слова в изучение (статус 1 = 'learning')
    for word_id in word_ids:
        current_user.set_word_status(word_id, 1)

    flash(f'Added {len(word_ids)} words from "{book.title}" to your learning queue.', 'success')
    return redirect(url_for('books.book_details', book_id=book_id))


@books.route('/edit-info/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book_info(book_id):
    """
    Quick edit for book info (title, author, level) without file uploads
    """
    book = Book.query.get_or_404(book_id)

    # Create a simplified form with just the fields we need
    class BookInfoForm(FlaskForm):
        title = StringField('Title', validators=[DataRequired(), Length(max=255)])
        author = StringField('Author', validators=[Optional(), Length(max=255)])
        level = SelectField('Book Level', choices=[
            ('', 'Not specified'),
            ('A1', 'A1 - Beginner'),
            ('A2', 'A2 - Elementary'),
            ('B1', 'B1 - Intermediate'),
            ('B2', 'B2 - Upper Intermediate'),
            ('C1', 'C1 - Advanced'),
            ('C2', 'C2 - Proficiency')
        ], default='')
        submit = SubmitField('Save Changes')

    form = BookInfoForm()

    if request.method == 'GET':
        # Pre-populate the form with existing values
        form.title.data = book.title
        form.author.data = book.author
        form.level.data = book.level

    if form.validate_on_submit():
        try:
            # Update basic book info
            book.title = form.title.data
            book.author = form.author.data
            book.level = form.level.data

            # Save changes
            db.session.commit()
            flash('Book information updated successfully!', 'success')
            return redirect(url_for('books.book_details', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating book information: {str(e)}', 'danger')

    return render_template('books/edit_info.html', form=form, book=book)


@books.route('/edit-info-with-cover/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book_info_with_cover(book_id):
    """
    Edit for book info including cover image upload
    """
    book = Book.query.get_or_404(book_id)
    form = BookContentForm(obj=book)

    # We'll ignore the file and content fields
    if request.method == 'GET':
        # Pre-populate the form with existing values
        form.title.data = book.title
        form.author.data = book.author
        form.level.data = book.level

    if form.validate_on_submit():
        try:
            # Update basic book info
            book.title = form.title.data
            book.author = form.author.data
            book.level = form.level.data

            # Process cover image if uploaded
            if form.cover_image.data and hasattr(form.cover_image.data, 'filename') and form.cover_image.data.filename:
                cover_filename = save_cover_image(form.cover_image.data)
                if cover_filename:
                    # Remove old cover if exists
                    if book.cover_image:
                        old_cover_path = os.path.join('app/static', book.cover_image)
                        if os.path.exists(old_cover_path):
                            try:
                                os.remove(old_cover_path)
                            except Exception as e:
                                logger.error(f"Error removing old cover: {str(e)}")

                    book.cover_image = cover_filename

            # Save changes
            db.session.commit()
            flash('Book information updated successfully!', 'success')
            return redirect(url_for('books.book_details', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating book information: {str(e)}', 'danger')

    return render_template('books/edit_info_with_cover.html', form=form, book=book)
