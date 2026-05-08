"""API hardening tests for /api/books/reading-session/end (Task 7)."""
from __future__ import annotations

import uuid

import pytest

from app.books.reading_session import UserReadingSession, start_session
from app.auth.models import User
from app.utils.db import db


@pytest.fixture
def other_user(db_session):
    username = f'other_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


class TestReadingSessionEndApi:
    def test_foreign_session_returns_403_json(
        self, authenticated_client, db_session, other_user, test_chapter,
    ):
        session = start_session(other_user.id, test_chapter.id, db)
        db_session.commit()

        response = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': session.id},
        )

        assert response.status_code == 403
        assert response.is_json
        body = response.get_json()
        assert body['success'] is False
        assert body['error'] == 'forbidden'

    def test_negative_offset_returns_400(
        self, authenticated_client, db_session, test_chapter,
    ):
        user_id = authenticated_client.application.test_user.id
        session = start_session(user_id, test_chapter.id, db)
        db_session.commit()

        response = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': session.id, 'current_offset_pct': -0.1},
        )

        assert response.status_code == 400
        body = response.get_json()
        assert body['error'] == 'invalid_offset_delta'

        # Session must remain open after a rejected request.
        db_session.expire_all()
        row = db_session.get(UserReadingSession, session.id)
        assert row.ended_at is None

    def test_oversized_offset_returns_400(
        self, authenticated_client, db_session, test_chapter,
    ):
        user_id = authenticated_client.application.test_user.id
        session = start_session(user_id, test_chapter.id, db)
        db_session.commit()

        response = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': session.id, 'current_offset_pct': 1.5},
        )

        assert response.status_code == 400
        body = response.get_json()
        assert body['error'] == 'invalid_offset_delta'

    def test_non_numeric_offset_returns_400(
        self, authenticated_client, db_session, test_chapter,
    ):
        user_id = authenticated_client.application.test_user.id
        session = start_session(user_id, test_chapter.id, db)
        db_session.commit()

        response = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': session.id, 'current_offset_pct': 'not-a-number'},
        )

        assert response.status_code == 400
        body = response.get_json()
        assert body['error'] == 'invalid_offset_delta'

    def test_valid_offset_succeeds(
        self, authenticated_client, db_session, test_chapter,
    ):
        user_id = authenticated_client.application.test_user.id
        session = start_session(user_id, test_chapter.id, db)
        db_session.commit()

        response = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': session.id, 'current_offset_pct': 0.2},
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body['success'] is True

    def test_missing_session_id_returns_400_json(self, authenticated_client):
        response = authenticated_client.post(
            '/api/books/reading-session/end',
            json={},
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body['error'] == 'missing_session_id'

    def test_unknown_session_returns_404_json(self, authenticated_client):
        response = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': 999_999_999},
        )
        assert response.status_code == 404
        body = response.get_json()
        assert body['error'] == 'not_found'
