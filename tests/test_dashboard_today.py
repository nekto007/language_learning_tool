"""The focused dashboard keeps the server's queue and completion semantics."""
import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader

from tests.test_dashboard_ux_audit import _base_plan, _build_env

pytestmark = pytest.mark.smoke


def task(number: int, **overrides) -> dict:
    return {
        'id': f'task:{number}', 'title': f'Задание {number}', 'kind': 'curriculum',
        'lesson_type': 'grammar', 'url': f'/lesson/{number}', 'eta_minutes': 5,
        'completed': False, 'skipped': False, 'blocked': False, 'data': {},
        **overrides,
    }


def focused(plan: dict, completion: dict | None = None) -> BeautifulSoup:
    env = _build_env()
    markup = env.get_template('partials/unified_daily_plan.html').render(
        unified_plan=plan, plan_completion=completion or {}, dashboard_today=True,
    )
    return BeautifulSoup(markup, 'html.parser')


def test_one_header_uses_live_completion_and_only_current_step_is_actionable():
    page = focused(_base_plan(required=[task(1), task(2), task(3)]), {'task:1': True})
    assert len(page.select('h1')) == 1
    assert 'Выполнено 1 из 3' in page.get_text()
    assert 'примерно 10 мин' in page.get_text()
    assert page.select_one('.today-header [role=progressbar]')['aria-valuenow'] == '1'
    assert page.select_one('[data-state=current] .plan-item__cta')['href'] == '/lesson/2'
    assert not page.select_one('[data-state=locked]').select('a')
    assert not page.select('.daily-plan__header, .daily-plan__goals, .daily-plan__counter')


def test_grammar_task_keeps_its_name_instead_of_repeating_module_title():
    page = focused(_base_plan(required=[task(1, title='Множественное число', data={'module_title': 'Числа и цвета'})]))
    assert page.select_one('.plan-item__title').get_text() == 'Множественное число'


def test_large_review_backlog_is_under_disclosure_and_goal_stays_unchanged():
    page = focused(_base_plan(required=[task(1, kind='srs', title='Повторение слов — 30', data={
        'overdue_reviews': 431, 'reason_hint': 'Порция из 15 повторений.',
        'goal_total': 30, 'reviews_today': 4, 'new_today': 2,
    })]))
    details = page.select_one('.today-review-details')
    assert details and not details.has_attr('open')
    assert '431' in details.get_text()
    assert 'Долг:' not in page.get_text()
    assert '6 из 30 карточек' in page.get_text()
    assert page.select_one('.plan-item__cta')['href'] == '/lesson/1'


@pytest.mark.parametrize('flags, state', [({'skipped': True}, 'skipped'), ({'blocked': True}, 'blocked')])
def test_skipped_and_blocked_are_not_completed_or_selected_as_primary(flags: dict, state: str):
    page = focused(_base_plan(required=[task(1, **flags), task(2)]))
    assert 'Выполнено 0 из 2' in page.get_text()
    assert page.select_one(f'[data-state={state}]')
    assert page.select_one('[data-state=current] .plan-item__cta')['href'] == '/lesson/2'
    if state == 'blocked':
        assert not page.select_one('[data-state=blocked]').select('a')


def test_skip_controls_and_server_allowance_are_preserved():
    page = focused(_base_plan(required=[task(1, kind='srs', data={
        'slot_skip_allowed': True, 'slot_skips_remaining': 1,
    })]))
    assert page.select_one('button[data-skip-kind=srs]')
    assert len(page.select('[data-skip-reasons=srs] button[data-reason]')) == 3


@pytest.mark.parametrize('settled, secured, empty, unlocked', [
    (False, False, False, False), (True, False, False, True),
    (False, True, False, True), (False, False, True, True),
])
def test_extra_disclosure_does_not_change_queue_unlock_rules(settled: bool, secured: bool, empty: bool, unlocked: bool):
    required = [] if empty else [task(1, skipped=settled, completed=secured)]
    optional = [task(n) for n in range(2, 7)]
    page = focused(_base_plan(required=required, optional=optional, day_secured=secured))
    assert bool(page.select_one('.today-extra .plan-item__cta')) == unlocked
    assert page.select_one('[data-item-id="task:3"]')['data-locked'] == 'true'
    assert not page.select_one('[data-item-id="task:3"]').select('a')
    assert len(page.select('[data-optional-overflow=true][hidden]')) == 2
    assert page.select_one('[data-action=expand-optional]')


def test_secured_header_is_explicit_even_without_required_items():
    page = focused(_base_plan(day_secured=True))
    assert 'На сегодня всё получилось!' in page.get_text()
    assert not page.select('.plan-item--current')
    assert not page.select('.daily-plan__celebration')
    assert 'Завершите настройку' not in page.get_text()


def test_blocked_empty_plan_preserves_prerequisite_explanation():
    page = focused(_base_plan(blocked_module={'module_title': 'Новый модуль', 'reasons': ['Завершите предыдущий модуль']}))
    assert 'Завершите предыдущий модуль' in page.get_text()


def test_next_module_is_identified_without_changing_lesson_link():
    page = focused(_base_plan(day_secured=True, module_progress={'module_title': 'Числа'}, optional=[task(2, data={
        'module_title': 'Комната', 'module_number': 5,
    })]))
    assert 'Модуль 5 · Комната' in page.select_one('.today-module-label').get_text()
    assert page.select_one('.plan-item__cta')['href'] == '/lesson/2'


def test_full_dashboard_has_one_queue_and_quiet_links_instead_of_competing_widgets():
    env = _build_env()
    env.loader = ChoiceLoader([DictLoader({'base.html': '{% block extra_css %}{% endblock %}{% block content %}{% endblock %}'}), env.loader])
    plan = _base_plan(required=[task(1), task(2)])
    output = env.get_template('words/dashboard_unified.html').render(
        unified_plan=plan, plan_completion={}, stats_card={}, study_start=None,
        week_rhythm={}, achievements_by_category={},
    )
    page = BeautifulSoup(output, 'html.parser')
    assert len(page.select('[data-daily-plan=true]')) == 1
    assert len(page.select('.plan-item__cta--button')) == 1
    assert len(page.select('h1')) == 1
    assert not page.select('.dash-rank--band, .dash-leaderboard__list, .dash-achievements__goal, .wset-rail__cta')
    assert page.select_one('a[href="/stub/study.achievements"]')
    assert page.select_one('a[href="/stub/study.stats"]')
