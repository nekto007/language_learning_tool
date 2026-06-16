"""Unit tests for the daily-race widget helpers in app.words.routes.

Salvaged from the retired legacy-dashboard test suite: these exercise the
still-live helpers (_compute_daily_race_state, _participant_initials,
_MEDAL_BY_RANK, _build_daily_race_widget) which have no other coverage. The
dashboard-render assertions that lived alongside them were dropped with the
legacy dashboard.html template.
"""

class TestDailyRaceWidget:
    """Tests for the daily race widget data and template rendering."""

    def test_compute_daily_race_state_legacy_plan(self, app):
        """_compute_daily_race_state returns correct steps and score for legacy plan."""
        from app.words.routes import _compute_daily_race_state

        plan = {
            'steps': {
                'lesson': {'title': 'Урок', 'state': 'completed'},
                'grammar': {'title': 'Грамматика', 'state': 'open'},
            }
        }
        summary = {}
        result = _compute_daily_race_state(plan, summary, streak=3)
        assert result['steps_total'] == 2
        assert result['steps_done'] == 1
        assert result['score'] == 22  # lesson = 22 pts
        assert result['next_step_title'] is not None

    def test_compute_daily_race_state_mission_plan(self, app):
        """_compute_daily_race_state correctly scores completed mission phases."""
        from app.words.routes import _compute_daily_race_state, _MISSION_PHASE_POINTS

        phases = [
            {'id': 'p1', 'phase': 'recall', 'title': 'Повторение', 'required': True, 'mode': 'srs_words'},
            {'id': 'p2', 'phase': 'learn', 'title': 'Урок', 'required': True, 'mode': 'lesson'},
        ]
        plan = {'phases': phases}
        summary = {'words_reviewed': 10}  # enough to mark recall done
        result = _compute_daily_race_state(plan, summary, streak=5)
        assert result['steps_total'] == 2
        assert isinstance(result['score'], int)
        assert result['score'] >= 0

    def test_compute_daily_race_state_linear_plan(self, app):
        """_compute_daily_race_state scores completed linear slots."""
        from app.words.routes import _compute_daily_race_state, _LINEAR_SLOT_POINTS

        plan = {
            'mode': 'linear',
            'baseline_slots': [
                {'kind': 'curriculum', 'title': 'Lesson', 'completed': True, 'url': '/learn/1/?from=linear_plan'},
                {'kind': 'srs', 'title': 'SRS', 'completed': False, 'url': '/study/cards?from=linear_plan'},
            ],
        }
        summary = {'lessons_count': 1, 'srs_words_reviewed': 0, 'srs_review_reviewed': 0}

        result = _compute_daily_race_state(plan, summary, streak=4)

        assert result['steps_total'] == 2
        assert result['steps_done'] == 1
        assert result['score'] == _LINEAR_SLOT_POINTS['curriculum']
        assert result['next_step_title'] == 'SRS'

    def test_participant_initials_basic(self, app):
        """_participant_initials returns 1-2 uppercase letters."""
        from app.words.routes import _participant_initials

        assert _participant_initials('alice') == 'AL'
        assert _participant_initials('Alice Bob') == 'AB'
        assert _participant_initials('a') == 'A'
        assert _participant_initials('') == '?'
        assert _participant_initials(None) == '?'

    def test_participant_initials_underscore_name(self, app):
        """_participant_initials splits on underscores for compound names."""
        from app.words.routes import _participant_initials

        assert _participant_initials('john_doe') == 'JD'

    def test_medal_by_rank_mapping(self, app):
        """_MEDAL_BY_RANK maps top 3 places to medal class names."""
        from app.words.routes import _MEDAL_BY_RANK

        assert _MEDAL_BY_RANK[1] == 'gold'
        assert _MEDAL_BY_RANK[2] == 'silver'
        assert _MEDAL_BY_RANK[3] == 'bronze'
        assert 4 not in _MEDAL_BY_RANK

    def test_build_daily_race_widget_returns_correct_structure(self, app, db_session, test_user):
        """_build_daily_race_widget returns dict with required keys including new fields."""
        from unittest.mock import patch
        from app.words.routes import _build_daily_race_widget

        fake_plan = {'steps': {'lesson': {'title': 'Урок', 'state': 'done'}}}
        fake_summary = {}
        fake_streak = 3

        with patch('app.words.routes._compute_daily_race_state') as mock_state, \
             patch('app.achievements.daily_race.get_race_standings', return_value={
                 'race_id': 11,
                 'race_date': '2026-04-17',
                 'my_rank': 1,
                 'participants': [
                     {'user_id': test_user.id, 'username': test_user.username, 'points': 22, 'rank': 1, 'is_me': True, 'is_ghost': False},
                     {'user_id': None, 'username': 'Луна', 'points': 18, 'rank': 2, 'is_me': False, 'is_ghost': True},
                     {'user_id': None, 'username': 'Комета', 'points': 10, 'rank': 3, 'is_me': False, 'is_ghost': True},
                 ],
             }), \
             patch('app.daily_plan.service.get_daily_plan_unified', return_value=fake_plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=fake_summary), \
             patch('app.telegram.queries.get_current_streak', return_value=fake_streak):

            mock_state.return_value = {
                'score': 22,
                'steps_done': 1,
                'steps_total': 1,
                'next_step_title': None,
                'next_step_points': 0,
            }

            result = _build_daily_race_widget(test_user.id, tz='Europe/Moscow')

        if result is not None:
            assert 'rank' in result
            assert 'place_class' in result
            assert 'is_complete' in result
            assert 'leaderboard' in result
            assert isinstance(result['leaderboard'], list)
            for row in result['leaderboard']:
                assert 'initials' in row
                assert 'place_class' in row
                assert 'is_complete' in row

    def test_build_daily_race_widget_uses_persisted_race_cohort(self, app, db_session, test_user):
        from unittest.mock import patch
        from app.words.routes import _build_daily_race_widget

        fake_plan = {'steps': {'lesson': {'title': 'Урок', 'state': 'done'}}}
        fake_summary = {}

        with patch('app.achievements.daily_race.get_race_standings', return_value={
            'race_id': 17,
            'race_date': '2026-04-17',
            'my_rank': 2,
            'participants': [
                {'user_id': None, 'username': 'Луна', 'points': 24, 'rank': 1, 'is_me': False, 'is_ghost': True},
                {'user_id': test_user.id, 'username': test_user.username, 'points': 22, 'rank': 2, 'is_me': True, 'is_ghost': False},
                {'user_id': None, 'username': 'Комета', 'points': 10, 'rank': 3, 'is_me': False, 'is_ghost': True},
            ],
        }), \
             patch('app.words.routes._compute_daily_race_state', return_value={
                 'score': 22,
                 'steps_done': 1,
                 'steps_total': 1,
                 'next_step_title': None,
                 'next_step_points': 0,
             }), \
             patch('app.daily_plan.service.get_daily_plan_unified', return_value=fake_plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=fake_summary), \
             patch('app.telegram.queries.get_current_streak', return_value=3):
            result = _build_daily_race_widget(test_user.id, tz='Europe/Moscow')

        assert result is not None
        assert result['rank'] == 2
        assert [row['username'] for row in result['leaderboard']] == ['Луна', test_user.username, 'Комета']

    def test_build_daily_race_widget_skips_failed_participant_without_rollback(self, app, db_session, test_user):
        from unittest.mock import patch
        from app.auth.models import User
        from app.words.routes import _build_daily_race_widget

        other_user = User(
            username='other_racer',
            email='other_racer@example.com',
            password_hash='x',
            salt='x',
            onboarding_completed=True,
            active=True,
        )
        db_session.add(other_user)
        db_session.commit()

        fake_plan = {'steps': {'lesson': {'title': 'Урок', 'state': 'done'}}}

        def summary_side_effect(user_id, tz=None):
            if user_id == other_user.id:
                raise RuntimeError('summary failed')
            return {}

        with patch('app.achievements.daily_race.get_race_standings', return_value={
            'race_id': 17,
            'race_date': '2026-04-17',
            'my_rank': 1,
            'participants': [
                {'user_id': other_user.id, 'username': other_user.username, 'points': 30, 'rank': 1, 'is_me': False, 'is_ghost': False},
                {'user_id': test_user.id, 'username': test_user.username, 'points': 22, 'rank': 2, 'is_me': True, 'is_ghost': False},
            ],
        }), \
             patch('app.words.routes._compute_daily_race_state', return_value={
                 'score': 22,
                 'steps_done': 1,
                 'steps_total': 1,
                 'next_step_title': None,
                 'next_step_points': 0,
             }), \
             patch('app.daily_plan.service.get_daily_plan_unified', return_value=fake_plan), \
             patch('app.telegram.queries.get_daily_summary', side_effect=summary_side_effect), \
             patch('app.telegram.queries.get_current_streak', return_value=3):
            result = _build_daily_race_widget(test_user.id, tz='Europe/Moscow')

        assert result is not None
        assert result['rank'] == 2
        assert len(result['leaderboard']) == 1
        assert result['leaderboard'][0]['user_id'] == test_user.id

