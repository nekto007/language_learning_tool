"""Tests for Task 19: badges showcase on dashboard."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.study.models import Achievement, UserAchievement
from app.study.services.stats_service import StatsService


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
        code=code or f'showcase_test_{uuid.uuid4().hex[:8]}',
        name=name,
        description=description,
        icon=icon,
        xp_reward=xp_reward,
        category=category,
    )
    db_session.add(ach)
    db_session.commit()
    return ach


def _award(db_session, user_id, achievement, earned_at=None, seen_at=None):
    ua = UserAchievement(
        user_id=user_id,
        achievement_id=achievement.id,
        earned_at=earned_at or datetime.now(timezone.utc),
        seen_at=seen_at,
    )
    db_session.add(ua)
    db_session.commit()
    return ua


class TestGetBadgesShowcase:
    def test_empty_when_no_achievements(self, db_session, test_user):
        Achievement.query.delete()
        db_session.commit()

        result = StatsService.get_badges_showcase(test_user.id)

        assert result['recent'] == []
        assert result['teasers'] == []
        assert result['earned_count'] == 0
        assert result['total_count'] == 0

    def test_returns_total_count_from_all_achievements(self, db_session, test_user):
        a1 = _make_achievement(db_session)
        a2 = _make_achievement(db_session)

        result = StatsService.get_badges_showcase(test_user.id, teaser_limit=20)

        assert result['total_count'] >= 2
        assert result['earned_count'] == 0
        assert len(result['recent']) == 0
        codes = {t['code'] for t in result['teasers']}
        assert a1.code in codes or a2.code in codes

    def test_earned_badges_appear_in_recent_sorted_by_recency(self, db_session, test_user):
        ach_old = _make_achievement(db_session, name='Старый значок')
        ach_new = _make_achievement(db_session, name='Новый значок')
        base = datetime.now(timezone.utc)
        _award(db_session, test_user.id, ach_old, earned_at=base - timedelta(days=2))
        _award(db_session, test_user.id, ach_new, earned_at=base)

        result = StatsService.get_badges_showcase(test_user.id)

        assert result['earned_count'] == 2
        assert len(result['recent']) == 2
        assert result['recent'][0]['code'] == ach_new.code
        assert result['recent'][1]['code'] == ach_old.code

    def test_recent_limit_respected(self, db_session, test_user):
        badges = [_make_achievement(db_session) for _ in range(8)]
        base = datetime.now(timezone.utc)
        for i, b in enumerate(badges):
            _award(db_session, test_user.id, b, earned_at=base - timedelta(minutes=i))

        result = StatsService.get_badges_showcase(test_user.id, recent_limit=3)

        assert len(result['recent']) == 3
        assert result['earned_count'] == 8

    def test_teasers_exclude_earned_badges(self, db_session, test_user):
        ach_earned = _make_achievement(db_session, name='Получен')
        ach_unearned = _make_achievement(db_session, name='Не получен')
        _award(db_session, test_user.id, ach_earned)

        result = StatsService.get_badges_showcase(test_user.id, teaser_limit=50)

        teaser_codes = {t['code'] for t in result['teasers']}
        assert ach_earned.code not in teaser_codes
        # The unearned achievement should appear in teasers (ordered by xp_reward asc)
        assert ach_unearned.code in teaser_codes

    def test_teaser_limit_respected(self, db_session, test_user):
        for _ in range(7):
            _make_achievement(db_session)

        result = StatsService.get_badges_showcase(test_user.id, teaser_limit=2)

        assert len(result['teasers']) == 2

    def test_teasers_empty_when_all_earned(self, db_session, test_user):
        # Ensure only the badges we create exist for this test path by
        # earning every existing achievement.
        existing = Achievement.query.all()
        for ach in existing:
            existing_ua = UserAchievement.query.filter_by(
                user_id=test_user.id, achievement_id=ach.id
            ).first()
            if existing_ua is None:
                _award(db_session, test_user.id, ach)

        result = StatsService.get_badges_showcase(test_user.id)

        assert result['teasers'] == []
        assert result['earned_count'] == result['total_count']

    def test_recent_payload_includes_metadata(self, db_session, test_user):
        ach = _make_achievement(
            db_session, name='Первый прогресс', description='За первую миссию',
            icon='🎯', xp_reward=40, category='mission',
        )
        _award(db_session, test_user.id, ach)

        result = StatsService.get_badges_showcase(test_user.id)

        assert len(result['recent']) == 1
        entry = result['recent'][0]
        assert entry['code'] == ach.code
        assert entry['name'] == 'Первый прогресс'
        assert entry['description'] == 'За первую миссию'
        assert entry['icon'] == '🎯'
        assert entry['xp_reward'] == 40
        assert entry['category'] == 'mission'
        assert entry['earned_at'] is not None

    def test_isolated_per_user(self, db_session, test_user, second_user):
        ach = _make_achievement(db_session, name='Чужой значок')
        _award(db_session, second_user.id, ach)

        result = StatsService.get_badges_showcase(test_user.id)

        earned_codes = {r['code'] for r in result['recent']}
        assert ach.code not in earned_codes
        assert result['earned_count'] == 0


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


class TestDashboardBadgesShowcaseRender:
    def _get_dashboard(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=dict(MOCK_PLAN)):
            return client.get('/dashboard')

    def test_showcase_rendered_when_achievements_exist(
        self, client, app, db_session, test_user, words_module_access,
    ):
        ach = _make_achievement(
            db_session, name='Первая миссия', description='Завершил первую миссию',
            icon='🎯', xp_reward=50,
        )
        # ensure visible earned badge
        _award(
            db_session, test_user.id, ach,
            seen_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        response = self._get_dashboard(client, test_user)

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-badges' in html
        assert 'data-badges-showcase="true"' in html
        assert 'Первая миссия' in html
        # Earned badge item marker is present
        assert 'data-badge-item="earned"' in html
        # Link to full achievements page
        assert 'Все значки' in html

    def test_showcase_displays_count_earned_of_total(
        self, client, app, db_session, test_user, words_module_access,
    ):
        ach_earned = _make_achievement(db_session, name='Получен')
        ach_unearned = _make_achievement(db_session, name='Не получен')
        _award(
            db_session, test_user.id, ach_earned,
            seen_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        response = self._get_dashboard(client, test_user)
        html = response.data.decode('utf-8')

        assert 'data-badges-count="true"' in html
        # Count should include "1 из N" where N >= 2
        import re
        match = re.search(r'data-badges-count="true"[^>]*>\s*(\d+)\s+из\s+(\d+)', html)
        assert match is not None
        earned, total = int(match.group(1)), int(match.group(2))
        assert earned >= 1
        assert total >= 2
        assert total >= earned

    def test_showcase_shows_locked_teasers_for_unearned(
        self, client, app, db_session, test_user, words_module_access,
    ):
        ach = _make_achievement(db_session, name='Скрытый значок', icon='🔥', xp_reward=1)

        response = self._get_dashboard(client, test_user)
        html = response.data.decode('utf-8')

        assert 'dash-badges' in html
        assert 'data-badge-item="locked"' in html
        assert 'dash-badges__icon--locked' in html
        # Teaser shows the badge name so the user knows what to aim for
        assert 'Скрытый значок' in html

    def test_showcase_absent_when_no_achievements_in_system(
        self, client, app, db_session, test_user, words_module_access,
    ):
        # Clear all achievements so the showcase should not render.
        Achievement.query.delete()
        db_session.commit()

        response = self._get_dashboard(client, test_user)
        html = response.data.decode('utf-8')

        # The showcase markup uses data-badges-showcase as a stable hook;
        # the CSS class alone is not reliable because the stylesheet is inline.
        assert 'data-badges-showcase="true"' not in html
        assert 'data-badges-count="true"' not in html
        assert 'data-badge-item="earned"' not in html
        assert 'data-badge-item="locked"' not in html

    def test_showcase_renders_when_only_teasers_exist(
        self, client, app, db_session, test_user, words_module_access,
    ):
        # No user achievements earned, but badges exist in the system.
        _make_achievement(db_session, name='Можно получить', icon='🎖', xp_reward=1)

        response = self._get_dashboard(client, test_user)
        html = response.data.decode('utf-8')

        assert 'dash-badges' in html
        assert 'data-badge-item="locked"' in html
        assert 'Можно получить' in html
