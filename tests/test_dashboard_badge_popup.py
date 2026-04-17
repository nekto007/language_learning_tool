"""Tests for Task 18: badge award popup on dashboard."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.achievements.services import AchievementService
from app.study.models import Achievement, UserAchievement


MOCK_PLAN = {
    'next_lesson': None,
    'grammar_topic': None,
    'words_due': 0,
    'has_any_words': False,
    'book_to_read': None,
    'suggested_books': [],
    'book_course_lesson': None,
    'book_course_done_today': False,
    'onboarding': None,
    'bonus': [],
    'mission': None,
    'steps': {},
}


def _make_achievement(db_session, *, code=None, name='Тестовая награда',
                      description='Описание', icon='🏅', xp_reward=25,
                      category='mission'):
    ach = Achievement(
        code=code or f'test_badge_{uuid.uuid4().hex[:8]}',
        name=name,
        description=description,
        icon=icon,
        xp_reward=xp_reward,
        category=category,
    )
    db_session.add(ach)
    db_session.commit()
    return ach


def _award(db_session, user_id, achievement, seen_at=None, earned_at=None):
    ua = UserAchievement(
        user_id=user_id,
        achievement_id=achievement.id,
        earned_at=earned_at or datetime.now(timezone.utc),
        seen_at=seen_at,
    )
    db_session.add(ua)
    db_session.commit()
    return ua


class TestGetUnseenBadges:
    def test_returns_empty_when_no_badges(self, db_session, test_user):
        assert AchievementService.get_unseen_badges(test_user.id) == []

    def test_returns_freshly_earned_badge(self, db_session, test_user):
        ach = _make_achievement(db_session, name='Первый день', icon='🎯', xp_reward=50)
        _award(db_session, test_user.id, ach)

        result = AchievementService.get_unseen_badges(test_user.id)

        assert len(result) == 1
        entry = result[0]
        assert entry['code'] == ach.code
        assert entry['name'] == 'Первый день'
        assert entry['icon'] == '🎯'
        assert entry['xp_reward'] == 50
        assert 'user_achievement_id' in entry

    def test_skips_already_seen_badges(self, db_session, test_user):
        ach = _make_achievement(db_session)
        seen_time = datetime.now(timezone.utc) - timedelta(hours=1)
        _award(db_session, test_user.id, ach, seen_at=seen_time)

        assert AchievementService.get_unseen_badges(test_user.id) == []

    def test_only_returns_badges_for_given_user(self, db_session, test_user, second_user):
        ach = _make_achievement(db_session)
        _award(db_session, second_user.id, ach)

        assert AchievementService.get_unseen_badges(test_user.id) == []
        other = AchievementService.get_unseen_badges(second_user.id)
        assert len(other) == 1

    def test_ordered_oldest_first(self, db_session, test_user):
        old = _make_achievement(db_session, code=f'old_{uuid.uuid4().hex[:6]}')
        new = _make_achievement(db_session, code=f'new_{uuid.uuid4().hex[:6]}')
        base = datetime.now(timezone.utc)
        _award(db_session, test_user.id, old, earned_at=base - timedelta(hours=2))
        _award(db_session, test_user.id, new, earned_at=base)

        result = AchievementService.get_unseen_badges(test_user.id)

        assert [r['code'] for r in result] == [old.code, new.code]


class TestMarkBadgesSeen:
    def test_marks_all_unseen_when_ids_not_given(self, db_session, test_user):
        a1 = _make_achievement(db_session, code=f'a_{uuid.uuid4().hex[:6]}')
        a2 = _make_achievement(db_session, code=f'b_{uuid.uuid4().hex[:6]}')
        _award(db_session, test_user.id, a1)
        _award(db_session, test_user.id, a2)

        updated = AchievementService.mark_badges_seen(test_user.id)

        assert updated == 2
        assert AchievementService.get_unseen_badges(test_user.id) == []

    def test_marks_only_given_ids(self, db_session, test_user):
        a1 = _make_achievement(db_session, code=f'a_{uuid.uuid4().hex[:6]}')
        a2 = _make_achievement(db_session, code=f'b_{uuid.uuid4().hex[:6]}')
        ua1 = _award(db_session, test_user.id, a1)
        _award(db_session, test_user.id, a2)

        updated = AchievementService.mark_badges_seen(test_user.id, [ua1.id])

        assert updated == 1
        remaining = AchievementService.get_unseen_badges(test_user.id)
        assert len(remaining) == 1
        assert remaining[0]['code'] == a2.code

    def test_empty_id_list_is_noop(self, db_session, test_user):
        ach = _make_achievement(db_session)
        _award(db_session, test_user.id, ach)

        updated = AchievementService.mark_badges_seen(test_user.id, [])

        assert updated == 0
        assert len(AchievementService.get_unseen_badges(test_user.id)) == 1

    def test_already_seen_badges_are_not_restamped(self, db_session, test_user):
        ach = _make_achievement(db_session)
        original_seen_time = datetime.now(timezone.utc) - timedelta(days=2)
        ua = _award(db_session, test_user.id, ach, seen_at=original_seen_time)

        updated = AchievementService.mark_badges_seen(test_user.id)

        assert updated == 0
        db_session.refresh(ua)
        # The seen_at stamp must be unchanged.
        assert ua.seen_at is not None
        assert abs((ua.seen_at - original_seen_time.replace(tzinfo=None)).total_seconds()) < 2


@pytest.fixture
def words_module_access(app, db_session, test_user):
    from app.modules.models import SystemModule, UserModule
    with app.app_context():
        words_module = SystemModule.query.filter_by(code='words').first()
        if not words_module:
            words_module = SystemModule(code='words', name='Words', description='Words')
            db_session.add(words_module)
            db_session.flush()
        user_module = UserModule.query.filter_by(
            user_id=test_user.id, module_id=words_module.id,
        ).first()
        if not user_module:
            db_session.add(UserModule(
                user_id=test_user.id, module_id=words_module.id, is_enabled=True,
            ))
            db_session.commit()
    return words_module


@pytest.fixture(autouse=True)
def _clear_leaderboard_cache():
    from app.words.routes import _leaderboard_cache
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0
    yield
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0


class TestDashboardBadgePopupRender:
    def _get_dashboard(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=dict(MOCK_PLAN)):
            return client.get('/dashboard')

    def test_popup_rendered_when_unseen_badge_exists(
        self, client, app, db_session, test_user, words_module_access,
    ):
        ach = _make_achievement(
            db_session, code=f'popup_test_{uuid.uuid4().hex[:6]}',
            name='Первая миссия', description='Завершил первую миссию',
            icon='🎯', xp_reward=60,
        )
        _award(db_session, test_user.id, ach)

        response = self._get_dashboard(client, test_user)

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-badge-popup' in html
        assert 'Первая миссия' in html
        assert 'Завершил первую миссию' in html
        assert '+60 XP' in html

    def test_popup_absent_when_no_unseen_badges(
        self, client, app, db_session, test_user, words_module_access,
    ):
        response = self._get_dashboard(client, test_user)

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-badge-popup' not in html

    def test_popup_absent_for_already_seen_badges(
        self, client, app, db_session, test_user, words_module_access,
    ):
        ach = _make_achievement(db_session, code=f'seen_test_{uuid.uuid4().hex[:6]}')
        _award(
            db_session, test_user.id, ach,
            seen_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        response = self._get_dashboard(client, test_user)

        html = response.data.decode('utf-8')
        assert 'dash-badge-popup' not in html

    def test_dashboard_visit_marks_badges_seen(
        self, client, app, db_session, test_user, words_module_access,
    ):
        ach = _make_achievement(db_session, code=f'seen_mark_{uuid.uuid4().hex[:6]}')
        ua = _award(db_session, test_user.id, ach)
        assert ua.seen_at is None

        first = self._get_dashboard(client, test_user)
        assert first.status_code == 200
        assert 'dash-badge-popup' in first.data.decode('utf-8')

        db_session.expire_all()
        refreshed = UserAchievement.query.get(ua.id)
        assert refreshed.seen_at is not None

        second = self._get_dashboard(client, test_user)
        assert 'dash-badge-popup' not in second.data.decode('utf-8')
