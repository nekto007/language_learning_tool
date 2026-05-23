"""Regression tests for Task 3 admin findings (CSRF tokens + audit logging)."""
import uuid

import pytest

from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.utils.db import db


CSRF_INPUT_MARKER = 'name="csrf_token"'


@pytest.mark.smoke
def test_curriculum_edit_templates_carry_csrf_token():
    """Admin curriculum edit templates must include the csrf_token hidden input."""
    template_paths = [
        'app/templates/admin/curriculum/edit_text.html',
        'app/templates/admin/curriculum/edit_quiz.html',
        'app/templates/admin/curriculum/edit_matching.html',
        'app/templates/admin/curriculum/edit_grammar.html',
        'app/templates/admin/curriculum/user_progress.html',
        'app/templates/admin/curriculum/progress_details.html',
        'app/templates/admin/curriculum/edit_module.html',
        'app/templates/admin/curriculum/edit_level.html',
    ]
    for path in template_paths:
        with open(path, encoding='utf-8') as fh:
            contents = fh.read()
        assert 'csrf_token()' in contents, f'csrf_token() missing from {path}'
        assert CSRF_INPUT_MARKER in contents, f'csrf hidden input missing from {path}'


def _make_admin(db_session):
    suffix = uuid.uuid4().hex[:8]
    admin = User(
        username=f'audit_admin_{suffix}',
        email=f'audit_admin_{suffix}@example.com',
        is_admin=True,
        active=True,
    )
    admin.set_password('pass1234')
    db_session.add(admin)
    db_session.flush()
    return admin


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _make_target_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    target = User(
        username=f'audit_target_{suffix}',
        email=f'audit_target_{suffix}@example.com',
        active=True,
    )
    target.set_password('pass1234')
    db_session.add(target)
    db_session.flush()
    return target


class TestUserToggleAuditLog:
    """toggle_user_status / toggle_admin_status / toggle_mission_plan must audit-log."""

    def test_toggle_user_status_logs_action(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        response = client.post(f'/admin/users/{target.id}/toggle_status', follow_redirects=False)
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            target_type='user',
            target_id=target.id,
        ).order_by(AdminAuditLog.id.desc()).first()
        assert entry is not None
        assert entry.action in ('user.activate', 'user.deactivate')

    def test_toggle_admin_status_logs_action(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        response = client.post(f'/admin/users/{target.id}/toggle_admin', follow_redirects=False)
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            target_type='user',
            target_id=target.id,
        ).order_by(AdminAuditLog.id.desc()).first()
        assert entry is not None
        assert entry.action in ('user.grant_admin', 'user.revoke_admin')

    def test_toggle_mission_plan_logs_action(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        response = client.post(f'/admin/users/{target.id}/toggle_mission_plan', follow_redirects=False)
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            target_type='user',
            target_id=target.id,
        ).order_by(AdminAuditLog.id.desc()).first()
        assert entry is not None
        assert entry.action in ('user.enable_mission_plan', 'user.disable_mission_plan')


class TestCurriculumDeleteAuditLog:
    """delete_level / delete_module / delete_lesson / progress reset/delete must audit-log."""

    def test_delete_lesson_logs_action(self, app, client, db_session, test_lesson_vocabulary):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)
        lesson_id = test_lesson_vocabulary.id

        response = client.post(
            f'/admin/curriculum/lessons/{lesson_id}/delete', follow_redirects=False
        )
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            action='curriculum.lesson.delete',
            target_type='lesson',
            target_id=lesson_id,
        ).first()
        assert entry is not None

    def test_reset_progress_logs_action(self, app, client, db_session, test_lesson_progress):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)
        progress_id = test_lesson_progress.id

        response = client.post(
            f'/admin/curriculum/progress/{progress_id}/reset', follow_redirects=False
        )
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            action='curriculum.progress.reset',
            target_type='lesson_progress',
            target_id=progress_id,
        ).first()
        assert entry is not None

    def test_delete_progress_logs_action(self, app, client, db_session, test_lesson_progress):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)
        progress_id = test_lesson_progress.id

        response = client.post(
            f'/admin/curriculum/progress/{progress_id}/delete', follow_redirects=False
        )
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            action='curriculum.progress.delete',
            target_type='lesson_progress',
            target_id=progress_id,
        ).first()
        assert entry is not None
