"""Lesson audit item 12: review budget policy of the SRS slot.

1. Accuracy throttles NEW cards only; the review allowance is always the
   base ``reviews_per_day`` (no x0.6 / x0.2 / x0 cut).
2. A share of the combined ceiling is reserved for mature reviews, so the
   20 learning directions a card lesson activates no longer take the whole
   next day; tile, queue and completion checks use one split.
3. The tile names the signal that pauses NEW cards: backlog or accuracy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from flask import url_for

from app.daily_plan.items.srs import _pause_reason_hint
from app.srs.constants import CardState
from app.srs.counting import REVIEW_RESERVE_SHARE, split_due_budget
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.study.services.srs_service import SRSService
from app.words.models import CollectionWords


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _card(db_session, user, *, state: str, due_hours_ago: int = 1) -> UserCardDirection:
    word = CollectionWords(english_word=f'rb_{uuid.uuid4().hex[:10]}', russian_word='перевод')
    db_session.add(word)
    db_session.commit()
    uw = UserWord(user_id=user.id, word_id=word.id)
    db_session.add(uw)
    db_session.commit()
    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = state
    card.step_index = 2 if state == CardState.LEARNING.value else 0
    card.interval = 10 if state == CardState.REVIEW.value else 0
    card.repetitions = 3 if state == CardState.REVIEW.value else 0
    card.ease_factor = 2.5
    card.first_reviewed = _now() - timedelta(days=5)
    card.last_reviewed = _now() - timedelta(days=2)
    card.next_review = _now() - timedelta(hours=due_hours_ago)
    db_session.add(card)
    db_session.commit()
    return card


class TestAccuracyThrottlesNewOnly:
    @pytest.mark.parametrize('tier', ['normal', 'low', 'critical', 'collapse'])
    def test_review_share_is_full_on_every_tier(self, tier):
        assert SRSService.TIER_PCT[tier]['review'] == 1.0

    def test_new_share_still_drops(self):
        assert [SRSService.TIER_PCT[t]['new'] for t in ('normal', 'low', 'critical', 'collapse')] == [1.0, 0.6, 0.2, 0.0]

    def test_adaptive_reviews_equal_base_under_collapse(self, app, db_session, test_user):
        db_session.add(StudySettings(user_id=test_user.id, new_words_per_day=10, reviews_per_day=20))
        db_session.commit()
        with patch.object(SRSService, '_resolve_tier', return_value=('collapse', False, 'collapse', None)), \
             patch.object(SRSService, '_overdue_review_count', return_value=0):
            assert SRSService.get_adaptive_limits(test_user.id) == (0, 20)
            assert SRSService.get_adaptive_limit_reason(test_user.id) == 'collapse'


class TestSplitDueBudget:
    @pytest.mark.parametrize('learning_due, review_due, budget, expected', [
        (40, 100, 20, (10, 10)),   # the card-lesson morning: reviews keep half
        (5, 100, 20, (5, 15)),     # small learning pile: reviews take the rest
        (40, 3, 20, (17, 3)),      # few reviews due: reserve shrinks to them
        (0, 100, 20, (0, 20)),
        (40, 0, 20, (20, 0)),
        (40, 100, 5, (2, 3)),      # late in the day: ceil(5 x 0.5) = 3 held back
        (40, 100, 0, (0, 0)),
    ])
    def test_split(self, app, test_user, learning_due, review_due, budget, expected):
        with patch('app.srs.counting.count_reviews_today', return_value=0):
            assert split_due_budget(
                test_user.id, learning_due=learning_due, review_due=review_due,
                due_budget=budget, remaining_reviews=budget,
            ) == expected

    def test_reserve_share_is_half(self):
        assert REVIEW_RESERVE_SHARE == 0.5

    def test_learning_never_exceeds_budget_minus_reserve(self, app, test_user):
        with patch('app.srs.counting.count_reviews_today', return_value=0):
            for budget in range(0, 41):
                learning, review = split_due_budget(
                    test_user.id, learning_due=1000, review_due=1000,
                    due_budget=budget, remaining_reviews=budget,
                )
                assert learning + review == budget
                assert review >= (budget + 1) // 2


class TestPauseReason:
    def _settings(self, db_session, user, reviews=20):
        db_session.add(StudySettings(user_id=user.id, new_words_per_day=10, reviews_per_day=reviews))
        db_session.commit()

    def test_backlog_binds_when_accuracy_is_fine(self, app, db_session, test_user):
        self._settings(db_session, test_user)
        with patch.object(SRSService, 'get_adaptive_limit_reason', return_value='normal'), \
             patch.object(SRSService, 'get_overdue_review_count', return_value=409):
            pause = SRSService.get_new_card_pause(test_user.id)
        assert pause['binding'] == 'backlog'
        assert pause['backlog_tier'] == 'collapse'
        assert pause['days_behind'] == pytest.approx(20.45, abs=0.06)
        assert pause['new_pct'] == 0.0
        hint = _pause_reason_hint(pause, review_show=24)
        assert hint == 'Долг 409 карточек. Сегодня разбираем 24. Новые слова начнут возвращаться, когда долг станет меньше 60.'
        assert 'дн.' not in hint

    def test_accuracy_binds_when_no_backlog(self, app, db_session, test_user):
        self._settings(db_session, test_user)
        with patch.object(SRSService, 'get_adaptive_limit_reason', return_value='collapse'), \
             patch.object(SRSService, 'get_overdue_review_count', return_value=0):
            pause = SRSService.get_new_card_pause(test_user.id)
        assert pause['binding'] == 'accuracy'
        assert _pause_reason_hint(pause, 10) == 'Точность ниже 45 % — пауза на новые слова, повторения вернут форму.'

    def test_no_reduction_means_no_hint(self, app, db_session, test_user):
        self._settings(db_session, test_user)
        with patch.object(SRSService, 'get_adaptive_limit_reason', return_value='normal'), \
             patch.object(SRSService, 'get_overdue_review_count', return_value=10):
            pause = SRSService.get_new_card_pause(test_user.id)
        assert pause['binding'] is None and _pause_reason_hint(pause) is None

    def test_equal_cut_names_both(self, app, db_session, test_user):
        self._settings(db_session, test_user)
        # critical accuracy (x0.2) vs backlog critical (x0.0): backlog binds; collapse vs critical-backlog: equal 0 -> both
        with patch.object(SRSService, 'get_adaptive_limit_reason', return_value='collapse'), \
             patch.object(SRSService, 'get_overdue_review_count', return_value=100):
            pause = SRSService.get_new_card_pause(test_user.id)
        assert pause['binding'] == 'both'
        hint = _pause_reason_hint(pause, 12)
        assert hint.startswith('Долг 100 карточек. Сегодня разбираем 12.') and hint.endswith('повторения вернут форму.')

    def test_reader_does_not_create_settings(self, app, db_session, test_user):
        assert StudySettings.query.filter_by(user_id=test_user.id).first() is None
        with patch.object(SRSService, 'get_adaptive_limit_reason', return_value='normal'), \
             patch.object(SRSService, 'get_overdue_review_count', return_value=0):
            SRSService.get_new_card_pause(test_user.id)
        assert StudySettings.query.filter_by(user_id=test_user.id).first() is None


class TestTileAndQueueAgree:
    def _deck(self, db_session, user, learning: int, review: int) -> None:
        db_session.add(StudySettings(user_id=user.id, new_words_per_day=0, reviews_per_day=20))
        db_session.commit()
        for _ in range(learning):
            _card(db_session, user, state=CardState.LEARNING.value)
        for _ in range(review):
            _card(db_session, user, state=CardState.REVIEW.value)

    def test_card_lesson_morning_keeps_half_for_reviews(self, app, db_session, test_user, client):
        """30 learning + 30 review due, ceiling 20: the tile shows 10 + 10 and the queue serves 10 + 10."""
        from app.daily_plan.items.srs import build_srs_item
        from app.utils.db import db as real_db
        self._deck(db_session, test_user, learning=30, review=30)
        with app.test_request_context():
            item = build_srs_item(test_user.id, real_db, section='required')
            url = url_for('study.get_study_items', source='linear_plan', **{'from': 'linear_plan', 'slot': 'srs'})
        assert item is not None
        assert (item.data['learning_show'], item.data['review_show']) == (10, 10)
        assert item.data['total_show'] == 20
        _login(client, test_user)
        resp = client.get(url)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        items = resp.get_json()['items']
        states = [i['state'] for i in items]
        assert states.count(CardState.LEARNING.value) == 10
        assert states.count(CardState.REVIEW.value) == 10
        assert len(items) == 20

    def test_small_learning_pile_leaves_reviews_the_rest(self, app, db_session, test_user, client):
        from app.daily_plan.items.srs import build_srs_item
        from app.utils.db import db as real_db
        self._deck(db_session, test_user, learning=4, review=30)
        with app.test_request_context():
            item = build_srs_item(test_user.id, real_db, section='required')
            url = url_for('study.get_study_items', source='linear_plan', **{'from': 'linear_plan', 'slot': 'srs'})
        assert (item.data['learning_show'], item.data['review_show']) == (4, 16)
        _login(client, test_user)
        states = [i['state'] for i in client.get(url).get_json()['items']]
        assert states.count(CardState.LEARNING.value) == 4
        assert states.count(CardState.REVIEW.value) == 16


class TestMotivatingHint:
    """Owner's rule: the hint talks about today's portion and the comeback, never about days of work."""

    def _pause(self, **over):
        base = {'binding': 'backlog', 'backlog_tier': 'collapse', 'accuracy_tier': 'normal',
                'overdue': 415, 'days_behind': 13.8, 'reviews_per_day': 30}
        base.update(over)
        return base

    def test_big_debt_names_portion_and_comeback(self):
        assert _pause_reason_hint(self._pause(), review_show=24) == (
            'Долг 415 карточек. Сегодня разбираем 24. Новые слова начнут возвращаться, когда долг станет меньше 90.'
        )

    def test_no_portion_left_today(self):
        hint = _pause_reason_hint(self._pause(), review_show=0)
        assert hint == 'Долг 415 карточек. Новые слова начнут возвращаться, когда долг станет меньше 90.'

    def test_small_debt_is_reassuring(self):
        hint = _pause_reason_hint(self._pause(backlog_tier='low', overdue=45, days_behind=1.5), review_show=20)
        assert hint == 'Долг 45 карточек — новых слов сегодня меньше. Такой долг закрывается за пару дней.'

    def test_never_mentions_days_or_decimals(self):
        for tier in ('low', 'critical', 'collapse'):
            hint = _pause_reason_hint(self._pause(backlog_tier=tier), review_show=24)
            assert 'дн.' not in hint and '13.8' not in hint and '13,8' not in hint
