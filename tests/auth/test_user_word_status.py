"""Tests for User.set_word_status ease_factor constant usage."""
import pytest

from app.auth.models import User
from app.srs.constants import DEFAULT_EASE_FACTOR
from app.utils.db import db


@pytest.fixture()
def word(db_session):
    from app.words.models import CollectionWords
    w = CollectionWords(english_word='testword', russian_word='тестслово')
    db_session.add(w)
    db_session.flush()
    return w


class TestSetWordStatusEaseFactor:
    def test_is_already_known_uses_default_ease_factor_new_word(
        self, app, db_session, test_user, word
    ):
        """Creating an 'already known' card (status=3) uses DEFAULT_EASE_FACTOR."""
        from app.study.models import UserCardDirection, UserWord
        db_session.commit()

        test_user.set_word_status(word.id, 3)
        db_session.commit()

        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=word.id).first()
        assert uw is not None
        cards = UserCardDirection.query.filter_by(user_word_id=uw.id).all()
        assert len(cards) == 2
        for card in cards:
            assert card.ease_factor == DEFAULT_EASE_FACTOR

    def test_is_already_known_updates_existing_cards_to_at_least_default(
        self, app, db_session, test_user, word
    ):
        """Updating an existing word to 'already known' does not set ease below DEFAULT."""
        from app.study.models import UserCardDirection, UserWord
        db_session.commit()

        # First create as 'new'
        test_user.set_word_status(word.id, 1)
        db_session.commit()

        # Now promote to 'already known'
        test_user.set_word_status(word.id, 3)
        db_session.commit()

        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=word.id).first()
        cards = UserCardDirection.query.filter_by(user_word_id=uw.id).all()
        for card in cards:
            assert card.ease_factor >= DEFAULT_EASE_FACTOR


class TestSetWordStatusAlreadyKnownSrsInvariants:
    """status=3 («Уже знаю») — разметка, а не реальный грейд карточки."""

    def test_does_not_consume_new_card_budget(
        self, app, db_session, test_user, word
    ):
        """first_reviewed не ставится — иначе массовая разметка известных
        слов съедала бы дневной бюджет новых карточек."""
        from app.srs.counting import count_new_cards_today
        from app.study.models import UserCardDirection, UserWord
        db_session.commit()

        test_user.set_word_status(word.id, 3)
        db_session.commit()

        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=word.id).first()
        cards = UserCardDirection.query.filter_by(user_word_id=uw.id).all()
        assert len(cards) == 2
        for card in cards:
            assert card.first_reviewed is None
            assert card.last_reviewed is None
        assert count_new_cards_today(test_user.id, db) == 0

    def test_next_review_is_naive_day_anchored(
        self, app, db_session, test_user, word
    ):
        """next_review — naive UTC (конвенция колонок) и day-anchored
        от локальной полуночи, как у apply_review_schedule."""
        from app.study.models import UserCardDirection, UserWord
        from app.utils.time_utils import day_to_naive_utc
        db_session.commit()

        test_user.set_word_status(word.id, 3)
        db_session.commit()

        expected = day_to_naive_utc(
            test_user.id, db, days_ahead=UserWord.MASTERED_THRESHOLD_DAYS,
        )
        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=word.id).first()
        cards = UserCardDirection.query.filter_by(user_word_id=uw.id).all()
        for card in cards:
            assert card.next_review.tzinfo is None
            assert card.next_review == expected
            assert card.state == 'review'
