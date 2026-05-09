"""Activity-driven chain refresh in /api/daily-plan and /api/daily-status.

Verifies Task 3 acceptance: each request to the linear-plan API rebuilds the
slot chain from authoritative DB state. After the user records activity for
the trailing slot, the next response includes one additional slot. Once the
spine and other extension sources are exhausted, the chain stops growing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.books.models import Book, Chapter
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.models import UserReadingPreference


def _empty_summary() -> dict:
    return {
        'lessons_count': 0,
        'lesson_types': [],
        'words_reviewed': 0,
        'srs_words_reviewed': 0,
        'srs_new_reviewed': 0,
        'srs_review_reviewed': 0,
        'grammar_exercises': 0,
        'grammar_correct': 0,
        'books_read': [],
        'book_course_lessons_today': 0,
    }


def _make_level(db_session, order: int = 1) -> CEFRLevel:
    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(
        code=code,
        name=f'Level {code}',
        description='desc',
        order=order,
    )
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel) -> Module:
    module = Module(
        level_id=level.id,
        number=1,
        title=f'{level.code} M1',
        description='desc',
        raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module: Module, number: int) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'L{number}',
        type='quiz',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_book(db_session) -> Book:
    suffix = uuid.uuid4().hex[:8]
    book = Book(
        title=f'Book {suffix}',
        author='Author',
        level='A2',
        chapters_cnt=1,
        summary='s',
    )
    db_session.add(book)
    db_session.commit()
    db_session.add(Chapter(
        book_id=book.id, chap_num=1, title='Ch 1', words=100, text_raw='t',
    ))
    db_session.commit()
    return book


def _complete_lesson(db_session, user_id: int, lesson: Lessons) -> None:
    db_session.add(LessonProgress(
        user_id=user_id,
        lesson_id=lesson.id,
        status='completed',
        score=100.0,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    db_session.commit()


def _record_curriculum_xp(db_session, user_id: int) -> None:
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import (
        LINEAR_XP_EVENT_TYPE,
        get_linear_event_local_date,
    )
    from app.utils.db import db as real_db

    db_session.add(StreakEvent(
        user_id=user_id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=get_linear_event_local_date(user_id, real_db),
        coins_delta=0,
        details={'source': 'linear_curriculum_quiz', 'xp': 10},
    ))
    db_session.commit()


def _record_reading_xp(db_session, user_id: int) -> None:
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import (
        LINEAR_XP_EVENT_TYPE,
        get_linear_event_local_date,
    )
    from app.utils.db import db as real_db

    db_session.add(StreakEvent(
        user_id=user_id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=get_linear_event_local_date(user_id, real_db),
        coins_delta=0,
        details={'source': 'linear_book_reading', 'xp': 15},
    ))
    db_session.commit()


def _set_reading_preference(db_session, user_id: int, book: Book) -> None:
    db_session.add(UserReadingPreference(
        user_id=user_id,
        book_id=book.id,
        selected_at=datetime.now(timezone.utc),
    ))
    db_session.commit()


@pytest.fixture
def linear_user_setup(db_session, test_user):
    """Pin test_user to the linear plan with 3 lessons on the spine."""
    level = _make_level(db_session, order=1)
    module = _make_module(db_session, level)
    lessons = [
        _make_lesson(db_session, module, number=i)
        for i in (1, 2, 3)
    ]
    test_user.use_linear_plan = True
    test_user.onboarding_level = level.code
    db_session.commit()
    return {
        'user': test_user,
        'level': level,
        'module': module,
        'lessons': lessons,
    }


class TestDailyPlanChainRefresh:
    def test_chain_grows_with_each_completion_then_stops(
        self, authenticated_client, db_session, linear_user_setup,
    ):
        user = linear_user_setup['user']
        lessons = linear_user_setup['lessons']
        book = _make_book(db_session)

        with patch(
            'app.telegram.queries.get_daily_summary',
            return_value=_empty_summary(),
        ):
            # ── Initial request: baseline only (curriculum + srs + reading).
            response = authenticated_client.get('/api/daily-plan')
            assert response.status_code == 200
            data = response.get_json()
            assert data['mode'] == 'linear'
            assert data['chain_meta']['baseline_count'] == 3
            assert len(data['slots']) == 3
            assert len(data['baseline_slots']) == 3

            # ── First activity: complete lesson_1 + read today.
            _complete_lesson(db_session, user.id, lessons[0])
            _record_curriculum_xp(db_session, user.id)
            _set_reading_preference(db_session, user.id, book)
            _record_reading_xp(db_session, user.id)

            response = authenticated_client.get('/api/daily-plan')
            data = response.get_json()
            assert data['chain_meta']['baseline_count'] == 3
            assert len(data['slots']) == 4
            extension = data['slots'][-1]
            assert extension['kind'] == 'curriculum'
            assert extension['data']['lesson_id'] == lessons[1].id
            assert extension['data'].get('extension') is True

            # ── Second activity: complete lesson_2 → next extension is lesson_3.
            _complete_lesson(db_session, user.id, lessons[1])
            _record_curriculum_xp(db_session, user.id)

            response = authenticated_client.get('/api/daily-plan')
            data = response.get_json()
            # Baseline curriculum slot now reflects lesson_2 (most recent
            # completed today); the chain extension carries lesson_3.
            assert len(data['slots']) == 4
            extension = data['slots'][-1]
            assert extension['kind'] == 'curriculum'
            assert extension['data']['lesson_id'] == lessons[2].id
            assert extension['data'].get('extension') is True

            # ── Third activity: complete lesson_3, no spine remaining.
            _complete_lesson(db_session, user.id, lessons[2])
            _record_curriculum_xp(db_session, user.id)

            response = authenticated_client.get('/api/daily-plan')
            data = response.get_json()
            # Spine done, srs and reading already complete → no extras.
            assert len(data['slots']) == 3
            assert data['chain_meta']['has_more_available'] is False
            assert 'curriculum' in data['chain_meta']['exhausted_sources']

    def test_daily_status_chain_refresh_matches_daily_plan(
        self, authenticated_client, db_session, linear_user_setup,
    ):
        """`/api/daily-status` exposes the same regenerated chain via plan.slots."""
        user = linear_user_setup['user']
        lessons = linear_user_setup['lessons']
        book = _make_book(db_session)

        with patch(
            'app.telegram.queries.get_daily_summary',
            return_value=_empty_summary(),
        ), patch(
            'app.telegram.queries.get_yesterday_summary',
            return_value={},
        ), patch(
            'app.achievements.streak_service.process_streak_on_activity',
            return_value={
                'streak_status': {'streak': 0, 'has_activity_today': False},
                'required_steps': 3,
                'streak_repaired': False,
            },
        ):
            response = authenticated_client.get('/api/daily-status')
            assert response.status_code == 200
            data = response.get_json()
            assert data['plan']['mode'] == 'linear'
            assert len(data['plan']['slots']) == 3

            _complete_lesson(db_session, user.id, lessons[0])
            _record_curriculum_xp(db_session, user.id)
            _set_reading_preference(db_session, user.id, book)
            _record_reading_xp(db_session, user.id)

            response = authenticated_client.get('/api/daily-status')
            data = response.get_json()
            slots = data['plan']['slots']
            assert len(slots) == 4
            assert slots[-1]['kind'] == 'curriculum'
            assert slots[-1]['data']['lesson_id'] == lessons[1].id
