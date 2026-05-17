"""Tests for get_listening_stats in insights_service (Task 9).

Covers:
- Correct aggregates from ListeningAttempt rows
- Empty state returns zeros
- Only last-7-days data counted for avg_score and total_replays
- total_lessons is all-time distinct lesson count
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.curriculum.models import CEFRLevel, ListeningAttempt, Lessons, Module
from app.study.insights_service import get_listening_stats


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_lesson(db_session, lesson_type: str = 'dictation') -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='Module',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Listening Lesson',
        type=lesson_type,
        content={'audio_url': '/audio/test.mp3', 'transcript': 'Hello world'},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestGetListeningStats:
    def test_empty_state_returns_zeros(self, db_session, app, test_user):
        with app.app_context():
            result = get_listening_stats(test_user.id)
            assert result['total_lessons'] == 0
            assert result['avg_score'] == 0.0
            assert result['total_replays'] == 0

    def test_correct_aggregates(self, db_session, app, test_user):
        with app.app_context():
            lesson = _make_lesson(db_session)
            now = datetime.now(timezone.utc)
            for score, replays in [(80.0, 2), (100.0, 1)]:
                attempt = ListeningAttempt(
                    user_id=test_user.id,
                    lesson_id=lesson.id,
                    score=score,
                    replay_count=replays,
                    created_at=now - timedelta(days=1),
                )
                db_session.add(attempt)
            db_session.commit()

            result = get_listening_stats(test_user.id)
            assert result['total_lessons'] == 1
            assert result['avg_score'] == 90.0
            assert result['total_replays'] == 3

    def test_total_lessons_counts_distinct_lessons(self, db_session, app, test_user):
        with app.app_context():
            lesson1 = _make_lesson(db_session)
            lesson2 = _make_lesson(db_session, 'audio_fill_blank')
            now = datetime.now(timezone.utc)
            for lesson in (lesson1, lesson2):
                db_session.add(ListeningAttempt(
                    user_id=test_user.id,
                    lesson_id=lesson.id,
                    score=75.0,
                    replay_count=0,
                    created_at=now,
                ))
            # Second attempt on lesson1 — should not inflate distinct count
            db_session.add(ListeningAttempt(
                user_id=test_user.id,
                lesson_id=lesson1.id,
                score=90.0,
                replay_count=1,
                created_at=now,
            ))
            db_session.commit()

            result = get_listening_stats(test_user.id)
            assert result['total_lessons'] == 2

    def test_avg_score_only_last_7_days(self, db_session, app, test_user):
        """Old attempts (>7 days ago) must not affect avg_score."""
        with app.app_context():
            lesson = _make_lesson(db_session)
            now = datetime.now(timezone.utc)
            # Old attempt — should NOT be in avg
            db_session.add(ListeningAttempt(
                user_id=test_user.id,
                lesson_id=lesson.id,
                score=10.0,
                replay_count=5,
                created_at=now - timedelta(days=10),
            ))
            # Recent attempt
            db_session.add(ListeningAttempt(
                user_id=test_user.id,
                lesson_id=lesson.id,
                score=90.0,
                replay_count=1,
                created_at=now - timedelta(days=2),
            ))
            db_session.commit()

            result = get_listening_stats(test_user.id)
            # total_lessons is all-time: 1 distinct lesson
            assert result['total_lessons'] == 1
            # avg_score only from last 7 days
            assert result['avg_score'] == 90.0
            # total_replays only from last 7 days
            assert result['total_replays'] == 1

    def test_does_not_include_other_users_data(self, db_session, app, test_user):
        with app.app_context():
            from app.auth.models import User as UserModel
            uname = f'other_{uuid.uuid4().hex[:6]}'
            other = UserModel(
                username=uname,
                email=f'{uname}@example.com',
            )
            other.set_password('testpass')
            db_session.add(other)
            db_session.commit()

            lesson = _make_lesson(db_session)
            now = datetime.now(timezone.utc)
            db_session.add(ListeningAttempt(
                user_id=other.id,
                lesson_id=lesson.id,
                score=100.0,
                replay_count=3,
                created_at=now,
            ))
            db_session.commit()

            result = get_listening_stats(test_user.id)
            assert result['total_lessons'] == 0
            assert result['avg_score'] == 0.0
            assert result['total_replays'] == 0
