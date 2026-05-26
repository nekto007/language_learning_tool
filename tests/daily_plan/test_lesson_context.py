"""Tests for ``app/daily_plan/linear/lesson_context.py``."""
from __future__ import annotations

import pytest

from app.daily_plan.linear.lesson_context import (
    DailyPlanLessonContext,
    build_lesson_context_from_plan,
    _is_current_slot,
    _pick_next_slot,
    _compute_day_secured,
)


@pytest.fixture
def plan_three_baseline():
    """A typical day-start plan: 3 incomplete baseline slots, no extensions."""
    slots = [
        {
            'kind': 'curriculum',
            'title': 'A1/M1 — Vocabulary',
            'url': '/learn/101/?from=linear_plan&slot=curriculum',
            'completed': False,
            'data': {'lesson_id': 101},
        },
        {
            'kind': 'srs',
            'title': 'SRS: 12 cards',
            'url': '/study/cards?source=linear_plan&from=linear_plan&slot=srs',
            'completed': False,
            'data': {'cards_due': 12},
        },
        {
            'kind': 'book',
            'title': 'Reading: Animal Farm',
            'url': '/read/42/?from=linear_plan&slot=book',
            'completed': False,
            'data': {'book_id': 42},
        },
    ]
    return {
        'mode': 'linear',
        'slots': slots,
        'baseline_slots': slots,
        'day_secured': False,
    }


def test_is_current_slot_matches_by_lesson_id():
    slot = {'kind': 'curriculum', 'data': {'lesson_id': 7}}
    assert _is_current_slot(slot, 'curriculum', 7) is True
    assert _is_current_slot(slot, 'curriculum', 8) is False


def test_is_current_slot_kind_only_when_no_lesson_id():
    """SRS/book/error_review have no lesson_id — kind match is enough."""
    slot = {'kind': 'srs', 'data': {}}
    assert _is_current_slot(slot, 'srs', None) is True
    assert _is_current_slot(slot, 'book', None) is False


def test_is_current_slot_requires_kind_param():
    """No slot param → never current (we're not in plan context)."""
    slot = {'kind': 'curriculum', 'data': {'lesson_id': 7}}
    assert _is_current_slot(slot, None, 7) is False
    assert _is_current_slot(slot, '', 7) is False


def test_pick_next_slot_skips_current_and_returns_following(plan_three_baseline):
    next_slot = _pick_next_slot(
        plan_three_baseline['slots'],
        slot_param='curriculum',
        current_lesson_id=101,
    )
    assert next_slot is not None
    assert next_slot['kind'] == 'srs'


