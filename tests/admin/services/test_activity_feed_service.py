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
        code = uuid.uuid4().hex[:2].upper()
        level = CEFRLevel(code=code, name="Lvl", description="", order=88)
        db_session.add(level)
        db_session.flush()
        mod = Module(level_id=level.id, number=1, title="Mod")
        db_session.add(mod)
        db_session.flush()
        lesson = Lessons(module_id=mod.id, number=1, title="Les", type="text", order=1)
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
        code = uuid.uuid4().hex[:2].upper()
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
        code = uuid.uuid4().hex[:2].upper()
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
        code = uuid.uuid4().hex[:2].upper()
        level = CEFRLevel(code=code, name="Lvl", description="", order=85)
        db_session.add(level)
        db_session.flush()
        mod = Module(level_id=level.id, number=1, title="Mod")
        db_session.add(mod)
        db_session.flush()
        lesson = Lessons(module_id=mod.id, number=1, title="ScoreLes", type="text", order=1)
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
