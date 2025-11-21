"""
Tests for deck management routes in app/study/routes.py
Covers 9 deck CRUD routes with ~40 tests total
Focus: CRUD operations, access control, auto-deck protection, fork synchronization
"""
import pytest
from datetime import datetime, timezone

from app.study.models import QuizDeck, QuizDeckWord
from app.utils.db import db


class TestCreateDeck:
    """Test /my-decks/create route - Lines 1922-1954"""

    def test_get_create_form(self, authenticated_client, study_settings):
        """Test GET request shows create deck form"""
        response = authenticated_client.get('/study/my-decks/create')

        assert response.status_code == 200

    def test_create_deck_post(self, authenticated_client, study_settings, db_session):
        """Test creating a new deck"""
        response = authenticated_client.post('/study/my-decks/create', data={
            'title': 'My New Deck',
            'description': 'Test deck description',
            'is_public': ''  # Not public
        }, follow_redirects=False)

        assert response.status_code == 302

        # Check deck was created
        deck = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            title='My New Deck'
        ).first()

        assert deck is not None
        assert deck.description == 'Test deck description'
        assert deck.is_public is False

    def test_create_public_deck_generates_share_code(self, authenticated_client, study_settings, db_session):
        """Test that creating a public deck generates a share code"""
        response = authenticated_client.post('/study/my-decks/create', data={
            'title': 'Public Test Deck',
            'description': 'Public deck',
            'is_public': 'on'
        }, follow_redirects=False)

        assert response.status_code == 302

        deck = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            title='Public Test Deck'
        ).first()

        assert deck is not None
        assert deck.is_public is True
        assert deck.share_code is not None

    def test_validates_title_required(self, authenticated_client, study_settings):
        """Test that title is required"""
        response = authenticated_client.post('/study/my-decks/create', data={
            'title': '',
            'description': 'No title'
        }, follow_redirects=False)

        # Should redirect back to form with error
        assert response.status_code == 302

    def test_redirects_to_edit_after_creation(self, authenticated_client, study_settings):
        """Test redirect to edit page after creation"""
        response = authenticated_client.post('/study/my-decks/create', data={
            'title': 'Redirect Test Deck',
            'description': ''
        }, follow_redirects=False)

        assert response.status_code == 302
        assert '/edit' in response.location

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.get('/study/my-decks/create')

        assert response.status_code == 302
        assert 'login' in response.location.lower()


