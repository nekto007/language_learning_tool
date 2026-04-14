import pytest
from unittest.mock import patch, MagicMock


def _make_mission_plan(mission_type='progress', phases_completed=None):
    if phases_completed is None:
        phases_completed = [False, False, False]
    phases = []
    phase_defs = [
        {'phase': 'recall', 'title': 'Вспомни слова'},
        {'phase': 'learn', 'title': 'Новый урок'},
        {'phase': 'use', 'title': 'Применение'},
        {'phase': 'check', 'title': 'Подведение итогов'},
    ]
    for i, done in enumerate(phases_completed):
        d = phase_defs[i]
        phases.append({
            'id': f'ph{i}',
            'phase': d['phase'],
            'title': d['title'],
            'source_kind': 'normal_course',
            'mode': 'default',
            'required': True,
            'completed': done,
        })

    titles = {
        'progress': 'Продвигаемся вперёд',
        'repair': 'Укрепляем знания',
        'reading': 'Читаем и учимся',
    }
    reasons = {
        'progress': 'Следующий урок готов для вас',
        'repair': 'Несколько тем требуют повторения',
        'reading': 'Продолжаем чтение',
    }

    return {
        'plan_version': 'v1',
        'mission': {
            'type': mission_type,
            'title': titles[mission_type],
            'reason_code': f'{mission_type}_default',
            'reason_text': reasons[mission_type],
        },
        'primary_goal': {
            'type': 'complete_lesson',
            'title': 'Завершить урок',
            'success_criterion': '1 урок',
        },
        'primary_source': {
            'kind': 'normal_course',
            'id': '1',
            'label': 'English Basics',
        },
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
        user_module = UserModule.query.filter_by(user_id=test_user.id, module_id=words_module.id).first()
        if not user_module:
            user_module = UserModule(user_id=test_user.id, module_id=words_module.id, is_enabled=True)
            db_session.add(user_module)
            db_session.commit()
    return words_module


class TestDashboardMissionRender:
    def _get_dashboard(self, client, test_user, mission_plan):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan:
            mock_plan.return_value = mission_plan
            response = client.get('/dashboard')
        return response

    def test_mission_ui_rendered_when_flag_on(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-mission-header' in html
        assert 'data-mission-plan' in html
        assert 'Продвигаемся вперёд' in html
        assert 'Следующий урок готов для вас' in html

    def test_legacy_ui_rendered_when_flag_off(self, client, app, db_session, test_user, words_module_access):
        legacy_plan = {'steps': {}, 'next_lesson': None, 'words_due': 0}
        response = self._get_dashboard(client, test_user, legacy_plan)
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'class="dash-mission-header"' not in html
        assert 'data-mission-plan' not in html

    def test_phase_cards_rendered(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'Вспомни слова' in html
        assert 'Новый урок' in html
        assert 'Применение' in html
        assert 'data-phase-id="ph0"' in html
        assert 'data-phase-id="ph1"' in html
        assert 'data-phase-id="ph2"' in html

    def test_phase_states_correct(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-step--done' in html
        assert 'dash-step--current' in html
        assert 'dash-step--upcoming' in html

    def test_completion_banner_when_all_done(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [True, True, True])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-plan-complete' in html
        assert 'Отличная работа' in html

    def test_repair_mission_supportive_framing(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('repair', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'Укрепляем знания' in html
        assert 'Несколько тем требуют повторения' in html
        for word in ['экзамен', 'наказание', 'штраф', 'провал']:
            assert word not in html.lower()

    def test_reading_mission_rendered(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('reading', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'Читаем и учимся' in html

    def test_progress_bar_shows_correct_count(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [True, True, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert '2/3' in html

    def test_no_internal_content_type_names_shown(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        for internal_name in ['dialogue_completion_quiz', 'normal_course', 'grammar_lab', 'srs']:
            assert internal_name not in html or internal_name in str(response.data)
        assert 'source_kind' not in html

    def test_four_phases_rendered(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [True, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-id="ph3"' in html
        assert 'Подведение итогов' in html
