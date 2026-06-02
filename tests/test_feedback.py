"""Smoke tests for the in-app feedback channel."""

import io

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

    def test_post_defaults_priority_to_normal(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={'category': 'question', 'message': 'как работает повторение?'},
        )
        assert resp.status_code == 201
        row = Feedback.query.get(resp.get_json()['id'])
        assert row.priority == 'normal'

    def test_post_marks_urgent_as_high_priority(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={'category': 'bug', 'message': 'не могу продолжить урок', 'urgent': '1'},
        )
        assert resp.status_code == 201
        row = Feedback.query.get(resp.get_json()['id'])
        assert row.priority == 'high'

    def test_post_reports_rejected_screenshot(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            data={
                'category': 'bug',
                'message': 'скрин не должен пройти',
                'screenshot': (io.BytesIO(b'<?php echo "x"; ?>'), 'bad.php'),
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['screenshot_status'] == 'rejected'
        assert body['screenshot_reject_reason'] == 'malicious_content'

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
        fid = resp.get_json()['id']

        for admin in (admin_a, admin_b):
            n = Notification.query.filter_by(
                user_id=admin.id, type='feedback'
            ).order_by(Notification.id.desc()).first()
            assert n is not None
            assert n.link == f'/admin/feedback/{fid}'
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

    def test_admin_triage_sets_priority_and_assignee(self, client, admin_user, db_session):
        row = Feedback(
            user_id=admin_user.id, category='bug', message='critical issue', status='new',
        )
        db_session.add(row)
        db_session.commit()

        resp = client.post(
            f'/admin/feedback/{row.id}/triage',
            data={'priority': 'critical', 'assignee_admin_id': str(admin_user.id)},
            follow_redirects=False,
        )
        assert resp.status_code == 302

        db_session.expire_all()
        updated = Feedback.query.get(row.id)
        assert updated.priority == 'critical'
        assert updated.assignee_admin_id == admin_user.id

    def test_admin_filter_search_finds_feedback_by_url(self, client, admin_user, db_session):
        db_session.add(Feedback(
            user_id=admin_user.id,
            category='bug',
            message='visible text',
            url='https://example.test/special-lesson',
            status='new',
        ))
        db_session.add(Feedback(
            user_id=admin_user.id,
            category='idea',
            message='other text',
            url='https://example.test/other',
            status='new',
        ))
        db_session.commit()

        resp = client.get('/admin/feedback?q=special-lesson')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'visible text' in body
        assert 'other text' not in body


class TestFeedbackReplies:
    def test_user_reply_to_resolved_thread_reopens_it(self, authenticated_client, test_user, db_session):
        row = Feedback(
            user_id=test_user.id,
            category='bug',
            message='still broken',
            status='resolved',
        )
        db_session.add(row)
        db_session.commit()

        resp = authenticated_client.post(
            f'/api/feedback/{row.id}/reply',
            json={'body': 'Проблема всё ещё воспроизводится'},
        )
        assert resp.status_code == 201

        db_session.expire_all()
        updated = Feedback.query.get(row.id)
        assert updated.status == 'reopened'
        assert updated.reopened_at is not None

    def test_reply_acl_403_when_not_owner(self, app, client, test_user, second_user, db_session):
        from flask_login import login_user

        row = Feedback(
            user_id=test_user.id,
            category='bug',
            message='private thread',
            status='new',
        )
        db_session.add(row)
        db_session.commit()

        with app.test_request_context():
            login_user(second_user)
            with client.session_transaction() as session:
                session['_user_id'] = str(second_user.id)
                session['_fresh'] = True
                session['user_id'] = second_user.id

        resp = client.post(
            f'/api/feedback/{row.id}/reply',
            json={'body': 'чужой ответ'},
        )
        assert resp.status_code == 403

    def test_admin_reply_does_not_demote_resolved(self, client, admin_user, test_user, db_session):
        row = Feedback(
            user_id=test_user.id,
            category='question',
            message='already resolved',
            status='resolved',
        )
        db_session.add(row)
        db_session.commit()

        resp = client.post(
            f'/admin/feedback/{row.id}/reply',
            data={'body': 'финальное уточнение'},
            follow_redirects=False,
        )
        assert resp.status_code == 302

        db_session.expire_all()
        assert Feedback.query.get(row.id).status == 'resolved'

    def test_thread_list_api_owner_only(self, authenticated_client, test_user, second_user, db_session):
        own = Feedback(user_id=test_user.id, category='bug', message='mine', status='new')
        other = Feedback(user_id=second_user.id, category='bug', message='not mine', status='new')
        db_session.add_all([own, other])
        db_session.commit()

        resp = authenticated_client.get('/api/feedback/threads?limit=10')
        assert resp.status_code == 200
        ids = {item['id'] for item in resp.get_json()['threads']}
        assert own.id in ids
        assert other.id not in ids

    def test_thread_view_clears_unread_notifications(
        self, authenticated_client, test_user, db_session
    ):
        from app.notifications.models import Notification

        row = Feedback(
            user_id=test_user.id,
            category='question',
            message='needs reply',
            status='in_progress',
        )
        db_session.add(row)
        db_session.flush()
        link = f'/feedback/{row.id}'
        note = Notification(
            user_id=test_user.id,
            type='feedback',
            title='Ответ',
            message='Команда ответила',
            link=link,
            read=False,
        )
        db_session.add(note)
        db_session.commit()

        count_resp = authenticated_client.get('/api/feedback/unread-count')
        assert count_resp.get_json()['count'] == 1

        resp = authenticated_client.get(link)
        assert resp.status_code == 200

        db_session.expire_all()
        assert Notification.query.get(note.id).read is True


class TestFeedbackScreenshotUpload:
    """Validation surface for the screenshot attachment path."""

    def _png_bytes(self) -> bytes:
        # Smallest valid PNG (8×8 transparent) — enough to satisfy Pillow.
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGBA', (8, 8), (0, 0, 0, 0)).save(buf, format='PNG')
        return buf.getvalue()

    def test_valid_png_attaches_and_reports_status(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            data={
                'category': 'bug',
                'message': 'cards animate weird',
                'screenshot': (io.BytesIO(self._png_bytes()), 'shot.png'),
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 201, resp.data
        body = resp.get_json()
        assert body['screenshot_status'] == 'attached'
        assert body['screenshot_message'] is None
        row = Feedback.query.get(body['id'])
        assert row.screenshot_path is not None
        assert row.screenshot_path.startswith('feedback/')

    def test_rejects_dangerous_magic_bytes(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            data={
                'category': 'bug',
                'message': 'tried to slip a php shell',
                'screenshot': (io.BytesIO(b'<?php echo "x"; ?>'), 'evil.png'),
            },
            content_type='multipart/form-data',
        )
        # Feedback still saves — screenshot was just dropped.
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['screenshot_status'] == 'rejected'
        assert body['screenshot_reject_reason'] == 'malicious_content'
        assert Feedback.query.get(body['id']).screenshot_path is None

    def test_rejects_unsupported_format_with_human_reason(
        self, authenticated_client, db_session
    ):
        # Random bytes — Pillow will fail to identify any image format.
        resp = authenticated_client.post(
            '/api/feedback',
            data={
                'category': 'bug',
                'message': 'not really an image',
                'screenshot': (io.BytesIO(b'not-an-image-' * 20), 'fake.png'),
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['screenshot_status'] == 'rejected'
        # Either process_failed (Pillow refused to open) or unsupported_format —
        # both are acceptable end-states; the user sees a human message either way.
        assert body['screenshot_reject_reason'] in {'process_failed', 'unsupported_format'}
        assert body['screenshot_message']


class TestFeedbackScreenshotServe:
    """ACL surface for serving stored screenshots."""

    def _attach_png(self, authenticated_client) -> int:
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (4, 4), (255, 0, 0)).save(buf, format='PNG')
        resp = authenticated_client.post(
            '/api/feedback',
            data={
                'category': 'bug',
                'message': 'with screenshot',
                'screenshot': (io.BytesIO(buf.getvalue()), 'shot.png'),
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 201
        return resp.get_json()['id']

    def test_owner_can_view_own_screenshot(self, authenticated_client, db_session):
        fid = self._attach_png(authenticated_client)
        row = Feedback.query.get(fid)
        rel = row.screenshot_path.replace('feedback/', '', 1)
        resp = authenticated_client.get(f'/feedback/screenshots/{rel}')
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/')

    def test_stranger_gets_403(self, app, authenticated_client, second_user, db_session):
        from flask_login import login_user

        fid = self._attach_png(authenticated_client)
        row = Feedback.query.get(fid)
        rel = row.screenshot_path.replace('feedback/', '', 1)

        client = app.test_client()
        with app.test_request_context():
            login_user(second_user)
            with client.session_transaction() as session:
                session['_user_id'] = str(second_user.id)
                session['_fresh'] = True
                session['user_id'] = second_user.id

        resp = client.get(f'/feedback/screenshots/{rel}')
        assert resp.status_code == 403

    def test_traversal_attempt_returns_404(self, authenticated_client, db_session):
        resp = authenticated_client.get('/feedback/screenshots/..%2F..%2Fetc%2Fpasswd')
        assert resp.status_code in (400, 403, 404)


class TestFeedbackAutoContext:
    """Server-side URL parsing + client context blob handling."""

    def test_lesson_id_extracted_from_url(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={
                'category': 'bug',
                'message': 'audio not playing',
                'url': 'https://llt-english.com/learn/12345/?from=linear_plan',
            },
        )
        assert resp.status_code == 201
        row = Feedback.query.get(resp.get_json()['id'])
        assert row.lesson_id == 12345

    def test_book_id_extracted_from_read_url(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            '/api/feedback',
            json={
                'category': 'idea',
                'message': 'add font-size toggle',
                'url': 'https://llt-english.com/read/42',
            },
        )
        assert resp.status_code == 201
        row = Feedback.query.get(resp.get_json()['id'])
        assert row.book_id == 42

    def test_context_json_persisted_when_small(self, authenticated_client, db_session):
        import json as _json
        resp = authenticated_client.post(
            '/api/feedback',
            data={
                'category': 'bug',
                'message': 'crashed',
                'context': _json.dumps({
                    'client_errors': [{'message': 'boom', 'at': '2026-01-01'}],
                    'path': '/dashboard',
                }),
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 201
        row = Feedback.query.get(resp.get_json()['id'])
        assert row.context_json is not None
        assert row.context_json.get('path') == '/dashboard'

    def test_context_json_rejected_when_oversize(self, authenticated_client, db_session):
        # 9 KiB blob — over the 8 KiB cap.
        import json as _json
        huge = {'x': 'y' * (9 * 1024)}
        resp = authenticated_client.post(
            '/api/feedback',
            data={
                'category': 'idea',
                'message': 'with oversized context',
                'context': _json.dumps(huge),
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code == 201
        row = Feedback.query.get(resp.get_json()['id'])
        # Oversize context is silently dropped — feedback itself still saves.
        assert row.context_json is None


class TestFeedbackUnreadCount:
    def test_only_unread_feedback_notifications_counted(
        self, authenticated_client, test_user, db_session
    ):
        from app.notifications.models import Notification

        # Mix of read/unread + different types so the count must filter both.
        for read, ntype in (
            (False, 'feedback'),
            (False, 'feedback'),
            (True, 'feedback'),
            (False, 'achievement'),
        ):
            db_session.add(Notification(
                user_id=test_user.id, type=ntype,
                title='x', message='y', link='/feedback/1',
                read=read,
            ))
        db_session.commit()

        resp = authenticated_client.get('/api/feedback/unread-count')
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 2
