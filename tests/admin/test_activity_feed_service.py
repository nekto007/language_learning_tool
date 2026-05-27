"""Tests for activity_feed_service — all 5 sources, outer-join dedup, XP reading, pagination."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.auth.models import User


def _make_user(db_session):
    username = f'af_{uuid.uuid4().hex[:8]}'
    user = User(username=username, email=f'{username}@test.com', active=True)
    user.set_password('pass')
    db_session.add(user)
    db_session.flush()
    return user


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Source: lesson_completed
# ---------------------------------------------------------------------------

class TestFetchLessonCompleted:
    @pytest.mark.smoke
    def test_lesson_completed_event_appears(self, app, db_session):
        from app.admin.services.activity_feed_service import get_recent_events
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

        user = _make_user(db_session)
        code = uuid.uuid4().hex[:2].upper()
        level = CEFRLevel(code=code, name='Test', description='Test', order=88)
        db_session.add(level)
        db_session.flush()
        module = Module(level_id=level.id, number=1, title='Mod')
        db_session.add(module)
        db_session.flush()
        lesson = Lessons(module_id=module.id, number=1, title='My Lesson', type='text', order=1)
        db_session.add(lesson)
        db_session.flush()

        now = _now()
        lp = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            completed_at=now,
            last_activity=now,
        )
        db_session.add(lp)
        db_session.commit()

        events = get_recent_events(db_session, limit=10, event_types=['lesson_completed'])
        types = [e.event_type for e in events]
        user_ids = [e.user_id for e in events]
        assert 'lesson_completed' in types
        assert user.id in user_ids

    def test_lesson_score_included_in_description(self, app, db_session):
        from app.admin.services.activity_feed_service import get_recent_events
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

        user = _make_user(db_session)
        code = uuid.uuid4().hex[:2].upper()
        level = CEFRLevel(code=code, name='Test2', description='T', order=87)
        db_session.add(level)
        db_session.flush()
        module = Module(level_id=level.id, number=1, title='M2')
        db_session.add(module)
        db_session.flush()
        lesson = Lessons(module_id=module.id, number=1, title='Scored Lesson', type='text', order=1)
        db_session.add(lesson)
        db_session.flush()

        now = _now()
        lp = LessonProgress(
            user_id=user.id, lesson_id=lesson.id,
            status='completed', score=85.0,
            completed_at=now, last_activity=now,
        )
        db_session.add(lp)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['lesson_completed']
        )
        assert len(events) >= 1
        # Score should appear in description
        assert '85%' in events[0].description


# ---------------------------------------------------------------------------
# Source: achievement_granted — outer join dedup
# ---------------------------------------------------------------------------

class TestFetchAchievements:
    @pytest.mark.smoke
    def test_achievement_event_appears(self, app, db_session):
        from app.admin.services.activity_feed_service import get_recent_events
        from app.study.models import Achievement, UserAchievement

        user = _make_user(db_session)
        code = f'test_{uuid.uuid4().hex[:6]}'
        ach = Achievement(code=code, name='Test Badge', icon='🏆')
        db_session.add(ach)
        db_session.flush()

        now = _now()
        ua = UserAchievement(user_id=user.id, achievement_id=ach.id, earned_at=now)
        db_session.add(ua)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['achievement_granted']
        )
        assert len(events) >= 1
        assert 'Test Badge' in events[0].description

    def test_multiple_achievements_no_duplicate_rows(self, app, db_session):
        """Outer join to Achievement should not multiply rows — one UA → one event."""
        from app.admin.services.activity_feed_service import get_recent_events
        from app.study.models import Achievement, UserAchievement

        user = _make_user(db_session)
        now = _now()
        for i in range(3):
            code = f'multi_{uuid.uuid4().hex[:6]}'
            ach = Achievement(code=code, name=f'Badge {i}', icon='🏆')
            db_session.add(ach)
            db_session.flush()
            ua = UserAchievement(
                user_id=user.id, achievement_id=ach.id,
                earned_at=now - timedelta(seconds=i)
            )
            db_session.add(ua)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=100, user_id=user.id, event_types=['achievement_granted']
        )
        # Must be exactly 3, not more (no cartesian product)
        assert len(events) == 3

    def test_user_filter_restricts_to_user(self, app, db_session):
        """user_id filter returns only that user's achievements."""
        from app.admin.services.activity_feed_service import get_recent_events
        from app.study.models import Achievement, UserAchievement

        user1 = _make_user(db_session)
        user2 = _make_user(db_session)
        now = _now()
        for user in (user1, user2):
            code = f'filt_{uuid.uuid4().hex[:6]}'
            ach = Achievement(code=code, name=f'Badge {code}', icon='🏆')
            db_session.add(ach)
            db_session.flush()
            ua = UserAchievement(user_id=user.id, achievement_id=ach.id, earned_at=now)
            db_session.add(ua)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user1.id, event_types=['achievement_granted']
        )
        assert all(e.user_id == user1.id for e in events)


