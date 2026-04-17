"""
Tests for cache invalidation after user progress updates.
Verifies that per-user caches are cleared after progress mutations.
"""
import uuid
import pytest
import app.curriculum.cache as _cache_module

from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
from app.curriculum.cache import CurriculumCache, SimpleCache


def _cache():
    """Return the currently active cache instance (may be replaced by init_cache)."""
    return _cache_module.cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_level(db_session, order=1):
    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name=f'Level {order}', order=order)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level, number=1):
    module = Module(
        level_id=level.id,
        number=number,
        title=f'Module {number}',
        description='',
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module, number=1):
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'Lesson {number}',
        type='vocabulary',
        order=number,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ---------------------------------------------------------------------------
# SimpleCache unit tests
# ---------------------------------------------------------------------------

class TestSimpleCacheDeleteByPattern:
    """Unit tests for SimpleCache.delete_by_pattern()."""

    def test_delete_by_pattern_removes_matching_keys(self):
        c = SimpleCache()
        c.set('user_42:progress', 'data1')
        c.set('user_42:lessons', 'data2')
        c.set('user_99:progress', 'other_data')

        deleted = c.delete_by_pattern('user_42')

        assert deleted == 2
        assert c.get('user_42:progress') is None
        assert c.get('user_42:lessons') is None
        assert c.get('user_99:progress') == 'other_data'

    def test_delete_by_pattern_no_match_returns_zero(self):
        c = SimpleCache()
        c.set('user_1:data', 'val')

        deleted = c.delete_by_pattern('user_999')

        assert deleted == 0
        assert c.get('user_1:data') == 'val'

    def test_delete_by_pattern_empty_cache(self):
        c = SimpleCache()
        deleted = c.delete_by_pattern('user_1')
        assert deleted == 0


# ---------------------------------------------------------------------------
# CurriculumCache invalidation tests
# ---------------------------------------------------------------------------

class TestCurriculumCacheInvalidation:
    """Tests for CurriculumCache.invalidate_user_cache() targeting specific user keys."""

    def test_invalidate_removes_user_specific_keys(self):
        # Manually seed cache with user-specific keys (simulating cached data)
        user_id = 42
        c = _cache()
        c.set(f'curriculum:get_user_progress:user_{user_id}:abc', {'progress': 'data'})
        c.set(f'curriculum:get_user_active_lessons:user_{user_id}:def', ['lesson1'])
        c.set(f'user_xp_{user_id}', {'user_xp': 100})
        # Another user's data should NOT be removed
        c.set(f'curriculum:get_user_progress:user_99:xyz', {'progress': 'other'})

        CurriculumCache.invalidate_user_cache(user_id)

        assert c.get(f'curriculum:get_user_progress:user_{user_id}:abc') is None
        assert c.get(f'curriculum:get_user_active_lessons:user_{user_id}:def') is None
        assert c.get(f'user_xp_{user_id}') is None
        # Other user's cache must be untouched
        assert c.get('curriculum:get_user_progress:user_99:xyz') == {'progress': 'other'}

    def test_invalidate_noop_when_no_user_keys(self):
        """invalidate_user_cache does not raise when user has no cached data."""
        CurriculumCache.invalidate_user_cache(user_id=99999)


# ---------------------------------------------------------------------------
# Progress mutation → cache invalidation integration tests
# ---------------------------------------------------------------------------

class TestProgressMutationInvalidatesCache:
    """Tests that ProgressService mutations invalidate user cache."""

    def test_create_or_update_progress_invalidates_cache(self, db_session, test_user):
        """Updating progress clears per-user curriculum caches."""
        from app.curriculum.services.progress_service import ProgressService

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module)

        # Seed the live cache with stale data
        user_id = test_user.id
        c = _cache()
        stale_key = f'curriculum:get_user_progress:user_{user_id}:stale'
        c.set(stale_key, {'stale': True})
        xp_key = f'user_xp_{user_id}'
        c.set(xp_key, {'user_xp': 0})

        ProgressService.create_or_update_progress(
            user_id=user_id,
            lesson_id=lesson.id,
            status='completed',
        )

        # After mutation, stale keys should be gone
        assert c.get(stale_key) is None
        assert c.get(xp_key) is None

    def test_update_progress_with_grading_invalidates_cache(self, db_session, test_user):
        """update_progress_with_grading also invalidates user cache."""
        from app.curriculum.services.progress_service import ProgressService

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module)

        user_id = test_user.id
        c = _cache()
        stale_key = f'curriculum:get_user_active_lessons:user_{user_id}:stale'
        c.set(stale_key, ['old_lesson'])

        ProgressService.update_progress_with_grading(
            user_id=user_id,
            lesson=lesson,
            result={'score': 80},
        )

        assert c.get(stale_key) is None

    @pytest.mark.smoke
    def test_cache_returns_fresh_data_after_progress_update(self, db_session, test_user):
        """After progress update, cached stats reflect new state, not stale cache."""
        from app.curriculum.services.progress_service import ProgressService

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module)

        user_id = test_user.id
        c = _cache()

        # Seed a stale XP cache entry
        xp_key = f'user_xp_{user_id}'
        c.set(xp_key, {'user_xp': 9999, 'user_level': 99})

        ProgressService.create_or_update_progress(
            user_id=user_id,
            lesson_id=lesson.id,
            status='in_progress',
        )

        # Stale XP cache should be cleared; next read will fetch fresh from DB
        assert c.get(xp_key) is None
