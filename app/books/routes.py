# app/books/routes.py

import logging
import os
import re
import threading

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import desc, func
from wtforms.fields.choices import SelectField
from wtforms.fields.simple import StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional

from app.books.forms import BookContentForm
from app.books.models import Book, Chapter
from app.books.parsers import process_uploaded_book
from app.books.processors import enqueue_book_processing
from app.study.models import UserWord
from app.utils.db import db
from app.admin.utils.decorators import admin_required
from app.words.models import CollectionWords, word_book_link
from app.modules.decorators import module_required

books = Blueprint('books', __name__)

logger = logging.getLogger(__name__)

# Configuration for book cover images
COVER_UPLOAD_FOLDER = 'app/static/uploads/covers'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_COVER_WIDTH = 400
MAX_COVER_HEIGHT = 600
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_cover_image(file):
    os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)
    from app.utils.file_security import process_and_save_cover_image

    result = process_and_save_cover_image(file)
    if result is None:
        flash('Ошибка при загрузке файла. Проверьте формат и размер изображения.', 'danger')
    return result


@books.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_book_redirect():
    flash('Функция добавления книг перенесена в админку', 'info')
    return redirect(url_for('admin.add_book'))


@books.route('/content/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book_content(book_id):
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

            # Sync linked BookCourse rows when book opts into course generation
            if book.create_course:
                try:
                    from app.curriculum.book_courses import sync_book_course_from_book
                    sync_book_course_from_book(book.id, db.session)
                except Exception as sync_err:
                    logger.error(f"BookCourse sync failed for book {book.id}: {sync_err}")

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

    if not form.content.data and book.content:
        form.content.data = book.content

    use_optimized = request.args.get('optimized', 'true').lower() in ['true', '1', 'yes']

    template = 'books/content_editor_optimized.html' if use_optimized else 'books/add.html'

    return render_template(template, form=form, book=book, is_edit=True)


@books.route('/reprocess-words/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def reprocess_book_words(book_id):
    book = Book.query.get_or_404(book_id)

    if not book.content:
        flash('В этой книге нет содержимого для обработки.', 'warning')
        return redirect(url_for('books.book_details', book_id=book_id))

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
    os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)
    book = Book.query.get_or_404(book_id)

    if 'cover_image' not in request.files:
        flash('Файл не выбран', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

    file = request.files['cover_image']

    if file.filename == '':
        flash('Файл не выбран', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

    if not hasattr(file, 'filename'):
        flash('Неверный объект файла', 'danger')
        return redirect(url_for('books.book_details', book_id=book_id))

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
    from app.books.models import UserChapterProgress

    all_books = Book.query.join(Chapter).distinct().order_by(Book.title).all()

    user_progress = db.session.query(
        UserChapterProgress, Chapter
    ).join(
        Chapter, UserChapterProgress.chapter_id == Chapter.id
    ).filter(
        UserChapterProgress.user_id == current_user.id
    ).all()

    from app.books.progress import _progress_from_records

    book_chapter_counts = {}
    for book in all_books:
        book_chapter_counts[book.id] = book.chapters_cnt or len(book.chapters)

    book_progress_map = {}
    for ucp, chapter in user_progress:
        bid = chapter.book_id
        if bid not in book_progress_map:
            book_progress_map[bid] = {
                'records': [],
                'last_chapter_num': chapter.chap_num,
                'last_read': ucp.updated_at,
            }
        entry = book_progress_map[bid]
        entry['records'].append(ucp)
        if ucp.updated_at and (entry['last_read'] is None or ucp.updated_at > entry['last_read']):
            entry['last_read'] = ucp.updated_at
            entry['last_chapter_num'] = chapter.chap_num

    book_progress = {}
    for bid, entry in book_progress_map.items():
        total_chapters = book_chapter_counts.get(bid, 1) or 1
        pct = int(_progress_from_records(entry['records'], total_chapters))
        book_progress[bid] = {
            'progress_pct': min(pct, 100),
            'last_chapter_num': entry['last_chapter_num'],
            'last_read': entry['last_read'],
        }

    recent_books = []
    for book in all_books:
        if book.id in book_progress:
            recent_books.append((book, book_progress[book.id]))
    recent_books.sort(key=lambda x: x[1]['last_read'] or datetime.min, reverse=True)

    books_started = len(book_progress)

    return render_template('books/read_selection.html',
                           recent_books=recent_books,
                           all_books=all_books,
                           books_started=books_started,
                           book_progress=book_progress)


@books.route('/read/<int:book_id>')
@login_required
@module_required('books')
def read_book(book_id):
    book = Book.query.get_or_404(book_id)

    has_chapters = Chapter.query.filter_by(book_id=book_id).first() is not None

    if has_chapters:
        # Redirect to chapter-based reader, preserving query params (e.g.
        # ?from=linear_plan&slot=book for linear-plan navigation context).
        forwarded_args = {k: v for k, v in request.args.items() if k not in {'book_id'}}
        return redirect(url_for('books.read_book_chapters', book_id=book_id, **forwarded_args))

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
    if book_slug:
        book = Book.query.filter_by(slug=book_slug).first_or_404()
        book_id = book.id
    else:
        book = Book.query.get_or_404(book_id)

    chapters = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.chap_num).all()

    if not chapters:
        flash('В этой книге нет глав. Перенаправляем к обычному ридеру.', 'info')
        return redirect(url_for('books.read_book', book_id=book_id))

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

    current_chapter = Chapter.query.filter_by(
        book_id=book_id,
        chap_num=chapter_num
    ).first()

    if not current_chapter:
        current_chapter = chapters[0]  # Default to first chapter

    from app.books.models import UserChapterProgress
    chapter_progress = UserChapterProgress.query.filter_by(
        user_id=current_user.id,
        chapter_id=current_chapter.id
    ).first()

    back_url = request.args.get('from')
    if back_url in ('daily_plan', 'linear_plan'):
        back_url = None  # tracking flag, not a URL
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
    book = Book.query.filter_by(slug=book_slug).first_or_404()

    chapters = Chapter.query.filter_by(book_id=book.id).order_by(Chapter.chap_num).all()

    if not chapters:
        flash('This book has no chapters available.', 'warning')
        return redirect(url_for('books.book_details', book_id=book.id))

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

# Legacy save progress API removed - using chapter-based progress only


@books.route('/books')
@login_required
def book_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    sort_by = request.args.get('sort', 'title')
    sort_order = request.args.get('order', 'asc')

    search_query = request.args.get('search', '')
    level_filter = request.args.get('level', '')
    letter_filter = request.args.get('letter', '')

    query = db.select(Book)

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

    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    book_items = pagination.items

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

    unique_words = book.unique_words or 0  # Handle None values
    word_stats = {
        'total': unique_words,
        'new': unique_words,  # По умолчанию все слова считаем новыми, потом вычтем изученные
        'learning': 0,
        'review': 0,  # Добавляем статус 'review'
        'mastered': 0
    }

    tracked_count = 0
    for status, count in status_counts:
        if status in word_stats and status != 'new':
            word_stats[status] = count
            tracked_count += count

    word_stats['new'] = max(0, unique_words - tracked_count)

    if book.unique_words and book.unique_words > 0:
        word_progress = int(((word_stats['mastered']) / book.unique_words) * 100)
    else:
        word_progress = 0

    from app.books.models import UserChapterProgress, Chapter
    from app.books.progress import compute_book_progress_percent

    total_chapters = Chapter.query.filter_by(book_id=book_id).count()
    reading_progress = 0
    last_read_chapter = None

    if total_chapters > 0:
        user_chapters = db.session.query(
            UserChapterProgress, Chapter
        ).join(
            Chapter, UserChapterProgress.chapter_id == Chapter.id
        ).filter(
            Chapter.book_id == book_id,
            UserChapterProgress.user_id == current_user.id
        ).order_by(Chapter.chap_num).all()

        if user_chapters:
            latest_updated = None
            for progress_record, chapter in user_chapters:
                if latest_updated is None or (progress_record.updated_at and progress_record.updated_at > latest_updated):
                    latest_updated = progress_record.updated_at
                    last_read_chapter = chapter.chap_num

            reading_progress = int(compute_book_progress_percent(current_user.id, book_id, db))

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

    use_optimized = request.args.get('optimized', 'true').lower() in ['true', '1', 'yes']

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
        chapters=chapters,
        last_read_chapter=last_read_chapter
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

    word_ids = [item[0].id for item in book_words]
    user_words = UserWord.query.filter(
        UserWord.user_id == current_user.id,
        UserWord.word_id.in_(word_ids)
    ).all()

    from app.utils.db import string_to_status
    word_statuses = {uw.word_id: string_to_status(uw.status) for uw in user_words}

    for word_id in word_ids:
        if word_id not in word_statuses:
            word_statuses[word_id] = 0

    word_stats = {
        'total': book.unique_words or 0,
        'new': book.unique_words or 0,
        'learning': 0,
        'review': 0,
        'mastered': 0
    }

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

    tracked_count = 0
    for status_name, count in status_counts:
        if status_name in word_stats and status_name != 'new':
            word_stats[status_name] = count
            tracked_count += count

    word_stats['new'] = max(0, (book.unique_words or 0) - tracked_count)

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

    for word_id in word_ids:
        current_user.set_word_status(word_id, 1)

    flash(f'Added {len(word_ids)} words from "{book.title}" to your learning queue.', 'success')
    return redirect(url_for('books.book_details', book_id=book_id))


@books.route('/edit-info/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book_info(book_id):
    book = Book.query.get_or_404(book_id)

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
    book = Book.query.get_or_404(book_id)
    form = BookContentForm(obj=book)

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


@books.route('/books/<int:book_id>/read')
@login_required
@module_required('books')
def book_read(book_id):
    book = Book.query.get_or_404(book_id)

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

    flash('Этот формат книги не поддерживается. Пожалуйста, используйте книги с главами.', 'warning')
    return render_template('books/book_details', book=book)


@books.route('/books/<int:book_id>/edit')
@login_required
@admin_required
def book_edit(book_id):
    return redirect(url_for('books.edit_book_info', book_id=book_id))
