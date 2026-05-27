"""Tests for admin quiz deck management (Task 88).

Covers:
- export with 0 cards returns empty words list (not error)
- import validates format before writing to DB
- clone creates a deep copy (independent rows, not shallow reference)
- public deck flag: private deck not accessible via share code
"""
import json

import pytest

from app.study.models import QuizDeck, QuizDeckWord
from app.utils.db import db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_deck(db_session, admin_user):
    """An empty deck owned by admin_user."""
    deck = QuizDeck(
        title='Admin Test Deck',
        user_id=admin_user.id,
        is_public=False,
    )
    db_session.add(deck)
    db_session.commit()
    return deck


@pytest.fixture
def admin_deck_with_words(db_session, admin_user):
    """A deck owned by admin_user with two custom words."""
    deck = QuizDeck(
        title='Admin Deck With Words',
        user_id=admin_user.id,
        is_public=False,
    )
    db_session.add(deck)
    db_session.flush()

    for i in range(2):
        word = QuizDeckWord(
            deck_id=deck.id,
            custom_english=f'word_{i}',
            custom_russian=f'слово_{i}',
            order_index=i,
        )
        db_session.add(word)

    db_session.commit()
    return deck


@pytest.fixture
def public_deck(db_session, admin_user):
    """A public deck with a share code (uses admin_user for other tests)."""
    deck = QuizDeck(
        title='Public Deck',
        user_id=admin_user.id,
        is_public=True,
    )
    db_session.add(deck)
    db_session.flush()
    deck.generate_share_code()
    db_session.commit()
    return deck


@pytest.fixture
def private_deck_with_code(db_session, test_user):
    """A private deck with a share_code — uses test_user so client stays unauthenticated."""
    import secrets, string
    deck = QuizDeck(
        title='Private Deck',
        user_id=test_user.id,
        is_public=False,
        share_code=''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8)),
    )
    db_session.add(deck)
    db_session.commit()
    return deck


@pytest.fixture
def public_deck_no_login(db_session, test_user):
    """A public deck — uses test_user so client stays unauthenticated for share page tests."""
    deck = QuizDeck(
        title='Public Deck No Login',
        user_id=test_user.id,
        is_public=True,
    )
    db_session.add(deck)
    db_session.flush()
    deck.generate_share_code()
    db_session.commit()
    return deck


# ---------------------------------------------------------------------------
# 1. Export — 0 cards returns empty words list
# ---------------------------------------------------------------------------


