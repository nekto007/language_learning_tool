"""Lesson audit item 15: the «behind» signal and the required-section floor.

1. ``pace_status`` reports ``behind`` when a learner with prior history hit
   the pace on fewer than three of the last seven study days; newcomers are
   never behind; the upward nudge and behind are mutually exclusive.
2. The required section never shrinks to a single lesson: a short, closable
   filler (themed quiz, else grammar review) keeps a floor of two items, and
   the snapshot can detect its completion.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.plan_builder import (
    REQUIRED_MIN_ITEMS,
    _ensure_minimum_items,
    build_required_snapshot,
)
from app.daily_plan.snapshot import _is_item_completed
from app.daily_plan.tier import PACE_BEHIND_DAYS, PACE_UP_DAYS, pace_status
from app.study.models import WordSet, WordSetQuizResult, WordSetWord
from app.utils.db import db as real_db
from app.words.models import CollectionWords
from tests.conftest import unique_level_code


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _user(db_session, difficulty: str = 'light') -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(username=f'bh_{suffix}', email=f'bh_{suffix}@example.com', active=True)
    user.set_password('Str0ng-Passw0rd!')
    user.plan_difficulty = difficulty
    db_session.add(user)
    db_session.commit()
    return user


def _lessons(db_session, n: int) -> list[Lessons]:
    code = unique_level_code()
    level = CEFRLevel(code=code, name=f'L-{code}', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='M', description='', raw_content={})
    db_session.add(module)
    db_session.commit()
    lessons = [Lessons(module_id=module.id, number=i + 1, title=f'L{i + 1}', type='vocabulary', content={}) for i in range(n)]
    db_session.add_all(lessons)
    db_session.commit()
    return lessons


def _complete(db_session, user, lesson, when: datetime) -> None:
    db_session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id, status='completed',
                                  started_at=when, completed_at=when, last_activity=when))
    db_session.commit()


def _hit_days(db_session, user, lessons, days: int) -> None:
    for d in range(1, days + 1):
        _complete(db_session, user, lessons[d - 1], (_now() - timedelta(days=d)).replace(hour=12))


def _published_set(db_session) -> WordSet:
    words = []
    for _ in range(3):
        w = CollectionWords(english_word=f'ws_{uuid.uuid4().hex[:10]}', russian_word='перевод')
        db_session.add(w)
        words.append(w)
    db_session.commit()
    ws = WordSet(slug=f'set-{uuid.uuid4().hex[:8]}', name='Набор', description='d', level='A1', sort_order=0, is_published=True)
    db_session.add(ws)
    db_session.commit()
    for i, w in enumerate(words):
        db_session.add(WordSetWord(set_id=ws.id, word_id=w.id, order_index=i))
    db_session.commit()
    return ws


class TestPaceStatus:
    def test_behind_needs_history_and_few_hits(self, app, db_session):
        user = _user(db_session)
        lessons = _lessons(db_session, 12)
        _complete(db_session, user, lessons[11], _now() - timedelta(days=30))  # history before the window
        _hit_days(db_session, user, lessons, PACE_BEHIND_DAYS - 1)
        status = pace_status(user.id, real_db)
        assert status['behind'] is True and status['recommended'] is None
        assert status['days_hit'] == PACE_BEHIND_DAYS - 1 and status['lessons_per_day'] == 1

    def test_newcomer_is_never_behind(self, app, db_session):
        user = _user(db_session)
        lessons = _lessons(db_session, 3)
        _hit_days(db_session, user, lessons, 1)
        status = pace_status(user.id, real_db)
        assert status['behind'] is False and status['days_hit'] == 1

    def test_enough_hits_is_not_behind(self, app, db_session):
        user = _user(db_session)
        lessons = _lessons(db_session, 12)
        _complete(db_session, user, lessons[11], _now() - timedelta(days=30))
        _hit_days(db_session, user, lessons, PACE_BEHIND_DAYS)
        assert pace_status(user.id, real_db)['behind'] is False

    def test_nudge_and_behind_are_exclusive(self, app, db_session):
        user = _user(db_session)
        lessons = _lessons(db_session, 12)
        _complete(db_session, user, lessons[11], _now() - timedelta(days=30))
        _hit_days(db_session, user, lessons, PACE_UP_DAYS)
        status = pace_status(user.id, real_db)
        assert status['recommended'] == 2 and status['behind'] is False

    def test_zero_hits_with_history_is_behind(self, app, db_session):
        user = _user(db_session)
        lessons = _lessons(db_session, 1)
        _complete(db_session, user, lessons[0], _now() - timedelta(days=40))
        status = pace_status(user.id, real_db)
        assert status['behind'] is True and status['days_hit'] == 0


class TestMinimumFloor:
    def test_floor_is_two(self):
        assert REQUIRED_MIN_ITEMS == 2

    def test_filler_added_when_only_one_item(self, app, db_session):
        user = _user(db_session)
        _published_set(db_session)
        items = [{'id': 'curriculum:1', 'kind': 'curriculum', 'section': 'required'}]
        with app.test_request_context():
            out = _ensure_minimum_items(user.id, real_db, items)
        assert len(out) == 2
        assert out[1]['kind'] == 'word_set_quiz' and out[1]['section'] == 'required'
        assert out[1]['data']['minimum_filler'] is True
        assert 'completed' not in out[1]  # live field stripped for the snapshot

    def test_two_items_untouched(self, app, db_session):
        user = _user(db_session)
        _published_set(db_session)
        items = [{'id': 'curriculum:1', 'kind': 'curriculum'}, {'id': 'srs:global', 'kind': 'srs'}]
        with app.test_request_context():
            assert _ensure_minimum_items(user.id, real_db, items) == items

    def test_empty_required_stays_empty(self, app, db_session):
        user = _user(db_session)
        _published_set(db_session)
        with app.test_request_context():
            assert _ensure_minimum_items(user.id, real_db, []) == []

    def test_no_sources_means_no_filler(self, app, db_session):
        user = _user(db_session)
        items = [{'id': 'curriculum:1', 'kind': 'curriculum'}]
        with app.test_request_context():
            assert _ensure_minimum_items(user.id, real_db, items) == items

    def test_snapshot_detects_filler_completion(self, app, db_session):
        user = _user(db_session)
        ws = _published_set(db_session)
        item = {'id': f'word_set_quiz:{ws.slug}', 'kind': 'word_set_quiz', 'data': {'set_slug': ws.slug, 'minimum_filler': True}}
        with app.test_request_context():
            assert _is_item_completed(user.id, item, real_db) is False
            db_session.add(WordSetQuizResult(user_id=user.id, set_id=ws.id, total_questions=3, correct_answers=2,
                                             score_percentage=66.7, time_taken=30, completed_at=_now()))
            db_session.commit()
            assert _is_item_completed(user.id, item, real_db) is True

    def test_required_snapshot_gets_the_floor(self, app, db_session):
        user = _user(db_session, 'light')
        _lessons(db_session, 3)
        _published_set(db_session)
        with app.test_request_context():
            items = build_required_snapshot(user.id, 'calm', real_db)
        kinds = [it['kind'] for it in items]
        assert kinds == ['curriculum', 'word_set_quiz'], kinds
        assert items[1]['data']['minimum_filler'] is True

    def test_payload_carries_behind_flag(self, app, db_session):
        from app.daily_plan.plan import get_daily_plan
        user = _user(db_session, 'light')
        lessons = _lessons(db_session, 2)
        _complete(db_session, user, lessons[1], _now() - timedelta(days=40))
        with app.test_request_context():
            plan = get_daily_plan(user.id, real_db)
        assert plan['pace']['behind'] is True
        assert plan['pace']['lessons_per_day'] == 1
