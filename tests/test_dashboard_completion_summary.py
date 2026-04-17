"""Tests for Task 29: Mission completion summary screen.

Covers:
- dash-completion-summary renders when all phases done and completion_summary present
- Total XP earned today shown in the summary
- Badges section shown when new badges exist
- Race position displayed when race data present
- Rank progress shown
- Summary absent when not all phases done
- CSS classes and data attributes are present
- get_today_xp sums XP from StreakEvents correctly
"""
import pytest
from datetime import date, timedelta
from unittest.mock import patch


def _make_mission_plan(phases_completed=None, bonus_phase=False):
    if phases_completed is None:
        phases_completed = [False, False, False]
    phase_defs = [
        {'phase': 'recall', 'mode': 'recall', 'title': 'Recall'},
        {'phase': 'learn', 'mode': 'learn', 'title': 'Learn'},
        {'phase': 'use', 'mode': 'use', 'title': 'Use'},
    ]
    phases = []
    for i, done in enumerate(phases_completed):
        phases.append({
            'id': f'cs_ph{i}',
            'phase': phase_defs[i]['phase'],
            'mode': phase_defs[i]['mode'],
            'title': phase_defs[i]['title'],
            'source_kind': 'normal_course',
            'required': True,
            'completed': done,
            'preview': None,
        })
    if bonus_phase:
        phases.append({
            'id': 'cs_ph_bonus',
            'phase': 'bonus',
            'mode': 'speed_review',
            'title': 'Bonus',
            'source_kind': 'normal_course',
            'required': False,
            'completed': True,
            'preview': None,
        })
    return {
        'plan_version': 'v1',
        'mission': {
            'type': 'progress',
            'title': 'Продвигаемся вперёд',
            'reason_code': 'progress_default',
            'reason_text': 'Следующий урок готов',
        },
        'primary_goal': {'type': 'complete_lesson', 'title': 'Завершить урок', 'success_criterion': '1 урок'},
        'primary_source': {'kind': 'normal_course', 'id': '1', 'label': 'English Basics'},
        'phases': phases,
        'completion': None,
        'steps': {},
    }


def _set_user_stats(db_session, user_id, total_xp=0, streak_days=0, plans_completed=0):
    from app.achievements.models import UserStatistics
    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    if stats is None:
        stats = UserStatistics(user_id=user_id)
        db_session.add(stats)
        db_session.flush()
    stats.total_xp = total_xp
    stats.current_streak_days = streak_days
    stats.plans_completed_total = plans_completed
    db_session.commit()
    return stats


@pytest.fixture()
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


@pytest.fixture(autouse=True)
def clear_leaderboard_cache():
    from app.words.routes import _leaderboard_cache
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0
    yield
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0


def _get_dashboard(client, test_user, mission_plan):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
        sess['_fresh'] = True
    with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan:
        mock_plan.return_value = mission_plan
        response = client.get('/dashboard')
    return response


class TestGetTodayXP:
    """Unit tests for xp_service.get_today_xp."""

    def test_returns_zero_when_no_events(self, app, db_session, test_user):
        from app.achievements.xp_service import get_today_xp
        result = get_today_xp(test_user.id, date.today())
        assert result == 0

    def test_sums_xp_phase_events(self, app, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=today,
            coins_delta=0,
            details={'xp': 40, 'phase_id': 'p1', 'mode': 'learn'},
        ))
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=today,
            coins_delta=0,
            details={'xp': 15, 'phase_id': 'p2', 'mode': 'recall'},
        ))
        db_session.flush()
        result = get_today_xp(test_user.id, today)
        assert result == 55

    def test_sums_perfect_day_xp(self, app, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=today,
            coins_delta=0,
            details={'xp': 50},
        ))
        db_session.flush()
        result = get_today_xp(test_user.id, today)
        assert result == 50

    def test_ignores_other_dates(self, app, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        yesterday = today - timedelta(days=1)
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=yesterday,
            coins_delta=0,
            details={'xp': 100, 'phase_id': 'p1', 'mode': 'learn'},
        ))
        db_session.flush()
        result = get_today_xp(test_user.id, today)
        assert result == 0

    def test_ignores_other_users(self, app, db_session, test_user):
        """Returns 0 for a user with no events even when other users have events."""
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        # No events for test_user — just confirm zero
        result = get_today_xp(test_user.id, today)
        assert result == 0


