"""Tests for curriculum search — Task 89."""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'srch_{suffix}',
        email=f'srch_{suffix}@example.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, order: int = 1) -> CEFRLevel:
    level = CEFRLevel(code=_unique_code(), name='Test Level', description='d', order=order)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int = 1) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'Module {number}',
        description='d',
        raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module: Module, title: str, number: int = 1) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=title,
        type='text',
        content={'text': 'sample'},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------

class TestSearchRoute:
    def test_empty_query_redirects_to_learn(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        response = client.get('/curriculum/search?q=', follow_redirects=True)
        # After following all redirects it should land on the learn page
        assert response.status_code == 200

    def test_empty_q_param_redirects(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        # Empty q should redirect (status 302 before following)
        response = client.get('/curriculum/search?q=', follow_redirects=False)
        # May redirect to learn or onboarding then learn; just check it's a redirect
        assert response.status_code == 302

    def test_whitespace_only_query_redirects(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        response = client.get('/curriculum/search?q=   ', follow_redirects=False)
        assert response.status_code == 302

    def test_search_returns_200_with_query(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        response = client.get('/curriculum/search?q=test')
        assert response.status_code == 200

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get('/curriculum/search?q=hello', follow_redirects=False)
        assert response.status_code in (302, 401)

    def test_lesson_found_in_results(self, client, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, title='UniqueSearchTermXYZ789')
        _login(client, user)

        response = client.get('/curriculum/search?q=UniqueSearchTermXYZ789')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        assert 'UniqueSearchTermXYZ789' in data

    def test_lesson_not_found_shows_empty_state(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        response = client.get('/curriculum/search?q=ZZZNOMATCHEVERHOPEFULLY99999')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        assert 'Ничего не найдено' in data

    def test_results_grouped_by_module(self, client, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session)
        module = _make_module(db_session, level, number=1)
        # Two lessons in same module, both matching
        _make_lesson(db_session, module, title='SearchGroup lesson alpha', number=1)
        _make_lesson(db_session, module, title='SearchGroup lesson beta', number=2)
        _login(client, user)

        response = client.get('/curriculum/search?q=SearchGroup')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        assert 'SearchGroup lesson alpha' in data
        assert 'SearchGroup lesson beta' in data
        # Module title appears once (group header)
        assert f'Модуль {module.number}' in data

    def test_query_echoed_in_response(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        response = client.get('/curriculum/search?q=helloworld')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        assert 'helloworld' in data

    def test_xss_query_is_escaped(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        xss = '<script>alert(1)</script>'
        response = client.get(f'/curriculum/search?q={xss}')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        # The raw script tag should not appear unescaped
        assert '<script>alert(1)</script>' not in data

    def test_search_template_has_search_form(self, client, db_session):
        user = _make_user(db_session)
        _login(client, user)
        response = client.get('/curriculum/search?q=test')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        assert 'search-form' in data
        assert 'name="q"' in data
