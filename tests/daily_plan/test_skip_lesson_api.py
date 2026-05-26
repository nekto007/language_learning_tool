"""Tests for daily-plan slot skip semantics."""
from __future__ import annotations

from unittest.mock import patch

from app.daily_plan.models import DailyPlanEvent


def _unified_plan(*, first='srs') -> dict:
    """Build a fake unified plan payload with two required items."""
    required = [
        {
            'id': f'{first}:global',
            'kind': first,
            'title': first,
            'completed': False,
            'url': f'/{first}',
            'data': {'slot_skip_allowed': True, 'slot_skips_remaining': 1},
        },
        {
            'id': 'curriculum:lesson:1',
            'kind': 'curriculum',
            'title': 'Course lesson',
            'completed': False,
            'url': '/learn/1/',
            'data': {},
        },
    ]
    return {
        'mode': 'unified',
        'required': required,
        'optional': [],
        'setup': [],
    }


def test_slot_skip_records_current_slot(authenticated_client, db_session, test_user):
    with patch('app.daily_plan.plan.get_daily_plan', return_value=_unified_plan(first='srs')):
        response = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'srs',
                'reason_text': 'not_today',
            },
        )

    assert response.status_code == 200
    event = db_session.query(DailyPlanEvent).filter_by(
        user_id=test_user.id,
        event_type='slot_skipped',
    ).one()
    assert event.step_kind == 'srs'


def test_slot_skip_rejects_non_current_slot(authenticated_client):
    with patch('app.daily_plan.plan.get_daily_plan', return_value=_unified_plan(first='srs')):
        response = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'curriculum',
                'reason_text': 'not_today',
            },
        )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'not_current_slot'


def test_slot_skip_quota_is_one_per_day(authenticated_client):
    with patch('app.daily_plan.plan.get_daily_plan', return_value=_unified_plan(first='srs')):
        first = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'srs',
                'reason_text': 'not_today',
            },
        )
        second = authenticated_client.post(
            '/api/daily-plan/events',
            json={
                'event_type': 'slot_skipped',
                'step_kind': 'curriculum',
                'reason_text': 'not_today',
            },
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.get_json()['error'] == 'skip_quota_exhausted'
