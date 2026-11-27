# app/admin/routes/book_routes.py

"""
Book Management Routes для административной панели
Маршруты для управления книгами, главами, метаданными
"""
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func

from app.admin.audit import log_admin_action
from app.admin.services.book_import import ImportedChapter, install_chapters, prepare_chapters
from app.admin.services.book_passport import (
    PASSPORT_FORMATS,
    confirm_passport,
    has_passport_form,
    passport_changed,
    passport_draft,
    passport_revision,
    passport_token,
)
from app.admin.services.book_processing_service import (
    BOOK_TEMP_DIR,
    BookProcessingService,
    BookUploadError,
    save_uploaded_book_file,
)
from app.admin.services.chapter_editor import apply_chapter, chapter_preview_impact, chapter_revision, review_chapter, text_for_edit
from app.admin.utils.cache import clear_admin_cache
from app.admin.utils.decorators import admin_required, handle_admin_errors
from app.admin.utils.import_helpers import delete_import_data, load_import_data, save_import_data
from app.books.forms import BookContentForm
from app.books.models import Book, Chapter
from app.books.parsers import extract_file_metadata
from app.books.readability import book_has_text, chapter_has_text
from app.utils.audio import get_clean_audio_filename
from app.utils.db import db
from app.words.models import CollectionWords

# Создаем blueprint для book routes
book_bp = Blueprint('book_admin', __name__)

logger = logging.getLogger(__name__)


@book_bp.route('/books')
@admin_required
@handle_admin_errors(return_json=False)
def books() -> ResponseReturnValue:
    """Search the full book catalogue and show its actual reading availability."""
    search = request.args.get('q', '').strip()[:255]
    text = request.args.get('text', '')
    publication = request.args.get('publication', '')
    level = request.args.get('level', '')
    has_text = book_has_text(Book.id)
    chapter_count = (db.select(func.count(Chapter.id)).where(Chapter.book_id == Book.id)
                     .correlate(Book).scalar_subquery())
    query = Book.query.add_columns(has_text.label('has_text'), chapter_count.label('chapter_count'))
    if search:
        clauses = [func.lower(Book.title).contains(search.lower(), autoescape=True),
                   func.lower(Book.author).contains(search.lower(), autoescape=True)]
        if re.fullmatch(r'[0-9]{1,10}', search) and int(search) < 2**31:
            clauses.append(Book.id == int(search))
        query = query.filter(db.or_(*clauses))
    if text in ('available', 'missing'):
        query = query.filter(has_text if text == 'available' else ~has_text)
    if publication in ('published', 'draft'):
        query = query.filter(Book.is_published.is_(publication == 'published'))
    if level in ('A1', 'A2', 'B1', 'B2', 'C1', 'C2'):
        query = query.filter(Book.level == level)
    pagination = query.order_by(Book.title, Book.id).paginate(per_page=20, error_out=False)
    return render_template('admin/books/index.html', pagination=pagination,
                           search=search, text=text, publication=publication, level=level)


@book_bp.route('/books/scrape-website', methods=['POST'])
@admin_required
def scrape_website() -> ResponseReturnValue:
    """Explain the remaining import path to old callers of this URL."""
    return jsonify({
        'success': False,
        'error': 'Импорт книг по URL недоступен. Загрузите файл в форме добавления книги.',
        'upload_url': url_for('.add_book'),
    }), 410


