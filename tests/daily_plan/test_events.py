"""Tests for slot skip event recording and plan skipped-slot integration.

Covers:
- slot_skipped event recorded via POST /api/daily-plan/events
- Invalid reason and slot kind return 400
- meta={kind, reason} format accepted
- _get_skipped_slot_kinds returns correct set
- compute_linear_day_secured: skipped != completed → not secured
- Template state machine: skipped slot unlocks the next slot
- DailyPlanEventType enum includes slot_skipped
"""
from __future__ import annotations

import pytest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_mock_event(step_kind='curriculum', reason_text='no_time', plan_date=None):
    ev = MagicMock()
    ev.step_kind = step_kind
    ev.reason_text = reason_text
    ev.plan_date = plan_date or date.today()
    return ev


def _make_slot(kind='curriculum', completed=False, skipped=False):
    return {
        'kind': kind,
        'title': f'{kind} title',
        'lesson_type': 'card',
        'eta_minutes': 10,
        'url': '/learn/1/?from=linear_plan',
        'completed': completed,
        'skipped': skipped,
        'data': {},
    }


def _compute_states(slots):
    """Replicate the Jinja template state machine logic in Python."""
    states = []
    current_found = False
    for slot in slots:
        if slot.get('completed'):
            states.append('done')
        elif slot.get('skipped'):
            states.append('skipped')
        elif not current_found:
            states.append('current')
            current_found = True
        else:
            states.append('locked')
    return states


# ── _CLIENT_EVENTS and constants ──────────────────────────────────────────────


class TestClientEventsSet:
    def test_slot_skipped_in_client_events(self, app):
        with app.app_context():
            from app.api.daily_plan import _CLIENT_EVENTS
            assert 'slot_skipped' in _CLIENT_EVENTS

    def test_skip_reasons_defined(self, app):
        with app.app_context():
            from app.api.daily_plan import _SKIP_REASONS
            assert _SKIP_REASONS == {'no_time', 'too_hard', 'not_today'}

    def test_skip_slot_kinds_covers_all_linear_kinds(self, app):
        with app.app_context():
            from app.api.daily_plan import _SKIP_SLOT_KINDS
            for kind in ('curriculum', 'srs', 'reading', 'listening', 'writing', 'error_review'):
                assert kind in _SKIP_SLOT_KINDS


# ── HTTP endpoint tests ───────────────────────────────────────────────────────


class TestSlotSkipEndpoint:
    def test_valid_skip_top_level_fields(self, authenticated_client, db_session):
        r = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'curriculum',
                'reason_text': 'no_time',
            },
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['event_type'] == 'slot_skipped'

    def test_valid_skip_meta_format(self, authenticated_client, db_session):
        r = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'meta': {'kind': 'srs', 'reason': 'too_hard'},
            },
        )
        assert r.status_code == 200

    def test_all_valid_reasons_accepted(self, authenticated_client, db_session):
        for reason in ('no_time', 'too_hard', 'not_today'):
            r = authenticated_client.post(
                '/api/daily-plan/events',
                json={
                    'event_type': 'slot_skipped',
                    'step_kind': 'reading',
                    'reason_text': reason,
                },
            )
            assert r.status_code == 200, f"reason={reason} returned {r.status_code}"

    def test_invalid_reason_returns_400(self, authenticated_client):
        r = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'curriculum',
                'reason_text': 'bad_reason',
            },
        )
        assert r.status_code == 400
        assert r.get_json()['error'] == 'invalid_reason'

    def test_invalid_slot_kind_returns_400(self, authenticated_client):
        r = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'nonexistent_kind',
                'reason_text': 'no_time',
            },
        )
        assert r.status_code == 400
        assert r.get_json()['error'] == 'invalid_slot_kind'

    def test_missing_step_kind_returns_400(self, authenticated_client):
        r = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'reason_text': 'no_time',
            },
        )
        assert r.status_code == 400

    def test_missing_reason_returns_400(self, authenticated_client):
        r = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'curriculum',
            },
        )
        assert r.status_code == 400


# ── _get_skipped_slot_kinds unit tests ────────────────────────────────────────


