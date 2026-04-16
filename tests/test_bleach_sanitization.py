"""
Tests for bleach sanitization of user-provided text fields in deck routes.
Ensures <script> and other HTML tags are stripped before storage.
"""
import pytest

from app.study.models import QuizDeck, QuizDeckWord
from app.utils.db import db


class TestBleachSanitization:
    """Verify that HTML/script tags are stripped from user-provided free text."""

    @pytest.mark.smoke
    def test_script_tag_stripped_from_deck_title(self, authenticated_client, study_settings, db_session):
        """Creating a deck with <script> in title stores plain text."""
        response = authenticated_client.post('/study/my-decks/create', data={
            'title': '<script>alert(1)</script>My Deck',
            'description': 'clean description',
        }, follow_redirects=False)

        assert response.status_code == 302

        deck = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id
        ).order_by(QuizDeck.id.desc()).first()

        assert deck is not None
        assert '<script>' not in deck.title
        assert 'alert(1)' in deck.title or deck.title == 'My Deck'

    def test_script_tag_stripped_from_deck_description(self, authenticated_client, study_settings, db_session):
        """Creating a deck with <script> in description stores sanitized text."""
        response = authenticated_client.post('/study/my-decks/create', data={
            'title': 'Clean Title Deck',
            'description': '<img src=x onerror=alert(1)>nice description',
        }, follow_redirects=False)

        assert response.status_code == 302

        deck = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            title='Clean Title Deck'
        ).first()

        assert deck is not None
        assert '<img' not in deck.description
        assert 'onerror' not in deck.description

    def test_script_tag_stripped_from_custom_sentences(self, authenticated_client, study_settings, quiz_deck, db_session):
        """Adding a word with <script> in custom_sentences stores sanitized text."""
        response = authenticated_client.post(
            f'/study/my-decks/{quiz_deck.id}/words/add',
            data={
                'word_id': '',
                'custom_english': '<b>hello</b>',
                'custom_russian': 'привет',
                'custom_sentences': '<script>alert(1)</script>Example sentence.',
            },
            follow_redirects=False
        )

        deck_word = QuizDeckWord.query.filter_by(
            deck_id=quiz_deck.id
        ).order_by(QuizDeckWord.id.desc()).first()

        if deck_word and deck_word.custom_sentences:
            assert '<script>' not in deck_word.custom_sentences
        if deck_word and deck_word.custom_english:
            assert '<b>' not in deck_word.custom_english

    def test_sanitize_helper_strips_all_tags(self):
        """Unit test: _sanitize() removes all HTML tags."""
        from app.study.deck_routes import _sanitize

        assert _sanitize('<script>alert(1)</script>text') == 'alert(1)text'
        assert _sanitize('<b>bold</b>') == 'bold'
        assert _sanitize('plain text') == 'plain text'
        assert _sanitize('<img src=x onerror=alert(1)>') == ''

    def test_api_add_phrase_script_stripped(self, authenticated_client, study_settings, quiz_deck, db_session):
        """api_add_phrase_to_deck strips <script> from english/russian/context fields."""
        user = authenticated_client.application.test_user
        user.default_study_deck_id = quiz_deck.id
        db.session.commit()

        response = authenticated_client.post(
            '/study/api/add-phrase-to-deck',
            json={
                'english': '<script>xss</script>hello',
                'russian': 'привет',
                'context': '<b>context</b>',
            }
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') is True

        deck_word = QuizDeckWord.query.filter_by(
            deck_id=quiz_deck.id
        ).order_by(QuizDeckWord.id.desc()).first()

        if deck_word:
            if deck_word.custom_english:
                assert '<script>' not in deck_word.custom_english
            if deck_word.custom_sentences:
                assert '<b>' not in deck_word.custom_sentences
