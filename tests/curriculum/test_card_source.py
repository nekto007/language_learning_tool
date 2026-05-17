"""Tests for UserCardDirection.source tracking.

Task 72: Vocabulary source tracking — verifies that cards get the correct
source value and that the source is exposed in the API and template.
"""
from __future__ import annotations

import uuid

import pytest

from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique() -> str:
    return uuid.uuid4().hex[:12]


def _make_word(db_session) -> CollectionWords:
    word = CollectionWords(
        english_word=f"src_word_{_unique()}",
        russian_word="тестовое",
        level="B1",
    )
    db_session.add(word)
    db_session.flush()
    return word


def _make_user_word(db_session, test_user, word) -> UserWord:
    uw = UserWord(user_id=test_user.id, word_id=word.id)
    db_session.add(uw)
    db_session.flush()
    return uw


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestUserCardDirectionSourceField:
    def test_source_none_by_default(self, app, db_session, test_user):
        word = _make_word(db_session)
        uw = _make_user_word(db_session, test_user, word)
        card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
        db_session.add(card)
        db_session.commit()

        fetched = db_session.get(UserCardDirection, card.id)
        assert fetched.source is None

    def test_source_lesson_vocab_persists(self, app, db_session, test_user):
        word = _make_word(db_session)
        uw = _make_user_word(db_session, test_user, word)
        card = UserCardDirection(user_word_id=uw.id, direction='eng-rus', source='lesson_vocab')
        db_session.add(card)
        db_session.commit()

        fetched = db_session.get(UserCardDirection, card.id)
        assert fetched.source == 'lesson_vocab'

    def test_source_book_reading_persists(self, app, db_session, test_user):
        word = _make_word(db_session)
        uw = _make_user_word(db_session, test_user, word)
        card = UserCardDirection(user_word_id=uw.id, direction='rus-eng', source='book_reading')
        db_session.add(card)
        db_session.commit()

        fetched = db_session.get(UserCardDirection, card.id)
        assert fetched.source == 'book_reading'

    def test_source_custom_list_persists(self, app, db_session, test_user):
        word = _make_word(db_session)
        uw = _make_user_word(db_session, test_user, word)
        card = UserCardDirection(user_word_id=uw.id, direction='eng-rus', source='custom_list')
        db_session.add(card)
        db_session.commit()

        fetched = db_session.get(UserCardDirection, card.id)
        assert fetched.source == 'custom_list'

    def test_multiple_attempts_per_word_allowed(self, app, db_session, test_user):
        word = _make_word(db_session)
        uw = _make_user_word(db_session, test_user, word)
        card_en = UserCardDirection(user_word_id=uw.id, direction='eng-rus', source='lesson_vocab')
        card_ru = UserCardDirection(user_word_id=uw.id, direction='rus-eng', source='book_reading')
        db_session.add(card_en)
        db_session.add(card_ru)
        db_session.commit()

        # Different sources for different directions on the same word
        fetched_en = UserCardDirection.query.filter_by(user_word_id=uw.id, direction='eng-rus').first()
        fetched_ru = UserCardDirection.query.filter_by(user_word_id=uw.id, direction='rus-eng').first()
        assert fetched_en.source == 'lesson_vocab'
        assert fetched_ru.source == 'book_reading'

    def test_source_field_accepts_valid_sources(self, app, db_session, test_user):
        valid_sources = ['lesson_vocab', 'book_reading', 'custom_list', 'manual', None]
        for i, src in enumerate(valid_sources):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, test_user, word)
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus', source=src)
            db_session.add(card)
            db_session.flush()
            assert card.source == src


# ---------------------------------------------------------------------------
# Migration / schema test
# ---------------------------------------------------------------------------

class TestMigrationRunsCleanly:
    def test_source_column_exists_in_db(self, app, db_session, test_user):
        """Verify that the source column exists and is nullable."""
        from sqlalchemy import text
        result = db_session.execute(
            text("SELECT column_name, is_nullable FROM information_schema.columns "
                 "WHERE table_name='user_card_directions' AND column_name='source'")
        ).fetchone()
        assert result is not None, "source column missing from user_card_directions"
        assert result[1] == 'YES', "source column should be nullable"


# ---------------------------------------------------------------------------
# Template test
# ---------------------------------------------------------------------------

class TestSourceBadgeInTemplate:
    def test_source_badge_element_in_flashcard_template(self):
        from pathlib import Path
        tpl = (
            Path(__file__).parent.parent.parent
            / "app" / "templates" / "components" / "_flashcard_session.html"
        ).read_text(encoding="utf-8")

        assert "card-source-badge" in tpl

    def test_source_badge_css_classes_defined(self):
        from pathlib import Path
        css = (
            Path(__file__).parent.parent.parent
            / "app" / "static" / "css" / "design-system.css"
        ).read_text(encoding="utf-8")

        assert ".card-source-badge" in css
        assert ".card-source-badge--lesson-vocab" in css
        assert ".card-source-badge--book-reading" in css
        assert ".card-source-badge--custom-list" in css
