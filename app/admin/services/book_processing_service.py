# app/admin/services/book_processing_service.py

"""
Сервис для обработки книг (Books Processing Service)
Обрабатывает книги, главы, метаданные и статистику
"""
import html
import json
import logging
import pathlib
import re
import shutil
import subprocess
import tempfile

from flask import flash
from sqlalchemy import func

from app.books.models import Book, Chapter
from app.utils.db import db
from app.utils.file_security import process_and_save_cover_image

logger = logging.getLogger(__name__)


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
                    cmd = f'python convert_fb2_to_txt.py "{input_file}" "{txt_file}"'
                    logger.info(f"[CHAPTER_PROCESS] Running conversion command: {cmd}")
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
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
                cmd = f'python "{prepare_script}"'
                logger.info(f"[CHAPTER_PROCESS] Executing command: {cmd}")
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
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
