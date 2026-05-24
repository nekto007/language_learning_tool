"""Tests for app/admin/utils/cache.py and related system routes."""
import time
import pytest
from freezegun import freeze_time
from datetime import datetime, timezone

import app.admin.utils.cache as cache_module
from app.admin.utils.cache import (
    get_cache,
    set_cache,
    clear_admin_cache,
    clear_cache_by_prefix,
    cleanup_expired,
    get_cache_stats,
    MAX_CACHE_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure cache is empty before and after each test."""
    clear_admin_cache()
    yield
    clear_admin_cache()


# ---------------------------------------------------------------------------
# Unit tests — pure cache behaviour
# ---------------------------------------------------------------------------

class TestSetAndGet:
    def test_set_and_get_returns_value(self):
        set_cache('k1', 'hello')
        assert get_cache('k1') == 'hello'

    def test_get_missing_key_returns_none(self):
        assert get_cache('no_such_key') is None

    def test_set_overwrites_existing(self):
        set_cache('k', 'v1')
        set_cache('k', 'v2')
        assert get_cache('k') == 'v2'

    def test_cache_stores_complex_objects(self):
        payload = {'a': [1, 2, 3], 'b': True}
        set_cache('complex', payload)
        assert get_cache('complex') == payload

    @pytest.mark.smoke
    def test_expired_entry_returns_none(self):
        with freeze_time('2025-01-01 10:00:00'):
            set_cache('ttl_key', 'value')
        # 10 seconds later with a 5-second timeout → expired
        with freeze_time('2025-01-01 10:00:10'):
            assert get_cache('ttl_key', timeout=5) is None

    def test_not_expired_entry_returns_value(self):
        with freeze_time('2025-01-01 10:00:00'):
            set_cache('live_key', 'still here')
        with freeze_time('2025-01-01 10:00:04'):
            assert get_cache('live_key', timeout=10) == 'still here'

    def test_lru_ordering_on_get(self):
        """Getting a key should move it to the end (most recently used)."""
        set_cache('a', 1)
        set_cache('b', 2)
        # Access 'a' to make it MRU
        get_cache('a', timeout=300)
        keys = list(cache_module._cache.keys())
        assert keys[-1] == 'a'


class TestLRUEviction:
    def test_oldest_entry_evicted_when_full(self):
        for i in range(MAX_CACHE_SIZE):
            set_cache(f'key_{i}', i)
        # Cache is full; next write should evict key_0 (oldest)
        set_cache('new_key', 'new')
        assert get_cache('key_0') is None
        assert get_cache('new_key') == 'new'

    def test_size_never_exceeds_max(self):
        for i in range(MAX_CACHE_SIZE + 20):
            set_cache(f'k{i}', i)
        assert len(cache_module._cache) <= MAX_CACHE_SIZE


class TestClearAll:
    def test_clear_admin_cache_empties_cache(self):
        set_cache('x', 1)
        set_cache('y', 2)
        clear_admin_cache()
        assert get_cache('x') is None
        assert get_cache('y') is None
        assert len(cache_module._cache) == 0


class TestClearByPrefix:
    def test_clears_matching_keys_only(self):
        set_cache('seo_audit_v1', 'a')
        set_cache('seo_sites', 'b')
        set_cache('dashboard_dau', 'c')
        removed = clear_cache_by_prefix('seo_')
        assert removed == 2
        assert get_cache('seo_audit_v1') is None
        assert get_cache('seo_sites') is None
        assert get_cache('dashboard_dau') == 'c'

    def test_empty_prefix_matches_all(self):
        set_cache('abc', 1)
        set_cache('xyz', 2)
        removed = clear_cache_by_prefix('')
        assert removed == 2

    def test_no_match_returns_zero(self):
        set_cache('foo', 1)
        removed = clear_cache_by_prefix('bar_')
        assert removed == 0
        assert get_cache('foo') == 1


class TestCleanupExpired:
    def test_removes_expired_entries(self):
        with freeze_time('2025-01-01 10:00:00'):
            set_cache('old1', 'v1')
            set_cache('old2', 'v2')
        with freeze_time('2025-01-01 10:00:05'):
            set_cache('fresh', 'v3')
            removed = cleanup_expired(timeout=4)
        assert removed == 2
        assert len(cache_module._cache) == 1

    def test_no_expired_entries(self):
        set_cache('alive', 'v')
        removed = cleanup_expired(timeout=300)
        assert removed == 0


class TestGetCacheStats:
    def test_returns_size_and_max_size(self):
        set_cache('s1', 1)
        set_cache('s2', 2)
        stats = get_cache_stats()
        assert stats['size'] == 2
        assert stats['max_size'] == MAX_CACHE_SIZE

    def test_empty_cache_stats(self):
        stats = get_cache_stats()
        assert stats['size'] == 0
        assert stats['entries'] == []

    def test_entries_have_key_and_age(self):
        with freeze_time('2025-01-01 10:00:00'):
            set_cache('entry_key', 'v')
        with freeze_time('2025-01-01 10:00:07'):
            stats = get_cache_stats()
        assert len(stats['entries']) == 1
        entry = stats['entries'][0]
        assert entry['key'] == 'entry_key'
        assert entry['age_seconds'] == 7

    def test_note_mentions_per_worker(self):
        stats = get_cache_stats()
        assert 'per-worker' in stats['note'].lower() or 'Per-worker' in stats['note']


# ---------------------------------------------------------------------------
# Integration tests — HTTP endpoints
# ---------------------------------------------------------------------------

class TestCacheStatsEndpoint:
    @pytest.mark.smoke
    def test_cache_stats_returns_json(self, app, admin_client):
        set_cache('test_entry', 'val')
        resp = admin_client.get('/admin/system/cache-stats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'size' in data
        assert 'max_size' in data
        assert 'entries' in data
        assert data['size'] >= 1

    def test_cache_stats_requires_admin(self, app, client):
        resp = client.get('/admin/system/cache-stats')
        assert resp.status_code in (302, 401, 403)


class TestClearCacheEndpoint:
    def test_clear_cache_requires_admin(self, app, client):
        resp = client.post('/admin/system/clear-cache', data={'confirm': 'CLEAR_CACHE'})
        assert resp.status_code in (302, 401, 403)

    def test_clear_cache_creates_audit_log(self, app, admin_client, db_session):
        from app.admin.audit import AdminAuditLog
        set_cache('before_clear', 'x')
        resp = admin_client.post(
            '/admin/system/clear-cache',
            data={'confirm': 'CLEAR_CACHE'},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)
        entry = db_session.query(AdminAuditLog).filter_by(action='system.clear_cache').first()
        assert entry is not None

    def test_clear_cache_empties_cache(self, app, admin_client):
        set_cache('wipe_me', 'data')
        admin_client.post(
            '/admin/system/clear-cache',
            data={'confirm': 'CLEAR_CACHE'},
        )
        assert get_cache('wipe_me') is None


class TestClearCachePrefixEndpoint:
    def test_clear_prefix_removes_matching_entries(self, app, admin_client):
        set_cache('seo_v1', 'a')
        set_cache('seo_v2', 'b')
        set_cache('dashboard_x', 'c')
        admin_client.post(
            '/admin/system/clear-cache-prefix',
            data={'prefix': 'seo_'},
        )
        assert get_cache('seo_v1') is None
        assert get_cache('seo_v2') is None
        assert get_cache('dashboard_x') == 'c'

    def test_clear_prefix_creates_audit_log(self, app, admin_client, db_session):
        from app.admin.audit import AdminAuditLog
        set_cache('pfx_key', 'val')
        admin_client.post(
            '/admin/system/clear-cache-prefix',
            data={'prefix': 'pfx_'},
        )
        entry = db_session.query(AdminAuditLog).filter_by(
            action='system.clear_cache_prefix',
        ).first()
        assert entry is not None
        assert entry.target_type == 'pfx_'

    def test_clear_prefix_empty_prefix_rejected(self, app, admin_client):
        resp = admin_client.post(
            '/admin/system/clear-cache-prefix',
            data={'prefix': ''},
            follow_redirects=False,
        )
        # Should redirect back with a warning flash
        assert resp.status_code in (200, 302)

    def test_clear_prefix_requires_admin(self, app, client):
        resp = client.post('/admin/system/clear-cache-prefix', data={'prefix': 'x'})
        assert resp.status_code in (302, 401, 403)