# ---------------------------------------------------------------------------
# Source: xp_awarded — reads details['xp'] not coins_delta
# ---------------------------------------------------------------------------

class TestFetchXpEvents:
    @pytest.mark.smoke
    def test_xp_read_from_details_xp_field(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id,
            event_type='xp_curriculum_lesson',
            coins_delta=0,
            event_date=date.today(),
            details={'xp': 42},
            created_at=now,
        )
        db_session.add(se)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['xp_awarded']
        )
        assert len(events) >= 1
        assert '+42 XP' in events[0].description

    def test_xp_falls_back_to_coins_delta_when_no_details_xp(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id,
            event_type='xp_srs_global',
            coins_delta=15,
            event_date=date.today(),
            details=None,
            created_at=now,
        )
        db_session.add(se)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['xp_awarded']
        )
        assert len(events) >= 1
        assert '+15 XP' in events[0].description

    def test_xp_prefers_details_xp_over_coins_delta(self, app, db_session):
        """details['xp'] takes priority over coins_delta (coins_delta always 0 in practice)."""
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id,
            event_type='xp_prefer_test',
            coins_delta=5,          # should be ignored
            event_date=date.today(),
            details={'xp': 20},     # should be used
            created_at=now,
        )
        db_session.add(se)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['xp_awarded']
        )
        assert len(events) >= 1
        assert '+20 XP' in events[0].description
        assert '+5 XP' not in events[0].description

    def test_non_xp_streak_events_excluded(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id,
            event_type='streak_repair',  # does not match xp_% pattern
            coins_delta=10,
            event_date=date.today(),
            created_at=now,
        )
        db_session.add(se)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['xp_awarded']
        )
        # streak_repair should not appear as xp_awarded
        user_xp_events = [e for e in events if e.user_id == user.id]
        assert len(user_xp_events) == 0


# ---------------------------------------------------------------------------
# Source: day_secured
# ---------------------------------------------------------------------------

class TestFetchDaySecured:
    @pytest.mark.smoke
    def test_day_secured_event_appears(self, app, db_session):
        from app.admin.services.activity_feed_service import get_recent_events
        from app.daily_plan.models import DailyPlanLog

        user = _make_user(db_session)
        now = _now()
        log = DailyPlanLog(
            user_id=user.id,
            plan_date=date.today(),
            secured_at=now,
        )
        db_session.add(log)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['day_secured']
        )
        assert len(events) >= 1
        assert events[0].event_type == 'day_secured'

    def test_unsecured_plan_log_excluded(self, app, db_session):
        from app.admin.services.activity_feed_service import get_recent_events
        from app.daily_plan.models import DailyPlanLog

        user = _make_user(db_session)
        log = DailyPlanLog(
            user_id=user.id,
            plan_date=date.today(),
            secured_at=None,
        )
        db_session.add(log)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['day_secured']
        )
        user_events = [e for e in events if e.user_id == user.id]
        assert len(user_events) == 0


# ---------------------------------------------------------------------------
# Source: admin_action
# ---------------------------------------------------------------------------

