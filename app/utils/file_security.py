"""
Утилиты для безопасной обработки загружаемых файлов
"""
import logging
import os
import uuid
from typing import Optional, Tuple

from PIL import Image
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# Конфигурация
UPLOAD_BASE_FOLDER = 'uploads'  # За пределами app/static
COVER_UPLOAD_FOLDER = os.path.join(UPLOAD_BASE_FOLDER, 'covers')
ALLOWED_IMAGE_TYPES = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_MIME_TYPES = {'image/png', 'image/jpeg', 'image/gif'}
MAX_COVER_WIDTH = 400
MAX_COVER_HEIGHT = 600
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def validate_image_mime_type(file_path: str) -> bool:
    """
    Проверяет реальный MIME-тип файла, а не только расширение

    Args:
        file_path: Путь к файлу для проверки

    Returns:
        bool: True если файл - валидное изображение разрешенного типа
    """
    try:
        # Используем Pillow для определения реального типа изображения
        with Image.open(file_path) as img:
            # Получаем формат изображения (PNG, JPEG, GIF и т.д.)
            image_format = img.format

            if image_format is None:
                logger.warning(f"File {file_path} is not a valid image")
                return False

            # Нормализуем формат к нижнему регистру и преобразуем JPEG -> jpg
            image_type = image_format.lower()
            if image_type == 'jpeg':
                image_type = 'jpg'

            # Проверяем, что тип разрешен
            if image_type not in ALLOWED_IMAGE_TYPES:
                logger.warning(f"Image type {image_type} is not allowed")
                return False

            # Проверяем, что файл - валидное изображение
            img.verify()
            return True

    except Exception as e:
        logger.error(f"Error validating image MIME type: {e}")
        return False


def strip_image_metadata(image: Image.Image) -> Image.Image:
    """
    Удаляет все EXIF и другие метаданные из изображения

    Args:
        image: PIL Image объект

    Returns:
        Image: Очищенное изображение без метаданных
    """
    try:
        # Создаем новое изображение без метаданных
        data = list(image.getdata())
        image_without_exif = Image.new(image.mode, image.size)
        image_without_exif.putdata(data)

        return image_without_exif
    except Exception as e:
        logger.warning(f"Could not strip metadata, returning original: {e}")
        return image


