"""Queue eligibility must match the pool used to reserve mature reviews."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from flask import url_for

from app.srs.counting import split_due_budget
from app.study.models import QuizDeck, QuizDeckWord, StudySettings
from tests.srs.test_review_budget_policy import _card, _login, _now


def _setup(db_session, user, client):
    db_session.add(StudySettings(user_id=user.id, new_words_per_day=0, reviews_per_day=20))
    db_session.commit()
    _login(client, user)


def _queue(app, client, **params):
    with app.test_request_context():
        url = url_for('study.get_study_items', **params)
    response = client.get(url)
    assert response.status_code == 200
    return response.get_json()['items']


@pytest.mark.parametrize('state', ['learning', 'relearning'])
def test_free_study_keeps_fifteen_minute_grace(app, db_session, test_user, client, state):
    _setup(db_session, test_user, client)
    card = _card(db_session, test_user, state=state)
    card.next_review = _now() + timedelta(minutes=10)
    db_session.commit()
    assert [item['id'] for item in _queue(app, client)] == [card.id]


def test_excluded_reviews_do_not_consume_learning_reserve(app, db_session, test_user, client):
    _setup(db_session, test_user, client)
    learning = [_card(db_session, test_user, state='learning') for _ in range(20)]
    reviews = [_card(db_session, test_user, state='review') for _ in range(20)]
    items = _queue(app, client, source='linear_plan', **{
        'from': 'linear_plan', 'slot': 'srs',
        'exclude_card_ids': ','.join(str(card.id) for card in reviews),
    })
    assert {item['id'] for item in items} == {card.id for card in learning}


def test_free_study_reserves_for_reviews_due_later_today(app, db_session, test_user, client):
    from app.utils.db import db
    from app.utils.time_utils import day_to_naive_utc

    _setup(db_session, test_user, client)
    for _ in range(20):
        _card(db_session, test_user, state='learning')
    tomorrow = day_to_naive_utc(test_user.id, db, days_ahead=1)
    for _ in range(20):
        card = _card(db_session, test_user, state='review')
        card.next_review = tomorrow - timedelta(microseconds=1)
    db_session.commit()
    states = [item['state'] for item in _queue(app, client)]
    assert (states.count('learning'), states.count('review')) == (10, 10)


def test_relearning_and_learning_share_one_cap(app, db_session, test_user, client):
    _setup(db_session, test_user, client)
    for state, count in [('relearning', 6), ('learning', 12), ('review', 20)]:
        for _ in range(count):
            _card(db_session, test_user, state=state)
    states = [item['state'] for item in _queue(
        app, client, source='linear_plan', **{'from': 'linear_plan', 'slot': 'srs'},
    )]
    assert [states.count(state) for state in ['relearning', 'learning', 'review']] == [6, 4, 10]


@pytest.mark.parametrize('due_budget, spent, expected', [(20, 0, (0, 5)), (20, 5, (0, 0)), (0, 0, (0, 0))])
def test_floor_respects_spent_reviews_and_combined_cap(app, test_user, due_budget, spent, expected):
    with patch('app.srs.counting.count_reviews_today', return_value=spent):
        assert split_due_budget(
            test_user.id, learning_due=0, review_due=20,
            due_budget=due_budget, remaining_reviews=0,
        ) == expected


@pytest.mark.parametrize('limit', [0, 3])
def test_deck_uses_own_cap_and_keeps_learning_priority(app, db_session, test_user, client, limit):
    _setup(db_session, test_user, client)
    deck = QuizDeck(user_id=test_user.id, title='Adversarial deck',
                    new_words_per_day=0, reviews_per_day=limit)
    db_session.add(deck)
    db_session.commit()
    for state in ['learning', 'review']:
        for _ in range(4):
            card = _card(db_session, test_user, state=state)
            db_session.add(QuizDeckWord(deck_id=deck.id, word_id=card.user_word.word_id,
                                       user_word_id=card.user_word_id))
    db_session.commit()
    states = [item['state'] for item in _queue(app, client, deck_id=deck.id)]
    assert states == ['learning'] * limit
