"""
Comprehensive tests for Admin Cache Utils (app/admin/utils/cache.py)

Tests in-memory caching for admin statistics:
- get_cache
- set_cache
- clear_admin_cache
- clear_cache_by_prefix

Coverage target: 100% for app/admin/utils/cache.py
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import time


class TestGetCache:
    """Test get_cache function"""

    def test_returns_none_for_missing_key(self):
        """Test returns None when key doesn't exist"""
        from app.admin.utils.cache import get_cache, clear_admin_cache

        clear_admin_cache()  # Ensure clean state

        result = get_cache('nonexistent_key')

        assert result is None

    def test_returns_cached_value(self):
        """Test returns value from cache"""
        from app.admin.utils.cache import get_cache, set_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('test_key', {'data': 'value'})
        result = get_cache('test_key')

        assert result == {'data': 'value'}

    def test_respects_timeout(self):
        """Test cache expires after timeout"""
        from app.admin.utils.cache import get_cache, set_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('test_key', 'value')

        # Mock time to simulate expiry
        with patch('app.admin.utils.cache.datetime') as mock_datetime:
            # Current time + 400 seconds (more than default 300s timeout)
            future_time = datetime.now(timezone.utc) + timedelta(seconds=400)
            mock_datetime.now.return_value = future_time

            result = get_cache('test_key')

        assert result is None

    def test_custom_timeout(self):
        """Test uses custom timeout parameter"""
        from app.admin.utils.cache import get_cache, set_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('test_key', 'value')

        # With very short timeout (1 second), it should expire
        with patch('app.admin.utils.cache.datetime') as mock_datetime:
            future_time = datetime.now(timezone.utc) + timedelta(seconds=2)
            mock_datetime.now.return_value = future_time

            result = get_cache('test_key', timeout=1)

        assert result is None

    def test_removes_expired_cache(self):
        """Test removes entry from cache after expiry"""
        from app.admin.utils.cache import get_cache, set_cache, clear_admin_cache, _cache

        clear_admin_cache()

        set_cache('test_key', 'value')
        assert 'test_key' in _cache

        # Expire cache
        with patch('app.admin.utils.cache.datetime') as mock_datetime:
            future_time = datetime.now(timezone.utc) + timedelta(seconds=400)
            mock_datetime.now.return_value = future_time

            get_cache('test_key')

        # Key should be deleted
        from app.admin.utils.cache import _cache as current_cache
        assert 'test_key' not in current_cache

    def test_returns_value_before_timeout(self):
        """Test returns value when not expired"""
        from app.admin.utils.cache import get_cache, set_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('test_key', 'value')

        # Check immediately (definitely not expired)
        result = get_cache('test_key')

        assert result == 'value'


class TestSetCache:
    """Test set_cache function"""

    def test_stores_value_in_cache(self):
        """Test stores value in cache"""
        from app.admin.utils.cache import set_cache, get_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('my_key', {'some': 'data'})
        result = get_cache('my_key')

        assert result == {'some': 'data'}

    def test_stores_timestamp(self):
        """Test stores timestamp with value"""
        from app.admin.utils.cache import set_cache, clear_admin_cache, _cache

        clear_admin_cache()

        set_cache('test_key', 'value')

        # Access cache directly to check timestamp
        from app.admin.utils.cache import _cache as current_cache
        value, timestamp = current_cache['test_key']

        assert value == 'value'
        assert isinstance(timestamp, datetime)
        assert timestamp.tzinfo is not None  # Has timezone

    def test_overwrites_existing_key(self):
        """Test overwrites existing cache entry"""
        from app.admin.utils.cache import set_cache, get_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('key', 'old_value')
        set_cache('key', 'new_value')

        result = get_cache('key')

        assert result == 'new_value'

    def test_stores_different_types(self):
        """Test can store different data types"""
        from app.admin.utils.cache import set_cache, get_cache, clear_admin_cache

        clear_admin_cache()

        # Store dict
        set_cache('dict_key', {'a': 1})
        assert get_cache('dict_key') == {'a': 1}

        # Store list
        set_cache('list_key', [1, 2, 3])
        assert get_cache('list_key') == [1, 2, 3]

        # Store string
        set_cache('str_key', 'hello')
        assert get_cache('str_key') == 'hello'

        # Store int
        set_cache('int_key', 42)
        assert get_cache('int_key') == 42


