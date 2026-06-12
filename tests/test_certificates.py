"""Tests for level certificates (сертификаты уровней + share-image)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.achievements.certificates import (
    get_completed_level,
    get_completed_levels,
    render_certificate_png,
)
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code


@pytest.fixture
def level_with_lessons(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Elementary', description='d', order=2)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M1', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lessons = []
    for i in range(1, 4):
        lesson = Lessons(
            module_id=module.id, number=i, title=f'L{i}', type='vocabulary',
            content={'words': []},
        )
        db_session.add(lesson)
        lessons.append(lesson)
    db_session.commit()
    return level, module, lessons


def _complete(db_session, user_id, lessons):
    now = datetime.now(timezone.utc)
    for lesson in lessons:
        db_session.add(LessonProgress(
            user_id=user_id, lesson_id=lesson.id, status='completed',
            score=90, completed_at=now,
        ))
    db_session.commit()


@pytest.mark.smoke
class TestCertificateService:
    def test_no_certificates_without_progress(self, db_session, test_user, level_with_lessons):
        assert get_completed_levels(test_user.id) == []

    def test_partial_progress_not_certified(self, db_session, test_user, level_with_lessons):
        _, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons[:2])
        assert get_completed_levels(test_user.id) == []

    def test_full_completion_certified(self, db_session, test_user, level_with_lessons):
        level, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons)
        certs = get_completed_levels(test_user.id)
        assert len(certs) == 1
        assert certs[0]['code'] == level.code
        assert certs[0]['total_lessons'] == 3
        assert certs[0]['completed_at'] is not None

    def test_get_completed_level_case_insensitive(self, db_session, test_user, level_with_lessons):
        level, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons)
        assert get_completed_level(test_user.id, level.code.lower()) is not None
        assert get_completed_level(test_user.id, 'ZZ') is None

    def test_render_png(self):
        png = render_certificate_png('Тест Юзер', 'B1', 'Intermediate', date(2026, 6, 1))
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert len(png) > 5000


@pytest.mark.smoke
class TestCertificateRoutes:
    def test_page_renders_for_completed_level(
        self, authenticated_client, db_session, test_user, level_with_lessons
    ):
        level, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons)
        resp = authenticated_client.get(
            f'/u/{test_user.username}/certificate/{level.code}'
        )
        assert resp.status_code == 200
        assert 'Сертификат'.encode() in resp.data

    def test_404_when_level_not_completed(
        self, authenticated_client, db_session, test_user, level_with_lessons
    ):
        level, _, _ = level_with_lessons
        resp = authenticated_client.get(
            f'/u/{test_user.username}/certificate/{level.code}'
        )
        assert resp.status_code == 404

    def test_png_endpoint(
        self, authenticated_client, db_session, test_user, level_with_lessons
    ):
        level, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons)
        resp = authenticated_client.get(
            f'/u/{test_user.username}/certificate/{level.code}.png'
        )
        assert resp.status_code == 200
        assert resp.content_type == 'image/png'
        assert resp.data[:8] == b'\x89PNG\r\n\x1a\n'

    def test_hidden_profile_404_for_strangers(
        self, client, db_session, test_user, level_with_lessons
    ):
        level, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons)
        test_user.profile_is_public = False
        db_session.commit()
        resp = client.get(f'/u/{test_user.username}/certificate/{level.code}')
        assert resp.status_code == 404
        resp = client.get(f'/u/{test_user.username}/certificate/{level.code}.png')
        assert resp.status_code == 404

    def test_public_for_anonymous_when_visible(
        self, client, db_session, test_user, level_with_lessons
    ):
        level, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons)
        resp = client.get(f'/u/{test_user.username}/certificate/{level.code}')
        assert resp.status_code == 200

    def test_achievements_page_lists_certificates(
        self, authenticated_client, db_session, test_user, level_with_lessons
    ):
        level, _, lessons = level_with_lessons
        _complete(db_session, test_user.id, lessons)
        resp = authenticated_client.get('/study/achievements')
        assert resp.status_code == 200
        assert 'Сертификаты уровней'.encode() in resp.data
        assert level.code.encode() in resp.data
