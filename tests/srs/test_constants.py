"""Tests for app/srs/constants.py — learning path settings."""
from __future__ import annotations

from app.srs.constants import LEARNING_STEPS, RELEARNING_STEPS, GRADUATING_INTERVAL


def test_learning_steps_three_stage_path():
    # 1 min, 10 min, 1 day → graduates on day 2 with one prior day-scale review.
    assert LEARNING_STEPS == [1, 10, 1440]


def test_learning_steps_strictly_increasing():
    assert all(b > a for a, b in zip(LEARNING_STEPS, LEARNING_STEPS[1:]))


def test_relearning_steps_includes_one_day_step():
    assert RELEARNING_STEPS == [10, 1440]


def test_graduating_interval_unchanged():
    assert GRADUATING_INTERVAL == 1
