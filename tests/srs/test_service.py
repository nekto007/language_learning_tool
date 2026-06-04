"""Tests for app/srs/service.py — leech auto-suspend + RELEARNING_STEPS."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.srs.constants import (
    CardState,
    GRADUATING_INTERVAL,
    LEARNING_STEPS,
    LEECH_THRESHOLD,
    LEECH_SUSPEND_DAYS,
    RATING_DONT_KNOW,
    RATING_DOUBT,
    RATING_KNOW,
    RELEARNING_STEPS,
)
from app.srs.service import UnifiedSRSService
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.study.services import SRSService
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'srssvc_{suffix}',
        email=f'srssvc_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_word(db_session) -> CollectionWords:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'word_{suffix}',
        russian_word=f'слово_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_review_card(db_session, user: User, *, lapses: int) -> UserCardDirection:
    word = _make_word(db_session)
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = 'review'
    db_session.add(uw)
    db_session.commit()

    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = CardState.REVIEW.value
    card.lapses = lapses
    card.repetitions = 5
    card.interval = 10
    card.ease_factor = 2.0
    card.step_index = 0
    card.next_review = _now_naive()
    db_session.add(card)
    db_session.commit()
    return card


class TestRelearningSteps:
    def test_relearning_steps_now_two_days(self):
        assert RELEARNING_STEPS == [10, 1440]


class TestLeechAutoSuspend:
    def test_calc_dict_includes_bury_days_when_threshold_crossed(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=LEECH_THRESHOLD - 1,
        )
        assert result.get('bury_days') == LEECH_SUSPEND_DAYS

    def test_calc_dict_omits_bury_days_below_threshold(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=2,
        )
        assert 'bury_days' not in result or result.get('bury_days') is None

    def test_calc_dict_reburies_above_threshold(self):
        # Cards already past threshold should re-bury on every lapse: firing
        # only on the crossing event leaves recurring leeches cycling through
        # daily failures once their first bury expires.
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=LEECH_THRESHOLD,
        )
        assert result.get('bury_days') == LEECH_SUSPEND_DAYS

    def test_grade_card_buries_on_threshold(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        before = datetime.now(timezone.utc)
        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        db_session.refresh(card)
        assert card.lapses == LEECH_THRESHOLD
        assert card.buried_until is not None

        # Compare in UTC. buried_until may be naive or aware depending on DB.
        # New semantics: buried_until = midnight of (today_local + N days),
        # so the delta from "before" is in the range (N-1, N+1) days depending
        # on time-of-day when the bury fires.
        buried = card.buried_until
        if buried.tzinfo is None:
            buried = buried.replace(tzinfo=timezone.utc)
        delta = buried - before
        assert delta >= timedelta(days=LEECH_SUSPEND_DAYS - 1)
        assert delta <= timedelta(days=LEECH_SUSPEND_DAYS + 1)

    def test_grade_card_does_not_bury_below_threshold(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=2)

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        db_session.refresh(card)
        assert card.lapses == 3
        assert card.buried_until is None

    def test_due_cards_excludes_buried_leech(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        # _get_due_cards must not include this buried leech
        cards = UnifiedSRSService()._get_due_cards(user_id=user.id, limit=50)
        assert card.id not in [c.id for c in cards]

    def test_buried_leech_returns_after_seven_days(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        # Simulate 8 days passing
        db_session.refresh(card)
        card.buried_until = datetime.now(timezone.utc) - timedelta(days=1)
        # Also make next_review due so it is included
        card.next_review = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        cards = UnifiedSRSService()._get_due_cards(user_id=user.id, limit=50)
        assert card.id in [c.id for c in cards]


class TestLearningStepsGraduation:
    def test_three_steps_to_graduate(self):
        assert len(LEARNING_STEPS) == 3
        # Step 0 → 1
        r1 = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW, state=CardState.LEARNING.value,
            step_index=0, repetitions=1, interval=0, ease_factor=2.5,
        )
        assert r1['state'] == CardState.LEARNING.value
        assert r1['step_index'] == 1
        assert r1['requeue_minutes'] == LEARNING_STEPS[1]
        # Step 1 → 2
        r2 = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW, state=CardState.LEARNING.value,
            step_index=1, repetitions=2, interval=0, ease_factor=2.5,
        )
        assert r2['state'] == CardState.LEARNING.value
        assert r2['step_index'] == 2
        assert r2['requeue_minutes'] == LEARNING_STEPS[2]
        # Step 2 → graduate
        r3 = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW, state=CardState.LEARNING.value,
            step_index=2, repetitions=3, interval=0, ease_factor=2.5,
        )
        assert r3['state'] == CardState.REVIEW.value
        assert r3['interval'] == GRADUATING_INTERVAL
        assert r3['requeue_minutes'] is None


def _make_settings(db_session, user: User, *, new_per_day: int = 10) -> StudySettings:
    s = StudySettings(user_id=user.id, new_words_per_day=new_per_day, reviews_per_day=100)
    db_session.add(s)
    db_session.commit()
    return s


class TestAdaptiveLimitReason:
    """Tier resolver maps signals → {normal, low, critical, collapse}.

    Раздел 5 of docs/srs-fix-plan.md: drop is instant, recovery climbs
    one tier per day with a 1-day rest at the floor.
    """

    def test_reason_normal_when_no_history(self, db_session):
        user = _make_user(db_session)
        _make_settings(db_session, user)
        assert SRSService.get_adaptive_limit_reason(user.id) == 'normal'
        new, _ = SRSService.get_adaptive_limits(user.id)
        assert new == 10  # 100% of base 10

    def test_collapse_on_very_low_accuracy(self, db_session):
        """20% accuracy on REVIEW state → collapse tier (NEW=0, REVIEW=0)."""
        user = _make_user(db_session)
        _make_settings(db_session, user)
        for _ in range(5):
            word = _make_word(db_session)
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'review'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.REVIEW.value
            card.correct_count = 1
            card.incorrect_count = 4  # 20% accuracy
            card.last_reviewed = datetime.now(timezone.utc).replace(tzinfo=None)
            card.next_review = card.last_reviewed + timedelta(days=1)
            db_session.add(card)
        db_session.commit()
        assert SRSService.get_adaptive_limit_reason(user.id) == 'collapse'
        new, reviews = SRSService.get_adaptive_limits(user.id)
        assert new == 0
        assert reviews == 0

    def test_backlog_caps_new_but_not_reviews(self, db_session):
        """51 overdue REVIEW cards with reviews_per_day=10 = 5+ days behind.

        After Bug #2 fix: backlog throttles NEW only — REVIEW stays at
        accuracy_pct. So with normal accuracy:
          new   → 0  (critical-tier backlog cap)
          reviews → 10 (100% of base 10, because reviews are how the
                        user reduces the backlog).
        """
        user = _make_user(db_session)
        _make_settings(db_session, user, new_per_day=10)
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        for _ in range(51):
            word = _make_word(db_session)
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'review'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.REVIEW.value
            card.correct_count = 9
            card.incorrect_count = 1
            card.last_reviewed = past
            card.next_review = past
            db_session.add(card)
        db_session.commit()
        from app.study.models import StudySettings
        s = StudySettings.query.filter_by(user_id=user.id).first()
        s.reviews_per_day = 10
        db_session.commit()
        # Tier label reflects accuracy only — accuracy 90% → normal.
        assert SRSService.get_adaptive_limit_reason(user.id) == 'normal'
        new, reviews = SRSService.get_adaptive_limits(user.id)
        assert new == 0    # backlog "critical" → NEW capped at 0%
        assert reviews == 10  # accuracy normal → REVIEW unchanged


class TestAdaptiveTierLadder:
    """Day-ladder recovery from a drop (Раздел 5).

    Drop is immediate; recovery climbs one tier per day, with day 1 as a
    rest day at the floor before the first climb on day 2.
    """

    def _seed_collapse(self, db_session, user):
        """Force collapse by creating REVIEW cards with 20% accuracy."""
        for _ in range(5):
            word = _make_word(db_session)
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'review'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.REVIEW.value
            card.correct_count = 1
            card.incorrect_count = 4  # 20%
            card.last_reviewed = _now_naive()
            card.next_review = _now_naive() + timedelta(days=1)
            db_session.add(card)
        db_session.commit()

    def _store_floor(self, db_session, user, floor: str, floor_date):
        from app.achievements.models import UserStatistics
        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        if not stats:
            stats = UserStatistics(user_id=user.id)
            db_session.add(stats)
        stats.adaptive_tier_floor = floor
        stats.adaptive_tier_floor_date = floor_date
        db_session.commit()

    def test_rest_day_at_floor_after_drop(self, db_session):
        """Day 1 after drop: still at floor (no climb yet)."""
        from datetime import timedelta as td
        from app.utils.time_utils import get_user_local_date
        user = _make_user(db_session)
        _make_settings(db_session, user)
        today = get_user_local_date(user.id)
        self._store_floor(db_session, user, 'collapse', today - td(days=1))
        assert SRSService.get_adaptive_limit_reason(user.id) == 'collapse'

    def test_climb_one_tier_two_days_after_drop(self, db_session):
        """Day 2 after drop: climb one tier (collapse → critical)."""
        from datetime import timedelta as td
        from app.utils.time_utils import get_user_local_date
        user = _make_user(db_session)
        _make_settings(db_session, user)
        today = get_user_local_date(user.id)
        self._store_floor(db_session, user, 'collapse', today - td(days=2))
        assert SRSService.get_adaptive_limit_reason(user.id) == 'critical'

    def test_full_climb_back_to_normal(self, db_session):
        """Day 4 after collapse drop: reached normal."""
        from datetime import timedelta as td
        from app.utils.time_utils import get_user_local_date
        user = _make_user(db_session)
        _make_settings(db_session, user)
        today = get_user_local_date(user.id)
        self._store_floor(db_session, user, 'collapse', today - td(days=4))
        assert SRSService.get_adaptive_limit_reason(user.id) == 'normal'

    def test_drop_during_climb_resets_floor(self, db_session):
        """If accuracy crashes mid-recovery, immediate drop to new floor."""
        from datetime import timedelta as td
        from app.utils.time_utils import get_user_local_date
        from app.achievements.models import UserStatistics

        user = _make_user(db_session)
        _make_settings(db_session, user)
        today = get_user_local_date(user.id)
        self._store_floor(db_session, user, 'low', today - td(days=2))
        self._seed_collapse(db_session, user)
        SRSService.record_tier_state(user.id)
        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        assert stats.adaptive_tier_floor == 'collapse'
        assert stats.adaptive_tier_floor_date == today


class TestGradeCardPessimisticLock:
    """Раздел 6: grade_card holds a SELECT … FOR UPDATE on the direction row
    so two parallel grades on the same card serialize. Without the lock,
    the second flush would clobber the first (last-write-wins), losing
    increments to ``lapses`` / ``first_reviewed`` / state transitions.
    """

    def test_grade_card_emits_for_update_select(self, db_session):
        """Direct SQL inspection — at least one SELECT against
        user_card_directions during grade_card must carry FOR UPDATE.
        """
        from sqlalchemy import event
        from app.utils.db import db

        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=0)

        captured: list[str] = []

        def _capture(conn, cursor, statement, params, context, executemany):
            if statement and 'user_card_directions' in statement.lower():
                captured.append(statement)

        event.listen(db.engine, 'before_cursor_execute', _capture)
        try:
            result = UnifiedSRSService().grade_card(
                card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
            )
            assert result['success'] is True
        finally:
            event.remove(db.engine, 'before_cursor_execute', _capture)

        selects = [s for s in captured if s.lstrip().upper().startswith('SELECT')]
        assert any('FOR UPDATE' in s.upper() for s in selects), (
            'grade_card must take a FOR UPDATE lock on the direction row. '
            f'Observed SELECTs: {selects}'
        )

    def test_grade_grammar_exercise_emits_for_update_select(self, db_session):
        """Same guarantee for grammar exercise grading."""
        from sqlalchemy import event
        from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
        from app.utils.db import db
        import uuid

        user = _make_user(db_session)
        topic = GrammarTopic(
            slug=f'topic-{uuid.uuid4().hex[:8]}', title='T', title_ru='Т',
            level='A1', order=0,
        )
        db_session.add(topic)
        db_session.commit()
        ex = GrammarExercise(
            topic_id=topic.id, exercise_type='multiple_choice',
            content={'question': 'q', 'options': ['a', 'b'], 'correct_answer': 'a'},
            order=1, difficulty=1,
        )
        db_session.add(ex)
        db_session.commit()

        captured: list[str] = []

        def _capture(conn, cursor, statement, params, context, executemany):
            if statement and 'user_grammar_exercises' in statement.lower():
                captured.append(statement)

        event.listen(db.engine, 'before_cursor_execute', _capture)
        try:
            result = UnifiedSRSService().grade_grammar_exercise(
                exercise_id=ex.id, rating=RATING_KNOW, user_id=user.id,
            )
            assert result['success'] is True
        finally:
            event.remove(db.engine, 'before_cursor_execute', _capture)

        selects = [s for s in captured if s.lstrip().upper().startswith('SELECT')]
        assert any('FOR UPDATE' in s.upper() for s in selects), (
            'grade_grammar_exercise must take a FOR UPDATE lock on the progress row. '
            f'Observed SELECTs: {selects}'
        )


class TestReviewIntervalCap:
    """Раздел 12: REVIEW intervals are capped at MAX_REVIEW_INTERVAL_DAYS so
    mastered cards still cycle through reminders. Without the cap an
    SM-2 streak drifts to 180+ day intervals → silent forgetting.
    """

    def test_know_path_caps_new_interval(self):
        from app.srs.constants import MAX_REVIEW_INTERVAL_DAYS
        # Interval 50, ease 2.8 → SM-2 wants 50*2.8*1.3 = 182. Must cap.
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=10,
            interval=50,
            ease_factor=2.8,
            lapses=0,
        )
        assert result['interval'] <= MAX_REVIEW_INTERVAL_DAYS
        assert result['days_until_review'] <= MAX_REVIEW_INTERVAL_DAYS

    def test_hard_path_caps_new_interval(self):
        from app.srs.constants import INTERVAL_MULTIPLIER_HARD, MAX_REVIEW_INTERVAL_DAYS
        # Interval 100, hard rating → 100*1.2 = 120. Must cap.
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=10,
            interval=100,
            ease_factor=2.5,
            lapses=0,
        )
        assert result['interval'] <= MAX_REVIEW_INTERVAL_DAYS

    def test_long_know_streak_never_drifts_past_cap(self):
        """Repeat KNOW on REVIEW many times — interval stays ≤ cap forever."""
        from app.srs.constants import MAX_REVIEW_INTERVAL_DAYS
        interval = 1
        ease = 2.5
        for _ in range(20):
            result = UnifiedSRSService.calculate_sm2_update(
                rating=RATING_KNOW,
                state=CardState.REVIEW.value,
                step_index=0,
                repetitions=1,
                interval=interval,
                ease_factor=ease,
                lapses=0,
            )
            interval = result['interval']
            ease = result['ease_factor']
            assert interval <= MAX_REVIEW_INTERVAL_DAYS

    def test_grade_card_next_review_capped_after_variance(self, db_session):
        """End-to-end: grade_card writes next_review within cap window, even
        after ±10% variance."""
        from app.srs.constants import MAX_REVIEW_INTERVAL_DAYS
        from app.utils.time_utils import day_to_naive_utc

        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=0)
        card.interval = 55  # high baseline
        card.ease_factor = 2.8
        db_session.commit()

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        db_session.commit()
        db_session.refresh(card)

        # next_review = today_midnight_local + N days where N <= cap.
        today_midnight = day_to_naive_utc(user.id, db_session, days_ahead=0)
        # Cap-day midnight in naive UTC
        cap_midnight = day_to_naive_utc(
            user.id, db_session, days_ahead=MAX_REVIEW_INTERVAL_DAYS,
        )
        assert today_midnight <= card.next_review <= cap_midnight


class TestSessionAttemptsResetOnLessonEntry:
    """Раздел 11: lesson card entry must clear ``session_attempts`` so the
    ``MAX_SESSION_ATTEMPTS`` cap re-arms — otherwise a card that hit the
    cap in a previous session stays un-requeueable forever in subsequent
    openings of the same lesson.
    """

    def test_reset_helper_zeros_attempts_for_listed_words(self, db_session):
        from app.curriculum.routes.card_lessons import _reset_lesson_session_attempts

        user = _make_user(db_session)
        word1 = _make_word(db_session)
        word2 = _make_word(db_session)
        for word, attempts in ((word1, 3), (word2, 2)):
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'learning'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.LEARNING.value
            card.session_attempts = attempts
            db_session.add(card)
            db_session.commit()

        _reset_lesson_session_attempts(user.id, [word1.id, word2.id])
        db_session.commit()

        cards = UserCardDirection.query.join(UserWord).filter(
            UserWord.user_id == user.id,
        ).all()
        assert all(c.session_attempts == 0 for c in cards)

    def test_reset_helper_scopes_to_word_ids(self, db_session):
        """Reset must not touch session_attempts on other words."""
        from app.curriculum.routes.card_lessons import _reset_lesson_session_attempts

        user = _make_user(db_session)
        word_in = _make_word(db_session)
        word_out = _make_word(db_session)
        for word in (word_in, word_out):
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'learning'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.LEARNING.value
            card.session_attempts = 3
            db_session.add(card)
            db_session.commit()

        _reset_lesson_session_attempts(user.id, [word_in.id])
        db_session.commit()

        in_card = UserCardDirection.query.join(UserWord).filter(
            UserWord.user_id == user.id, UserWord.word_id == word_in.id,
        ).first()
        out_card = UserCardDirection.query.join(UserWord).filter(
            UserWord.user_id == user.id, UserWord.word_id == word_out.id,
        ).first()
        assert in_card.session_attempts == 0
        assert out_card.session_attempts == 3

    def test_reset_helper_empty_word_ids_noop(self, db_session):
        from app.curriculum.routes.card_lessons import _reset_lesson_session_attempts

        user = _make_user(db_session)
        # Should not raise; nothing to reset.
        _reset_lesson_session_attempts(user.id, [])


class TestAdaptiveTierDropLogging:
    """Раздел 10: record_tier_state emits an observable signal on each drop
    so support / monitoring can answer 'why did this user collapse' without
    inspecting per-user DB state. Recovery climbs are not logged (they are
    deterministic from the stored floor & date).
    """

    def _seed_collapse_signals(self, db_session, user):
        for _ in range(5):
            word = _make_word(db_session)
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'review'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.REVIEW.value
            card.correct_count = 1
            card.incorrect_count = 4  # 20% accuracy
            card.last_reviewed = _now_naive()
            card.next_review = _now_naive() + timedelta(days=1)
            db_session.add(card)
        db_session.commit()

    def test_record_tier_state_logs_on_drop(self, db_session, caplog):
        import logging
        user = _make_user(db_session)
        _make_settings(db_session, user)
        self._seed_collapse_signals(db_session, user)

        with caplog.at_level(logging.INFO, logger='app.study.services.srs_service'):
            SRSService.record_tier_state(user.id)

        messages = [r.getMessage() for r in caplog.records]
        drop_logs = [m for m in messages if 'adaptive_tier' in m and 'drop' in m]
        assert len(drop_logs) == 1, drop_logs
        text = drop_logs[0]
        assert 'collapse' in text  # new floor
        assert 'accuracy=' in text
        assert 'overdue=' in text
        assert f'user={user.id}' in text

    def test_record_tier_state_silent_when_no_drop(self, db_session, caplog):
        """No new drop → no log entry."""
        import logging
        user = _make_user(db_session)
        _make_settings(db_session, user)

        with caplog.at_level(logging.INFO, logger='app.study.services.srs_service'):
            SRSService.record_tier_state(user.id)

        drop_logs = [
            r for r in caplog.records
            if 'adaptive_tier' in r.getMessage() and 'drop' in r.getMessage()
        ]
        assert drop_logs == []


class TestProgressiveLeechBury:
    """Раздел 9: consecutive leech burials extend the next bury duration.

    bury_days = LEECH_SUSPEND_DAYS * (1 + n), capped at MAX_LEECH_SUSPEND_DAYS.
    The streak counter resets on a successful review (rating >= Doubt)
    after the bury expires, so the next first bury starts at base again.
    """

    def test_first_bury_uses_base_duration(self):
        from app.srs.constants import LEECH_SUSPEND_DAYS
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=LEECH_THRESHOLD,
            consecutive_leech_burials=0,
        )
        assert result.get('bury_days') == LEECH_SUSPEND_DAYS

    def test_second_consecutive_bury_doubles_duration(self):
        from app.srs.constants import LEECH_SUSPEND_DAYS
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=LEECH_THRESHOLD + 1,
            consecutive_leech_burials=1,
        )
        assert result.get('bury_days') == LEECH_SUSPEND_DAYS * 2

    def test_progressive_sequence(self):
        """7, 14, 21, 28, 35, … capped at MAX_LEECH_SUSPEND_DAYS."""
        from app.srs.constants import LEECH_SUSPEND_DAYS, MAX_LEECH_SUSPEND_DAYS

        for n in range(15):
            result = UnifiedSRSService.calculate_sm2_update(
                rating=RATING_DONT_KNOW,
                state=CardState.REVIEW.value,
                step_index=0,
                repetitions=5,
                interval=10,
                ease_factor=2.0,
                lapses=LEECH_THRESHOLD + n,
                consecutive_leech_burials=n,
            )
            expected = min(MAX_LEECH_SUSPEND_DAYS, LEECH_SUSPEND_DAYS * (1 + n))
            assert result.get('bury_days') == expected, f'n={n}'

    def test_grade_card_increments_streak_on_bury(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        db_session.commit()
        db_session.refresh(card)
        assert card.consecutive_leech_burials == 1

        # Force second consecutive lapse on the same card (still over threshold).
        card.state = CardState.REVIEW.value
        card.buried_until = None  # simulate post-bury return
        db_session.commit()
        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        db_session.commit()
        db_session.refresh(card)
        assert card.consecutive_leech_burials == 2

    def test_grade_card_resets_streak_on_successful_review(self, db_session):
        from app.srs.constants import LEECH_SUSPEND_DAYS

        user = _make_user(db_session)
        # Simulate a card that has been buried twice consecutively.
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD)
        card.consecutive_leech_burials = 2
        card.buried_until = None
        db_session.commit()

        # User finally remembers it — KNOW on REVIEW.
        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        db_session.commit()
        db_session.refresh(card)
        assert card.consecutive_leech_burials == 0


class TestConcurrentCardCreation:
    """Раздел 7: UserWord / UserCardDirection get_or_create must not raise
    IntegrityError when two writers race on the same (user_id, word_id) /
    (user_word_id, direction). Both helpers wrap INSERT in a savepoint and
    re-fetch on conflict.
    """

    def test_userword_get_or_create_returns_existing_no_error(self, db_session):
        user = _make_user(db_session)
        word = _make_word(db_session)

        a = UserWord.get_or_create(user.id, word.id)
        db_session.commit()
        b = UserWord.get_or_create(user.id, word.id)
        assert a.id == b.id

    def test_direction_get_or_create_returns_existing_no_error(self, db_session):
        from app.study.models import UserCardDirection as Direction
        user = _make_user(db_session)
        word = _make_word(db_session)
        uw = UserWord.get_or_create(user.id, word.id)
        db_session.commit()

        a = Direction.get_or_create(user_word_id=uw.id, direction='eng-rus')
        db_session.commit()
        b = Direction.get_or_create(user_word_id=uw.id, direction='eng-rus')
        assert a.id == b.id

    def test_userword_get_or_create_recovers_from_concurrent_insert(self, db_session):
        """Simulate the race: another transaction inserted the row between
        our SELECT and our INSERT. The savepoint-wrapped INSERT must raise
        IntegrityError internally, get rolled back, and the helper must
        re-fetch the row instead of bubbling the exception.
        """
        from sqlalchemy.exc import IntegrityError
        from app.utils.db import db

        user = _make_user(db_session)
        word = _make_word(db_session)

        # Step 1: another worker already committed the row.
        other_uw = UserWord(user_id=user.id, word_id=word.id)
        db_session.add(other_uw)
        db_session.commit()

        # Step 2: a stale caller hasn't seen it yet — emulate by detaching
        # and calling get_or_create. The SELECT inside should pick up the
        # existing row, no INSERT attempted. (If it did try INSERT, the
        # savepoint pattern would still catch IntegrityError.)
        db.session.expire_all()
        result = UserWord.get_or_create(user.id, word.id)
        assert result.id == other_uw.id

    def test_build_cards_for_words_idempotent_under_race(self, db_session):
        """Two sequential calls to _build_cards_for_words for the same word
        must result in exactly one UserWord and two UserCardDirection rows.
        Stand-in for two concurrent lesson-card-prep paths landing on the
        same word_id."""
        from app.curriculum.routes.card_lessons import _build_cards_for_words
        from app.study.models import UserCardDirection as Direction

        user = _make_user(db_session)
        word = _make_word(db_session)
        db_session.commit()

        _build_cards_for_words([word], user.id, activate_srs=True)
        db_session.commit()
        _build_cards_for_words([word], user.id, activate_srs=True)
        db_session.commit()

        uws = UserWord.query.filter_by(user_id=user.id, word_id=word.id).all()
        assert len(uws) == 1
        dirs = Direction.query.filter_by(user_word_id=uws[0].id).all()
        directions = sorted(d.direction for d in dirs)
        assert directions == ['eng-rus', 'rus-eng']


class TestRelearningEaseFactorClamp:
    """_handle_relearning must keep ease_factor within [MIN, MAX] for parity
    with the other SM-2 handlers, even when called with out-of-range input."""

    @pytest.mark.parametrize('rating', [1, 2, 3])
    def test_below_min_is_clamped_up(self, rating):
        from app.srs.constants import MIN_EASE_FACTOR, RELEARNING_STEPS
        result = UnifiedSRSService.calculate_sm2_update(
            rating=rating,
            state=CardState.RELEARNING.value,
            step_index=0,
            repetitions=1,
            interval=1,
            ease_factor=1.1,  # below MIN_EASE_FACTOR (1.3)
            lapses=3,
        )
        assert result['ease_factor'] >= MIN_EASE_FACTOR

    @pytest.mark.parametrize('rating', [1, 2, 3])
    def test_above_max_is_clamped_down(self, rating):
        from app.srs.constants import MAX_EASE_FACTOR
        result = UnifiedSRSService.calculate_sm2_update(
            rating=rating,
            state=CardState.RELEARNING.value,
            step_index=0,
            repetitions=1,
            interval=1,
            ease_factor=3.5,  # above MAX_EASE_FACTOR (2.8)
            lapses=3,
        )
        assert result['ease_factor'] <= MAX_EASE_FACTOR
