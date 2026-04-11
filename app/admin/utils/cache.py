# app/admin/utils/cache.py

"""
Кэширование для административной панели LLT English

Bounded in-memory cache with LRU eviction and periodic expired-entry cleanup.
"""
import logging
from collections import OrderedDict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_CACHE_SIZE = 100
_cache_timeout = 300  # 5 минут (по умолчанию)

# OrderedDict for LRU ordering: most-recently-used entries move to the end
_cache: OrderedDict = OrderedDict()


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
        if (datetime.now(timezone.utc) - cached_time).total_seconds() < timeout:
            # Move to end (most recently used)
            _cache.move_to_end(key)
            return cached_data
        else:
            # Удаляем устаревший кэш
            del _cache[key]
    return None


def set_cache(key, value):
    """
    Сохраняет значение в кэш с LRU eviction when max_size exceeded.

    Args:
        key: Ключ кэша
        value: Значение для сохранения
    """
    if key in _cache:
        # Update existing: move to end
        _cache[key] = (value, datetime.now(timezone.utc))
        _cache.move_to_end(key)
    else:
        # Evict oldest entries if at capacity
        while len(_cache) >= MAX_CACHE_SIZE:
            evicted_key, _ = _cache.popitem(last=False)
            logger.debug("Cache evicted key: %s (max_size=%d)", evicted_key, MAX_CACHE_SIZE)
        _cache[key] = (value, datetime.now(timezone.utc))


def cleanup_expired(timeout=_cache_timeout):
    """
    Удаляет все просроченные записи из кэша.

    Вызывается периодически или вручную для предотвращения накопления
    устаревших данных в памяти.

    Args:
        timeout: Время жизни записей в секундах

    Returns:
        Количество удалённых записей
    """
    now = datetime.now(timezone.utc)
    expired_keys = [
        key for key, (_, cached_time) in _cache.items()
        if (now - cached_time).total_seconds() >= timeout
    ]
    for key in expired_keys:
        del _cache[key]
    if expired_keys:
        logger.debug("Cleaned up %d expired cache entries", len(expired_keys))
    return len(expired_keys)


def clear_admin_cache():
    """Очищает административный кэш"""
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
