"""Per-request daily-plan context for lesson pages.

When a lesson is opened with ``?from=linear_plan&slot=<kind>``, this module
builds a small dataclass describing:

- whether the current request comes from the linear daily plan;
- which slot (kind + lesson_id) the user is currently inside;
- what the next slot in the plan is (URL + title), AFTER treating the
  current slot as completed — i.e. the link the completion screen should
  show as the primary CTA;
- whether finishing this slot will close the day (``day_secured``);
- a dashboard URL for the secondary CTA.

The output is consumed by ``_lesson_completion_actions.html`` and by the
``/api/lesson/<id>/submit`` endpoints (so the client can refresh CTAs
after submit without a page reload).

This module is intentionally pure-Python and Flask-aware only inside the
build function (it reads ``flask.request.args``). The dataclass itself is
serialisable to a dict for JSON responses via ``to_dict()``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


PLAN_FROM_VALUE = 'linear_plan'


def _parse_referer_args() -> tuple[str, Optional[str]]:
    """Extract (from, slot) from the request Referer URL, if any.

    Used by /api/lesson/<id>/submit and similar API endpoints whose own URL
    has no query string. The lesson page that triggered the POST carries
    ``?from=linear_plan&slot=<kind>`` and the browser sends it as Referer.
    """
    try:
        from flask import request
        from urllib.parse import parse_qs, urlsplit
        ref = request.headers.get('Referer') or ''
        if not ref:
            return '', None
        parts = urlsplit(ref)
        q = parse_qs(parts.query or '')
        from_val = (q.get('from', [''])[0] or '').strip()
        slot_val = (q.get('slot', [''])[0] or '').strip() or None
        return from_val, slot_val
    except Exception:
        return '', None


@dataclass(frozen=True)
class DailyPlanLessonContext:
    """Daily-plan flags + next-step metadata for a single lesson render.

    ``is_daily_plan`` is the authoritative gate for daily-plan-aware UI.
    When False, the rest of the fields carry sensible defaults (None /
    False) and the lesson page renders its standalone (catalog) CTAs.
    """

    is_daily_plan: bool
    slot_kind: Optional[str]
    next_slot_url: Optional[str]
    next_slot_title: Optional[str]
    next_slot_kind: Optional[str]
    day_secured: bool
    dashboard_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'is_daily_plan': self.is_daily_plan,
            'slot_kind': self.slot_kind,
            'next_slot_url': self.next_slot_url,
            'next_slot_title': self.next_slot_title,
            'next_slot_kind': self.next_slot_kind,
            'day_secured': self.day_secured,
            'dashboard_url': self.dashboard_url,
        }


def _is_current_slot(
    slot: dict[str, Any],
    slot_param: Optional[str],
    current_lesson_id: Optional[int],
) -> bool:
    """Return True if ``slot`` is the one the user is currently inside.

    Curriculum-like slots (curriculum/listening/speaking/writing) carry
    ``data.lesson_id`` so we can disambiguate when the chain has multiple
    extensions of the same kind. For kind-only slots (srs/book/error_review)
    the first matching kind in chain order is treated as the current one.
    """
    if not slot_param:
        return False
    if slot.get('kind') != slot_param:
        return False
    if current_lesson_id is None:
        return True
    data = slot.get('data') or {}
    return data.get('lesson_id') == current_lesson_id


def _pick_next_slot(
    all_slots: list[dict[str, Any]],
    slot_param: Optional[str],
    current_lesson_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Walk the chain in display order, return the first incomplete slot
    that comes AFTER the current one (or anywhere if current not found).

    Skipped slots and the current slot itself are ignored. When the
    current slot can't be located in the chain (e.g. user reopened a
    finished lesson directly), fall back to the first incomplete slot —
    that's still the most useful next-step CTA.
    """
    found_current = False
    for slot in all_slots:
        if _is_current_slot(slot, slot_param, current_lesson_id):
            found_current = True
            continue
        if not found_current:
            continue
        if slot.get('completed') or slot.get('skipped'):
            continue
        return slot

    if not found_current:
        for slot in all_slots:
            if not (slot.get('completed') or slot.get('skipped')):
                return slot

    return None


def _compute_day_secured(
    baseline_slots: list[dict[str, Any]],
    slot_param: Optional[str],
    current_lesson_id: Optional[int],
) -> bool:
    """Predict ``day_secured`` after this lesson is completed.

    We count incomplete baseline slots and subtract 1 if the current slot
    is one of them — because the caller is about to finish it. When there
    are no baseline slots left incomplete, the day is secured.
    """
    incomplete = [
        slot for slot in baseline_slots
        if not (slot.get('completed') or slot.get('skipped'))
    ]
    if not incomplete:
        return True
    if slot_param and any(
        _is_current_slot(s, slot_param, current_lesson_id) for s in incomplete
    ):
        return len(incomplete) <= 1
    return False


