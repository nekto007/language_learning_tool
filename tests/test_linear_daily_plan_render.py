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
          day_secured: bool = False,
          chain_extensions: list[dict] | None = None) -> dict:
    extensions = list(chain_extensions or [])
    all_slots = list(slots) + extensions
    return {
        'mode': 'linear',
        'position': _base_position() if position is _UNSET else position,
        'progress': _base_progress() if progress is _UNSET else progress,
        'baseline_slots': slots,
        'slots': all_slots,
        'chain_meta': {
            'baseline_count': len(slots),
            'has_more_available': bool(extensions),
            'exhausted_sources': [],
        },
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
        # Third slot: locked (not current, not done) — sequential chain
        assert 'linear-slot--locked' in html
        assert 'data-linear-locked="true"' in html

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
        # Reading slot needs to be current (or at least not locked) for the
        # select-book CTA to render — earlier chain slots are completed here.
        plan = _plan(slots=[
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', completed=True, url='/s', data={'due_count': 1}),
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
            _slot('error_review', url='/learn/error-review/?from=linear_plan',
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

    def test_locked_slots_appear_after_current(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', url='/s', data={'due_count': 3}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        # Only the first incomplete slot is current; the rest are locked.
        assert html.count('linear-slot--current') == 1
        assert html.count('linear-slot--locked') == 2
        # Locked slots show the lock badge text instead of an action link.
        assert 'Откроется после завершения предыдущего' in html
        # Locked slots do NOT render Start/Open buttons.
        srs_slot = html.split('data-slot-kind="srs"')[1].split('data-slot-kind="reading"')[0]
        assert 'linear-slot__btn' not in srs_slot
        assert 'data-linear-locked="true"' in srs_slot

    def test_completing_first_slot_shifts_current_and_locked(self, app):
        """When the first slot completes, the second becomes current and the
        third becomes locked — sequential chain progression."""
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', url='/s', data={'due_count': 3}),
            _slot('reading', url='/r'),
        ])
        # Promote curriculum via plan_completion to simulate finishing it.
        html = _render(app, {
            'linear_plan': plan,
            'plan_completion': {'curriculum': True},
        })
        # First → done, second → current, third → locked.
        first_current_pos = html.index('linear-slot--current')
        first_done_pos = html.index('linear-slot--done')
        first_locked_pos = html.index('linear-slot--locked')
        assert first_done_pos < first_current_pos < first_locked_pos
        # The locked slot is the reading slot (last in the chain).
        reading_segment = html.split('data-slot-kind="reading"')[1]
        assert 'data-slot-state="locked"' in reading_segment

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
        assert 'data-plan-celebration="true"' in html
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
        # When baseline is closed, the chain extension targeting the next
        # spine lesson is the inline next-action. continuation.next_lessons
        # is a *preview* of lessons that come after that extension.
        next_lessons = [
            {'lesson_id': 103, 'lesson_type': 'quiz',
             'lesson_number': 5, 'module_number': 5, 'level_code': 'A2'},
            {'lesson_id': 104, 'lesson_type': 'reading',
             'lesson_number': 6, 'module_number': 5, 'level_code': 'A2'},
        ]
        extension = _slot(
            'curriculum',
            url='/learn/102/?from=linear_plan_continuation',
            lesson_type='grammar',
            data={
                'lesson_id': 102,
                'lesson_number': 4,
                'module_number': 5,
                'level_code': 'A2',
                'extension': True,
            },
        )
        plan = _plan(
            slots=[
                _slot('curriculum', completed=True, url='/c'),
                _slot('srs', completed=True),
                _slot('reading', completed=True, url='/r'),
            ],
            chain_extensions=[extension],
            day_secured=True,
            next_lessons=next_lessons,
        )
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-continuation="true"' in html
        # Primary CTA points at the chain extension URL (first incomplete
        # chain slot pointing at the next curriculum lesson).
        assert '/learn/102/?from=linear_plan_continuation' in html
        # Preview list contains the lessons after the inline chain extension.
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


class TestWeakGrammarPill:
    def test_pill_renders_when_hint_present(self, app):
        plan = _plan(slots=[
            _slot('curriculum', lesson_type='grammar', url='/learn/1/?from=linear_plan',
                  data={
                      'lesson_id': 1,
                      'weak_topic_hint': True,
                      'weak_topic_id': 42,
                      'weak_topic_name': 'Present Perfect',
                      'weak_topic_accuracy': 0.4,
                  }),
            _slot('srs', data={'due_count': 1}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'linear-slot__pill--weak-grammar' in html
        assert 'Слабая тема: Present Perfect' in html
        assert 'data-weak-grammar-topic-id="42"' in html

    def test_pill_hidden_when_hint_absent(self, app):
        plan = _plan(slots=[
            _slot('curriculum', lesson_type='grammar', url='/learn/1/?from=linear_plan',
                  data={'lesson_id': 1}),
            _slot('srs', data={'due_count': 1}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'linear-slot__pill--weak-grammar' not in html
        assert 'Слабая тема' not in html

    def test_pill_hidden_when_only_flag_without_name(self, app):
        plan = _plan(slots=[
            _slot('curriculum', lesson_type='grammar', url='/learn/1/?from=linear_plan',
                  data={'weak_topic_hint': True}),
            _slot('srs', data={'due_count': 1}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'linear-slot__pill--weak-grammar' not in html


class TestLinearPlanChainExtension:
    def test_baseline_header_renders_when_slots_present(self, app):
        plan = _plan(slots=[
            _slot('curriculum', url='/c'),
            _slot('srs', data={'due_count': 1}),
            _slot('reading', url='/r'),
        ])
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-chain-header="baseline"' in html
        assert 'Минимум на день' in html

    def test_chain_length_attribute_reflects_total(self, app):
        slots = [
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', completed=True, data={'due_count': 0}),
            _slot('reading', completed=True, url='/r'),
            _slot('curriculum', url='/c2', title='Extra lesson'),
        ]
        plan = _plan(slots=slots, day_secured=True)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': True,
            'exhausted_sources': [],
        }
        plan['baseline_slots'] = slots[:3]
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-chain-length="4"' in html
        assert 'data-linear-baseline-count="3"' in html

    def test_divider_renders_between_baseline_and_extension(self, app):
        slots = [
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', completed=True, data={'due_count': 0}),
            _slot('reading', completed=True, url='/r'),
            _slot('curriculum', url='/c2', title='Bonus lesson'),
        ]
        plan = _plan(slots=slots[:3], day_secured=True)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': True,
            'exhausted_sources': [],
        }
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-chain-divider="extension"' in html
        assert 'Дальше необязательно' in html
        # Divider sits before the extension slot, after the baseline ones.
        divider_pos = html.index('data-linear-chain-divider="extension"')
        bonus_pos = html.index('Bonus lesson')
        first_slot_pos = html.index('data-slot-kind="curriculum"')
        assert first_slot_pos < divider_pos < bonus_pos

    def test_divider_hidden_when_chain_equals_baseline(self, app):
        slots = [
            _slot('curriculum', url='/c'),
            _slot('srs', data={'due_count': 1}),
            _slot('reading', url='/r'),
        ]
        plan = _plan(slots=slots)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': True,
            'exhausted_sources': [],
        }
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-chain-divider' not in html

    def test_exhausted_block_renders_when_secured_and_no_more(self, app):
        slots = [
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', completed=True, data={'due_count': 0}),
            _slot('reading', completed=True, url='/r'),
        ]
        plan = _plan(slots=slots, day_secured=True)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': False,
            'exhausted_sources': ['curriculum', 'srs', 'reading', 'error_review'],
        }
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-chain-exhausted="true"' in html
        assert 'На сегодня источники исчерпаны' in html

    def test_exhausted_block_hidden_when_not_secured(self, app):
        slots = [
            _slot('curriculum', url='/c'),
            _slot('srs', data={'due_count': 1}),
            _slot('reading', url='/r'),
        ]
        plan = _plan(slots=slots)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': False,
            'exhausted_sources': [],
        }
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-chain-exhausted' not in html

    def test_exhausted_block_hidden_when_more_available(self, app):
        slots = [
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', completed=True, data={'due_count': 0}),
            _slot('reading', completed=True, url='/r'),
        ]
        plan = _plan(slots=slots, day_secured=True)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': True,
            'exhausted_sources': [],
        }
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        assert 'data-linear-chain-exhausted' not in html

    def test_extension_slot_not_completed_by_plan_completion_kind(self, app):
        """plan_completion is keyed by kind and only describes baseline activity.

        Once baseline curriculum is done, plan_completion['curriculum']=True.
        That signal must not cascade to a freshly-appended pending curriculum
        extension slot — otherwise the bonus task appears already-done.
        """
        slots = [
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', completed=True, data={'due_count': 0}),
            _slot('reading', completed=True, url='/r'),
            _slot('curriculum', url='/c2', title='Bonus lesson'),
        ]
        plan = _plan(slots=slots[:3], day_secured=True)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': True,
            'exhausted_sources': [],
        }
        html = _render(app, {
            'linear_plan': plan,
            'plan_completion': {'curriculum': True, 'srs': True, 'reading': True},
        })
        # The extension slot must render as current (not completed).
        bonus_pos = html.index('Bonus lesson')
        # Find the slot wrapper that contains "Bonus lesson" — extension must
        # not carry the completed CSS class.
        snippet = html[max(0, bonus_pos - 800):bonus_pos]
        assert 'linear-slot--current' in snippet or 'data-slot-state="current"' in snippet
        assert 'linear-slot--completed' not in snippet

    def test_summary_counts_only_baseline_when_chain_extends(self, app):
        slots = [
            _slot('curriculum', completed=True, url='/c'),
            _slot('srs', completed=True, data={'due_count': 0}),
            _slot('reading', completed=True, url='/r'),
            _slot('curriculum', url='/c2', title='Bonus'),
        ]
        plan = _plan(slots=slots[:3], day_secured=True)
        plan['slots'] = slots
        plan['chain_meta'] = {
            'baseline_count': 3,
            'has_more_available': True,
            'exhausted_sources': [],
        }
        html = _render(app, {'linear_plan': plan, 'plan_completion': {}})
        # Summary stays on the minimum (baseline) count, not the chain length.
        assert '>3/3<' in html


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
        assert "linear_plan" in source
        assert "'partials/linear_daily_plan.html'" in source
