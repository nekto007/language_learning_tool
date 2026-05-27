"""Tests for curriculum access control — Task 7 audit.

Covers:
- check_module_access API vs HTML distinction in require_lesson_access
- Direct URL lesson access without creating duplicate LessonProgress records
- Anonymous requests get 302/401 (not 500) on /curriculum/* routes
- Prerequisites check with empty/None list returns True (no crash)
"""
from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.curriculum.models import (
    CEFRLevel, LessonProgress, Lessons, Module,
)
from app.curriculum.security import (
    _is_api_request,
    check_module_access,
    check_lesson_access,
)
from app.utils.db import db as real_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_level(db_session, order=10) -> CEFRLevel:
    level = CEFRLevel(
        code=uuid.uuid4().hex[:2].upper(),
        name='TestLevel',
        order=order,
    )
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level, number=1, prerequisites=None) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'Module {number}',
        raw_content={},
        min_score_required=70,
        prerequisites=prerequisites,
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module, number=1) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'Lesson {number}',
        type='vocabulary',
        order=number,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _complete_lesson(db_session, user, lesson, score=90.0) -> LessonProgress:
    progress = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=score,
    )
    db_session.add(progress)
    db_session.commit()
    return progress


def _mock_user(user_id, is_admin=False):
    m = MagicMock()
    m.is_authenticated = True
    m.is_admin = is_admin
    m.id = user_id
    return m


# ---------------------------------------------------------------------------
# _is_api_request detection
# ---------------------------------------------------------------------------

class TestIsApiRequest:
    """Verify _is_api_request correctly classifies requests."""

    def test_api_path_detected_as_api(self, app):
        with app.test_request_context('/api/daily-status'):
            assert _is_api_request() is True

    def test_html_path_without_accept_is_not_api(self, app):
        with app.test_request_context('/curriculum/lesson/1'):
            assert _is_api_request() is False

    def test_accept_json_header_detected_as_api(self, app):
        with app.test_request_context(
            '/curriculum/lesson/1',
            headers={'Accept': 'application/json'},
        ):
            assert _is_api_request() is True

    def test_accept_html_is_not_api(self, app):
        with app.test_request_context(
            '/curriculum/lesson/1',
            headers={'Accept': 'text/html'},
        ):
            assert _is_api_request() is False


# ---------------------------------------------------------------------------
# require_lesson_access: API vs HTML response distinction
# ---------------------------------------------------------------------------

