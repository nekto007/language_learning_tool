"""Regression test for SEC-003 (cross-zone audit 2026-08-08).

``_flashcard_session.html`` built ``url_for('study.deck_detail', …)`` — an
endpoint that does not exist. The branch is only reached when a deck has words
but nothing is due today, so the page 500'd exactly when it should have praised
the user for finishing the deck.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.study.models import QuizDeck, QuizDeckWord, UserCardDirection, UserWord
from app.words.models import CollectionWords


@pytest.fixture
def exhausted_deck(db_session, test_user):
    """A deck whose only word is already scheduled far into the future."""
    word = CollectionWords(english_word='serendipity', russian_word='случайность', level='A1')
    db_session.add(word)
    db_session.flush()

    deck = QuizDeck(title='Exhausted Deck', user_id=test_user.id, is_public=False)
    db_session.add(deck)
    db_session.flush()
    db_session.add(QuizDeckWord(deck_id=deck.id, word_id=word.id, order_index=0))

    user_word = UserWord(user_id=test_user.id, word_id=word.id)
    user_word.status = 'learning'
    db_session.add(user_word)
    db_session.flush()

    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    for direction in ('eng-rus', 'rus-eng'):
        row = UserCardDirection(user_word_id=user_word.id, direction=direction)
        row.state = 'review'
        row.next_review = future
        row.first_reviewed = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        row.repetitions = 3
        db_session.add(row)
    db_session.flush()
    return deck


class TestNothingToStudyScreenRenders:
    def test_empty_deck_screen_is_200_not_500(self, authenticated_client, exhausted_deck):
        response = authenticated_client.get(f'/study/cards/deck/{exhausted_deck.id}')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Сейчас нечего учить!' in html or 'Дневной лимит достигнут!' in html

    def test_add_words_button_points_at_a_real_endpoint(
        self, authenticated_client, exhausted_deck,
    ):
        response = authenticated_client.get(f'/study/cards/deck/{exhausted_deck.id}')

        assert response.status_code == 200
        assert f'/study/my-decks/{exhausted_deck.id}/edit' in response.get_data(as_text=True)


class TestTemplateBuildsWithDeckId:
    """Direct render — the 500 came from Jinja's BuildError, not from the route."""

    def test_flashcard_session_renders_with_deck_id(self, app):
        from flask import render_template_string

        with app.test_request_context('/study/cards'):
            html = render_template_string(
                "{% include 'components/_flashcard_session.html' %}",
                fc_nothing_to_study=True,
                fc_deck_id=42,
                fc_back_url='/study',
                fc_cards=[],
                fc_title='Deck',
                fc_session_id=1,
            )

        assert '/study/my-decks/42/edit' in html
