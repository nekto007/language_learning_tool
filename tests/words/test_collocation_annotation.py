"""Tests for WordCollocation queries, VocabAnnotation validation,
frequency_band=None safety, and etymology HTML sanitization (Task 18).
"""
import uuid

import pytest

from app.curriculum.models import WordCollocation, VocabAnnotation
from app.words.detail_service import build_word_profile, _strip_html
from app.words.models import CollectionWords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_word(db_session, **kwargs) -> CollectionWords:
    defaults = dict(
        english_word=f'word_{uuid.uuid4().hex[:8]}',
        russian_word='слово',
        level='A1',
        item_type='word',
    )
    defaults.update(kwargs)
    w = CollectionWords(**defaults)
    db_session.add(w)
    db_session.flush()
    return w


# ---------------------------------------------------------------------------
# 1. WordCollocation — empty result is safe
# ---------------------------------------------------------------------------

class TestWordCollocationEmpty:
    @pytest.mark.smoke
    def test_word_without_collocations_returns_empty_list(self, db_session):
        word = _make_word(db_session)
        result = (
            WordCollocation.query
            .filter(WordCollocation.word_id == word.id)
            .order_by(WordCollocation.id)
            .all()
        )
        assert result == []

    def test_word_with_collocations_returns_them(self, db_session):
        word = _make_word(db_session)
        col = WordCollocation(
            word_id=word.id,
            collocation_phrase='make a decision',
            translation='принять решение',
        )
        db_session.add(col)
        db_session.flush()
        result = (
            WordCollocation.query
            .filter(WordCollocation.word_id == word.id)
            .all()
        )
        assert len(result) == 1
        assert result[0].collocation_phrase == 'make a decision'

    def test_build_word_profile_with_no_collocations_does_not_raise(self, db_session):
        """build_word_profile must not raise for a word with no collocations."""
        word = _make_word(db_session)
        profile = build_word_profile(word)
        assert isinstance(profile, dict)


# ---------------------------------------------------------------------------
# 2. VocabAnnotation — AJAX validation
# ---------------------------------------------------------------------------

class TestVocabAnnotationValidation:
    @pytest.fixture
    def word(self, db_session):
        return _make_word(db_session)

    @pytest.mark.smoke
    def test_empty_note_returns_400(self, authenticated_client, db_session, word):
        resp = authenticated_client.post(
            f'/curriculum/api/words/{word.id}/annotation',
            json={'note': ''},
            content_type='application/json',
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'error' in data

    def test_whitespace_only_note_returns_400(self, authenticated_client, db_session, word):
        resp = authenticated_client.post(
            f'/curriculum/api/words/{word.id}/annotation',
            json={'note': '   '},
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_valid_note_returns_200(self, authenticated_client, db_session, word):
        resp = authenticated_client.post(
            f'/curriculum/api/words/{word.id}/annotation',
            json={'note': 'my study note'},
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['note'] == 'my study note'

    def test_note_too_long_returns_400(self, authenticated_client, db_session, word):
        resp = authenticated_client.post(
            f'/curriculum/api/words/{word.id}/annotation',
            json={'note': 'x' * 2001},
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_missing_note_key_returns_400(self, authenticated_client, db_session, word):
        resp = authenticated_client.post(
            f'/curriculum/api/words/{word.id}/annotation',
            json={},
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_nonexistent_word_returns_404(self, authenticated_client):
        resp = authenticated_client.post(
            '/curriculum/api/words/999999/annotation',
            json={'note': 'test'},
            content_type='application/json',
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. frequency_band=None — no KeyError in build_word_profile
# ---------------------------------------------------------------------------

class TestFrequencyBandNone:
    @pytest.mark.smoke
    def test_frequency_band_none_does_not_raise(self, db_session):
        word = _make_word(db_session, frequency_band=None)
        profile = build_word_profile(word)
        assert isinstance(profile, dict)
        # frequency_band=None should give a label without crashing
        assert 'frequency_band_label' in profile

    def test_frequency_band_1_gives_correct_label(self, db_session):
        word = _make_word(db_session, frequency_band=1)
        profile = build_word_profile(word)
        assert 'Top 1000' in profile['frequency_band_label']

    def test_frequency_band_none_excluded_from_facts(self, db_session):
        word = _make_word(db_session, frequency_band=None)
        profile = build_word_profile(word)
        labels = [f['label'] for f in profile['study_facts']]
        assert 'Частотная группа' not in labels

    def test_frequency_band_set_included_in_facts(self, db_session):
        word = _make_word(db_session, frequency_band=2)
        profile = build_word_profile(word)
        labels = [f['label'] for f in profile['study_facts']]
        assert 'Частотная группа' in labels


# ---------------------------------------------------------------------------
# 4. Etymology HTML sanitization
# ---------------------------------------------------------------------------

class TestEtymologySanitization:
    @pytest.mark.smoke
    def test_strip_html_removes_script_tags(self):
        result = _strip_html('<script>alert(1)</script>plain text')
        assert '<script>' not in result
        assert 'plain text' in result

    def test_strip_html_removes_all_tags(self):
        result = _strip_html('<b>bold</b> and <i>italic</i>')
        assert result == 'bold and italic'

    def test_strip_html_empty_string(self):
        assert _strip_html('') == ''

    def test_strip_html_none_like(self):
        assert _strip_html(None) == ''

    def test_build_word_profile_strips_etymology_html(self, db_session):
        word = _make_word(db_session, etymology='<b>Latin</b> <script>evil()</script>origin')
        profile = build_word_profile(word)
        assert '<b>' not in profile['etymology']
        assert '<script>' not in profile['etymology']
        assert 'Latin' in profile['etymology']
        assert 'origin' in profile['etymology']

    def test_build_word_profile_etymology_none_gives_empty(self, db_session):
        word = _make_word(db_session, etymology=None)
        profile = build_word_profile(word)
        assert profile['etymology'] == ''

    def test_build_word_profile_plain_etymology_unchanged(self, db_session):
        word = _make_word(db_session, etymology='From Old English "god"')
        profile = build_word_profile(word)
        assert profile['etymology'] == 'From Old English "god"'
