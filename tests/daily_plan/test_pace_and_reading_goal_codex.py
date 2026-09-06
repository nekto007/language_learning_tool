"""Adversarial settings compatibility and study-day boundaries."""

from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from flask import url_for

from app.auth.models import User
from app.books.reading_session import is_daily_reading_target_met_today
from app.daily_plan.plan_builder import _reading_item_dict
from app.daily_plan.tier import recommend_pace
from app.study.models import StudySettings
from app.utils.db import db
from app.utils.time_utils import study_day_date_for_tz
from tests.daily_plan.test_pace_and_reading_goal import _complete, _lessons, _user


@pytest.mark.parametrize('difficulty', ['light', 'intensive'])
def test_old_settings_form_does_not_reset_pace(app, db_session, client, difficulty):
    user = _user(db_session, difficulty)
    db_session.add(StudySettings(user_id=user.id, reading_minutes_per_day=10))
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    with app.test_request_context():
        url = url_for('study.settings')
    response = client.post(url, data={
        'new_words_per_day': '5', 'reviews_per_day': '20', 'show_hint_time': '10',
        'reading_minutes_per_day': '10',
        'include_translations': 'y', 'include_examples': 'y', 'include_audio': 'y',
    })
    assert response.status_code in (200, 302, 303)
    db_session.expire_all()
    assert db_session.get(User, user.id).plan_difficulty == difficulty
    assert StudySettings.query.filter_by(user_id=user.id).one().reading_minutes_per_day == 10


@pytest.mark.parametrize('tz_name', ['Pacific/Kiritimati', 'America/Los_Angeles'])
def test_recommendation_includes_window_start_but_excludes_today(app, db_session, tz_name):
    user = _user(db_session, 'light')
    lessons = _lessons(db_session, 6)
    today = study_day_date_for_tz(tz_name, now_utc=datetime.now(UTC))

    def instant(day, hour=12):
        return datetime.combine(day, time(hour), ZoneInfo(tz_name)).astimezone(UTC).replace(tzinfo=None)

    # Four unambiguous days plus one exactly on the 02:00 study-day boundary.
    for lesson, days in zip(lessons[:4], [1, 2, 3, 4]):
        _complete(db_session, user, lesson, instant(today - timedelta(days=days)))
    _complete(db_session, user, lessons[4], instant(today - timedelta(days=7), 2))
    _complete(db_session, user, lessons[5], instant(today, 2))
    with patch('app.utils.time_utils.get_user_timezone_name', return_value=tz_name), \
         patch('app.utils.time_utils.get_user_local_date', return_value=today):
        assert recommend_pace(user.id, db) == {'current': 1, 'recommended': 2, 'days_hit': 5}
        progress = lessons[4].lesson_progress[0]
        progress.completed_at -= timedelta(microseconds=1)
        db_session.flush()
        assert recommend_pace(user.id, db) is None


def test_goal_without_book_does_not_create_required_slot(app, db_session):
    user = _user(db_session)
    db_session.add(StudySettings(user_id=user.id, reading_minutes_per_day=15))
    db_session.commit()
    with app.test_request_context():
        assert _reading_item_dict(user.id, db) is None


def test_reading_time_gate_tracks_goal_changes(app, db_session):
    user = _user(db_session)
    settings = StudySettings(user_id=user.id, reading_minutes_per_day=5)
    db_session.add(settings)
    db_session.commit()
    with patch('app.books.reading_session.get_book_reading_seconds_today', return_value=300):
        assert is_daily_reading_target_met_today(user.id, 123, db)
        settings.reading_minutes_per_day = 10
        db_session.flush()
        assert not is_daily_reading_target_met_today(user.id, 123, db)
        settings.reading_minutes_per_day = 0
        db_session.flush()
        assert is_daily_reading_target_met_today(user.id, 123, db)


def test_reading_xp_checks_updated_goal_before_awarding(app, db_session):
    from types import SimpleNamespace
    from app.daily_plan.linear.xp import maybe_award_book_reading_xp

    user = _user(db_session)
    settings = StudySettings(user_id=user.id, reading_minutes_per_day=10)
    db_session.add(settings)
    db_session.commit()
    with patch('app.daily_plan.linear.xp.is_linear_user', return_value=True), \
         patch('app.daily_plan.linear.slots.reading_slot.get_user_reading_preference',
               return_value=SimpleNamespace(book_id=123)), \
         patch('app.books.reading_session.has_min_reading_time_today',
               side_effect=lambda *args, minimum_seconds: 300 >= minimum_seconds), \
         patch('app.daily_plan.linear.xp.award_linear_slot_xp_idempotent') as award:
        assert maybe_award_book_reading_xp(user.id, db_session=db) is None
        award.assert_not_called()
        settings.reading_minutes_per_day = 5
        db_session.flush()
        maybe_award_book_reading_xp(user.id, db_session=db)
        award.assert_called_once()