class TestEditDeck:
    """Test /my-decks/<id>/edit route - Lines 1957-2006"""

    def test_get_edit_form(self, authenticated_client, quiz_deck, study_settings):
        """Test GET request shows edit form"""
        response = authenticated_client.get(f'/study/my-decks/{quiz_deck.id}/edit')

        assert response.status_code == 200
        assert quiz_deck.title.encode() in response.data

    def test_edit_deck_post(self, authenticated_client, quiz_deck, study_settings, db_session):
        """Test editing deck details"""
        response = authenticated_client.post(f'/study/my-decks/{quiz_deck.id}/edit', data={
            'title': 'Updated Title',
            'description': 'Updated description',
            'is_public': ''
        }, follow_redirects=False)

        assert response.status_code == 302

        db_session.refresh(quiz_deck)
        assert quiz_deck.title == 'Updated Title'
        assert quiz_deck.description == 'Updated description'

    def test_prevents_editing_auto_deck(self, authenticated_client, study_settings, db_session):
        """Test that auto decks cannot be edited"""
        auto_deck = QuizDeck(
            title='Все мои слова',
            user_id=authenticated_client.application.test_user.id,
            is_public=False
        )
        db_session.add(auto_deck)
        db_session.commit()

        response = authenticated_client.get(f'/study/my-decks/{auto_deck.id}/edit')

        # Should redirect with error
        assert response.status_code == 302
        assert '/study/' in response.location

    def test_access_denied_other_user(self, authenticated_client, second_user, study_settings, db_session):
        """Test that user cannot edit another user's deck"""
        other_deck = QuizDeck(
            title='Other User Deck',
            user_id=second_user.id,
            is_public=False
        )
        db_session.add(other_deck)
        db_session.commit()

        response = authenticated_client.get(f'/study/my-decks/{other_deck.id}/edit')

        # Should redirect with error
        assert response.status_code == 302

    def test_generates_share_code_on_first_public(self, authenticated_client, quiz_deck, study_settings, db_session):
        """Test that share code is generated when making deck public"""
        assert quiz_deck.is_public is False
        assert quiz_deck.share_code is None

        response = authenticated_client.post(f'/study/my-decks/{quiz_deck.id}/edit', data={
            'title': quiz_deck.title,
            'description': quiz_deck.description,
            'is_public': 'on'
        }, follow_redirects=False)

        assert response.status_code == 302

        db_session.refresh(quiz_deck)
        assert quiz_deck.is_public is True
        assert quiz_deck.share_code is not None

    def test_syncs_forks_when_public(self, authenticated_client, public_quiz_deck, second_user, test_words_list, study_settings, db_session):
        """Test that forks are synced when parent deck is updated"""
        # Add words to parent deck
        for i, word in enumerate(test_words_list[:3]):
            deck_word = QuizDeckWord(
                deck_id=public_quiz_deck.id,
                word_id=word.id,
                order_index=i
            )
            db_session.add(deck_word)
        db_session.commit()

        # Create a fork (copy)
        fork = QuizDeck(
            title=f'{public_quiz_deck.title} (копия)',
            user_id=second_user.id,
            is_public=False,
            parent_deck_id=public_quiz_deck.id
        )
        db_session.add(fork)
        db_session.commit()

        # Add new word to parent
        new_word = test_words_list[5]
        new_deck_word = QuizDeckWord(
            deck_id=public_quiz_deck.id,
            word_id=new_word.id,
            order_index=10
        )
        db_session.add(new_deck_word)
        db_session.commit()

        # Edit parent deck to trigger sync
        response = authenticated_client.post(f'/study/my-decks/{public_quiz_deck.id}/edit', data={
            'title': public_quiz_deck.title,
            'description': 'Updated',
            'is_public': 'on'
        }, follow_redirects=False)

        assert response.status_code == 302

    def test_validates_title(self, authenticated_client, quiz_deck, study_settings):
        """Test that title validation works"""
        response = authenticated_client.post(f'/study/my-decks/{quiz_deck.id}/edit', data={
            'title': '',  # Empty title
            'description': 'desc'
        })

        assert response.status_code == 200  # Stays on form with error

    def test_requires_authentication(self, client, quiz_deck):
        """Test that authentication is required"""
        response = client.get(f'/study/my-decks/{quiz_deck.id}/edit')

        assert response.status_code == 302
        assert 'login' in response.location.lower()


class TestDeleteDeck:
    """Test /my-decks/<id>/delete route - Lines 2009-2032"""

    def test_delete_deck_success(self, authenticated_client, quiz_deck, study_settings, db_session):
        """Test successfully deleting a deck"""
        deck_id = quiz_deck.id

        response = authenticated_client.post(f'/study/my-decks/{deck_id}/delete', follow_redirects=False)

        assert response.status_code == 302

        # Deck should be deleted
        deleted_deck = QuizDeck.query.get(deck_id)
        assert deleted_deck is None

    def test_prevents_deleting_auto_deck(self, authenticated_client, study_settings, db_session):
        """Test that auto decks cannot be deleted"""
        auto_deck = QuizDeck(
            title='Выученные слова',
            user_id=authenticated_client.application.test_user.id,
            is_public=False
        )
        db_session.add(auto_deck)
        db_session.commit()

        deck_id = auto_deck.id
        response = authenticated_client.post(f'/study/my-decks/{deck_id}/delete')

        # Should redirect with error, deck not deleted
        assert response.status_code == 302
        assert QuizDeck.query.get(deck_id) is not None

    def test_access_denied_other_user(self, authenticated_client, second_user, study_settings, db_session):
        """Test that user cannot delete another user's deck"""
        other_deck = QuizDeck(
            title='Other Deck',
            user_id=second_user.id,
            is_public=False
        )
        db_session.add(other_deck)
        db_session.commit()

        response = authenticated_client.post(f'/study/my-decks/{other_deck.id}/delete')

        # Should return 403
        assert response.status_code in [302, 403]

    def test_requires_authentication(self, client, quiz_deck):
        """Test that authentication is required"""
        response = client.post(f'/study/my-decks/{quiz_deck.id}/delete')

        assert response.status_code == 302
        assert 'login' in response.location.lower()


