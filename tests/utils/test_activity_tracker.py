"""Tests for app.utils.activity_tracker.has_learning_activity."""
from datetime import datetime, timedelta, timezone

import pytest

from app.utils.activity_tracker import has_learning_activity


@pytest.fixture
def today_window():
    """Naive UTC window covering 'today'."""
    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def test_no_activity_returns_false(db_session, test_user, today_window):
    start, end = today_window
    assert has_learning_activity(test_user.id, start, end) is False


def test_study_session_only_returns_true(db_session, test_user, today_window):
    """Plan-mandated case: user with only StudySession activity is counted."""
    from app.study.models import StudySession

    start, end = today_window
    session = StudySession(
        user_id=test_user.id,
        session_type='cards',
        start_time=start + timedelta(hours=2),
    )
    db_session.add(session)
    db_session.commit()

    assert has_learning_activity(test_user.id, start, end) is True


def test_book_chapter_progress_counts(db_session, test_user, today_window):
    """Book reading via UserChapterProgress (composite PK)."""
    from app.books.models import Book, Chapter, UserChapterProgress

    start, end = today_window
    book = Book(title='T', author='A', chapters_cnt=1, level='A1')
    db_session.add(book)
    db_session.flush()
    chapter = Chapter(book_id=book.id, chap_num=1, title='C1',
                      words=100, text_raw='hello')
    db_session.add(chapter)
    db_session.flush()
    progress = UserChapterProgress(
        user_id=test_user.id,
        chapter_id=chapter.id,
        offset_pct=0.5,
        updated_at=start + timedelta(hours=2),
    )
    db_session.add(progress)
    db_session.commit()

    assert has_learning_activity(test_user.id, start, end) is True


def test_aware_boundaries_accepted(db_session, test_user, today_window):
    from app.study.models import StudySession

    start, end = today_window
    session = StudySession(
        user_id=test_user.id,
        session_type='cards',
        start_time=start + timedelta(hours=1),
    )
    db_session.add(session)
    db_session.commit()

    aware_start = start.replace(tzinfo=timezone.utc)
    aware_end = end.replace(tzinfo=timezone.utc)
    assert has_learning_activity(test_user.id, aware_start, aware_end) is True


def test_activity_outside_window_excluded(db_session, test_user, today_window):
    from app.study.models import StudySession

    start, end = today_window
    yesterday = StudySession(
        user_id=test_user.id,
        session_type='cards',
        start_time=start - timedelta(hours=1),
    )
    tomorrow = StudySession(
        user_id=test_user.id,
        session_type='cards',
        start_time=end + timedelta(minutes=1),
    )
    db_session.add_all([yesterday, tomorrow])
    db_session.commit()

    assert has_learning_activity(test_user.id, start, end) is False


def test_boundary_inclusive_start_exclusive_end(db_session, test_user, today_window):
    """Activity exactly at start counts; exactly at end does not."""
    from app.study.models import StudySession

    start, end = today_window
    at_start = StudySession(
        user_id=test_user.id, session_type='cards', start_time=start,
    )
    db_session.add(at_start)
    db_session.commit()
    assert has_learning_activity(test_user.id, start, end) is True

    db_session.delete(at_start)
    db_session.commit()

    at_end = StudySession(
        user_id=test_user.id, session_type='cards', start_time=end,
    )
    db_session.add(at_end)
    db_session.commit()
    assert has_learning_activity(test_user.id, start, end) is False


def test_xp_linear_streak_event_counts(db_session, test_user, today_window):
    """Linear-only user with xp_linear StreakEvent registers as active."""
    from datetime import date as _date
    from app.achievements.models import StreakEvent

    start, end = today_window
    event = StreakEvent(
        user_id=test_user.id,
        event_type='xp_linear',
        event_date=_date.today(),
        details={'source': 'linear_curriculum_card'},
        created_at=start + timedelta(hours=3),
    )
    db_session.add(event)
    db_session.commit()

    assert has_learning_activity(test_user.id, start, end) is True


def test_xp_linear_outside_window_excluded(db_session, test_user, today_window):
    from datetime import date as _date, timedelta as _td
    from app.achievements.models import StreakEvent

    start, end = today_window
    yesterday_event = StreakEvent(
        user_id=test_user.id,
        event_type='xp_linear',
        event_date=_date.today() - _td(days=1),
        details={'source': 'linear_curriculum_card'},
        created_at=start - timedelta(hours=2),
    )
    db_session.add(yesterday_event)
    db_session.commit()

    assert has_learning_activity(test_user.id, start, end) is False


def test_non_linear_streak_event_ignored(db_session, test_user, today_window):
    """Only event_type starting with 'xp_linear' counts; other events do not."""
    from datetime import date as _date
    from app.achievements.models import StreakEvent

    start, end = today_window
    other = StreakEvent(
        user_id=test_user.id,
        event_type='xp_curriculum_lesson',
        event_date=_date.today(),
        details={'lesson_id': 1},
        created_at=start + timedelta(hours=4),
    )
    db_session.add(other)
    db_session.commit()

    assert has_learning_activity(test_user.id, start, end) is False


def test_telegram_has_activity_today_delegates(db_session, test_user, monkeypatch):
    """telegram.queries.has_activity_today must delegate to canonical helper."""
    import app.utils.activity_tracker as tracker
    from app.telegram import queries as q

    calls = {'count': 0}
    real = tracker.has_learning_activity

    def fake(user_id, start, end, db_session=None):
        calls['count'] += 1
        return real(user_id, start, end, db_session=db_session)

    monkeypatch.setattr(tracker, 'has_learning_activity', fake)

    q.has_activity_today(test_user.id)
    assert calls['count'] == 1


def test_telegram_has_activity_in_range_delegates(db_session, test_user, monkeypatch):
    import app.utils.activity_tracker as tracker
    from app.telegram import queries as q

    calls = {'count': 0}
    real = tracker.has_learning_activity

    def fake(user_id, start, end, db_session=None):
        calls['count'] += 1
        return real(user_id, start, end, db_session=db_session)

    monkeypatch.setattr(tracker, 'has_learning_activity', fake)

    now = datetime.utcnow()
    q._has_activity_in_range(test_user.id, now - timedelta(hours=1), now)
    assert calls['count'] == 1
