"""Nested transaction, ordering and token-log regression checks."""

import logging
from unittest.mock import patch

from sqlalchemy import text

from app.srs.counting import interleave_old_debt
from app.study.services.srs_service import SRSService
from tests.srs.test_grade_log import _card, _events


def test_tier_sql_failure_inside_outer_savepoint_preserves_grade(app, db_session, test_user):
    card = _card(db_session, test_user, state='review')
    original = (card.state, card.interval, card.incorrect_count)

    def fail_tier(*args):
        db_session.execute(text('SELECT 1 / 0'))

    outer = db_session.begin_nested()
    with patch.object(SRSService, 'record_tier_state', side_effect=fail_tier):
        card.update_after_review(1, context='lesson')
    assert db_session.execute(text('SELECT 42')).scalar() == 42
    assert card.state == 'relearning'
    assert len(_events(db_session, test_user.id)) == 1
    outer.rollback()
    db_session.refresh(card)
    assert (card.state, card.interval, card.incorrect_count) == original
    assert _events(db_session, test_user.id) == []


def test_interleave_preserves_each_recovery_order_and_inputs():
    for fresh_count in range(21):
        for old_count in range(21):
            fresh = [('fresh', i) for i in range(fresh_count)]
            old = [('old', i) for i in range(old_count)]
            result = interleave_old_debt(fresh, old)
            assert len(result) == fresh_count + old_count
            assert [item for item in result if item[0] == 'fresh'] == fresh
            assert [item for item in result if item[0] == 'old'] == old
            assert fresh == [('fresh', i) for i in range(fresh_count)]
            assert old == [('old', i) for i in range(old_count)]
            if fresh:
                assert result[0] == fresh[0]


def test_bad_bearer_log_omits_token_and_query_string(client, caplog):
    token = 'secret-bearer-value.not-a-jwt.signature'
    with caplog.at_level(logging.INFO, logger='app.api.decorators'):
        response = client.get('/api/daily-status?secret=query-private-value', headers={
            'Authorization': 'Bearer ' + token, 'User-Agent': 'codex-audit',
        })
    assert response.status_code == 401
    records = [record for record in caplog.records if record.name == 'app.api.decorators']
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.INFO and record.exc_info is None
    assert token not in record.getMessage()
    assert 'query-private-value' not in record.getMessage()
