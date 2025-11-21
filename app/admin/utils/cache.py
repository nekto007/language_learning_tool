# app/admin/utils/cache.py

"""
Кэширование для административной панели LLT English
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Простое in-memory кэширование для статистики
_cache = {}
_cache_timeout = 300  # 5 минут (по умолчанию)


def get_cache(key, timeout=_cache_timeout):
    """
    Получает значение из кэша

    Args:
        key: Ключ кэша
        timeout: Время жизни кэша в секундах

    Returns:
        Закэшированные данные или None, если кэш устарел или не существует
    """
    if key in _cache:
        cached_data, cached_time = _cache[key]
        if (datetime.now(timezone.utc) - cached_time).seconds < timeout:
            return cached_data
        else:
            # Удаляем устаревший кэш
            del _cache[key]
    return None


def set_cache(key, value):
    """
    Сохраняет значение в кэш

    Args:
        key: Ключ кэша
        value: Значение для сохранения
    """
    _cache[key] = (value, datetime.now(timezone.utc))


def clear_admin_cache():
    """Очищает административный кэш"""
    global _cache
    _cache.clear()
    logger.info("Admin cache cleared")


def clear_cache_by_prefix(prefix):
    """
    Очищает кэш по префиксу ключа

    Args:
        prefix: Префикс ключей для очистки
    """
    keys_to_delete = [key for key in _cache.keys() if key.startswith(prefix)]
    for key in keys_to_delete:
        del _cache[key]
    logger.info(f"Cleared {len(keys_to_delete)} cache entries with prefix '{prefix}'")
