"""A whole book finished today satisfies reading without inventing timer time."""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from flask_jwt_extended import create_access_token
from freezegun import freeze_time
import pytest

from app.achievements.models import StreakEvent
from app.achievements.xp_service import BOOK_CHAPTER_XP_EVENT_TYPE
from app.books.models import Book, Chapter, UserChapterProgress
from app.books.progress import get_book_completion_state
from app.books.reading_session import (
    UserReadingSession,
    get_book_reading_seconds_today,
    is_daily_reading_target_met_today,
    was_book_completed_today,
)
from app.daily_plan.items.reading import _read_today, build_reading_item
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.slots.reading_slot import build_reading_slot
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, maybe_award_book_reading_xp
from app.daily_plan.snapshot import overlay_completion
from app.study.models import StudySettings
from app.utils.db import db
from app.utils.time_utils import get_user_local_date


@pytest.fixture(autouse=True)
def stable_time():
    with freeze_time('2026-11-22 12:00:00+00:00'):
        yield


@pytest.fixture
def reading_case(db_session, test_user, test_book, test_chapter):
    assert db.engine.dialect.name == 'postgresql', 'This suite requires a guarded disposable PostgreSQL database'
    db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
    db_session.add(StudySettings(user_id=test_user.id, reading_minutes_per_day=30))
    db_session.commit()
    return SimpleNamespace(user=test_user, book=test_book, chapter=test_chapter)


def headers(user):
    token = create_access_token(identity=str(user.id), additional_claims={'auth_version': user.auth_version()})
    return {'Authorization': 'Bearer ' + token}


def finish_native(client, case, chapter=None, offset=1.0):
    chapter = chapter or case.chapter
    response = client.patch('/api/native/reading/progress', headers=headers(case.user), json={
        'book_id': case.book.id, 'chapter_id': chapter.id, 'offset_pct': offset,
    })
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def reading_awards(user_id):
    return StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.details['source'].astext == 'linear_book_reading',
    ).all()


@pytest.mark.parametrize('transport', ['native_progress', 'web_progress', 'legacy_position', 'native_end'])
def test_final_short_book_credits_today_without_a_time_goal_and_only_once(
    app, authenticated_client, reading_case, transport,
):
    case = reading_case
    native = app.test_client()
    if transport == 'native_progress':
        body = finish_native(native, case)
    elif transport == 'web_progress':
        response = authenticated_client.patch('/api/progress', json={
            'book_id': case.book.id, 'chapter_id': case.chapter.id, 'offset_pct': 1.0,
        })
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
    elif transport == 'legacy_position':
        response = authenticated_client.post('/api/save-reading-position', json={
            'book_id': case.book.id, 'chapter': case.chapter.chap_num, 'position': 1.0,
        })
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
    else:
        response = native.post('/api/native/reading/start', headers=headers(case.user),
                               json={'chapter_id': case.chapter.id})
        assert response.status_code == 200, response.get_json()
        response = native.post('/api/native/reading/end', headers=headers(case.user), json={
            'session_id': response.get_json()['session_id'], 'current_offset_pct': 1.0,
        })
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body['daily_target_met'] is True

    assert body['book_completed'] is True
    assert get_book_completion_state(case.user.id, case.book.id, db)['is_completed'] is True
    assert get_book_reading_seconds_today(case.user.id, case.book.id, db) == 0
    assert was_book_completed_today(case.user.id, case.book.id, db) is True
    assert is_daily_reading_target_met_today(case.user.id, case.book.id, db) is True
    assert len(reading_awards(case.user.id)) == 1
    assert reading_awards(case.user.id)[0].details['book_id'] == case.book.id

    # Replaying completion and the corrective XP entrypoint must not pay again.
    finish_native(native, case)
    assert maybe_award_book_reading_xp(case.user.id, db_session=db) is None
    db.session.commit()
    assert len(reading_awards(case.user.id)) == 1
    assert StreakEvent.query.filter_by(user_id=case.user.id, event_type=BOOK_CHAPTER_XP_EVENT_TYPE).count() == 1
    assert get_book_reading_seconds_today(case.user.id, case.book.id, db) == 0
    if transport != 'native_end':
        assert UserReadingSession.query.filter_by(user_id=case.user.id).count() == 0


def test_finished_today_card_survives_snapshot_and_fresh_builders(app, reading_case):
    case = reading_case
    finish_native(app.test_client(), case)
    item = build_reading_item(case.user.id, db)
    assert item is not None and item.completed is True
    assert item.data['gate_reached'] is True
    assert item.data['time_spent_seconds'] == 0
    assert item.data['gate_seconds'] == 1800
    legacy = build_reading_slot(case.user.id, db)
    assert legacy.completed is True and legacy.data['gate_reached'] is True

    frozen_item = item.to_dict()
    frozen_item['completed'] = False
    result = overlay_completion(case.user.id, {'items': [frozen_item]}, db)
    assert len(result) == 1
    assert result[0]['completed'] is True
    assert result[0]['eta_minutes'] == 0 and result[0]['url'] is None
    assert result[0]['data']['time_spent_seconds'] == 0
    assert result[0]['data']['gate_reached'] is True


