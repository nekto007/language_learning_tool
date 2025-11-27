# app/admin/routes/book_routes.py

"""
Book Management Routes для административной панели
Маршруты для управления книгами, главами, метаданными
"""
import json
import logging
import os
import re
import subprocess
import threading
import traceback
from datetime import UTC, datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for, current_app)
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename

from app.admin.services.book_processing_service import BookProcessingService
from app.admin.utils.cache import clear_admin_cache
from app.admin.utils.decorators import admin_required, handle_admin_errors
from app.books.forms import BookContentForm
from app.books.models import Book, Chapter
from app.books.parsers import extract_file_metadata, process_uploaded_book
from app.utils.db import db
from app.words.models import CollectionWords, PhrasalVerb

# Создаем blueprint для book routes
book_bp = Blueprint('book_admin', __name__)

logger = logging.getLogger(__name__)


@book_bp.route('/books')
@admin_required
def books():
    """Главная страница управления книгами"""
    try:
        # Статистика по книгам
        total_books = Book.query.count()

        # Книги с обработанными данными
        books_with_stats = Book.query.filter(
            Book.words_total.isnot(None),
            Book.words_total > 0
        ).count()

        # Книги без статистики
        books_without_stats = total_books - books_with_stats

        # Общая статистика слов во всех книгах
        words_total_all = db.session.query(func.sum(Book.words_total)).scalar() or 0
        unique_words_all = db.session.query(func.sum(Book.unique_words)).scalar() or 0

        # Недавно добавленные книги
        recent_books = Book.query.order_by(
            Book.created_at.desc().nullslast()
        ).limit(10).all()

        # Топ книг по количеству слов
        top_books = Book.query.filter(
            Book.words_total.isnot(None)
        ).order_by(Book.words_total.desc()).limit(5).all()

        return render_template(
            'admin/books/index.html',
            total_books=total_books,
            books_with_stats=books_with_stats,
            books_without_stats=books_without_stats,
            words_total_all=words_total_all,
            unique_words_all=unique_words_all,
            recent_books=recent_books,
            top_books=top_books
        )
    except Exception as e:
        logger.error(f"Error in book management: {str(e)}")
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        return redirect(url_for('admin.dashboard'))