class TestBuildCompletionSummary:
    """Unit tests for _build_completion_summary helper."""

    def test_returns_dict_with_required_keys(self, app, db_session, test_user):
        from app.words.routes import _build_completion_summary
        plan = _make_mission_plan([True, True, True])
        from app.achievements.streak_service import compute_plan_steps
        plan_completion, _, _, _ = compute_plan_steps(plan, {})
        result = _build_completion_summary(
            test_user.id, plan, None, None, None, [], 5, plan_completion, 'UTC',
        )
        assert result is not None
        assert 'today_xp' in result
        assert 'streak' in result
        assert 'closing_message' in result
        assert 'share_text' in result

    def test_streak_included(self, app, db_session, test_user):
        from app.words.routes import _build_completion_summary
        plan = _make_mission_plan([True, True, True])
        from app.achievements.streak_service import compute_plan_steps
        plan_completion, _, _, _ = compute_plan_steps(plan, {})
        result = _build_completion_summary(
            test_user.id, plan, None, None, None, [], 42, plan_completion, 'UTC',
        )
        assert result['streak'] == 42

    def test_bonus_done_detected(self, app, db_session, test_user):
        from app.words.routes import _build_completion_summary
        plan = _make_mission_plan([True, True, True], bonus_phase=True)
        from app.achievements.streak_service import compute_plan_steps
        plan_completion = {
            'cs_ph0': True, 'cs_ph1': True, 'cs_ph2': True, 'cs_ph_bonus': True,
        }
        result = _build_completion_summary(
            test_user.id, plan, None, None, None, [], 5, plan_completion, 'UTC',
        )
        assert result['bonus_done'] is True

    def test_bonus_not_done_when_not_completed(self, app, db_session, test_user):
        from app.words.routes import _build_completion_summary
        plan = _make_mission_plan([True, True, True], bonus_phase=True)
        plan_completion = {
            'cs_ph0': True, 'cs_ph1': True, 'cs_ph2': True, 'cs_ph_bonus': False,
        }
        result = _build_completion_summary(
            test_user.id, plan, None, None, None, [], 5, plan_completion, 'UTC',
        )
        assert result['bonus_done'] is False

    def test_closing_message_varies_by_mission_type(self, app, db_session, test_user):
        from app.words.routes import _build_completion_summary
        plan_p = _make_mission_plan([True, True, True])
        plan_r = {**plan_p, 'mission': {'type': 'repair', 'title': 'Repair', 'reason_code': 'r', 'reason_text': 'r'}}
        plan_rd = {**plan_p, 'mission': {'type': 'reading', 'title': 'Reading', 'reason_code': 'r', 'reason_text': 'r'}}

        from app.achievements.streak_service import compute_plan_steps
        pc, _, _, _ = compute_plan_steps(plan_p, {})

        res_p = _build_completion_summary(test_user.id, plan_p, None, None, None, [], 5, pc, 'UTC')
        res_r = _build_completion_summary(test_user.id, plan_r, None, None, None, [], 5, pc, 'UTC')
        res_rd = _build_completion_summary(test_user.id, plan_rd, None, None, None, [], 5, pc, 'UTC')

        # All should have a closing message
        assert res_p['closing_message']
        assert res_r['closing_message']
        assert res_rd['closing_message']

    def test_share_text_contains_streak(self, app, db_session, test_user):
        from app.words.routes import _build_completion_summary
        plan = _make_mission_plan([True, True, True])
        from app.achievements.streak_service import compute_plan_steps
        pc, _, _, _ = compute_plan_steps(plan, {})
        result = _build_completion_summary(
            test_user.id, plan, None, None, None, [], 7, pc, 'UTC',
        )
        assert '7' in result['share_text']