class TestClearAdminCache:
    """Test clear_admin_cache function"""

    def test_clears_all_cache(self):
        """Test clears entire cache"""
        from app.admin.utils.cache import set_cache, clear_admin_cache, get_cache

        set_cache('key1', 'value1')
        set_cache('key2', 'value2')
        set_cache('key3', 'value3')

        clear_admin_cache()

        assert get_cache('key1') is None
        assert get_cache('key2') is None
        assert get_cache('key3') is None

    def test_empty_cache_after_clear(self):
        """Test cache dict is empty after clear"""
        from app.admin.utils.cache import set_cache, clear_admin_cache, _cache

        set_cache('key', 'value')
        clear_admin_cache()

        from app.admin.utils.cache import _cache as current_cache
        assert len(current_cache) == 0

    def test_logs_clear_action(self):
        """Test logs when cache is cleared"""
        from app.admin.utils.cache import clear_admin_cache

        with patch('app.admin.utils.cache.logger') as mock_logger:
            clear_admin_cache()

            mock_logger.info.assert_called_with("Admin cache cleared")


class TestClearCacheByPrefix:
    """Test clear_cache_by_prefix function"""

    def test_clears_matching_prefix(self):
        """Test clears only keys with matching prefix"""
        from app.admin.utils.cache import set_cache, clear_cache_by_prefix, get_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('user_stats_123', 'data1')
        set_cache('user_stats_456', 'data2')
        set_cache('global_stats', 'data3')

        clear_cache_by_prefix('user_stats_')

        assert get_cache('user_stats_123') is None
        assert get_cache('user_stats_456') is None
        assert get_cache('global_stats') == 'data3'  # Not cleared

    def test_clears_nothing_for_no_match(self):
        """Test doesn't clear anything if no keys match"""
        from app.admin.utils.cache import set_cache, clear_cache_by_prefix, get_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('key1', 'value1')
        set_cache('key2', 'value2')

        clear_cache_by_prefix('nonexistent_')

        assert get_cache('key1') == 'value1'
        assert get_cache('key2') == 'value2'

    def test_logs_clear_count(self):
        """Test logs number of entries cleared"""
        from app.admin.utils.cache import set_cache, clear_cache_by_prefix, clear_admin_cache

        clear_admin_cache()

        set_cache('user_1', 'data')
        set_cache('user_2', 'data')
        set_cache('admin_1', 'data')

        with patch('app.admin.utils.cache.logger') as mock_logger:
            clear_cache_by_prefix('user_')

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert 'Cleared 2 cache entries' in call_args
            assert "prefix 'user_'" in call_args

    def test_handles_empty_cache(self):
        """Test handles empty cache gracefully"""
        from app.admin.utils.cache import clear_cache_by_prefix, clear_admin_cache

        clear_admin_cache()

        # Should not raise error
        clear_cache_by_prefix('any_prefix_')

    def test_partial_prefix_match(self):
        """Test only clears exact prefix matches"""
        from app.admin.utils.cache import set_cache, clear_cache_by_prefix, get_cache, clear_admin_cache

        clear_admin_cache()

        set_cache('stats_user', 'data1')
        set_cache('stats_admin', 'data2')
        set_cache('user_stats', 'data3')

        clear_cache_by_prefix('stats_')

        assert get_cache('stats_user') is None
        assert get_cache('stats_admin') is None
        assert get_cache('user_stats') == 'data3'  # Different prefix


class TestCacheIntegration:
    """Integration tests for cache functionality"""

    def test_full_cache_lifecycle(self):
        """Test complete cache lifecycle"""
        from app.admin.utils.cache import set_cache, get_cache, clear_admin_cache

        clear_admin_cache()

        # Set value
        set_cache('key', 'value')
        assert get_cache('key') == 'value'

        # Overwrite
        set_cache('key', 'new_value')
        assert get_cache('key') == 'new_value'

        # Clear
        clear_admin_cache()
        assert get_cache('key') is None

    def test_multiple_keys_independent(self):
        """Test multiple cache keys are independent"""
        from app.admin.utils.cache import set_cache, get_cache, clear_cache_by_prefix, clear_admin_cache

        clear_admin_cache()

        set_cache('a_1', 'value1')
        set_cache('a_2', 'value2')
        set_cache('b_1', 'value3')

        # Clear only 'a_' prefix
        clear_cache_by_prefix('a_')

        assert get_cache('a_1') is None
        assert get_cache('a_2') is None
        assert get_cache('b_1') == 'value3'
