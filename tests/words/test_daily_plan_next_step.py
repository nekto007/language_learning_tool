"""Tests for _next_step_from_unified in app/words/routes.py.

Covers the unified-aware next-step handler that replaced _next_step_from_legacy:
(a) unified plan with mixed required/optional → returns first not-done item
(b) all required done, optional pending → returns first optional item
(c) all done → has_next=False, all_done=True with fallback_url
(d) item in plan_completion but item.completed=False → still treated as done
(e) blocked items are skipped
(f) items without url are skipped
(g) dispatcher routes unified mode to _next_step_from_unified, not legacy
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_item(
    item_id: str,
    kind: str = 'curriculum',
    title: str = 'Test Item',
    url: str = '/test-url',
    completed: bool = False,
    skipped: bool = False,
    blocked: bool = False,
) -> dict:
    return {
        'id': item_id,
        'kind': kind,
        'title': title,
        'url': url,
        'completed': completed,
        'skipped': skipped,
        'blocked': blocked,
        'section': 'required',
        'eta_minutes': 10,
        'completion_signal': 'lesson_completed',
        'subtitle': None,
        'data': {},
    }


def _make_unified_plan(required: list, optional: list | None = None) -> dict:
    return {
        'mode': 'unified',
        'required': required,
        'optional': optional or [],
        'setup': [],
        'day_secured': False,
        '_plan_meta': {'effective_mode': 'unified'},
    }


def _make_daily_summary() -> dict:
    return {
        'lessons_count': 0,
        'lessons_completed_today': 0,
        'grammar_exercises': 0,
        'words_reviewed': 0,
        'srs_words_reviewed': 0,
        'srs_review_reviewed': 0,
        'error_review_resolved_today': 0,
        'books_read': [],
    }


# ── Unit tests for _next_step_from_unified (via API endpoint) ────────────────

class TestNextStepFromUnified:
    """Tests for _next_step_from_unified via the /api/daily-plan/next-step endpoint."""

    def _call(self, client, plan, summary) -> dict:
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=summary):
            resp = client.get('/api/daily-plan/next-step')
        assert resp.status_code == 200
        return resp.get_json()

    def test_returns_first_required_not_done(self, authenticated_client):
        """Returns the first required item that is not done."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', kind='curriculum', title='Lesson 1', url='/lesson/1'),
            _make_item('srs:global', kind='srs', title='SRS Review', url='/study'),
        ])
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is True
        assert data['step_type'] == 'curriculum'
        assert data['step_title'] == 'Lesson 1'
        assert data['step_url'] == '/lesson/1'
        assert '🎯' in data['step_icon'] or '\U0001f3af' in data['step_icon']

    def test_skips_completed_required_returns_next(self, authenticated_client):
        """Skips the first required item if it's completed, returns second."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', completed=True, url='/lesson/1'),
            _make_item('srs:global', kind='srs', title='SRS Review', url='/study'),
        ])
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is True
        assert data['step_type'] == 'srs'
        assert data['step_url'] == '/study'

    def test_all_required_done_returns_first_optional(self, authenticated_client):
        """When all required are done, returns the first incomplete optional."""
        plan = _make_unified_plan(
            required=[_make_item('curriculum:lesson:1', completed=True)],
            optional=[_make_item('reading:42', kind='reading', title='Read Book', url='/books/42')],
        )
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is True
        assert data['step_type'] == 'reading'
        assert data['step_url'] == '/books/42'

    def test_all_done_returns_all_done_flag(self, authenticated_client):
        """Returns has_next=False and all_done=True when all items are complete."""
        plan = _make_unified_plan(
            required=[_make_item('curriculum:lesson:1', completed=True)],
            optional=[_make_item('reading:42', kind='reading', completed=True, url='/books/42')],
        )
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is False
        assert data['all_done'] is True
        assert 'fallback_url' in data

    def test_item_in_plan_completion_treated_as_done(self, authenticated_client):
        """Item in plan_completion (activity-based) is treated as done even if completed=False."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', completed=False),
            _make_item('srs:global', kind='srs', title='SRS', url='/study'),
        ])
        # Mark curriculum item done via activity (lessons_count > 0)
        summary = _make_daily_summary()
        summary['lessons_count'] = 1

        data = self._call(authenticated_client, plan, summary)

        assert data['has_next'] is True
        assert data['step_type'] == 'srs'

    def test_blocked_items_are_skipped(self, authenticated_client):
        """Blocked items are skipped; returns next non-blocked item."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', blocked=True, url='/lesson/1'),
            _make_item('srs:global', kind='srs', title='SRS', url='/study'),
        ])
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is True
        assert data['step_type'] == 'srs'

    def test_items_without_url_are_skipped(self, authenticated_client):
        """Items without a url are skipped."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', url=None),
            _make_item('srs:global', kind='srs', title='SRS', url='/study'),
        ])
        plan['required'][0] = dict(plan['required'][0], url=None)
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is True
        assert data['step_type'] == 'srs'

    def test_steps_done_and_total_counts_required_only(self, authenticated_client):
        """steps_done and steps_total reflect the required section count."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', completed=True),
            _make_item('srs:global', kind='srs', title='SRS', url='/study'),
        ])
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['steps_total'] == 2
        assert data['steps_done'] == 1

    def test_empty_plan_returns_all_done(self, authenticated_client):
        """Empty required and optional returns all_done=True."""
        plan = _make_unified_plan(required=[], optional=[])
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is False
        assert data['all_done'] is True

    def test_skipped_item_treated_as_done(self, authenticated_client):
        """Skipped items are treated as done and skipped over."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', skipped=True, url='/lesson/1'),
            _make_item('srs:global', kind='srs', title='SRS', url='/study'),
        ])
        data = self._call(authenticated_client, plan, _make_daily_summary())

        assert data['has_next'] is True
        assert data['step_type'] == 'srs'

    def test_icon_map_for_various_kinds(self, authenticated_client):
        """Icon is set correctly for each known kind."""
        expected_icons = {
            'curriculum': '\U0001f3af',
            'srs': '\U0001f4d6',
            'reading': '\U0001f4d5',
            'error_review': '\U0001f50d',
            'challenge': '\U0001f3c6',
            'grammar_review': '\U0001f9e0',
        }
        for kind, icon in expected_icons.items():
            plan = _make_unified_plan(required=[
                _make_item(f'{kind}:1', kind=kind, title=kind, url='/test'),
            ])
            data = self._call(authenticated_client, plan, _make_daily_summary())
            assert data['step_icon'] == icon, f"Wrong icon for kind={kind}"


class TestNextStepDispatcher:
    """Tests for the dispatcher routing in daily_plan_next_step."""

    def test_unified_mode_calls_unified_handler(self, authenticated_client):
        """unified mode plan routes through _next_step_from_unified, not legacy."""
        plan = _make_unified_plan(required=[
            _make_item('curriculum:lesson:1', kind='curriculum', title='Lesson', url='/lesson/1'),
        ])
        summary = _make_daily_summary()

        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=summary):
            resp = authenticated_client.get('/api/daily-plan/next-step')

        assert resp.status_code == 200
        data = resp.get_json()
        # Unified handler returns has_next=True for an incomplete item
        assert data['has_next'] is True
        assert data['step_type'] == 'curriculum'

    def test_non_unified_mode_falls_to_legacy_shim(self, authenticated_client):
        """Non-unified, non-mission plan falls through to the legacy no-op shim."""
        plan = {
            'mode': 'unknown_mode',
            'required': [],
            'optional': [],
            '_plan_meta': {'effective_mode': 'unknown_mode'},
        }
        summary = _make_daily_summary()

        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=summary):
            resp = authenticated_client.get('/api/daily-plan/next-step')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_next'] is False
        assert data['all_done'] is True
        assert 'fallback_url' in data
