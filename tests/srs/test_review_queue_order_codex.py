"""Adversarial boundaries and eligibility for the old-review quota."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from flask import url_for
from sqlalchemy.exc import IntegrityError

from app.daily_plan.items.srs import build_srs_item
from app.srs.counting import count_old_review_debt, old_debt_cutoff
from app.study.models import QuizDeck, QuizDeckWord
from app.utils.db import db
from tests.srs.test_review_queue_order import _login, _now, _plan_queue_url, _review_card, _settings


def _ids(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return [item['id'] for item in response.get_json()['items']]


@pytest.mark.parametrize('cap, expected', [(1, ['old']), (2, ['boundary', 'old'])])
def test_exact_cutoff_and_small_batch(app, db_session, test_user, client, cap, expected):
    _settings(db_session, test_user, reviews=cap)
    now = _now()
    cutoff = old_debt_cutoff(now)
    boundary = _review_card(db_session, test_user, overdue_days=30)
    old = _review_card(db_session, test_user, overdue_days=31)
    boundary.next_review = cutoff
    old.next_review = cutoff - timedelta(microseconds=1)
    db_session.commit()
    assert count_old_review_debt(test_user.id, now_utc=now) == 1
    _login(client, test_user)
    with patch('app.study.api_routes.old_debt_cutoff', return_value=cutoff):
        served = _ids(client, _plan_queue_url(app))
    mapping = {'old': old.id, 'boundary': boundary.id}
    assert served == [mapping[name] for name in expected]


def test_excluding_old_cards_releases_their_quota(app, db_session, test_user, client):
    _settings(db_session, test_user, reviews=3)
    fresh = [_review_card(db_session, test_user, overdue_days=d) for d in (1, 2, 3)]
    old = _review_card(db_session, test_user, overdue_days=90)
    _login(client, test_user)
    url = _plan_queue_url(app) + f'&exclude_card_ids={old.id}'
    assert _ids(client, url) == [card.id for card in fresh]


def test_recovery_priority_stays_inside_each_quota(app, db_session, test_user, client):
    _settings(db_session, test_user, reviews=3)
    fresh = _review_card(db_session, test_user, overdue_days=1)
    recovering_fresh = _review_card(db_session, test_user, overdue_days=20)
    _review_card(db_session, test_user, overdue_days=100)
    recovering_old = _review_card(db_session, test_user, overdue_days=40)
    recovering_fresh.recovery_required = recovering_old.recovery_required = True
    db_session.commit()
    _login(client, test_user)
    assert _ids(client, _plan_queue_url(app)) == [recovering_fresh.id, fresh.id, recovering_old.id]
    with app.test_request_context():
        item = build_srs_item(test_user.id, db, section='required')
    assert (item.data['review_fresh_show'], item.data['review_old_show']) == (2, 1)


def test_current_schema_rejects_legacy_null_state(app, db_session, test_user):
    legacy = _review_card(db_session, test_user, overdue_days=90)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            legacy.state = None
            db_session.flush()


def test_free_study_today_window_and_deck_order(app, db_session, test_user, client):
    from app.utils.time_utils import day_to_naive_utc

    _settings(db_session, test_user, reviews=2)
    future = _review_card(db_session, test_user, overdue_days=1)
    old = _review_card(db_session, test_user, overdue_days=90)
    future.next_review = day_to_naive_utc(test_user.id, db, days_ahead=1) - timedelta(microseconds=1)
    deck = QuizDeck(user_id=test_user.id, title='Quota exception', reviews_per_day=2, new_words_per_day=0)
    db_session.add(deck)
    db_session.flush()
    for card in (future, old):
        db_session.add(QuizDeckWord(deck_id=deck.id, word_id=card.user_word.word_id,
                                   user_word_id=card.user_word_id))
    db_session.commit()
    _login(client, test_user)
    with app.test_request_context():
        free_url = url_for('study.get_study_items')
        deck_url = url_for('study.get_study_items', deck_id=deck.id)
    assert _ids(client, free_url) == [future.id, old.id]
    assert _ids(client, deck_url) == [old.id, future.id]
    assert _ids(client, _plan_queue_url(app)) == [old.id]
