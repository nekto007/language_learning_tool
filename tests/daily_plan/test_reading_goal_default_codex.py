"""Atomic first-book defaults and inaccessible-book recovery."""

from datetime import timedelta
from unittest.mock import patch

from app.daily_plan.items.reading import ensure_reading_goal_on_first_book
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.plan_builder import _reading_item_dict
from app.daily_plan.snapshot import overlay_completion
from app.study.models import StudySettings
from app.utils.db import db
from tests.daily_plan.test_reading_goal_default import _book
from tests.daily_plan.test_behind_signal_and_minimum import _now


def test_first_goal_does_not_commit_pending_book_selection(app, db_session, test_user):
    book = _book(db_session)
    assert StudySettings.query.filter_by(user_id=test_user.id).first() is None
    db_session.add(UserReadingPreference(user_id=test_user.id, book_id=book.id))
    with patch.object(db.session, 'commit', wraps=db.session.commit) as commit:
        ensure_reading_goal_on_first_book(test_user.id, db)
    assert commit.call_count == 0, 'Creating settings must not commit the pending book preference'


def test_settings_failure_is_handled_by_select_transaction(app, db_session, test_user, authenticated_client):
    book = _book(db_session)
    with patch('app.daily_plan.items.reading.ensure_reading_goal_on_first_book',
               side_effect=RuntimeError('injected settings failure')):
        response = authenticated_client.post('/api/books/select', json={'book_id': book.id})
    assert response.status_code == 500
    assert response.is_json
    assert UserReadingPreference.query.filter_by(user_id=test_user.id).first() is None


def test_access_loss_drops_required_reading_despite_positive_goal(app, db_session, test_user):
    book = _book(db_session)
    db_session.add(StudySettings(user_id=test_user.id, reading_minutes_per_day=5))
    db_session.add(UserReadingPreference(user_id=test_user.id, book_id=book.id,
                                        selected_at=_now() - timedelta(days=2)))
    db_session.commit()
    with app.test_request_context():
        item = _reading_item_dict(test_user.id, db)
    assert item is not None
    with app.test_request_context(), \
         patch('app.daily_plan.items.reading.book_access_ok_for_reading', return_value=False):
        assert _reading_item_dict(test_user.id, db) is None
        assert overlay_completion(test_user.id, {'items': [item]}, db) == []