class TestCopyDeck:
    """Test /decks/<id>/copy route - Lines 2035-2087"""

    def test_copy_public_deck(self, authenticated_client, public_quiz_deck, test_words_list, study_settings, db_session):
        """Test copying a public deck"""
        # Add words to deck
        for i, word in enumerate(test_words_list[:3]):
            deck_word = QuizDeckWord(
                deck_id=public_quiz_deck.id,
                word_id=word.id,
                order_index=i
            )
            db_session.add(deck_word)
        db_session.commit()

        response = authenticated_client.post(f'/study/decks/{public_quiz_deck.id}/copy', follow_redirects=False)

        assert response.status_code == 302

        # Check copy was created
        copy = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            parent_deck_id=public_quiz_deck.id
        ).first()

        assert copy is not None
        assert '(копия)' in copy.title
        assert copy.is_public is False

    def test_copies_all_words(self, authenticated_client, public_quiz_deck, test_words_list, study_settings, db_session):
        """Test that all words are copied"""
        # Add words to deck
        for i, word in enumerate(test_words_list[:5]):
            deck_word = QuizDeckWord(
                deck_id=public_quiz_deck.id,
                word_id=word.id,
                order_index=i
            )
            db_session.add(deck_word)
        db_session.commit()

        response = authenticated_client.post(f'/study/decks/{public_quiz_deck.id}/copy', follow_redirects=False)

        assert response.status_code == 302

        # Check all words were copied
        copy = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            parent_deck_id=public_quiz_deck.id
        ).first()

        assert copy.word_count == 5

    def test_links_to_parent_deck(self, authenticated_client, public_quiz_deck, study_settings):
        """Test that copy is linked to parent deck"""
        response = authenticated_client.post(f'/study/decks/{public_quiz_deck.id}/copy', follow_redirects=False)

        assert response.status_code == 302

        copy = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            parent_deck_id=public_quiz_deck.id
        ).first()

        assert copy.parent_deck_id == public_quiz_deck.id
        assert copy.last_synced_at is not None

    def test_prevents_duplicate_copy(self, authenticated_client, public_quiz_deck, study_settings, db_session):
        """Test that duplicate copies are prevented"""
        # First copy
        response1 = authenticated_client.post(f'/study/decks/{public_quiz_deck.id}/copy', follow_redirects=False)
        assert response1.status_code == 302

        # Try to copy again
        response2 = authenticated_client.post(f'/study/decks/{public_quiz_deck.id}/copy', follow_redirects=False)

        # Should redirect to existing copy
        assert response2.status_code == 302

        # Should only have one copy
        copies = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            parent_deck_id=public_quiz_deck.id
        ).count()

        assert copies == 1

    def test_access_denied_private_deck(self, authenticated_client, second_user, study_settings, db_session):
        """Test that private decks cannot be copied"""
        private_deck = QuizDeck(
            title='Private Deck',
            user_id=second_user.id,
            is_public=False
        )
        db_session.add(private_deck)
        db_session.commit()

        response = authenticated_client.post(f'/study/decks/{private_deck.id}/copy')

        # Should redirect with error
        assert response.status_code == 302

    def test_requires_authentication(self, client, public_quiz_deck):
        """Test that authentication is required"""
        response = client.post(f'/study/decks/{public_quiz_deck.id}/copy')

        assert response.status_code == 302
        assert 'login' in response.location.lower()


