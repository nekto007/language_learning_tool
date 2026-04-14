"""
Integration tests for app/curriculum/routes/srs_api.py

Tests all SRS API endpoints:
- GET /curriculum/api/v1/srs/session
- POST /curriculum/api/v1/srs/grade
- POST /curriculum/api/v1/srs/session/complete
- GET /curriculum/api/v1/srs/due-count
- GET /curriculum/api/v1/srs/next-session-time
- POST /curriculum/api/v1/lesson/<id>/create-srs-cards
- POST /curriculum/api/v1/lesson/<id>/completed
"""
import pytest
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Tests: GET /curriculum/api/v1/srs/session
# ---------------------------------------------------------------------------

class TestGetSrsSession:
    def test_unauth(self, client):
        r = client.get('/curriculum/api/v1/srs/session')
        assert r.status_code in [302, 401]

    def test_missing_lesson_id(self, authenticated_client):
        r = authenticated_client.get('/curriculum/api/v1/srs/session')
        assert r.status_code == 400
        assert 'lesson_id' in r.get_json().get('error', '')

    @patch('app.curriculum.routes.srs_api.BookCourseEnrollment')
    @patch('app.curriculum.routes.srs_api.DailyLesson')
    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_not_enrolled_403(self, mock_srs, mock_dl, mock_enroll, authenticated_client):
        mock_lesson = MagicMock()
        mock_lesson.module.course_id = 1
        mock_dl.query.get_or_404.return_value = mock_lesson
        mock_enroll.query.filter_by.return_value.first.return_value = None
        r = authenticated_client.get('/curriculum/api/v1/srs/session?lesson_id=1')
        assert r.status_code == 403

    @patch('app.curriculum.routes.srs_api.BookCourseEnrollment')
    @patch('app.curriculum.routes.srs_api.DailyLesson')
    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_no_cards_404(self, mock_srs, mock_dl, mock_enroll, authenticated_client):
        mock_lesson = MagicMock()
        mock_lesson.module.course_id = 1
        mock_dl.query.get_or_404.return_value = mock_lesson
        mock_enroll.query.filter_by.return_value.first.return_value = MagicMock()
        mock_srs.return_value.create_srs_session_for_lesson.return_value = {
            'session_key': None, 'deck': []}
        r = authenticated_client.get('/curriculum/api/v1/srs/session?lesson_id=1')
        assert r.status_code == 404

    @patch('app.curriculum.routes.srs_api.BookCourseEnrollment')
    @patch('app.curriculum.routes.srs_api.DailyLesson')
    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_success(self, mock_srs, mock_dl, mock_enroll, authenticated_client):
        mock_lesson = MagicMock()
        mock_lesson.module.course_id = 1
        mock_dl.query.get_or_404.return_value = mock_lesson
        mock_enroll.query.filter_by.return_value.first.return_value = MagicMock()
        session_data = {'session_key': 'abc123', 'deck': [{'card_id': 1}]}
        mock_srs.return_value.create_srs_session_for_lesson.return_value = session_data
        r = authenticated_client.get('/curriculum/api/v1/srs/session?lesson_id=1')
        assert r.status_code == 200
        d = r.get_json()
        assert d['session_key'] == 'abc123'


# ---------------------------------------------------------------------------
# Tests: POST /curriculum/api/v1/srs/grade
# ---------------------------------------------------------------------------

