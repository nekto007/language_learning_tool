# app/books/routes.py

import inspect
import logging
import os
import re
import sys
import threading
import uuid
from datetime import UTC, datetime

from PIL import Image
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename
from wtforms.fields.choices import SelectField
from wtforms.fields.simple import StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional

from app import csrf
from app.books.forms import BookContentForm
from app.books.models import Book, Bookmark, Chapter
from app.books.parsers import process_uploaded_book
from app.books.processors import enqueue_book_processing
from app.study.models import UserWord
from app.utils.db import db, word_book_link
from app.utils.decorators import admin_required
from app.words.models import CollectionWords
from app.modules.decorators import module_required

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
    Сохраняет и обрабатывает обложку книги (устаревшая функция)

    ВНИМАНИЕ: Эта функция использует безопасную утилиту из app.utils.file_security
    для защиты от:
    - Загрузки вредоносных файлов (проверка реального MIME-типа)
    - XSS атак через метаданные (очистка EXIF)
    - Path traversal атак

    Args:
        file: Объект загруженного файла

    Returns:
        str: Относительный путь к сохраненному файлу или None в случае ошибки
    """
    from app.utils.file_security import process_and_save_cover_image

    result = process_and_save_cover_image(file)
    if result is None:
        flash('Ошибка при загрузке файла. Проверьте формат и размер изображения.', 'danger')
    return result


@books.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_book_redirect():
    """
    Перенаправляет на админку для добавления новой книги
    """
    flash('Функция добавления книг перенесена в админку', 'info')
    return redirect(url_for('admin.add_book'))


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
                    book.words_total = result['word_count']
                    book.unique_words = result['unique_words']
                    content_changed = True

                except Exception as e:
                    flash(f'Ошибка обработки файла: {str(e)}', 'danger')
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
                    book.words_total = len(words)
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
                flash('Содержимое книги успешно обновлено! Обработка слов запущена в фоновом режиме.',
                      'success')
            else:
                flash('Содержимое книги успешно обновлено!', 'success')

            return redirect(url_for('books.book_details', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка обновления книги: {str(e)}', 'danger')

    # Заполняем форму существующими данными
    if not form.content.data and book.content:
        form.content.data = book.content

    # A/B testing for optimized editor
    use_optimized = request.args.get('optimized', 'true').lower() in ['true', '1', 'yes']

    template = 'books/content_editor_optimized.html' if use_optimized else 'books/add.html'

    return render_template(template, form=form, book=book, is_edit=True)


@books.route('/reprocess-words/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def reprocess_book_words(book_id):
    """
    Запускает повторную обработку слов для существующей книги
    """
    book = Book.query.get_or_404(book_id)

    if not book.content:
        flash('В этой книге нет содержимого для обработки.', 'warning')
        return redirect(url_for('books.book_details', book_id=book_id))

    # Запускаем обработку слов
    processing_result = enqueue_book_processing(book.id, book.content)

    if processing_result.get("status") == "already_processing":
        flash('Эта книга уже обрабатывается.', 'info')
    elif processing_result.get("async", False):
        flash('Обработка слов поставлена в очередь в фоновом режиме.', 'success')
    elif processing_result.get("sync", False) and processing_result.get("status") == "success":
        flash('Слова были успешно обработаны!', 'success')
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
        flash('Файл не выбран', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

    file = request.files['cover_image']

    if file.filename == '':
        flash('Файл не выбран', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

    # Проверяем, что файл имеет атрибут filename
    if not hasattr(file, 'filename'):
        flash('Неверный объект файла', 'danger')
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
        flash('Обложка книги успешно обновлена!', 'success')

    return redirect(url_for('books.book_details', book_id=book_id))


@books.route('/read')
@login_required
@module_required('books')
def read_selection():
    """
    Page for selecting a book to read
    """
    # Get user's recent reading progress from chapters
    from app.books.models import UserChapterProgress
    recent_chapter_progress = UserChapterProgress.query.filter_by(
        user_id=current_user.id
    ).join(Chapter).join(Book).order_by(
        UserChapterProgress.updated_at.desc()
    ).limit(10).all()

    # Get all books with chapters
    all_books = Book.query.join(Chapter).distinct().order_by(Book.title).all()

    # Get reading statistics
    books_started = db.session.query(Book.id).join(Chapter).join(
        UserChapterProgress
    ).filter(UserChapterProgress.user_id == current_user.id).distinct().count()

    return render_template('books/read_selection.html',
                           recent_books=recent_chapter_progress,
                           all_books=all_books,
                           books_started=books_started)


@books.route('/read/<int:book_id>')
@login_required
@module_required('books')
def read_book(book_id):
    """
    Page for reading a book - redirects to chapter-based reader if chapters exist
    """
    book = Book.query.get_or_404(book_id)

    # Check if book has chapters
    has_chapters = Chapter.query.filter_by(book_id=book_id).first() is not None

    if has_chapters:
        # Redirect to chapter-based reader
        return redirect(url_for('books.read_book_chapters', book_id=book_id))

    # For books without chapters, we need to handle differently
    # Since there's no content field in the new schema, old-style books won't work
    flash('Этот формат книги не поддерживается. Пожалуйста, используйте книги с главами.', 'warning')
    return redirect(url_for('books.book_details', book_id=book.id))


@books.route('/books/<string:book_slug>/chapter/<int:chapter_num>')
@books.route('/books/<string:book_slug>/reader')
@books.route('/reader/<string:book_slug>/<int:chapter_num>')
@books.route('/read/<int:book_id>/chapters')
@login_required
@module_required('books')
def read_book_chapters(book_id=None, book_slug=None, chapter_num=None):
    """
    Chapter-based book reader with support for both ID and slug URLs
    """
    # Get book by slug or id
    if book_slug:
        book = Book.query.filter_by(slug=book_slug).first_or_404()
        book_id = book.id
    else:
        book = Book.query.get_or_404(book_id)

    # Get chapters
    chapters = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.chap_num).all()

    if not chapters:
        flash('В этой книге нет глав. Перенаправляем к обычному ридеру.', 'info')
        return redirect(url_for('books.read_book', book_id=book_id))

    # Get current chapter from URL params, query params or user progress
    if not chapter_num:
        chapter_num = request.args.get('chapter', type=int)

    if not chapter_num:
        # Try to get from user progress
        from app.books.models import UserChapterProgress
        latest_progress = UserChapterProgress.query.filter_by(
            user_id=current_user.id
        ).join(Chapter).filter(
            Chapter.book_id == book_id
        ).order_by(UserChapterProgress.updated_at.desc()).first()

        if latest_progress:
            chapter_num = latest_progress.chapter.chap_num
        else:
            chapter_num = 1

    # Get current chapter
    current_chapter = Chapter.query.filter_by(
        book_id=book_id,
        chap_num=chapter_num
    ).first()

    if not current_chapter:
        current_chapter = chapters[0]  # Default to first chapter

    # Get chapter progress
    from app.books.models import UserChapterProgress
    chapter_progress = UserChapterProgress.query.filter_by(
        user_id=current_user.id,
        chapter_id=current_chapter.id
    ).first()

    # Determine back URL based on referrer or query parameter
    back_url = request.args.get('from')
    if not back_url:
        referrer = request.referrer
        if referrer:
            # Check if referrer is from books list or book details
            if '/books' in referrer and f'/books/{book_id}' not in referrer:
                back_url = url_for('books.book_list')
            elif 'curriculum' in referrer or 'module' in referrer:
                back_url = referrer
            else:
                back_url = url_for('books.book_details', book_id=book_id)
        else:
            back_url = url_for('books.book_details', book_id=book_id)

    # Use simple reader template
    return render_template('books/reader_simple.html',
                           book=book,
                           chapters=chapters,
                           current_chapter=current_chapter,
                           chapter_progress=chapter_progress,
                           back_url=back_url
                           )


@books.route('/books/<string:book_slug>/reader-v2')
@books.route('/books/<string:book_slug>/chapter/<int:chapter_num>/v2')
@login_required
@module_required('books')
def read_book_v2(book_slug, chapter_num=None):
    """
    Enhanced Reader v2 - Uses new API endpoints
    """
    # Get book by slug
    book = Book.query.filter_by(slug=book_slug).first_or_404()

    # Get chapters for navigation
    chapters = Chapter.query.filter_by(book_id=book.id).order_by(Chapter.chap_num).all()

    if not chapters:
        flash('This book has no chapters available.', 'warning')
        return redirect(url_for('books.book_details', book_id=book.id))

    # Current chapter info (for SEO and title, actual loading is done via API)
    current_chapter = None
    if chapter_num:
        current_chapter = Chapter.query.filter_by(
            book_id=book.id,
            chap_num=chapter_num
        ).first()

    if not current_chapter:
        current_chapter = chapters[0]  # Default to first chapter

    return render_template('books/reader-v2.html',
                           book=book,
                           chapters=chapters,
                           current_chapter=current_chapter
                           )


# Old reading position API removed - using chapter-based progress only


@books.route('/api/translate', methods=['POST'])
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
        return jsonify({'success': False, 'error': str(e)}), 500


@books.route('/api/add-word-to-learning', methods=['POST'])
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
            from sqlalchemy import func
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

        # Синхронизация мастер-колод
        from app.study.routes import sync_master_decks
        sync_master_decks(current_user.id)
        db.session.commit()

        return jsonify({'success': True, 'message': f'Word "{word}" added to learning list'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@books.route('/api/bookmarks/<int:book_id>')
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
        return jsonify({'success': False, 'error': str(e)}), 500


@books.route('/api/bookmarks', methods=['POST'])
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
        return jsonify({'success': False, 'error': str(e)}), 500


# Legacy save progress API removed - using chapter-based progress only


def get_word_base_form(word):
    """
    Simple function to get the base form of a word without using NLTK
    Returns a tuple (base_form, form_type) or (None, None) if not found
    """
    word = word.lower().strip()

    # Dictionary of irregular verbs (past -> base form)
    irregular_verbs = {
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


@books.route('/api/test', methods=['GET'])
@login_required
def api_test():
    """Test API endpoint"""
    return jsonify({'status': 'ok', 'message': 'API is working'})


@books.route('/books/word-translation/<word>', methods=['GET'])
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
    from sqlalchemy import or_
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

        # Проверяем наличие аудио
        audio_url = None
        has_audio = word_entry.get_download == 1 and word_entry.listening
        if has_audio:
            # Извлекаем имя файла из поля listening (убираем audio/ и .mp3)
            audio_filename = word_entry.listening
            if audio_filename.startswith('audio/') and audio_filename.endswith('.mp3'):
                audio_filename = audio_filename[6:-4]  # Убираем 'audio/' и '.mp3'
                audio_url = url_for('static', filename=f'audio/{audio_filename}.mp3')

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
    """API для добавления слова в очередь изучения и колоду 'Слова из чтения'"""
    from app.study.models import QuizDeck, QuizDeckWord
    from app.study.services.deck_service import DeckService
    from sqlalchemy import func

    data = request.get_json()
    word_id = data.get('word_id')

    if not word_id:
        return jsonify({'success': False, 'error': 'Word ID is required'}), 400

    word_entry = CollectionWords.query.get(word_id)

    if not word_entry:
        return jsonify({'success': False, 'error': 'Word not found in dictionary'}), 404

    current_status = current_user.get_word_status(word_id)

    if current_status == 0:
        current_user.set_word_status(word_id, 1)  # 1 = queued for learning

        # Добавление в колоду "Слова из чтения"
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

        db.session.commit()

        # Синхронизация мастер-колод
        DeckService.sync_master_decks(current_user.id)

        return jsonify({
            'success': True,
            'message': 'Word added to learning queue',
            'new_status': 1
        })
    else:
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

    # Оптимизированный запрос статистики для всех книг сразу
    book_stats = {}

    if book_items and current_user.is_authenticated:
        book_ids = [book.id for book in book_items]

        # Один запрос для всех книг
        bulk_stats_query = db.select(
            word_book_link.c.book_id,
            UserWord.status,
            func.count().label('count')
        ).select_from(
            word_book_link
        ).join(
            UserWord,
            (word_book_link.c.word_id == UserWord.word_id) &
            (UserWord.user_id == current_user.id)
        ).where(
            word_book_link.c.book_id.in_(book_ids)
        ).group_by(
            word_book_link.c.book_id,
            UserWord.status
        )

        bulk_results = db.session.execute(bulk_stats_query).all()

        # Инициализируем статистику для всех книг
        for book in book_items:
            book_stats[book.id] = {
                'total': book.unique_words or 0,
                'new': book.unique_words or 0,
                'learning': 0,
                'review': 0,
                'mastered': 0
            }

        # Обновляем статистику на основе результатов запроса
        for book_id, status, count in bulk_results:
            if book_id in book_stats and status in book_stats[book_id]:
                book_stats[book_id][status] = count
                # Вычитаем из 'new' если есть статус
                if status != 'new':
                    book_stats[book_id]['new'] -= count
    else:
        # Для неавторизованных пользователей или пустого списка
        for book in book_items:
            book_stats[book.id] = {
                'total': book.unique_words or 0,
                'new': book.unique_words or 0,
                'learning': 0,
                'review': 0,
                'mastered': 0
            }

    # Get chapter counts for all books
    chapter_counts = {}
    if book_items:
        book_ids = [book.id for book in book_items]
        chapter_count_query = db.select(
            Chapter.book_id,
            func.count(Chapter.id).label('chapter_count')
        ).where(
            Chapter.book_id.in_(book_ids)
        ).group_by(Chapter.book_id)

        chapter_results = db.session.execute(chapter_count_query).all()
        for book_id, count in chapter_results:
            chapter_counts[book_id] = count

    # Проверяем, хочет ли пользователь использовать оптимизированную версию
    use_optimized = request.args.get('optimized', 'true').lower() == 'true'

    template = 'books/list_optimized.html' if use_optimized else 'books/list.html'

    return render_template(
        template,
        books=book_items,
        pagination=pagination,
        book_stats=book_stats,
        chapter_counts=chapter_counts,
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
    unique_words = book.unique_words or 0  # Handle None values
    word_stats = {
        'total': unique_words,
        'new': unique_words,  # По умолчанию все слова считаем новыми, потом вычтем изученные
        'learning': 0,
        'review': 0,  # Добавляем статус 'review'
        'mastered': 0
    }

    # Обновляем статистику с реальными данными
    # Сначала собираем все статусы кроме 'new'
    tracked_count = 0
    for status, count in status_counts:
        if status in word_stats and status != 'new':
            word_stats[status] = count
            tracked_count += count

    # new = все слова минус те что уже отслеживаются
    word_stats['new'] = max(0, unique_words - tracked_count)

    # Расчет процента прогресса слов
    if book.unique_words and book.unique_words > 0:
        word_progress = int(((word_stats['mastered']) / book.unique_words) * 100)
    else:
        word_progress = 0

    # Расчет процента прогресса чтения книги
    from app.books.models import UserChapterProgress, Chapter

    # Get total chapters for the book
    total_chapters = Chapter.query.filter_by(book_id=book_id).count()
    reading_progress = 0

    if total_chapters > 0:
        # Get all user's progress for this book's chapters
        user_chapters = db.session.query(
            UserChapterProgress, Chapter
        ).join(
            Chapter, UserChapterProgress.chapter_id == Chapter.id
        ).filter(
            Chapter.book_id == book_id,
            UserChapterProgress.user_id == current_user.id
        ).order_by(Chapter.chap_num).all()

        if user_chapters:
            # Calculate overall reading progress
            total_progress = 0
            for progress_record, chapter in user_chapters:
                # Each chapter contributes 1/total_chapters to overall progress
                chapter_contribution = progress_record.offset_pct / total_chapters
                total_progress += chapter_contribution

            reading_progress = int(total_progress * 100)

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

    # Get word statuses efficiently
    word_statuses = {}
    if frequent_words:
        word_ids = [word.id for word, _ in frequent_words]
        # Bulk query for user word statuses
        user_words = UserWord.query.filter(
            UserWord.user_id == current_user.id,
            UserWord.word_id.in_(word_ids)
        ).all()

        # Create status mapping
        for user_word in user_words:
            word_statuses[user_word.word_id] = user_word.status

        # Fill missing words with 'new' status
        for word_id in word_ids:
            if word_id not in word_statuses:
                word_statuses[word_id] = 'new'

    # A/B testing for optimized version
    use_optimized = request.args.get('optimized', 'true').lower() in ['true', '1', 'yes']

    # Check if book has chapters
    chapters = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.chap_num).all()

    template = 'books/details_optimized.html' if use_optimized else 'books/details.html'

    return render_template(
        template,
        book=book,
        word_stats=word_stats,
        progress=reading_progress,
        word_progress=word_progress,
        frequent_words=frequent_words,
        word_statuses=word_statuses,
        chapters=chapters
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

    # Bulk load word statuses to avoid N+1 queries
    word_ids = [item[0].id for item in book_words]
    user_words = UserWord.query.filter(
        UserWord.user_id == current_user.id,
        UserWord.word_id.in_(word_ids)
    ).all()

    # Create status mapping (0 = new, 1 = learning, 2 = review, 3 = mastered)
    from app.utils.db import string_to_status
    word_statuses = {uw.word_id: string_to_status(uw.status) for uw in user_words}

    # Fill in missing words with status 0 (new)
    for word_id in word_ids:
        if word_id not in word_statuses:
            word_statuses[word_id] = 0

    # Get word statistics for filter counts
    word_stats = {
        'total': book.unique_words or 0,
        'new': book.unique_words or 0,
        'learning': 0,
        'review': 0,
        'mastered': 0
    }

    # Get counts for each status
    stats_query = db.select(
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

    status_counts = db.session.execute(stats_query).all()

    # Сначала собираем все статусы кроме 'new'
    tracked_count = 0
    for status_name, count in status_counts:
        if status_name in word_stats and status_name != 'new':
            word_stats[status_name] = count
            tracked_count += count

    # new = все слова минус те что уже отслеживаются
    word_stats['new'] = max(0, (book.unique_words or 0) - tracked_count)

    # A/B testing for optimized version
    use_optimized = request.args.get('optimized', 'true').lower() in ['true', '1', 'yes']

    template = 'books/words_optimized.html' if use_optimized else 'books/words.html'

    return render_template(
        template,
        book=book,
        book_words=book_words,
        pagination=pagination,
        word_statuses=word_statuses,
        word_stats=word_stats,
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
            flash('Информация о книге успешно обновлена!', 'success')
            return redirect(url_for('books.book_details', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка обновления информации о книге: {str(e)}', 'danger')

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
            flash('Информация о книге успешно обновлена!', 'success')
            return redirect(url_for('books.book_details', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка обновления информации о книге: {str(e)}', 'danger')

    return render_template('books/edit_info_with_cover.html', form=form, book=book)


# ========================================
# URL Redirects for Backward Compatibility
# New standard: /books/{id}/{action}
# ========================================

@books.route('/books/<int:book_id>/read')
@login_required
@module_required('books')
def book_read(book_id):
    """
    Standardized URL for reading a book
    Works directly without redirects
    """
    book = Book.query.get_or_404(book_id)

    # Check if book has chapters
    has_chapters = Chapter.query.filter_by(book_id=book_id).first() is not None

    if has_chapters:
        # Render chapter-based reader directly
        chapters = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.chap_num).all()

        # Get chapter number from query params or user progress
        chapter_num = request.args.get('chapter', type=int)

        if not chapter_num:
            # Try to get from user progress
            from app.books.models import UserChapterProgress
            latest_progress = UserChapterProgress.query.filter_by(
                user_id=current_user.id
            ).join(Chapter).filter(
                Chapter.book_id == book_id
            ).order_by(UserChapterProgress.updated_at.desc()).first()

            if latest_progress:
                chapter_num = latest_progress.chapter.chap_num
            else:
                chapter_num = 1

        # Get current chapter
        current_chapter = Chapter.query.filter_by(
            book_id=book_id,
            chap_num=chapter_num
        ).first()

        if not current_chapter:
            current_chapter = chapters[0]

        # Get chapter progress
        chapter_progress = UserChapterProgress.query.filter_by(
            user_id=current_user.id,
            chapter_id=current_chapter.id
        ).first()

        # Determine back URL
        back_url = request.args.get('from')
        if not back_url:
            back_url = url_for('books.book_details', book_id=book_id)

        return render_template('books/reader_simple.html',
                             book=book,
                             chapters=chapters,
                             current_chapter=current_chapter,
                             chapter_progress=chapter_progress,
                             back_url=back_url)

    # For books without chapters
    flash('Этот формат книги не поддерживается. Пожалуйста, используйте книги с главами.', 'warning')
    return render_template('books/book_details', book=book)


@books.route('/api/save-reading-position', methods=['POST'])
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
        progress.updated_at = datetime.now(timezone.utc)

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


@books.route('/books/<int:book_id>/edit')
@login_required
@admin_required
def book_edit(book_id):
    """
    Standardized URL for editing a book
    """
    return redirect(url_for('books.edit_book_info', book_id=book_id))