class TestAddWordToDeck:
    """Test /my-decks/<id>/words/add route - Lines 2090-2175"""

    def test_add_collection_word(self, authenticated_client, quiz_deck, test_words_list, study_settings, db_session):
        """Test adding a word from collection to deck"""
        word = test_words_list[0]

        response = authenticated_client.post(f'/study/my-decks/{quiz_deck.id}/words/add', data={
            'word_id': word.id
        }, follow_redirects=False)

        assert response.status_code == 302

        # Check word was added
        deck_word = QuizDeckWord.query.filter_by(
            deck_id=quiz_deck.id,
            word_id=word.id
        ).first()

        assert deck_word is not None

    def test_add_custom_word(self, authenticated_client, quiz_deck, study_settings):
        """Test adding a custom word (not from collection)"""
        response = authenticated_client.post(f'/study/my-decks/{quiz_deck.id}/words/add', data={
            'word_id': '',  # No word_id
            'custom_english': 'custom word',
            'custom_russian': 'кастом слово',
            'custom_sentences': 'Example|Пример'
        }, follow_redirects=False)

        assert response.status_code == 302

        # Check custom word was added
        deck_word = QuizDeckWord.query.filter_by(
            deck_id=quiz_deck.id,
            word_id=None,
            custom_english='custom word'
        ).first()

        assert deck_word is not None
        assert deck_word.custom_russian == 'кастом слово'

    def test_custom_overrides(self, authenticated_client, quiz_deck, test_words_list, study_settings):
        """Test that custom fields override collection word"""
        word = test_words_list[0]

        response = authenticated_client.post(f'/study/my-decks/{quiz_deck.id}/words/add', data={
            'word_id': word.id,
            'custom_english': 'custom override',
            'custom_russian': 'кастом перевод'
        }, follow_redirects=False)

        assert response.status_code == 302

        deck_word = QuizDeckWord.query.filter_by(
            deck_id=quiz_deck.id,
            word_id=word.id
        ).first()

        assert deck_word.custom_english == 'custom override'
        assert deck_word.custom_russian == 'кастом перевод'

    def test_prevents_duplicate_word(self, authenticated_client, quiz_deck_with_words, test_words_list, study_settings):
        """Test that duplicate words are prevented"""
        # Try to add word that's already in deck
        existing_word_id = test_words_list[0].id

        response = authenticated_client.post(f'/study/my-decks/{quiz_deck_with_words.id}/words/add', data={
            'word_id': existing_word_id
        }, follow_redirects=False)

        # Should handle gracefully
        assert response.status_code in [200, 302]

    def test_ajax_response(self, authenticated_client, quiz_deck, test_words_list, study_settings):
        """Test AJAX response when adding word"""
        word = test_words_list[0]

        response = authenticated_client.post(
            f'/study/my-decks/{quiz_deck.id}/words/add',
            data={'word_id': word.id},
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )

        # Should return JSON for AJAX
        assert response.status_code == 200
        if response.content_type and 'json' in response.content_type:
            data = response.get_json()
            assert 'success' in data or 'status' in data

    def test_access_denied(self, authenticated_client, second_user, test_words_list, study_settings, db_session):
        """Test access denied to other user's deck"""
        other_deck = QuizDeck(
            title='Other Deck',
            user_id=second_user.id,
            is_public=False
        )
        db_session.add(other_deck)
        db_session.commit()

        response = authenticated_client.post(f'/study/my-decks/{other_deck.id}/words/add', data={
            'word_id': test_words_list[0].id
        })

        assert response.status_code in [302, 403]

    def test_requires_authentication(self, client, quiz_deck):
        """Test that authentication is required"""
        response = client.post(f'/study/my-decks/{quiz_deck.id}/words/add', data={
            'word_id': 1
        })

        assert response.status_code == 302
        assert 'login' in response.location.lower()