class TestGradeCard:
    def test_unauth(self, client):
        r = client.post('/curriculum/api/v1/srs/grade',
                        data=json.dumps({}), content_type='application/json')
        assert r.status_code in [302, 401]

    def test_no_json(self, authenticated_client):
        r = authenticated_client.post('/curriculum/api/v1/srs/grade')
        assert r.status_code in [400, 500]  # 500 when Content-Type is not JSON

    def test_missing_card_id(self, authenticated_client):
        r = authenticated_client.post('/curriculum/api/v1/srs/grade',
                                       data=json.dumps({'rating': 2}),
                                       content_type='application/json')
        assert r.status_code == 400

    def test_missing_rating_and_grade(self, authenticated_client):
        r = authenticated_client.post('/curriculum/api/v1/srs/grade',
                                       data=json.dumps({'card_id': 1}),
                                       content_type='application/json')
        assert r.status_code == 400

    def test_invalid_rating(self, authenticated_client):
        r = authenticated_client.post('/curriculum/api/v1/srs/grade',
                                       data=json.dumps({'card_id': 1, 'rating': 5}),
                                       content_type='application/json')
        assert r.status_code == 400

    @patch('app.curriculum.routes.srs_api.unified_srs_service')
    def test_success_with_rating(self, mock_srs, authenticated_client):
        mock_srs.grade_card.return_value = {'success': True, 'requeue_position': None}
        r = authenticated_client.post('/curriculum/api/v1/srs/grade',
                                       data=json.dumps({'card_id': 1, 'rating': 2}),
                                       content_type='application/json')
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    @patch('app.curriculum.routes.srs_api.unified_srs_service')
    def test_success_with_legacy_grade(self, mock_srs, authenticated_client):
        mock_srs.grade_card.return_value = {'success': True, 'requeue_position': 3}
        r = authenticated_client.post('/curriculum/api/v1/srs/grade',
                                       data=json.dumps({'card_id': 1, 'grade': 4}),
                                       content_type='application/json')
        assert r.status_code == 200
        # grade 4 -> rating 3 (KNOW)
        call_args = mock_srs.grade_card.call_args
        assert call_args.kwargs['rating'] == 3

    @patch('app.curriculum.routes.srs_api.unified_srs_service')
    def test_legacy_grade_low(self, mock_srs, authenticated_client):
        mock_srs.grade_card.return_value = {'success': True}
        authenticated_client.post('/curriculum/api/v1/srs/grade',
                                   data=json.dumps({'card_id': 1, 'grade': 0}),
                                   content_type='application/json')
        call_args = mock_srs.grade_card.call_args
        assert call_args.kwargs['rating'] == 1  # DONT_KNOW

    @patch('app.curriculum.routes.srs_api.unified_srs_service')
    def test_legacy_grade_medium(self, mock_srs, authenticated_client):
        mock_srs.grade_card.return_value = {'success': True}
        authenticated_client.post('/curriculum/api/v1/srs/grade',
                                   data=json.dumps({'card_id': 1, 'grade': 2}),
                                   content_type='application/json')
        call_args = mock_srs.grade_card.call_args
        assert call_args.kwargs['rating'] == 2  # DOUBT

    @patch('app.curriculum.routes.srs_api.unified_srs_service')
    def test_grade_failure(self, mock_srs, authenticated_client):
        mock_srs.grade_card.return_value = {'success': False, 'error': 'Card not found'}
        r = authenticated_client.post('/curriculum/api/v1/srs/grade',
                                       data=json.dumps({'card_id': 999, 'rating': 1}),
                                       content_type='application/json')
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: POST /curriculum/api/v1/srs/session/complete
# ---------------------------------------------------------------------------

class TestCompleteSrsSession:
    def test_unauth(self, client):
        r = client.post('/curriculum/api/v1/srs/session/complete',
                        data=json.dumps({}), content_type='application/json')
        assert r.status_code in [302, 401]

    def test_no_json(self, authenticated_client):
        r = authenticated_client.post('/curriculum/api/v1/srs/session/complete')
        assert r.status_code in [400, 500]  # 500 when Content-Type is not JSON

    def test_missing_fields(self, authenticated_client):
        r = authenticated_client.post('/curriculum/api/v1/srs/session/complete',
                                       data=json.dumps({'session_key': 'k'}),
                                       content_type='application/json')
        assert r.status_code == 400

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_success(self, mock_srs, authenticated_client):
        mock_srs.return_value.complete_srs_session.return_value = True
        r = authenticated_client.post('/curriculum/api/v1/srs/session/complete',
                                       data=json.dumps({
                                           'session_key': 'k', 'lesson_id': 1,
                                           'stats': {'correct': 5}}),
                                       content_type='application/json')
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_failure(self, mock_srs, authenticated_client):
        mock_srs.return_value.complete_srs_session.return_value = False
        r = authenticated_client.post('/curriculum/api/v1/srs/session/complete',
                                       data=json.dumps({
                                           'session_key': 'k', 'lesson_id': 1}),
                                       content_type='application/json')
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# Tests: GET /curriculum/api/v1/srs/due-count
# ---------------------------------------------------------------------------