def build_lesson_context(
    user_id: int,
    db,
    current_lesson_id: Optional[int] = None,
    from_param: Optional[str] = None,
    slot_param: Optional[str] = None,
) -> DailyPlanLessonContext:
    """Return a ``DailyPlanLessonContext`` for the current Flask request.

    Args:
        user_id: the current user (used to fetch the plan).
        db: SQLAlchemy session, passed through to ``get_linear_plan``.
        current_lesson_id: the lesson the user is currently on; passed to
            disambiguate which slot they're inside. Pass ``None`` for
            slot kinds without a lesson id (SRS/book/error_review) — the
            first slot of the matching kind is treated as current.
        from_param: explicit override for the ``from`` query param. Use
            this from API endpoints (where the POST URL has no query)
            to look at JSON body / Referer instead. When ``None``,
            ``request.args.get('from')`` is consulted, then Referer.
        slot_param: explicit override for the ``slot`` query param. Same
            fallback rules as ``from_param``.

    The function never raises: if the plan can't be loaded (e.g. legacy
    user with no plan state), it falls back to a non-plan context so the
    lesson page just renders its standalone CTAs.
    """
    from flask import request, url_for

    dashboard_url = url_for('words.dashboard')

    # Resolve from/slot params with this precedence:
    #   1. explicit overrides (caller passed them)
    #   2. request.args query string
    #   3. Referer header (so /api/lesson/<id>/submit can inherit from the
    #      lesson page that triggered the POST)
    if from_param is None:
        try:
            from_param = (request.args.get('from') or '').strip()
        except RuntimeError:
            from_param = ''
        if not from_param:
            from_param, slot_from_referer = _parse_referer_args()
            if slot_param is None:
                slot_param = slot_from_referer
    if slot_param is None:
        try:
            slot_param = (request.args.get('slot') or '').strip() or None
        except RuntimeError:
            slot_param = None
        if not slot_param:
            _, slot_from_referer = _parse_referer_args()
            slot_param = slot_from_referer

    if from_param != PLAN_FROM_VALUE:
        return DailyPlanLessonContext(
            is_daily_plan=False,
            slot_kind=None,
            next_slot_url=None,
            next_slot_title=None,
            next_slot_kind=None,
            day_secured=False,
            dashboard_url=dashboard_url,
        )

    try:
        from app.daily_plan.linear.plan import get_linear_plan
        plan = get_linear_plan(user_id, db) or {}
    except Exception:
        # Defensive: if plan assembly fails, degrade to catalog flow
        # rather than 500'ing the lesson page.
        return DailyPlanLessonContext(
            is_daily_plan=False,
            slot_kind=slot_param,
            next_slot_url=None,
            next_slot_title=None,
            next_slot_kind=None,
            day_secured=False,
            dashboard_url=dashboard_url,
        )

    all_slots = plan.get('slots') or []
    baseline_slots = plan.get('baseline_slots') or []

    next_slot = _pick_next_slot(all_slots, slot_param, current_lesson_id)
    day_secured = _compute_day_secured(baseline_slots, slot_param, current_lesson_id)

    return DailyPlanLessonContext(
        is_daily_plan=True,
        slot_kind=slot_param,
        next_slot_url=(next_slot or {}).get('url'),
        next_slot_title=(next_slot or {}).get('title'),
        next_slot_kind=(next_slot or {}).get('kind'),
        day_secured=day_secured,
        dashboard_url=dashboard_url,
    )


def build_lesson_context_from_plan(
    plan: dict[str, Any],
    slot_param: Optional[str],
    current_lesson_id: Optional[int],
    dashboard_url: str,
    from_param: str = PLAN_FROM_VALUE,
) -> DailyPlanLessonContext:
    """Build a context dataclass from an already-loaded plan.

    Useful in tests and in places where the caller has already fetched
    ``get_linear_plan(...)`` and wants to avoid the duplicate call.
    """
    if from_param != PLAN_FROM_VALUE:
        return DailyPlanLessonContext(
            is_daily_plan=False,
            slot_kind=None,
            next_slot_url=None,
            next_slot_title=None,
            next_slot_kind=None,
            day_secured=False,
            dashboard_url=dashboard_url,
        )

    all_slots = plan.get('slots') or []
    baseline_slots = plan.get('baseline_slots') or []
    next_slot = _pick_next_slot(all_slots, slot_param, current_lesson_id)
    day_secured = _compute_day_secured(baseline_slots, slot_param, current_lesson_id)

    return DailyPlanLessonContext(
        is_daily_plan=True,
        slot_kind=slot_param,
        next_slot_url=(next_slot or {}).get('url'),
        next_slot_title=(next_slot or {}).get('title'),
        next_slot_kind=(next_slot or {}).get('kind'),
        day_secured=day_secured,
        dashboard_url=dashboard_url,
    )
