"""Task 7: Tests for _build_cards_for_words creating both card directions.

Verify that when _build_cards_for_words creates new UserCardDirection rows for
a word that has never been added to SRS, it creates both 'eng-rus' AND 'rus-eng'
directions — not just eng-rus. Also verifies DEFAULT_EASE_FACTOR and
CardState.NEW.value are used explicitly.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.curriculum.routes.card_lessons import _build_cards_for_words
from app.srs.constants import CardState, DEFAULT_EASE_FACTOR, DIRECTION_ENG_RUS, DIRECTION_RUS_ENG
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords


@pytest.fixture()
def user(db_session):
    s = uuid.uuid4().hex[:10]
    u = User(username=f"cl_{s}", email=f"cl_{s}@example.com", active=True)
    u.set_password("pass")
    db_session.add(u)
    db_session.commit()
    return u


def _make_word(db_session) -> CollectionWords:
    s = uuid.uuid4().hex[:8]
    word = CollectionWords(english_word=f"cl_{s}", russian_word=f"рус_{s}", level="A1")
    db_session.add(word)
    db_session.commit()
    return word


def _directions_for_user_word(db_session, user_word_id: int) -> list[UserCardDirection]:
    return (
        db_session.query(UserCardDirection)
        .filter(UserCardDirection.user_word_id == user_word_id)
        .all()
    )


# ---------------------------------------------------------------------------
# Both directions created
# ---------------------------------------------------------------------------

class TestBothDirectionsCreated:
    def test_new_word_creates_eng_rus_and_rus_eng(self, app, db_session, user):
        """_build_cards_for_words must create eng-rus AND rus-eng for a brand-new word."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            cards = _build_cards_for_words([word], user.id, activate_srs=True)

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        assert uw is not None, "UserWord must have been created"

        dirs = _directions_for_user_word(db_session, uw.id)
        direction_values = {d.direction for d in dirs}

        assert DIRECTION_ENG_RUS in direction_values, "eng-rus direction must be created"
        assert DIRECTION_RUS_ENG in direction_values, "rus-eng direction must be created"
        assert len(dirs) == 2, f"Expected exactly 2 directions, got {len(dirs)}"

    def test_cards_list_contains_both_directions(self, app, db_session, user):
        """The returned cards list must include entries for both directions."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            cards = _build_cards_for_words([word], user.id, activate_srs=True)

        directions_in_cards = {c['direction'] for c in cards}
        assert DIRECTION_ENG_RUS in directions_in_cards
        assert DIRECTION_RUS_ENG in directions_in_cards

    def test_eng_rus_card_has_correct_front_back(self, app, db_session, user):
        """eng-rus card: front=English, back=Russian."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            cards = _build_cards_for_words([word], user.id, activate_srs=True)

        er = next(c for c in cards if c['direction'] == DIRECTION_ENG_RUS)
        assert er['front'] == word.english_word
        assert er['back'] == word.russian_word

    def test_rus_eng_card_has_correct_front_back(self, app, db_session, user):
        """rus-eng card: front=Russian, back=English."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            cards = _build_cards_for_words([word], user.id, activate_srs=True)

        re = next(c for c in cards if c['direction'] == DIRECTION_RUS_ENG)
        assert re['front'] == word.russian_word
        assert re['back'] == word.english_word


# ---------------------------------------------------------------------------
# DEFAULT_EASE_FACTOR and CardState.NEW used explicitly
# ---------------------------------------------------------------------------

class TestCardDefaults:
    def test_created_cards_use_default_ease_factor(self, app, db_session, user):
        """Created UserCardDirection rows must use DEFAULT_EASE_FACTOR, not hardcoded 2.5."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            _build_cards_for_words([word], user.id, activate_srs=True)

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        dirs = _directions_for_user_word(db_session, uw.id)
        for d in dirs:
            assert d.ease_factor == DEFAULT_EASE_FACTOR, (
                f"Direction {d.direction}: ease_factor={d.ease_factor}, "
                f"expected DEFAULT_EASE_FACTOR={DEFAULT_EASE_FACTOR}"
            )

    def test_created_cards_have_new_state(self, app, db_session, user):
        """Created UserCardDirection rows must have state=CardState.NEW."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            _build_cards_for_words([word], user.id, activate_srs=True)

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        dirs = _directions_for_user_word(db_session, uw.id)
        for d in dirs:
            assert d.state == CardState.NEW.value, (
                f"Direction {d.direction}: state={d.state}, expected {CardState.NEW.value}"
            )

    def test_created_cards_source_is_lesson_vocab(self, app, db_session, user):
        """Source column must be set to 'lesson_vocab'."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            _build_cards_for_words([word], user.id, activate_srs=True)

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        dirs = _directions_for_user_word(db_session, uw.id)
        for d in dirs:
            assert d.source == 'lesson_vocab'


# ---------------------------------------------------------------------------
# Idempotency — second invocation does not create duplicates
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_call_does_not_create_duplicates(self, app, db_session, user):
        """Calling _build_cards_for_words twice for the same word must not duplicate directions."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            _build_cards_for_words([word], user.id, activate_srs=True)
            # Second call — same word already has directions
            _build_cards_for_words([word], user.id, activate_srs=True)

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        dirs = _directions_for_user_word(db_session, uw.id)
        assert len(dirs) == 2, (
            f"Expected exactly 2 directions after second call, got {len(dirs)}"
        )

    def test_existing_directions_returned_in_cards(self, app, db_session, user):
        """If directions already exist, _build_cards_for_words returns them without creating new rows."""
        word = _make_word(db_session)

        # Pre-create both directions manually
        uw = UserWord(user_id=user.id, word_id=word.id)
        db_session.add(uw)
        db_session.commit()

        dir_er = UserCardDirection(
            user_word_id=uw.id,
            direction=DIRECTION_ENG_RUS,
            source='lesson_vocab',
            ease_factor=DEFAULT_EASE_FACTOR,
            state=CardState.NEW.value,
        )
        dir_re = UserCardDirection(
            user_word_id=uw.id,
            direction=DIRECTION_RUS_ENG,
            source='lesson_vocab',
            ease_factor=DEFAULT_EASE_FACTOR,
            state=CardState.NEW.value,
        )
        db_session.add(dir_er)
        db_session.add(dir_re)
        db_session.commit()

        with app.test_request_context('/'):
            cards = _build_cards_for_words([word], user.id, activate_srs=True)

        dirs = _directions_for_user_word(db_session, uw.id)
        assert len(dirs) == 2, "No extra directions must be created when they already exist"
        assert len(cards) == 2


# ---------------------------------------------------------------------------
# activate_srs=False path — display-only, no DB rows
# ---------------------------------------------------------------------------

class TestActivateSrsFalse:
    def test_no_rows_created_when_srs_disabled(self, app, db_session, user):
        """activate_srs=False must not create any UserCardDirection rows."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            cards = _build_cards_for_words([word], user.id, activate_srs=False)

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        assert uw is None, "UserWord must not be created when activate_srs=False"
        assert len(cards) == 1, "Should return one display-only card"
        assert cards[0]['direction_id'] is None

    def test_display_card_ease_factor_uses_constant(self, app, db_session, user):
        """Display-only card dict must use DEFAULT_EASE_FACTOR, not a literal 2.5."""
        word = _make_word(db_session)

        with app.test_request_context('/'):
            cards = _build_cards_for_words([word], user.id, activate_srs=False)

        assert cards[0]['ease_factor'] == DEFAULT_EASE_FACTOR
