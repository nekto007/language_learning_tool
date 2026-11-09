# tests/admin/services/test_activity_feed_service.py

"""Unit tests for app/admin/services/activity_feed_service.py.

Coverage target: bring activity_feed_service from 16% to 80%+.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.admin.services.activity_feed_service import (
    ALL_EVENT_TYPES,
    EVENT_TYPE_LABELS,
    ActivityEvent,
    get_recent_events,
)
from app.auth.models import User
from app.utils.db import db
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db_session) -> User:
    name = f"afs_{uuid.uuid4().hex[:8]}"
    u = User(username=name, email=f"{name}@test.com", active=True)
    u.set_password("pass")
    db_session.add(u)
    db_session.flush()
    return u


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# EventType constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_all_event_types_list(self):
        assert "lesson_completed" in ALL_EVENT_TYPES
        assert "achievement_granted" in ALL_EVENT_TYPES
        assert "xp_awarded" in ALL_EVENT_TYPES
        assert "day_secured" in ALL_EVENT_TYPES
        assert "admin_action" in ALL_EVENT_TYPES

    def test_event_type_labels_cover_all_types(self):
        for et in ALL_EVENT_TYPES:
            assert et in EVENT_TYPE_LABELS


# ---------------------------------------------------------------------------
# ActivityEvent dataclass
# ---------------------------------------------------------------------------


class TestActivityEvent:
    def test_create_event(self):
        ts = _now()
        ev = ActivityEvent(
            timestamp=ts,
            user_id=1,
            user_email="user@test.com",
            event_type="lesson_completed",
            description="Test description",
        )
        assert ev.timestamp == ts
        assert ev.user_id == 1
        assert ev.detail_url is None

    def test_create_event_with_detail_url(self):
        ev = ActivityEvent(
            timestamp=_now(),
            user_id=1,
            user_email="a@b.com",
            event_type="admin_action",
            description="Did something",
            detail_url="/admin/foo",
        )
        assert ev.detail_url == "/admin/foo"


# ---------------------------------------------------------------------------
# _fetch_lesson_completed
# ---------------------------------------------------------------------------


class TestFetchLessonCompleted:
    @pytest.mark.smoke
    def test_returns_lesson_completed_events(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_lesson_completed
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

        user = _make_user(db_session)
        code = unique_level_code()
        level = CEFRLevel(code=code, name="Lvl", description="", order=88)
        db_session.add(level)
        db_session.flush()
        mod = Module(level_id=level.id, number=1, title="Mod")
        db_session.add(mod)
        db_session.flush()
        lesson = Lessons(module_id=mod.id, number=1, title="Les", type="quiz", order=1)
        db_session.add(lesson)
        db_session.flush()
        now = _now()
        lp = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status="completed",
            last_activity=now,
            completed_at=now,
            score=85.0,
        )
        db_session.add(lp)
        db_session.commit()

        events = _fetch_lesson_completed(db_session, None, None, None, 100)
        assert any(e.user_id == user.id for e in events)
        matching = [e for e in events if e.user_id == user.id]
        assert len(matching) >= 1
        assert "85%" in matching[0].description or "85" in matching[0].description

    def test_filter_by_user_id(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_lesson_completed
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

        user1 = _make_user(db_session)
        user2 = _make_user(db_session)
        code = unique_level_code()
        level = CEFRLevel(code=code, name="Lvl", description="", order=87)
        db_session.add(level)
        db_session.flush()
        mod = Module(level_id=level.id, number=1, title="Mod")
        db_session.add(mod)
        db_session.flush()
        lesson = Lessons(module_id=mod.id, number=1, title="Les", type="text", order=1)
        db_session.add(lesson)
        db_session.flush()
        now = _now()
        for u in [user1, user2]:
            lp = LessonProgress(
                user_id=u.id,
                lesson_id=lesson.id,
                status="completed",
                last_activity=now,
                completed_at=now,
            )
            db_session.add(lp)
        db_session.commit()

        events = _fetch_lesson_completed(db_session, user1.id, None, None, 100)
        assert all(e.user_id == user1.id for e in events)

    def test_filter_by_date_range(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_lesson_completed
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

        user = _make_user(db_session)
        code = unique_level_code()
        level = CEFRLevel(code=code, name="Lvl", description="", order=86)
        db_session.add(level)
        db_session.flush()
        mod = Module(level_id=level.id, number=1, title="Mod")
        db_session.add(mod)
        db_session.flush()
        lesson = Lessons(module_id=mod.id, number=1, title="Les", type="text", order=1)
        db_session.add(lesson)
        db_session.flush()

        now = _now()
        old = now - timedelta(days=30)
        lp = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status="completed",
            last_activity=old,
            completed_at=old,
        )
        db_session.add(lp)
        db_session.commit()

        future = now + timedelta(days=1)
        events = _fetch_lesson_completed(db_session, user.id, future, None, 100)
        assert all(e.user_id != user.id for e in events)

    def test_score_included_in_description(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_lesson_completed
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

        user = _make_user(db_session)
        code = unique_level_code()
        level = CEFRLevel(code=code, name="Lvl", description="", order=85)
        db_session.add(level)
        db_session.flush()
        mod = Module(level_id=level.id, number=1, title="Mod")
        db_session.add(mod)
        db_session.flush()
        lesson = Lessons(module_id=mod.id, number=1, title="ScoreLes", type="quiz", order=1)
        db_session.add(lesson)
        db_session.flush()
        now = _now()
        lp = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status="completed",
            last_activity=now,
            completed_at=now,
            score=72.5,
        )
        db_session.add(lp)
        db_session.commit()

        events = _fetch_lesson_completed(db_session, user.id, None, None, 100)
        matching = [e for e in events if e.user_id == user.id]
        assert len(matching) >= 1
        # Should include the score percentage
        assert "73%" in matching[0].description or "72%" in matching[0].description


# ---------------------------------------------------------------------------
# _fetch_achievements
# ---------------------------------------------------------------------------


class TestFetchAchievements:
    @pytest.mark.smoke
    def test_returns_achievement_events(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_achievements
        from app.study.models import Achievement, UserAchievement

        user = _make_user(db_session)
        code = f"ach_{uuid.uuid4().hex[:6]}"
        ach = Achievement(
            name=f"Test Ach {code}",
            description="Test",
            icon="⭐",
            code=code,
            category="test",
        )
        db_session.add(ach)
        db_session.flush()
        ua = UserAchievement(user_id=user.id, achievement_id=ach.id, earned_at=_now())
        db_session.add(ua)
        db_session.commit()

        events = _fetch_achievements(db_session, user.id, None, None, 100)
        assert any(e.user_id == user.id for e in events)
        matching = [e for e in events if e.user_id == user.id]
        assert ach.name in matching[0].description

    def test_filter_by_user(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_achievements
        from app.study.models import Achievement, UserAchievement

        user1 = _make_user(db_session)
        user2 = _make_user(db_session)
        code = f"ach_{uuid.uuid4().hex[:6]}"
        ach = Achievement(
            name=f"Ach {code}", description="Test", icon="star",
            code=code, category="test",
        )
        db_session.add(ach)
        db_session.flush()
        now = _now()
        for u in [user1, user2]:
            db_session.add(UserAchievement(user_id=u.id, achievement_id=ach.id, earned_at=now))
        db_session.commit()

        events = _fetch_achievements(db_session, user1.id, None, None, 100)
        assert all(e.user_id == user1.id for e in events)


# ---------------------------------------------------------------------------
# _fetch_xp_events
# ---------------------------------------------------------------------------


class TestFetchXpEvents:
    @pytest.mark.smoke
    def test_returns_xp_events(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import _fetch_xp_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id,
            event_type="xp_curriculum_lesson",
            coins_delta=0,
            details={"xp": 40},
            created_at=now,
            event_date=now.date(),
        )
        db_session.add(se)
        db_session.commit()

        events = _fetch_xp_events(db_session, user.id, None, None, 100)
        assert any(e.user_id == user.id for e in events)
        matching = [e for e in events if e.user_id == user.id]
        assert "+40" in matching[0].description

    def test_non_xp_events_excluded(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import _fetch_xp_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id,
            event_type="streak_milestone",
            coins_delta=0,
            details={},
            created_at=now,
            event_date=now.date(),
        )
        db_session.add(se)
        db_session.commit()

        events = _fetch_xp_events(db_session, user.id, None, None, 100)
        assert all(e.user_id != user.id for e in events)

    def test_coins_delta_fallback_when_no_details_xp(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import _fetch_xp_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id,
            event_type="xp_srs",
            coins_delta=15,
            details={},
            created_at=now,
            event_date=now.date(),
        )
        db_session.add(se)
        db_session.commit()

        events = _fetch_xp_events(db_session, user.id, None, None, 100)
        matching = [e for e in events if e.user_id == user.id]
        assert "+15" in matching[0].description


# ---------------------------------------------------------------------------
# _fetch_day_secured
# ---------------------------------------------------------------------------


class TestFetchDaySecured:
    @pytest.mark.smoke
    def test_returns_day_secured_events(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_day_secured
        from app.daily_plan.models import DailyPlanLog

        user = _make_user(db_session)
        now = _now()
        log = DailyPlanLog(
            user_id=user.id,
            plan_date=now.date(),
            secured_at=now,
            mission_type="progress",
        )
        db_session.add(log)
        db_session.commit()

        events = _fetch_day_secured(db_session, user.id, None, None, 100)
        assert any(e.user_id == user.id for e in events)
        matching = [e for e in events if e.user_id == user.id]
        assert "(progress)" in matching[0].description

    def test_only_secured_days_returned(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_day_secured
        from app.daily_plan.models import DailyPlanLog

        user = _make_user(db_session)
        now = _now()
        log = DailyPlanLog(
            user_id=user.id,
            plan_date=now.date(),
            secured_at=None,  # Not secured
        )
        db_session.add(log)
        db_session.commit()

        events = _fetch_day_secured(db_session, user.id, None, None, 100)
        assert all(e.user_id != user.id for e in events)

    def test_mission_type_none_shows_no_parens(self, app, db_session):
        from app.admin.services.activity_feed_service import _fetch_day_secured
        from app.daily_plan.models import DailyPlanLog

        user = _make_user(db_session)
        now = _now()
        log = DailyPlanLog(
            user_id=user.id,
            plan_date=now.date(),
            secured_at=now,
            mission_type=None,
        )
        db_session.add(log)
        db_session.commit()

        events = _fetch_day_secured(db_session, user.id, None, None, 100)
        matching = [e for e in events if e.user_id == user.id]
        assert "(None)" not in matching[0].description


# ---------------------------------------------------------------------------
# _fetch_admin_actions
# ---------------------------------------------------------------------------


class TestFetchAdminActions:
    @pytest.mark.smoke
    def test_returns_admin_action_events(self, app, db_session):
        from app.admin.audit import AdminAuditLog
        from app.admin.services.activity_feed_service import _fetch_admin_actions

        admin = _make_user(db_session)
        now = _now()
        log = AdminAuditLog(
            admin_id=admin.id,
            action="word.delete",
            target_type="word",
            target_id=42,
            created_at=now,
        )
        db_session.add(log)
        db_session.commit()

        events = _fetch_admin_actions(db_session, admin.id, None, None, 100)
        assert any(e.user_id == admin.id for e in events)
        matching = [e for e in events if e.user_id == admin.id]
        assert "word.delete" in matching[0].description
        assert "word#42" in matching[0].description

    def test_filter_by_admin_id(self, app, db_session):
        from app.admin.audit import AdminAuditLog
        from app.admin.services.activity_feed_service import _fetch_admin_actions

        admin1 = _make_user(db_session)
        admin2 = _make_user(db_session)
        now = _now()
        for a in [admin1, admin2]:
            db_session.add(AdminAuditLog(admin_id=a.id, action="test.action", created_at=now))
        db_session.commit()

        events = _fetch_admin_actions(db_session, admin1.id, None, None, 100)
        assert all(e.user_id == admin1.id for e in events)

    def test_deleted_admin_shows_id_fallback(self, app, db_session):
        from app.admin.audit import AdminAuditLog
        from app.admin.services.activity_feed_service import _fetch_admin_actions

        now = _now()
        # Create with null admin_id (admin was deleted)
        log = AdminAuditLog(
            admin_id=None,
            action="ghost.action",
            created_at=now,
        )
        db_session.add(log)
        db_session.commit()

        events = _fetch_admin_actions(db_session, None, None, None, 100)
        ghost_events = [e for e in events if e.event_type == "admin_action" and "ghost.action" in e.description]
        assert len(ghost_events) >= 1
        assert "admin#None" in ghost_events[0].user_email or ghost_events[0].user_email is not None


# ---------------------------------------------------------------------------
# get_recent_events (integration)
# ---------------------------------------------------------------------------


class TestGetRecentEvents:
    @pytest.mark.smoke
    def test_returns_merged_sorted_events(self, app, db_session):
        """get_recent_events returns events from multiple sources merged by time."""
        from app.achievements.models import StreakEvent
        from app.admin.audit import AdminAuditLog

        user = _make_user(db_session)
        now = _now()

        se = StreakEvent(
            user_id=user.id,
            event_type="xp_curriculum_lesson",
            coins_delta=0,
            details={"xp": 20},
            created_at=now,
            event_date=now.date(),
        )
        log = AdminAuditLog(admin_id=user.id, action="test.action", created_at=now - timedelta(seconds=1))
        db_session.add(se)
        db_session.add(log)
        db_session.commit()

        events = get_recent_events(db_session, limit=50)
        assert len(events) >= 1
        # Should be sorted newest first
        for i in range(len(events) - 1):
            assert events[i].timestamp >= events[i + 1].timestamp

    def test_event_type_filter_works(self, app, db_session):
        """Only requested event types are returned."""
        from app.admin.audit import AdminAuditLog

        admin = _make_user(db_session)
        now = _now()
        db_session.add(AdminAuditLog(admin_id=admin.id, action="audit.test", created_at=now))
        db_session.commit()

        events = get_recent_events(db_session, event_types=["admin_action"], limit=50)
        assert all(e.event_type == "admin_action" for e in events)

    def test_offset_and_limit_work(self, app, db_session):
        """offset/limit slice is applied after merge."""
        from app.admin.audit import AdminAuditLog

        admin = _make_user(db_session)
        now = _now()
        for i in range(5):
            db_session.add(
                AdminAuditLog(
                    admin_id=admin.id,
                    action=f"action.{i}",
                    created_at=now - timedelta(seconds=i),
                )
            )
        db_session.commit()

        events_all = get_recent_events(
            db_session, event_types=["admin_action"], limit=10, offset=0,
            user_id=admin.id,
        )
        events_offset = get_recent_events(
            db_session, event_types=["admin_action"], limit=10, offset=2,
            user_id=admin.id,
        )
        assert len(events_all) == 5
        assert len(events_offset) == 3

    def test_exception_in_one_source_does_not_crash(self, app, db_session):
        """If one fetch helper throws, remaining sources still return."""
        from unittest.mock import patch

        with patch(
            "app.admin.services.activity_feed_service._fetch_lesson_completed",
            side_effect=RuntimeError("DB down"),
        ):
            events = get_recent_events(
                db_session,
                event_types=["lesson_completed", "admin_action"],
                limit=10,
            )
        # Should not raise — lesson_completed events silently skipped
        assert isinstance(events, list)

    def test_date_range_filter_passes_through(self, app, db_session):
        """date_from/date_to are forwarded to each fetch helper."""
        from app.admin.audit import AdminAuditLog

        admin = _make_user(db_session)
        now = _now()
        old = now - timedelta(days=30)
        db_session.add(AdminAuditLog(admin_id=admin.id, action="old.action", created_at=old))
        db_session.commit()

        future = now + timedelta(days=1)
        events = get_recent_events(
            db_session,
            user_id=admin.id,
            event_types=["admin_action"],
            date_from=future,
            limit=10,
        )
        assert all("old.action" not in e.description for e in events)


class TestLearningDiagnostics:
    @staticmethod
    def _lesson(db_session, lesson_type='translation'):
        from app.curriculum.models import CEFRLevel, Lessons, Module
        level = CEFRLevel(code=unique_level_code(), name='Test', order=100)
        db_session.add(level)
        db_session.flush()
        module = Module(level_id=level.id, number=1, title='Diagnostic module')
        db_session.add(module)
        db_session.flush()
        lesson = Lessons(module_id=module.id, number=1, title='Diagnostic lesson',
                         type=lesson_type, order=1)
        db_session.add(lesson)
        db_session.flush()
        return lesson

    def test_registration_and_first_open_have_distinct_dates_and_links(self, app, db_session):
        from app.curriculum.models import LessonProgress
        user = _make_user(db_session)
        lesson = self._lesson(db_session)
        opened_at = _now() - timedelta(days=2)
        user.created_at = opened_at - timedelta(hours=1)
        db_session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id,
                                    started_at=opened_at, last_activity=_now()))
        db_session.commit()
        events = get_recent_events(db_session, user_id=user.id,
                                   event_types=['registered', 'lesson_opened'])
        assert [event.event_type for event in events] == ['lesson_opened', 'registered']
        assert events[0].timestamp == opened_at
        assert events[0].lesson_id == lesson.id
        assert events[0].module_title == 'Diagnostic module'
        assert events[0].detail_url.endswith(f'/students/{user.id}#lesson-{lesson.id}')
        assert events[0].user_name == user.username
        recent_events = get_recent_events(db_session, user_id=user.id,
                                          event_types=['lesson_opened'], date_from=_now() - timedelta(days=1))
        assert recent_events == []  # last_activity is not a new opening

    def test_real_zero_counter_translation_is_included_passive_reading_is_not(self, app, db_session):
        from app.curriculum.models import LessonAttempt
        user = _make_user(db_session)
        translation = self._lesson(db_session, 'translation')
        reading = self._lesson(db_session, 'reading')
        for lesson in (translation, reading):
            db_session.add(LessonAttempt(user_id=user.id, lesson_id=lesson.id, attempt_number=1,
                                        completed_at=_now(), score=0, passed=False, total_questions=0))
        db_session.commit()
        events = get_recent_events(db_session, user_id=user.id, event_types=['lesson_attempt'])
        assert len(events) == 1
        assert events[0].lesson_id == translation.id
        assert events[0].score == 0
        assert 'не пройдено' in events[0].description

    @pytest.mark.parametrize('lesson_type', [
        'vocabulary', 'card', 'flashcards', 'reading', 'listening_immersion', 'writing_prompt', 'grammar',
    ])
    def test_passive_completion_does_not_claim_accuracy(self, app, db_session, lesson_type):
        from app.curriculum.models import LessonProgress
        user = _make_user(db_session)
        lesson = self._lesson(db_session, lesson_type)
        db_session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id,
                                    status='completed', completed_at=_now(), score=100, data={}))
        db_session.commit()
        events = get_recent_events(db_session, user_id=user.id, event_types=['lesson_completed'])
        assert len(events) == 1
        assert events[0].score is None
        assert '%' not in events[0].description

    def test_testout_completion_has_no_per_lesson_accuracy(self, app, db_session):
        from app.curriculum.models import LessonProgress
        user = _make_user(db_session)
        lesson = self._lesson(db_session, 'quiz')
        db_session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id,
                                    status='completed', completed_at=_now(), score=100,
                                    data={'test_out': True}))
        db_session.commit()
        events = get_recent_events(db_session, user_id=user.id,
                                   event_types=['lesson_completed', 'lesson_opened'])
        assert len(events) == 1
        assert events[0].score is None and '%' not in events[0].description
        assert 'экстерном' in events[0].description

    def test_completion_score_requires_real_grading_semantics(self):
        from types import SimpleNamespace
        from app.admin.services.activity_feed_service import _completion_score
        progress = SimpleNamespace(score=100, data={})
        assert _completion_score(progress, SimpleNamespace(type='reading')) is None
        assert _completion_score(progress, SimpleNamespace(type='grammar')) is None
        assert _completion_score(progress, SimpleNamespace(type='quiz')) == 100
        progress.data = {'test_out': True}
        assert _completion_score(progress, SimpleNamespace(type='quiz')) is None
        progress.data = {'total_questions': 3}
        assert _completion_score(progress, SimpleNamespace(type='grammar')) == 100

    def test_writing_and_pronunciation_do_not_expose_answers(self, app, db_session):
        from app.curriculum.models import PronunciationAttempt, UserWritingAttempt
        user = _make_user(db_session)
        lesson = self._lesson(db_session, 'writing_prompt')
        secret = 'private answer never in timeline'
        db_session.add(UserWritingAttempt(user_id=user.id, lesson_id=lesson.id,
                                         response_text=secret, word_count=5))
        db_session.add(PronunciationAttempt(user_id=user.id, word='privateword',
                                           recognized_text=secret, matched=False))
        db_session.commit()
        events = get_recent_events(db_session, user_id=user.id,
                                   event_types=['writing_submitted', 'pronunciation_attempt'])
        assert len(events) == 2
        assert {event.event_type for event in events} == {'writing_submitted', 'pronunciation_attempt'}
        assert all(secret not in event.description and 'privateword' not in event.description for event in events)

    def test_equal_time_pagination_is_stable(self, app, db_session):
        from app.curriculum.models import LessonAttempt
        user = _make_user(db_session)
        lesson = self._lesson(db_session)
        stamp = _now()
        for number in range(1, 5):
            db_session.add(LessonAttempt(user_id=user.id, lesson_id=lesson.id, attempt_number=number,
                                        completed_at=stamp, score=20, passed=False))
        db_session.commit()
        first = get_recent_events(db_session, user_id=user.id, event_types=['lesson_attempt'], limit=2)
        second = get_recent_events(db_session, user_id=user.id, event_types=['lesson_attempt'], limit=2, offset=2)
        assert [e.attempt_number for e in first + second] == [4, 3, 2, 1]

    def test_audio_sources_are_preserved_and_paginate_without_inferred_merging(self):
        from unittest.mock import MagicMock, patch
        stamp = _now()
        common = {'user_id': 5, 'user_email': None, 'lesson_id': 9, 'score': 50,
                  'lesson_type': 'dictation'}
        grade = ActivityEvent(timestamp=stamp, event_type='lesson_attempt', description='graded',
                              attempt_number=2, **common)
        audio = ActivityEvent(timestamp=stamp + timedelta(seconds=1), event_type='listening_submitted',
                              description='audio', **common)
        with patch('app.admin.services.activity_feed_service._fetch_lesson_attempts', return_value=[grade]), \
             patch('app.admin.services.activity_feed_service._fetch_listening_submissions', return_value=[audio]):
            first = get_recent_events(MagicMock(), event_types=['lesson_attempt', 'listening_submitted'], limit=1)
            second = get_recent_events(MagicMock(), event_types=['lesson_attempt', 'listening_submitted'],
                                       limit=1, offset=1)
        assert first == [audio]
        assert second == [grade]
        assert audio.attempt_number is None  # no invented cross-source association

    def test_source_errors_are_visible_and_mixed_timezones_sort_safely(self):
        from unittest.mock import MagicMock, patch
        stamp = _now()
        first = ActivityEvent(stamp, 1, None, 'registered', 'first')
        second = ActivityEvent((stamp + timedelta(hours=1)).replace(tzinfo=timezone.utc),
                               1, None, 'lesson_opened', 'second')
        errors = []
        with patch('app.admin.services.activity_feed_service._fetch_registered', return_value=[first]), \
             patch('app.admin.services.activity_feed_service._fetch_lesson_opened', return_value=[second]), \
             patch('app.admin.services.activity_feed_service._fetch_lesson_attempts', side_effect=RuntimeError):
            result = get_recent_events(MagicMock(), event_types=['registered', 'lesson_opened', 'lesson_attempt'],
                                       source_errors=errors)
        assert result == [second, first]
        assert errors == ['lesson_attempt']

    def test_sql_failure_rolls_back_only_its_source_savepoint(self, app, db_session):
        from sqlalchemy import text
        from unittest.mock import patch
        user = _make_user(db_session)
        db_session.commit()
        errors = []

        def invalid_query(*args):
            db_session.execute(text('SELECT missing_activity_diagnostic_column'))

        with patch('app.admin.services.activity_feed_service._fetch_lesson_attempts', side_effect=invalid_query):
            events = get_recent_events(db_session, user_id=user.id,
                                       event_types=['lesson_attempt', 'registered'], source_errors=errors)
        assert errors == ['lesson_attempt']
        assert len(events) == 1 and events[0].event_type == 'registered'
        assert db_session.query(User).filter_by(id=user.id).count() == 1
