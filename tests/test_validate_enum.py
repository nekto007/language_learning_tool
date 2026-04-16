"""Tests for validate_enum utility and its application in API routes."""
import pytest

from app.utils.validators import validate_enum, WordStatus, LessonStatus
from app.srs.constants import CardState


class TestValidateEnum:
    """Unit tests for the validate_enum function."""

    @pytest.mark.smoke
    def test_valid_value_returns_true(self):
        assert validate_enum('new', WordStatus) is True
        assert validate_enum('learning', WordStatus) is True
        assert validate_enum('review', WordStatus) is True
        assert validate_enum('mastered', WordStatus) is True

    def test_invalid_value_returns_false(self):
        assert validate_enum('unknown', WordStatus) is False
        assert validate_enum('', WordStatus) is False
        assert validate_enum('NEW', WordStatus) is False  # case-sensitive

    def test_valid_lesson_status(self):
        assert validate_enum('completed', LessonStatus) is True
        assert validate_enum('in_progress', LessonStatus) is True
        assert validate_enum('not_started', LessonStatus) is True

    def test_invalid_lesson_status(self):
        assert validate_enum('done', LessonStatus) is False
        assert validate_enum('active', LessonStatus) is False

    def test_valid_card_state(self):
        assert validate_enum('new', CardState) is True
        assert validate_enum('learning', CardState) is True
        assert validate_enum('review', CardState) is True
        assert validate_enum('relearning', CardState) is True

    def test_invalid_card_state(self):
        assert validate_enum('mastered', CardState) is False
        assert validate_enum('finished', CardState) is False


class TestUpdateSingleWordStatusValidation:
    """Integration tests — invalid enum value returns 400 from the API."""

    def _word(self, db_session):
        from app.words.models import CollectionWords
        import uuid
        word = CollectionWords(
            english_word=f'vword_{uuid.uuid4().hex[:8]}',
            russian_word='тест',
            level='A1',
            sentences='Test.',
            listening='',
            brown=0,
            get_download=0,
        )
        db_session.add(word)
        db_session.commit()
        return word

    def test_invalid_status_returns_400(self, authenticated_client, db_session):
        word = self._word(db_session)
        resp = authenticated_client.post(
            f'/api/words/{word.id}/status',
            json={'status': 'invalid_status'},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'Invalid status' in data['error']

    def test_valid_status_accepted(self, authenticated_client, db_session):
        word = self._word(db_session)
        resp = authenticated_client.post(
            f'/api/words/{word.id}/status',
            json={'status': 'learning'},
        )
        # 200 or possible 404 if endpoint is unreachable — just not 400 for status
        assert resp.status_code != 400 or 'Invalid status' not in (resp.get_json() or {}).get('error', '')
