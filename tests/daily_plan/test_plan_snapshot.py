"""Tests for the daily required-plan snapshot (app/daily_plan/snapshot.py).

Covers:
- snapshot creation on first assembly of the day (+ frozen SRS goal_total)
- composition/order pinned on subsequent assemblies
- kind-matching (lesson skip swaps the curriculum item id)
- vanished slot carried as completed
- mid-day new kinds demoted instead of growing required
- malformed snapshot silently rebuilt
- empty required never snapshotted
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.daily_plan.models import DailyPlanLog
from app.daily_plan.snapshot import (
    SNAPSHOT_VERSION,
    reconcile_required_with_snapshot,
)
from app.utils.db import db as real_db
from app.utils.time_utils import get_user_local_date


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_user(db_session) -> User:
    s = _uid()
    user = User(username=f'plansnap_{s}', email=f'plansnap_{s}@example.com', active=True)
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _item(item_id: str, kind: str, *, title: str = 'item', eta: int = 5,
          completed: bool = False, data: dict | None = None) -> dict:
    return {
        'id': item_id,
        'section': 'required',
        'kind': kind,
        'title': title,
        'subtitle': None,
        'lesson_type': None,
        'eta_minutes': eta,
        'url': '/x',
        'completed': completed,
        'completion_signal': 'none',
        'data': dict(data or {}),
    }


def _srs_item(total_show: int = 30, reviews_today: int = 0, new_today: int = 0) -> dict:
    return _item('srs:global', 'srs', title=f'Повторение слов — {total_show}', eta=8, data={
        'total_show': total_show,
        'reviews_today': reviews_today,
        'new_today': new_today,
    })


def _get_snapshot(user_id: int) -> dict | None:
    today = get_user_local_date(user_id, real_db)
    row = DailyPlanLog.query.filter_by(user_id=user_id, plan_date=today).first()
    return row.plan_json if row else None


class TestSnapshotCreation:
    def test_first_call_persists_snapshot_and_returns_unchanged(self, db_session):
        user = _make_user(db_session)
        items = [_srs_item(30), _item('curriculum:lesson:1', 'curriculum', eta=10)]

        result, demoted = reconcile_required_with_snapshot(user.id, items, real_db)
        db_session.commit()

        assert [it['id'] for it in result] == ['srs:global', 'curriculum:lesson:1']
        assert demoted == []
        snap = _get_snapshot(user.id)
        assert snap is not None
        assert snap['version'] == SNAPSHOT_VERSION
        assert [s['id'] for s in snap['slots']] == ['srs:global', 'curriculum:lesson:1']
        assert snap['slots'][0]['srs_goal_total'] == 30

    def test_goal_total_injected_on_first_call(self, db_session):
        user = _make_user(db_session)
        items = [_srs_item(total_show=25, reviews_today=3, new_today=2)]

        result, _ = reconcile_required_with_snapshot(user.id, items, real_db)

        assert result[0]['data']['goal_total'] == 30  # 25 + 3 + 2

    def test_empty_required_not_snapshotted(self, db_session):
        user = _make_user(db_session)

        result, demoted = reconcile_required_with_snapshot(user.id, [], real_db)
        db_session.commit()

        assert result == [] and demoted == []
        assert _get_snapshot(user.id) is None


class TestReconcile:
    def test_composition_and_order_pinned(self, db_session):
        user = _make_user(db_session)
        morning = [_srs_item(30), _item('curriculum:lesson:1', 'curriculum')]
        reconcile_required_with_snapshot(user.id, morning, real_db)
        db_session.commit()

        # Evening assembly reorders the same items — snapshot order wins.
        evening = [_item('curriculum:lesson:1', 'curriculum'), _srs_item(18)]
        result, demoted = reconcile_required_with_snapshot(user.id, evening, real_db)

        assert [it['id'] for it in result] == ['srs:global', 'curriculum:lesson:1']
        assert demoted == []

    def test_srs_goal_frozen_from_snapshot(self, db_session):
        user = _make_user(db_session)
        reconcile_required_with_snapshot(user.id, [_srs_item(30)], real_db)
        db_session.commit()

        # Later: 12 reviewed, only 18 still showing — goal stays 30.
        later = [_srs_item(total_show=18, reviews_today=12)]
        result, _ = reconcile_required_with_snapshot(user.id, later, real_db)

        assert result[0]['data']['goal_total'] == 30

    def test_kind_match_swaps_curriculum_lesson(self, db_session):
        user = _make_user(db_session)
        reconcile_required_with_snapshot(
            user.id, [_item('curriculum:lesson:1', 'curriculum')], real_db)
        db_session.commit()

        # Lesson skipped → next assembly serves lesson 2 under a new id.
        fresh = [_item('curriculum:lesson:2', 'curriculum', title='Урок 2')]
        result, demoted = reconcile_required_with_snapshot(user.id, fresh, real_db)

        assert len(result) == 1
        assert result[0]['id'] == 'curriculum:lesson:2'
        assert result[0]['title'] == 'Урок 2'
        assert demoted == []

    def test_vanished_slot_carried_as_completed(self, db_session):
        user = _make_user(db_session)
        morning = [
            _item('curriculum:lesson:1', 'curriculum'),
            _item('listening:lesson:7', 'listening', title='Аудирование M1'),
        ]
        reconcile_required_with_snapshot(user.id, morning, real_db)
        db_session.commit()

        fresh = [_item('curriculum:lesson:1', 'curriculum')]
        result, _ = reconcile_required_with_snapshot(user.id, fresh, real_db)

        assert [it['id'] for it in result] == ['curriculum:lesson:1', 'listening:lesson:7']
        carried = result[1]
        assert carried['completed'] is True
        assert carried['data'].get('snapshot_carried') is True
        assert carried['eta_minutes'] == 0
        assert carried['title'] == 'Аудирование M1'

    def test_new_kind_mid_day_demoted_not_added(self, db_session):
        user = _make_user(db_session)
        reconcile_required_with_snapshot(
            user.id, [_item('curriculum:lesson:1', 'curriculum')], real_db)
        db_session.commit()

        fresh = [
            _item('curriculum:lesson:1', 'curriculum'),
            _item('error_review:today', 'error_review'),
        ]
        result, demoted = reconcile_required_with_snapshot(user.id, fresh, real_db)

        assert [it['id'] for it in result] == ['curriculum:lesson:1']
        assert [it['id'] for it in demoted] == ['error_review:today']

    def test_malformed_snapshot_rebuilt(self, db_session):
        user = _make_user(db_session)
        today = get_user_local_date(user.id, real_db)
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=today, plan_json={'version': 99, 'slots': 'junk'},
        ))
        db_session.commit()

        items = [_item('curriculum:lesson:1', 'curriculum')]
        result, demoted = reconcile_required_with_snapshot(user.id, items, real_db)
        db_session.commit()

        assert [it['id'] for it in result] == ['curriculum:lesson:1']
        assert demoted == []
        snap = _get_snapshot(user.id)
        assert snap['version'] == SNAPSHOT_VERSION
        assert [s['id'] for s in snap['slots']] == ['curriculum:lesson:1']


class TestDeckQuizSwap:
    def test_deck_quiz_matches_srs_slot_by_kind(self, db_session):
        user = _make_user(db_session)
        reconcile_required_with_snapshot(user.id, [_srs_item(30)], real_db)
        db_session.commit()

        # Mid-day the builder swaps srs:global for the deck-quiz variant.
        deck = _item('srs:deck_quiz', 'srs', title='Квиз по словам — 20',
                     data={'word_limit': 20})
        result, demoted = reconcile_required_with_snapshot(user.id, [deck], real_db)

        assert len(result) == 1
        assert result[0]['id'] == 'srs:deck_quiz'
        # Frozen goal from the morning snapshot still applies to the srs slot.
        assert result[0]['data']['goal_total'] == 30
        assert demoted == []