def test_pick_next_slot_skips_already_completed():
    slots = [
        {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': True, 'data': {}},
        {'kind': 'book', 'completed': False, 'data': {'book_id': 5}},
    ]
    nxt = _pick_next_slot(slots, slot_param='curriculum', current_lesson_id=1)
    assert nxt is not None
    assert nxt['kind'] == 'book'


def test_pick_next_slot_returns_none_when_only_current_left():
    slots = [
        {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': False, 'data': {}},
    ]
    nxt = _pick_next_slot(slots, slot_param='srs', current_lesson_id=None)
    assert nxt is None


def test_pick_next_slot_skips_skipped_slots():
    slots = [
        {'kind': 'curriculum', 'completed': False, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': False, 'skipped': True, 'data': {}},
        {'kind': 'book', 'completed': False, 'data': {'book_id': 5}},
    ]
    nxt = _pick_next_slot(slots, slot_param='curriculum', current_lesson_id=1)
    assert nxt is not None
    assert nxt['kind'] == 'book'


def test_pick_next_slot_uses_skipped_fallback_when_no_active_slot():
    slots = [
        {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': False, 'skipped': True, 'data': {}},
        {'kind': 'listening', 'completed': False, 'blocked': True, 'data': {'lesson_id': 2}},
    ]
    nxt = _pick_next_slot(slots, slot_param='curriculum', current_lesson_id=1)
    assert nxt is not None
    assert nxt['kind'] == 'srs'


def test_pick_next_slot_skips_blocked_slots():
    slots = [
        {'kind': 'curriculum', 'completed': False, 'data': {'lesson_id': 1}},
        {'kind': 'listening', 'completed': False, 'blocked': True, 'data': {'lesson_id': 2}},
        {'kind': 'book', 'completed': False, 'data': {'book_id': 5}},
    ]
    nxt = _pick_next_slot(slots, slot_param='curriculum', current_lesson_id=1)
    assert nxt is not None
    assert nxt['kind'] == 'book'


def test_pick_next_slot_fallback_when_current_not_found(plan_three_baseline):
    """User opened a lesson without correct slot context — give them
    *some* useful next-step rather than nothing."""
    nxt = _pick_next_slot(
        plan_three_baseline['slots'],
        slot_param='curriculum',
        current_lesson_id=999,  # not in chain
    )
    assert nxt is not None
    assert nxt['kind'] == 'curriculum'  # first incomplete


def test_compute_day_secured_false_when_multiple_baseline_pending(plan_three_baseline):
    secured = _compute_day_secured(
        plan_three_baseline['baseline_slots'],
        slot_param='curriculum',
        current_lesson_id=101,
    )
    assert secured is False


def test_compute_day_secured_true_when_finishing_last_pending():
    baseline = [
        {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': True, 'data': {}},
        {'kind': 'book', 'completed': False, 'data': {'book_id': 5}},
    ]
    secured = _compute_day_secured(baseline, slot_param='book', current_lesson_id=None)
    assert secured is True


def test_compute_day_secured_true_when_all_baseline_already_done():
    baseline = [
        {'kind': 'curriculum', 'completed': True, 'data': {}},
        {'kind': 'srs', 'completed': True, 'data': {}},
    ]
    secured = _compute_day_secured(baseline, slot_param='curriculum', current_lesson_id=1)
    assert secured is True


def test_compute_day_secured_false_when_finishing_extension_with_baseline_pending():
    """If the user is finishing an extension slot but a baseline is still
    incomplete, the day is NOT secured."""
    baseline = [
        {'kind': 'curriculum', 'completed': False, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': True, 'data': {}},
    ]
    secured = _compute_day_secured(baseline, slot_param='srs', current_lesson_id=None)
    assert secured is False


def test_compute_day_secured_false_when_skipped_baseline_pending():
    baseline = [
        {'kind': 'curriculum', 'completed': False, 'skipped': True, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': True, 'data': {}},
        {'kind': 'book', 'completed': False, 'data': {'book_id': 5}},
    ]
    secured = _compute_day_secured(baseline, slot_param='book', current_lesson_id=None)
    assert secured is False


def test_compute_day_secured_false_when_blocked_baseline_pending():
    baseline = [
        {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
        {'kind': 'book', 'completed': False, 'data': {'book_id': 5}},
        {'kind': 'listening', 'completed': False, 'blocked': True, 'data': {'lesson_id': 2}},
    ]
    secured = _compute_day_secured(baseline, slot_param='book', current_lesson_id=None)
    assert secured is False


def test_build_from_plan_not_daily_plan_returns_defaults(plan_three_baseline):
    ctx = build_lesson_context_from_plan(
        plan_three_baseline,
        slot_param=None,
        current_lesson_id=None,
        dashboard_url='/dashboard',
        from_param='',  # not from=linear_plan
    )
    assert ctx.is_daily_plan is False
    assert ctx.next_slot_url is None
    assert ctx.day_secured is False
    assert ctx.dashboard_url == '/dashboard'


def test_build_from_plan_curriculum_open(plan_three_baseline):
    ctx = build_lesson_context_from_plan(
        plan_three_baseline,
        slot_param='curriculum',
        current_lesson_id=101,
        dashboard_url='/dashboard',
    )
    assert ctx.is_daily_plan is True
    assert ctx.slot_kind == 'curriculum'
    assert ctx.next_slot_kind == 'srs'
    assert ctx.next_slot_title == 'SRS: 12 cards'
    assert ctx.next_slot_url is not None
    assert 'from=linear_plan' in ctx.next_slot_url
    assert ctx.day_secured is False


def test_build_from_plan_last_slot_signals_day_secured():
    plan = {
        'slots': [
            {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
            {'kind': 'srs', 'completed': True, 'data': {}},
            {'kind': 'book', 'completed': False, 'data': {'book_id': 5},
             'url': '/read/5/', 'title': 'Reading'},
        ],
        'baseline_slots': [
            {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
            {'kind': 'srs', 'completed': True, 'data': {}},
            {'kind': 'book', 'completed': False, 'data': {'book_id': 5}},
        ],
    }
    ctx = build_lesson_context_from_plan(
        plan,
        slot_param='book',
        current_lesson_id=None,
        dashboard_url='/dashboard',
    )
    assert ctx.is_daily_plan is True
    assert ctx.slot_kind == 'book'
    assert ctx.next_slot_url is None  # nothing left
    assert ctx.day_secured is True


def test_to_dict_round_trip():
    ctx = DailyPlanLessonContext(
        is_daily_plan=True,
        slot_kind='curriculum',
        next_slot_url='/study/cards?from=linear_plan&slot=srs',
        next_slot_title='SRS',
        next_slot_kind='srs',
        day_secured=False,
        dashboard_url='/dashboard',
    )
    d = ctx.to_dict()
    assert d['is_daily_plan'] is True
    assert d['slot_kind'] == 'curriculum'
    assert d['next_slot_url'].startswith('/study/cards')
    assert d['day_secured'] is False


def test_build_lesson_context_accepts_full_db_object_not_session():
    """Regression: the dashboard context processor and lesson API endpoints
    pass the SQLAlchemy ``db`` object (whose ``.session`` is the scoped
    session) — not ``db.session`` directly. Downstream get_daily_plan →
    find_next_lesson_linear does ``db.session.query(...)``. Passing a
    session here would silently degrade to is_daily_plan=False, leaving
    lesson pages with catalog CTAs even when ?from=linear_plan is set."""
    from unittest.mock import MagicMock
    from app.daily_plan.linear.lesson_context import build_lesson_context, PLAN_FROM_VALUE
    from app import create_app
    app = create_app()
    with app.test_request_context(f'/learn/1/?from={PLAN_FROM_VALUE}&slot=curriculum'):
        fake_session = MagicMock()
        fake_db = MagicMock()
        fake_db.session = fake_session
        from unittest.mock import patch
        # build_lesson_context now reaches into the unified plan; patch the
        # source module that owns the symbol.
        with patch('app.daily_plan.plan.get_daily_plan',
                   return_value={'required': [], 'optional': [], 'setup': []}) as mock_plan:
            ctx = build_lesson_context(user_id=1, db=fake_db, current_lesson_id=1)
        mock_plan.assert_called_once()
        forwarded_db = mock_plan.call_args.args[1]
        assert forwarded_db is fake_db
        assert ctx.is_daily_plan is True


def test_extension_after_baseline_chosen_as_next():
    """When baseline curriculum is complete and an extension is queued,
    the extension is the next CTA target."""
    slots = [
        {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': 1}},
        {'kind': 'srs', 'completed': True, 'data': {}},
        {'kind': 'book', 'completed': True, 'data': {'book_id': 5}},
        # extension
        {'kind': 'curriculum', 'completed': False, 'data': {'lesson_id': 2,
         'extension': True}, 'url': '/learn/2/', 'title': 'Bonus'},
    ]
    nxt = _pick_next_slot(slots, slot_param='book', current_lesson_id=None)
    assert nxt is not None
    assert nxt['data'].get('extension') is True
    assert nxt['kind'] == 'curriculum'