class TestRequireLessonAccessResponse:
    """require_lesson_access must return JSON 403 for API requests and
    redirect+flash for HTML requests when lesson is locked."""

    def _create_locked_lesson(self, db_session):
        """Create a lesson that is NOT accessible (module 2, no progress in module 1)."""
        level = _make_level(db_session, order=20)
        mod1 = _make_module(db_session, level, number=1)
        mod2 = _make_module(db_session, level, number=2)
        _make_lesson(db_session, mod1, number=1)
        locked_lesson = _make_lesson(db_session, mod2, number=1)
        return locked_lesson

    def test_locked_lesson_html_request_returns_redirect(
        self, app, db_session, test_user, client
    ):
        locked = self._create_locked_lesson(db_session)

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        resp = client.get(f'/learn/{locked.id}/')
        assert resp.status_code == 302
        location = resp.headers.get('Location', '')
        assert '/learn/' in location or '/login' in location

    def test_locked_lesson_api_request_returns_json_403(
        self, app, db_session, test_user, client
    ):
        locked = self._create_locked_lesson(db_session)

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        resp = client.get(
            f'/learn/{locked.id}/',
            headers={'Accept': 'application/json'},
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data is not None
        assert 'error' in data


# ---------------------------------------------------------------------------
# Anonymous user access — must not produce 500
# ---------------------------------------------------------------------------

class TestAnonymousAccess:
    """Anonymous requests on /learn/* and /curriculum/* must redirect (302)
    or return 401 for AJAX — never 500."""

    def test_anonymous_html_request_redirects_to_login(self, app, client):
        resp = client.get('/learn/')
        # Flask-Login redirects to login (302), no 500.
        assert resp.status_code in (302, 301)
        location = resp.headers.get('Location', '')
        assert 'login' in location or 'next' in location

    def test_anonymous_ajax_request_returns_401(self, app, client):
        resp = client.get(
            '/learn/',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data is not None
        assert data.get('error') or data.get('success') is False

    def test_anonymous_learn_level_redirects(self, app, client, test_level):
        resp = client.get(f'/learn/{test_level.code.lower()}/')
        assert resp.status_code in (302, 301)

    def test_anonymous_lesson_url_does_not_500(self, app, client, db_session):
        level = _make_level(db_session, order=30)
        mod = _make_module(db_session, level, number=1)
        lesson = _make_lesson(db_session, mod, number=1)
        resp = client.get(f'/learn/{lesson.id}/')
        assert resp.status_code != 500
        assert resp.status_code in (302, 301, 401, 403)


# ---------------------------------------------------------------------------
# check_module_access with empty / None prerequisites
# ---------------------------------------------------------------------------

class TestEmptyPrerequisites:
    """check_module_access must return True for modules with empty or None
    prerequisites — no crash expected."""

    def test_none_prerequisites_returns_true(self, app, db_session, test_user):
        level = _make_level(db_session, order=40)
        mod = _make_module(db_session, level, number=1, prerequisites=None)
        with app.app_context():
            with patch('app.curriculum.security.current_user', _mock_user(test_user.id)):
                assert check_module_access(mod.id) is True

    def test_empty_list_prerequisites_returns_true(self, app, db_session, test_user):
        level = _make_level(db_session, order=41)
        mod = _make_module(db_session, level, number=1, prerequisites=[])
        with app.app_context():
            with patch('app.curriculum.security.current_user', _mock_user(test_user.id)):
                assert check_module_access(mod.id) is True

    def test_prerequisites_with_empty_dicts_returns_true(self, app, db_session, test_user):
        level = _make_level(db_session, order=42)
        mod = _make_module(db_session, level, number=1, prerequisites=[{}])
        with app.app_context():
            with patch('app.curriculum.security.current_user', _mock_user(test_user.id)):
                assert check_module_access(mod.id) is True

    def test_check_prerequisites_method_empty_list(self, app, db_session):
        level = _make_level(db_session, order=43)
        mod = _make_module(db_session, level, number=1, prerequisites=[])
        with app.app_context():
            accessible, reasons = mod.check_prerequisites(user_id=1)
        assert accessible is True
        assert reasons == []

    def test_check_prerequisites_method_none(self, app, db_session):
        level = _make_level(db_session, order=44)
        mod = _make_module(db_session, level, number=1, prerequisites=None)
        with app.app_context():
            accessible, reasons = mod.check_prerequisites(user_id=1)
        assert accessible is True
        assert reasons == []

    def test_check_prerequisites_dicts_without_type_returns_true(self, app, db_session):
        level = _make_level(db_session, order=45)
        mod = _make_module(db_session, level, number=1, prerequisites=[{'foo': 'bar'}])
        with app.app_context():
            accessible, reasons = mod.check_prerequisites(user_id=1)
        assert accessible is True


# ---------------------------------------------------------------------------
# LessonProgress — no duplicates when record already exists
# ---------------------------------------------------------------------------

class TestLessonProgressNoDuplicate:
    """lesson_detail and lesson_by_id must not create a second LessonProgress
    record when one already exists."""

    def test_second_visit_does_not_create_duplicate_progress(
        self, app, db_session, test_user, client
    ):
        level = _make_level(db_session, order=50)
        mod = _make_module(db_session, level, number=1)
        lesson = _make_lesson(db_session, mod, number=1)

        # Pre-create a progress record
        existing = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='in_progress',
        )
        db_session.add(existing)
        db_session.commit()

        # Login the test user
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.curriculum.security.current_user', _mock_user(test_user.id)):
            with patch('app.curriculum.security.check_lesson_access', return_value=True):
                resp = client.get(f'/learn/{lesson.id}/')
        # Should redirect (to lesson type render or elsewhere) — not 500
        assert resp.status_code != 500

        # Still only one progress row in DB
        count = LessonProgress.query.filter_by(
            user_id=test_user.id,
            lesson_id=lesson.id,
        ).count()
        assert count == 1

    def test_progress_count_stays_one_on_repeated_access(
        self, app, db_session, test_user
    ):
        """Verify check_lesson_access and service layer logic do not duplicate rows."""
        level = _make_level(db_session, order=51)
        mod = _make_module(db_session, level, number=1)
        lesson = _make_lesson(db_session, mod, number=1)

        prog = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='completed',
        )
        real_db.session.add(prog)
        real_db.session.commit()

        existing_count = LessonProgress.query.filter_by(
            user_id=test_user.id,
            lesson_id=lesson.id,
        ).count()
        assert existing_count == 1

        # Simulate that check_lesson_access doesn't trigger creation
        with app.app_context():
            with patch('app.curriculum.security.current_user', _mock_user(test_user.id)):
                result = check_lesson_access(lesson.id)
        # Completed lesson is always accessible
        assert result is True

        final_count = LessonProgress.query.filter_by(
            user_id=test_user.id,
            lesson_id=lesson.id,
        ).count()
        assert final_count == 1


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_check_module_access_unauthenticated_returns_false(app, db_session, test_module):
    """Unauthenticated user is denied module access without crashing."""
    with app.app_context():
        anon = MagicMock()
        anon.is_authenticated = False
        with patch('app.curriculum.security.current_user', anon):
            result = check_module_access(test_module.id)
    assert result is False


@pytest.mark.smoke
def test_check_lesson_access_unauthenticated_returns_false(app, db_session, test_lesson_vocabulary):
    """Unauthenticated user is denied lesson access without crashing."""
    with app.app_context():
        anon = MagicMock()
        anon.is_authenticated = False
        with patch('app.curriculum.security.current_user', anon):
            result = check_lesson_access(test_lesson_vocabulary.id)
    assert result is False


@pytest.mark.smoke
def test_anonymous_main_curriculum_page_no_500(app, client):
    """Anonymous user hitting /learn/ must not get a 500 error."""
    resp = client.get('/learn/')
    assert resp.status_code != 500
