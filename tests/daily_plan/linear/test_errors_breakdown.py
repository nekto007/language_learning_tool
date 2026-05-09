"""Tests for ``get_unresolved_breakdown`` and the /api/error-review/summary route."""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.errors import get_unresolved_breakdown
from app.daily_plan.linear.models import QuizErrorLog
from app.grammar_lab.models import GrammarTopic
from app.utils.db import db as real_db


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'breakuser_{suffix}',
        email=f'breakuser_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_topic(db_session, title: str) -> GrammarTopic:
    slug = f'topic-{uuid.uuid4().hex[:8]}'
    topic = GrammarTopic(
        slug=slug,
        title=title,
        title_ru=title + ' RU',
        level='A1',
        order=1,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


def _make_module(db_session) -> Module:
    level = CEFRLevel(code=_unique_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M1',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module: Module, *, type_='quiz', topic_id=None, title='L') -> Lessons:
    next_number = db_session.query(Lessons).filter_by(module_id=module.id).count() + 1
    lesson = Lessons(
        module_id=module.id,
        number=next_number,
        title=title,
        type=type_,
        content={},
        grammar_topic_id=topic_id,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _seed_errors(db_session, user_id: int, lesson_id: int, count: int) -> None:
    for i in range(count):
        db_session.add(QuizErrorLog(
            user_id=user_id,
            lesson_id=lesson_id,
            question_payload={'idx': i},
        ))
    db_session.commit()


class TestGetUnresolvedBreakdown:
    def test_empty_backlog_returns_empty_lists(self, db_session):
        user = _make_user(db_session)
        out = get_unresolved_breakdown(user.id, real_db)
        assert out == {'by_lesson': [], 'by_topic': []}

    def test_groups_by_lesson_and_topic_direct(self, db_session):
        user = _make_user(db_session)
        topic_a = _make_topic(db_session, 'TopicA')
        topic_b = _make_topic(db_session, 'TopicB')
        module = _make_module(db_session)
        l1 = _make_lesson(db_session, module, type_='grammar', topic_id=topic_a.id, title='LA')
        l2 = _make_lesson(db_session, module, type_='grammar', topic_id=topic_b.id, title='LB')

        _seed_errors(db_session, user.id, l1.id, 3)
        _seed_errors(db_session, user.id, l2.id, 1)

        out = get_unresolved_breakdown(user.id, real_db)

        by_lesson = out['by_lesson']
        assert by_lesson[0] == {'id': l1.id, 'title': 'LA', 'count': 3}
        assert by_lesson[1] == {'id': l2.id, 'title': 'LB', 'count': 1}

        by_topic = out['by_topic']
        assert by_topic[0]['id'] == topic_a.id
        assert by_topic[0]['count'] == 3
        assert by_topic[0]['title'] == 'TopicA RU'
        assert by_topic[1]['id'] == topic_b.id
        assert by_topic[1]['count'] == 1

    def test_inferred_topic_from_module_grammar_lesson(self, db_session):
        """Quiz lesson without grammar_topic_id should inherit module's grammar lesson topic."""
        user = _make_user(db_session)
        topic = _make_topic(db_session, 'Inferred')
        module = _make_module(db_session)
        # Grammar lesson with topic in same module
        _make_lesson(db_session, module, type_='grammar', topic_id=topic.id, title='G')
        # Quiz lesson without topic
        quiz_lesson = _make_lesson(db_session, module, type_='quiz', topic_id=None, title='Q')

        _seed_errors(db_session, user.id, quiz_lesson.id, 2)

        out = get_unresolved_breakdown(user.id, real_db)
        assert out['by_lesson'] == [{'id': quiz_lesson.id, 'title': 'Q', 'count': 2}]
        assert len(out['by_topic']) == 1
        assert out['by_topic'][0]['id'] == topic.id
        assert out['by_topic'][0]['count'] == 2

    def test_no_topic_bucketed_under_none(self, db_session):
        user = _make_user(db_session)
        module = _make_module(db_session)
        # Vocab quiz, no grammar lesson in module → topic id None
        quiz_lesson = _make_lesson(db_session, module, type_='quiz', topic_id=None)

        _seed_errors(db_session, user.id, quiz_lesson.id, 2)

        out = get_unresolved_breakdown(user.id, real_db)
        assert out['by_topic'] == [{'id': None, 'title': '', 'count': 2}]

    def test_resolved_errors_excluded(self, db_session):
        user = _make_user(db_session)
        topic = _make_topic(db_session, 'T')
        module = _make_module(db_session)
        lesson = _make_lesson(db_session, module, type_='grammar', topic_id=topic.id)
        _seed_errors(db_session, user.id, lesson.id, 2)

        from datetime import datetime, timezone
        for row in db_session.query(QuizErrorLog).filter_by(user_id=user.id).all():
            row.resolved_at = datetime.now(timezone.utc)
        db_session.commit()

        out = get_unresolved_breakdown(user.id, real_db)
        assert out == {'by_lesson': [], 'by_topic': []}


class TestErrorReviewSummaryEndpoint:
    def test_returns_breakdown_payload(self, authenticated_client, db_session, test_user):
        topic = _make_topic(db_session, 'TX')
        module = _make_module(db_session)
        lesson = _make_lesson(db_session, module, type_='grammar', topic_id=topic.id, title='LX')
        _seed_errors(db_session, test_user.id, lesson.id, 2)

        response = authenticated_client.get('/api/error-review/summary')
        assert response.status_code == 200
        body = response.get_json()
        assert body['unresolved_count'] == 2
        assert body['last_resolved_at'] is None
        assert body['by_lesson'] == [{'id': lesson.id, 'title': 'LX', 'count': 2}]
        assert len(body['by_topic']) == 1
        assert body['by_topic'][0]['id'] == topic.id
        assert body['by_topic'][0]['count'] == 2

    def test_empty_payload(self, authenticated_client, db_session, test_user):
        response = authenticated_client.get('/api/error-review/summary')
        assert response.status_code == 200
        body = response.get_json()
        assert body['unresolved_count'] == 0
        assert body['by_lesson'] == []
        assert body['by_topic'] == []

    def test_requires_auth(self, client):
        response = client.get('/api/error-review/summary')
        assert response.status_code in (401, 302, 403)
