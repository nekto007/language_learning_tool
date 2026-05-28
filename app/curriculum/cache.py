# app/curriculum/cache.py

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

from flask_login import current_user

logger = logging.getLogger(__name__)


_CACHE_MAX_SIZE = 2000  # hard upper bound to prevent unbounded growth


class SimpleCache:
    """Simple in-memory cache implementation"""

    def __init__(self):
        self._cache = {}
        self._expiry = {}

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if key in self._cache:
            # Check if expired
            if key in self._expiry and datetime.now(timezone.utc) > self._expiry[key]:
                self.delete(key)
                return None
            return self._cache[key]
        return None

    def set(self, key: str, value: Any, timeout: int = 300) -> None:
        """Set value in cache with timeout in seconds"""
        self._cache[key] = value
        if timeout:
            self._expiry[key] = datetime.now(timezone.utc) + timedelta(seconds=timeout)
        # Prune expired entries when the cache grows too large.
        if len(self._cache) > _CACHE_MAX_SIZE:
            self.prune()

    def prune(self) -> int:
        """Remove all expired entries. Returns count of removed keys."""
        now = datetime.now(timezone.utc)
        expired = [k for k, exp in list(self._expiry.items()) if now > exp]
        for key in expired:
            self._cache.pop(key, None)
            self._expiry.pop(key, None)
        return len(expired)

    def delete(self, key: str) -> None:
        """Delete key from cache"""
        self._cache.pop(key, None)
        self._expiry.pop(key, None)

    def clear(self) -> None:
        """Clear all cache"""
        self._cache.clear()
        self._expiry.clear()

    def delete_by_pattern(self, pattern: str) -> int:
        """Delete all keys containing pattern. Returns count of deleted keys."""
        keys_to_delete = [k for k in list(self._cache.keys()) if pattern in k]
        for key in keys_to_delete:
            self.delete(key)
        return len(keys_to_delete)

    def size(self) -> int:
        """Get cache size"""
        return len(self._cache)


# Global cache instance
cache = SimpleCache()


def cache_key(*args, **kwargs) -> str:
    """Generate cache key from arguments"""
    # Create a unique key from all arguments
    key_data = {
        'args': args,
        'kwargs': kwargs
    }
    key_string = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.md5(key_string.encode()).hexdigest()


