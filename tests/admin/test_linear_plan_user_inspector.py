"""Tests for the per-user linear plan admin inspector page."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.achievements.models import StreakEvent
from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.daily_plan.linear.models import QuizErrorLog


def _make_user(db_session, *, linear: bool = True) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"insp_{suffix}",
        email=f"insp_{suffix}@example.com",
        active=True,
        onboarding_completed=True,
        use_linear_plan=linear,
    )
    user.set_password("pw")
    db_session.add(user)
    db_session.commit()
    return user


class TestLinearPlanInspectorAuth:
    def test_anonymous_redirects_to_login(self, client, db_session):
        user = _make_user(db_session)
        response = client.get(f'/admin/linear-plan/{user.id}', follow_redirects=False)
        # admin_required redirects unauthenticated to login.
        assert response.status_code in (301, 302)

    def test_non_admin_redirects(self, app, client, test_user, db_session):
        # test_user is not admin in conftest defaults; admin_required redirects.
        target = _make_user(db_session)
        from flask_login import login_user
        with app.test_request_context():
            login_user(test_user)
            with client.session_transaction() as sess:
                sess['_user_id'] = str(test_user.id)
                sess['_fresh'] = True
        response = client.get(f'/admin/linear-plan/{target.id}', follow_redirects=False)
        assert response.status_code in (301, 302)


class TestLinearPlanInspectorRender:
    @pytest.mark.smoke
    def test_admin_can_open_for_linear_user(self, app, admin_client, db_session):
        user = _make_user(db_session, linear=True)
        response = admin_client.get(f'/admin/linear-plan/{user.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'Linear Plan Inspector' in body
        assert user.username in body

    def test_admin_view_for_disabled_user_shows_notice(self, app, admin_client, db_session):
        user = _make_user(db_session, linear=False)
        response = admin_client.get(f'/admin/linear-plan/{user.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'linear-disabled-notice' in body

    def test_missing_user_redirects(self, app, admin_client):
        response = admin_client.get('/admin/linear-plan/999999')
        assert response.status_code in (301, 302)

    def test_renders_recent_xp_events(self, app, admin_client, db_session):
        user = _make_user(db_session, linear=True)
        db_session.add(
            StreakEvent(
                user_id=user.id,
                event_type='xp_linear',
                event_date=date.today(),
                coins_delta=0,
                details={'source': 'linear_book_reading', 'xp': 15},
            )
        )
        db_session.commit()

        response = admin_client.get(f'/admin/linear-plan/{user.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'linear_book_reading' in body

    def test_renders_recent_quiz_errors(self, app, admin_client, db_session, test_lesson_quiz):
        user = _make_user(db_session, linear=True)
        db_session.add(
            QuizErrorLog(
                user_id=user.id,
                lesson_id=test_lesson_quiz.id,
                question_payload={'q': 'x'},
            )
        )
        db_session.commit()

        response = admin_client.get(f'/admin/linear-plan/{user.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'quiz-error-rows' in body

    def test_audit_log_written_on_access(self, app, admin_client, db_session):
        user = _make_user(db_session, linear=True)
        before = db_session.query(AdminAuditLog).filter_by(
            action='user.linear_plan_inspect', target_id=user.id
        ).count()
        response = admin_client.get(f'/admin/linear-plan/{user.id}')
        assert response.status_code == 200
        after = db_session.query(AdminAuditLog).filter_by(
            action='user.linear_plan_inspect', target_id=user.id
        ).count()
        assert after == before + 1
