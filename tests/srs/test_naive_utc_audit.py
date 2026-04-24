"""Task 8: sanity checks that SRS-related datetime comparisons use naive UTC
and do not raise TypeError against naive Column(DateTime) fields."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.models import User
from app.daily_plan.linear.slots.srs_slot import (
    _today_start,
    count_srs_due_cards,
    get_linear_plan_due_mix_cards,
)
from app.daily_plan.next_step import _check_srs_due
from app.srs.constants import CardState
from app.study.models import UserCardDirection, UserWord
from app.study.services.srs_service import SRSService
from app.utils.db import db as real_db
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    u = User(username=f'naive_{suffix}', email=f'naive_{suffix}@example.com', active=True)
    u.set_password('secret123')
    db_session.add(u)
    db_session.commit()
    return u


def _seed_due_card(db_session, user: User) -> UserCardDirection:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'w_{suffix}',
        russian_word=f'с_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()

    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = 'learning'
    db_session.add(uw)
    db_session.commit()

    now = _now_naive()
    direction = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    direction.state = CardState.REVIEW.value
    direction.next_review = now - timedelta(minutes=5)
    direction.last_reviewed = now - timedelta(days=1)
    direction.first_reviewed = now - timedelta(days=5)
    db_session.add(direction)
    db_session.commit()
    return direction


def test_today_start_is_naive():
    start = _today_start()
    assert start.tzinfo is None


def test_count_srs_due_cards_handles_naive_column(db_session):
    user = _user(db_session)
    _seed_due_card(db_session, user)
    # Must not raise TypeError (naive vs aware)
    count = count_srs_due_cards(user.id, real_db)
    assert count >= 1


def test_get_linear_plan_due_mix_cards_uses_naive_now(db_session):
    user = _user(db_session)
    _seed_due_card(db_session, user)
    # Must not raise (the internal `now` must be naive)
    cards = get_linear_plan_due_mix_cards(user.id, real_db, limit=5)
    assert isinstance(cards, list)


def test_check_srs_due_naive(db_session):
    user = _user(db_session)
    _seed_due_card(db_session, user)
    # Must not raise
    step = _check_srs_due(user.id, real_db)
    assert step is not None
    assert step.kind == 'srs'


def test_srs_service_get_adaptive_limits_naive(db_session):
    user = _user(db_session)
    _seed_due_card(db_session, user)
    # get_adaptive_limits does backlog count via next_review < now
    adaptive_new, adaptive_reviews = SRSService.get_adaptive_limits(user.id)
    assert adaptive_new >= 0
    assert adaptive_reviews >= 0


def test_srs_service_check_daily_limits_naive(db_session):
    user = _user(db_session)
    _seed_due_card(db_session, user)
    new_today, reviews_today, new_limit, review_limit = SRSService.check_daily_limits(user.id)
    assert new_today >= 0
    assert reviews_today >= 0
    assert new_limit >= 0
    assert review_limit >= 0
