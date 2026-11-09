"""Admin diagnostics: real model queries, access gates and consistent drilldowns."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.models import User
from app.curriculum.models import LessonAttempt, LessonProgress


@pytest.fixture
def learner_path(db_session, test_lesson_vocabulary, test_lesson_quiz):
    name = f'journey_{uuid.uuid4().hex[:8]}'
    user = User(username=name, email=f'{name}@example.test', onboarding_completed=True,
                onboarding_level='A1', is_admin=False,
                created_at=datetime.now(UTC) - timedelta(days=10))
    user.set_password('test-only-password')
    db_session.add(user)
    db_session.flush()
    start = user.created_at
    db_session.add_all([
        LessonProgress(user_id=user.id, lesson_id=test_lesson_vocabulary.id,
                       status='completed', started_at=start + timedelta(minutes=1),
                       completed_at=start + timedelta(minutes=3), last_activity=start + timedelta(minutes=3)),
        LessonProgress(user_id=user.id, lesson_id=test_lesson_quiz.id,
                       status='in_progress', started_at=start + timedelta(minutes=4),
                       last_activity=start + timedelta(minutes=8)),
        LessonAttempt(user_id=user.id, lesson_id=test_lesson_quiz.id, attempt_number=1,
                      started_at=start + timedelta(minutes=4), completed_at=start + timedelta(minutes=8),
                      score=20, passed=False, total_questions=0),
    ])
    db_session.commit()
    return user, test_lesson_vocabulary, test_lesson_quiz


def test_students_search_and_lesson_drilldown(client, admin_user, learner_path):
    user, vocab, _ = learner_path
    response = client.get('/admin/activity/students', query_string={'q': user.username})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert user.username in html
    assert f'/admin/activity/students/{user.id}' in html
    assert 'В среднем на ученика' in html  # noqa: RUF001
    response = client.get('/admin/activity/students', query_string={'days': 30, 'lesson_id': vocab.id})
    assert response.status_code == 200
    assert user.username in response.get_data(as_text=True)


def test_detail_includes_passive_completion_real_attempt_and_navigation(client, admin_user, learner_path):
    user, vocab, quiz = learner_path
    response = client.get(f'/admin/activity/students/{user.id}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert vocab.title in html and quiz.title in html
    assert 'Последние проверки' in html
    assert 'не пройдено' in html
    assert f'/admin/users/{user.id}' in html
    assert f'/admin/activity?user_id={user.id}' in html


def test_funnel_drilldown_matches_visible_members(client, admin_user, learner_path):
    user, _, _ = learner_path
    response = client.get('/admin/activity/funnel?days=30')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'path_opened_without_path_completed' in html
    assert 'Когортное удержание' in html
    assert 'D7' in html
    # Vocabulary is a real completion without a graded submission.
    completed = client.get('/admin/activity/students?days=30&stage=path_completed')
    assert user.username in completed.get_data(as_text=True)
    lost = client.get('/admin/activity/students?days=30&stage=path_opened_without_path_completed')
    assert user.username not in lost.get_data(as_text=True)


def test_bottlenecks_and_feed_link_to_student(client, admin_user, learner_path):
    user, _, quiz = learner_path
    response = client.get('/admin/activity/lessons?days=30')
    assert response.status_code == 200
    assert quiz.title in response.get_data(as_text=True)
    response = client.get('/admin/activity', query_string={'user_id': user.id, 'event_types': 'lesson_attempt'})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Проверка работы' in html
    assert f'/admin/activity/students/{user.id}' in html


@pytest.mark.parametrize('path', [
    '/admin/activity/students?status=invented', '/admin/activity/students?level=X9',
    '/admin/activity/students?stage=invented',
])
def test_invalid_diagnostics_filters_rejected(client, admin_user, path):
    assert client.get(path).status_code == 400


def test_missing_student_is_404(client, admin_user):
    assert client.get('/admin/activity/students/2147483647').status_code == 404


@pytest.mark.parametrize('path', [
    '/admin/activity/students', '/admin/activity/students/1', '/admin/activity/lessons',
])
def test_diagnostics_require_admin(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


@pytest.mark.parametrize('path', [
    '/admin/activity/students', '/admin/activity/students/1',
    '/admin/activity/lessons', '/admin/activity/funnel',
])
def test_authenticated_learner_cannot_read_admin_diagnostics(authenticated_client, path):
    response = authenticated_client.get(path)
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_input_grader_counts_persist_on_attempt(app, db_session, test_user, test_lesson_quiz):
    from unittest.mock import patch

    from app.curriculum.services.progress_service import ProgressService
    test_lesson_quiz.type = 'translation'
    db_session.commit()
    with patch('app.curriculum.services.progress_service._invalidate_user_progress_cache'):
        ProgressService.update_progress_with_grading(
            test_user.id, test_lesson_quiz,
            {'score': 25, 'correct_items': 1, 'total_items': 4, 'passed': False})
    attempt = LessonAttempt.query.filter_by(user_id=test_user.id, lesson_id=test_lesson_quiz.id).one()
    assert attempt.correct_answers == 1
    assert attempt.total_questions == 4


def test_postgres_testout_is_attainment_without_a_fake_open(
        client, admin_user, db_session, test_lesson_vocabulary):
    name = f'extern_{uuid.uuid4().hex[:8]}'
    now = datetime.now(UTC)
    learner = User(username=name, email=f'{name}@example.test', is_admin=False,
                   created_at=now - timedelta(days=10), onboarding_completed=True)
    learner.set_password('test-only-password')
    db_session.add(learner)
    db_session.flush()
    db_session.add(LessonProgress(
        user_id=learner.id, lesson_id=test_lesson_vocabulary.id, status='completed',
        started_at=now - timedelta(days=10) + timedelta(minutes=1),
        completed_at=now - timedelta(days=10) + timedelta(minutes=2),
        last_activity=now - timedelta(days=10) + timedelta(minutes=2),
        data={'test_out': True}, score=100))
    db_session.commit()
    response = client.get('/admin/activity/students?days=30&stage=path_opened')
    assert response.status_code == 200
    assert name not in response.get_data(as_text=True)
    response = client.get('/admin/activity', query_string={
        'user_id': learner.id, 'event_types': 'lesson_opened'})
    assert 'Первое записанное открытие' not in response.get_data(as_text=True)
    detail = client.get(f'/admin/activity/students/{learner.id}')
    assert detail.status_code == 200
    assert 'Экстерном' in detail.get_data(as_text=True)


def test_retention_drilldowns_use_mature_denominator(client, admin_user, learner_path):
    learner, _, _ = learner_path
    eligible = client.get('/admin/activity/students?days=30&stage=eligible_D7')
    assert eligible.status_code == 200
    assert learner.username in eligible.get_data(as_text=True)
    retained = client.get('/admin/activity/students?days=30&stage=retained_D7')
    assert retained.status_code == 200
    assert learner.username not in retained.get_data(as_text=True)


def test_administrator_history_link_is_not_broken(client, admin_user):
    response = client.get(f'/admin/activity/students/{admin_user.id}')
    assert response.status_code == 200
    assert 'История администратора' in response.get_data(as_text=True)
