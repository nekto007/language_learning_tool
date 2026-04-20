"""Render tests for partials/linear_daily_plan.html (Task 10).

These tests exercise the partial via the app's Jinja environment with
mock linear-plan payloads — no DB, no full dashboard route — so they
stay tight and focused on the template's own logic (header, slot
states, continuation CTA/preview, empty states). An integration test
through the dashboard route lives in tests/smoke/test_linear_dashboard_smoke.py
(Task 12).
"""
from __future__ import annotations

import pytest


def _render(app, context: dict) -> str:
    """Render the linear partial with the given context."""
    env = app.jinja_env
    template = env.get_template('partials/linear_daily_plan.html')
    return template.render(**context)


def _base_position(**overrides) -> dict:
    base = {
        'lesson_id': 101,
        'lesson_type': 'card',
        'lesson_number': 3,
        'module_id': 7,
        'module_number': 5,
        'level_code': 'A2',
    }
    base.update(overrides)
    return base


def _base_progress(**overrides) -> dict:
    base = {
        'level': 'A2',
        'percent': 40,
        'lessons_remaining_in_level': 30,
        'lessons_remaining_to_next_level': 30,
    }
    base.update(overrides)
    return base


def _slot(kind: str, *, completed: bool = False, url: str | None = None,
          title: str | None = None, eta: int = 10, data: dict | None = None,
          lesson_type: str | None = None) -> dict:
    return {
        'kind': kind,
        'title': title if title is not None else f'{kind} title',
        'lesson_type': lesson_type,
        'eta_minutes': eta,
        'url': url,
        'completed': completed,
        'data': data or {},
    }


_UNSET = object()


def _plan(*, slots: list[dict], position=_UNSET,
          progress=_UNSET, next_lessons: list[dict] | None = None,
          day_secured: bool = False) -> dict:
    return {
        'mode': 'linear',
        'position': _base_position() if position is _UNSET else position,
        'progress': _base_progress() if progress is _UNSET else progress,
        'baseline_slots': slots,
        'continuation': {
            'available': day_secured,
            'next_lessons': next_lessons or [],
        },
        'day_secured': day_secured,
    }


class TestLinearPlanHeader:
    def test_position_chip_shows_level_module_lesson(self, app):
        plan = _plan(slots=[
            _slot('curriculum', lesson_type='card',
                  url='/learn/101/?from=linear_plan&source=linear_plan_card'),
            _slot('srs', data={'due_count': 5}),
            _slot('reading', data={'needs_selection': True}),
        ])
        html = _render(app, {
            'linear_plan': plan,
            'plan_completion': {},
        })
        assert 'data-linear-plan="true"' in html
        assert 'A2' in html
        assert 'M5' in html
        assert 'L3' in html

    def test_lesson_type_shown_near_position(self, app):
        plan = _plan(slots=[_slot('curriculum', lesson_type='grammar',
                                  url='/learn/1/?from=linear_plan')])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        # Russian label for grammar lesson type
        assert 'Грамматика' in html

    def test_no_position_when_curriculum_complete(self, app):
        plan = _plan(
            slots=[_slot('curriculum', completed=True, url=None, title='Курс пройден')],
            position=None,
        )
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-position="complete"' in html
        assert 'Курс пройден' in html

    def test_level_progress_bar_rendered(self, app):
        plan = _plan(
            slots=[_slot('curriculum', url='/u')],
            progress=_base_progress(percent=65, lessons_remaining_in_level=12),
        )
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-progress="true"' in html
        assert 'width: 65%' in html
        assert '12' in html
        # Pluralization: 12 → уроков
        assert 'уроков' in html

    def test_level_progress_single_lesson_pluralization(self, app):
        plan = _plan(
            slots=[_slot('curriculum', url='/u')],
            progress=_base_progress(percent=99, lessons_remaining_in_level=1),
        )
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'осталось 1' in html
        assert 'урок' in html


