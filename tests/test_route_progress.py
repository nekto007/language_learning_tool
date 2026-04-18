"""Unit tests for UserRouteProgress model and helper functions.

Covers:
- Step weight lookup per phase kind
- Step accumulation and checkpoint detection
- get_or_create behaviour (idempotent first call)
- Checkpoint boundary at CHECKPOINT_INTERVAL
- Multiple crossings in one session
- Bonus phase contributes 0 steps
- get_route_state with and without an existing row
"""
import pytest
from app.daily_plan.route_progress import (
    CHECKPOINT_INTERVAL,
    PHASE_STEP_WEIGHTS,
    UserRouteProgress,
    add_route_steps,
    get_phase_step_weight,
    get_route_state,
)


# ---------------------------------------------------------------------------
# get_phase_step_weight
# ---------------------------------------------------------------------------

def test_learn_weight():
    assert get_phase_step_weight("learn") == 3


def test_recall_weight():
    assert get_phase_step_weight("recall") == 2


def test_use_weight():
    assert get_phase_step_weight("use") == 2


def test_read_weight():
    assert get_phase_step_weight("read") == 2


def test_check_weight():
    assert get_phase_step_weight("check") == 1


def test_close_weight():
    assert get_phase_step_weight("close") == 1


def test_bonus_weight_is_zero():
    assert get_phase_step_weight("bonus") == 0


def test_unknown_phase_returns_zero():
    assert get_phase_step_weight("nonexistent") == 0


# ---------------------------------------------------------------------------
# add_route_steps — basic accumulation
# ---------------------------------------------------------------------------

def test_add_first_step_creates_row(db_session, test_user):
    row, crossed = add_route_steps(test_user.id, "recall", db_session)
    assert row is not None
    assert row.user_id == test_user.id
    assert row.total_steps == 2
    assert row.steps_in_checkpoint == 2
    assert crossed is False


def test_add_learn_step(db_session, test_user):
    row, _ = add_route_steps(test_user.id, "learn", db_session)
    assert row.total_steps == 3


def test_bonus_step_no_change(db_session, test_user):
    row, crossed = add_route_steps(test_user.id, "bonus", db_session)
    assert row.total_steps == 0
    assert crossed is False


def test_idempotent_get_or_create(db_session, test_user):
    row1, _ = add_route_steps(test_user.id, "check", db_session)
    row2, _ = add_route_steps(test_user.id, "check", db_session)
    assert row1.id == row2.id
    assert row2.total_steps == 2


# ---------------------------------------------------------------------------
# Checkpoint detection
# ---------------------------------------------------------------------------

def test_checkpoint_not_crossed_below_interval(db_session, test_user):
    # CHECKPOINT_INTERVAL is 20; add 19 weighted steps
    # recall=2 * 9 = 18, then check=1 → total 19
    for _ in range(9):
        add_route_steps(test_user.id, "recall", db_session)
    _, crossed = add_route_steps(test_user.id, "check", db_session)
    assert crossed is False
    row = db_session.query(UserRouteProgress).filter_by(user_id=test_user.id).first()
    assert row.checkpoint_number == 0
    assert row.total_steps == 19


def test_checkpoint_crossed_at_interval(db_session, test_user):
    # Add exactly CHECKPOINT_INTERVAL steps: 10 × recall(2) = 20
    for _ in range(9):
        add_route_steps(test_user.id, "recall", db_session)
    _, crossed = add_route_steps(test_user.id, "recall", db_session)
    assert crossed is True
    row = db_session.query(UserRouteProgress).filter_by(user_id=test_user.id).first()
    assert row.checkpoint_number == 1
    assert row.steps_in_checkpoint == 0
    assert row.total_steps == 20


def test_multiple_checkpoints(db_session, test_user):
    # 40 steps = checkpoint 2: 20 × recall(2)
    for _ in range(20):
        add_route_steps(test_user.id, "recall", db_session)
    row = db_session.query(UserRouteProgress).filter_by(user_id=test_user.id).first()
    assert row.checkpoint_number == 2
    assert row.total_steps == 40
    assert row.steps_in_checkpoint == 0


def test_steps_in_checkpoint_resets_after_crossing(db_session, test_user):
    # Cross checkpoint then add 3 more (check=1)
    for _ in range(10):
        add_route_steps(test_user.id, "recall", db_session)
    for _ in range(3):
        add_route_steps(test_user.id, "check", db_session)
    row = db_session.query(UserRouteProgress).filter_by(user_id=test_user.id).first()
    assert row.total_steps == 23
    assert row.checkpoint_number == 1
    assert row.steps_in_checkpoint == 3


# ---------------------------------------------------------------------------
# get_route_state
# ---------------------------------------------------------------------------

def test_route_state_no_row(db_session, test_user):
    state = get_route_state(test_user.id, steps_today=5, db_session=db_session)
    assert state["total_steps"] == 0
    assert state["checkpoint_number"] == 0
    assert state["steps_to_next_checkpoint"] == CHECKPOINT_INTERVAL
    assert state["percent_to_checkpoint"] == 0
    assert state["steps_today"] == 5


def test_route_state_with_row(db_session, test_user):
    # Add 10 steps (5 recall)
    for _ in range(5):
        add_route_steps(test_user.id, "recall", db_session)
    state = get_route_state(test_user.id, steps_today=10, db_session=db_session)
    assert state["total_steps"] == 10
    assert state["checkpoint_number"] == 0
    assert state["steps_to_next_checkpoint"] == CHECKPOINT_INTERVAL - 10
    assert state["percent_to_checkpoint"] == 50
    assert state["steps_today"] == 10


def test_route_state_after_checkpoint(db_session, test_user):
    for _ in range(10):
        add_route_steps(test_user.id, "recall", db_session)
    state = get_route_state(test_user.id, steps_today=20, db_session=db_session)
    assert state["checkpoint_number"] == 1
    assert state["steps_to_next_checkpoint"] == CHECKPOINT_INTERVAL
    assert state["percent_to_checkpoint"] == 0
