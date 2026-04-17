"""Tests for Task 26: XP and level display on dashboard.

Covers:
- dash-xp widget renders with level badge and XP progress bar
- XP gain indicators on completed phase cards
- Streak multiplier display
- Level-up golden flash overlay
"""
import pytest
from unittest.mock import patch


def _make_mission_plan(phases_completed=None):
    if phases_completed is None:
        phases_completed = [False, False, False]
    phase_defs = [
        {'phase': 'recall', 'mode': 'recall', 'title': 'Вспомни слова'},
        {'phase': 'learn', 'mode': 'learn', 'title': 'Новый урок'},
        {'phase': 'use', 'mode': 'use', 'title': 'Применение'},
    ]
    phases = []
    for i, done in enumerate(phases_completed):
        phases.append({
            'id': f'xp_ph{i}',
            'phase': phase_defs[i]['phase'],
            'mode': phase_defs[i]['mode'],
            'title': phase_defs[i]['title'],
            'source_kind': 'normal_course',
            'required': True,
            'completed': done,
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


@pytest.fixture
def words_module_access(app, db_session, test_user):
    from app.modules.models import SystemModule, UserModule
    with app.app_context():
        words_module = SystemModule.query.filter_by(code='words').first()
        if not words_module:
            words_module = SystemModule(code='words', name='Words', description='Words module')
            db_session.add(words_module)
            db_session.flush()
        user_module = UserModule.query.filter_by(
            user_id=test_user.id, module_id=words_module.id
        ).first()
        if not user_module:
            user_module = UserModule(
                user_id=test_user.id, module_id=words_module.id, is_enabled=True
            )
            db_session.add(user_module)
            db_session.commit()
    return words_module


def _set_user_xp(db_session, user_id, total_xp, streak_days=0):
    from app.achievements.models import UserStatistics
    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    if stats is None:
        stats = UserStatistics(user_id=user_id)
        db_session.add(stats)
        db_session.flush()
    stats.total_xp = total_xp
    stats.current_streak_days = streak_days
    db_session.commit()
    return stats


def _get_dashboard(client, test_user, mission_plan):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
        sess['_fresh'] = True
    with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan:
        mock_plan.return_value = mission_plan
        response = client.get('/dashboard')
    return response


class TestDashboardXPWidget:
    """Task 26: dash-xp widget renders level badge and XP progress bar."""

    def test_xp_widget_present_on_dashboard(self, client, app, db_session, test_user, words_module_access):
        """Dashboard renders the dash-xp widget container."""
        _set_user_xp(db_session, test_user.id, 150)
        plan = _make_mission_plan([False, False, False])
        response = _get_dashboard(client, test_user, plan)
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'class="dash-xp"' in html or 'dash-xp' in html
        assert 'data-xp-widget="true"' in html

    def test_xp_widget_shows_level_badge(self, client, app, db_session, test_user, words_module_access):
        """Level badge shows current level number."""
        _set_user_xp(db_session, test_user.id, 0)
        plan = _make_mission_plan()
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-xp-level="true"' in html
        assert 'Уровень 1' in html

    def test_xp_widget_shows_level_2_at_100xp(self, client, app, db_session, test_user, words_module_access):
        """At 100 XP the widget shows Level 2."""
        _set_user_xp(db_session, test_user.id, 100)
        plan = _make_mission_plan()
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'Уровень 2' in html

    def test_xp_widget_shows_progress_bar(self, client, app, db_session, test_user, words_module_access):
        """Progress bar with data-xp-progress attribute renders."""
        _set_user_xp(db_session, test_user.id, 50)
        plan = _make_mission_plan()
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-xp-progress="true"' in html
        assert 'data-xp-pct="' in html

    def test_xp_widget_shows_xp_text(self, client, app, db_session, test_user, words_module_access):
        """XP text 'X/Y XP' is present in the widget."""
        _set_user_xp(db_session, test_user.id, 50)
        plan = _make_mission_plan()
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # 50 XP: level 1, need 100 to reach level 2. xp_in_level=50, xp_to_next=50, span=100
        assert '50/100 XP' in html

    def test_xp_widget_shows_streak_multiplier(self, client, app, db_session, test_user, words_module_access):
        """Streak multiplier element renders when streak > 0."""
        _set_user_xp(db_session, test_user.id, 0, streak_days=10)
        plan = _make_mission_plan()
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-xp-multiplier="true"' in html
        # Multiplier for 10 days: 1.0 + 10 * 0.02 = 1.2
        assert 'x1.2' in html

    def test_xp_widget_no_multiplier_without_streak(self, client, app, db_session, test_user, words_module_access):
        """When streak is 0, multiplier indicator is absent or shows x1.0."""
        _set_user_xp(db_session, test_user.id, 0, streak_days=0)
        plan = _make_mission_plan()
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # Either no multiplier badge at all, or it shows 1.0 — the test is that no >1 multiplier shown
        if 'data-xp-multiplier="true"' in html:
            assert 'x1.0' in html

    def test_xp_widget_css_rules_present(self):
        """Required CSS rules for dash-xp live in dashboard.html."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.dash-xp {' in css or '.dash-xp{' in css
        assert '.dash-xp__level' in css
        assert '.dash-xp__bar' in css
        assert '.dash-xp__bar-fill' in css


class TestDashboardXPGainOnPhases:
    """Task 26: XP gain indicators on completed phase cards."""

    def test_done_phase_shows_xp_gain(self, client, app, db_session, test_user, words_module_access):
        """Completed (done) phase cards display a +N XP indicator."""
        _set_user_xp(db_session, test_user.id, 0)
        plan = _make_mission_plan([True, False, False])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-xp="true"' in html
        # recall phase XP = 15
        assert '+15 XP' in html

    def test_undone_phase_no_xp_gain(self, client, app, db_session, test_user, words_module_access):
        """Non-completed phases do not display XP gain indicators."""
        _set_user_xp(db_session, test_user.id, 0)
        plan = _make_mission_plan([False, False, False])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-xp="true"' not in html

    def test_learn_phase_done_shows_correct_xp(self, client, app, db_session, test_user, words_module_access):
        """Learn phase shows +40 XP when completed."""
        _set_user_xp(db_session, test_user.id, 0)
        plan = _make_mission_plan([True, True, False])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert '+40 XP' in html


class TestDashboardLevelUpCelebration:
    """Task 26: level-up golden flash overlay when user levels up."""

    def test_levelup_overlay_present_when_leveled_up(self, client, app, db_session, test_user, words_module_access):
        """When xp_level_up is set in streak result, level-up overlay element renders."""
        _set_user_xp(db_session, test_user.id, 0)
        plan = _make_mission_plan([False, False, False])

        fake_level_up = {'new_level': 3, 'xp': 300}

        with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan, \
             patch('app.achievements.streak_service.process_streak_on_activity') as mock_streak:
            mock_plan.return_value = plan
            mock_streak.return_value = {
                'streak_status': {'streak': 5},
                'required_steps': 1,
                'streak_repaired': False,
                'steps_done': 0,
                'steps_total': 3,
                'milestone_reward': None,
                'rank_up': None,
                'xp_level_up': fake_level_up,
            }
            with client.session_transaction() as sess:
                sess['_user_id'] = str(test_user.id)
                sess['_fresh'] = True
            response = client.get('/dashboard')

        html = response.data.decode('utf-8')
        assert 'data-xp-levelup="true"' in html
        assert '3' in html  # new level number shown

    def test_levelup_overlay_absent_without_level_up(self, client, app, db_session, test_user, words_module_access):
        """When no level-up occurred, the overlay element is absent."""
        _set_user_xp(db_session, test_user.id, 0)
        plan = _make_mission_plan([False, False, False])
        response = _get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-xp-levelup="true"' not in html

    def test_levelup_overlay_css_present(self):
        """Level-up golden flash CSS keyframe and class rules live in dashboard.html."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '@keyframes xpLevelUpFlash' in css
        assert '.dash-xp-levelup' in css
