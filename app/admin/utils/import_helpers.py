# app/admin/utils/import_helpers.py

"""
Утилиты для управления временными файлами импорта
"""
import json
import logging
import os
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# Директория для временных файлов импорта
IMPORT_TEMP_DIR = 'app/temp/import_translations'
os.makedirs(IMPORT_TEMP_DIR, exist_ok=True)


def _validate_import_id(import_id):
    """Return a canonical UUID hex string or None.

    Form-supplied identifiers must be UUIDs so they cannot be used to
    traverse to arbitrary paths via ``os.path.join``.
    """
    if not import_id or not isinstance(import_id, str):
        return None
    try:
        return str(uuid.UUID(import_id))
    except (ValueError, AttributeError):
        return None


def save_import_data(data: dict, *, prefix: str = '', private: bool = False) -> str:
    """
    Сохраняет данные импорта во временный файл

    Args:
        data: Данные для сохранения (должны быть сериализуемы в JSON)

    Returns:
        str: Уникальный ID импорта
    """
    import_id = str(uuid.uuid4())
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{prefix}{import_id}.json")

    def open_private(path: str, flags: int) -> int:
        return os.open(path, flags | os.O_EXCL, 0o600)

    with open(file_path, 'w', encoding='utf-8', opener=open_private if private else None) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Удаляем старые файлы (старше 1 часа)
    cleanup_old_imports()

    return import_id


def load_import_data(import_id: str, *, prefix: str = '') -> dict | None:
    """
    Загружает данные импорта из временного файла

    Args:
        import_id: ID импорта (должен быть валидным UUID)

    Returns:
        dict: Загруженные данные или None, если файл не найден / id невалиден
    """
    safe_id = _validate_import_id(import_id)
    if safe_id is None:
        logger.warning("Rejected invalid import_id for load")
        return None
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{prefix}{safe_id}.json")
    try:
        with open(file_path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def delete_import_data(import_id: str, *, prefix: str = '') -> bool:
    """
    Удаляет временный файл импорта

    Args:
        import_id: ID импорта (должен быть валидным UUID)
    """
    safe_id = _validate_import_id(import_id)
    if safe_id is None:
        logger.warning("Rejected invalid import_id for delete")
        return False
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{prefix}{safe_id}.json")
    try:
        os.remove(file_path)
    except FileNotFoundError:
        return False
    return True


def cleanup_old_imports():
    """Удаляет старые файлы импорта (старше 1 часа)"""
    current_time = datetime.now().timestamp()

    for filename in os.listdir(IMPORT_TEMP_DIR):
        if filename.endswith('.json'):
            file_path = os.path.join(IMPORT_TEMP_DIR, filename)
            try:
                if current_time - os.path.getmtime(file_path) > 3600:
                    os.remove(file_path)
            except FileNotFoundError:
                continue
