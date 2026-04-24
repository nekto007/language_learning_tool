"""
Integration tests for app/curriculum/routes/api.py

Tests all curriculum API endpoints:
- GET /curriculum/api/levels
- GET /curriculum/api/level/<code>/modules
- GET /curriculum/api/module/<id>/lessons
- GET /curriculum/api/lesson/<id>/info
- GET /curriculum/api/user/progress
- GET /curriculum/api/lesson/<id>/card/session
"""
import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
from app.utils.db import db


@pytest.fixture
def curriculum_data(db_session):
    code = uuid.uuid4().hex[:2].upper()
    for _ in range(50):
        if not CEFRLevel.query.filter_by(code=code).first():
            break
        code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name='Test Level', description='desc', order=1)
    db_session.add(level)
    db_session.flush()
    module = Module(level_id=level.id, number=1, title='Test Module',
                    description='desc', raw_content={}, min_score_required=70,
                    allow_skip_test=False, input_mode='mixed')
    db_session.add(module)
    db_session.flush()
    v = Lessons(module_id=module.id, number=1, title='Vocab', type='vocabulary', order=0,
                content={'vocabulary': [{'word': 'hi', 'translation': 't'}]})
    q = Lessons(module_id=module.id, number=2, title='Quiz', type='quiz', order=1,
                content={'questions': [{'type': 'multiple_choice', 'question': 'Q?', 'options': ['A', 'B'], 'correct_index': 0}]})
    c = Lessons(module_id=module.id, number=3, title='Card', type='card', order=2, content={})
    db_session.add_all([v, q, c])
    db_session.commit()
    return {'level': level, 'module': module, 'vocab': v, 'quiz': q, 'card': c}


@pytest.fixture
def progress_data(db_session, test_user, curriculum_data):
    p = LessonProgress(user_id=test_user.id, lesson_id=curriculum_data['vocab'].id,
                       status='completed', score=85.0,
                       started_at=datetime.now(timezone.utc) - timedelta(days=2),
                       completed_at=datetime.now(timezone.utc) - timedelta(days=1),
                       last_activity=datetime.now(timezone.utc) - timedelta(hours=3))
    db_session.add(p)
    db_session.commit()
    return p


class TestApiGetLevels:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/levels').status_code in [302, 401]

    @pytest.mark.smoke
    def test_success(self, authenticated_client, curriculum_data):
        r = authenticated_client.get('/curriculum/api/levels')
        assert r.status_code == 200
        d = r.get_json()
        assert d['success'] and len(d['levels']) >= 1

    @pytest.mark.smoke
    def test_structure(self, authenticated_client, curriculum_data):
        d = authenticated_client.get('/curriculum/api/levels').get_json()
        lv = next((x for x in d['levels'] if x['code'] == curriculum_data['level'].code), None)
        assert lv is not None
        for k in ('id', 'code', 'name', 'total_lessons', 'completed_lessons', 'progress_percentage'):
            assert k in lv

    def test_progress_with_completions(self, authenticated_client, curriculum_data, progress_data):
        d = authenticated_client.get('/curriculum/api/levels').get_json()
        lv = next((x for x in d['levels'] if x['code'] == curriculum_data['level'].code), None)
        assert lv['completed_lessons'] == 1 and lv['total_lessons'] == 3

    def test_progress_zero(self, authenticated_client, curriculum_data):
        d = authenticated_client.get('/curriculum/api/levels').get_json()
        lv = next((x for x in d['levels'] if x['code'] == curriculum_data['level'].code), None)
        assert lv['completed_lessons'] == 0


class TestApiGetLevelModules:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/level/A1/modules').status_code in [302, 401]

    @pytest.mark.smoke
    def test_success(self, authenticated_client, curriculum_data):
        code = curriculum_data['level'].code
        r = authenticated_client.get(f'/curriculum/api/level/{code}/modules')
        assert r.status_code == 200
        d = r.get_json()
        assert d['success'] and d['level']['code'] == code

    def test_module_fields(self, authenticated_client, curriculum_data):
        code = curriculum_data['level'].code
        d = authenticated_client.get(f'/curriculum/api/level/{code}/modules').get_json()
        m = d['modules'][0]
        for k in ('id', 'number', 'title', 'total_lessons', 'is_accessible'):
            assert k in m

    def test_404(self, authenticated_client):
        r = authenticated_client.get('/curriculum/api/level/ZZ/modules')
        assert r.status_code == 404


class TestApiGetModuleLessons:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/module/1/lessons').status_code in [302, 401]

    def test_404(self, authenticated_client):
        assert authenticated_client.get('/curriculum/api/module/999999/lessons').status_code == 404

    @pytest.mark.smoke
    def test_success(self, authenticated_client, curriculum_data):
        mid = curriculum_data['module'].id
        r = authenticated_client.get(f'/curriculum/api/module/{mid}/lessons')
        assert r.status_code == 200 and len(r.get_json()['lessons']) == 3

    def test_fields(self, authenticated_client, curriculum_data):
        mid = curriculum_data['module'].id
        ls = authenticated_client.get(f'/curriculum/api/module/{mid}/lessons').get_json()['lessons'][0]
        for k in ('id', 'number', 'title', 'type', 'status', 'is_accessible'):
            assert k in ls

    def test_status_completed(self, authenticated_client, curriculum_data, progress_data):
        mid = curriculum_data['module'].id
        d = authenticated_client.get(f'/curriculum/api/module/{mid}/lessons').get_json()
        v = next((x for x in d['lessons'] if x['id'] == curriculum_data['vocab'].id), None)
        assert v['status'] == 'completed' and v['score'] == 85.0

    def test_status_not_started(self, authenticated_client, curriculum_data):
        mid = curriculum_data['module'].id
        for ls in authenticated_client.get(f'/curriculum/api/module/{mid}/lessons').get_json()['lessons']:
            assert ls['status'] == 'not_started'

    def test_locked_module_403(self, authenticated_client, db_session, curriculum_data):
        m2 = Module(level_id=curriculum_data['level'].id, number=2, title='Locked',
                     description='x', raw_content={}, min_score_required=70,
                     allow_skip_test=False, input_mode='mixed')
        db_session.add(m2)
        db_session.commit()
        assert authenticated_client.get(f'/curriculum/api/module/{m2.id}/lessons').status_code == 403


