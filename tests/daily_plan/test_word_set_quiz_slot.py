"""The themed-quiz plan item is optional and never gates the day.

`day_secured` is computed from the required section alone. A bonus quiz that
crept into required would change what closes a day for every learner.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.daily_plan.items.word_set_quiz import build_word_set_quiz_item
from app.daily_plan.plan import get_daily_plan
from app.study.models import WordSet, WordSetQuizResult, WordSetWord
from app.utils.db import db as real_db
from app.words.models import CollectionWords


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'wsetplan_{suffix}',
        email=f'wsetplan_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_set(db_session, *, published=True, word_count=3) -> WordSet:
    suffix = uuid.uuid4().hex[:8]
    word_set = WordSet(
        slug=f'set-{suffix}', name='Цвета', icon='🎨',
        accent='amber', is_published=published,
    )
    db_session.add(word_set)
    db_session.flush()

    for index in range(word_count):
        word = CollectionWords(
            english_word=f'w{index}_{suffix}', russian_word=f'слово{index}', level='A1'
        )
        db_session.add(word)
        db_session.flush()
        db_session.add(
            WordSetWord(set_id=word_set.id, word_id=word.id, order_index=index)
        )
    db_session.commit()
    return word_set


class TestBuilder:
    def test_returns_none_without_any_set(self, db_session):
        user = _make_user(db_session)
        assert build_word_set_quiz_item(user.id, real_db) is None

    def test_skips_empty_sets(self, db_session):
        user = _make_user(db_session)
        _make_set(db_session, word_count=0)
        assert build_word_set_quiz_item(user.id, real_db) is None

    def test_skips_unpublished_sets(self, db_session):
        user = _make_user(db_session)
        _make_set(db_session, published=False)
        assert build_word_set_quiz_item(user.id, real_db) is None

    def test_builds_an_optional_item(self, db_session):
        user = _make_user(db_session)
        word_set = _make_set(db_session)

        item = build_word_set_quiz_item(user.id, real_db)
        assert item is not None
        assert item.section == 'optional'
        assert item.kind == 'word_set_quiz'
        assert item.url == f'/study/quiz/set/{word_set.slug}'
        assert item.completed is False
        assert item.data['set_slug'] == word_set.slug

    def test_completed_when_a_quiz_was_played_today(self, db_session):
        user = _make_user(db_session)
        word_set = _make_set(db_session)

        db_session.add(WordSetQuizResult(
            user_id=user.id,
            set_id=word_set.id,
            total_questions=10,
            correct_answers=9,
            score_percentage=90.0,
            time_taken=45,
            # Production stores UTC-now in a naive column; mirror that so the
            # assertion exercises the real comparison basis.
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db_session.commit()

        item = build_word_set_quiz_item(user.id, real_db)
        assert item is not None
        assert item.completed is True
        assert item.eta_minutes == 0

    def test_completed_for_a_quiz_finished_just_after_the_day_starts(self, db_session):
        """A quiz taken at 02:30 in Istanbul is stored as 23:30 UTC the day before.

        The window is built from ``get_user_local_day_bounds`` — naive UTC, the
        basis the column is stored in. Anchoring it on the local calendar date
        instead placed this timestamp a day early, so the slot stayed unfinished
        for anyone studying at the very start of their study day.
        """
        from app.utils.time_utils import get_user_local_day_bounds

        user = _make_user(db_session)
        user.timezone = 'Europe/Istanbul'
        db_session.commit()
        word_set = _make_set(db_session)

        # 30 minutes into the current study day, whenever the suite happens to run.
        day_start_utc, _ = get_user_local_day_bounds(user.id, db_session)
        finished_at = day_start_utc + timedelta(minutes=30)

        db_session.add(WordSetQuizResult(
            user_id=user.id,
            set_id=word_set.id,
            total_questions=10,
            correct_answers=8,
            score_percentage=80.0,
            time_taken=50,
            completed_at=finished_at,
        ))
        db_session.commit()

        item = build_word_set_quiz_item(user.id, real_db)
        assert item is not None
        assert item.completed is True

    def test_not_completed_for_a_quiz_from_the_previous_study_day(self, db_session):
        """The window must still exclude yesterday, or the slot never resets."""
        from app.utils.time_utils import get_user_local_day_bounds

        user = _make_user(db_session)
        user.timezone = 'Europe/Istanbul'
        db_session.commit()
        word_set = _make_set(db_session)

        day_start_utc, _ = get_user_local_day_bounds(user.id, db_session)
        finished_at = day_start_utc - timedelta(minutes=1)

        db_session.add(WordSetQuizResult(
            user_id=user.id,
            set_id=word_set.id,
            total_questions=10,
            correct_answers=8,
            score_percentage=80.0,
            time_taken=50,
            completed_at=finished_at,
        ))
        db_session.commit()

        item = build_word_set_quiz_item(user.id, real_db)
        assert item is not None
        assert item.completed is False


class TestPlanIntegration:
    def test_item_never_lands_in_required(self, db_session):
        user = _make_user(db_session)
        _make_set(db_session)

        plan = get_daily_plan(user.id, real_db)

        required_kinds = {item['kind'] for item in plan.get('required', [])}
        assert 'word_set_quiz' not in required_kinds

    def test_incomplete_item_does_not_block_day_secured(self, db_session):
        """An unplayed themed quiz must not keep the day open."""
        user = _make_user(db_session)
        _make_set(db_session)

        plan = get_daily_plan(user.id, real_db)

        optional_ids = {item['id'] for item in plan.get('optional', [])}
        required_ids = {item['id'] for item in plan.get('required', [])}
        assert not (optional_ids & required_ids)

        # day_secured is always False at assembly; what matters is that the
        # item is absent from the section the recompute reads.
        assert plan.get('day_secured') is False
        for item in plan.get('required', []):
            assert item['kind'] != 'word_set_quiz'


@pytest.mark.smoke
def test_builder_is_safe_for_a_fresh_user(db_session):
    user = _make_user(db_session)
    assert build_word_set_quiz_item(user.id, real_db) is None
