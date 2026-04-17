"""
Tests for DB session rollback behavior in DeckService multi-step operations.

Covers Task 10: verify that IntegrityError mid-operation leaves the DB clean.
"""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.exc import IntegrityError, OperationalError

from app.study.models import QuizDeck, QuizDeckWord, UserWord
from app.utils.db import db


class TestCreateDeckRollback:
    """Test that create_deck rolls back on DB error."""

    @pytest.mark.smoke
    def test_create_deck_success(self, app, db_session, test_user):
        """create_deck happy path creates deck and returns it."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            deck = DeckService.create_deck(test_user.id, 'Rollback Test Deck')
            assert deck is not None
            assert deck.id is not None
            assert deck.title == 'Rollback Test Deck'

    def test_create_deck_rollback_on_integrity_error(self, app, db_session, test_user):
        """create_deck rolls back and re-raises IntegrityError mid-flush."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            initial_deck_count = QuizDeck.query.filter_by(user_id=test_user.id).count()

            with patch.object(db.session, 'flush', side_effect=IntegrityError(
                "duplicate key", {}, Exception("pk violation")
            )):
                with pytest.raises(IntegrityError):
                    DeckService.create_deck(test_user.id, 'Should Not Exist')

            # DB should be clean — no partial deck
            after_count = QuizDeck.query.filter_by(user_id=test_user.id).count()
            assert after_count == initial_deck_count

    def test_create_deck_rollback_on_operational_error(self, app, db_session, test_user):
        """create_deck rolls back and re-raises OperationalError."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            initial_count = QuizDeck.query.filter_by(user_id=test_user.id).count()

            with patch.object(db.session, 'flush', side_effect=OperationalError(
                "connection lost", {}, Exception("db down")
            )):
                with pytest.raises(OperationalError):
                    DeckService.create_deck(test_user.id, 'Operational Error Deck')

            after_count = QuizDeck.query.filter_by(user_id=test_user.id).count()
            assert after_count == initial_count


class TestCopyDeckRollback:
    """Test that copy_deck rolls back on DB error, leaving DB clean."""

    def test_copy_deck_success(self, app, db_session, test_user, public_quiz_deck):
        """copy_deck happy path returns new deck."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            new_deck, error = DeckService.copy_deck(public_quiz_deck.id, test_user.id)
            assert new_deck is not None
            assert error is None
            assert new_deck.parent_deck_id == public_quiz_deck.id

    def test_copy_deck_rollback_on_integrity_error(self, app, db_session, test_user, public_quiz_deck):
        """copy_deck rolls back and returns (None, error) on IntegrityError."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            initial_count = QuizDeck.query.filter_by(user_id=test_user.id).count()

            # Simulate IntegrityError at flush (after new_deck add)
            with patch.object(db.session, 'flush', side_effect=IntegrityError(
                "duplicate key", {}, Exception("pk violation")
            )):
                result_deck, error = DeckService.copy_deck(public_quiz_deck.id, test_user.id)

            assert result_deck is None
            assert error is not None
            # No partial deck should remain
            after_count = QuizDeck.query.filter_by(user_id=test_user.id).count()
            assert after_count == initial_count

    def test_copy_deck_rollback_on_commit_error(self, app, db_session, test_user, public_quiz_deck):
        """copy_deck rolls back if commit raises OperationalError."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            initial_count = QuizDeck.query.filter_by(user_id=test_user.id).count()

            with patch.object(db.session, 'commit', side_effect=OperationalError(
                "deadlock detected", {}, Exception("deadlock")
            )):
                result_deck, error = DeckService.copy_deck(public_quiz_deck.id, test_user.id)

            assert result_deck is None
            assert error is not None
            after_count = QuizDeck.query.filter_by(user_id=test_user.id).count()
            assert after_count == initial_count


class TestAddBulkWordsRollback:
    """Test that add_bulk_words_to_deck rolls back on DB error."""

    def test_add_bulk_words_success(self, app, db_session, test_user, quiz_deck, test_words_list):
        """add_bulk_words_to_deck happy path adds all words."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            word_ids = [w.id for w in test_words_list[:3]]
            added, skipped = DeckService.add_bulk_words_to_deck(quiz_deck.id, test_user.id, word_ids)

            assert added == 3
            assert skipped == 0
            deck_word_count = QuizDeckWord.query.filter_by(deck_id=quiz_deck.id).count()
            assert deck_word_count == 3

    def test_add_bulk_words_rollback_on_integrity_error(
        self, app, db_session, test_user, quiz_deck, test_words_list
    ):
        """add_bulk_words_to_deck rolls back and returns (0, total) on IntegrityError."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            word_ids = [w.id for w in test_words_list[:3]]
            initial_count = QuizDeckWord.query.filter_by(deck_id=quiz_deck.id).count()

            with patch.object(db.session, 'commit', side_effect=IntegrityError(
                "unique violation", {}, Exception("duplicate deck_word")
            )):
                added, skipped = DeckService.add_bulk_words_to_deck(
                    quiz_deck.id, test_user.id, word_ids
                )

            assert added == 0
            # skipped returns total count of input words on error
            assert skipped == len(word_ids)
            # DB is clean — no partial deck words
            after_count = QuizDeckWord.query.filter_by(deck_id=quiz_deck.id).count()
            assert after_count == initial_count

    def test_add_bulk_words_rollback_on_flush_error(
        self, app, db_session, test_user, quiz_deck, test_words_list
    ):
        """add_bulk_words_to_deck rolls back when flush fails mid-loop."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            word_ids = [w.id for w in test_words_list[:2]]
            initial_user_word_count = UserWord.query.filter_by(user_id=test_user.id).count()
            initial_deck_word_count = QuizDeckWord.query.filter_by(deck_id=quiz_deck.id).count()

            with patch.object(db.session, 'flush', side_effect=OperationalError(
                "connection error", {}, Exception("db error")
            )):
                added, skipped = DeckService.add_bulk_words_to_deck(
                    quiz_deck.id, test_user.id, word_ids
                )

            assert added == 0
            # No orphaned UserWord or QuizDeckWord records
            after_user_word_count = UserWord.query.filter_by(user_id=test_user.id).count()
            after_deck_word_count = QuizDeckWord.query.filter_by(deck_id=quiz_deck.id).count()
            assert after_user_word_count == initial_user_word_count
            assert after_deck_word_count == initial_deck_word_count

    def test_add_bulk_words_empty_list(self, app, db_session, test_user, quiz_deck):
        """add_bulk_words_to_deck with empty list returns (0, 0) immediately."""
        from app.study.services.deck_service import DeckService

        with app.app_context():
            added, skipped = DeckService.add_bulk_words_to_deck(quiz_deck.id, test_user.id, [])
            assert added == 0
            assert skipped == 0