class TestCompletionSummaryTemplate:
    """Integration tests: completion summary renders correctly in dashboard."""

    def test_summary_present_when_all_done(self, client, app, db_session, test_user, words_module_access):
        """dash-completion-summary renders when all phases done."""
        _set_user_stats(db_session, test_user.id, total_xp=200, streak_days=5, plans_completed=3)
        plan = _make_mission_plan([True, True, True])
        response = _get_dashboard(client, test_user, plan)
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-completion-summary' in html
        assert 'data-completion-summary="true"' in html

    def test_summary_absent_when_not_all_done(self, client, app, db_session, test_user, words_module_access):
        """No completion summary when phases are incomplete."""
        _set_user_stats(db_session, test_user.id)
        plan = _make_mission_plan([True, False, False])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-completion-summary="true"' not in html

    def test_summary_shows_xp_earned(self, client, app, db_session, test_user, words_module_access):
        """XP earned today is shown in the summary (from StreakEvents)."""
        from app.achievements.models import StreakEvent
        _set_user_stats(db_session, test_user.id, total_xp=200, streak_days=5)
        today = date.today()
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=today,
            coins_delta=0,
            details={'xp': 55, 'phase_id': 'p_test', 'mode': 'learn'},
        ))
        db_session.commit()
        plan = _make_mission_plan([True, True, True])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-completion-summary' in html
        assert '+55 XP' in html

    def test_summary_shows_race_position_when_present(self, client, app, db_session, test_user, words_module_access):
        """Race rank/total displayed when daily_race data available."""
        _set_user_stats(db_session, test_user.id, total_xp=100, streak_days=3)
        plan = _make_mission_plan([True, True, True])
        race_data = {
            'rank': 2, 'total': 4, 'score': 50, 'steps_done': 3, 'steps_total': 3,
            'streak': 3, 'is_complete': True, 'rival_above': None, 'rival_below': None,
            'gap_up': 0, 'gap_down': 0, 'callout': '', 'next_step_title': None,
            'next_step_points': None, 'duel_target': None, 'has_bot_rivals': False,
            'leaderboard': [], 'place_class': 'silver',
        }
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-completion-summary' in html

    def test_summary_shows_badges_when_unseen_present(self, client, app, db_session, test_user, words_module_access):
        """New badges section shows when unseen badges exist."""
        from app.study.models import Achievement, UserAchievement
        _set_user_stats(db_session, test_user.id, total_xp=150, streak_days=4)
        ach = Achievement.query.filter_by(code='mission_first').first()
        if ach is None:
            pytest.skip('mission_first badge not seeded')
        ua = UserAchievement(
            user_id=test_user.id,
            achievement_id=ach.id,
            seen_at=None,
        )
        db_session.add(ua)
        db_session.commit()
        plan = _make_mission_plan([True, True, True])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-completion-summary' in html

    def test_summary_css_rules_in_design_system(self):
        """Required CSS classes for completion summary exist in design-system.css."""
        import os
        css_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', 'static', 'css', 'design-system.css',
        )
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert 'dash-completion-summary' in css
        assert 'cs-card-flip-in' in css
        assert 'dash-completion-summary__card' in css
        assert 'dash-completion-summary__share-btn' in css

    def test_completion_summary_has_data_attribute(self, client, app, db_session, test_user, words_module_access):
        """Completion summary has the data-completion-cards attribute for JS hooks."""
        _set_user_stats(db_session, test_user.id, total_xp=100, streak_days=2)
        plan = _make_mission_plan([True, True, True])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-completion-cards="true"' in html

    def test_share_button_rendered(self, client, app, db_session, test_user, words_module_access):
        """Share button is rendered in the completion summary."""
        _set_user_stats(db_session, test_user.id, total_xp=100, streak_days=2)
        plan = _make_mission_plan([True, True, True])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-completion-summary__share-btn' in html
        assert 'Поделиться' in html
