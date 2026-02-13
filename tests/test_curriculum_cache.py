"""
Tests for curriculum cache
Тесты кеширования учебного плана
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import app.curriculum.cache as _cache_module
from app.curriculum.cache import SimpleCache, cache_key, cached, CurriculumCache


def _get_cache():
    """Get the current global cache instance (survives init_cache() replacement)."""
    return _cache_module.cache


@pytest.fixture(autouse=True)
def clear_global_cache():
    """Clear global cache before each test"""
    _get_cache().clear()
    yield
    _get_cache().clear()


class TestSimpleCache:
    """Тесты класса SimpleCache"""

    def test_init_creates_empty_cache(self):
        """Тест инициализации создает пустой кеш"""
        cache = SimpleCache()
        assert cache.size() == 0

    def test_set_and_get(self):
        """Тест установки и получения значения"""
        cache = SimpleCache()
        cache.set('key1', 'value1')

        assert cache.get('key1') == 'value1'

    def test_get_nonexistent_key(self):
        """Тест получения несуществующего ключа"""
        cache = SimpleCache()
        assert cache.get('nonexistent') is None

    def test_set_with_timeout(self):
        """Тест установки значения с таймаутом"""
        cache = SimpleCache()
        cache.set('key1', 'value1', timeout=1)

        # Сразу доступно
        assert cache.get('key1') == 'value1'

        # Simulate timeout expiry by shifting expiry time to the past
        cache._expiry['key1'] = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Должно вернуть None после истечения
        assert cache.get('key1') is None

    def test_set_without_timeout(self):
        """Тест установки значения без таймаута (timeout=0)"""
        cache = SimpleCache()
        cache.set('key1', 'value1', timeout=0)

        # Должно быть доступно
        assert cache.get('key1') == 'value1'

    def test_delete(self):
        """Тест удаления ключа"""
        cache = SimpleCache()
        cache.set('key1', 'value1')
        assert cache.get('key1') == 'value1'

        cache.delete('key1')
        assert cache.get('key1') is None

    def test_delete_nonexistent_key(self):
        """Тест удаления несуществующего ключа"""
        cache = SimpleCache()
        # Не должно вызывать ошибку
        cache.delete('nonexistent')

    def test_clear(self):
        """Тест очистки всего кеша"""
        cache = SimpleCache()
        cache.set('key1', 'value1')
        cache.set('key2', 'value2')
        assert cache.size() == 2

        cache.clear()
        assert cache.size() == 0
        assert cache.get('key1') is None
        assert cache.get('key2') is None

    def test_size(self):
        """Тест подсчета размера кеша"""
        cache = SimpleCache()
        assert cache.size() == 0

        cache.set('key1', 'value1')
        assert cache.size() == 1

        cache.set('key2', 'value2')
        assert cache.size() == 2

        cache.delete('key1')
        assert cache.size() == 1

    def test_expired_key_is_deleted(self):
        """Тест что истекший ключ удаляется из кеша"""
        cache = SimpleCache()
        cache.set('key1', 'value1', timeout=1)

        # Simulate timeout expiry
        cache._expiry['key1'] = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Попытка получить истекший ключ
        result = cache.get('key1')
        assert result is None

        # Ключ должен быть удален из кеша
        assert 'key1' not in cache._cache
        assert 'key1' not in cache._expiry

    def test_overwrite_existing_key(self):
        """Тест перезаписи существующего ключа"""
        cache = SimpleCache()
        cache.set('key1', 'value1')
        cache.set('key1', 'value2')

        assert cache.get('key1') == 'value2'

    def test_cache_different_types(self):
        """Тест кеширования разных типов данных"""
        cache = SimpleCache()

        cache.set('string', 'test')
        cache.set('int', 42)
        cache.set('list', [1, 2, 3])
        cache.set('dict', {'key': 'value'})
        cache.set('none', None)

        assert cache.get('string') == 'test'
        assert cache.get('int') == 42
        assert cache.get('list') == [1, 2, 3]
        assert cache.get('dict') == {'key': 'value'}
        # None - особый случай, означает отсутствие ключа
        assert cache.get('none') is None


class TestCacheKey:
    """Тесты функции cache_key"""

    def test_cache_key_no_args(self):
        """Тест генерации ключа без аргументов"""
        key = cache_key()
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hash length

    def test_cache_key_with_args(self):
        """Тест генерации ключа с позиционными аргументами"""
        key1 = cache_key(1, 2, 3)
        key2 = cache_key(1, 2, 3)

        # Одинаковые аргументы должны давать одинаковый ключ
        assert key1 == key2

    def test_cache_key_different_args(self):
        """Тест что разные аргументы дают разные ключи"""
        key1 = cache_key(1, 2, 3)
        key2 = cache_key(4, 5, 6)

        assert key1 != key2

    def test_cache_key_with_kwargs(self):
        """Тест генерации ключа с именованными аргументами"""
        key1 = cache_key(a=1, b=2)
        key2 = cache_key(a=1, b=2)

        assert key1 == key2

    def test_cache_key_kwargs_order_independent(self):
        """Тест что порядок kwargs не влияет на ключ"""
        key1 = cache_key(a=1, b=2)
        key2 = cache_key(b=2, a=1)

        # Должны быть одинаковыми из-за sort_keys=True
        assert key1 == key2

    def test_cache_key_mixed_args_kwargs(self):
        """Тест генерации ключа со смешанными аргументами"""
        key1 = cache_key(1, 2, c=3, d=4)
        key2 = cache_key(1, 2, c=3, d=4)

        assert key1 == key2

    def test_cache_key_with_complex_types(self):
        """Тест генерации ключа со сложными типами"""
        key1 = cache_key([1, 2, 3], {'a': 'b'})
        key2 = cache_key([1, 2, 3], {'a': 'b'})

        assert key1 == key2


class TestCachedDecorator:
    """Тесты декоратора cached"""

    def test_cached_function_is_cached(self):
        """Тест что функция кешируется"""
        call_count = {'count': 0}

        @cached(timeout=60, key_prefix='test_func_cached')
        def expensive_function(x):
            call_count['count'] += 1
            return x * 2

        # Первый вызов - вычисляется
        result1 = expensive_function(5)
        assert result1 == 10
        assert call_count['count'] == 1

        # Второй вызов - из кеша
        result2 = expensive_function(5)
        assert result2 == 10
        assert call_count['count'] == 1  # Не увеличилось!

    def test_cached_different_args(self):
        """Тест что разные аргументы кешируются отдельно"""
        call_count = {'count': 0}

        @cached(timeout=60, key_prefix='test_diff_args')
        def func(x):
            call_count['count'] += 1
            return x * 2

        result1 = func(5)
        result2 = func(10)

        # Два разных вызова
        assert result1 == 10
        assert result2 == 20
        assert call_count['count'] == 2

    def test_cached_with_key_prefix(self):
        """Тест работы с префиксом ключа"""
        @cached(timeout=60, key_prefix='test')
        def func(x):
            return x * 2

        result = func(5)
        assert result == 10

    def test_cached_timeout_expires(self, app):
        """Тест что кеш истекает после таймаута"""
        with app.app_context():
            call_count = {'count': 0}

            @cached(timeout=1, key_prefix='test_timeout')
            def func(x):
                call_count['count'] += 1
                return x * 2

            result1 = func(5)
            assert call_count['count'] == 1

            # Simulate cache expiry by clearing it
            _get_cache().clear()

            result2 = func(5)
            assert call_count['count'] == 2  # Функция вызвана снова

    def test_cached_cache_clear_method(self):
        """Тест метода cache_clear"""
        call_count = {'count': 0}

        @cached(timeout=60, key_prefix='test_cache_clear')
        def func(x):
            call_count['count'] += 1
            return x * 2

        result1 = func(5)
        assert call_count['count'] == 1

        # Очищаем кеш
        func.cache_clear()

        result2 = func(5)
        assert call_count['count'] == 2  # Функция вызвана снова

    def test_cached_cache_info_method(self):
        """Тест метода cache_info"""
        @cached(timeout=60)
        def func(x):
            return x * 2

        info = func.cache_info()
        assert 'size' in info
        assert isinstance(info['size'], int)

    def test_cached_with_user_specific(self):
        """Тест user-specific кеширования"""
        call_count = {'count': 0}

        @cached(timeout=60, user_specific=True, key_prefix='test_user_spec')
        def func(x):
            call_count['count'] += 1
            return x * 2

        # Без аутентификации
        with patch('app.curriculum.cache.current_user') as mock_user:
            mock_user.is_authenticated = False
            result = func(5)
            assert result == 10
            assert call_count['count'] == 1

    def test_cached_with_authenticated_user(self):
        """Тест кеширования с аутентифицированным пользователем"""
        call_count = {'count': 0}

        @cached(timeout=60, user_specific=True, key_prefix='test_auth_user')
        def func(x):
            call_count['count'] += 1
            return x * 2

        # С аутентифицированным пользователем
        with patch('app.curriculum.cache.current_user') as mock_user:
            mock_user.is_authenticated = True
            mock_user.id = 123

            result1 = func(5)
            assert result1 == 10
            assert call_count['count'] == 1

            # Второй вызов с тем же пользователем - из кеша
            result2 = func(5)
            assert result2 == 10
            assert call_count['count'] == 1

    def test_cached_preserves_function_name(self):
        """Тест что декоратор сохраняет имя функции"""
        @cached(timeout=60)
        def my_function(x):
            return x * 2

        assert my_function.__name__ == 'my_function'


class TestCurriculumCacheInvalidateUserCache:
    """Тесты метода invalidate_user_cache"""

    def test_invalidate_user_cache_clears_cache(self):
        """Тест что invalidate_user_cache очищает кеш"""
        from app.curriculum.cache import cache

        # Добавляем данные в кеш
        cache.set('test_key', 'test_value')
        assert cache.get('test_key') == 'test_value'

        # Инвалидируем кеш
        CurriculumCache.invalidate_user_cache(123)

        # Кеш должен быть очищен
        assert cache.get('test_key') is None


class TestCurriculumCacheMethodsStructure:
    """Тесты структуры методов CurriculumCache"""

    def test_get_all_levels_method_exists(self):
        """Тест что метод get_all_levels существует"""
        assert hasattr(CurriculumCache, 'get_all_levels')
        assert callable(CurriculumCache.get_all_levels)

    def test_get_level_modules_method_exists(self):
        """Тест что метод get_level_modules существует"""
        assert hasattr(CurriculumCache, 'get_level_modules')
        assert callable(CurriculumCache.get_level_modules)

    def test_get_module_lessons_method_exists(self):
        """Тест что метод get_module_lessons существует"""
        assert hasattr(CurriculumCache, 'get_module_lessons')
        assert callable(CurriculumCache.get_module_lessons)

    def test_get_user_progress_method_exists(self):
        """Тест что метод get_user_progress существует"""
        assert hasattr(CurriculumCache, 'get_user_progress')
        assert callable(CurriculumCache.get_user_progress)

    def test_get_user_active_lessons_method_exists(self):
        """Тест что метод get_user_active_lessons существует"""
        assert hasattr(CurriculumCache, 'get_user_active_lessons')
        assert callable(CurriculumCache.get_user_active_lessons)

    def test_get_user_srs_stats_method_exists(self):
        """Тест что метод get_user_srs_stats существует"""
        assert hasattr(CurriculumCache, 'get_user_srs_stats')
        assert callable(CurriculumCache.get_user_srs_stats)

    def test_invalidate_user_cache_method_exists(self):
        """Тест что метод invalidate_user_cache существует"""
        assert hasattr(CurriculumCache, 'invalidate_user_cache')
        assert callable(CurriculumCache.invalidate_user_cache)
