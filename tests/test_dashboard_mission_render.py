import pytest
from unittest.mock import patch, MagicMock


def _make_mission_plan(mission_type='progress', phases_completed=None, previews=None):
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
        phase_dict = {
            'id': f'ph{i}',
            'phase': d['phase'],
            'title': d['title'],
            'source_kind': 'normal_course',
            'mode': 'default',
            'required': True,
            'completed': done,
            'preview': None,
        }
        if previews is not None and i < len(previews):
            phase_dict['preview'] = previews[i]
        phases.append(phase_dict)

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
        visible_text_markers = ['dialogue_completion_quiz']
        for internal_name in visible_text_markers:
            assert internal_name not in html, f"Internal name '{internal_name}' leaked into dashboard HTML"
        assert 'source_kind' not in html

    def test_four_phases_rendered(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [True, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-id="ph3"' in html
        assert 'Подведение итогов' in html

    def test_phase_preview_chips_render(self, client, app, db_session, test_user, words_module_access):
        """Task 5: preview chips with item_count and estimated_minutes render on phase cards."""
        previews = [
            {'item_count': 14, 'content_title': 'Повторение карточек', 'estimated_minutes': 3},
            {'item_count': None, 'content_title': 'Present Perfect', 'estimated_minutes': 10},
            {'item_count': None, 'content_title': None, 'estimated_minutes': None},
        ]
        plan = _make_mission_plan('progress', [False, False, False], previews=previews)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')

        # Recall phase: content title shown with action prefix, count and time chips
        assert 'dash-step__preview' in html
        assert 'data-phase-preview="true"' in html
        assert 'Что сделаем:' in html
        assert 'Повторение: Повторение карточек' in html
        assert 'dash-step__chip--count' in html
        assert '14' in html
        assert 'dash-step__chip--time' in html
        assert '~3 мин' in html

        # Learn phase: content title with action prefix and time chip, no count chip
        assert 'Урок: Present Perfect' in html
        assert '~10 мин' in html

    def test_phase_preview_absent_when_no_data(self, client, app, db_session, test_user, words_module_access):
        """When all previews are None no preview block is emitted for that phase."""
        plan = _make_mission_plan('progress', [False, False, False], previews=[None, None, None])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-preview="true"' not in html
        assert 'Что сделаем:' not in html

    def test_phase_preview_without_chip_data(self, client, app, db_session, test_user, words_module_access):
        """Preview with only content_title renders title block but no chips for that phase."""
        previews = [
            {'item_count': None, 'content_title': 'Быстрый разогрев', 'estimated_minutes': None},
            None,
            None,
        ]
        plan = _make_mission_plan('progress', [False, False, False], previews=previews)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'Повторение: Быстрый разогрев' in html
        # Exactly one preview block rendered (the recall one), no chips inside it.
        assert html.count('data-phase-preview="true"') == 1
        assert 'aria-label="Количество заданий"' not in html
        assert 'aria-label="Время выполнения"' not in html

    def test_phase_kind_css_classes_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 6: each phase card emits dash-step--<kind> CSS class and data-phase-kind attribute."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-step--recall' in html
        assert 'dash-step--learn' in html
        assert 'dash-step--use' in html
        assert 'dash-step--check' in html
        assert 'data-phase-kind="recall"' in html
        assert 'data-phase-kind="learn"' in html
        assert 'data-phase-kind="use"' in html
        assert 'data-phase-kind="check"' in html

    def test_phase_svg_icons_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 6: phase icons rendered as inline SVG (not just emoji)."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-step__svg-icon' in html
        assert html.count('<svg class="dash-step__svg-icon"') >= 4

    def test_phase_kind_css_class_combined_with_state(self, client, app, db_session, test_user, words_module_access):
        """Task 6: kind class coexists with state class (done/current/upcoming) on same element."""
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # Recall is first phase (done), learn is second (current), use is third (upcoming)
        assert 'dash-step--phase dash-step--recall dash-step--done' in html
        assert 'dash-step--phase dash-step--learn dash-step--current' in html
        assert 'dash-step--phase dash-step--use dash-step--upcoming' in html

    def test_phase_palette_css_present(self):
        """Task 6: phase color palette CSS rules exist in dashboard template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        for kind in ('recall', 'learn', 'use', 'read', 'check', 'close'):
            assert f'.dash-step--phase.dash-step--{kind} .dash-step__body' in css, (
                f'Missing border-left rule for phase kind {kind!r}'
            )
            assert f'.dash-step--phase.dash-step--{kind} .dash-step__num' in css, (
                f'Missing num-colour rule for phase kind {kind!r}'
            )
            assert f'.dash-step--phase.dash-step--{kind} .dash-step__icon' in css, (
                f'Missing icon rule for phase kind {kind!r}'
            )

    def test_phase_state_data_attributes_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 7: data-phase-state and data-phase-index attributes present for JS animation hooks."""
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-state="done"' in html
        assert 'data-phase-state="current"' in html
        assert 'data-phase-state="upcoming"' in html
        assert 'data-phase-index="0"' in html
        assert 'data-phase-index="1"' in html

    def test_phase_check_element_rendered_for_done(self, client, app, db_session, test_user, words_module_access):
        """Task 7: completed phases render a dedicated checkmark element for animation targeting."""
        plan = _make_mission_plan('progress', [True, True, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-step__check' in html
        assert 'data-phase-check="true"' in html
        # Two done phases -> at least two check elements
        assert html.count('data-phase-check="true"') >= 2

    def test_phase_check_absent_for_active_phases(self, client, app, db_session, test_user, words_module_access):
        """Task 7: non-done phases should not render a check element (only numeric index)."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-check="true"' not in html

    def test_progress_bar_animation_attributes(self, client, app, db_session, test_user, words_module_access):
        """Task 7: plan progress bar exposes data attributes so JS can trigger the fill animation."""
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-plan-progress="true"' in html
        assert 'data-progress-fill="true"' in html
        assert 'data-progress-pct="' in html

    def test_phase_animation_css_keyframes_present(self):
        """Task 7: required keyframes and animation CSS classes live in the dashboard template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '@keyframes dashPhaseComplete' in css
        assert '@keyframes dashPhaseActivate' in css
        assert '@keyframes dashPhaseProgressFill' in css
        # The JS-toggled hooks must have associated CSS rules
        assert '.dash-step--phase.dash-step--just-completed' in css
        assert '.dash-step--phase.dash-step--current.dash-step--newly-active' in css
        assert '.dash-progress[data-plan-progress="true"].dash-progress--animate' in css
        # Reduced-motion guard
        assert '@media (prefers-reduced-motion: reduce)' in css

    def test_phase_animation_js_hook_present(self):
        """Task 7: JS that detects ?from=daily_plan and toggles animation classes is in the template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert "from=daily_plan" in html or "params.get('from')" in html
        assert 'dash-step--just-completed' in html
        assert 'dash-step--newly-active' in html
        assert 'dash-progress--animate' in html
        assert 'mission_phase_states_v1' in html

    def test_roadmap_container_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 8: roadmap container is emitted when a mission plan is present."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'class="dash-roadmap"' in html
        assert 'data-roadmap="true"' in html
        assert 'dash-roadmap__track' in html

    def test_roadmap_absent_in_legacy_plan(self, client, app, db_session, test_user, words_module_access):
        """Task 8: legacy plans (no mission) must not emit the roadmap container."""
        legacy_plan = {'steps': {}, 'next_lesson': None, 'words_due': 0}
        response = self._get_dashboard(client, test_user, legacy_plan)
        html = response.data.decode('utf-8')
        assert 'data-roadmap="true"' not in html
        assert 'class="dash-roadmap"' not in html

    def test_roadmap_node_count_matches_phases(self, client, app, db_session, test_user, words_module_access):
        """Task 8: one node per mission phase."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert html.count('data-roadmap-node="true"') == 4
        plan3 = _make_mission_plan('progress', [False, False, False])
        response3 = self._get_dashboard(client, test_user, plan3)
        html3 = response3.data.decode('utf-8')
        assert html3.count('data-roadmap-node="true"') == 3

    def test_roadmap_connector_count_matches_phase_gaps(self, client, app, db_session, test_user, words_module_access):
        """Task 8: connectors sit between nodes — N phases → N-1 connectors."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert html.count('data-roadmap-connector="true"') == 3

    def test_roadmap_node_state_classes(self, client, app, db_session, test_user, words_module_access):
        """Task 8: node state classes reflect phase completion (done / current / upcoming)."""
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-roadmap__node--done' in html
        assert 'dash-roadmap__node--current' in html
        assert 'dash-roadmap__node--upcoming' in html
        assert 'data-node-state="done"' in html
        assert 'data-node-state="current"' in html
        assert 'data-node-state="upcoming"' in html

    def test_roadmap_node_kind_classes(self, client, app, db_session, test_user, words_module_access):
        """Task 8: node carries a kind modifier matching its phase (recall/learn/etc.)."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-roadmap__node--recall' in html
        assert 'dash-roadmap__node--learn' in html
        assert 'dash-roadmap__node--use' in html
        assert 'dash-roadmap__node--check' in html
        assert 'data-node-kind="recall"' in html
        assert 'data-node-kind="learn"' in html

    def test_roadmap_done_connector_marker(self, client, app, db_session, test_user, words_module_access):
        """Task 8: a completed phase's outgoing connector is marked --done for the journey trail."""
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-roadmap__connector--done' in html

    def test_roadmap_css_rules_present(self):
        """Task 8: roadmap CSS rules (node, connector, responsive breakpoint) live in template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.dash-roadmap {' in css
        assert '.dash-roadmap__track' in css
        assert '.dash-roadmap__node' in css
        assert '.dash-roadmap__connector' in css
        assert '@media (max-width: 640px)' in css