class TestQuizDeckExport:

    @pytest.mark.smoke
    def test_export_empty_deck_returns_empty_words(self, client, admin_user, admin_deck, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = client.get(f'/admin/quiz-decks/{admin_deck.id}/export')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data['words'] == []
        assert data['title'] == admin_deck.title

    def test_export_deck_with_words(self, client, admin_user, admin_deck_with_words, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = client.get(f'/admin/quiz-decks/{admin_deck_with_words.id}/export')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['words']) == 2
        assert data['words'][0]['english'] == 'word_0'
        assert data['words'][0]['russian'] == 'слово_0'

    def test_export_includes_content_disposition(self, client, admin_user, admin_deck, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = client.get(f'/admin/quiz-decks/{admin_deck.id}/export')
        assert 'Content-Disposition' in resp.headers
        assert 'attachment' in resp.headers['Content-Disposition']

    def test_export_404_for_missing_deck(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = client.get('/admin/quiz-decks/99999/export')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Import — validates format before DB writes
# ---------------------------------------------------------------------------


class TestQuizDeckImport:

    def _post(self, client, data):
        return client.post(
            '/admin/quiz-decks/import',
            data=json.dumps(data),
            content_type='application/json',
        )

    @pytest.mark.smoke
    def test_import_success(self, client, admin_user, mock_admin_user, db_session):
        mock_admin_user.id = admin_user.id
        payload = {
            'title': 'Imported Deck',
            'words': [
                {'english': 'cat', 'russian': 'кот'},
                {'english': 'dog', 'russian': 'собака'},
            ],
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['word_count'] == 2
        # Verify DB was actually written
        deck = QuizDeck.query.get(data['deck_id'])
        assert deck is not None
        assert deck.title == 'Imported Deck'
        assert deck.words.count() == 2

    def test_import_empty_deck_no_words(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        payload = {'title': 'Empty Import', 'words': []}
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['word_count'] == 0

    def test_import_missing_title_returns_400(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = self._post(client, {'words': []})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'title' in data['message']

    def test_import_words_not_list_returns_400(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = self._post(client, {'title': 'Deck', 'words': 'not a list'})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'words' in data['message']

    def test_import_word_missing_english_returns_400(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        payload = {
            'title': 'Deck',
            'words': [{'russian': 'кот'}],  # missing english
        }
        resp = self._post(client, payload)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False

    def test_import_word_empty_fields_returns_400(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        payload = {
            'title': 'Deck',
            'words': [{'english': '', 'russian': 'кот'}],
        }
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_import_word_not_object_returns_400(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        payload = {
            'title': 'Deck',
            'words': ['not an object'],
        }
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_import_non_json_content_type_returns_400(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = client.post(
            '/admin/quiz-decks/import',
            data='{"title": "deck"}',
            content_type='text/plain',
        )
        assert resp.status_code == 400

    def test_import_validation_error_does_not_write_db(self, client, admin_user, mock_admin_user, db_session):
        """Validation errors must not persist any partial data."""
        mock_admin_user.id = admin_user.id
        before_count = QuizDeck.query.filter_by(user_id=admin_user.id).count()

        payload = {
            'title': 'Partial Deck',
            'words': [
                {'english': 'cat', 'russian': 'кот'},
                {'english': '', 'russian': 'собака'},  # invalid — triggers rollback path
            ],
        }
        resp = self._post(client, payload)
        assert resp.status_code == 400

        after_count = QuizDeck.query.filter_by(user_id=admin_user.id).count()
        assert after_count == before_count


# ---------------------------------------------------------------------------
# 3. Clone — deep copy (independent rows)
# ---------------------------------------------------------------------------


class TestQuizDeckClone:

    @pytest.mark.smoke
    def test_clone_creates_new_deck(self, client, admin_user, admin_deck_with_words, mock_admin_user, db_session):
        mock_admin_user.id = admin_user.id
        resp = client.post(
            f'/admin/quiz-decks/{admin_deck_with_words.id}/clone',
            headers={'Accept': 'application/json'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        new_id = data['new_deck_id']
        assert new_id != admin_deck_with_words.id

    def test_clone_deep_copies_words(self, client, admin_user, admin_deck_with_words, mock_admin_user, db_session):
        mock_admin_user.id = admin_user.id
        resp = client.post(
            f'/admin/quiz-decks/{admin_deck_with_words.id}/clone',
            headers={'Accept': 'application/json'},
        )
        new_id = resp.get_json()['new_deck_id']

        original_words = admin_deck_with_words.words.all()
        clone = QuizDeck.query.get(new_id)
        clone_words = clone.words.all()

        assert len(clone_words) == len(original_words)
        # Verify they are independent rows (different IDs)
        original_ids = {w.id for w in original_words}
        clone_ids = {w.id for w in clone_words}
        assert original_ids.isdisjoint(clone_ids), 'Clone must have distinct QuizDeckWord rows'

    def test_clone_copies_word_content(self, client, admin_user, admin_deck_with_words, mock_admin_user, db_session):
        mock_admin_user.id = admin_user.id
        resp = client.post(
            f'/admin/quiz-decks/{admin_deck_with_words.id}/clone',
            headers={'Accept': 'application/json'},
        )
        new_id = resp.get_json()['new_deck_id']
        clone = QuizDeck.query.get(new_id)
        clone_words = sorted(clone.words.all(), key=lambda w: w.order_index)

        assert clone_words[0].custom_english == 'word_0'
        assert clone_words[1].custom_russian == 'слово_1'

    def test_clone_is_private(self, client, admin_user, public_deck, mock_admin_user, db_session):
        """Clone of a public deck is private by default."""
        mock_admin_user.id = admin_user.id
        resp = client.post(
            f'/admin/quiz-decks/{public_deck.id}/clone',
            headers={'Accept': 'application/json'},
        )
        new_id = resp.get_json()['new_deck_id']
        clone = QuizDeck.query.get(new_id)
        assert clone.is_public is False

    def test_clone_404_for_missing_deck(self, client, admin_user, mock_admin_user):
        mock_admin_user.id = admin_user.id
        resp = client.post(
            '/admin/quiz-decks/99999/clone',
            headers={'Accept': 'application/json'},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Public deck flag — private deck not visible via share code
# ---------------------------------------------------------------------------


class TestPublicDeckVisibility:
    """Verify that is_public flag correctly controls share-code access.

    These tests use fixtures backed by test_user (not admin_user) so the
    test client stays unauthenticated, avoiding onboarding redirects that
    would mask the real response status.
    """

    @pytest.mark.smoke
    def test_public_deck_accessible_via_share_code(self, app, public_deck_no_login):
        """Unauthenticated user gets 200 from the public share page."""
        with app.test_client() as c:
            resp = c.get(f'/study/quiz/shared/{public_deck_no_login.share_code}')
            assert resp.status_code == 200

    def test_private_deck_not_accessible_via_share_code(self, app, private_deck_with_code):
        """Private deck must return 404 even if a share_code value exists in DB."""
        with app.test_client() as c:
            resp = c.get(f'/study/quiz/shared/{private_deck_with_code.share_code}')
            assert resp.status_code == 404

    def test_nonexistent_share_code_returns_404(self, app):
        with app.test_client() as c:
            resp = c.get('/study/quiz/shared/XXXXXXXX')
            assert resp.status_code == 404

    def test_admin_deck_without_code_not_accessible(self, app, admin_deck):
        """Deck without share_code cannot be accessed; the route only matches named codes."""
        assert admin_deck.share_code is None
        with app.test_client() as c:
            resp = c.get('/study/quiz/shared/')
            assert resp.status_code == 404
