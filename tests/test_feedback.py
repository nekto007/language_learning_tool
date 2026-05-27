"""Smoke tests for the in-app feedback channel."""

import pytest

from app.feedback.models import Feedback


pytestmark = pytest.mark.smoke


class TestFeedbackApi:
    def test_post_creates_feedback(self, authenticated_client, test_user, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={'category': 'bug', 'message': 'Кнопка не работает'},
        )
        assert resp.status_code == 201, resp.data
        body = resp.get_json()
        assert body['success'] is True
        assert isinstance(body['id'], int)

        row = Feedback.query.get(body['id'])
        assert row is not None
        assert row.user_id == test_user.id
        assert row.category == 'bug'
        assert row.message == 'Кнопка не работает'
        assert row.status == 'new'

    def test_post_rejects_invalid_category(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={'category': 'spam', 'message': 'hi'},
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_category'

    def test_post_rejects_empty_message(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={'category': 'idea', 'message': '   '},
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'empty_message'

    def test_post_truncates_long_message(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={'category': 'idea', 'message': 'x' * 5000},
        )
        assert resp.status_code == 201
        row = Feedback.query.get(resp.get_json()['id'])
        assert len(row.message) == 4000

    def test_post_requires_login(self, client, db_session):
        resp = client.post(
            '/api/feedback',
            json={'category': 'bug', 'message': 'hi'},
        )
        # login_required redirects to /login (302) or returns 401 for AJAX —
        # both are valid auth-required responses; just assert it's NOT 201.
        assert resp.status_code in (302, 401)

    def test_post_notifies_every_admin(self, authenticated_client, db_session):
        """Each new feedback submission stages an in-app notification per admin."""
        import uuid
        from app.auth.models import User
        from app.notifications.models import Notification

        admin_a = User(
            username=f'fb_admin_a_{uuid.uuid4().hex[:8]}',
            email=f'fb_admin_a_{uuid.uuid4().hex[:8]}@example.com',
            active=True, is_admin=True,
        )
        admin_a.set_password('p')
        admin_b = User(
            username=f'fb_admin_b_{uuid.uuid4().hex[:8]}',
            email=f'fb_admin_b_{uuid.uuid4().hex[:8]}@example.com',
            active=True, is_admin=True,
        )
        admin_b.set_password('p')
        db_session.add_all([admin_a, admin_b])
        db_session.commit()

        resp = authenticated_client.post(
            '/api/feedback',
            json={'category': 'bug', 'message': 'админам должно прийти'},
        )
        assert resp.status_code == 201

        for admin in (admin_a, admin_b):
            n = Notification.query.filter_by(
                user_id=admin.id, type='feedback'
            ).order_by(Notification.id.desc()).first()
            assert n is not None
            assert n.link == '/admin/feedback'
            assert 'админам' in n.message


class TestFeedbackAdmin:
    def test_admin_index_lists_entries(self, client, admin_user, db_session):
        db_session.add(Feedback(
            user_id=admin_user.id, category='bug', message='m1', status='new',
        ))
        db_session.add(Feedback(
            user_id=admin_user.id, category='idea', message='m2', status='resolved',
        ))
        db_session.commit()

        resp = client.get('/admin/feedback')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'm1' in body
        assert 'm2' in body

    def test_admin_set_status(self, client, admin_user, db_session):
        row = Feedback(
            user_id=admin_user.id, category='bug', message='to triage', status='new',
        )
        db_session.add(row)
        db_session.commit()
        fid = row.id

        resp = client.post(
            f'/admin/feedback/{fid}/status',
            data={'status': 'seen'},
            follow_redirects=False,
        )
        assert resp.status_code == 302

        db_session.expire_all()
        assert Feedback.query.get(fid).status == 'seen'

    def test_admin_rejects_unknown_status(self, client, admin_user, db_session):
        row = Feedback(
            user_id=admin_user.id, category='bug', message='x', status='new',
        )
        db_session.add(row)
        db_session.commit()

        resp = client.post(
            f'/admin/feedback/{row.id}/status',
            data={'status': 'spam'},
        )
        assert resp.status_code == 400
