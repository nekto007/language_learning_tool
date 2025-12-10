# app/books/safe_processors.py
"""
Безопасная обертка для функций обработки книг
Предотвращает проблемы с blueprint registration
"""

import logging
import sys
import traceback
from typing import Dict

logger = logging.getLogger(__name__)


def safe_process_book_words(book_id: int, content: str) -> Dict:
    """
    Безопасная обертка для process_book_words
    """
    logger.info(f"[SAFE_PROCESSOR] Starting safe_process_book_words for book_id={book_id}")

    try:
        # Проверяем текущие загруженные модули перед импортом
        modules_before = set(sys.modules.keys())
        logger.debug(f"[SAFE_PROCESSOR] Modules before import: {len(modules_before)}")

        # Импортируем модуль
        logger.info("[SAFE_PROCESSOR] Importing app.books.processors...")
        from app.books import processors

        # Проверяем какие новые модули были загружены
        modules_after = set(sys.modules.keys())
        new_modules = modules_after - modules_before
        logger.debug(f"[SAFE_PROCESSOR] New modules loaded: {len(new_modules)}")

        if new_modules:
            # Проверяем, есть ли среди них admin или blueprint модули
            admin_modules = [m for m in new_modules if 'admin' in m or 'blueprint' in m]
            if admin_modules:
                logger.warning(f"[SAFE_PROCESSOR] Admin/Blueprint modules detected: {admin_modules}")

        # Вызываем функцию
        logger.info("[SAFE_PROCESSOR] Calling process_book_words...")
        result = processors.process_book_words(book_id, content)

        logger.info(f"[SAFE_PROCESSOR] process_book_words completed successfully: {result}")
        return result

    except Exception as e:
        logger.error(f"[SAFE_PROCESSOR] Error in safe_process_book_words: {str(e)}")
        logger.error(f"[SAFE_PROCESSOR] Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }


def safe_process_book_chapters_words(book_id: int) -> Dict:
    """
    Безопасная обертка для process_book_chapters_words
    """
    print(f"[DEBUG SAFE] safe_process_book_chapters_words ВХОД: book_id={book_id}", flush=True)
    logger.info(f"[SAFE_PROCESSOR] Starting safe_process_book_chapters_words for book_id={book_id}")

    try:
        # Проверяем текущие загруженные модули перед импортом
        modules_before = set(sys.modules.keys())
        logger.debug(f"[SAFE_PROCESSOR] Modules before import: {len(modules_before)}")

        # Импортируем модуль
        logger.info("[SAFE_PROCESSOR] Importing app.books.processors...")
        from app.books import processors

        # Проверяем какие новые модули были загружены
        modules_after = set(sys.modules.keys())
        new_modules = modules_after - modules_before
        logger.debug(f"[SAFE_PROCESSOR] New modules loaded: {len(new_modules)}")

        if new_modules:
            # Проверяем, есть ли среди них admin или blueprint модули
            admin_modules = [m for m in new_modules if 'admin' in m or 'blueprint' in m]
            if admin_modules:
                logger.warning(f"[SAFE_PROCESSOR] Admin/Blueprint modules detected: {admin_modules}")

        # Вызываем функцию
        logger.info("[SAFE_PROCESSOR] Calling process_book_chapters_words...")
        result = processors.process_book_chapters_words(book_id)

        logger.info(f"[SAFE_PROCESSOR] process_book_chapters_words completed successfully: {result}")
        return result

    except Exception as e:
        logger.error(f"[SAFE_PROCESSOR] Error in safe_process_book_chapters_words: {str(e)}")
        logger.error(f"[SAFE_PROCESSOR] Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }


def diagnose_import_issue():
    """
    Диагностирует проблему с импортом модулей
    """
    logger.info("[SAFE_PROCESSOR] Running import diagnostics...")

    diagnosis = {
        "admin_modules": [],
        "blueprint_modules": [],
        "curriculum_modules": [],
        "problematic_imports": []
    }

    # Проверяем все загруженные модули
    for module_name, module in sys.modules.items():
        if module is None:
            continue

        # Проверяем admin модули
        if 'admin' in module_name:
            diagnosis["admin_modules"].append({
                "name": module_name,
                "has_blueprint": hasattr(module, 'admin') or hasattr(module, 'bp') or hasattr(module, 'blueprint')
            })

        # Проверяем blueprint модули
        if 'blueprint' in module_name.lower():
            diagnosis["blueprint_modules"].append(module_name)

        # Проверяем curriculum модули
        if 'curriculum' in module_name:
            diagnosis["curriculum_modules"].append({
                "name": module_name,
                "has_admin": hasattr(module, 'admin_bp') or hasattr(module, 'admin')
            })

    # Пробуем импортировать и смотрим что происходит
    try:
        logger.info("[SAFE_PROCESSOR] Testing import of app.books.processors...")
        import app.books.processors
        logger.info("[SAFE_PROCESSOR] Import successful")
    except Exception as e:
        logger.error(f"[SAFE_PROCESSOR] Import failed: {str(e)}")
        diagnosis["problematic_imports"].append({
            "module": "app.books.processors",
            "error": str(e),
            "traceback": traceback.format_exc()
        })

    return diagnosis