class TestGetSkippedSlotKinds:
    def test_returns_empty_set_when_no_events(self, app):
        with app.app_context():
            from app.daily_plan.linear.plan import _get_skipped_slot_kinds
            mock_db = MagicMock()
            mock_db.session.query.return_value.filter_by.return_value.all.return_value = []
            result = _get_skipped_slot_kinds(1, date.today(), mock_db)
            assert result == set()

    def test_returns_kinds_from_events(self, app):
        with app.app_context():
            from app.daily_plan.linear.plan import _get_skipped_slot_kinds
            mock_db = MagicMock()
            events = [
                _make_mock_event(step_kind='curriculum'),
                _make_mock_event(step_kind='srs'),
            ]
            mock_db.session.query.return_value.filter_by.return_value.all.return_value = events
            result = _get_skipped_slot_kinds(1, date.today(), mock_db)
            assert result == {'curriculum', 'srs'}

    def test_ignores_events_with_null_step_kind(self, app):
        with app.app_context():
            from app.daily_plan.linear.plan import _get_skipped_slot_kinds
            mock_db = MagicMock()
            ev = _make_mock_event(step_kind=None)
            mock_db.session.query.return_value.filter_by.return_value.all.return_value = [ev]
            result = _get_skipped_slot_kinds(1, date.today(), mock_db)
            assert result == set()


# ── compute_linear_day_secured with skipped slots ────────────────────────────


class TestComputeLinearDaySecured:
    def test_skipped_slot_not_completed_blocks_secured(self, app):
        with app.app_context():
            from app.daily_plan.linear.plan import compute_linear_day_secured
            slots = [
                _make_slot('curriculum', completed=True),
                _make_slot('srs', skipped=True),
                _make_slot('reading', completed=True),
            ]
            # skipped ≠ completed: day must NOT be secured
            assert compute_linear_day_secured(slots) is False

    def test_all_completed_is_secured(self, app):
        with app.app_context():
            from app.daily_plan.linear.plan import compute_linear_day_secured
            slots = [
                _make_slot('curriculum', completed=True),
                _make_slot('srs', completed=True),
            ]
            assert compute_linear_day_secured(slots) is True

    def test_empty_baseline_not_secured(self, app):
        with app.app_context():
            from app.daily_plan.linear.plan import compute_linear_day_secured
            assert compute_linear_day_secured([]) is False


# ── Template state machine: skipped unlocks next slot ────────────────────────


class TestSkippedSlotStateLogic:
    def test_skipped_first_slot_makes_second_current(self):
        slots = [
            _make_slot('curriculum', skipped=True),
            _make_slot('srs'),
            _make_slot('reading'),
        ]
        assert _compute_states(slots) == ['skipped', 'current', 'locked']

    def test_done_then_skipped_then_current(self):
        slots = [
            _make_slot('curriculum', completed=True),
            _make_slot('srs', skipped=True),
            _make_slot('reading'),
        ]
        assert _compute_states(slots) == ['done', 'skipped', 'current']

    def test_all_skipped_no_current(self):
        slots = [
            _make_slot('curriculum', skipped=True),
            _make_slot('srs', skipped=True),
        ]
        assert _compute_states(slots) == ['skipped', 'skipped']

    def test_default_behavior_unchanged_without_skip(self):
        slots = [
            _make_slot('curriculum'),
            _make_slot('srs'),
            _make_slot('reading'),
        ]
        assert _compute_states(slots) == ['current', 'locked', 'locked']

    def test_done_then_current_then_locked_unchanged(self):
        slots = [
            _make_slot('curriculum', completed=True),
            _make_slot('srs'),
            _make_slot('reading'),
        ]
        assert _compute_states(slots) == ['done', 'current', 'locked']


# ── DailyPlanEventType enum ───────────────────────────────────────────────────


class TestDailyPlanEventTypeEnum:
    def test_slot_skipped_in_enum(self, app):
        with app.app_context():
            from app.daily_plan.models import DailyPlanEventType
            assert DailyPlanEventType.slot_skipped.value == 'slot_skipped'
