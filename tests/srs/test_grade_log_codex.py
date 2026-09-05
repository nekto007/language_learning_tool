"""Adversarial transaction and sampling checks for the SRS grade log."""

from datetime import datetime

import pytest
from sqlalchemy import event

from app.srs.grade_log import recent_mature_accuracy
from app.srs.service import UnifiedSRSService
from app.study.models import CardGradeEvent
from app.study.services.srs_service import SRSService
from tests.srs.test_grade_log import _card, _events


def test_threshold_and_timestamp_tie_use_latest_ids(app, db_session, test_user):
    card = _card(db_session, test_user, state='review', correct=3, incorrect=7)
    stamp = datetime(2026, 9, 6)

    def append(rating, state='review'):
        db_session.add(CardGradeEvent(
            user_id=test_user.id, direction_id=card.id, rating=rating,
            state_before=state, state_after='review', graded_at=stamp,
        ))
        db_session.flush()

    for _ in range(9):
        append(3)
    assert recent_mature_accuracy(test_user.id, 10) is None
    assert SRSService._accuracy_on_recent_reviews(test_user.id, 20) == pytest.approx(30)
    append(1)
    assert recent_mature_accuracy(test_user.id, 10) == pytest.approx(90)
    assert SRSService._accuracy_on_recent_reviews(test_user.id, 20) == pytest.approx(90)
    for _ in range(10):
        append(1)
    # Same timestamp for every row: descending id must choose the latest ten.
    # Newer learning/relearning successes must not displace mature misses.
    for _ in range(12):
        append(3, 'relearning')
        append(3, 'learning')
    assert recent_mature_accuracy(test_user.id, 10) == 0


@pytest.mark.parametrize('surface', ['model', 'service'])
def test_outer_rollback_undoes_grade_and_event(app, db_session, test_user, surface):
    card = _card(db_session, test_user, state='review', interval=10)
    original = (card.state, card.interval, card.correct_count, card.incorrect_count)
    if surface == 'model':
        card.update_after_review(1, context='lesson')
    else:
        assert UnifiedSRSService().grade_card(card.id, 1, test_user.id)['success']
    assert len(_events(db_session, test_user.id)) == 1
    db_session.rollback()
    db_session.refresh(card)
    assert (card.state, card.interval, card.correct_count, card.incorrect_count) == original
    assert _events(db_session, test_user.id) == []


@pytest.mark.parametrize('surface', ['model', 'service'])
def test_event_insert_failure_cannot_leave_a_committed_grade(app, db_session, test_user, surface):
    card = _card(db_session, test_user, state='review', interval=10)
    original = (card.state, card.interval, card.lapses, card.incorrect_count)

    def reject_insert(mapper, connection, target):
        raise RuntimeError('injected grade-log INSERT failure')

    event.listen(CardGradeEvent, 'before_insert', reject_insert)
    try:
        if surface == 'model':
            with pytest.raises(RuntimeError, match='injected grade-log'):
                card.update_after_review(1)
        else:
            result = UnifiedSRSService().grade_card(card.id, 1, test_user.id)
            assert result['success'] is False
    finally:
        event.remove(CardGradeEvent, 'before_insert', reject_insert)
        db_session.rollback()
    db_session.refresh(card)
    assert (card.state, card.interval, card.lapses, card.incorrect_count) == original
    assert _events(db_session, test_user.id) == []