def test_one_finished_chapter_is_not_the_whole_book(app, db_session, reading_case):
    case = reading_case
    next_chapter = Chapter(book_id=case.book.id, chap_num=2, words=20, title='Last', text_raw='Another short page.')
    db_session.add(next_chapter)
    case.book.chapters_cnt = 2
    db_session.commit()
    first = finish_native(app.test_client(), case)
    assert first['book_completed'] is False
    assert was_book_completed_today(case.user.id, case.book.id, db) is False
    assert is_daily_reading_target_met_today(case.user.id, case.book.id, db) is False
    assert reading_awards(case.user.id) == []
    last = finish_native(app.test_client(), case, chapter=next_chapter)
    assert last['book_completed'] is True
    assert len(reading_awards(case.user.id)) == 1


def test_reopening_yesterdays_finished_book_does_not_credit_today(app, reading_case):
    case = reading_case
    with freeze_time('2026-11-21 12:00:00+00:00'):
        finish_native(app.test_client(), case)
        assert was_book_completed_today(case.user.id, case.book.id, db) is True
    finish_native(app.test_client(), case)
    assert get_book_completion_state(case.user.id, case.book.id, db)['is_completed'] is True
    assert was_book_completed_today(case.user.id, case.book.id, db) is False
    assert is_daily_reading_target_met_today(case.user.id, case.book.id, db) is False
    assert _read_today(case.user.id, case.book.id, db) is False
    assert maybe_award_book_reading_xp(case.user.id, db_session=db) is None
    assert build_reading_item(case.user.id, db) is None
    frozen = {'kind': 'reading', 'data': {'book_id': case.book.id}}
    assert overlay_completion(case.user.id, {'items': [frozen]}, db) == []
    assert len(reading_awards(case.user.id)) == 1  # Yesterday's award remains untouched.


@pytest.mark.parametrize('foreign_scope', ['other_book', 'other_user'])
def test_other_book_or_other_user_ledger_cannot_supply_completion_today(db_session, reading_case, foreign_scope):
    case = reading_case
    db_session.add(UserChapterProgress(user_id=case.user.id, chapter_id=case.chapter.id, offset_pct=1.0))
    event_user, event_book, event_chapter = case.user.id, case.book.id, case.chapter.id
    if foreign_scope == 'other_book':
        other_book = Book(title='Another book', author='Synthetic', chapters_cnt=1, is_published=True, rights_status='public_domain')
        db_session.add(other_book)
        db_session.flush()
        other_chapter = Chapter(book_id=other_book.id, chap_num=1, title='Other', words=1, text_raw='Other.')
        db_session.add(other_chapter)
        db_session.flush()
        event_book, event_chapter = other_book.id, other_chapter.id
    else:
        from app.auth.models import User
        key = 'reading_other_' + uuid4().hex[:10]
        other = User(username=key, email=key + '@example.invalid', active=True)
        other.set_password('synthetic-local-test-password')
        db_session.add(other)
        db_session.flush()
        event_user = other.id
    db_session.add(StreakEvent(user_id=event_user, event_type=BOOK_CHAPTER_XP_EVENT_TYPE,
                              event_date=get_user_local_date(case.user.id, db), coins_delta=0,
                              details={'book_id': event_book, 'chapter_id': event_chapter, 'xp': 50}))
    db_session.commit()
    assert was_book_completed_today(case.user.id, case.book.id, db) is False


def test_finished_book_is_scoped_when_selected_book_changes(app, db_session, reading_case):
    case = reading_case
    finish_native(app.test_client(), case)
    next_book = Book(title='Next selected book', author='Synthetic', chapters_cnt=1, is_published=True, rights_status='public_domain')
    db_session.add(next_book)
    db_session.flush()
    next_chapter = Chapter(book_id=next_book.id, chap_num=1, words=20, title='Start', text_raw='A new story.')
    db_session.add(next_chapter)
    preference = UserReadingPreference.query.filter_by(user_id=case.user.id).one()
    preference.book_id = next_book.id
    db_session.commit()
    assert _read_today(case.user.id, case.book.id, db) is True
    assert _read_today(case.user.id, next_book.id, db) is False
    assert maybe_award_book_reading_xp(case.user.id, db_session=db) is None
    assert build_reading_item(case.user.id, db).completed is False
    assert len(reading_awards(case.user.id)) == 1


def test_completion_ledger_uses_user_local_study_day(app, db_session, reading_case):
    case = reading_case
    case.user.timezone = 'Pacific/Auckland'
    db_session.commit()
    with freeze_time('2026-11-22 14:00:00+00:00'):
        assert get_user_local_date(case.user.id, db) == date(2026, 11, 23)
        finish_native(app.test_client(), case)
        assert was_book_completed_today(case.user.id, case.book.id, db) is True
        award = reading_awards(case.user.id)[0]
        assert award.event_date == date(2026, 11, 23)
