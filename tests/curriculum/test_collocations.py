"""Tests for WordCollocation model and get_collocations_for_word helper.

Task 29: Word collocations model.
"""
from __future__ import annotations

import uuid

from app.curriculum.models import WordCollocation, get_collocations_for_word
from app.utils.db import db
from app.words.models import CollectionWords


def _make_word(db_session) -> CollectionWords:
    word = CollectionWords(
        english_word=f"testword_{uuid.uuid4().hex[:12]}",
        russian_word="тестовое слово",
        level="B1",
    )
    db_session.add(word)
    db_session.commit()
    return word


class TestWordCollocationModel:
    def test_model_creates_correctly(self, app, db_session):
        word = _make_word(db_session)
        collocation = WordCollocation(
            word_id=word.id,
            collocation_phrase="make a decision",
            translation="принять решение",
            example="She had to make a decision quickly.",
        )
        db_session.add(collocation)
        db_session.commit()

        fetched = db_session.get(WordCollocation, collocation.id)
        assert fetched is not None
        assert fetched.word_id == word.id
        assert fetched.collocation_phrase == "make a decision"
        assert fetched.translation == "принять решение"
        assert fetched.example == "She had to make a decision quickly."

    def test_model_without_example(self, app, db_session):
        word = _make_word(db_session)
        collocation = WordCollocation(
            word_id=word.id,
            collocation_phrase="take action",
            translation="принять меры",
        )
        db_session.add(collocation)
        db_session.commit()

        fetched = db_session.get(WordCollocation, collocation.id)
        assert fetched.example is None

    def test_created_at_set_automatically(self, app, db_session):
        word = _make_word(db_session)
        collocation = WordCollocation(
            word_id=word.id,
            collocation_phrase="set a goal",
            translation="поставить цель",
        )
        db_session.add(collocation)
        db_session.commit()

        fetched = db_session.get(WordCollocation, collocation.id)
        assert fetched.created_at is not None

    def test_repr_contains_key_fields(self, app, db_session):
        word = _make_word(db_session)
        collocation = WordCollocation(
            word_id=word.id,
            collocation_phrase="keep in mind",
            translation="держать в уме",
        )
        db_session.add(collocation)
        db_session.commit()

        r = repr(collocation)
        assert "keep in mind" in r
        assert str(word.id) in r

    def test_get_collocations_returns_empty_for_word_without_collocations(self, app, db_session):
        word = _make_word(db_session)
        result = get_collocations_for_word(word.id, db)
        assert result == []

    def test_get_collocations_returns_all_for_word(self, app, db_session):
        word = _make_word(db_session)
        c1 = WordCollocation(word_id=word.id, collocation_phrase="break a habit", translation="избавиться от привычки")
        c2 = WordCollocation(word_id=word.id, collocation_phrase="form a habit", translation="выработать привычку")
        db_session.add_all([c1, c2])
        db_session.commit()

        result = get_collocations_for_word(word.id, db)
        assert len(result) == 2
        phrases = {c.collocation_phrase for c in result}
        assert "break a habit" in phrases
        assert "form a habit" in phrases

    def test_get_collocations_does_not_return_other_words_collocations(self, app, db_session):
        word1 = _make_word(db_session)
        word2 = _make_word(db_session)
        db_session.add(WordCollocation(word_id=word1.id, collocation_phrase="word1 phrase", translation="фраза 1"))
        db_session.add(WordCollocation(word_id=word2.id, collocation_phrase="word2 phrase", translation="фраза 2"))
        db_session.commit()

        result = get_collocations_for_word(word1.id, db)
        assert len(result) == 1
        assert result[0].collocation_phrase == "word1 phrase"

    def test_multiple_collocations_per_word_allowed(self, app, db_session):
        word = _make_word(db_session)
        for i in range(5):
            db_session.add(WordCollocation(
                word_id=word.id,
                collocation_phrase=f"phrase {i}",
                translation=f"перевод {i}",
            ))
        db_session.commit()

        result = get_collocations_for_word(word.id, db)
        assert len(result) == 5