class TestApiGetLessonInfo:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/lesson/1/info').status_code in [302, 401]

    def test_404(self, authenticated_client):
        assert authenticated_client.get('/curriculum/api/lesson/999999/info').status_code == 404

    @pytest.mark.smoke
    def test_success(self, authenticated_client, curriculum_data):
        lid = curriculum_data['vocab'].id
        d = authenticated_client.get(f'/curriculum/api/lesson/{lid}/info').get_json()
        assert d['success'] and 'lesson' in d and 'progress' in d

    @pytest.mark.smoke
    def test_structure(self, authenticated_client, curriculum_data):
        lid = curriculum_data['vocab'].id
        ls = authenticated_client.get(f'/curriculum/api/lesson/{lid}/info').get_json()['lesson']
        assert 'module' in ls and 'level' in ls

    def test_completed(self, authenticated_client, curriculum_data, progress_data):
        lid = curriculum_data['vocab'].id
        p = authenticated_client.get(f'/curriculum/api/lesson/{lid}/info').get_json()['progress']
        assert p['status'] == 'completed' and p['score'] == 85.0

    def test_not_started(self, authenticated_client, curriculum_data):
        lid = curriculum_data['vocab'].id
        p = authenticated_client.get(f'/curriculum/api/lesson/{lid}/info').get_json()['progress']
        assert p['status'] == 'not_started'

    def test_card_lesson_type(self, authenticated_client, curriculum_data):
        """Card lesson info endpoint should respond without server error."""
        lid = curriculum_data['card'].id
        r = authenticated_client.get(f'/curriculum/api/lesson/{lid}/info')
        assert r.status_code in [200, 403]  # 200 if accessible, 403 if locked


class TestApiGetUserProgress:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/user/progress').status_code in [302, 401]

    @pytest.mark.smoke
    def test_success(self, authenticated_client, curriculum_data):
        d = authenticated_client.get('/curriculum/api/user/progress').get_json()
        assert d['success'] and 'progress' in d

    @pytest.mark.smoke
    def test_structure(self, authenticated_client, curriculum_data):
        p = authenticated_client.get('/curriculum/api/user/progress').get_json()['progress']
        for k in ('total_lessons', 'started_lessons', 'completed_lessons',
                   'in_progress_lessons', 'completion_percentage', 'average_score', 'current_streak'):
            assert k in p

    def test_with_completions(self, authenticated_client, curriculum_data, progress_data):
        p = authenticated_client.get('/curriculum/api/user/progress').get_json()['progress']
        assert p['completed_lessons'] >= 1 and p['average_score'] > 0

    def test_recent_activity(self, authenticated_client, curriculum_data, progress_data):
        d = authenticated_client.get('/curriculum/api/user/progress').get_json()
        assert len(d['recent_activity']) >= 1

    def test_no_activity(self, authenticated_client):
        p = authenticated_client.get('/curriculum/api/user/progress').get_json()['progress']
        assert p['completed_lessons'] == 0 and p['current_streak'] == 0


class TestApiGetCardSession:
    def test_unauth(self, client):
        assert client.get('/curriculum/api/lesson/1/card/session').status_code in [302, 401]

    def test_non_card_400(self, authenticated_client, curriculum_data):
        lid = curriculum_data['vocab'].id
        assert authenticated_client.get(f'/curriculum/api/lesson/{lid}/card/session').status_code == 400

    def test_missing_404(self, authenticated_client):
        # Missing lesson resolves to 404 via @require_lesson_access.
        assert authenticated_client.get('/curriculum/api/lesson/999999/card/session').status_code == 404

    @pytest.mark.smoke
    def test_success(self, authenticated_client, curriculum_data):
        lid = curriculum_data['card'].id
        with patch('app.curriculum.routes.api.get_card_session_for_lesson') as m, \
             patch('app.curriculum.security.check_lesson_access', return_value=True):
            m.return_value = {'session_key': 'k', 'cards': [], 'total_due': 0}
            r = authenticated_client.get(f'/curriculum/api/lesson/{lid}/card/session')
            assert r.status_code == 200 and r.get_json()['success']


class TestCalculateUserStreak:
    def test_zero(self, app, test_user):
        from app.curriculum.routes.api import calculate_user_streak
        with app.app_context():
            assert calculate_user_streak(test_user.id) == 0

    def test_consecutive(self, app, db_session, test_user, curriculum_data):
        from app.curriculum.routes.api import calculate_user_streak
        now = datetime.now(timezone.utc)
        lessons = [curriculum_data['vocab'], curriculum_data['quiz'], curriculum_data['card']]
        for d in range(3):
            db_session.add(LessonProgress(
                user_id=test_user.id, lesson_id=lessons[d].id,
                status='completed', score=80.0, last_activity=now - timedelta(days=d)))
        db_session.commit()
        with app.app_context():
            assert calculate_user_streak(test_user.id) >= 1

    def test_nonexistent(self, app):
        from app.curriculum.routes.api import calculate_user_streak
        with app.app_context():
            assert calculate_user_streak(999999) == 0
