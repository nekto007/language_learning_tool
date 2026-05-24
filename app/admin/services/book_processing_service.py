# app/admin/services/book_processing_service.py

"""
Сервис для обработки книг (Books Processing Service)
Обрабатывает книги, главы, метаданные и статистику
"""
import html
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Optional, Tuple

from flask import flash
from sqlalchemy import func
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.books.models import Book, Chapter
from app.utils.db import db
from app.utils.file_security import process_and_save_cover_image

logger = logging.getLogger(__name__)

# Upload limits and allowed types for admin book uploads.
ALLOWED_BOOK_EXTENSIONS = frozenset({'txt', 'fb2', 'epub', 'pdf', 'docx'})
MAX_BOOK_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Public so callers can resolve uploads (and so tests can monkey-patch a tmp dir).
BOOK_TEMP_DIR = os.path.join('app', 'temp')


class BookUploadError(ValueError):
    """Raised when an uploaded book file fails validation."""


def save_uploaded_book_file(
    file: FileStorage,
    *,
    temp_dir: Optional[str] = None,
    allowed_extensions: frozenset = ALLOWED_BOOK_EXTENSIONS,
    max_size_bytes: int = MAX_BOOK_UPLOAD_BYTES,
) -> Tuple[str, str, str]:
    """
    Validate and persist an uploaded book file to a temp directory.

    Performs extension allow-list check, max-size check, and path-traversal
    defense: the resolved final path MUST stay inside ``temp_dir``.

    Returns (temp_path, safe_filename, ext_with_dot).
    Raises BookUploadError on any validation failure; the caller is expected
    to surface a 400 to the client.
    """
    if file is None or not getattr(file, 'filename', None):
        raise BookUploadError('Файл не выбран')

    safe_name = secure_filename(file.filename)
    if not safe_name or '.' not in safe_name:
        raise BookUploadError('Недопустимое имя файла')

    extension = safe_name.rsplit('.', 1)[1].lower()
    if extension not in allowed_extensions:
        raise BookUploadError(
            f'Расширение .{extension} не разрешено. Разрешены: {", ".join(sorted(allowed_extensions))}'
        )

    # Size check (rewinds the stream so the caller can re-read it).
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size <= 0:
        raise BookUploadError('Файл пуст')
    if size > max_size_bytes:
        mb = max_size_bytes // (1024 * 1024)
        raise BookUploadError(f'Размер файла превышает {mb} МБ')

    target_dir = temp_dir or BOOK_TEMP_DIR
    os.makedirs(target_dir, exist_ok=True)

    target_path = os.path.join(target_dir, safe_name)
    # Defense-in-depth: resolved path MUST stay inside target_dir.
    real_dir = os.path.realpath(target_dir)
    real_target = os.path.realpath(target_path)
    if os.path.commonpath([real_dir, real_target]) != real_dir:
        raise BookUploadError('Недопустимый путь файла')

    file.save(target_path)
    return target_path, safe_name, f'.{extension}'


