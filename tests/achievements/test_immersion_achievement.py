"""Tests for immersion_daily achievement (Task 61).

Covers:
- immersion_daily granted when all 4 skills practiced in one day
- only 3 skills → not granted
- second call on same day → idempotent
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.achievements.seed import seed_achievements
from app.achievements.services import check_immersion_achievement
from app.auth.models import User
from app.books.reading_session import UserReadingSession
from app.curriculum.models import (
    ListeningAttempt,
    PronunciationAttempt,
    UserWritingAttempt,
)
from app.study.models import Achievement, UserAchievement


BADGE_CODE = 'immersion_daily'
TODAY = date.today()
TODAY_START = datetime(TODAY.year, TODAY.month, TODAY.day)
TODAY_START_TZ = TODAY_START.replace(tzinfo=timezone.utc)


@pytest.fixture
def imm_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'imm_{suffix}',
        email=f'imm_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def imm_badge(db_session):
    seed_achievements()
    db_session.flush()
    badge = Achievement.query.filter_by(code=BADGE_CODE).first()
    assert badge is not None, f"Badge '{BADGE_CODE}' not seeded"
    return badge


@pytest.fixture
def test_lesson_for_imm(db_session):
    from app.curriculum.models import Lessons, Module
    from app.curriculum.models import CEFRLevel

    level = CEFRLevel.query.first()
    if level is None:
        level = CEFRLevel(code='A1', name='Beginner', description='Beginner', order=1)
        db_session.add(level)
        db_session.flush()

    module = Module(
        level_id=level.id,
        number=99,
        title='Imm Test Module',
        description='',
        raw_content={'module': {'id': 99, 'title': 'T', 'lessons': []}},
        min_score_required=70,
        allow_skip_test=False,
        input_mode='mixed',
    )
    db_session.add(module)
    db_session.flush()

    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Imm Lesson',
        type='quiz',
        order=0,
        content={'questions': []},
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


@pytest.fixture
def test_chapter_for_imm(db_session):
    from app.books.models import Book, Chapter

    book = Book(title='Imm Book', author='A', level='A1', chapters_cnt=1)
    db_session.add(book)
    db_session.flush()

    chapter = Chapter(
        book_id=book.id,
        chap_num=1,
        title='Imm Chapter',
        words=50,
        text_raw='Test.',
    )
    db_session.add(chapter)
    db_session.flush()
    return chapter


def _add_listening(db_session, user_id, lesson_id, created_at=None):
    row = ListeningAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        score=80.0,
        replay_count=0,
        created_at=created_at or TODAY_START,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_writing(db_session, user_id, lesson_id, created_at=None):
    row = UserWritingAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        response_text='Test response text for the writing exercise.',
        word_count=8,
        checklist_completed=True,
        created_at=created_at or TODAY_START,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_speaking(db_session, user_id, created_at=None):
    row = PronunciationAttempt(
        user_id=user_id,
        word='hello',
        recognized_text='hello',
        matched=True,
        created_at=created_at or TODAY_START,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_reading(db_session, user_id, chapter_id, started_at=None):
    row = UserReadingSession(
        user_id=user_id,
        chapter_id=chapter_id,
        started_at=started_at or TODAY_START_TZ,
        ended_at=TODAY_START_TZ + timedelta(minutes=5),
        offset_delta=0.1,
    )
    db_session.add(row)
    db_session.flush()
    return row


class TestImmersionAllFour:
    def test_all_four_grants_badge(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        _add_listening(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_writing(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_speaking(db_session, imm_user.id)
        _add_reading(db_session, imm_user.id, test_chapter_for_imm.id)

        awarded = check_immersion_achievement(imm_user.id, TODAY, db_session)
        codes = {a.code for a in awarded}
        assert BADGE_CODE in codes

    def test_idempotent_second_call(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        _add_listening(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_writing(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_speaking(db_session, imm_user.id)
        _add_reading(db_session, imm_user.id, test_chapter_for_imm.id)

        check_immersion_achievement(imm_user.id, TODAY, db_session)
        awarded2 = check_immersion_achievement(imm_user.id, TODAY, db_session)
        assert awarded2 == []

    def test_badge_row_created_in_db(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        _add_listening(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_writing(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_speaking(db_session, imm_user.id)
        _add_reading(db_session, imm_user.id, test_chapter_for_imm.id)

        check_immersion_achievement(imm_user.id, TODAY, db_session)
        ua = UserAchievement.query.filter_by(
            user_id=imm_user.id, achievement_id=imm_badge.id
        ).first()
        assert ua is not None


class TestImmersionOnlyThree:
    def test_no_listening_no_badge(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        _add_writing(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_speaking(db_session, imm_user.id)
        _add_reading(db_session, imm_user.id, test_chapter_for_imm.id)

        awarded = check_immersion_achievement(imm_user.id, TODAY, db_session)
        assert awarded == []

    def test_no_writing_no_badge(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        _add_listening(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_speaking(db_session, imm_user.id)
        _add_reading(db_session, imm_user.id, test_chapter_for_imm.id)

        awarded = check_immersion_achievement(imm_user.id, TODAY, db_session)
        assert awarded == []

    def test_no_speaking_no_badge(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        _add_listening(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_writing(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_reading(db_session, imm_user.id, test_chapter_for_imm.id)

        awarded = check_immersion_achievement(imm_user.id, TODAY, db_session)
        assert awarded == []

    def test_no_reading_no_badge(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        _add_listening(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_writing(db_session, imm_user.id, test_lesson_for_imm.id)
        _add_speaking(db_session, imm_user.id)

        awarded = check_immersion_achievement(imm_user.id, TODAY, db_session)
        assert awarded == []

    def test_no_activity_no_badge(self, db_session, imm_user, imm_badge):
        awarded = check_immersion_achievement(imm_user.id, TODAY, db_session)
        assert awarded == []


class TestImmersionDateBoundary:
    def test_yesterday_activity_does_not_count_for_today(
        self, db_session, imm_user, imm_badge, test_lesson_for_imm, test_chapter_for_imm
    ):
        yesterday = TODAY_START - timedelta(days=1)
        yesterday_tz = yesterday.replace(tzinfo=timezone.utc)

        _add_listening(db_session, imm_user.id, test_lesson_for_imm.id, created_at=yesterday)
        _add_writing(db_session, imm_user.id, test_lesson_for_imm.id, created_at=yesterday)
        _add_speaking(db_session, imm_user.id, created_at=yesterday)
        _add_reading(db_session, imm_user.id, test_chapter_for_imm.id, started_at=yesterday_tz)

        awarded = check_immersion_achievement(imm_user.id, TODAY, db_session)
        assert awarded == []