@book_bp.route('/books/scrape-website', methods=['POST'])
@admin_required
def scrape_website():
    """Web scraping для добавления новых книг"""
    from flask_login import current_user

    try:
        data = request.get_json()
        url = data.get('url')
        max_pages = data.get('max_pages', 10)

        if not url:
            return jsonify({
                'success': False,
                'error': 'URL не указан'
            }), 400

        # Импортируем и используем web scraper
        from app.web.scraper import WebScraper
        from config.settings import USER_AGENT, REQUEST_TIMEOUT, MAX_RETRIES

        scraper = WebScraper(
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT,
            max_retries=MAX_RETRIES
        )

        # Запускаем scraping
        results = scraper.scrape_website(url, max_pages)

        logger.info(f"Website scraping completed by {current_user.username}: {len(results)} books processed")

        return jsonify({
            'success': True,
            'scraped_count': len(results),
            'results': results[:10]  # Возвращаем первые 10 для предварительного просмотра
        })

    except Exception as e:
        logger.error(f"Error scraping website: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@book_bp.route('/books/update-statistics', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def update_book_statistics():
    """Обновление статистики всех книг"""
    from flask_login import current_user

    try:
        data = request.get_json()
        book_id = data.get('book_id')  # Опционально для конкретной книги

        if book_id:
            # Обновляем статистику одной книги
            book = Book.query.get_or_404(book_id)
            books_to_update = [book]
        else:
            # Обновляем статистику всех книг
            books_to_update = Book.query.all()

        updated_count = 0

        for book in books_to_update:
            try:
                # Используем DatabaseRepository для получения статистики
                from app.repository import DatabaseRepository
                repo = DatabaseRepository()

                # Получаем уникальные слова для книги
                unique_words_result = repo.execute_query(
                    "SELECT COUNT(DISTINCT word_id) FROM word_book_link WHERE book_id = %s",
                    (book.id,),
                    fetch=True
                )
                unique_words = unique_words_result[0][0] if unique_words_result else 0

                # Получаем общее количество слов (сумма частот)
                words_total_result = repo.execute_query(
                    "SELECT SUM(frequency) FROM word_book_link WHERE book_id = %s",
                    (book.id,),
                    fetch=True
                )
                words_total = words_total_result[0][0] if words_total_result else 0

                # Обновляем статистику книги
                book.unique_words = unique_words or 0
                book.words_total = words_total or 0
                # Use datetime.now(UTC) and convert to naive for DB compatibility
                book.created_at = datetime.now(UTC).replace(tzinfo=None)
                updated_count += 1

            except Exception as e:
                logger.warning(f"Error updating stats for book {book.id}: {str(e)}")
                continue

        db.session.commit()

        logger.info(f"Book statistics updated by {current_user.username}: {updated_count} books")

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'total_books': len(books_to_update)
        })

    except Exception as e:
        logger.error(f"Error updating book statistics: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@book_bp.route('/books/process-phrasal-verbs', methods=['POST'])
@admin_required
def process_phrasal_verbs():
    """Обработка файла с фразовыми глаголами"""
    from flask_login import current_user
    from app.utils.file_security import validate_text_file_upload

    try:
        phrasal_verbs_data = None

        if 'phrasal_verbs_file' in request.files and request.files['phrasal_verbs_file'].filename:
            file = request.files['phrasal_verbs_file']
            is_valid, error_msg = validate_text_file_upload(file, allowed_extensions={'txt', 'csv'}, max_size_mb=5)
            
            if not is_valid:
                return jsonify({'success': False, 'error': f'Ошибка валидации файла: {error_msg}'}), 400

            try:
                content = file.read().decode('utf-8')
                phrasal_verbs_data = content.strip().split('\n')
            except Exception as e:
                return jsonify({'success': False, 'error': f'Ошибка при чтении файла: {str(e)}'}), 400
                
        elif request.form.get('phrasal_verbs_text'):
            phrasal_verbs_data = request.form.get('phrasal_verbs_text').strip().split('\n')

        if not phrasal_verbs_data:
            return jsonify({'success': False, 'error': 'Данные фразовых глаголов не предоставлены'}), 400

        processed_count = 0
        errors = []

        for line_num, line in enumerate(phrasal_verbs_data, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split(';')
            if len(parts) != 5:
                errors.append(f'Строка {line_num}: неверный формат "{line}"')
                continue

            phrasal_verb_text, russian_translate, using, english_sentence, russian_sentence = parts
            phrasal_verb_text = phrasal_verb_text.strip()
            english_word = phrasal_verb_text.split(' ')[0].lower()
            base_word = CollectionWords.query.filter_by(english_word=english_word).first()

            if not base_word:
                errors.append(f'Строка {line_num}: базовое слово "{english_word}" не найдено')
                continue

            phrasal_verb = PhrasalVerb.query.filter_by(phrasal_verb=phrasal_verb_text).first()

            if not phrasal_verb:
                phrasal_verb = PhrasalVerb(
                    phrasal_verb=phrasal_verb_text,
                    russian_translate=russian_translate.strip(),
                    using=using.strip(),
                    sentence=f"{english_sentence.strip()}<br>{russian_sentence.strip()}",
                    word_id=base_word.id,
                    listening=f"[sound:pronunciation_en_{phrasal_verb_text.lower().replace(' ', '_')}.mp3]",
                    get_download=0
                )
                db.session.add(phrasal_verb)
            else:
                phrasal_verb.russian_translate = russian_translate.strip()
                phrasal_verb.using = using.strip()
                phrasal_verb.sentence = f"{english_sentence.strip()}<br>{russian_sentence.strip()}"

            processed_count += 1

        db.session.commit()

        result = {
            'success': True,
            'processed_count': processed_count,
            'total_lines': len([line for line in phrasal_verbs_data if line.strip() and not line.strip().startswith('#')])
        }

        if errors:
            result['errors'] = errors[:10]
            result['total_errors'] = len(errors)

        logger.info(f"Phrasal verbs processed by {current_user.username}: {processed_count} processed, {len(errors)} errors")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error processing phrasal verbs: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@book_bp.route('/books/statistics')
@admin_required
def book_statistics():
    """Детальная статистика по книгам"""
    try:
        stats = BookProcessingService.get_book_statistics()
        
        if 'error' in stats:
            flash(f'Ошибка при получении статистики: {stats["error"]}', 'danger')
            return redirect(url_for('book_admin.books'))

        # Дополнительные данные для шаблона
        top_books_by_words = Book.query.filter(
            Book.words_total.isnot(None), Book.words_total > 0
        ).order_by(Book.words_total.desc()).limit(20).all()

        top_books_by_unique = Book.query.filter(
            Book.unique_words.isnot(None), Book.unique_words > 0
        ).order_by(Book.unique_words.desc()).limit(20).all()

        books_without_stats = Book.query.filter(
            (Book.words_total.is_(None)) | (Book.words_total == 0)
        ).order_by(Book.title).limit(50).all()

        total_stats = db.session.query(
            func.count(Book.id).label('total_books'),
            func.sum(Book.words_total).label('words_total'),
            func.sum(Book.unique_words).label('unique_words'),
            func.avg(Book.words_total).label('avg_words'),
            func.avg(Book.unique_words).label('avg_unique')
        ).first()

        phrasal_stats = db.session.query(
            func.count(PhrasalVerb.id).label('total_phrasal_verbs'),
            func.count(PhrasalVerb.id).filter(PhrasalVerb.get_download == 1).label('with_audio')
        ).first()

        return render_template(
            'admin/books/statistics.html',
            top_books_by_words=top_books_by_words,
            top_books_by_unique=top_books_by_unique,
            books_without_stats=books_without_stats,
            total_stats=total_stats,
            phrasal_stats=phrasal_stats
        )
    except Exception as e:
        logger.error(f"Error getting book statistics: {str(e)}")
        flash(f'Ошибка при получении статистики: {str(e)}', 'danger')
        return redirect(url_for('book_admin.books'))


@book_bp.route('/books/extract-metadata', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def extract_book_metadata():
    """API для извлечения метаданных из загруженного файла"""
    logger.info("[METADATA_EXTRACT] Starting metadata extraction process")
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Файл не найден'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()

        temp_dir = os.path.join('app', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, filename)
        
        file.save(temp_file_path)

        try:
            metadata = extract_file_metadata(temp_file_path, file_ext)
            logger.info(f"[METADATA_EXTRACT] Extracted: {metadata.get('title', '')}")

            return jsonify({
                'success': True,
                'metadata': metadata,
                'filename': filename,
                'file_ext': file_ext
            })
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    except Exception as e:
        logger.error(f"[METADATA_EXTRACT] Error: {str(e)}")
        return jsonify({'success': False, 'error': f'Ошибка при извлечении метаданных: {str(e)}'}), 500


@book_bp.route('/books/cleanup', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def cleanup_books():
    """Очистка и оптимизация данных раздела Books"""
    if request.method == 'GET':
        cleanup_stats = {}
        try:
            # Count books without chapters (no content)
            books_no_content = db.session.execute(
                db.text("SELECT COUNT(*) FROM book WHERE chapters_cnt = 0 OR chapters_cnt IS NULL")
            ).scalar()
            books_no_stats = db.session.execute(
                db.text("SELECT COUNT(*) FROM book WHERE words_total = 0 OR words_total IS NULL")
            ).scalar()
            total_books = Book.query.count()

            cleanup_stats = {
                'books_no_content': books_no_content,
                'books_no_stats': books_no_stats,
                'total_books': total_books
            }
        except Exception as e:
            logger.error(f"Error analyzing books data: {str(e)}")
            cleanup_stats = {'error': str(e)}

        return render_template('admin/books/cleanup.html', stats=cleanup_stats)

    elif request.method == 'POST':
        action = request.form.get('action')
        results = {'success': True, 'message': '', 'details': []}

        try:
            if action == 'remove_empty_books':
                empty_books = Book.query.filter(
                    db.or_(Book.content.is_(None), Book.content == '')
                ).all()
                count = len(empty_books)
                for book in empty_books:
                    db.session.delete(book)
                db.session.commit()
                results['details'].append(f"Удалено {count} книг без содержания")

            elif action == 'clean_temp_files':
                temp_dir = os.path.join('app', 'temp')
                removed_files = 0
                if os.path.exists(temp_dir):
                    for filename in os.listdir(temp_dir):
                        try:
                            os.remove(os.path.join(temp_dir, filename))
                            removed_files += 1
                        except:
                            pass
                results['details'].append(f"Удалено {removed_files} временных файлов")

            results['message'] = 'Очистка выполнена успешно'

        except Exception as e:
            db.session.rollback()
            results['success'] = False
            results['message'] = f'Ошибка при очистке: {str(e)}'
            logger.error(f"Error in books cleanup: {str(e)}")

        flash(results['message'], 'success' if results['success'] else 'danger')
        for detail in results['details']:
            flash(detail, 'info')
        return redirect(url_for('book_admin.cleanup_books'))


@book_bp.route('/books/add', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def add_book():
    """Добавление новой книги через админку"""
    from flask_login import current_user
    
    logger.info("[BOOK_ADD] Starting book addition process")
    form = BookContentForm()

    if form.validate_on_submit():
        logger.info(f"[BOOK_ADD] Form validated - Title: '{form.title.data}', Author: '{form.author.data}'")
        
        # Проверяем существующую книгу
        existing_book = Book.query.filter(
            func.lower(Book.title) == func.lower(form.title.data),
            func.lower(Book.author) == func.lower(form.author.data)
        ).first()

        overwrite = request.form.get('overwrite') == 'true'

        if existing_book and not overwrite:
            logger.warning(f"[BOOK_ADD] Duplicate book detected - ID: {existing_book.id}")
            return jsonify({
                'success': False,
                'duplicate': True,
                'existing_book': {
                    'id': existing_book.id,
                    'title': existing_book.title,
                    'author': existing_book.author,
                    'created_at': existing_book.created_at.strftime('%Y-%m-%d %H:%M') if existing_book.created_at else 'Неизвестно'
                },
                'message': 'Книга с таким названием и автором уже существует!'
            })

        if existing_book and overwrite:
            logger.info(f"[BOOK_ADD] Overwriting existing book - ID: {existing_book.id}")
            new_book = existing_book
            chapters_count = Chapter.query.filter_by(book_id=existing_book.id).count()
            Chapter.query.filter_by(book_id=existing_book.id).delete()
            new_book.content = None
            new_book.words_total = 0
            new_book.unique_words = 0
            new_book.cover_image = None
            db.session.flush()
        else:
            logger.info("[BOOK_ADD] Creating new book record")
            new_book = Book(
                title=form.title.data,
                author=form.author.data,
                level=form.level.data,
                chapters_cnt=0,  # Initialize with 0, will be updated after chapter processing
                # Use datetime.now(UTC) and convert to naive for DB compatibility
                created_at=datetime.now(UTC).replace(tzinfo=None)
            )

        # Обновляем данные
        new_book.title = form.title.data
        new_book.author = form.author.data
        new_book.level = form.level.data

        # Обрабатываем обложку
        if form.cover_image.data and hasattr(form.cover_image.data, 'filename'):
            logger.info(f"[BOOK_ADD] Processing cover image")
            cover_filename = BookProcessingService.save_cover_image(form.cover_image.data)
            if cover_filename:
                new_book.cover_image = cover_filename

        # Обрабатываем файл контента
        if form.file.data and hasattr(form.file.data, 'filename'):
            logger.info(f"[BOOK_ADD] Processing book content file")
            filename = secure_filename(form.file.data.filename)
            file_ext = os.path.splitext(filename)[1].lower()

            chapter_formats = ['.fb2', '.txt']
            use_chapters = file_ext in chapter_formats

            if use_chapters:
                logger.info("[BOOK_ADD] Using chapter-based processing")
                if not existing_book or not overwrite:
                    db.session.add(new_book)
                db.session.commit()

                temp_dir = os.path.join('app', 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                temp_file_path = os.path.join(temp_dir, filename)
                form.file.data.save(temp_file_path)

                try:
                    success, message = BookProcessingService.process_book_into_chapters(
                        new_book.id, temp_file_path, file_ext
                    )
                    
                    message_text = f'Книга успешно {"перезаписана" if existing_book and overwrite else "добавлена"}! {message}'

                    if success:
                        app = current_app._get_current_object()
                        book_id_to_process = new_book.id

                        def start_chapter_processing():
                            logger.info(f"[ADMIN] Starting chapter processing thread for book {book_id_to_process}")
                            try:
                                with app.app_context():
                                    from app.books.safe_processors import (
                                        safe_process_book_chapters_words,
                                        diagnose_import_issue
                                    )
                                    diagnosis = diagnose_import_issue()
                                    logger.info(f"[ADMIN] Diagnosis results: {diagnosis}")
                                    result = safe_process_book_chapters_words(book_id_to_process)
                                    logger.info(f"[ADMIN] Processing result: {result}")
                            except Exception as e:
                                logger.error(f"[ADMIN] Error in chapter processing thread: {str(e)}")

                        processing_thread = threading.Thread(
                            target=start_chapter_processing,
                            name=f"BookChapterProcessor-{new_book.id}"
                        )
                        processing_thread.daemon = True
                        processing_thread.start()

                        if request.is_json or request.headers.get('Content-Type') == 'application/json':
                            return jsonify({'success': True, 'message': message_text})
                        flash(message_text, 'success')
                    else:
                        error_text = f'Книга {"перезаписана" if existing_book and overwrite else "добавлена"}, но ошибка при обработке глав: {message}'
                        if request.is_json or request.headers.get('Content-Type') == 'application/json':
                            return jsonify({'success': False, 'message': error_text})
                        flash(error_text, 'warning')
                finally:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)

                clear_admin_cache()
                action = "overwritten" if existing_book and overwrite else "added"
                logger.info(f"Book {action} with chapters by admin {current_user.username}: {new_book.title}")
                return redirect(url_for('book_admin.books'))
            else:
                # Для других форматов используем старую логику
                result = process_uploaded_book(
                    file=form.file.data,
                    title=form.title.data,
                    format_type=form.format_type.data
                )
                new_book.content = result['content']
                new_book.words_total = result['word_count']
                new_book.unique_words = result['unique_words']

        elif form.content.data:
            # Контент введен вручную
            content = form.content.data
            content = re.sub(r'\s+', ' ', content)
            paragraphs = [p.strip() for p in content.split('\\n\\n') if p.strip()]
            content_html = '<p>' + '</p><p>'.join(paragraphs) + '</p>'
            words = re.findall(r'\b[a-zA-Z]+\b', content.lower())
            new_book.content = content_html
            new_book.words_total = len(words)
            new_book.unique_words = len(set(words))

        # Сохраняем книгу (если не была обработана по главам)
        if not (form.file.data and hasattr(form.file.data, 'filename') and 
                os.path.splitext(secure_filename(form.file.data.filename))[1].lower() in ['.fb2', '.txt']):
            if not existing_book or not overwrite:
                db.session.add(new_book)
            db.session.commit()

            clear_admin_cache()

            # Запускаем обработку слов в фоне
            if new_book.content:
                app = current_app._get_current_object()
                book_id_to_process = new_book.id
                book_content = new_book.content

                def start_processing():
                    try:
                        with app.app_context():
                            from app.books.safe_processors import safe_process_book_words
                            result = safe_process_book_words(book_id_to_process, book_content)
                            logger.info(f"[ADMIN] Processing result: {result}")
                    except Exception as e:
                        logger.error(f"[ADMIN] Error in word processing thread: {str(e)}")

                processing_thread = threading.Thread(
                    target=start_processing,
                    name=f"BookWordProcessor-{new_book.id}"
                )
                processing_thread.daemon = True
                processing_thread.start()

                success_message = f'Книга успешно {"перезаписана" if existing_book and overwrite else "добавлена"}! Обработка слов запущена в фоновом режиме.'
            else:
                success_message = f'Книга успешно {"перезаписана" if existing_book and overwrite else "добавлена"}!'

            if request.is_json or request.headers.get('Content-Type') == 'application/json':
                return jsonify({'success': True, 'message': success_message})

            flash(success_message, 'success')
            action = "overwritten" if existing_book and overwrite else "added"
            logger.info(f"Book {action} by admin {current_user.username}: {new_book.title}")
            return redirect(url_for('book_admin.books'))
        else:
            logger.warning(f"[BOOK_ADD] Form validation failed - Errors: {form.errors}")

    logger.info("[BOOK_ADD] Rendering add book form")
    return render_template('admin/books/add.html', form=form)