def cached(timeout: int = 300, key_prefix: str = '', user_specific: bool = False):
    """
    Decorator to cache function results
    
    Args:
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache key
        user_specific: Whether to include user ID in cache key
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Build cache key
            cache_key_parts = [key_prefix, f.__name__]

            # Add user ID if user-specific caching
            if user_specific and current_user.is_authenticated:
                cache_key_parts.append(f"user_{current_user.id}")

            # Add function arguments
            cache_key_parts.append(cache_key(*args, **kwargs))

            key = ':'.join(filter(None, cache_key_parts))

            # Try to get from cache
            result = cache.get(key)
            if result is not None:
                logger.debug(f"Cache hit for {f.__name__}")
                return result

            # Execute function and cache result
            logger.debug(f"Cache miss for {f.__name__}")
            result = f(*args, **kwargs)
            cache.set(key, result, timeout)

            return result

        # Add cache management methods
        decorated_function.cache_clear = lambda: cache.clear()
        decorated_function.cache_info = lambda: {'size': cache.size()}

        return decorated_function

    return decorator


class CurriculumCache:
    """Specialized cache for curriculum data"""

    @staticmethod
    @cached(timeout=600, key_prefix='curriculum', user_specific=False)
    def get_all_levels() -> List[Dict]:
        """Cache all CEFR levels"""
        from app.curriculum.models import CEFRLevel

        levels = CEFRLevel.query.order_by(CEFRLevel.order).all()
        return [{
            'id': level.id,
            'code': level.code,
            'name': level.name,
            'description': level.description,
            'order': level.order
        } for level in levels]

    @staticmethod
    @cached(timeout=300, key_prefix='curriculum', user_specific=False)
    def get_level_modules(level_id: int) -> List[Dict]:
        """Cache modules for a level"""
        from app.curriculum.models import Module

        modules = Module.query.filter_by(
            level_id=level_id
        ).order_by(Module.number).all()

        return [{
            'id': module.id,
            'number': module.number,
            'title': module.title,
            'description': module.description,
            'level_id': module.level_id
        } for module in modules]

    @staticmethod
    @cached(timeout=180, key_prefix='curriculum', user_specific=False)
    def get_module_lessons(module_id: int) -> List[Dict]:
        """Cache lessons for a module"""
        from app.curriculum.models import Lessons

        lessons = Lessons.query.filter_by(
            module_id=module_id
        ).order_by(Lessons.order, Lessons.number).all()

        return [{
            'id': lesson.id,
            'number': lesson.number,
            'title': lesson.title,
            'type': lesson.type,
            'description': lesson.description,
            'order': lesson.order,
            'module_id': lesson.module_id
        } for lesson in lessons]

    @staticmethod
    @cached(timeout=60, key_prefix='curriculum', user_specific=True)
    def get_user_progress(user_id: int) -> Dict:
        """Cache user progress data"""
        from app.curriculum.services.progress_service import ProgressService
        return ProgressService.get_user_level_progress(user_id)

    @staticmethod
    @cached(timeout=120, key_prefix='curriculum', user_specific=True)
    def get_user_active_lessons(user_id: int, limit: int = 5) -> List[Dict]:
        """Cache user active lessons"""
        from app.curriculum.services.progress_service import ProgressService
        active_lessons = ProgressService.get_active_lessons(user_id, limit)

        # Convert to serializable format
        return [{
            'lesson_id': item['lesson'].id,
            'lesson_title': item['lesson'].title,
            'lesson_type': item['lesson'].type,
            'module_id': item['module'].id,
            'module_title': item['module'].title,
            'level_code': item['level'].code,
            'last_activity': item['last_activity'].isoformat() if item['last_activity'] else None,
            'score': item['score']
        } for item in active_lessons]

    @staticmethod
    @cached(timeout=300, key_prefix='curriculum', user_specific=True)
    def get_user_srs_stats(user_id: int) -> Dict:
        """Cache user SRS statistics"""
        from app.curriculum.services.srs_service import SRSService
        return SRSService.get_user_srs_statistics(user_id)

    @staticmethod
    def invalidate_user_cache(user_id: int):
        """Invalidate all cache entries for a user"""
        deleted = cache.delete_by_pattern(f"user_{user_id}")
        # Also delete the XP cache stored by template_utils
        cache.delete(f"user_xp_{user_id}")
        logger.info(f"Invalidated {deleted + 1} cache entries for user {user_id}")

    @staticmethod
    def invalidate_lesson_cache(lesson_id: int):
        """Invalidate cache entries related to a lesson"""
        cache.clear()  # For now, clear all cache
        logger.info(f"Invalidated cache for lesson {lesson_id}")

    @staticmethod
    def invalidate_module_cache(module_id: int):
        """Invalidate cache entries related to a module"""
        cache.clear()  # For now, clear all cache
        logger.info(f"Invalidated cache for module {module_id}")


def warm_cache():
    """Warm up cache with commonly accessed data"""
    try:
        logger.info("Warming up curriculum cache...")

        # Cache all levels
        CurriculumCache.get_all_levels()

        # Cache modules for each level
        from app.curriculum.models import CEFRLevel
        levels = CEFRLevel.query.all()

        for level in levels:
            CurriculumCache.get_level_modules(level.id)

            # Cache lessons for first few modules
            from app.curriculum.models import Module
            modules = Module.query.filter_by(level_id=level.id).limit(3).all()

            for module in modules:
                CurriculumCache.get_module_lessons(module.id)

        logger.info("Cache warming completed")

    except Exception as e:
        logger.error(f"Error warming cache: {str(e)}")


def init_cache(app, redis_client=None):
    """Initialize cache system"""
    global cache

    cache = SimpleCache()
    logger.info("Initialized simple cache")

    # Warm cache on startup
    # Skip in testing mode - tests will handle their own setup
    if not app.config.get('TESTING', False):
        with app.app_context():
            warm_cache()