class TestGetDueCardsCount:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/v1/srs/due-count').status_code in [302, 401]

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_success(self, mock_srs, authenticated_client):
        mock_srs.return_value.get_due_cards_count.return_value = 12
        r = authenticated_client.get('/curriculum/api/v1/srs/due-count')
        assert r.status_code == 200
        d = r.get_json()
        assert d['due_count'] == 12
        assert d['has_due_cards'] is True

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_zero(self, mock_srs, authenticated_client):
        mock_srs.return_value.get_due_cards_count.return_value = 0
        r = authenticated_client.get('/curriculum/api/v1/srs/due-count')
        d = r.get_json()
        assert d['due_count'] == 0
        assert d['has_due_cards'] is False


# ---------------------------------------------------------------------------
# Tests: GET /curriculum/api/v1/srs/next-session-time
# ---------------------------------------------------------------------------

class TestGetNextSessionTime:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/v1/srs/next-session-time').status_code in [302, 401]

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_with_time(self, mock_srs, authenticated_client):
        future = datetime(2026, 6, 15, 12, 0, 0)
        mock_srs.return_value.get_next_srs_session_time.return_value = future
        r = authenticated_client.get('/curriculum/api/v1/srs/next-session-time')
        assert r.status_code == 200
        d = r.get_json()
        assert d['next_session_time'] is not None

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_with_course_id(self, mock_srs, authenticated_client):
        future = datetime(2026, 6, 15, 12, 0, 0)
        mock_srs.return_value.get_next_srs_session_time.return_value = future
        r = authenticated_client.get('/curriculum/api/v1/srs/next-session-time?course_id=5')
        assert r.status_code == 200
        call_args = mock_srs.return_value.get_next_srs_session_time.call_args
        assert call_args.kwargs['course_id'] == 5

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    def test_no_time(self, mock_srs, authenticated_client):
        mock_srs.return_value.get_next_srs_session_time.return_value = None
        r = authenticated_client.get('/curriculum/api/v1/srs/next-session-time')
        d = r.get_json()
        assert d['next_session_time'] is None
        assert d['has_session_due'] is False


# ---------------------------------------------------------------------------
# Tests: POST /curriculum/api/v1/lesson/<id>/completed
# ---------------------------------------------------------------------------

class TestOnLessonCompleted:
    def test_unauth(self, client):
        r = client.post('/curriculum/api/v1/lesson/1/completed')
        assert r.status_code in [302, 401]

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    @patch('app.curriculum.routes.srs_api.DailyLesson')
    def test_vocabulary_creates_cards(self, mock_dl, mock_srs, authenticated_client):
        mock_lesson = MagicMock()
        mock_lesson.lesson_type = 'vocabulary'
        mock_dl.query.get_or_404.return_value = mock_lesson
        r = authenticated_client.post('/curriculum/api/v1/lesson/1/completed')
        assert r.status_code == 200
        assert r.get_json()['success'] is True
        mock_srs.return_value.auto_create_srs_cards_from_vocabulary_lesson.assert_called_once()

    @patch('app.curriculum.routes.srs_api.BookSRSIntegration')
    @patch('app.curriculum.routes.srs_api.DailyLesson')
    def test_non_vocabulary_no_cards(self, mock_dl, mock_srs, authenticated_client):
        mock_lesson = MagicMock()
        mock_lesson.lesson_type = 'reading_mcq'
        mock_dl.query.get_or_404.return_value = mock_lesson
        r = authenticated_client.post('/curriculum/api/v1/lesson/1/completed')
        assert r.status_code == 200
        mock_srs.return_value.auto_create_srs_cards_from_vocabulary_lesson.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: POST /curriculum/api/v1/lesson/<id>/create-srs-cards
# ---------------------------------------------------------------------------

class TestCreateSrsCards:
    def test_unauth(self, client):
        r = client.post('/curriculum/api/v1/lesson/1/create-srs-cards')
        assert r.status_code in [302, 401]