class TestFetchAdminActions:
    @pytest.mark.smoke
    def test_admin_action_event_appears(self, app, db_session):
        from app.admin.audit import AdminAuditLog
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        log = AdminAuditLog(
            admin_id=user.id,
            action='delete_word',
            target_type='Word',
            target_id=123,
            created_at=now,
        )
        db_session.add(log)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['admin_action']
        )
        assert len(events) >= 1
        assert events[0].event_type == 'admin_action'
        assert 'delete_word' in events[0].description

    def test_admin_action_null_target_renders_safely(self, app, db_session):
        from app.admin.audit import AdminAuditLog
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        log = AdminAuditLog(
            admin_id=user.id,
            action='clear_cache',
            target_type=None,
            target_id=None,
            created_at=now,
        )
        db_session.add(log)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=10, user_id=user.id, event_types=['admin_action']
        )
        user_events = [e for e in events if e.user_id == user.id]
        assert len(user_events) >= 1
        # Description should not blow up with None values
        assert 'clear_cache' in user_events[0].description


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    @pytest.mark.smoke
    def test_limit_restricts_results(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        for i in range(10):
            se = StreakEvent(
                user_id=user.id,
                event_type='xp_test_limit',
                coins_delta=0,
                event_date=date.today(),
                details={'xp': i},
                created_at=now - timedelta(seconds=i),
            )
            db_session.add(se)
        db_session.commit()

        events = get_recent_events(
            db_session, limit=3, user_id=user.id, event_types=['xp_awarded']
        )
        assert len(events) <= 3

    def test_offset_skips_events(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        base_time = _now()
        for i in range(6):
            se = StreakEvent(
                user_id=user.id,
                event_type='xp_offset_test',
                coins_delta=0,
                event_date=date.today(),
                details={'xp': i * 10},
                created_at=base_time - timedelta(seconds=i),
            )
            db_session.add(se)
        db_session.commit()

        all_events = get_recent_events(
            db_session, limit=6, offset=0, user_id=user.id, event_types=['xp_awarded']
        )
        offset_events = get_recent_events(
            db_session, limit=3, offset=3, user_id=user.id, event_types=['xp_awarded']
        )

        # Offset should give events that were NOT in the first 3
        assert len(all_events) >= 4
        assert len(offset_events) >= 1
        # The first event in offset_events should match the 4th in all_events
        if len(all_events) >= 4 and len(offset_events) >= 1:
            assert all_events[3].description == offset_events[0].description

    def test_mixed_sources_merge_and_sort_correctly(self, app, db_session):
        """Events from all 5 sources interleave correctly when sorted by timestamp."""
        from app.achievements.models import StreakEvent
        from app.admin.audit import AdminAuditLog
        from app.admin.services.activity_feed_service import get_recent_events
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
        from app.daily_plan.models import DailyPlanLog
        from app.study.models import Achievement, UserAchievement

        user = _make_user(db_session)
        base = _now()

        # lesson_completed (oldest)
        code = uuid.uuid4().hex[:2].upper()
        level = CEFRLevel(code=code, name='T', description='T', order=77)
        db_session.add(level)
        db_session.flush()
        module = Module(level_id=level.id, number=1, title='M')
        db_session.add(module)
        db_session.flush()
        lesson = Lessons(module_id=module.id, number=1, title='L', type='text', order=1)
        db_session.add(lesson)
        db_session.flush()
        lp = LessonProgress(
            user_id=user.id, lesson_id=lesson.id,
            status='completed',
            completed_at=base - timedelta(seconds=40),
            last_activity=base - timedelta(seconds=40),
        )
        db_session.add(lp)

        # achievement_granted
        ach = Achievement(code=f'mix_{uuid.uuid4().hex[:6]}', name='Mix Badge', icon='🏆')
        db_session.add(ach)
        db_session.flush()
        ua = UserAchievement(
            user_id=user.id, achievement_id=ach.id,
            earned_at=base - timedelta(seconds=30),
        )
        db_session.add(ua)

        # xp_awarded
        se = StreakEvent(
            user_id=user.id, event_type='xp_mixed_test',
            coins_delta=0, event_date=date.today(),
            details={'xp': 10},
            created_at=base - timedelta(seconds=20),
        )
        db_session.add(se)

        # day_secured
        plan = DailyPlanLog(
            user_id=user.id, plan_date=date.today(),
            secured_at=base - timedelta(seconds=10),
        )
        db_session.add(plan)

        # admin_action (most recent)
        audit = AdminAuditLog(
            admin_id=user.id, action='mixed_test_action',
            created_at=base,
        )
        db_session.add(audit)

        db_session.commit()

        events = get_recent_events(
            db_session, limit=100, user_id=user.id
        )
        user_events = [e for e in events if e.user_id == user.id]
        types = [e.event_type for e in user_events]

        assert 'lesson_completed' in types
        assert 'achievement_granted' in types
        assert 'xp_awarded' in types
        assert 'day_secured' in types
        assert 'admin_action' in types

        # Events must be sorted newest first
        for i in range(len(user_events) - 1):
            assert user_events[i].timestamp >= user_events[i + 1].timestamp

    def test_event_type_filter_excludes_other_types(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        now = _now()
        se = StreakEvent(
            user_id=user.id, event_type='xp_filter_test',
            coins_delta=0, event_date=date.today(),
            details={'xp': 5}, created_at=now,
        )
        db_session.add(se)
        db_session.commit()

        # Request only lesson_completed — xp_awarded should not appear
        events = get_recent_events(
            db_session, limit=20, user_id=user.id, event_types=['lesson_completed']
        )
        assert all(e.event_type == 'lesson_completed' for e in events)

    def test_date_filter_restricts_events(self, app, db_session):
        from app.achievements.models import StreakEvent
        from app.admin.services.activity_feed_service import get_recent_events

        user = _make_user(db_session)
        old_time = datetime(2020, 1, 1, 12, 0, 0)
        se = StreakEvent(
            user_id=user.id, event_type='xp_date_test',
            coins_delta=0, event_date=date(2020, 1, 1),
            details={'xp': 7}, created_at=old_time,
        )
        db_session.add(se)
        db_session.commit()

        from datetime import date as date_cls
        events = get_recent_events(
            db_session, limit=20, user_id=user.id, event_types=['xp_awarded'],
            date_from=datetime(2024, 1, 1),
        )
        user_events = [e for e in events if e.user_id == user.id]
        # 2020 event should be excluded
        assert all(e.timestamp >= datetime(2024, 1, 1) for e in user_events)