def process_and_save_cover_image(
    file: FileStorage,
    upload_folder: str = COVER_UPLOAD_FOLDER
) -> Optional[str]:
    """
    Безопасно обрабатывает и сохраняет обложку книги с полной валидацией

    Выполняет:
    - Проверку размера файла
    - Валидацию реального MIME-типа (не только расширения)
    - Удаление всех EXIF и метаданных
    - Изменение размера с сохранением пропорций
    - Сохранение в безопасной директории вне app/static

    Args:
        file: Объект загруженного файла
        upload_folder: Папка для сохранения (по умолчанию COVER_UPLOAD_FOLDER)

    Returns:
        str: Относительный путь к сохраненному файлу или None в случае ошибки
    """
    # Базовые проверки
    if not file or not hasattr(file, 'filename'):
        logger.warning("Invalid file object provided")
        return None

    if not file.filename:
        logger.warning("Empty filename provided")
        return None

    # Проверка расширения (первичная фильтрация)
    original_filename = secure_filename(file.filename)
    if '.' not in original_filename:
        logger.warning(f"No extension in filename: {original_filename}")
        return None

    extension = original_filename.rsplit('.', 1)[1].lower()
    if extension not in ALLOWED_IMAGE_TYPES:
        logger.warning(f"Extension {extension} not allowed")
        return None

    # Проверка размера файла
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE:
        logger.warning(f"File size {file_size} exceeds limit {MAX_FILE_SIZE}")
        return None

    # Создаем директорию для загрузок
    os.makedirs(upload_folder, exist_ok=True)

    # Генерируем уникальное имя файла
    # Всегда используем .jpg для унификации и безопасности
    unique_filename = f"{uuid.uuid4().hex}.jpg"
    temp_filepath = os.path.join(upload_folder, f"temp_{unique_filename}")
    final_filepath = os.path.join(upload_folder, unique_filename)

    try:
        # Сохраняем временный файл для валидации
        file.save(temp_filepath)

        # КРИТИЧНО: Проверяем реальный MIME-тип файла
        if not validate_image_mime_type(temp_filepath):
            logger.warning(f"MIME type validation failed for {original_filename}")
            os.remove(temp_filepath)
            return None

        # Открываем и обрабатываем изображение
        with Image.open(temp_filepath) as img:
            # Конвертируем в RGB (убирает альфа-канал и унифицирует формат)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if 'A' in img.mode:
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # КРИТИЧНО: Удаляем все метаданные (EXIF, GPS и т.д.)
            img = strip_image_metadata(img)

            # Изменяем размер с сохранением пропорций
            img_width, img_height = img.size
            if img_width > MAX_COVER_WIDTH or img_height > MAX_COVER_HEIGHT:
                ratio = min(MAX_COVER_WIDTH / img_width, MAX_COVER_HEIGHT / img_height)
                new_width = int(img_width * ratio)
                new_height = int(img_height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Сохраняем как JPEG без метаданных
            # exif=b"" гарантирует отсутствие EXIF данных
            img.save(final_filepath, format='JPEG', quality=85, optimize=True, exif=b"")

        # Удаляем временный файл
        os.remove(temp_filepath)

        # Возвращаем относительный путь
        relative_path = os.path.relpath(final_filepath, start='.')
        logger.info(f"Successfully saved secure cover image: {relative_path}")
        return relative_path

    except Exception as e:
        logger.error(f"Error processing cover image: {str(e)}")
        # Очищаем временные файлы
        for path in [temp_filepath, final_filepath]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up {path}: {cleanup_error}")
        return None


def get_upload_folder() -> str:
    """Возвращает путь к папке загрузок"""
    return UPLOAD_BASE_FOLDER


def get_cover_upload_folder() -> str:
    """Возвращает путь к папке обложек"""
    return COVER_UPLOAD_FOLDER


def validate_text_file_upload(
    file: FileStorage,
    allowed_extensions: set,
    max_size_mb: int = 10
) -> Tuple[bool, Optional[str]]:
    """
    Безопасная валидация текстовых файлов (JSON, CSV, TXT)

    Args:
        file: Объект загруженного файла
        allowed_extensions: Набор разрешенных расширений (например, {'json', 'csv', 'txt'})
        max_size_mb: Максимальный размер файла в МБ

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not file or not hasattr(file, 'filename'):
        return False, "Файл не предоставлен"

    if not file.filename:
        return False, "Имя файла отсутствует"

    # Безопасное имя файла (защита от path traversal)
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(file.filename)

    if not safe_name:
        return False, "Недопустимое имя файла"

    # Проверка расширения
    if '.' not in safe_name:
        return False, "Файл должен иметь расширение"

    extension = safe_name.rsplit('.', 1)[1].lower()
    if extension not in allowed_extensions:
        return False, f"Расширение .{extension} не разрешено. Разрешены: {', '.join(allowed_extensions)}"

    # Проверка размера файла
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Вернуть указатель в начало

    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        return False, f"Размер файла ({file_size / 1024 / 1024:.2f} МБ) превышает лимит {max_size_mb} МБ"

    # Проверка на подозрительные паттерны в имени файла
    suspicious_patterns = [
        '..',  # Path traversal
        '/',
        '\\',
        '\x00',  # Null byte
        '<',
        '>',
        ':',
        '"',
        '|',
        '?',
        '*'
    ]

    for pattern in suspicious_patterns:
        if pattern in file.filename:
            return False, f"Недопустимый символ в имени файла: {pattern}"

    # Дополнительная проверка: попытка прочитать начало файла как текст
    try:
        file.seek(0)
        sample = file.read(1024)  # Читаем первый КБ
        file.seek(0)

        # Проверяем, что это текст (UTF-8)
        sample.decode('utf-8')
    except UnicodeDecodeError:
        return False, "Файл не является текстовым (UTF-8)"
    except Exception as e:
        logger.error(f"Error validating text file: {e}")
        return False, "Ошибка при чтении файла"

    return True, None