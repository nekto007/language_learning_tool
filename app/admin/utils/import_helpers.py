# app/admin/utils/import_helpers.py

"""
Утилиты для управления временными файлами импорта
"""
import json
import os
import uuid
from datetime import datetime

# Директория для временных файлов импорта
IMPORT_TEMP_DIR = 'app/temp/import_translations'
os.makedirs(IMPORT_TEMP_DIR, exist_ok=True)


def save_import_data(data):
    """
    Сохраняет данные импорта во временный файл

    Args:
        data: Данные для сохранения (должны быть сериализуемы в JSON)

    Returns:
        str: Уникальный ID импорта
    """
    import_id = str(uuid.uuid4())
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Удаляем старые файлы (старше 1 часа)
    cleanup_old_imports()

    return import_id


def load_import_data(import_id):
    """
    Загружает данные импорта из временного файла

    Args:
        import_id: ID импорта

    Returns:
        dict: Загруженные данные или None, если файл не найден
    """
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")

    if not os.path.exists(file_path):
        return None

    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def delete_import_data(import_id):
    """
    Удаляет временный файл импорта

    Args:
        import_id: ID импорта
    """
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")

    if os.path.exists(file_path):
        os.remove(file_path)


def cleanup_old_imports():
    """Удаляет старые файлы импорта (старше 1 часа)"""
    current_time = datetime.now().timestamp()

    for filename in os.listdir(IMPORT_TEMP_DIR):
        if filename.endswith('.json'):
            file_path = os.path.join(IMPORT_TEMP_DIR, filename)
            file_time = os.path.getmtime(file_path)

            # Удаляем файлы старше 1 часа
            if current_time - file_time > 3600:
                os.remove(file_path)
