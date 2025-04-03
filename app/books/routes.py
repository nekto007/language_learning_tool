# app/books/routes.py

import logging
import os
import re
import uuid
from datetime import datetime

from PIL import Image
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename

from app.books.forms import BookContentForm
from app.books.models import Book, ReadingProgress
from app.books.parsers import process_uploaded_book
from app.utils.db import db, user_word_status, word_book_link
from app.words.models import CollectionWords

books = Blueprint('books', __name__)

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
            flash('Book added successfully! You can now read it or edit its content.', 'success')
            return redirect(url_for('books.book_details', book_id=new_book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error saving book: {str(e)}', 'danger')

    return render_template('books/add.html', form=form)


@books.route('/content/<int:book_id>', methods=['GET', 'POST'])
@login_required
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

            # Процесс обложки книги - проверяем, что файл действительно загружен
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

            # Обработка файла содержимого книги - тоже проверяем наличие файла
            if form.file.data and hasattr(form.file.data, 'filename'):
                try:
                    # Обрабатываем файл с помощью функции из parsers.py
                    result = process_uploaded_book(
                        file=form.file.data,
                        title=form.title.data,
                        format_type=form.format_type.data
                    )

                    # Сохраняем результаты
                    book.content = result['content']
                    book.total_words = result['word_count']
                    book.unique_words = result['unique_words']

                except Exception as e:
                    flash(f'Error processing file: {str(e)}', 'danger')
                    return render_template('books/add.html', form=form, book=book)

            elif form.content.data:
                # Если контент был отредактирован вручную
                content = form.content.data

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

            # Сохраняем изменения
            db.session.commit()
            flash('Book content updated successfully!', 'success')
            return redirect(url_for('books.book_details', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating book: {str(e)}', 'danger')

    # Заполняем форму существующими данными
    if not form.content.data and book.content:
        form.content.data = book.content

    return render_template('books/add.html', form=form, book=book, is_edit=True)


@books.route('/upload-cover/<int:book_id>', methods=['POST'])
@login_required
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


@books.route('/api/word-translation/<word>')
@login_required
def get_word_translation(word):
    """
    API for getting word translation
    """
    word = word.lower().strip()
    word_entry = CollectionWords.query.filter_by(english_word=word).first()

    if word_entry:
        # Get word status for the user
        status = current_user.get_word_status(word_entry.id)

        return jsonify({
            'word': word,
            'translation': word_entry.russian_word,
            'in_dictionary': True,
            'id': word_entry.id,
            'status': status
        })
    else:
        return jsonify({
            'word': word,
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
        current_user.set_word_status(word_id, 2)  # 2 = queued for learning
        return jsonify({
            'success': True,
            'message': 'Word added to learning queue',
            'new_status': 2
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

    # Get books with word counts
    query = db.select(Book).order_by(Book.title)

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
        # Get total words assigned to the user from this book
        words_status_query = db.select(
            func.count().label('count'),
            user_word_status.c.status
        ).select_from(
            word_book_link
        ).join(
            user_word_status,
            (word_book_link.c.word_id == user_word_status.c.word_id) &
            (user_word_status.c.user_id == current_user.id)
        ).where(
            word_book_link.c.book_id == book.id
        ).group_by(
            user_word_status.c.status
        )

        word_status_counts = db.session.execute(words_status_query).all()

        # Initialize statistics
        stats = {
            'total': book.unique_words,
            'new': book.unique_words,  # Default all to new, we'll subtract known words
            'known': 0,
            'queued': 0,
            'active': 0,
            'mastered': 0
        }

        # Update with actual status counts
        for count, status in word_status_counts:
            if status == 1:
                stats['known'] = count
                stats['new'] -= count
            elif status == 2:
                stats['queued'] = count
                stats['new'] -= count
            elif status == 3:
                stats['active'] = count
                stats['new'] -= count
            elif status == 4:
                stats['mastered'] = count
                stats['new'] -= count

        book_stats[book.id] = stats

    return render_template(
        'books/list.html',
        books=book_items,
        pagination=pagination,
        book_stats=book_stats
    )


@books.route('/books/<int:book_id>')
@login_required
def book_details(book_id):
    book = Book.query.get_or_404(book_id)

    # Get word statistics
    word_stats_query = db.select(
        user_word_status.c.status,
        func.count().label('count')
    ).join(
        word_book_link,
        user_word_status.c.word_id == word_book_link.c.word_id
    ).where(
        (word_book_link.c.book_id == book_id) &
        (user_word_status.c.user_id == current_user.id)
    ).group_by(
        user_word_status.c.status
    )

    status_counts = db.session.execute(word_stats_query).all()

    # Build stats dictionary
    word_stats = {
        'total': book.unique_words,
        'new': book.unique_words,  # Default all to new, we'll subtract known words
        'known': 0,
        'queued': 0,
        'active': 0,
        'mastered': 0
    }

    # Update with actual status counts
    for status, count in status_counts:
        if status == 1:
            word_stats['known'] = count
            word_stats['new'] -= count
        elif status == 2:
            word_stats['queued'] = count
            word_stats['new'] -= count
        elif status == 3:
            word_stats['active'] = count
            word_stats['new'] -= count
        elif status == 4:
            word_stats['mastered'] = count
            word_stats['new'] -= count

    # Calculate progress percentage
    if book.unique_words > 0:
        progress = int(((word_stats['known'] + word_stats['mastered']) / book.unique_words) * 100)
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

    # Build base query
    query = db.select(
        CollectionWords,
        word_book_link.c.frequency
    ).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).where(
        word_book_link.c.book_id == book_id
    )

    # Apply status filter if provided
    if status is not None:
        from app.utils.db import user_word_status
        if status == 0:  # New/Unclassified
            # Words that don't have a status entry or have status 0
            subquery = db.select(user_word_status.c.word_id).where(
                (user_word_status.c.user_id == current_user.id) &
                (user_word_status.c.status != 0)
            ).scalar_subquery()

            query = query.where(CollectionWords.id.not_in(subquery))
        else:
            query = query.join(
                user_word_status,
                (CollectionWords.id == user_word_status.c.word_id) &
                (user_word_status.c.user_id == current_user.id)
            ).where(user_word_status.c.status == status)

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

    # Execute paginated query
    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    book_words = pagination.items

    # Get word statuses
    word_statuses = {}
    for word, _ in book_words:
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

    # Get words from this book that are not already in queue, active, or mastered
    words_query = db.select(
        CollectionWords.id
    ).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).where(
        word_book_link.c.book_id == book_id
    ).outerjoin(
        user_word_status,
        (CollectionWords.id == user_word_status.c.word_id) &
        (user_word_status.c.user_id == current_user.id)
    ).where(
        (user_word_status.c.status.is_(None)) |
        (user_word_status.c.status == 0) |
        (user_word_status.c.status == 1)  # Include "known" words too
    )

    word_ids = [row[0] for row in db.session.execute(words_query).all()]

    # Add words to queue (status 2)
    for word_id in word_ids:
        current_user.set_word_status(word_id, 2)

    flash(f'Added {len(word_ids)} words from "{book.title}" to your learning queue.', 'success')
    return redirect(url_for('books.book_details', book_id=book_id))
