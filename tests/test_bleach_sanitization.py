"""
Tests for bleach sanitization of user-provided text fields.
Ensures <script> and other HTML tags are stripped before storage.
Covers: deck routes, vocab annotations, word etymology, notification rendering.
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


class TestVocabAnnotationSanitization:
    """Verify that HTML/script tags are stripped from vocabulary annotations."""

    @pytest.mark.smoke
    def test_script_tag_stripped_from_annotation(self, authenticated_client, test_word, db_session):
        """Saving annotation with <script> stores plain text (tags removed, text preserved)."""
        response = authenticated_client.post(
            f'/curriculum/api/words/{test_word.id}/annotation',
            json={'note': '<script>xss</script>my note'},
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data.get('ok') is True
        assert '<script>' not in data['note']
        assert '</script>' not in data['note']

    def test_img_onerror_stripped_from_annotation(self, authenticated_client, test_word, db_session):
        """Saving annotation with onerror handler strips the HTML."""
        response = authenticated_client.post(
            f'/curriculum/api/words/{test_word.id}/annotation',
            json={'note': '<img src=x onerror=alert(1)>clean note'},
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert '<img' not in data['note']
        assert 'onerror' not in data['note']
        assert 'clean note' in data['note']

    def test_html_only_annotation_rejected(self, authenticated_client, test_word, db_session):
        """An annotation that is only HTML tags becomes empty and returns 400."""
        response = authenticated_client.post(
            f'/curriculum/api/words/{test_word.id}/annotation',
            json={'note': '<script></script>'},
            content_type='application/json',
        )
        assert response.status_code == 400

    def test_plain_text_annotation_preserved(self, authenticated_client, test_word, db_session):
        """Plain text annotation is stored as-is."""
        response = authenticated_client.post(
            f'/curriculum/api/words/{test_word.id}/annotation',
            json={'note': 'This is a plain text note about the word.'},
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['note'] == 'This is a plain text note about the word.'

    def test_empty_annotation_rejected(self, authenticated_client, test_word, db_session):
        """Empty note returns 400."""
        response = authenticated_client.post(
            f'/curriculum/api/words/{test_word.id}/annotation',
            json={'note': ''},
            content_type='application/json',
        )
        assert response.status_code == 400


class TestEtymologySanitization:
    """Verify that etymology field is sanitized via bleach in the service layer."""

    def test_strip_html_helper_strips_tags(self):
        """_strip_html removes all HTML tags from etymology."""
        from app.words.detail_service import _strip_html

        assert _strip_html('<b>Latin</b> origo') == 'Latin origo'
        assert _strip_html('<script>alert(1)</script>word') == 'alert(1)word'
        assert _strip_html('plain etymology') == 'plain etymology'
        assert _strip_html('') == ''
        assert _strip_html(None) == ''

    def test_build_word_profile_sanitizes_etymology(self, db_session):
        """build_word_profile strips HTML tags from etymology field."""
        from app.words.models import CollectionWords
        from app.words.detail_service import build_word_profile
        import uuid

        word = CollectionWords(
            english_word=f'xss_test_{uuid.uuid4().hex[:6]}',
            russian_word='тест',
            level='A1',
            etymology='<script>xss</script>From Latin',
        )
        db_session.add(word)
        db_session.flush()

        profile = build_word_profile(word)
        assert '<script>' not in profile['etymology']
        assert '</script>' not in profile['etymology']
        assert 'From Latin' in profile['etymology']


class TestNotificationXSSSafety:
    """Verify notification API returns plain text messages safe for textContent rendering."""

    @pytest.mark.smoke
    def test_notification_api_returns_json_with_message(self, authenticated_client, db_session):
        """GET /api/notifications/list returns notification messages as plain strings."""
        from app.notifications.models import Notification
        from app.utils.db import db as _db

        user = authenticated_client.application.test_user
        notif = Notification(
            user_id=user.id,
            type='system',
            title='Test',
            message='Plain text notification message',
        )
        _db.session.add(notif)
        _db.session.commit()

        response = authenticated_client.get('/api/notifications/list')
        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') is True
        notifications = data.get('notifications', [])
        assert isinstance(notifications, list)
        found = next(
            (n for n in notifications if n.get('message') == 'Plain text notification message'),
            None,
        )
        assert found is not None

    def test_notification_with_html_message_stored_as_text(self, authenticated_client, db_session):
        """Notification message with HTML is stored/returned as string (textContent handles escaping)."""
        from app.notifications.models import Notification
        from app.utils.db import db as _db

        user = authenticated_client.application.test_user
        notif = Notification(
            user_id=user.id,
            type='system',
            title='XSS test',
            message='<b>bold text</b> notification',
        )
        _db.session.add(notif)
        _db.session.commit()

        response = authenticated_client.get('/api/notifications/list')
        assert response.status_code == 200
        data = response.get_json()
        notifications = data.get('notifications', [])
        found = next(
            (n for n in notifications if '<b>bold text</b>' in (n.get('message') or '')),
            None,
        )
        assert found is not None, "API returns raw message string; textContent in browser handles escaping"
