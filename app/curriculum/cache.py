# app/curriculum/cache.py

import hashlib
import json
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional

from flask_login import current_user

logger = logging.getLogger(__name__)


class SimpleCache:
    """Simple in-memory cache implementation"""

    def __init__(self):
        self._cache = {}
        self._expiry = {}

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if key in self._cache:
            # Check if expired
            if key in self._expiry and datetime.utcnow() > self._expiry[key]:
                self.delete(key)
                return None
            return self._cache[key]
        return None

    def set(self, key: str, value: Any, timeout: int = 300) -> None:
        """Set value in cache with timeout in seconds"""
        self._cache[key] = value
        if timeout:
            self._expiry[key] = datetime.utcnow() + timedelta(seconds=timeout)

    def delete(self, key: str) -> None:
        """Delete key from cache"""
        self._cache.pop(key, None)
        self._expiry.pop(key, None)

    def clear(self) -> None:
        """Clear all cache"""
        self._cache.clear()
        self._expiry.clear()

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
        # This is a simple implementation
        # In a real Redis cache, you'd use pattern matching
        cache.clear()  # For now, clear all cache
        logger.info(f"Invalidated cache for user {user_id}")

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


class CacheStats:
    """Cache statistics tracking"""

    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0

    def record_hit(self):
        self.hits += 1

    def record_miss(self):
        self.misses += 1

    def record_set(self):
        self.sets += 1

    def record_delete(self):
        self.deletes += 1

    def get_hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0

    def get_stats(self) -> Dict[str, Any]:
        return {
            'hits': self.hits,
            'misses': self.misses,
            'sets': self.sets,
            'deletes': self.deletes,
            'hit_rate': self.get_hit_rate(),
            'cache_size': cache.size()
        }


# Global cache stats
cache_stats = CacheStats()


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


def cache_middleware(f):
    """Middleware to handle cache invalidation on data changes"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        result = f(*args, **kwargs)

        # Check if this was a data modification operation
        if hasattr(result, 'status_code') and result.status_code in [200, 201]:
            # Invalidate relevant cache entries
            if 'lesson' in f.__name__:
                cache.clear()  # Simple approach - clear all
            elif 'progress' in f.__name__ and current_user.is_authenticated:
                CurriculumCache.invalidate_user_cache(current_user.id)

        return result

    return decorated_function


class RedisCache:
    """Redis cache implementation (for production use)"""

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.default_timeout = 300

    def get(self, key: str) -> Optional[Any]:
        """Get value from Redis cache"""
        if not self.redis:
            return None

        try:
            value = self.redis.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get error: {str(e)}")
            return None

    def set(self, key: str, value: Any, timeout: int = None) -> bool:
        """Set value in Redis cache"""
        if not self.redis:
            return False

        try:
            timeout = timeout or self.default_timeout
            serialized = json.dumps(value, default=str)
            return self.redis.setex(key, timeout, serialized)
        except Exception as e:
            logger.error(f"Redis set error: {str(e)}")
            return False

    def delete(self, key: str) -> bool:
        """Delete key from Redis cache"""
        if not self.redis:
            return False

        try:
            return self.redis.delete(key)
        except Exception as e:
            logger.error(f"Redis delete error: {str(e)}")
            return False

    def clear_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern"""
        if not self.redis:
            return 0

        try:
            keys = self.redis.keys(pattern)
            if keys:
                return self.redis.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Redis clear pattern error: {str(e)}")
            return 0


def init_cache(app, redis_client=None):
    """Initialize cache system"""
    global cache

    if redis_client:
        # Use Redis for production
        cache = RedisCache(redis_client)
        logger.info("Initialized Redis cache")
    else:
        # Use simple cache for development
        cache = SimpleCache()
        logger.info("Initialized simple cache")

    # Warm cache on startup
    with app.app_context():
        warm_cache()