class BookProcessingService:
    """Сервис для обработки книг и их содержимого"""

    @staticmethod
    def get_book_statistics():
        """Получает статистику по книгам"""
        try:
            # Топ-5 книг по количеству слов
            top_books = db.session.query(
                Book.title,
                Book.words_total,
                Book.unique_words
            ).order_by(Book.words_total.desc()).limit(5).all()

            # Общая статистика
            total_books = Book.query.count()
            words_total_all_books = db.session.query(func.sum(Book.words_total)).scalar() or 0
            total_unique_words_all = db.session.query(func.sum(Book.unique_words)).scalar() or 0

            return {
                'top_books': [
                    {
                        'title': book.title,
                        'words_total': book.words_total,
                        'unique_words': book.unique_words
                    }
                    for book in top_books
                ],
                'totals': {
                    'total_books': total_books,
                    'words_total_all_books': words_total_all_books,
                    'total_unique_words_all': total_unique_words_all
                }
            }
        except Exception as e:
            logger.error(f"Error getting book statistics: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def normalize(txt: str) -> str:
        """
        Normalize text by unescaping HTML entities and replacing smart quotes

        Args:
            txt: Text to normalize

        Returns:
            str: Normalized text
        """
        txt = html.unescape(txt)
        txt = txt.replace(""", '"').replace(""", '"')
        txt = txt.replace("'", "'").replace("'", "'")
        txt = txt.replace("—", "—")
        txt = re.sub(r"[ \t]+", " ", txt)
        return txt.strip()

    @staticmethod
    def process_book_into_chapters(book_id, file_path, file_ext):
        """
        Process uploaded book file into chapters using the conversion pipeline:
        FB2 -> TXT -> JSONL -> Database chapters

        Args:
            book_id: ID книги в базе данных
            file_path: Путь к загруженному файлу
            file_ext: Расширение файла (например, '.fb2' или '.txt')

        Returns:
            tuple: (success: bool, message: str)
        """
        logger.info(
            f"[CHAPTER_PROCESS] Starting chapter processing for book ID: {book_id}, file: {file_path}, format: {file_ext}"
        )

        try:
            book = Book.query.get(book_id)
            if not book:
                logger.error(f"[CHAPTER_PROCESS] Book with id {book_id} not found")
                raise ValueError(f"Book with id {book_id} not found")

            logger.info(f"[CHAPTER_PROCESS] Processing book: '{book.title}' by {book.author}")

            # Create temporary directory for processing
            logger.info("[CHAPTER_PROCESS] Creating temporary directory for processing")
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = pathlib.Path(temp_dir)
                logger.info(f"[CHAPTER_PROCESS] Temporary directory created: {temp_path}")

                # Copy uploaded file to temp directory
                input_file = temp_path / f"book{file_ext}"
                logger.info(f"[CHAPTER_PROCESS] Copying file to temporary location: {input_file}")
                shutil.copy(file_path, input_file)
                logger.info("[CHAPTER_PROCESS] File copied successfully")

                # Step 1: Convert FB2 to TXT if needed
                if file_ext.lower() == '.fb2':
                    logger.info("[CHAPTER_PROCESS] Converting FB2 to TXT format")
                    txt_file = temp_path / "book.txt"
                    cmd = ['python', 'convert_fb2_to_txt.py', str(input_file), str(txt_file)]
                    logger.info(f"[CHAPTER_PROCESS] Running conversion command: {cmd}")
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        logger.error(
                            f"[CHAPTER_PROCESS] FB2 conversion failed with return code {result.returncode}")
                        logger.error(f"[CHAPTER_PROCESS] Error output: {result.stderr}")
                        raise Exception(f"FB2 conversion failed: {result.stderr}")
                    input_file = txt_file
                    logger.info("[CHAPTER_PROCESS] FB2 to TXT conversion completed successfully")
                elif file_ext.lower() == '.txt':
                    logger.info(f"[CHAPTER_PROCESS] Using TXT file as-is (format: {file_ext})")
                else:
                    logger.error(f"[CHAPTER_PROCESS] Unsupported file format: {file_ext}")
                    raise ValueError(
                        f"Unsupported file format: {file_ext}. Only FB2 and TXT files are supported for chapter processing."
                    )

                # Step 2: Prepare text and create JSONL
                logger.info("[CHAPTER_PROCESS] Starting text preparation and JSONL creation")
                jsonl_file = temp_path / "chapters.jsonl"

                # Create prepare_text.py script content inline
                prepare_script = temp_path / "prepare_text_inline.py"
                prepare_script.write_text('''
import re, json, pathlib, html

chapter_pat = re.compile(r"^###\\s*CHAPTER_(\\d+)\\s*(.*)", re.I)

def normalize(txt: str) -> str:
    txt = html.unescape(txt)
    txt = txt.replace(""", '"').replace(""", '"')
    txt = txt.replace("'", "'").replace("'", "'")
    txt = txt.replace("—", "—")
    txt = re.sub(r"[ \\t]+", " ", txt)
    return txt.strip()

SRC = pathlib.Path(r"{input_file}")
DST = pathlib.Path(r"{jsonl_file}")
with DST.open("w", encoding="utf-8") as out:
    chap_no, chap_title, buff = None, "", []
    for line in SRC.read_text(encoding="utf-8").splitlines():
        m = chapter_pat.match(line)
        if m:
            if chap_no:
                text = normalize("\\n".join(buff))
                words = len(re.findall(r"\\b[\\w']+\\b", text))
                out.write(json.dumps({{
                    "chap": chap_no,
                    "title": chap_title or f"Chapter {{chap_no}}",
                    "words": words,
                    "text": text
                }}, ensure_ascii=False) + "\\n")
                buff.clear()
            chap_no, chap_title = int(m[1]), m[2].strip()
        else:
            buff.append(line)
    # Last chapter
    if chap_no:
        text = normalize("\\n".join(buff))
        words = len(re.findall(r"\\b[\\w']+\\b", text))
        out.write(json.dumps({{
            "chap": chap_no,
            "title": chap_title or f"Chapter {{chap_no}}",
            "words": words,
            "text": text
        }}, ensure_ascii=False) + "\\n")'''.format(input_file=input_file, jsonl_file=jsonl_file))

                # Run the prepare script
                logger.info("[CHAPTER_PROCESS] Running text preparation script")
                cmd = ['python', str(prepare_script)]
                logger.info(f"[CHAPTER_PROCESS] Executing command: {cmd}")
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(
                        f"[CHAPTER_PROCESS] Text preparation failed with return code {result.returncode}")
                    logger.error(f"[CHAPTER_PROCESS] Error output: {result.stderr}")
                    raise Exception(f"Text preparation failed: {result.stderr}")
                logger.info("[CHAPTER_PROCESS] Text preparation completed successfully")

                # Step 3: Load chapters from JSONL into database
                logger.info("[CHAPTER_PROCESS] Loading chapters from JSONL into database")
                chapters_data = []
                total_words = 0

                with jsonl_file.open('r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        try:
                            chapter_data = json.loads(line)
                            chapters_data.append(chapter_data)
                            total_words += chapter_data['words']
                        except json.JSONDecodeError as e:
                            logger.error(f"[CHAPTER_PROCESS] JSON decode error on line {line_num}: {str(e)}")
                            raise Exception(f"JSON decode error on line {line_num}: {str(e)}")

                logger.info(
                    f"[CHAPTER_PROCESS] Loaded {len(chapters_data)} chapters with total {total_words} words")

                # Update book statistics
                book.chapters_cnt = len(chapters_data)
                book.words_total = total_words
                logger.info(
                    f"[CHAPTER_PROCESS] Updated book statistics - Chapters: {book.chapters_cnt}, Words: {book.words_total}"
                )

                # Delete existing chapters if any
                existing_chapters = Chapter.query.filter_by(book_id=book.id).count()
                if existing_chapters > 0:
                    logger.info(f"[CHAPTER_PROCESS] Deleting {existing_chapters} existing chapters")
                    Chapter.query.filter_by(book_id=book.id).delete()

                # Insert new chapters
                logger.info("[CHAPTER_PROCESS] Inserting new chapters into database")
                for i, chapter_data in enumerate(chapters_data, 1):
                    logger.debug(
                        f"[CHAPTER_PROCESS] Creating chapter {i}/{len(chapters_data)}: '{chapter_data['title']}' ({chapter_data['words']} words)"
                    )
                    text_raw = chapter_data['text'].replace('\n\n', '\\n\\n')
                    chapter = Chapter(
                        book_id=book.id,
                        chap_num=chapter_data['chap'],
                        title=chapter_data['title'],
                        words=chapter_data['words'],
                        text_raw=text_raw
                    )
                    db.session.add(chapter)

                logger.info("[CHAPTER_PROCESS] Committing chapters to database")
                db.session.commit()
                logger.info(
                    f"[CHAPTER_PROCESS] Successfully processed {len(chapters_data)} chapters for book '{book.title}'"
                )
                return True, f"Successfully imported {len(chapters_data)} chapters"

        except Exception as e:
            logger.error(f"[CHAPTER_PROCESS] Error processing book into chapters: {str(e)}")
            logger.error(f"[CHAPTER_PROCESS] Exception type: {type(e).__name__}")
            db.session.rollback()
            return False, str(e)

    @staticmethod
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
        result = process_and_save_cover_image(file)
        if result is None:
            flash('Ошибка при загрузке файла. Проверьте формат и размер изображения.', 'danger')
        return result

    @staticmethod
    def start_background_chapter_processing(app, book_id: int) -> threading.Thread:
        """
        Start a daemon thread that runs ``safe_process_book_chapters_words``
        for the given book within an application context.

        Extracted from ``add_book`` so the route stays slim and we can test
        the launcher in isolation. Returns the started Thread.
        """

        def _worker():
            logger.info("Book chapter processing started: book_id=%s", book_id)
            success = False
            try:
                with app.app_context():
                    from app.books.safe_processors import safe_process_book_chapters_words
                    result = safe_process_book_chapters_words(book_id)
                    status = result.get('status', 'unknown')
                    success = (status == 'success')
                    logger.info(
                        "Book chapter processing finished: book_id=%s status=%s",
                        book_id, status,
                    )
            except Exception as exc:
                if not success:
                    logger.error(
                        "Book chapter processing failed: book_id=%s error=%s",
                        book_id, exc, exc_info=True,
                    )

        thread = threading.Thread(target=_worker, name=f"BookChapterProcessor-{book_id}", daemon=True)
        thread.start()
        return thread

    @staticmethod
    def start_background_word_processing(app, book_id: int, book_content: str) -> threading.Thread:
        """Background launcher for safe_process_book_words (non-chapter path)."""

        def _worker():
            try:
                with app.app_context():
                    from app.books.safe_processors import safe_process_book_words
                    result = safe_process_book_words(book_id, book_content)
                    logger.info(f"[ADMIN] Processing result: {result}")
            except Exception as exc:
                logger.error(f"[ADMIN] Error in word processing thread: {exc}")

        thread = threading.Thread(target=_worker, name=f"BookWordProcessor-{book_id}", daemon=True)
        thread.start()
        return thread
