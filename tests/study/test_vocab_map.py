"""Tests for vocabulary mastery map page (Task 38).

Route: GET /study/vocab-map
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.study.models import UserCardDirection, UserWord
from app.words.models import Collection, CollectionWordLink, CollectionWords
from app.utils.db import db
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_level(db_session, order: int = 1) -> CEFRLevel:
    level = CEFRLevel(
        code=unique_level_code(),
        name='Test Level',
        description='d',
        order=order,
    )
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int = 1) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'Module {number}',
        description='d',
        raw_content={'module': {'id': number}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_word(db_session, english: str) -> CollectionWords:
    word = CollectionWords(english_word=english)
    db_session.add(word)
    db_session.commit()
    return word


def _make_collection_with_words(db_session, *words: CollectionWords) -> Collection:
    coll = Collection(name=f'coll_{uuid.uuid4().hex[:8]}', description='d')
    db_session.add(coll)
    db_session.commit()
    for word in words:
        link = CollectionWordLink(collection_id=coll.id, word_id=word.id)
        db_session.add(link)
    db_session.commit()
    return coll


def _make_vocab_lesson(db_session, module: Module, collection: Collection) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Vocabulary Lesson',
        type='vocabulary',
        content={'words': []},
        collection_id=collection.id,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_user_word(db_session, user_id: int, word: CollectionWords, status: str = 'new') -> UserWord:
    uw = UserWord(user_id=user_id, word_id=word.id)
    uw.status = status
    db_session.add(uw)
    db_session.commit()
    return uw


def _make_mastered_card(db_session, user_word: UserWord, interval: int = 200) -> UserCardDirection:
    """Create a card direction that meets the mastered threshold."""
    card = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
    card.state = 'review'
    card.interval = interval
    card.ease_factor = 2.5
    card.repetitions = 10
    db_session.add(card)
    db_session.commit()
    return card


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVocabMapRoute:
    def test_returns_200(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        assert resp.status_code == 200

    def test_empty_user_shows_all_gray_modules(self, app, db_session, test_user, client):
        """Modules with no user activity should show gray (not-started) state."""
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level)
        word = _make_word(db_session, f'gray_word_{uuid.uuid4().hex[:6]}')
        coll = _make_collection_with_words(db_session, word)
        _make_vocab_lesson(db_session, module, coll)

        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert 'vocab-map__module--gray' in html
        assert module.title in html

    def test_module_counts_total_words(self, app, db_session, test_user, client):
        """Module with 3 vocab words should show 3 total."""
        level = _make_level(db_session, order=2)
        module = _make_module(db_session, level)
        words = [
            _make_word(db_session, f'count_word_{uuid.uuid4().hex[:6]}')
            for _ in range(3)
        ]
        coll = _make_collection_with_words(db_session, *words)
        _make_vocab_lesson(db_session, module, coll)

        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert '3 сл.' in html

    def test_mastered_words_shown_as_green(self, app, db_session, test_user, client):
        """Module where >80% of words are mastered should show green class."""
        level = _make_level(db_session, order=3)
        module = _make_module(db_session, level)

        # 4 words, 4 mastered → 100% mastery → green
        words = [
            _make_word(db_session, f'green_word_{uuid.uuid4().hex[:6]}')
            for _ in range(4)
        ]
        coll = _make_collection_with_words(db_session, *words)
        _make_vocab_lesson(db_session, module, coll)

        for word in words:
            uw = _make_user_word(db_session, test_user.id, word, status='review')
            _make_mastered_card(db_session, uw, interval=200)

        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        html = resp.get_data(as_text=True)

        assert 'vocab-map__module--green' in html

    def test_partial_mastery_shown_as_yellow(self, app, db_session, test_user, client):
        """Module where 50-79% of words are mastered should show yellow class."""
        level = _make_level(db_session, order=4)
        module = _make_module(db_session, level)

        # 4 words, 2 mastered → 50% → yellow
        words = [
            _make_word(db_session, f'yellow_word_{uuid.uuid4().hex[:6]}')
            for _ in range(4)
        ]
        coll = _make_collection_with_words(db_session, *words)
        _make_vocab_lesson(db_session, module, coll)

        # Mastered: 2 words
        for word in words[:2]:
            uw = _make_user_word(db_session, test_user.id, word, status='review')
            _make_mastered_card(db_session, uw, interval=200)
        # In-learning: 2 words
        for word in words[2:]:
            _make_user_word(db_session, test_user.id, word, status='learning')

        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        html = resp.get_data(as_text=True)

        assert 'vocab-map__module--yellow' in html

    def test_low_mastery_shown_as_red(self, app, db_session, test_user, client):
        """Module where <50% mastered and user has started → red."""
        level = _make_level(db_session, order=5)
        module = _make_module(db_session, level)

        # 4 words, 1 mastered → 25% → red
        words = [
            _make_word(db_session, f'red_word_{uuid.uuid4().hex[:6]}')
            for _ in range(4)
        ]
        coll = _make_collection_with_words(db_session, *words)
        _make_vocab_lesson(db_session, module, coll)

        uw = _make_user_word(db_session, test_user.id, words[0], status='review')
        _make_mastered_card(db_session, uw, interval=200)
        for word in words[1:]:
            _make_user_word(db_session, test_user.id, word, status='learning')

        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        html = resp.get_data(as_text=True)

        assert 'vocab-map__module--red' in html

    def test_module_without_vocab_lessons_excluded(self, app, db_session, test_user, client):
        """Modules with no vocabulary lesson type should not appear in the map."""
        level = _make_level(db_session, order=6)
        module = _make_module(db_session, level)
        # Only a grammar lesson, no vocabulary
        lesson = Lessons(
            module_id=module.id,
            number=1,
            title='Grammar Only Module',
            type='grammar',
            content={},
        )
        db_session.add(lesson)
        db_session.commit()

        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        html = resp.get_data(as_text=True)

        assert 'Grammar Only Module' not in html

    def test_requires_login(self, app, client):
        resp = client.get('/study/vocab-map')
        assert resp.status_code in (302, 401)

    def test_frequency_enriched_words_counted_correctly(self, app, db_session, test_user, client):
        """Frequency-band metadata on words does not break mastery aggregation in the map."""
        level = _make_level(db_session, order=7)
        module = _make_module(db_session, level)

        words = [
            _make_word(db_session, f'freq_map_word_{uuid.uuid4().hex[:6]}')
            for _ in range(2)
        ]
        # Set frequency_band on both words
        for word in words:
            word.frequency_band = 1
        db_session.commit()

        coll = _make_collection_with_words(db_session, *words)
        _make_vocab_lesson(db_session, module, coll)

        # Mastered 1 of 2 words → partial mastery (50%)
        uw = _make_user_word(db_session, test_user.id, words[0], status='review')
        _make_mastered_card(db_session, uw, interval=200)
        _make_user_word(db_session, test_user.id, words[1], status='learning')

        _login(client, test_user)
        resp = client.get('/study/vocab-map')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        # Module with 2 words should appear in map
        assert '2 сл.' in html
        # 1 of 2 mastered = 50% → yellow
        assert 'vocab-map__module--yellow' in html
