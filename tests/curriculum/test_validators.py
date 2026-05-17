"""Tests for LessonContentValidator, focusing on the dictation lesson type."""
from __future__ import annotations

import pytest
from marshmallow import ValidationError

from app.curriculum.validators import LessonContentValidator


class TestDictationValidator:
    def _validate(self, payload):
        return LessonContentValidator.validate('dictation', payload)

    def test_valid_payload_passes(self):
        ok, err, data = self._validate({
            'audio_url': '/static/audio/lesson1.mp3',
            'transcript': 'The quick brown fox jumps over the lazy dog.',
        })
        assert ok is True
        assert err is None
        assert data['audio_url'] == '/static/audio/lesson1.mp3'
        assert data['transcript'] == 'The quick brown fox jumps over the lazy dog.'
        assert data['hint_chars'] == 0

    def test_hint_chars_default_zero(self):
        ok, _, data = self._validate({
            'audio_url': '/audio/a.mp3',
            'transcript': 'Hello world.',
        })
        assert data['hint_chars'] == 0

    def test_hint_chars_explicit(self):
        ok, _, data = self._validate({
            'audio_url': '/audio/a.mp3',
            'transcript': 'Hello world.',
            'hint_chars': 3,
        })
        assert data['hint_chars'] == 3

    def test_missing_audio_url_fails(self):
        with pytest.raises(ValidationError) as exc_info:
            LessonContentValidator.validate('dictation', {
                'transcript': 'Some text here.',
            })
        messages = exc_info.value.messages
        assert 'audio_url' in messages

    def test_missing_transcript_fails(self):
        with pytest.raises(ValidationError) as exc_info:
            LessonContentValidator.validate('dictation', {
                'audio_url': '/audio/a.mp3',
            })
        messages = exc_info.value.messages
        assert 'transcript' in messages

    def test_empty_audio_url_fails(self):
        with pytest.raises(ValidationError):
            LessonContentValidator.validate('dictation', {
                'audio_url': '',
                'transcript': 'Some text.',
            })

    def test_empty_transcript_fails(self):
        with pytest.raises(ValidationError):
            LessonContentValidator.validate('dictation', {
                'audio_url': '/audio/a.mp3',
                'transcript': '',
            })

    def test_unknown_lesson_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown lesson type"):
            LessonContentValidator.validate('nonexistent_type', {})


class TestDictationXPSource:
    def test_dictation_in_lesson_type_to_source(self):
        from app.daily_plan.linear.xp import LESSON_TYPE_TO_SOURCE
        assert LESSON_TYPE_TO_SOURCE['dictation'] == 'linear_curriculum_dictation'

    def test_dictation_in_linear_xp(self):
        from app.achievements.xp_service import LINEAR_XP
        assert LINEAR_XP['linear_curriculum_dictation'] == 20

    def test_get_source_for_dictation(self):
        from app.daily_plan.linear.xp import get_source_for_lesson_type
        assert get_source_for_lesson_type('dictation') == 'linear_curriculum_dictation'
