"""Content-integrity tests for sentence_correction (audit E-092, E-100).

Guards against options/correct_sentence drift in single-item lessons and
verifies the validator helper.
"""
from __future__ import annotations

import json
import os

from app.curriculum.validators import validate_sentence_correction_content

_CONTENT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..',
    'content', 'immersion', 'sentence_correction_lessons.json',
)


def test_validator_flags_options_without_correct_sentence():
    bad = {
        'correct_sentence': 'I have a dog. It is an animal.',
        'options': ['It is an animal.', 'It is a animal.'],  # fragments
    }
    assert validate_sentence_correction_content(bad)


def test_validator_passes_when_correct_sentence_in_options():
    good = {
        'correct_sentence': 'I have a dog. It is an animal.',
        'options': [
            'I have a dog. It is a animal.',
            'I have a dog. It is an animal.',
        ],
    }
    assert validate_sentence_correction_content(good) == []


def test_validator_exempts_multi_item_and_free_text():
    assert validate_sentence_correction_content({'items': [{}]}) == []
    assert validate_sentence_correction_content(
        {'correct_sentence': 'x'}  # no options -> free text
    ) == []


def test_all_immersion_sentence_correction_lessons_are_valid():
    with open(_CONTENT_FILE, encoding='utf-8') as fh:
        lessons = json.load(fh)
    failures = {}
    for lesson in lessons:
        content = lesson.get('content', {})
        errs = validate_sentence_correction_content(content)
        if errs:
            failures[lesson.get('external_key')] = errs
    assert not failures, f"Content integrity failures: {failures}"
