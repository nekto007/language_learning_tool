import pytest
from unittest.mock import patch, MagicMock


def _make_mission_plan(mission_type='progress', phases_completed=None, previews=None, required=None):
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
            'required': required[i] if required is not None and i < len(required) else True,
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

    # ---- Task 9: roadmap node states (done/current/upcoming/bonus) ----

    def test_roadmap_state_classes_match_completion_order(self, client, app, db_session, test_user, words_module_access):
        """Task 9: given [done, current, upcoming, upcoming], node state classes map 1:1 to completion."""
        plan = _make_mission_plan('progress', [True, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-phase-id="ph0"' in html
        assert 'dash-roadmap__node--done' in html
        assert 'data-node-state="done"' in html
        assert 'dash-roadmap__node--current' in html
        assert 'data-node-state="current"' in html
        assert html.count('data-node-state="upcoming"') == 2

    def test_roadmap_done_node_renders_check_overlay(self, client, app, db_session, test_user, words_module_access):
        """Task 9: done nodes include a dedicated check-overlay element for solid-completion visuals."""
        plan = _make_mission_plan('progress', [True, True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'class="dash-roadmap__node-check"' in html
        assert html.count('class="dash-roadmap__node-check"') >= 2

    def test_roadmap_check_overlay_absent_without_done_phases(self, client, app, db_session, test_user, words_module_access):
        """Task 9: no check overlay emitted when no phase is done yet."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'class="dash-roadmap__node-check"' not in html

    def test_roadmap_connector_upcoming_class_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 9: connectors after a non-done phase get the --upcoming (dashed) modifier."""
        plan = _make_mission_plan('progress', [True, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-roadmap__connector--done' in html
        assert 'dash-roadmap__connector--upcoming' in html
        assert 'data-connector-state="done"' in html
        assert 'data-connector-state="upcoming"' in html

    def test_roadmap_bonus_node_class_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 9: optional (required=False) phases get the --bonus modifier and sparkle element."""
        plan = _make_mission_plan(
            'progress',
            [False, False, False, False],
            required=[True, True, True, False],
        )
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-roadmap__node--bonus' in html
        assert 'data-node-bonus="true"' in html
        assert 'class="dash-roadmap__node-sparkle"' in html

    def test_roadmap_bonus_absent_when_all_required(self, client, app, db_session, test_user, words_module_access):
        """Task 9: when every phase is required, no --bonus modifier nor sparkle element appears."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # Only the node modifier usage should be absent from node class lists.
        # (CSS selectors in <style> keep the substring; check for the class in markup.)
        assert 'class="dash-roadmap__node-sparkle"' not in html
        assert 'data-node-bonus="true"' not in html
        assert html.count('data-node-bonus="false"') == 4
        # No node-modifier usage on any rendered node element.
        assert 'dash-roadmap__node dash-roadmap__node--' in html  # sanity: nodes render
        assert ' dash-roadmap__node--bonus"' not in html
        assert ' dash-roadmap__node--bonus ' not in html

    def test_roadmap_state_css_rules_present(self):
        """Task 9: node-state CSS (done, current pulse, upcoming dashed, bonus sparkle) lives in template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        # State selectors
        assert '.dash-roadmap__node--done' in css
        assert '.dash-roadmap__node--current' in css
        assert '.dash-roadmap__node--upcoming' in css
        assert '.dash-roadmap__node--bonus' in css
        # Connector state selectors
        assert '.dash-roadmap__connector--done' in css
        assert '.dash-roadmap__connector--upcoming' in css
        # Supporting overlay selectors
        assert '.dash-roadmap__node-check' in css
        assert '.dash-roadmap__node-sparkle' in css
        # Current node should pulse and scale
        assert '@keyframes roadmap-node-pulse' in css
        assert 'transform: scale(1.2)' in css
        # Reduced-motion guard covers roadmap animations
        assert '@media (prefers-reduced-motion: reduce)' in css

    # ---- Task 10: roadmap start & finish markers ----

    def test_roadmap_start_marker_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 10: the roadmap emits a start marker before the first phase node."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-roadmap-marker="start"' in html
        assert 'dash-roadmap__marker--start' in html
        # Start marker appears in markup before any roadmap node
        start_pos = html.find('data-roadmap-marker="start"')
        first_node_pos = html.find('data-roadmap-node="true"')
        assert start_pos != -1 and first_node_pos != -1
        assert start_pos < first_node_pos

    def test_roadmap_finish_marker_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 10: the roadmap emits a finish marker after the last phase node."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-roadmap-marker="finish"' in html
        assert 'dash-roadmap__marker--finish' in html
        # Finish marker appears after the last node
        last_node_pos = html.rfind('data-roadmap-node="true"')
        finish_pos = html.find('data-roadmap-marker="finish"')
        assert last_node_pos != -1 and finish_pos != -1
        assert finish_pos > last_node_pos

    def test_roadmap_finish_marker_pending_state(self, client, app, db_session, test_user, words_module_access):
        """Task 10: when plan is incomplete, finish marker is in pending state with distance label."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # Data attributes (markup-only — avoids collision with CSS selector text)
        assert 'data-marker-state="pending"' in html
        assert 'data-marker-state="complete"' not in html
        assert 'data-steps-remaining="3"' in html
        assert 'data-marker-distance="true"' in html
        assert '3 шага до финиша' in html
        assert 'data-roadmap-complete="false"' in html

    def test_roadmap_finish_marker_complete_state(self, client, app, db_session, test_user, words_module_access):
        """Task 10: when all phases are done, finish shows complete state with confetti burst."""
        plan = _make_mission_plan('progress', [True, True, True])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-marker-state="complete"' in html
        assert 'data-marker-state="pending"' not in html
        assert 'data-roadmap-complete="true"' in html
        # Burst particles for the confetti animation (class appears once per piece element)
        assert 'class="dash-roadmap__marker-burst"' in html
        assert html.count('class="dash-roadmap__marker-burst-piece"') >= 6
        # No distance hint when complete
        assert 'data-marker-distance="true"' not in html
        assert 'data-steps-remaining="0"' in html

    def test_roadmap_finish_distance_label_pluralization(self, client, app, db_session, test_user, words_module_access):
        """Task 10: the distance hint pluralizes the remaining-steps count correctly (RU grammar)."""
        # 1 step remaining — singular form
        plan1 = _make_mission_plan('progress', [True, True, False])
        html1 = self._get_dashboard(client, test_user, plan1).data.decode('utf-8')
        assert '1 шаг до финиша' in html1
        assert 'data-steps-remaining="1"' in html1

        # 2 steps remaining — few form
        plan2 = _make_mission_plan('progress', [True, False, False])
        html2 = self._get_dashboard(client, test_user, plan2).data.decode('utf-8')
        assert '2 шага до финиша' in html2

        # 5 steps remaining (four phases, none done + one extra path) — many form
        # Use four-phase plan with zero done to approximate: 4 шага (few form)
        plan4 = _make_mission_plan('progress', [False, False, False, False])
        html4 = self._get_dashboard(client, test_user, plan4).data.decode('utf-8')
        assert '4 шага до финиша' in html4

    def test_roadmap_marker_absent_in_legacy_plan(self, client, app, db_session, test_user, words_module_access):
        """Task 10: legacy (non-mission) plans do not emit start/finish markers."""
        legacy_plan = {'steps': {}, 'next_lesson': None, 'words_due': 0}
        response = self._get_dashboard(client, test_user, legacy_plan)
        html = response.data.decode('utf-8')
        assert 'data-roadmap-marker="start"' not in html
        assert 'data-roadmap-marker="finish"' not in html
        assert 'data-marker-state=' not in html

    def test_roadmap_inner_connector_count_unchanged(self, client, app, db_session, test_user, words_module_access):
        """Task 10: adding start/finish edge connectors must not break the between-nodes count."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
        # Between-node connectors keep their stable data attribute
        assert html.count('data-roadmap-connector="true"') == 3
        # Edge connectors live under a different attribute so as not to pollute the count
        assert html.count('data-roadmap-edge-connector="start"') == 1
        assert html.count('data-roadmap-edge-connector="finish"') == 1

    def test_roadmap_marker_css_rules_present(self):
        """Task 10: start/finish marker styles and finish animations live in the template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        # Marker base + variants
        assert '.dash-roadmap__marker' in css
        assert '.dash-roadmap__marker--start' in css
        assert '.dash-roadmap__marker--finish' in css
        assert '.dash-roadmap__marker--complete' in css
        assert '.dash-roadmap__marker--pending' in css
        # Distance label + burst
        assert '.dash-roadmap__marker-distance' in css
        assert '.dash-roadmap__marker-burst' in css
        # Celebration keyframes
        assert '@keyframes roadmap-finish-pulse' in css
        assert '@keyframes roadmap-finish-burst' in css

    # ---- Task 11: mobile-responsive roadmap breakpoints ----

    def _read_dashboard_template(self):
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _find_roadmap_mobile_block(self, css):
        """Locate the roadmap-scoped @media (max-width: 640px) rule (not heatmap)."""
        anchor = 'Task 11: Mobile-responsive roadmap breakpoints'
        anchor_start = css.find(anchor)
        assert anchor_start != -1, "Task 11 anchor comment missing from template CSS"
        # Search forward from the anchor for the mobile media rule
        mobile_start = css.find('@media (max-width: 640px)', anchor_start)
        assert mobile_start != -1
        # Cap at next @media or next top-level comment
        next_media = css.find('@media', mobile_start + 10)
        end = next_media if next_media != -1 else mobile_start + 4000
        return css[mobile_start:end]

    def test_roadmap_mobile_breakpoint_present(self):
        """Task 11: mobile (< 640px) media query with vertical serpentine + 48px nodes."""
        css = self._read_dashboard_template()
        mobile_block = self._find_roadmap_mobile_block(css)
        assert 'width: 48px' in mobile_block
        assert 'height: 48px' in mobile_block
        assert 'min-width: 44px' in mobile_block
        assert 'min-height: 44px' in mobile_block
        # Vertical serpentine: track becomes a column
        assert 'flex-direction: column' in mobile_block
        # Roadmap-scoped (references dash-roadmap selectors inside)
        assert '.dash-roadmap' in mobile_block

    def test_roadmap_tablet_breakpoint_present(self):
        """Task 11: tablet (641-1024px) media query with horizontal scroll + snap."""
        css = self._read_dashboard_template()
        assert '@media (min-width: 641px) and (max-width: 1024px)' in css
        tablet_start = css.find('@media (min-width: 641px) and (max-width: 1024px)')
        tablet_end = css.find('@media', tablet_start + 10)
        tablet_block = css[tablet_start:tablet_end if tablet_end != -1 else tablet_start + 2500]
        # Horizontal scroll with snap points
        assert 'overflow-x: auto' in tablet_block
        assert 'scroll-snap-type: x mandatory' in tablet_block
        assert 'scroll-snap-align' in tablet_block
        # Touch targets
        assert 'min-width: 44px' in tablet_block
        assert 'min-height: 44px' in tablet_block

    def test_roadmap_desktop_breakpoint_present(self):
        """Task 11: desktop (> 1024px) shows a fully expanded horizontal layout with no scroll."""
        css = self._read_dashboard_template()
        assert '@media (min-width: 1025px)' in css
        desktop_start = css.find('@media (min-width: 1025px)')
        desktop_end = css.find('@media', desktop_start + 10)
        desktop_block = css[desktop_start:desktop_end if desktop_end != -1 else desktop_start + 1500]
        assert 'flex-direction: row' in desktop_block
        assert 'overflow: visible' in desktop_block

    def test_roadmap_swipe_hint_element_present(self, client, app, db_session, test_user, words_module_access):
        """Task 11: roadmap emits a swipe hint element used on tablet horizontal layouts."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-roadmap-swipe-hint="true"' in html
        assert 'dash-roadmap__swipe-hint' in html

    def test_roadmap_swipe_hint_css_present(self):
        """Task 11: swipe hint has default display:none and is revealed only in tablet breakpoint."""
        css = self._read_dashboard_template()
        assert '.dash-roadmap__swipe-hint' in css
        # Default state is hidden
        hint_start = css.find('.dash-roadmap__swipe-hint {')
        assert hint_start != -1
        hint_block = css[hint_start:hint_start + 300]
        assert 'display: none' in hint_block
        # Tablet breakpoint reveals the hint
        tablet_start = css.find('@media (min-width: 641px) and (max-width: 1024px)')
        tablet_block = css[tablet_start:tablet_start + 2500]
        assert 'display: block' in tablet_block