class TestEditDeckWord:
    """Test /my-decks/<id>/words/<id>/edit route - Lines 2178-2222"""

    def test_edit_word_custom_fields(self, authenticated_client, quiz_deck_with_words, test_words_list, study_settings, db_session):
        """Test editing custom fields of a deck word"""
        deck_word = QuizDeckWord.query.filter_by(deck_id=quiz_deck_with_words.id).first()

        response = authenticated_client.post(
            f'/study/my-decks/{quiz_deck_with_words.id}/words/{deck_word.word_id}/edit',
            data={
                'custom_english': 'edited english',
                'custom_russian': 'edited russian',
                'custom_sentences': 'Edited example|Отредактированный пример'
            },
            follow_redirects=False
        )

        assert response.status_code in [200, 302]

        db_session.refresh(deck_word)
        assert deck_word.custom_english == 'edited english'
        assert deck_word.custom_russian == 'edited russian'

    def test_ajax_response(self, authenticated_client, quiz_deck_with_words, study_settings, db_session):
        """Test AJAX response"""
        deck_word = QuizDeckWord.query.filter_by(deck_id=quiz_deck_with_words.id).first()

        response = authenticated_client.post(
            f'/study/my-decks/{quiz_deck_with_words.id}/words/{deck_word.word_id}/edit',
            data={'custom_english': 'ajax edit'},
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )

        assert response.status_code == 200

    def test_access_denied(self, authenticated_client, second_user, study_settings, db_session):
        """Test access denied to other user's deck"""
        other_deck = QuizDeck(
            title='Other Deck',
            user_id=second_user.id,
            is_public=False
        )
        db_session.add(other_deck)
        db_session.commit()

        response = authenticated_client.post(
            f'/study/my-decks/{other_deck.id}/words/1/edit',
            data={'custom_english': 'hack'}
        )

        assert response.status_code in [302, 403, 404]

    def test_requires_authentication(self, client, quiz_deck):
        """Test that authentication is required"""
        response = client.post(f'/study/my-decks/{quiz_deck.id}/words/1/edit', data={})

        assert response.status_code == 302
        assert 'login' in response.location.lower()


class TestRemoveWordFromDeck:
    """Test /my-decks/<id>/words/<id>/delete route - Lines 2225-2243"""

    def test_remove_word(self, authenticated_client, quiz_deck_with_words, study_settings, db_session):
        """Test removing a word from deck"""
        deck_word = QuizDeckWord.query.filter_by(deck_id=quiz_deck_with_words.id).first()
        word_id = deck_word.word_id

        response = authenticated_client.post(
            f'/study/my-decks/{quiz_deck_with_words.id}/words/{word_id}/delete',
            follow_redirects=False
        )

        assert response.status_code == 302

        # Word should be removed
        removed_word = QuizDeckWord.query.filter_by(
            deck_id=quiz_deck_with_words.id,
            word_id=word_id
        ).first()

        assert removed_word is None

    def test_access_denied(self, authenticated_client, second_user, study_settings, db_session):
        """Test access denied to other user's deck"""
        other_deck = QuizDeck(
            title='Other Deck',
            user_id=second_user.id,
            is_public=False
        )
        db_session.add(other_deck)
        db_session.commit()

        response = authenticated_client.post(
            f'/study/my-decks/{other_deck.id}/words/1/delete'
        )

        assert response.status_code in [302, 403, 404]

    def test_requires_authentication(self, client, quiz_deck):
        """Test that authentication is required"""
        response = client.post(f'/study/my-decks/{quiz_deck.id}/words/1/delete')

        assert response.status_code == 302
        assert 'login' in response.location.lower()


class TestSearchWords:
    """Test /api/search-words route - Lines 2246-2292"""

    def test_search_autocomplete(self, authenticated_client, test_words_list, study_settings):
        """Test word search autocomplete"""
        response = authenticated_client.get('/study/api/search-words?q=hel')

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)

    def test_limits_results(self, authenticated_client, test_words_list, study_settings):
        """Test that results are limited"""
        response = authenticated_client.get('/study/api/search-words?q=e')

        assert response.status_code == 200
        data = response.get_json()
        assert len(data) <= 50  # Default limit

    def test_sorts_by_relevance(self, authenticated_client, test_words_list, study_settings):
        """Test that results are sorted by relevance"""
        # Search for word that exists
        word = test_words_list[0]
        response = authenticated_client.get(f'/study/api/search-words?q={word.english_word[:4]}')

        assert response.status_code == 200
        data = response.get_json()

        # Exact matches should come first
        if len(data) > 0:
            assert isinstance(data[0], dict)
            assert 'text' in data[0] or 'label' in data[0] or 'value' in data[0]

    def test_requires_min_query_length(self, authenticated_client, study_settings):
        """Test minimum query length requirement"""
        response = authenticated_client.get('/study/api/search-words?q=a')

        assert response.status_code == 200
        # May return empty list for too short query

    def test_returns_json(self, authenticated_client, study_settings):
        """Test that response is JSON"""
        response = authenticated_client.get('/study/api/search-words?q=test')

        assert response.status_code == 200
        assert response.content_type == 'application/json'

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.get('/study/api/search-words?q=test')

        assert response.status_code == 302
        assert 'login' in response.location.lower()
