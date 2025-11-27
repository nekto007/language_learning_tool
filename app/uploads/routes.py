"""
Безопасный endpoint для отдачи загруженных файлов
"""
import logging
import mimetypes
import os
from flask import Blueprint, abort, send_file, current_app
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

uploads = Blueprint('uploads', __name__)

# Базовая директория проекта (на уровень выше app/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Разрешенные MIME-типы для отдачи
ALLOWED_SERVE_MIMETYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
}


@uploads.route('/covers/<filename>')
def serve_cover(filename):
    """
    Безопасно отдает обложки книг с правильным Content-Type

    Args:
        filename: Имя файла для отдачи

    Returns:
        Response: Файл с правильными заголовками или 404
    """
    try:
        # Используем secure_filename для предотвращения path traversal
        safe_filename = secure_filename(filename)

        if not safe_filename or safe_filename != filename:
            logger.warning(f"Attempt to access unsafe filename: {filename}")
            abort(404)

        # Строим полный путь к файлу
        file_path = os.path.join(BASE_DIR, 'uploads', 'covers', safe_filename)

        # Проверяем существование файла
        if not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}")
            abort(404)

        # Проверяем, что это файл, а не директория
        if not os.path.isfile(file_path):
            logger.warning(f"Path is not a file: {file_path}")
            abort(404)

        # Определяем MIME-тип на основе расширения
        mimetype, _ = mimetypes.guess_type(safe_filename)

        # Проверяем, что MIME-тип разрешен
        if mimetype not in ALLOWED_SERVE_MIMETYPES:
            logger.warning(f"Disallowed MIME type {mimetype} for file {safe_filename}")
            # Принудительно устанавливаем image/jpeg для безопасности
            mimetype = 'image/jpeg'

        # Отдаем файл с правильными заголовками
        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=False,
            download_name=safe_filename,
            # Добавляем заголовки безопасности
            conditional=True,
            etag=True,
            last_modified=None,
            max_age=86400  # Кэш на 24 часа
        )

    except Exception as e:
        logger.error(f"Error serving file {filename}: {str(e)}")
        abort(404)