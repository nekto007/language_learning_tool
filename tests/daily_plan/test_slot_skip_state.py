"""DP-092 — «Пропустить» помечает один слот, а не все слоты того же kind.

``/api/daily-plan/events`` пишет per-slot ключ (``get_slot_skip_key``) в
``mission_type``, но читатель матчил только по ``step_kind``: на normal /
intensive один пропуск гасил все 2–3 curriculum-слота дня и раньше времени
снимал замок с «Дополнительно». Уроки после пропущенного при этом
предлагались как «current», хотя роут отдал бы 403 (предыдущий урок не
завершён) — ревью Codex.
"""
from __future__ import annotations

from app.daily_plan.models import DailyPlanEvent
from app.daily_plan.plan import (
    _anchor_slot_skipped,
    _apply_unified_skip_state,
    _get_unified_skipped_slots,
)
from app.utils.db import db as real_db
from tests.daily_plan.test_unified_plan import _make_user
from tests.support_dates import study_today


def _slot(kind: str, lesson_id: int | None = None, completed: bool = False) -> dict:
    data = {'lesson_id': lesson_id} if lesson_id else {}
    return {'id': f'{kind}:{lesson_id or "x"}', 'kind': kind, 'completed': completed, 'data': data}


def _intensive() -> list[dict]:
    return [_slot('curriculum', 101), _slot('srs'), _slot('reading'), _slot('curriculum', 102), _slot('curriculum', 103)]


class TestSkipMatchesOneSlot:

    def test_keyed_skip_marks_only_its_slot(self):
        required = _intensive()
        _apply_unified_skip_state(required, [('curriculum', 'lesson:101')])
        assert [it.get('skipped', False) for it in required] == [True, False, False, False, False]

    def test_legacy_kind_only_skip_marks_one_slot_not_every_one(self):
        required = _intensive()
        _apply_unified_skip_state(required, [('curriculum', None)])
        assert [it.get('skipped', False) for it in required] == [True, False, False, False, False]

    def test_completed_slot_is_never_marked_skipped(self):
        required = [_slot('curriculum', 101, completed=True), _slot('srs')]
        _apply_unified_skip_state(required, [('curriculum', 'lesson:101')])
        assert not required[0].get('skipped')

    def test_idempotent(self):
        required = _intensive()
        skips = [('curriculum', 'lesson:101')]
        _apply_unified_skip_state(required, skips)
        first = [dict(it) for it in required]
        _apply_unified_skip_state(required, skips)
        assert required == first


class TestDependantsAreBlocked:

    def test_later_curriculum_slots_block_after_a_skipped_lesson(self):
        required = _intensive()
        _apply_unified_skip_state(required, [('curriculum', 'lesson:101')])
        assert required[3]['blocked'] is True
        assert required[4]['blocked'] is True
        assert required[3]['data']['locked_reason']
        # SRS / reading do not depend on the lesson — still actionable.
        assert not required[1].get('blocked') and not required[2].get('blocked')

    def test_skipping_srs_blocks_nothing(self):
        required = _intensive()
        _apply_unified_skip_state(required, [('srs', 'slot:1:srs')])
        assert required[1]['skipped'] is True
        assert not any(it.get('blocked') for it in required)

    def test_block_does_not_touch_the_snapshot_dict(self):
        """``data`` заменяется копией — снапшот живёт в ``plan_json``."""
        required = _intensive()
        original_data = required[3]['data']
        _apply_unified_skip_state(required, [('curriculum', 'lesson:101')])
        assert 'locked_reason' not in original_data


class TestSkipRowsAreReadWithTheirKey:

    def test_events_carry_the_slot_key(self, db_session):
        user = _make_user(db_session)
        db_session.add(DailyPlanEvent(
            user_id=user.id, event_type='slot_skipped', plan_date=study_today(),
            step_kind='curriculum', mission_type='lesson:101',
        ))
        db_session.commit()

        assert _get_unified_skipped_slots(user.id, real_db) == [('curriculum', 'lesson:101')]
        assert _anchor_slot_skipped(user.id, real_db, 101) is True
        assert _anchor_slot_skipped(user.id, real_db, 102) is False

    def test_legacy_row_without_key_matches_any_curriculum_anchor(self, db_session):
        user = _make_user(db_session)
        db_session.add(DailyPlanEvent(
            user_id=user.id, event_type='slot_skipped', plan_date=study_today(),
            step_kind='curriculum', mission_type=None,
        ))
        db_session.commit()

        assert _get_unified_skipped_slots(user.id, real_db) == [('curriculum', None)]
        assert _anchor_slot_skipped(user.id, real_db, 555) is True
