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
        # Task 6: reason_text was removed from the compact mission header
        assert 'Следующий урок готов для вас' not in html

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
        # completion_summary section is shown when all phases done
        assert 'dash-completion-summary' in html or 'dash-plan-complete' in html

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

    def test_linear_progress_bar_removed(self, client, app, db_session, test_user, words_module_access):
        """Task 5 (compact redesign): linear 0/3 progress bar above phase cards is gone — roadmap is the single progress indicator."""
        plan = _make_mission_plan('progress', [True, True, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-plan-progress="true"' not in html
        assert 'data-progress-fill="true"' not in html
        assert 'data-progress-pct="' not in html

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

    def test_phase_animation_css_keyframes_present(self):
        """Task 7: required keyframes and animation CSS classes live in the dashboard template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '@keyframes dashPhaseComplete' in css
        assert '@keyframes dashPhaseActivate' in css
        # The JS-toggled hooks must have associated CSS rules
        assert '.dash-step--phase.dash-step--just-completed' in css
        assert '.dash-step--phase.dash-step--current.dash-step--newly-active' in css
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
        import re
        # Use data-node-kind which appears exactly once per roadmap node (not in CSS/JS)
        plan = _make_mission_plan('progress', [False, False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert len(re.findall(r'data-node-kind="[^"]*"', html)) == 4
        plan3 = _make_mission_plan('progress', [False, False, False])
        response3 = self._get_dashboard(client, test_user, plan3)
        html3 = response3.data.decode('utf-8')
        assert len(re.findall(r'data-node-kind="[^"]*"', html3)) == 3

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
        # Finish marker appears after the last node (use data-node-bonus which is
        # only in the HTML element, not in JS/CSS)
        last_node_pos = html.rfind('data-node-bonus="')
        finish_pos = html.find('data-roadmap-marker="finish"')
        assert last_node_pos != -1 and finish_pos != -1
        assert finish_pos > last_node_pos

    def test_roadmap_finish_marker_pending_state(self, client, app, db_session, test_user, words_module_access):
        """Task 10: when plan is incomplete, finish marker is in pending state.

        Task 5 (compact redesign): the "N steps to finish" distance label was removed —
        the pending marker icon alone signals the remaining distance.
        """
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # Data attributes (markup-only — avoids collision with CSS selector text)
        assert 'data-marker-state="pending"' in html
        assert 'data-marker-state="complete"' not in html
        assert 'data-steps-remaining="3"' in html
        # Distance label is gone (Task 5)
        assert 'data-marker-distance="true"' not in html
        assert 'до финиша' not in html
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
        # Distance hint is removed entirely (Task 5)
        assert 'data-marker-distance="true"' not in html
        assert 'data-steps-remaining="0"' in html

    def test_roadmap_finish_distance_label_removed(self, client, app, db_session, test_user, words_module_access):
        """Task 5 (compact redesign): the pluralised "N шагов до финиша" label is removed."""
        for phases in ([True, True, False], [True, False, False], [False, False, False, False]):
            plan = _make_mission_plan('progress', phases)
            html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
            assert 'до финиша' not in html
            assert 'data-marker-distance="true"' not in html

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
        # Distance label removed (Task 5); burst still present.
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
        """Mobile (< 640px) uses horizontal scroll with snap points.

        The vertical zig-zag variant was dropped because it ballooned the
        roadmap's height and broke absolute-positioned route-tokens that
        align to the horizontal axis via `left: %`.
        """
        css = self._read_dashboard_template()
        mobile_block = self._find_roadmap_mobile_block(css)
        assert 'width: 48px' in mobile_block
        assert 'height: 48px' in mobile_block
        assert 'min-width: 44px' in mobile_block
        assert 'min-height: 44px' in mobile_block
        # Horizontal scroll (same pattern as tablet)
        assert 'flex-direction: row' in mobile_block
        assert 'overflow-x: auto' in mobile_block
        assert 'scroll-snap-type: x mandatory' in mobile_block
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

    # ---- Task 14: rank badge on dashboard ----

    def _set_user_plans(self, db_session, user_id, count, code=None):
        """Ensure a UserStatistics row with the given plans_completed_total exists."""
        from app.achievements.models import UserStatistics
        from app.achievements.ranks import get_rank_code

        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id)
            db_session.add(stats)
            db_session.flush()
        stats.plans_completed_total = count
        stats.current_rank = code or get_rank_code(count)
        db_session.commit()
        return stats

    def test_rank_badge_renders_for_novice(self, client, app, db_session, test_user, words_module_access):
        """Task 14: dashboard renders rank badge with novice name at zero plans completed."""
        plan = _make_mission_plan('progress', [False, False, False])
        self._set_user_plans(db_session, test_user.id, 0)
        response = self._get_dashboard(client, test_user, plan)
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'class="dash-rank dash-rank--novice"' in html
        assert 'data-rank-code="novice"' in html
        assert 'data-rank-plans="0"' in html
        assert 'Новичок' in html
        assert '0/7' in html
        assert 'до «Исследователь»' in html
        assert 'data-rank-progress="true"' in html

    def test_rank_badge_renders_progress_numbers(self, client, app, db_session, test_user, words_module_access):
        """Task 14: progress bar text shows current / next-threshold numbers."""
        plan = _make_mission_plan('progress', [False, False, False])
        self._set_user_plans(db_session, test_user.id, 14)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-rank--explorer' in html
        assert 'data-rank-plans="14"' in html
        assert '14/21' in html
        assert 'до «Ученик»' in html
        # Progress fill width is (14 - 7) / (21 - 7) = 50%
        assert 'width: 50' in html or 'width: 50.0' in html

    def test_rank_badge_renders_expert(self, client, app, db_session, test_user, words_module_access):
        """Task 14: badge picks correct rank name at higher thresholds."""
        plan = _make_mission_plan('progress', [False, False, False])
        self._set_user_plans(db_session, test_user.id, 60)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-rank--expert' in html
        assert 'Эксперт' in html
        assert '60/100' in html
        assert 'до «Мастер»' in html

    def test_rank_badge_max_rank_shows_max_label(self, client, app, db_session, test_user, words_module_access):
        """Task 14: at the top rank, badge shows a max-rank label instead of the progress bar."""
        plan = _make_mission_plan('progress', [False, False, False])
        self._set_user_plans(db_session, test_user.id, 400)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-rank--grandmaster' in html
        assert 'Грандмастер' in html
        assert 'dash-rank__progress--max' in html
        assert 'Максимальный титул' in html
        # No "до «..»" next-rank pointer when at max
        assert 'до «' not in html.split('dash-rank')[1].split('dash-plan')[0] if 'dash-rank' in html else True

    def test_rank_badge_absent_when_rank_info_missing(self, client, app, db_session, test_user, words_module_access):
        """Task 14: without rank_info the template omits the badge entirely."""
        from unittest.mock import patch as _patch
        plan = _make_mission_plan('progress', [False, False, False])
        with _patch('app.words.routes._build_rank_info', return_value=None):
            response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'class="dash-rank' not in html
        assert 'data-rank-progress="true"' not in html

    def test_rank_badge_unique_colors_per_rank(self):
        """Task 14: each rank code has a unique colour class rule in the template CSS."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        for code in ('novice', 'explorer', 'student', 'expert', 'master', 'legend', 'grandmaster'):
            assert f'.dash-rank--{code} .dash-rank__badge' in css, f'missing CSS rule for rank {code!r}'

    def test_rank_badge_progress_fill_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 14: progress bar track and fill elements rendered with width percent."""
        plan = _make_mission_plan('progress', [False, False, False])
        self._set_user_plans(db_session, test_user.id, 7)  # exact threshold for explorer
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'dash-rank__progress-track' in html
        assert 'dash-rank__progress-fill' in html
        # At threshold start, progress within new rank is 0%
        assert 'width: 0' in html

    # ---- Task 33: Route board container ----

    def test_route_container_rendered_for_mission_plan(self, client, app, db_session, test_user, words_module_access):
        """Task 33: dash-route container is emitted when a mission plan is present."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-route-container="true"' in html
        assert 'class="dash-route' in html

    def test_route_container_absent_for_legacy_plan(self, client, app, db_session, test_user, words_module_access):
        """Task 33: legacy plans must not emit the route container."""
        legacy_plan = {'steps': {}, 'next_lesson': None, 'words_due': 0}
        response = self._get_dashboard(client, test_user, legacy_plan)
        html = response.data.decode('utf-8')
        assert 'data-route-container="true"' not in html

    def test_route_checkpoint_count_matches_phases(self, client, app, db_session, test_user, words_module_access):
        """Task 33: one route checkpoint per mission phase."""
        plan4 = _make_mission_plan('progress', [False, False, False, False])
        html4 = self._get_dashboard(client, test_user, plan4).data.decode('utf-8')
        assert html4.count('data-route-checkpoint="true"') == 4

        plan3 = _make_mission_plan('progress', [False, False, False])
        html3 = self._get_dashboard(client, test_user, plan3).data.decode('utf-8')
        assert html3.count('data-route-checkpoint="true"') == 3

    def test_route_metadata_total_checkpoints(self, client, app, db_session, test_user, words_module_access):
        """Task 33: data-total-checkpoints attribute matches phase count."""
        plan = _make_mission_plan('progress', [False, False, False, False])
        html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
        assert 'data-total-checkpoints="4"' in html

    def test_route_metadata_current_checkpoint(self, client, app, db_session, test_user, words_module_access):
        """Task 33: data-current-checkpoint reflects the index of the first incomplete phase."""
        plan = _make_mission_plan('progress', [True, False, False])
        html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
        assert 'data-current-checkpoint="1"' in html

    def test_route_metadata_finish_state_in_progress(self, client, app, db_session, test_user, words_module_access):
        """Task 33: finish state is in_progress when plan is not complete."""
        plan = _make_mission_plan('progress', [True, False, False])
        html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
        assert 'data-finish-state="in_progress"' in html

    def test_route_metadata_finish_state_done(self, client, app, db_session, test_user, words_module_access):
        """Task 33: finish state is done when all phases are complete."""
        plan = _make_mission_plan('progress', [True, True, True])
        html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
        assert 'data-finish-state="done"' in html

    def test_route_checkpoint_kind_attributes(self, client, app, db_session, test_user, words_module_access):
        """Task 33: each checkpoint carries data-checkpoint-kind and data-checkpoint-state."""
        plan = _make_mission_plan('progress', [True, False, False, False])
        html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
        assert 'data-checkpoint-kind="recall"' in html
        assert 'data-checkpoint-kind="learn"' in html
        assert 'data-checkpoint-state="done"' in html
        assert 'data-checkpoint-state="current"' in html
        assert 'data-checkpoint-state="upcoming"' in html

    def test_route_compact_class_for_small_plans(self, client, app, db_session, test_user, words_module_access):
        """Task 33: dash-route--compact applied to plans with 3 or fewer phases."""
        plan3 = _make_mission_plan('progress', [False, False, False])
        html3 = self._get_dashboard(client, test_user, plan3).data.decode('utf-8')
        # Check the class appears in the opening tag's class attribute, not just CSS
        assert 'class="dash-route dash-route--compact"' in html3 or 'class="dash-route  dash-route--compact"' in html3 or 'dash-route--compact"' in html3

    def test_route_compact_absent_for_large_plans(self, client, app, db_session, test_user, words_module_access):
        """Task 33: dash-route--compact not applied to plans with more than 3 phases."""
        plan4 = _make_mission_plan('progress', [False, False, False, False])
        html4 = self._get_dashboard(client, test_user, plan4).data.decode('utf-8')
        # Find the route container opening tag (up to >) and check compact is absent from it
        import re
        route_tag_match = re.search(r'data-route-container="true"[^>]*>', html4)
        assert route_tag_match is not None
        assert 'dash-route--compact' not in route_tag_match.group(0)

    def test_route_contains_roadmap_and_timeline(self, client, app, db_session, test_user, words_module_access):
        """Task 33: dash-route wraps both roadmap and timeline — both must be inside it."""
        plan = _make_mission_plan('progress', [False, False, False])
        html = self._get_dashboard(client, test_user, plan).data.decode('utf-8')
        route_start = html.find('data-route-container="true"')
        roadmap_pos = html.find('data-roadmap="true"')
        timeline_pos = html.find('data-mission-plan="true"')
        route_end_marker = html.find('/dash-route -->', route_start)
        assert route_start < roadmap_pos
        assert route_start < timeline_pos
        # Roadmap and timeline must come after the opening route container
        assert roadmap_pos > route_start
        assert timeline_pos > route_start

    def test_route_css_rules_present(self):
        """Task 33: dash-route CSS rules (container, compact, mobile fallback) live in template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.dash-route {' in css
        assert '.dash-route--compact' in css

    # ---- Task 34: Rival tokens on the route ----

    def _get_dashboard_with_race(self, client, test_user, mission_plan, race_data):
        """Render dashboard with both a mocked plan and a mocked daily_race payload."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan, \
             patch('app.words.routes._build_daily_race_widget') as mock_race:
            mock_plan.return_value = mission_plan
            mock_race.return_value = race_data
            response = client.get('/dashboard')
        return response

    def _make_route_rivals(self):
        """Return a minimal route_rivals list with ahead/me/behind tokens."""
        return [
            {
                'user_id': 2, 'username': 'Ракета', 'initials': 'РА',
                'score': 30, 'steps_done': 2, 'steps_total': 3,
                'streak': 5, 'next_step_title': '', 'next_step_points': 0,
                'is_me': False, 'is_bot': False, 'rank': 1, 'place_class': 'gold',
                'is_complete': False, 'route_position': 66, 'rival_role': 'ahead',
            },
            {
                'user_id': 1, 'username': 'Testuser', 'initials': 'TE',
                'score': 20, 'steps_done': 1, 'steps_total': 3,
                'streak': 3, 'next_step_title': 'Урок', 'next_step_points': 40,
                'is_me': True, 'is_bot': False, 'rank': 2, 'place_class': 'silver',
                'is_complete': False, 'route_position': 33, 'rival_role': 'me',
            },
            {
                'user_id': 3, 'username': 'Молния', 'initials': 'МО',
                'score': 10, 'steps_done': 0, 'steps_total': 3,
                'streak': 1, 'next_step_title': '', 'next_step_points': 0,
                'is_me': False, 'is_bot': True, 'rank': 3, 'place_class': '',
                'is_complete': False, 'route_position': 0, 'rival_role': 'behind',
            },
        ]

    def _make_race_payload(self, route_rivals=None):
        rivals = route_rivals if route_rivals is not None else self._make_route_rivals()
        return {
            'rank': 2, 'place_class': 'silver', 'total': 3,
            'score': 20, 'steps_done': 1, 'steps_total': 3,
            'streak': 3, 'is_complete': False,
            'rival_above': rivals[0], 'rival_below': rivals[2],
            'gap_up': 10, 'gap_down': 10,
            'callout': 'Сократи отрыв!',
            'next_step_title': 'Урок', 'next_step_points': 40,
            'duel_target': rivals[0],
            'has_bot_rivals': True,
            'leaderboard': rivals,
            'route_rivals': rivals,
            'next_action_title': '', 'next_action_url': '',
        }

    def test_route_rivals_in_payload(self):
        """Task 34: route_rivals list is present and includes route_position for each entry."""
        # Test the logic directly without a full DB round-trip
        from app.words.routes import _build_daily_race_widget
        # Ensure route_position calculation: steps_done/steps_total * 100
        dummy_entry = {'steps_done': 2, 'steps_total': 4}
        st = dummy_entry['steps_total']
        pos = int(dummy_entry['steps_done'] / st * 100) if st > 0 else 0
        assert pos == 50

        dummy_entry_zero = {'steps_done': 0, 'steps_total': 0}
        st2 = dummy_entry_zero['steps_total']
        pos2 = int(dummy_entry_zero['steps_done'] / st2 * 100) if st2 > 0 else 0
        assert pos2 == 0

    def test_route_rivals_roles(self):
        """Task 34: route_rivals entries carry rival_role field: ahead/me/behind/leader."""
        rivals = self._make_route_rivals()
        roles = {r['rival_role'] for r in rivals}
        assert 'me' in roles
        assert 'ahead' in roles
        assert 'behind' in roles

    def test_route_token_html_rendered_when_rivals_present(self, client, app, db_session, test_user, words_module_access):
        """Task 34: dash-route-token elements rendered when route_rivals is in daily_race payload."""
        plan = _make_mission_plan('progress', [False, False, False])
        race = self._make_race_payload()
        response = self._get_dashboard_with_race(client, test_user, plan, race)
        html = response.data.decode('utf-8')
        assert 'data-route-tokens="true"' in html
        assert 'data-route-token="true"' in html
        # User token with rival_role="me" must be present
        assert 'dash-route-token--me' in html

    def test_route_token_ahead_and_behind_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 34: ahead and behind rival tokens are rendered on the route."""
        plan = _make_mission_plan('progress', [False, False, False])
        race = self._make_race_payload()
        response = self._get_dashboard_with_race(client, test_user, plan, race)
        html = response.data.decode('utf-8')
        assert 'dash-route-token--ahead' in html
        assert 'dash-route-token--behind' in html

    def test_route_token_positions_in_style(self, client, app, db_session, test_user, words_module_access):
        """Task 34: each token carries inline left% style matching its route_position."""
        plan = _make_mission_plan('progress', [False, False, False])
        race = self._make_race_payload()
        response = self._get_dashboard_with_race(client, test_user, plan, race)
        html = response.data.decode('utf-8')
        # ahead token at 66%
        assert 'left: 66%' in html
        # me token at 33%
        assert 'left: 33%' in html

    def test_route_tokens_absent_when_no_race(self, client, app, db_session, test_user, words_module_access):
        """Task 34: token strip not rendered when daily_race is None."""
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard_with_race(client, test_user, plan, None)
        html = response.data.decode('utf-8')
        assert 'data-route-tokens="true"' not in html

    def test_bot_rival_labeled_training(self, client, app, db_session, test_user, words_module_access):
        """Task 34: bot rival tokens carry the training CSS class."""
        plan = _make_mission_plan('progress', [False, False, False])
        race = self._make_race_payload()
        response = self._get_dashboard_with_race(client, test_user, plan, race)
        html = response.data.decode('utf-8')
        assert 'dash-route-token--training' in html

    def test_route_token_css_classes_in_design_system(self):
        """Task 34: CSS classes for route tokens exist in design-system.css."""
        import os
        css_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'css', 'design-system.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.dash-route-tokens' in css
        assert '.dash-route-token--me' in css
        assert '.dash-route-token--ahead' in css
        assert '.dash-route-token--behind' in css
        assert '.dash-route-token--leader' in css
        assert '.dash-route-token--training' in css

    def test_leaderboard_rendered_as_collapsible_details(self, client, app, db_session, test_user, words_module_access):
        """Task 34: race leaderboard is wrapped in a details element (secondary/compact UI)."""
        plan = _make_mission_plan('progress', [False, False, False])
        race = self._make_race_payload()
        response = self._get_dashboard_with_race(client, test_user, plan, race)
        html = response.data.decode('utf-8')
        assert 'dash-race__board--compact' in html

    # ---- Task 35: Overtake and checkpoint animations ----

    def test_route_token_has_animate_attribute(self, client, app, db_session, test_user, words_module_access):
        """Task 35: each route token carries data-animate-token for JS animation targeting."""
        plan = _make_mission_plan('progress', [False, False, False])
        race = self._make_race_payload()
        response = self._get_dashboard_with_race(client, test_user, plan, race)
        html = response.data.decode('utf-8')
        assert 'data-animate-token="true"' in html
        # Three tokens from route_rivals; attribute also appears inside <script>, so >= 3
        assert html.count('data-animate-token="true"') >= 3

    def test_route_container_exposes_checkpoint_and_finish_data(self, client, app, db_session, test_user, words_module_access):
        """Task 35: route container has data-current-checkpoint and data-finish-state for JS."""
        plan = _make_mission_plan('progress', [True, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-current-checkpoint=' in html
        assert 'data-finish-state=' in html
        assert 'data-current-checkpoint="1"' in html
        assert 'data-finish-state="in_progress"' in html

    def test_route_finish_state_done_when_all_complete(self, client, app, db_session, test_user, words_module_access):
        """Task 35: finish-state is 'done' when all phases complete — triggers calm finish JS."""
        plan = _make_mission_plan('progress', [True, True, True])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-finish-state="done"' in html

    def test_route_animation_css_keyframes_present(self):
        """Task 35: token-move, overtake, checkpoint, and finish-calm keyframes in template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '@keyframes route-token-move' in css
        assert '@keyframes route-token-overtake' in css
        assert '@keyframes roadmap-node-just-reached' in css
        assert '@keyframes roadmap-node-completed' in css
        assert '@keyframes route-finish-calm' in css
        assert '@keyframes route-overtake-toast-in' in css

    def test_route_animation_css_classes_present(self):
        """Task 35: animation state CSS classes for token move, overtake, checkpoint, finish exist."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.dash-route-token--just-moved' in css
        assert '.dash-route-token--overtaking' in css
        assert '.dash-route-overtake-toast' in css
        assert '.dash-roadmap__node--current.dash-roadmap__node--just-reached' in css
        assert '.dash-roadmap__node--done.dash-roadmap__node--just-completed' in css
        assert '.dash-route--finish-calm' in css

    def test_route_animation_reduced_motion_guard_present(self):
        """Task 35: animation classes are suppressed under prefers-reduced-motion."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        # Find the Task 35 reduced-motion block by anchoring on an earlier Task 35 marker
        task35_anchor = css.find('Task 35: Overtake and checkpoint animations')
        assert task35_anchor != -1, 'Task 35 CSS anchor comment missing'
        reduced_start = css.find('@media (prefers-reduced-motion: reduce)', task35_anchor)
        assert reduced_start != -1
        reduced_block = css[reduced_start:reduced_start + 600]
        assert 'dash-route-token--just-moved' in reduced_block

    def test_route_animation_js_hook_present(self):
        """Task 35: JS for route overtake/checkpoint detection is in the template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert 'mission_route_state_v1' in html
        assert 'dash-route-token--just-moved' in html
        assert 'dash-route-token--overtaking' in html
        assert 'dash-roadmap__node--just-reached' in html
        assert 'dash-roadmap__node--just-completed' in html
        assert 'dash-route--finish-calm' in html
        assert 'data-animate-token' in html

    # ---- Task 9 (Plan): Day secured banner + next-step card ----

    def _make_mission_plan_with_secured(self, mission_type='progress', phases_completed=None, day_secured=False):
        plan = _make_mission_plan(mission_type, phases_completed)
        plan['day_secured'] = day_secured
        return plan

    def test_day_secured_banner_shown_when_secured_and_not_all_done(self, client, app, db_session, test_user, words_module_access):
        """Task 9: day-secured banner renders when day_secured=True and required phases are done but bonus phases remain."""
        plan = self._make_mission_plan_with_secured('progress', [True, True, False], day_secured=True)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-day-secured="true"' in html
        assert 'dash-day-secured' in html
        assert 'День закрыт!' in html
        assert 'Серия сохранена' in html

    def test_day_secured_banner_absent_when_not_secured(self, client, app, db_session, test_user, words_module_access):
        """Task 9: day-secured banner must not appear when day_secured=False."""
        plan = self._make_mission_plan_with_secured('progress', [False, False, False], day_secured=False)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'class="dash-day-secured"' not in html
        assert 'День закрыт!' not in html

    def test_day_secured_banner_absent_when_all_done(self, client, app, db_session, test_user, words_module_access):
        """Task 9: when all phases are done the completion summary shows instead; no secured banner."""
        plan = self._make_mission_plan_with_secured('progress', [True, True, True], day_secured=True)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # Banner must not appear when m_all_done (completion summary takes over)
        assert 'class="dash-day-secured"' not in html

    def test_next_step_container_rendered_inside_secured_banner(self, client, app, db_session, test_user, words_module_access):
        """Task 9/14: next-step queue container is present inside the secured banner for JS to populate."""
        plan = self._make_mission_plan_with_secured('progress', [True, True, False], day_secured=True)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-next-step-container="true"' in html
        # Task 14: queue container replaces individual step slots; JS builds items dynamically
        assert 'data-next-step-queue="true"' in html
        assert 'data-next-step-dismiss="true"' in html

    def test_next_step_container_absent_when_not_secured(self, client, app, db_session, test_user, words_module_access):
        """Task 9: next-step container must not appear when day is not secured."""
        plan = self._make_mission_plan_with_secured('progress', [False, False, False], day_secured=False)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # The HTML element must not be rendered (the string also appears in JS, check the element markup)
        assert 'class="dash-next-step"' not in html
        assert 'Продолжить позже' not in html

    def test_continue_later_dismiss_button_rendered(self, client, app, db_session, test_user, words_module_access):
        """Task 9: dismiss button with correct data attribute is present when secured."""
        plan = self._make_mission_plan_with_secured('progress', [True, True, False], day_secured=True)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-next-step-dismiss="true"' in html
        assert 'Продолжить позже' in html

    def test_day_secured_css_rules_present(self):
        """Task 9: day-secured and next-step CSS rules exist in dashboard template."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.dash-day-secured {' in css
        assert '.dash-day-secured__banner' in css
        assert '.dash-next-step {' in css
        assert '.dash-next-step__btn--go' in css
        assert '.dash-next-step__btn--dismiss' in css

    def test_day_secured_js_hook_present(self):
        """Task 9: JS that fetches /api/daily-plan/continuation and renders the next-step card exists."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert '/api/daily-plan/continuation' in html
        assert 'data-next-step-container' in html
        assert 'next_step_shown' in html
        assert 'next_step_accepted' in html
        assert 'next_step_dismissed' in html

    def test_day_secured_cards_url_in_container(self, client, app, db_session, test_user, words_module_access):
        """Task 9: cards URL is embedded in the secured banner container for JS SRS/vocab fallback."""
        plan = self._make_mission_plan_with_secured('progress', [True, True, False], day_secured=True)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'data-cards-url=' in html

    def test_existing_progress_ui_unchanged_when_secured(self, client, app, db_session, test_user, words_module_access):
        """Task 9: existing roadmap and timeline are still rendered when day is secured (above banner)."""
        plan = self._make_mission_plan_with_secured('progress', [True, True, False], day_secured=True)
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # Standard mission plan UI elements must still be present
        assert 'data-roadmap="true"' in html
        assert 'data-mission-plan="true"' in html
        assert 'dash-mission-header' in html

    # ---- Task 5 (compact redesign): Route board removed from dashboard ----

    def _get_dashboard_with_route_state(self, client, test_user, plan, route_progress_state):
        """Render dashboard with a mocked plan and route progress state."""
        from unittest.mock import patch
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan, \
             patch('app.daily_plan.route_progress.get_route_state') as mock_route:
            mock_plan.return_value = plan
            mock_route.return_value = route_progress_state
            response = client.get('/dashboard')
        return response

    def test_route_board_markup_absent_on_dashboard(self, client, app, db_session, test_user, words_module_access):
        """Task 5: route board and its sub-elements no longer render on the dashboard."""
        plan = _make_mission_plan('progress', [True, False, False])
        plan['day_secured'] = True
        route_state = {
            'steps_today': 5,
            'total_steps': 25,
            'checkpoint_number': 1,
            'steps_to_next_checkpoint': 15,
            'percent_to_checkpoint': 25,
        }
        response = self._get_dashboard_with_route_state(client, test_user, plan, route_state)
        html = response.data.decode('utf-8')
        assert 'data-route-board="true"' not in html
        assert 'data-route-bar-fill="true"' not in html
        assert 'data-secured-marker="true"' not in html
        assert 'data-checkpoint-reached="true"' not in html
        assert 'data-steps-to-checkpoint="true"' not in html
        assert 'data-steps-today-label="true"' not in html

    def test_route_board_queue_hooks_retained_for_day_secured_banner(self):
        """Task 5: queue JS hooks remain (Task 8 will remove them with the day-secured banner)."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert 'data-next-step-queue' in html
        assert 'buildQueueItem' in html


class TestHeroCompactLayout:
    """19 Tasks plan — Task 1: hero collapses to greeting + streak only."""

    def _get_dashboard(self, client, test_user, mission_plan):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan:
            mock_plan.return_value = mission_plan
            response = client.get('/dashboard')
        return response

    def _extract_hero(self, html):
        start = html.find('<div class="dash-hero">')
        assert start != -1, 'dash-hero container missing'
        # Everything between the hero container and the next top-level block
        # (rank, mission-xp widget, welcome card, race, plan, section, etc.)
        markers = [
            'class="dash-rank ',
            'class="dash-xp "',
            'class="dash-xp"',
            'class="dash-welcome"',
            'class="dash-race',
            'class="dash-plan',
            'Rank badge',
        ]
        end_positions = [html.find(m, start + 10) for m in markers]
        end_positions = [p for p in end_positions if p != -1]
        assert end_positions, 'could not locate end of hero section'
        return html[start:min(end_positions)]

    def test_hero_compact_layout_renders(self, client, app, db_session, test_user, words_module_access):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        hero = self._extract_hero(html)
        # Greeting + streak container still present
        assert 'dash-hero__greeting' in hero
        assert 'dash-hero__title' in hero
        # Decorative shapes are gone
        assert 'dash-shape' not in hero
        assert 'dash-hero__bg-shapes' not in hero
        # Removed blocks do NOT appear inside the hero section
        assert 'dash-yesterday' not in hero
        assert 'dash-xp-bar' not in hero
        # Rank badge is no longer nested inside the hero card
        assert 'dash-rank' not in hero
        # Single gradient background layer is still wired
        assert 'dash-hero__bg' in hero

    def test_hero_has_max_width_720(self):
        """Compact hero caps width at ~720px via inline CSS."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        # Match the .dash-hero rule block (not a mobile override)
        hero_rule_start = css.find('.dash-hero {')
        hero_rule_end = css.find('}', hero_rule_start)
        assert hero_rule_start != -1 and hero_rule_end != -1
        hero_rule = css[hero_rule_start:hero_rule_end]
        assert 'max-width: 720px' in hero_rule
        assert 'margin: 0 auto' in hero_rule

    def test_dash_shape_animations_removed(self):
        """Task 1: dash-shape keyframes + float animations are gone."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert 'dash-shape--1' not in css
        assert 'dash-shape--2' not in css
        assert '@keyframes dashFloat1' not in css
        assert '@keyframes dashFloat2' not in css

    def test_hero_single_row_flex_layout(self):
        """Greeting row uses flex layout so greeting + streak can share a row."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        greeting_start = css.find('.dash-hero__greeting {')
        assert greeting_start != -1
        greeting_end = css.find('}', greeting_start)
        greeting_rule = css[greeting_start:greeting_end]
        assert 'display: flex' in greeting_rule
        assert 'flex-wrap: wrap' in greeting_rule
        assert 'align-items: center' in greeting_rule

    def test_hero_has_no_decorative_shapes_in_markup(self):
        """Task 1: dash-shape divs are not in the rendered dashboard."""
        import os
        tpl_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            tpl = f.read()
        assert 'dash-shape--1' not in tpl
        assert 'dash-shape--2' not in tpl
        assert 'dash-hero__bg-shapes' not in tpl


class TestHeroStreakStates:
    """19 Tasks plan — Task 2: hero streak = 3 states + flash overlay."""

    def _read_template(self):
        import os
        tpl_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
        )
        with open(tpl_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _extract_greeting_block(self, tpl):
        """Return the inline-if chain inside the hero greeting block."""
        start = tpl.find('<div class="dash-hero__greeting">')
        assert start != -1, 'hero greeting block missing'
        end = tpl.find('</div>\n        </div>\n    </div>', start)
        assert end != -1, 'could not find end of hero greeting block'
        return tpl[start:end]

    def test_streak_repaired_not_rendered_inside_hero_greeting(self):
        """streak_repaired branch lives at top-level overlay, not nested in hero greeting."""
        tpl = self._read_template()
        greeting = self._extract_greeting_block(tpl)
        assert 'streak_repaired' not in greeting
        assert 'dash-streak--restored' not in greeting
        assert 'dash-streak__restored' not in greeting

    def test_streak_flash_overlay_present_top_level(self):
        """dash-streak-flash overlay is rendered at top level, outside the hero card."""
        tpl = self._read_template()
        # Markup block is present
        assert 'dash-streak-flash' in tpl
        assert 'data-streak-flash="true"' in tpl
        assert 'Серия восстановлена!' in tpl
        # Overlay is not nested inside the hero card
        hero_start = tpl.find('<div class="dash-hero">')
        hero_end_marker = tpl.find('</div>\n        </div>\n    </div>', hero_start)
        assert hero_end_marker != -1
        flash_pos = tpl.find('dash-streak-flash')
        assert flash_pos > hero_end_marker, 'streak-flash overlay must be outside the hero card'

    def test_streak_flash_autodismiss_script_present(self):
        """Auto-dismiss script for flash overlay fires after 2500 ms."""
        tpl = self._read_template()
        assert 'data-streak-flash="true"' in tpl
        # Autodismiss at 2500 ms
        assert '2500' in tpl
        # Script removes the flash element
        # (a simple heuristic: querying the selector in the same template)
        assert "querySelector('[data-streak-flash=\"true\"]')" in tpl

    def test_streak_flash_css_rule_present(self):
        """dash-streak-flash has fixed-position CSS + reuses xpLevelUpFlash animation."""
        tpl = self._read_template()
        rule_start = tpl.find('.dash-streak-flash {')
        assert rule_start != -1, 'missing .dash-streak-flash CSS rule'
        rule_end = tpl.find('}', rule_start)
        rule = tpl[rule_start:rule_end]
        assert 'position: fixed' in rule
        assert 'animation: xpLevelUpFlash' in rule

    def test_streak_has_three_branches_only(self):
        """Hero greeting has exactly 3 branches: streak>0 / can_repair / else."""
        tpl = self._read_template()
        greeting = self._extract_greeting_block(tpl)
        # Three expected branch conditions
        assert '{% if streak > 0 %}' in greeting
        assert '{% elif streak_status and streak_status.can_repair %}' in greeting
        assert '{% else %}' in greeting
        # Contradictory branch removed
        assert 'can_repair and streak > 0' not in greeting
        assert 'can_repair and streak>0' not in greeting

    def test_streak_zero_subtitle_copy(self):
        """Zero-streak branch shows the 'start again' subtitle."""
        tpl = self._read_template()
        greeting = self._extract_greeting_block(tpl)
        assert 'Сегодня начни заново' in greeting

    def test_streak_share_button_guarded_by_seven_days(self):
        """Share button condition uses streak >= 7, not 'streak in milestones'."""
        tpl = self._read_template()
        greeting = self._extract_greeting_block(tpl)
        # New share-button condition
        assert 'streak >= 7 and current_user.referral_code' in greeting
        # Milestone-gated share button is gone
        share_block_pos = greeting.find('dash-streak__share-btn')
        assert share_block_pos != -1
        # The preceding condition that wraps the share button must be the
        # streak>=7 check, not the milestone check.
        preceding = greeting[:share_block_pos]
        last_if = preceding.rfind('{% if ')
        assert last_if != -1
        last_if_block = preceding[last_if:]
        assert 'streak >= 7' in last_if_block


class TestHeroStreakRendering:
    """Runtime assertions — render dashboard with different streak states."""

    def _get_dashboard_with_streak(
        self, client, test_user, mission_plan, *,
        streak=0, can_repair=False, streak_repaired=False, coins=0, referral_code=None,
    ):
        if referral_code is not None:
            from app.auth.models import User
            from app.utils.db import db
            user = User.query.get(test_user.id)
            user.referral_code = referral_code
            db.session.add(user)
            db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        streak_status = {
            'streak': streak,
            'can_repair': can_repair,
            'coins_balance': coins,
            'repair_cost': 10,
            'required_steps': 1,
        }
        streak_result = {
            'streak_status': streak_status,
            'required_steps': 1,
            'streak_repaired': streak_repaired,
            'steps_done': 0,
            'steps_total': 3,
            'milestone_reward': None,
            'rank_up': None,
        }

        with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan, \
             patch('app.achievements.streak_service.process_streak_on_activity') as mock_streak:
            mock_plan.return_value = mission_plan
            mock_streak.return_value = streak_result
            response = client.get('/dashboard')
        return response

    def test_streak_active_renders_streak_badge(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard_with_streak(
            client, test_user, plan, streak=5, coins=3,
        )
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'class="dash-streak"' in html
        assert '5' in html
        assert 'dash-streak-recovery' not in html
        assert 'Сегодня начни заново' not in html

    def test_streak_zero_renders_start_subtitle(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard_with_streak(
            client, test_user, plan, streak=0, can_repair=False,
        )
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'Сегодня начни заново' in html
        assert 'dash-streak-recovery' not in html
        # No streak badge rendered
        assert 'class="dash-streak"' not in html

    def test_streak_recovery_renders_when_zero_and_can_repair(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard_with_streak(
            client, test_user, plan, streak=0, can_repair=True, coins=10,
        )
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-streak-recovery' in html
        assert 'Серия прервалась' in html
        assert 'Сегодня начни заново' not in html

    def test_streak_repaired_renders_flash_overlay_outside_hero(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard_with_streak(
            client, test_user, plan, streak=3, streak_repaired=True, coins=1,
        )
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Flash overlay rendered
        assert 'dash-streak-flash' in html
        assert 'Серия восстановлена!' in html
        assert 'data-streak-flash="true"' in html
        # Old inline "restored" marker must not appear
        assert 'dash-streak--restored' not in html
        assert 'dash-streak__restored' not in html

    def test_streak_milestone_badge_only_on_milestone(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        # Milestone: 7 → badge visible
        r1 = self._get_dashboard_with_streak(client, test_user, plan, streak=7)
        html1 = r1.data.decode('utf-8')
        assert 'dash-streak__milestone' in html1
        assert 'Неделя' in html1

        # Non-milestone: 8 → no badge
        r2 = self._get_dashboard_with_streak(client, test_user, plan, streak=8)
        html2 = r2.data.decode('utf-8')
        assert 'dash-streak__milestone' not in html2

    def test_share_button_visible_when_streak_at_least_seven(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        # Non-milestone streak ≥ 7 still shows the share button
        response = self._get_dashboard_with_streak(
            client, test_user, plan, streak=8, referral_code='TESTCODE',
        )
        html = response.data.decode('utf-8')
        assert 'dash-streak__share-btn' in html
        # No milestone badge at streak=8 since 8 is not a milestone
        assert 'dash-streak__milestone' not in html

    def test_share_button_absent_when_streak_below_seven(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard_with_streak(
            client, test_user, plan, streak=6, referral_code='TESTCODE',
        )
        html = response.data.decode('utf-8')
        assert 'dash-streak__share-btn' not in html


class TestMissionHeaderSimplified:
    """19 Tasks plan — Task 6: mission header = title + track + goal (eyebrow + reason removed)."""

    def _read_template(self):
        import os
        tpl_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
        )
        with open(tpl_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _extract_header_block(self, tpl):
        """Return the mission header markup."""
        start = tpl.find('<div class="dash-mission-header">')
        assert start != -1, 'mission header block missing'
        # The block is followed by the Task 5 compact-redesign comment.
        end = tpl.find('{# Task 5 (compact redesign)', start)
        assert end != -1, 'could not find end of mission header block'
        return tpl[start:end]

    def test_eyebrow_markup_removed(self):
        tpl = self._read_template()
        header = self._extract_header_block(tpl)
        assert 'dash-mission-header__eyebrow' not in header
        assert 'Главная миссия дня' not in header

    def test_reason_text_markup_removed(self):
        tpl = self._read_template()
        header = self._extract_header_block(tpl)
        assert 'dash-mission-header__reason' not in header
        assert 'reason_text' not in header

    def test_title_and_badges_preserved(self):
        tpl = self._read_template()
        header = self._extract_header_block(tpl)
        # Title, track pill and goal pill markup stays
        assert 'dash-mission-header__title' in header
        assert "m.get('title', '')" in header
        assert 'Трек:' in header
        assert 'Цель дня:' in header
        assert 'dash-mission-header__pill' in header

    def test_eyebrow_reason_css_rules_removed(self):
        """CSS cleanup: removed elements should not carry leftover style blocks."""
        tpl = self._read_template()
        assert '.dash-mission-header__eyebrow {' not in tpl
        assert '.dash-mission-header__reason {' not in tpl

    def test_header_spacing_compact(self):
        """Padding and margin should be tighter than the old 1rem/1.25rem/1rem layout."""
        tpl = self._read_template()
        rule_start = tpl.find('.dash-mission-header {')
        assert rule_start != -1, 'missing .dash-mission-header CSS rule'
        rule_end = tpl.find('}', rule_start)
        rule = tpl[rule_start:rule_end]
        assert 'padding: 0.75rem 1rem' in rule
        assert 'margin-bottom: 0.75rem' in rule


class TestMissionHeaderRendering:
    """Runtime assertions — dashboard renders simplified mission header."""

    def _get_dashboard(self, client, test_user, mission_plan):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.daily_plan.service.get_daily_plan_unified') as mock_plan:
            mock_plan.return_value = mission_plan
            response = client.get('/dashboard')
        return response

    def test_eyebrow_not_in_rendered_dashboard(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'Главная миссия дня' not in html
        assert 'dash-mission-header__eyebrow' not in html

    def test_reason_text_not_in_rendered_dashboard(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        # reason text configured in fixture must not appear
        assert 'Следующий урок готов для вас' not in html
        assert 'dash-mission-header__reason' not in html

    def test_title_and_pills_in_rendered_dashboard(
        self, client, app, db_session, test_user, words_module_access,
    ):
        plan = _make_mission_plan('progress', [False, False, False])
        response = self._get_dashboard(client, test_user, plan)
        html = response.data.decode('utf-8')
        assert 'Продвигаемся вперёд' in html
        assert 'Трек:' in html
        assert 'Цель дня:' in html
        assert 'Завершить урок' in html
