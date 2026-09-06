"""Lesson audit item 14: explicit lesson pace and an opt-in reading goal.

1. ``User.plan_difficulty`` maps to 1/2/3 curriculum lessons a day; the
   secured-day ladder no longer decides. ``recommend_pace`` nudges upward
   when the learner hit the pace on most of the last seven study days.
2. Reading is optional unless ``StudySettings.reading_minutes_per_day`` > 0;
   the daily target is that goal (fixed 5 minutes otherwise), no more 5/10
   day-of-month alternation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from flask import url_for

from app.auth.models import User
from app.books.reading_session import (
    DAILY_READING_TARGET_SECONDS,
    get_daily_reading_target_seconds,
)
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.items.reading import reading_goal_enabled
from app.daily_plan.tier import (
    PACE_UP_DAYS,
    difficulty_for_pace,
    pace_from_difficulty,
    recommend_pace,
)
from app.study.models import StudySettings
from app.utils.db import db as real_db
from tests.conftest import unique_level_code


def _user(db_session, difficulty: str = 'normal') -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(username=f'pace_{suffix}', email=f'pace_{suffix}@example.com', active=True)
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


class TestPaceMapping:
    @pytest.mark.parametrize('value, pace', [('light', 1), ('normal', 2), ('intensive', 3), ('INTENSIVE', 3), (None, 2), ('junk', 2)])
    def test_from_difficulty(self, value, pace):
        assert pace_from_difficulty(value) == pace

    @pytest.mark.parametrize('pace, value', [(1, 'light'), (2, 'normal'), (3, 'intensive'), (9, 'normal')])
    def test_for_pace(self, pace, value):
        assert difficulty_for_pace(pace) == value


class TestRecommendPace:
    def _hit_days(self, db_session, user, lessons, days: int, per_day: int) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        i = 0
        for d in range(1, days + 1):
            when = (now - timedelta(days=d)).replace(hour=12)
            for _ in range(per_day):
                _complete(db_session, user, lessons[i], when)
                i += 1

    def test_nudges_up_when_pace_is_met_most_days(self, app, db_session):
        user = _user(db_session, 'light')
        lessons = _lessons(db_session, PACE_UP_DAYS)
        self._hit_days(db_session, user, lessons, days=PACE_UP_DAYS, per_day=1)
        rec = recommend_pace(user.id, real_db)
        assert rec == {'current': 1, 'recommended': 2, 'days_hit': PACE_UP_DAYS}

    def test_no_nudge_below_threshold(self, app, db_session):
        user = _user(db_session, 'light')
        lessons = _lessons(db_session, PACE_UP_DAYS - 1)
        self._hit_days(db_session, user, lessons, days=PACE_UP_DAYS - 1, per_day=1)
        assert recommend_pace(user.id, real_db) is None

    def test_days_must_reach_the_current_pace(self, app, db_session):
        user = _user(db_session, 'normal')  # pace 2: one lesson a day does not count
        lessons = _lessons(db_session, 7)
        self._hit_days(db_session, user, lessons, days=7, per_day=1)
        assert recommend_pace(user.id, real_db) is None

    def test_never_above_three(self, app, db_session):
        user = _user(db_session, 'intensive')
        assert recommend_pace(user.id, real_db) is None

    def test_today_does_not_count(self, app, db_session):
        user = _user(db_session, 'light')
        lessons = _lessons(db_session, PACE_UP_DAYS)
        self._hit_days(db_session, user, lessons, days=PACE_UP_DAYS - 1, per_day=1)
        _complete(db_session, user, lessons[-1], datetime.now(UTC).replace(tzinfo=None))
        assert recommend_pace(user.id, real_db) is None


class TestReadingTarget:
    def test_fixed_floor_without_goal_on_any_day(self, app, db_session):
        user = _user(db_session)
        for day in (date(2026, 9, 3), date(2026, 9, 4)):  # odd and even days of the month
            assert get_daily_reading_target_seconds(day, user_id=user.id) == DAILY_READING_TARGET_SECONDS
        assert get_daily_reading_target_seconds(date(2026, 9, 4)) == DAILY_READING_TARGET_SECONDS

    def test_personal_goal_wins(self, app, db_session):
        user = _user(db_session)
        db_session.add(StudySettings(user_id=user.id, new_words_per_day=5, reviews_per_day=20, reading_minutes_per_day=10))
        db_session.commit()
        assert get_daily_reading_target_seconds(date(2026, 9, 3), user_id=user.id) == 600
        assert reading_goal_enabled(user.id, real_db) is True

    def test_zero_goal_means_optional(self, app, db_session):
        user = _user(db_session)
        db_session.add(StudySettings(user_id=user.id, new_words_per_day=5, reviews_per_day=20, reading_minutes_per_day=0))
        db_session.commit()
        assert reading_goal_enabled(user.id, real_db) is False
        assert get_daily_reading_target_seconds(user_id=user.id) == DAILY_READING_TARGET_SECONDS


class TestReadingRequiredOnlyWithGoal:
    def test_reading_item_dict_needs_a_goal(self, app, db_session):
        from app.daily_plan import plan_builder
        user = _user(db_session)
        with patch.object(plan_builder, 'get_user_reading_preference', return_value=object()), \
             patch.object(plan_builder, 'book_selected_today', return_value=False), \
             patch.object(plan_builder, 'build_reading_item') as build:
            assert plan_builder._reading_item_dict(user.id, real_db) is None
            build.assert_not_called()
            db_session.add(StudySettings(user_id=user.id, new_words_per_day=5, reviews_per_day=20, reading_minutes_per_day=5))
            db_session.commit()
            build.return_value = None
            plan_builder._reading_item_dict(user.id, real_db)
            build.assert_called_once()


class TestSettingsPage:
    def _login(self, client, user) -> None:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

    def test_saves_pace_and_reading_goal(self, app, db_session, client, test_user):
        self._login(client, test_user)
        with app.test_request_context():
            url = url_for('study.settings')
        page = client.get(url)
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert 'name="lessons_per_day"' in html and 'name="reading_minutes_per_day"' in html
        resp = client.post(url, data={
            'new_words_per_day': '5', 'reviews_per_day': '20', 'show_hint_time': '10',
            'include_translations': 'y', 'include_examples': 'y', 'include_audio': 'y',
            'lessons_per_day': '3', 'reading_minutes_per_day': '10',
        }, follow_redirects=False)
        assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:300]
        db_session.expire_all()
        assert db_session.get(User, test_user.id).plan_difficulty == 'intensive'
        assert StudySettings.query.filter_by(user_id=test_user.id).one().reading_minutes_per_day == 10


class TestPlanPayload:
    def test_payload_carries_pace(self, app, db_session):
        from app.daily_plan.plan import get_daily_plan
        user = _user(db_session, 'light')
        with app.test_request_context():
            plan = get_daily_plan(user.id, real_db)
        assert plan['pace']['lessons_per_day'] == 1
        assert plan['pace']['recommended'] is None


class TestMigrationFile:
    def test_chain_and_statements(self):
        from pathlib import Path
        src = Path('migrations/versions/20260906_reading_goal_and_pace.py').read_text(encoding='utf-8')
        assert "down_revision = '20260906_card_grade_events'" in src
        assert "'reading_minutes_per_day'" in src
        assert "UPDATE users SET plan_difficulty = 'light' WHERE plan_difficulty = 'normal'" in src
