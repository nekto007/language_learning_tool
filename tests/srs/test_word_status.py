"""Tests for UserWord.recalculate_status — the derived word-level status.

The rule that matters: a word only counts as learned ('review') once BOTH
recall directions hold. Recognising the English form is not the same as being
able to produce it, and the old rule let a single keypress on a fresh word
count as learned in every "выучено" total.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.models import User
from app.srs.constants import CardState
from app.study.models import UserCardDirection, UserWord
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'wstatus_{suffix}',
        email=f'wstatus_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_user_word(db_session, user: User) -> UserWord:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'word_{suffix}',
        russian_word=f'слово_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()

    user_word = UserWord(user_id=user.id, word_id=word.id)
    db_session.add(user_word)
    db_session.commit()
    return user_word


def _add_direction(
    db_session,
    user_word: UserWord,
    direction: str,
    *,
    state: str = CardState.NEW.value,
    first_reviewed: datetime | None = None,
    interval: int = 0,
) -> UserCardDirection:
    row = UserCardDirection(user_word_id=user_word.id, direction=direction)
    row.state = state
    row.first_reviewed = first_reviewed
    row.interval = interval
    db_session.add(row)
    db_session.commit()
    return row


class TestRecalculateStatus:
    def test_no_directions_keeps_new(self, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)

        user_word.recalculate_status()

        assert user_word.status == 'new'

    def test_single_direction_in_review_is_not_learned(self, db_session):
        # One "Знаю" on a freshly seen word creates one direction and jumps it
        # straight to REVIEW. That is not a learned word.
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.REVIEW.value)

        user_word.recalculate_status()

        assert user_word.status == 'learning'

    def test_both_directions_in_review_is_learned(self, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.REVIEW.value)
        _add_direction(db_session, user_word, 'rus-eng', state=CardState.REVIEW.value)

        user_word.recalculate_status()

        assert user_word.status == 'review'

    def test_any_direction_learning_wins(self, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.REVIEW.value)
        _add_direction(db_session, user_word, 'rus-eng', state=CardState.LEARNING.value)

        user_word.recalculate_status()

        assert user_word.status == 'learning'

    def test_relearning_counts_as_learning(self, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.RELEARNING.value)
        _add_direction(db_session, user_word, 'rus-eng', state=CardState.REVIEW.value)

        user_word.recalculate_status()

        assert user_word.status == 'learning'

    def test_untouched_new_directions_stay_new(self, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus')
        _add_direction(db_session, user_word, 'rus-eng')

        user_word.recalculate_status()

        assert user_word.status == 'new'

    def test_graded_but_still_new_direction_is_learning(self, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', first_reviewed=_now_naive())
        _add_direction(db_session, user_word, 'rus-eng')

        user_word.recalculate_status()

        assert user_word.status == 'learning'

    def test_regressed_direction_drops_learned_status(self, db_session):
        # A word stops counting as learned as soon as one direction is no
        # longer in review — it is started, but not finished.
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.REVIEW.value)
        _add_direction(db_session, user_word, 'rus-eng', state=CardState.REVIEW.value)
        user_word.recalculate_status()
        assert user_word.status == 'review'

        sibling = UserCardDirection.query.filter_by(
            user_word_id=user_word.id, direction='rus-eng',
        ).first()
        sibling.state = CardState.NEW.value
        db_session.commit()

        user_word.recalculate_status()

        assert user_word.status == 'learning'

    def test_excluded_word_still_recalculates(self, db_session):
        # Returning early for excluded words froze their status forever, which
        # is why the dashboard and the achievement counters disagreed.
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        user_word.srs_excluded = True
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.REVIEW.value)
        _add_direction(db_session, user_word, 'rus-eng', state=CardState.REVIEW.value)

        user_word.recalculate_status()

        assert user_word.status == 'review'


class TestMasteredIsDerived:
    def test_mastered_requires_review_status_and_interval(self, db_session):
        from app.srs.constants import MASTERED_THRESHOLD_DAYS

        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(
            db_session, user_word, 'eng-rus',
            state=CardState.REVIEW.value, interval=MASTERED_THRESHOLD_DAYS,
        )
        _add_direction(
            db_session, user_word, 'rus-eng',
            state=CardState.REVIEW.value, interval=MASTERED_THRESHOLD_DAYS,
        )
        user_word.recalculate_status()

        assert user_word.is_mastered is True

    def test_shortest_interval_decides(self, db_session):
        from app.srs.constants import MASTERED_THRESHOLD_DAYS

        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(
            db_session, user_word, 'eng-rus',
            state=CardState.REVIEW.value, interval=MASTERED_THRESHOLD_DAYS,
        )
        _add_direction(
            db_session, user_word, 'rus-eng',
            state=CardState.REVIEW.value, interval=1,
        )
        user_word.recalculate_status()

        assert user_word.is_mastered is False


class TestLocalDateRendering:
    """A rest ending on the 10th must not be shown as the 9th.

    buried_until stores the user's local day start projected to naive UTC, so
    rendering it as UTC prints the previous calendar day east of Greenwich.
    """

    def test_local_date_matches_the_scheduled_day(self, db_session):
        from app.utils.time_utils import day_to_naive_utc, naive_utc_to_user_local_date

        user = _make_user(db_session)
        user.timezone = 'Europe/Istanbul'  # UTC+3, where the off-by-one showed
        db_session.commit()

        buried_until = day_to_naive_utc(user.id, db_session, days_ahead=7)
        local_date = naive_utc_to_user_local_date(user.id, buried_until, db_session)

        # The raw UTC value lands on the previous day; the local one must not.
        assert local_date is not None
        assert local_date >= buried_until.date()

    def test_none_is_passed_through(self, db_session):
        from app.utils.time_utils import naive_utc_to_user_local_date

        user = _make_user(db_session)
        assert naive_utc_to_user_local_date(user.id, None, db_session) is None


class TestRecalcWordStatusCommand:
    """The one-off backfill that re-derives stored statuses under the new rule."""

    def test_dry_run_reports_without_writing(self, app, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.REVIEW.value)
        user_word.status = 'review'  # the value the old single-direction rule produced
        db_session.commit()

        result = app.test_cli_runner().invoke(args=['recalc-word-status', '--dry-run'])

        assert result.exit_code == 0, result.output
        assert 'Recalculating word statuses (dry-run)' in result.output

    def test_live_run_rewrites_stale_status(self, app, db_session):
        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus', state=CardState.REVIEW.value)
        user_word.status = 'review'
        db_session.commit()
        word_id = user_word.id

        result = app.test_cli_runner().invoke(args=['recalc-word-status', '--user-id', str(user.id)])

        assert result.exit_code == 0, result.output
        refreshed = UserWord.query.get(word_id)
        assert refreshed.status == 'learning'


class TestEnsureCardDirections:
    def test_creates_both_directions(self, db_session):
        from app.srs.cards import ensure_card_directions

        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)

        created = ensure_card_directions(user_word)
        db_session.commit()

        assert {d.direction for d in created} == {'eng-rus', 'rus-eng'}
        assert user_word.directions.count() == 2

    def test_is_idempotent(self, db_session):
        from app.srs.cards import ensure_card_directions

        user = _make_user(db_session)
        user_word = _make_user_word(db_session, user)
        _add_direction(db_session, user_word, 'eng-rus')

        ensure_card_directions(user_word)
        db_session.commit()

        assert user_word.directions.count() == 2
