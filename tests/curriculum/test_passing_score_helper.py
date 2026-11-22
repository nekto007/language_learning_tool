"""The same owner-level thresholds apply despite stale authored overrides."""
from types import SimpleNamespace

import pytest

from app.curriculum.constants import (
    PASSING_SCORE_DEFAULT,
    PASSING_SCORE_DICTATION,
    QUIZ_LESSON_TYPES,
    get_lesson_passing_score,
)


def lesson(kind, content=None):
    return SimpleNamespace(type=kind, content=content)


@pytest.mark.parametrize('kind', sorted(QUIZ_LESSON_TYPES))
@pytest.mark.parametrize('content', [None, {}, {'passing_score_percent': 70},
                                    {'passing_score': 80}, {'passing_score_percent': 100}])
def test_ordinary_quiz_and_grammar_always_use_50(kind, content):
    assert get_lesson_passing_score(lesson(kind, content)) == 50


@pytest.mark.parametrize('content', [None, {}, {'passing_score_percent': 70},
                                    {'passing_score': 80}, {'passing_score_percent': 100}])
def test_final_test_always_uses_75(content):
    assert get_lesson_passing_score(lesson('final_test', content)) == 75


def test_unrelated_defaults_are_unchanged():
    assert get_lesson_passing_score(lesson('dictation', {})) == PASSING_SCORE_DICTATION == 75
    assert get_lesson_passing_score(lesson('audio_fill_blank', {})) == PASSING_SCORE_DEFAULT == 70
    assert get_lesson_passing_score(lesson('translation', None)) == 70


@pytest.mark.parametrize('kind', ['dictation', 'translation', 'audio_fill_blank', 'test_out'])
def test_unrelated_types_preserve_authored_overrides(kind):
    assert get_lesson_passing_score(lesson(kind, {'passing_score_percent': 85})) == 85
    assert get_lesson_passing_score(lesson(kind, {'passing_score': 80})) == 80
    assert get_lesson_passing_score(lesson(kind, {'passing_score_percent': 90, 'passing_score': 50})) == 90


@pytest.mark.parametrize('invalid', ['bogus', 150, -10, 0])
def test_malformed_non_quiz_override_falls_back(invalid):
    assert get_lesson_passing_score(lesson('translation', {'passing_score_percent': invalid})) == 70
    assert get_lesson_passing_score(lesson('dictation', {'passing_score_percent': invalid})) == 75
