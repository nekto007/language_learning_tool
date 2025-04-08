# app/books/parser.py

import logging
import os
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


def parse_book_file(file_path, file_ext, format_type='enhanced'):
    """
    Парсит файл книги и возвращает HTML-контент с сохранением форматирования

    Args:
        file_path: Путь к файлу книги
        file_ext: Расширение файла (.txt, .fb2, .epub, и т.д.)
        format_type: Тип форматирования (auto, simple, enhanced)

    Returns:
        tuple: (html_content, word_count, unique_words_count)
    """
    file_ext = file_ext.lower()

    if file_ext == '.txt':
        return parse_txt(file_path, format_type)
    elif file_ext == '.fb2':
        return parse_fb2(file_path, format_type)
    elif file_ext == '.epub':
        return parse_epub(file_path, format_type)
    elif file_ext == '.pdf':
        return parse_pdf(file_path, format_type)
    elif file_ext == '.docx':
        return parse_docx(file_path, format_type)
    else:
        raise ValueError(f"Unsupported file format: {file_ext}")


def parse_txt(file_path, format_type):
    """Парсит TXT-файл"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
    except UnicodeDecodeError:
        # Попробуем другие кодировки
        encodings = ['latin-1', 'cp1251', 'windows-1251']
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as file:
                    content = file.read()
                break
            except UnicodeDecodeError:
                continue

    # Процесс нормализации текста
    # Удаляем лишние пробелы между словами
    content = re.sub(r'\s+', ' ', content)

    # Восстанавливаем правильные переносы абзацев
    content = re.sub(r'\n\s*\n', '\n\n', content)

    # Подсчет слов
    words = re.findall(r'\b[a-zA-Z]+\b', content.lower())
    word_count = len(words)
    unique_words = len(set(words))

    # Форматирование в зависимости от выбранного типа
    if format_type == 'simple':
        # Простое форматирование с абзацами
        paragraphs = content.split('\n\n')
        normalized_paragraphs = []

        for paragraph in paragraphs:
            # Нормализуем текст абзаца
            normalized_paragraph = re.sub(r'\s+', ' ', paragraph).strip()
            if normalized_paragraph:
                normalized_paragraphs.append(normalized_paragraph)

        html_content = '<p>' + '</p><p>'.join(normalized_paragraphs) + '</p>'

    elif format_type == 'enhanced':
        # Улучшенное форматирование для изучения языка
        paragraphs = content.split('\n\n')
        html_parts = []
        chapter_pattern = re.compile(r'^(?:Chapter|CHAPTER)\s+(\d+|[IVXLCDM]+)(?:\s*[:.-]\s*)?(.*)$', re.IGNORECASE)

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            # Нормализуем текст абзаца
            normalized_paragraph = re.sub(r'\s+', ' ', paragraph).strip()

            # Проверяем, является ли абзац заголовком главы
            chapter_match = chapter_pattern.match(normalized_paragraph)
            if chapter_match:
                chapter_num = chapter_match.group(1)
                chapter_title = chapter_match.group(2).strip() if chapter_match.group(2) else ""
                if chapter_title:
                    html_parts.append(f'<h2>Chapter {chapter_num}: {chapter_title}</h2>')
                else:
                    html_parts.append(f'<h2>Chapter {chapter_num}</h2>')
            else:
                # Важно: добавляем абзац БЕЗ атрибута class
                html_parts.append(f'<p>{normalized_paragraph}</p>')

        html_content = ''.join(html_parts)

    else:  # auto
        # Автоматическое обнаружение структуры с нормализованными пробелами
        normalized_content = re.sub(r'\s+', ' ', content)
        html_content = f'<div>{normalized_content}</div>'

    return html_content, word_count, unique_words


def parse_fb2(file_path, format_type):
    """Парсит FB2-файл (FictionBook)"""
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        namespace = ''
        if root.tag.startswith('{'):
            namespace = root.tag.split('}')[0] + '}'
        # Извлекаем текст из body
        body = root.find('.//' + namespace + 'body')
        if body is None:
            raise ValueError("Could not find body element in FB2 file")

        html_parts = []
        word_count = 0
        unique_words = set()
        # Перебираем секции и получаем текст
        for section in body.findall('.//' + namespace + 'section'):
            # Проверяем, есть ли заголовок
            title = section.find('.//' + namespace + 'title')
            if title is not None:
                title_text = ''.join(title.itertext()).strip()
                title_text = re.sub(r'\s+', ' ', title_text)  # Нормализуем пробелы
                if title_text:
                    html_parts.append(f"<h2>{title_text}</h2>")

            # Обрабатываем абзацы
            for p in section.findall('.//' + namespace + 'p'):
                p_text = ''.join(p.itertext()).strip()
                p_text = re.sub(r'\s+', ' ', p_text)  # Нормализуем пробелы
                if p_text:
                    html_parts.append(f'<p class="book-paragraph">{p_text}</p>')

                    # Подсчет слов
                    words = re.findall(r'\b[a-zA-Z]+\b', p_text.lower())
                    word_count += len(words)
                    unique_words.update(words)

        # Формируем HTML контент
        html_content = ''.join(html_parts)
        return html_content, word_count, len(unique_words)

    except Exception as e:
        logger.error(f"Error parsing FB2 file: {str(e)}")
        # В случае ошибки возвращаем простой текст
        return parse_txt(file_path, format_type)


def parse_epub(file_path, format_type):
    """
    Парсит EPUB-файл

    Требует установки библиотеки ebooklib:
    pip install ebooklib
    """
    try:
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(file_path)

        html_parts = []
        word_count = 0
        unique_words = set()

        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = item.get_content().decode('utf-8')

                # Используем BeautifulSoup для парсинга HTML
                soup = BeautifulSoup(content, 'html.parser')

                # Извлекаем заголовки и абзацы
                for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
                    text = tag.get_text().strip()
                    text = re.sub(r'\s+', ' ', text)  # Нормализуем пробелы
                    if text:
                        if tag.name.startswith('h'):
                            html_parts.append(f"<{tag.name}>{text}</{tag.name}>")
                        else:
                            html_parts.append(f'<p class="book-paragraph">{text}</p>')

                        # Подсчет слов
                        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
                        word_count += len(words)
                        unique_words.update(words)

        # Формируем HTML контент
        html_content = ''.join(html_parts)

        return html_content, word_count, len(unique_words)

    except ImportError:
        logger.error("ebooklib not installed. Install with: pip install ebooklib")
        # В случае отсутствия библиотеки, возвращаем простой текст
        return parse_txt(file_path, format_type)
    except Exception as e:
        logger.error(f"Error parsing EPUB file: {str(e)}")
        return parse_txt(file_path, format_type)


def parse_pdf(file_path, format_type):
    """
    Парсит PDF-файл

    Требует установки библиотеки PyPDF2:
    pip install PyPDF2
    """
    try:
        import PyPDF2

        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)

            # Извлекаем текст из всех страниц
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n\n"

        # Нормализация пробелов
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)

        # Подсчет слов
        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
        word_count = len(words)
        unique_words = len(set(words))

        # Форматируем текст
        if format_type == 'simple':
            paragraphs = text.split('\n\n')
            normalized_paragraphs = []

            for paragraph in paragraphs:
                normalized_paragraph = re.sub(r'\s+', ' ', paragraph).strip()
                if normalized_paragraph:
                    normalized_paragraphs.append(normalized_paragraph)

            html_content = '<p>' + '</p><p>'.join(normalized_paragraphs) + '</p>'

        elif format_type == 'enhanced':
            paragraphs = text.split('\n\n')
            html_parts = []

            for paragraph in paragraphs:
                paragraph = paragraph.strip()
                if not paragraph:
                    continue

                # Нормализуем текст
                normalized_paragraph = re.sub(r'\s+', ' ', paragraph).strip()

                # Проверяем, может ли абзац быть заголовком
                if len(paragraph) < 100 and paragraph.isupper():
                    html_parts.append(f"<h2>{normalized_paragraph}</h2>")
                else:
                    html_parts.append(f'<p class="book-paragraph">{normalized_paragraph}</p>')

            html_content = ''.join(html_parts)
        else:  # auto
            html_content = f'<div class="book-text">{text}</div>'

        return html_content, word_count, unique_words

    except ImportError:
        logger.error("PyPDF2 not installed. Install with: pip install PyPDF2")
        return parse_txt(file_path, format_type)
    except Exception as e:
        logger.error(f"Error parsing PDF file: {str(e)}")
        return parse_txt(file_path, format_type)


def parse_docx(file_path, format_type):
    """
    Парсит DOCX-файл

    Требует установки библиотеки python-docx:
    pip install python-docx
    """
    try:
        from docx import Document

        doc = Document(file_path)

        html_parts = []
        word_count = 0
        unique_words = set()

        # Обрабатываем абзацы
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue

            # Нормализуем текст
            text = re.sub(r'\s+', ' ', text).strip()

            # Проверяем, является ли абзац заголовком
            if paragraph.style.name.startswith('Heading'):
                level = paragraph.style.name.replace('Heading', '')
                try:
                    level = int(level)
                    if 1 <= level <= 6:
                        html_parts.append(f"<h{level}>{text}</h{level}>")
                    else:
                        html_parts.append(f"<h2>{text}</h2>")
                except ValueError:
                    html_parts.append(f"<h2>{text}</h2>")
            else:
                html_parts.append(f'<p class="book-paragraph">{text}</p>')

            # Подсчет слов
            words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
            word_count += len(words)
            unique_words.update(words)

        # Формируем HTML контент
        html_content = ''.join(html_parts)

        return html_content, word_count, len(unique_words)

    except ImportError:
        logger.error("python-docx not installed. Install with: pip install python-docx")
        return parse_txt(file_path, format_type)
    except Exception as e:
        logger.error(f"Error parsing DOCX file: {str(e)}")
        return parse_txt(file_path, format_type)


def process_uploaded_book(file, title, format_type='enhanced'):
    """
    Обрабатывает загруженный файл книги

    Args:
        file: Объект загруженного файла
        title: Название книги
        format_type: Тип форматирования

    Returns:
        dict: {'content': html_content, 'word_count': word_count, 'unique_words': unique_words}
    """
    try:
        # Проверяем, что file - это объект файла, а не строка
        if not file or not hasattr(file, 'filename'):
            raise ValueError("Invalid file object - missing filename attribute")

        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()

        # Создаем временный файл
        temp_dir = 'app/temp'
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, filename)

        file.save(temp_path)

        # Обрабатываем файл
        html_content, word_count, unique_words = parse_book_file(temp_path, file_ext, format_type)

        # Удаляем временный файл
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return {
            'content': html_content,
            'word_count': word_count,
            'unique_words': unique_words
        }

    except Exception as e:
        logger.error(f"Error processing book file: {str(e)}")
        # Очищаем временные файлы
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        raise e
