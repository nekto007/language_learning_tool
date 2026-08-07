"""Tests for app/srs/visibility.py — the single "may this card be served?" rule.

The parity tests are the point of this file: the SQL filter and its Python
twin must agree on the same rows, otherwise the surfaces that can only use one
of them drift apart again.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.models import User
from app.srs.constants import CardState
from app.srs.visibility import (
    is_card_resting,
    is_card_servable,
    is_word_in_srs,
    naive_utc_now,
    not_buried_filter,
    srs_scope_filter,
    srs_servable_filter,
)
from app.study.models import UserCardDirection, UserWord
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'srsvis_{suffix}',
        email=f'srsvis_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_card(
    db_session,
    user: User,
    *,
    excluded: bool = False,
    buried_until: datetime | None = None,
) -> UserCardDirection:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'word_{suffix}',
        russian_word=f'слово_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()

    user_word = UserWord(user_id=user.id, word_id=word.id)
    user_word.srs_excluded = excluded
    db_session.add(user_word)
    db_session.commit()

    card = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
    card.state = CardState.REVIEW.value
    card.next_review = _now_naive() - timedelta(hours=1)
    card.buried_until = buried_until
    db_session.add(card)
    db_session.commit()
    return card


def _servable_ids(db_session, user: User) -> set[int]:
    rows = (
        db_session.query(UserCardDirection.id)
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(srs_servable_filter(user.id))
        .all()
    )
    return {row[0] for row in rows}


def _in_scope_ids(db_session, user: User) -> set[int]:
    rows = (
        db_session.query(UserCardDirection.id)
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(srs_scope_filter(user.id))
        .all()
    )
    return {row[0] for row in rows}


class TestNaiveUtcNow:
    def test_returns_naive(self):
        assert naive_utc_now().tzinfo is None

    def test_normalises_aware_input(self):
        aware = datetime.now(timezone.utc)
        assert naive_utc_now(aware).tzinfo is None

    def test_passes_naive_input_through(self):
        naive = _now_naive()
        assert naive_utc_now(naive) == naive


class TestServableFilter:
    def test_plain_card_is_servable(self, db_session):
        user = _make_user(db_session)
        card = _make_card(db_session, user)

        assert card.id in _servable_ids(db_session, user)

    def test_excluded_word_is_not_servable(self, db_session):
        user = _make_user(db_session)
        card = _make_card(db_session, user, excluded=True)

        assert card.id not in _servable_ids(db_session, user)

    def test_resting_card_is_not_servable(self, db_session):
        user = _make_user(db_session)
        card = _make_card(db_session, user, buried_until=_now_naive() + timedelta(days=3))

        assert card.id not in _servable_ids(db_session, user)

    def test_expired_rest_is_servable_again(self, db_session):
        user = _make_user(db_session)
        card = _make_card(db_session, user, buried_until=_now_naive() - timedelta(minutes=1))

        assert card.id in _servable_ids(db_session, user)

    def test_other_users_card_is_not_servable(self, db_session):
        owner = _make_user(db_session)
        stranger = _make_user(db_session)
        card = _make_card(db_session, owner)

        assert card.id not in _servable_ids(db_session, stranger)


class TestScopeFilterKeepsRestingCards:
    """Surfaces that exist to show resting cards take the scope half alone."""

    def test_resting_card_stays_in_scope(self, db_session):
        user = _make_user(db_session)
        card = _make_card(db_session, user, buried_until=_now_naive() + timedelta(days=3))

        assert card.id in _in_scope_ids(db_session, user)

    def test_excluded_word_leaves_scope(self, db_session):
        user = _make_user(db_session)
        card = _make_card(db_session, user, excluded=True)

        assert card.id not in _in_scope_ids(db_session, user)


class TestPythonTwinParity:
    """is_card_servable must classify the same rows as the SQL filter."""

    def test_parity_across_all_combinations(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        cards = [
            _make_card(db_session, user),
            _make_card(db_session, user, excluded=True),
            _make_card(db_session, user, buried_until=now + timedelta(days=3)),
            _make_card(db_session, user, buried_until=now - timedelta(minutes=1)),
            _make_card(db_session, user, excluded=True, buried_until=now + timedelta(days=3)),
        ]

        from_sql = _servable_ids(db_session, user)
        from_python = {c.id for c in cards if is_card_servable(c)}

        assert from_python == from_sql

    def test_handles_aware_buried_until(self, db_session):
        user = _make_user(db_session)
        card = _make_card(db_session, user)
        card.buried_until = datetime.now(timezone.utc) + timedelta(days=2)

        assert is_card_resting(card) is True
        assert is_card_servable(card) is False

    def test_none_inputs_are_safe(self):
        assert is_card_servable(None) is False
        assert is_word_in_srs(None) is False


class TestNotBuriedFilterStandalone:
    def test_selects_only_unrested_rows(self, db_session):
        user = _make_user(db_session)
        free = _make_card(db_session, user)
        resting = _make_card(db_session, user, buried_until=_now_naive() + timedelta(days=5))

        rows = (
            db_session.query(UserCardDirection.id)
            .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
            .filter(UserWord.user_id == user.id, not_buried_filter())
            .all()
        )
        ids = {row[0] for row in rows}

        assert free.id in ids
        assert resting.id not in ids