@book_bp.route('/books/update-statistics', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def update_book_statistics() -> ResponseReturnValue:
    """Recount readable chapters and refresh words from the stored index if present."""
    data = request.get_json(silent=True) if request.is_json else request.form
    if data is None or not hasattr(data, 'get'):
        return jsonify({'success': False, 'error': 'invalid_request'}), 400
    book_id = data.get('book_id')
    query = Book.query
    if book_id is not None:
        if not isinstance(book_id, (int, str)) or isinstance(book_id, bool) or not re.fullmatch(r'[0-9]{1,10}', str(book_id)):
            return jsonify({'success': False, 'error': 'invalid_book_id'}), 400
        if not 0 < int(book_id) < 2**31:
            return jsonify({'success': False, 'error': 'invalid_book_id'}), 400
        query = query.filter(Book.id == int(book_id))
    targets = query.order_by(Book.id).with_for_update().all()
    if book_id is not None and not targets:
        return jsonify({'success': False, 'error': 'Книга не найдена.'}), 404
    ids = [book.id for book in targets]
    chapters = dict(db.session.query(Chapter.book_id, func.count(Chapter.id))
                    .filter(Chapter.book_id.in_(ids), chapter_has_text()).group_by(Chapter.book_id))
    from app.words.models import word_book_link

    indexed = {row.book_id: row for row in db.session.query(
        word_book_link.c.book_id, func.count().label('unique_count'),
        func.sum(word_book_link.c.frequency).label('words_total'),
    ).filter(word_book_link.c.book_id.in_(ids)).group_by(word_book_link.c.book_id)}
    changed = 0
    for book in targets:
        counts = indexed.get(book.id)
        chapter_count = chapters.get(book.id, 0)
        previous = (book.chapters_cnt, book.words_total, book.unique_words)
        book.chapters_cnt = chapter_count
        if counts is not None and chapter_count:
            book.words_total = counts.words_total or 0
            book.unique_words = counts.unique_count
        changed += previous != (book.chapters_cnt, book.words_total, book.unique_words)
    if changed:
        log_admin_action(current_user.id, 'book.update_statistics', target_type='book', required=True)
    db.session.commit()
    if not request.is_json:
        flash(f'Проверено книг: {len(targets)}. Обновлено: {changed}.', 'success')
        return redirect(url_for('.book_statistics'), code=303)
    return jsonify({'success': True, 'updated_count': changed, 'total_books': len(targets)})


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

            # Check if phrasal verb exists in CollectionWords
            phrasal_verb_entry = CollectionWords.query.filter_by(english_word=phrasal_verb_text).first()

            if not phrasal_verb_entry:
                phrasal_verb_entry = CollectionWords(
                    english_word=phrasal_verb_text,
                    russian_word=russian_translate.strip(),
                    usage_context=using.strip(),
                    sentences=f"{english_sentence.strip()}<br>{russian_sentence.strip()}",
                    base_word_id=base_word.id,
                    listening=get_clean_audio_filename(phrasal_verb_text),
                    get_download=0,
                    item_type='phrasal_verb',
                    level='B1'
                )
                db.session.add(phrasal_verb_entry)
            else:
                phrasal_verb_entry.russian_word = russian_translate.strip()
                phrasal_verb_entry.usage_context = using.strip()
                phrasal_verb_entry.sentences = f"{english_sentence.strip()}<br>{russian_sentence.strip()}"
                phrasal_verb_entry.item_type = 'phrasal_verb'
                phrasal_verb_entry.base_word_id = base_word.id

            processed_count += 1

        if processed_count > 0:
            log_admin_action(current_user.id, 'book.process_phrasal_verbs', target_type='word')
        db.session.commit()

        result = {
            'success': True,
            'processed_count': processed_count,
            'total_lines': len([
                line for line in phrasal_verbs_data
                if line.strip() and not line.strip().startswith('#')
            ])
        }

        if errors:
            result['errors'] = errors[:10]
            result['total_errors'] = len(errors)

        logger.info(
            "Phrasal verbs processed by %s: %d processed, %d errors",
            current_user.username, processed_count, len(errors),
        )
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

        # Get phrasal verb stats from CollectionWords
        phrasal_stats = db.session.query(
            func.count(CollectionWords.id).label('total_phrasal_verbs'),
            func.count(CollectionWords.id).filter(CollectionWords.get_download == 1).label('with_audio')
        ).filter(CollectionWords.item_type == 'phrasal_verb').first()

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
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не найден'}), 400

    file = request.files['file']
    try:
        temp_file_path, filename, file_ext = save_uploaded_book_file(file)
    except BookUploadError as e:
        logger.warning(f"[METADATA_EXTRACT] Upload rejected: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

    try:
        metadata = extract_file_metadata(temp_file_path, file_ext, original_filename=filename)
        logger.info(f"[METADATA_EXTRACT] Extracted: {metadata.get('title', '')}")
        return jsonify({
            'success': True,
            'metadata': metadata,
            'filename': filename,
            'file_ext': file_ext,
        })
    except Exception as e:
        logger.error(f"[METADATA_EXTRACT] Error: {str(e)}")
        return jsonify({'success': False, 'error': f'Ошибка при извлечении метаданных: {str(e)}'}), 500
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                logger.warning(f"[METADATA_EXTRACT] Failed to remove temp file: {temp_file_path}")


@book_bp.route('/books/add/passport-preview', methods=['POST'])
@book_bp.route('/books/<int:book_id>/passport-preview', methods=['POST'])
@admin_required
def preview_book_passport(book_id: int | None = None) -> ResponseReturnValue:
    book = db.session.get(Book, book_id) if book_id is not None else None
    if book_id is not None and book is None:
        abort(404)
    if request.form.get('passport_revision', '') != passport_revision(book):
        return jsonify(error='Карточка изменилась. Сверьте черновик с текущими полями и повторите предпросмотр.',
                       revision=passport_revision(book)), 409
    try:
        values, digest = passport_draft(book, request.form, request.files.get('file'))
    except ValueError as error:
        return jsonify(error=str(error)), 422
    response = jsonify(values=values, token=passport_token(current_user.id, book, digest))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _confirmed_book_passport(book: Book | None) -> dict[str, str | None]:
    form = request.form
    if not has_passport_form(form):
        return {}
    if form.get('passport_revision', '') != passport_revision(book):
        raise BadSignature('stale book revision')
    token = form.get('passport_token', '')
    if not token and not passport_changed(book, form):
        return {}
    values, digest = passport_draft(book, form, request.files.get('file'))
    confirm_passport(token, current_user.id, book, digest)
    return values


@book_bp.route('/books/cleanup', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def cleanup_books() -> ResponseReturnValue:
    """List books to review individually and clean expired upload files."""
    if request.method == 'POST':
        action = request.form.get('action')
        if action != 'clean_temp_files':
            flash('Откройте нужную книгу из каталога для проверки и удаления.', 'warning')
            return redirect(url_for('.cleanup_books'), code=303)
        cutoff = (datetime.now(UTC) - timedelta(days=1)).timestamp()
        removed = failed = 0
        for path in Path(BOOK_TEMP_DIR).glob('book-*'):
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                logger.exception('Could not remove expired book upload')
                failed += 1
        if removed:
            log_admin_action(current_user.id, 'book.cleanup_temp_files', target_type='book')
            db.session.commit()
        message = f'Удалено просроченных временных файлов: {removed}.'
        if failed:
            message += f' Не удалось удалить: {failed}.'
        flash(message, 'warning' if failed else 'success')
        return redirect(url_for('.cleanup_books'), code=303)

    stats = {'books_no_content': Book.query.filter(~book_has_text(Book.id)).count()}
    return render_template('admin/books/cleanup.html', stats=stats)


@book_bp.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def edit_book(book_id: int) -> ResponseReturnValue:
    """Редактирование книги"""
    from app.admin.routes.materials import materials_return_url

    query = Book.query.filter_by(id=book_id)
    if request.method == 'POST':
        query = query.with_for_update().populate_existing()
    book = query.first_or_404()
    has_text = bool(db.session.query(book_has_text(book_id)).scalar())
    has_chapters = Chapter.query.filter_by(book_id=book_id).first() is not None
    context = {'book': book, 'has_text': has_text, 'has_chapters': has_chapters,
               'edition_revision': passport_revision(book), 'edition_formats': PASSPORT_FORMATS}

    if request.method == 'POST':
        try:
            passport = _confirmed_book_passport(book)
        except BadSignature:
            return render_template(
                'admin/books/edit.html', **context,
                passport_error='Карточка или черновик изменились. Проверьте поля и повторите предпросмотр.',
            ), 409
        except ValueError as error:
            return render_template('admin/books/edit.html', **context, passport_error=str(error)), 422
        book.title = request.form.get('title', book.title).strip()
        book.author = request.form.get('author', book.author).strip()
        submitted_level = request.form.get('level', book.level)
        allowed_levels = (None, '', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2')
        # Preserve legacy CEFR values (e.g. C2) when admin saves an unrelated
        # edit without touching the level dropdown.
        if submitted_level not in allowed_levels and submitted_level != book.level:
            flash(f'Недопустимый уровень "{submitted_level}".', 'danger')
            return render_template('admin/books/edit.html', **context)
        book.level = submitted_level
        book.summary = request.form.get('description', book.summary)

        rights_error = _apply_book_rights_form(book, request.form)
        if rights_error:
            flash(rights_error, 'danger')
            return render_template('admin/books/edit.html', **context)
        if passport:
            book.source_edition_id = passport['source_edition_id']
            book.source_format = passport['source_format']

        if book.create_course:
            from app.curriculum.book_courses import sync_book_course_from_book

            sync_book_course_from_book(book.id, db.session)
        log_admin_action(current_user.id, 'book.update', target_type='book', target_id=book_id, required=bool(passport))
        db.session.commit()
        flash(f'Книга "{book.title}" обновлена', 'success')
        return redirect(materials_return_url() or url_for('book_admin.books'))

    return render_template('admin/books/edit.html', **context)


_BOOK_TEXT_PREFIX = 'book-text-'


@book_bp.route('/books/<int:book_id>/text', methods=['GET', 'POST'])
@admin_required
def upload_book_text(book_id: int) -> ResponseReturnValue:
    """Attach a source to an existing ordinary book with no chapter rows."""
    query = Book.query.filter_by(id=book_id)
    applying = request.method == 'POST' and request.form.get('action') == 'apply'
    if applying:
        query = query.with_for_update().populate_existing()
    book = query.first_or_404()
    if book.is_short_reading or Chapter.query.filter_by(book_id=book_id).first():
        abort(409, 'В карточке уже есть главы или используется редактор короткого чтения.')
    if request.method == 'GET':
        return render_template('admin/books/upload_text.html', book=book)

    signer = URLSafeTimedSerializer(current_app.secret_key, salt='book-text-preview')
    revision = [current_user.id, book.id, book.title, book.author, book.is_published]
    if applying:
        try:
            binding, preview_id = signer.loads(request.form.get('preview_token', ''), max_age=1800)
            staged = load_import_data(preview_id, prefix=_BOOK_TEXT_PREFIX)
            if (binding != revision or not staged or staged['binding'] != revision
                    or not delete_import_data(preview_id, prefix=_BOOK_TEXT_PREFIX)):
                raise BadSignature('stale book text')
        except BadSignature:
            flash('Предпросмотр устарел. Загрузите источник заново.', 'warning')
            return render_template('admin/books/upload_text.html', book=book), 409
        chapters = [ImportedChapter(title, text) for title, text in staged['chapters']]
        install_chapters(book, chapters)
        log_admin_action(current_user.id, 'book.text.attach', target_type='book', target_id=book.id, required=True)
        db.session.commit()
        _finish_book_import(book.id, f'Текст сохранён. Главы: {len(chapters)}.')
        return redirect(url_for('.chapter_list', book_id=book.id), code=303)

    if request.form.get('action') != 'preview':
        abort(400)
    text = request.form.get('content', '')
    try:
        chapters = prepare_chapters(request.files.get('file'), text, book.title)
    except BookUploadError as exc:
        flash(str(exc), 'danger')
        return render_template('admin/books/upload_text.html', book=book, content=text), 422
    except Exception:
        logger.warning('Could not read source for existing book %s', book.id, exc_info=True)
        flash('Не удалось получить текст книги. Проверьте файл или вставьте текст.', 'danger')
        return render_template('admin/books/upload_text.html', book=book, content=text), 422
    preview_id = save_import_data({'binding': revision, 'chapters': [[ch.title, ch.text] for ch in chapters]},
                                  prefix=_BOOK_TEXT_PREFIX, private=True)
    token = signer.dumps([revision, preview_id])
    return render_template('admin/books/upload_text.html', book=book, chapters=chapters, token=token)


@book_bp.post('/books/<int:book_id>/publication')
@admin_required
def book_publication(book_id: int) -> ResponseReturnValue:
    action = request.form.get('action')
    if action not in ('publish', 'unpublish'):
        abort(400)
    book = Book.query.filter_by(id=book_id).with_for_update().populate_existing().first_or_404()
    publish = action == 'publish'
    if publish and not db.session.query(book_has_text(book_id)).scalar():
        flash('Сначала добавьте текст, пригодный для чтения.', 'warning')
        return redirect(url_for('.edit_book', book_id=book_id), code=303)
    if book.is_published != publish:
        book.is_published = publish
        log_admin_action(current_user.id, f'book.{action}', target_type='book', target_id=book.id, required=True)
        db.session.commit()
        clear_admin_cache()
        flash('Книга опубликована.' if publish else 'Книга снята с публикации.', 'success')
    return redirect(url_for('.edit_book', book_id=book_id), code=303)


@book_bp.get('/books/<int:book_id>/chapters')
@admin_required
def chapter_list(book_id: int):
    book = Book.query.get_or_404(book_id)
    chapters = Chapter.query.filter_by(book_id=book.id).order_by(Chapter.chap_num).all()
    return render_template('admin/books/chapters.html', book=book, chapters=chapters,
                           has_text=bool(db.session.query(book_has_text(book_id)).scalar()))


@book_bp.route('/books/<int:book_id>/chapters/<int:chapter_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_chapter(book_id: int, chapter_id: int) -> ResponseReturnValue:
    from app.admin.routes.materials import materials_return_url

    book_query = Book.query.filter_by(id=book_id)
    chapter_query = Chapter.query.filter_by(book_id=book_id, id=chapter_id)
    action = request.form.get('action') if request.method == 'POST' else None
    if action == 'apply':
        book_query = book_query.with_for_update().populate_existing()
        chapter_query = chapter_query.with_for_update().populate_existing()
    book = book_query.first_or_404()
    chapter = chapter_query.first_or_404()
    title, text = chapter.title, text_for_edit(chapter.text_raw)
    revision = chapter_revision(title, text)
    preview, token, error, status = None, '', '', 200
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        text = text_for_edit(request.form.get('text', ''))
        try:
            if request.form.get('revision') != revision:
                raise BadSignature('chapter changed')
            if action not in ('preview', 'apply'):
                raise ValueError('Выберите предпросмотр или сохранение.')
            binding = [current_user.id, chapter.id, revision, chapter_revision(title, text)]
            signer = URLSafeTimedSerializer(current_app.secret_key, salt='admin-chapter-preview')
            if action == 'apply':
                signed = request.form.get('preview_token', '')
                if len(signed) > 1024 or signer.loads(signed, max_age=1800) != binding:
                    raise BadSignature('preview changed')
            preview = review_chapter(book, chapter, title, text)
            if action == 'preview':
                token = signer.dumps(binding)
            else:
                if title != chapter.title or preview.text_changed:
                    apply_chapter(book, chapter, title, text, preview)
                    log_admin_action(current_user.id, 'book.chapter.update', 'chapter', chapter.id, required=True)
                    db.session.commit()
                    clear_admin_cache()
                    flash('Глава сохранена.', 'success')
                return redirect(materials_return_url() or url_for('.chapter_list', book_id=book.id), code=303)
        except BadSignature:
            error, status = 'Глава или черновик изменились. Сверьте данные и заново откройте предпросмотр.', 409
        except ValueError as exc:
            error, status = str(exc), 422
    impact = None
    if (action == 'preview' and status == 200) or (action in ('preview', 'apply') and status == 422):
        impact = chapter_preview_impact(book, chapter, text)
    return render_template('admin/books/edit_chapter.html', book=book, chapter=chapter, title=title, text=text,
                           revision=revision, preview=preview, impact=impact, token=token, error=error), status


# ---------------------------------------------------------------------------
# Rights / licensing metadata form handling
# ---------------------------------------------------------------------------

_RIGHTS_STATUS_CHOICES = ('public_domain', 'licensed', 'companion_only')
_AUDIO_RIGHTS_CHOICES = ('public_domain', 'licensed', 'companion_only', 'none')


def _apply_book_rights_form(book, form) -> str | None:
    """Validate & apply rights fields from the admin edit form.

    Returns an error message string on failure, ``None`` on success. Does not
    commit — the caller's existing ``db.session.commit()`` covers it.
    """
    from datetime import date as _date

    rights_status = (form.get('rights_status') or book.rights_status or 'companion_only').strip()
    if rights_status not in _RIGHTS_STATUS_CHOICES:
        return f'Недопустимый rights_status: {rights_status!r}'

    audio_rights = (form.get('audio_rights_status') or book.audio_rights_status or 'companion_only').strip()
    if audio_rights not in _AUDIO_RIGHTS_CHOICES:
        return f'Недопустимый audio_rights_status: {audio_rights!r}'

    raw_pct = form.get('allowed_text_percent')
    if raw_pct is None or raw_pct == '':
        allowed_pct = 100 if book.allowed_text_percent is None else book.allowed_text_percent
    else:
        try:
            allowed_pct = int(raw_pct)
        except (TypeError, ValueError):
            return 'allowed_text_percent должен быть целым числом 0–100'
        if not 0 <= allowed_pct <= 100:
            return 'allowed_text_percent должен быть в диапазоне 0–100'

    expiration_raw = (form.get('expiration_date', book.expiration_date.isoformat() if book.expiration_date else '') or '').strip()
    if expiration_raw:
        try:
            expiration = _date.fromisoformat(expiration_raw)
        except ValueError:
            return 'expiration_date должен быть в формате YYYY-MM-DD'
    else:
        expiration = None

    book.rights_status = rights_status
    book.audio_rights_status = audio_rights
    book.allowed_text_percent = allowed_pct
    book.expiration_date = expiration
    if 'source_url' in form:
        book.source_url = form['source_url'].strip() or None
    book.license_type = (form.get('license_type', book.license_type) or '').strip() or None
    if 'permission_document' in form:
        book.permission_document = form['permission_document'].strip() or None
    book.territory = (form.get('territory', book.territory) or 'worldwide').strip() or 'worldwide'
    if 'rights_status' in form or 'commercial_use_allowed' in form:
        book.commercial_use_allowed = form.get('commercial_use_allowed') == 'on'
    return None


def _book_has_dependents(book_id: int) -> bool:
    from app.books.models import Block, Bookmark, UserChapterProgress
    from app.books.reading_session import UserReadingSession
    from app.curriculum.book_courses import BookCourse
    from app.curriculum.daily_lessons import DailyLesson
    from app.curriculum.models import Lessons
    from app.daily_plan.linear.models import UserReadingPreference

    chapter_ids = db.select(Chapter.id).where(Chapter.book_id == book_id)
    references = (
        Block.book_id == book_id,
        Bookmark.book_id == book_id,
        BookCourse.book_id == book_id,
        Lessons.book_id == book_id,
        UserReadingPreference.book_id == book_id,
        DailyLesson.chapter_id.in_(chapter_ids),
        UserChapterProgress.chapter_id.in_(chapter_ids),
        UserReadingSession.chapter_id.in_(chapter_ids),
    )
    return bool(db.session.query(db.or_(*(db.exists().where(reference) for reference in references))).scalar())


@book_bp.route('/books/<int:book_id>/delete', methods=['GET', 'POST'])
@admin_required
def delete_book(book_id: int) -> ResponseReturnValue:
    query = Book.query.filter_by(id=book_id)
    if request.method == 'POST':
        query = query.with_for_update().populate_existing()
    book = query.first_or_404()
    if request.method == 'POST':
        if request.form.get('confirm') != 'yes':
            return jsonify({'success': False, 'error': 'Подтвердите удаление в карточке книги.'}), 400
        db.session.query(Chapter.id).filter_by(book_id=book_id).with_for_update().all()
    blocked = book.is_published or _book_has_dependents(book.id)
    if request.method == 'GET' or blocked:
        return render_template('admin/books/delete.html', book=book, blocked=blocked), 409 if blocked else 200

    db.session.delete(book)
    log_admin_action(current_user.id, 'book.delete', target_type='book', target_id=book_id, required=True)
    db.session.commit()
    clear_admin_cache()
    flash('Книга удалена.', 'success')
    return redirect(url_for('.books'), code=303)


def _finish_book_import(book_id: int, message: str) -> None:
    clear_admin_cache()
    try:
        BookProcessingService.start_background_chapter_processing(current_app._get_current_object(), book_id)
    except Exception:
        logger.exception('Could not start chapter indexing for book %s', book_id)
        flash(f'{message} Обработку слов не удалось запустить.', 'warning')
    else:
        flash(message, 'success')


@book_bp.route('/books/add', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def add_book() -> ResponseReturnValue:
    """Prepare a readable book before writing its catalogue and chapter rows."""
    form = BookContentForm()
    if request.method == 'GET':
        return render_template('admin/books/add.html', form=form)

    if not form.validate_on_submit():
        return render_template('admin/books/add.html', form=form), 400

    try:
        passport = _confirmed_book_passport(None)
    except BadSignature:
        return render_template(
            'admin/books/add.html', form=form,
            passport_error='Предпросмотр устарел. Выберите тот же файл и повторите предпросмотр.',
        ), 409
    except ValueError as error:
        return render_template('admin/books/add.html', form=form, passport_error=str(error)), 422

    title = form.title.data.strip()
    author = (form.author.data or '').strip()
    book = Book(title=title, author=author, level=form.level.data,
                created_at=datetime.now(UTC).replace(tzinfo=None), is_published=False)
    if rights_error := _apply_book_rights_form(book, request.form):
        flash(rights_error, 'danger')
        return render_template('admin/books/add.html', form=form), 422
    if passport:
        book.source_edition_id = passport['source_edition_id']
        book.source_format = passport['source_format']

    try:
        chapters = prepare_chapters(form.file.data, form.content.data or '', title)
    except BookUploadError as exc:
        flash(str(exc), 'danger')
        return render_template('admin/books/add.html', form=form), 422
    except Exception:
        logger.warning('Book import could not read the submitted source', exc_info=True)
        flash('Не удалось получить текст книги. Проверьте файл или вставьте текст.', 'danger')
        return render_template('admin/books/add.html', form=form), 422

    # Serialise matching uploads through this form even when the title is new.
    if db.session.get_bind().dialect.name == 'postgresql':
        db.session.execute(db.text(
            'SELECT pg_advisory_xact_lock(624117066, hashtext(lower(:title) || chr(31) || lower(:author)))'
        ), {'title': title, 'author': author})
    existing = Book.query.filter(func.lower(Book.title) == func.lower(title),
                                 func.lower(Book.author) == func.lower(author)).first()
    if existing is not None:
        flash('Книга с таким названием и автором уже существует.', 'danger')
        return render_template('admin/books/add.html', form=form, existing_book=existing), 409

    if form.cover_image.data:
        book.cover_image = BookProcessingService.save_cover_image(form.cover_image.data)
        if not book.cover_image:
            return render_template('admin/books/add.html', form=form), 422
    try:
        install_chapters(book, chapters)
        db.session.add(book)
        db.session.flush()
        log_admin_action(current_user.id, 'book.create', target_type='book', target_id=book.id, required=True)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if book.cover_image:
            try:
                Path(book.cover_image).unlink(missing_ok=True)
            except OSError:
                logger.warning('Could not remove cover after failed book import', exc_info=True)
        logger.exception('Could not save imported book')
        flash('Не удалось сохранить книгу. Попробуйте ещё раз.', 'danger')
        return render_template('admin/books/add.html', form=form), 500

    _finish_book_import(book.id, f'Черновик сохранён. Главы: {len(chapters)}.')
    return redirect(url_for('.chapter_list', book_id=book.id), code=303)