class TestLinearPlanSlots:
    def test_three_slots_rendered_with_correct_states(self, app):
        plan = _plan(slots=[
            _slot('curriculum', completed=True, url='/learn/1/'),
            _slot('srs', url='/study?source=linear_plan', data={'due_count': 4}),
            _slot('reading', data={'needs_selection': True}),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        # First slot: done
        assert 'linear-slot--done' in html
        # Second slot: current (first incomplete)
        assert 'linear-slot--current' in html
        # Third slot: pending (not current, not done)
        assert 'linear-slot--pending' in html

    def test_slot_order_preserved(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', url='/s', data={'due_count': 5}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        i_curr = html.index('data-slot-kind="curriculum"')
        i_srs = html.index('data-slot-kind="srs"')
        i_read = html.index('data-slot-kind="reading"')
        assert i_curr < i_srs < i_read

    def test_reading_slot_select_book_triggers_modal(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', url='/s', data={'due_count': 1}),
            _slot('reading', url='#book-select-modal', title='Выбрать книгу',
                  data={'needs_selection': True}),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-action="select-book"' in html
        assert 'href="#book-select-modal"' in html
        assert 'Выбрать книгу' in html

    def test_reading_slot_with_book_shows_chapter_info(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', data={'due_count': 0}),
            _slot('reading', url='/read/42?from=linear_plan',
                  title='The Hobbit',
                  data={
                      'book_id': 42,
                      'book_title': 'The Hobbit',
                      'current_chapter_num': 3,
                      'current_chapter_title': 'Riddles in the Dark',
                      'needs_selection': False,
                  }),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'The Hobbit' in html
        assert 'Глава 3' in html
        assert 'Riddles in the Dark' in html

    def test_four_slots_render_error_review(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', url='/s', data={'due_count': 3}),
            _slot('reading', url='/r'),
            _slot('error_review', url='/learn/error-review?from=linear_plan',
                  title='Разбор ошибок (10)',
                  data={'unresolved_count': 12, 'pool_size': 10}),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-slot-kind="error_review"' in html
        assert 'Разбор ошибок' in html
        assert 'Неразобранных ошибок: 12' in html

    def test_completed_slot_hides_action_button(self, app):
        plan = _plan(slots=[
            _slot('curriculum', completed=True, url='/c', title='Done lesson'),
            _slot('srs', url='/s', data={'due_count': 3}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'Готово' in html
        # The done badge should appear, no Начать/Открыть button for the first slot's action.
        first_slot = html.split('data-slot-kind="srs"')[0]
        assert 'linear-slot__btn' not in first_slot

    def test_current_slot_uses_primary_cta(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/learn/1/?from=linear_plan'),
            _slot('srs', url='/study', data={'due_count': 1}),
            _slot('reading', url='/read/1'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'linear-slot__btn--primary' in html
        assert 'Начать' in html

    def test_plan_completion_promotes_slot_to_done(self, app):
        """When plan_completion flags a kind done, the slot renders as done
        even if the raw slot.completed is False (mirrors the mission flow)."""
        plan = _plan(slots=[
            _slot('curriculum', completed=False, url='/c'),
            _slot('srs', url='/s', data={'due_count': 3}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {
            'linear_plan': plan,
            'plan_completion': {'curriculum': True},
        })
        assert 'linear-slot--done' in html
        # Current becomes the srs slot now that curriculum is promoted.
        first_current = html.split('linear-slot--current')[0]
        assert 'data-slot-kind="curriculum"' in first_current


class TestLinearPlanProgressSummary:
    def test_progress_bar_counts_done_over_total(self, app):
        plan = _plan(slots=[
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', data={'due_count': 0}, completed=True),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-summary="true"' in html
        assert '>2/3<' in html
        assert 'width: 66%' in html

    def test_secured_banner_when_all_slots_done(self, app):
        plan = _plan(
            slots=[
                _slot('curriculum', completed=True, url='/c'),
                _slot('srs', completed=True),
                _slot('reading', completed=True, url='/r'),
            ],
            day_secured=True,
            next_lessons=[{
                'lesson_id': 102,
                'lesson_type': 'grammar',
                'lesson_number': 4,
                'module_number': 5,
                'level_code': 'A2',
            }],
        )
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-secured="true"' in html
        assert '3/3' in html
        assert 'linear-plan__summary-fill--done' in html


class TestLinearPlanContinuation:
    def test_continuation_hidden_when_not_secured(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', data={'due_count': 1}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-continuation="true"' not in html

    def test_continuation_cta_and_preview_when_secured(self, app):
        next_lessons = [
            {'lesson_id': 102, 'lesson_type': 'grammar',
             'lesson_number': 4, 'module_number': 5, 'level_code': 'A2'},
            {'lesson_id': 103, 'lesson_type': 'quiz',
             'lesson_number': 5, 'module_number': 5, 'level_code': 'A2'},
            {'lesson_id': 104, 'lesson_type': 'reading',
             'lesson_number': 6, 'module_number': 5, 'level_code': 'A2'},
        ]
        plan = _plan(
            slots=[
                _slot('curriculum', completed=True, url='/c'),
                _slot('srs', completed=True),
                _slot('reading', completed=True, url='/r'),
            ],
            day_secured=True,
            next_lessons=next_lessons,
        )
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-continuation="true"' in html
        # Primary CTA points at the first upcoming lesson.
        assert '/learn/102/?from=linear_plan_continuation' in html
        # Preview list contains all three next lessons.
        assert '/learn/102/?from=linear_plan_preview' in html
        assert '/learn/103/?from=linear_plan_preview' in html
        assert '/learn/104/?from=linear_plan_preview' in html
        # CTA label and lesson types are humanised.
        assert 'Следующий урок' in html
        assert 'Грамматика' in html
        assert 'Квиз' in html

    def test_continuation_hidden_when_secured_but_no_next_lessons(self, app):
        plan = _plan(
            slots=[
                _slot('curriculum', completed=True, url='/c'),
                _slot('srs', completed=True),
                _slot('reading', completed=True, url='/r'),
            ],
            day_secured=True,
            next_lessons=[],
        )
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-continuation="true"' not in html


class TestLinearPlanEmptyState:
    def test_empty_slots_show_fallback(self, app):
        plan = _plan(slots=[])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'linear-plan__empty' in html
        assert 'ещё формируется' in html


class TestBookSelectModalPresent:
    """The modal lives in dashboard.html itself (rendered for everyone) so
    the linear partial can trigger it via href="#book-select-modal"."""

    def test_modal_markup_lives_in_dashboard_template(self, app):
        env = app.jinja_env
        source = env.loader.get_source(env, 'dashboard.html')[0]
        assert 'id="book-select-modal"' in source
        assert 'linear-modal__panel' in source
        assert 'book-select-modal-list' in source
        assert 'linear-daily-plan.js' in source

    def test_partial_included_behind_linear_plan_flag(self, app):
        env = app.jinja_env
        source = env.loader.get_source(env, 'dashboard.html')[0]
        assert "{% if linear_plan %}" in source
        assert "'partials/linear_daily_plan.html'" in source
