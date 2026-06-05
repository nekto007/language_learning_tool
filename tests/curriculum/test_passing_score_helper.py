"""Tests for ``app.curriculum.constants.get_lesson_passing_score``.

This is the canonical helper that grader / route / reconcile-cron all use
to resolve the effective passing threshold for a lesson — a divergence
between any of them re-introduces the "UI passed / DB in_progress" bug class.
"""
from __future__ import annotations

import pytest

from app.curriculum.constants import (
    PASSING_SCORE_DEFAULT,
    PASSING_SCORE_DICTATION,
    get_lesson_passing_score,
)


class _Lesson:
    """Lightweight stand-in for ``Lessons`` (no DB required)."""

    def __init__(self, lesson_type: str = 'quiz', content=None):
        self.type = lesson_type
        self.content = content


class TestTypeDefaults:
    def test_dictation_defaults_to_80(self):
        assert get_lesson_passing_score(_Lesson('dictation', {})) == PASSING_SCORE_DICTATION

    def test_audio_fill_blank_defaults_to_70(self):
        """Despite being audio-themed, audio_fill_blank uses the default
        70 threshold in both grader and route — only dictation is 80."""
        assert get_lesson_passing_score(_Lesson('audio_fill_blank', {})) == PASSING_SCORE_DEFAULT

    def test_final_test_defaults_to_70(self):
        assert get_lesson_passing_score(_Lesson('final_test', {})) == PASSING_SCORE_DEFAULT

    def test_missing_content_uses_default(self):
        assert get_lesson_passing_score(_Lesson('quiz', None)) == PASSING_SCORE_DEFAULT


class TestContentOverride:
    def test_passing_score_percent_wins(self):
        lesson = _Lesson('quiz', {'passing_score_percent': 85})
        assert get_lesson_passing_score(lesson) == 85

    def test_legacy_passing_score_key(self):
        lesson = _Lesson('quiz', {'passing_score': 75})
        assert get_lesson_passing_score(lesson) == 75

    def test_percent_takes_precedence_over_legacy(self):
        lesson = _Lesson('quiz', {'passing_score_percent': 90, 'passing_score': 50})
        assert get_lesson_passing_score(lesson) == 90

    def test_override_applies_to_dictation_too(self):
        lesson = _Lesson('dictation', {'passing_score_percent': 60})
        assert get_lesson_passing_score(lesson) == 60


class TestRobustness:
    def test_non_numeric_override_falls_back(self):
        assert get_lesson_passing_score(_Lesson('quiz', {'passing_score_percent': 'bogus'})) == PASSING_SCORE_DEFAULT

    def test_out_of_range_override_falls_back(self):
        assert get_lesson_passing_score(_Lesson('quiz', {'passing_score_percent': 150})) == PASSING_SCORE_DEFAULT
        assert get_lesson_passing_score(_Lesson('quiz', {'passing_score_percent': -10})) == PASSING_SCORE_DEFAULT

    def test_zero_threshold_honoured(self):
        """An explicit zero is a valid (if permissive) configuration."""
        assert get_lesson_passing_score(_Lesson('quiz', {'passing_score_percent': 0})) == 0
