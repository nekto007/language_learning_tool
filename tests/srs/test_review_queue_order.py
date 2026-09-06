"""Lesson audit item 13: composition of the daily review batch.

Fresh overdue cards (≤ 30 days) come first, closest to their date first; old
debt (> 30 days) keeps a third of the batch, oldest first, and fills whatever
fresh cards leave empty. Dates are never rewritten.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from flask import url_for

from app.srs.constants import CardState
from app.srs.counting import (
    OLD_DEBT_DAYS,
    OLD_DEBT_QUOTA_SHARE,
    count_old_review_debt,
    old_debt_cutoff,
    old_debt_quota,
)
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.words.models import CollectionWords


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _review_card(db_session, user, *, overdue_days: float) -> UserCardDirection:
    word = CollectionWords(english_word=f'rq_{uuid.uuid4().hex[:10]}', russian_word='перевод')
    db_session.add(word)
    db_session.commit()
    uw = UserWord(user_id=user.id, word_id=word.id)
    db_session.add(uw)
    db_session.commit()
    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = CardState.REVIEW.value
    card.interval = 10
    card.repetitions = 3
    card.ease_factor = 2.5
    card.first_reviewed = _now() - timedelta(days=200)
    card.last_reviewed = _now() - timedelta(days=overdue_days + 10)
    card.next_review = _now() - timedelta(days=overdue_days)
    db_session.add(card)
    db_session.commit()
    return card


def _settings(db_session, user, reviews: int = 20) -> None:
    db_session.add(StudySettings(user_id=user.id, new_words_per_day=0, reviews_per_day=reviews))
    db_session.commit()


def _plan_queue_url(app) -> str:
    with app.test_request_context():
        return url_for('study.get_study_items', source='linear_plan', **{'from': 'linear_plan', 'slot': 'srs'})


class TestQuota:
    def test_parameters(self):
        assert OLD_DEBT_DAYS == 30
        assert OLD_DEBT_QUOTA_SHARE == pytest.approx(1 / 3)

    @pytest.mark.parametrize('cap, old, fresh, expected', [
        (14, 391, 20, (9, 5)),   # plenty of both: old keeps a third
        (14, 391, 2, (2, 12)),   # few fresh: old fills the batch
        (14, 391, 0, (0, 14)),
        (14, 0, 30, (14, 0)),    # no old debt: fresh take everything
        (14, 3, 30, (11, 3)),    # little old debt: quota shrinks to it
        (20, 30, 12, (12, 8)),
        (0, 5, 5, (0, 0)),
        (1, 5, 5, (0, 1)),
    ])
    def test_split(self, cap, old, fresh, expected):
        assert old_debt_quota(cap, old, fresh) == expected

    def test_batch_is_full_whenever_cards_allow(self):
        for cap in range(0, 31):
            for old in (0, 1, 5, 40):
                for fresh in (0, 1, 5, 40):
                    f, o = old_debt_quota(cap, old, fresh)
                    assert f + o == min(cap, old + fresh)
                    assert f <= fresh and o <= old

    def test_cutoff_is_thirty_days_back(self):
        now = datetime(2026, 9, 6, 12, 0, 0)
        assert old_debt_cutoff(now) == now - timedelta(days=30)


class TestOldDebtCount:
    def test_counts_only_review_cards_past_the_cutoff(self, app, db_session, test_user):
        _review_card(db_session, test_user, overdue_days=45)
        _review_card(db_session, test_user, overdue_days=100)
        _review_card(db_session, test_user, overdue_days=5)
        young = _review_card(db_session, test_user, overdue_days=45)
        young.state = CardState.LEARNING.value  # not mature: not debt
        db_session.commit()
        assert count_old_review_debt(test_user.id) == 2


class TestQueueComposition:
    def _ids_by_overdue(self, db_session, user, days: list[float]) -> dict[int, float]:
        return {_review_card(db_session, user, overdue_days=d).id: d for d in days}

    def test_fresh_first_then_old_quota(self, app, db_session, test_user, client):
        """12 fresh + 30 old, cap 20: 12 fresh (youngest first) then 8 old (oldest first)."""
        _settings(db_session, test_user)
        fresh = self._ids_by_overdue(db_session, test_user, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 20])
        old = self._ids_by_overdue(db_session, test_user, [40 + 3 * i for i in range(30)])  # 40 … 127 days
        _login(client, test_user)
        resp = client.get(_plan_queue_url(app))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        served = [i['id'] for i in resp.get_json()['items']]
        assert len(served) == 20
        fresh_part, old_part = served[:12], served[12:]
        assert all(i in fresh for i in fresh_part) and all(i in old for i in old_part)
        assert [fresh[i] for i in fresh_part] == sorted(fresh.values())          # closest to its date first
        assert [old[i] for i in old_part] == sorted(old.values(), reverse=True)[:8]  # oldest first

    def test_few_fresh_cards_let_old_debt_fill_the_batch(self, app, db_session, test_user, client):
        _settings(db_session, test_user)
        fresh = self._ids_by_overdue(db_session, test_user, [2, 9])
        old = self._ids_by_overdue(db_session, test_user, [35 + 2 * i for i in range(30)])
        _login(client, test_user)
        served = [i['id'] for i in client.get(_plan_queue_url(app)).get_json()['items']]
        assert len(served) == 20
        assert served[:2] == sorted(fresh, key=fresh.get)
        assert all(i in old for i in served[2:]) and len(served[2:]) == 18

    def test_no_fresh_cards_means_all_old(self, app, db_session, test_user, client):
        _settings(db_session, test_user)
        old = self._ids_by_overdue(db_session, test_user, [31 + i for i in range(25)])
        _login(client, test_user)
        served = [i['id'] for i in client.get(_plan_queue_url(app)).get_json()['items']]
        assert len(served) == 20 and all(i in old for i in served)
        assert [old[i] for i in served] == sorted(old.values(), reverse=True)[:20]

    def test_dates_are_untouched(self, app, db_session, test_user, client):
        _settings(db_session, test_user)
        cards = {c.id: c.next_review for c in (_review_card(db_session, test_user, overdue_days=d) for d in (3, 50, 90))}
        _login(client, test_user)
        client.get(_plan_queue_url(app))
        for cid, before in cards.items():
            assert db_session.get(UserCardDirection, cid).next_review == before


class TestTileSubtitle:
    def test_subtitle_names_old_debt(self, app, db_session, test_user):
        from app.daily_plan.items.srs import build_srs_item
        from app.utils.db import db as real_db
        _settings(db_session, test_user)
        for d in (1, 2, 3):
            _review_card(db_session, test_user, overdue_days=d)
        for d in (40, 60, 80, 100, 120, 140):
            _review_card(db_session, test_user, overdue_days=d)
        with app.test_request_context(), patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'):
            item = build_srs_item(test_user.id, real_db, section='required')
        assert item is not None
        assert item.data['review_show'] == 9
        assert (item.data['review_fresh_show'], item.data['review_old_show']) == (3, 6)
        assert '9 на повтор, из них 6 давних' in item.subtitle

    def test_all_old_subtitle(self, app, db_session, test_user):
        from app.daily_plan.items.srs import build_srs_item
        from app.utils.db import db as real_db
        _settings(db_session, test_user)
        for d in (40, 60):
            _review_card(db_session, test_user, overdue_days=d)
        with app.test_request_context(), patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'):
            item = build_srs_item(test_user.id, real_db, section='required')
        assert '2 давних на повтор' in item.subtitle
