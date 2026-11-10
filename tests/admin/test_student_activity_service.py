"""Database-backed query tests isolated from Flask/global production metadata.

Run independently with --noconftest when the PostgreSQL fixture is unavailable.
The temporary schema represents only the columns used by diagnostic SELECTs.
"""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, Integer, String, create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

spec = importlib.util.spec_from_file_location(
    'student_activity_service', Path(__file__).resolve().parents[2] /
    'app/admin/services/student_activity_service.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
NOW = datetime(2026, 11, 9, 12)


@pytest.fixture
def diagnostic_db(monkeypatch):
    base = declarative_base()

    def model(name, columns):
        return type(name, (base,), {'__tablename__': name.lower(), 'id': Column(Integer, primary_key=True), **columns})

    user = model('User', {
        'username': Column(String), 'email': Column(String), 'created_at': Column(DateTime),
        'is_admin': Column(Boolean), 'onboarding_level': Column(String),
        'onboarding_completed': Column(Boolean), 'acquisition_meta': Column(JSON),
    })
    level = model('Level', {'code': Column(String), 'order': Column(Integer)})
    module = model('Module', {'level_id': Column(Integer), 'number': Column(Integer), 'title': Column(String)})
    lesson = model('Lesson', {'module_id': Column(Integer), 'number': Column(Integer),
                              'title': Column(String), 'type': Column(String)})
    progress = model('Progress', {
        'user_id': Column(Integer), 'lesson_id': Column(Integer), 'status': Column(String),
        'started_at': Column(DateTime), 'completed_at': Column(DateTime),
        'last_activity': Column(DateTime), 'score': Column(Float), 'best_score': Column(Float),
        'last_score': Column(Float), 'data': Column(JSON),
    })
    attempt = model('Attempt', {
        'user_id': Column(Integer), 'lesson_id': Column(Integer), 'completed_at': Column(DateTime),
        'passed': Column(Boolean), 'score': Column(Float), 'attempt_number': Column(Integer),
        'total_questions': Column(Integer, default=0),
    })
    listening = model('Listening', {'user_id': Column(Integer), 'lesson_id': Column(Integer), 'created_at': Column(DateTime)})
    writing = model('Writing', {'user_id': Column(Integer), 'lesson_id': Column(Integer),
                               'created_at': Column(DateTime), 'word_count': Column(Integer)})
    pronunciation = model('Pronunciation', {'user_id': Column(Integer), 'created_at': Column(DateTime)})
    plan = model('Plan', {'user_id': Column(Integer), 'created_at': Column(DateTime),
                          'plan_date': Column(Date), 'secured_at': Column(DateTime)})
    plan_module = ModuleType('app.daily_plan.models')
    plan_module.DailyPlanLog = plan
    monkeypatch.setitem(sys.modules, 'app.daily_plan.models', plan_module)
    models = (user, level, attempt, progress, lesson, listening, module, pronunciation, writing)
    monkeypatch.setattr(service, '_models', lambda: models)
    engine = create_engine('sqlite://')
    base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(level(id=1, code='A1', order=1))
    session.add(module(id=1, level_id=1, number=1, title='Greetings'))
    session.add_all([lesson(id=i, module_id=1, number=i, title=f'Lesson {i}', type='quiz') for i in (1, 2)])
    session.flush()
    yield session, models
    session.close()
    engine.dispose()


def add_user(session, models, uid, **kwargs):
    user = models[0](id=uid, username=f'student_{uid}', email=f's{uid}@example.test',
                     created_at=kwargs.pop('created_at', NOW - timedelta(days=10)),
                     is_admin=kwargs.pop('is_admin', False), onboarding_level='A1',
                     onboarding_completed=True, acquisition_meta={}, **kwargs)
    session.add(user)
    session.flush()
    return user


def add_progress(session, models, uid, *, completed=False, age=1, lesson_id=1):
    at = NOW - timedelta(hours=age)
    row = models[3](user_id=uid, lesson_id=lesson_id,
                    status='completed' if completed else 'in_progress',
                    started_at=at, last_activity=at, completed_at=at if completed else None,
                    score=80, best_score=80, last_score=80)
    session.add(row)
    session.flush()
    return row


def add_attempt(session, models, uid, *, passed=False, age=1, number=1):
    row = models[2](user_id=uid, lesson_id=1, completed_at=NOW - timedelta(hours=age),
                    passed=passed, score=80 if passed else 20, attempt_number=number)
    session.add(row)
    session.flush()


def test_all_diagnostic_states_and_excluded_admin(diagnostic_db):
    session, models = diagnostic_db
    for uid in range(1, 8):
        add_user(session, models, uid, is_admin=uid == 7)
    add_progress(session, models, 2)
    add_progress(session, models, 3)
    add_attempt(session, models, 3)
    add_attempt(session, models, 3, number=2)
    add_progress(session, models, 4, age=100)
    add_attempt(session, models, 4, age=100)
    add_progress(session, models, 5, completed=True, age=48)
    add_attempt(session, models, 5, age=48, passed=True)
    add_progress(session, models, 6)
    add_attempt(session, models, 6, passed=True)
    result = service.get_students(session, now=NOW)
    assert result['total'] == 6
    assert {s['user_id']: s['status'] for s in result['students']} == {
        1: 'no_lesson', 2: 'opened_no_submission', 3: 'failed_attempts',
        4: 'idle_3d', 5: 'completed_no_next', 6: 'progressing',
    }
    assert result['summary']['lessons_completed'] == 1
    assert result['summary']['median_lessons_completed'] == 0


def test_specialized_submission_counts_as_learning_without_double_counting_days(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1)
    add_progress(session, models, 1)
    session.add(models[5](user_id=1, lesson_id=1, created_at=NOW - timedelta(hours=1)))
    session.add(models[8](user_id=1, lesson_id=1, created_at=NOW - timedelta(hours=1), word_count=10))
    session.add(models[7](user_id=1, created_at=NOW - timedelta(minutes=20)))
    session.flush()
    row = service.get_students(session, now=NOW)['students'][0]
    assert row['status'] == 'progressing'
    assert row['graded_attempts'] == 0
    assert row['submission_days'] == 1
    assert row['last_submission_at'] == NOW - timedelta(minutes=20)


def test_membership_search_status_registration_and_pagination(diagnostic_db):
    session, models = diagnostic_db
    for uid in range(1, 5):
        add_user(session, models, uid, created_at=NOW - timedelta(days=uid))
    result = service.get_students(session, user_ids=[1, 2, 3], days=2, per_page=1, page=2, now=NOW)
    assert result['total'] == 2
    assert result['pages'] == 2
    assert result['students'][0]['user_id'] == 2
    assert service.get_students(session, search='s3@example', now=NOW)['total'] == 1
    assert service.get_students(session, search='student_%', now=NOW)['total'] == 0
    assert service.get_students(session, status='progressing', now=NOW)['total'] == 0
    assert service.get_students(session, user_ids=[], now=NOW)['total'] == 0


def test_latest_lesson_and_filtered_summary_do_not_duplicate_users(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1)
    add_user(session, models, 2)
    add_progress(session, models, 1, completed=True, age=30)
    add_progress(session, models, 1, lesson_id=2)
    for number in range(1, 4):
        add_attempt(session, models, 1, number=number)
    result = service.get_students(session, lesson_id=2, now=NOW)
    assert result['total'] == 1
    assert result['summary']['lessons_completed'] == 1
    assert result['students'][0]['latest_lesson']['lesson_id'] == 2
    assert result['students'][0]['lessons_opened'] == 2
    assert result['students'][0]['graded_attempts'] == 3


def test_lesson_diagnostics_distinguishes_opened_completed_and_idle(diagnostic_db):
    session, models = diagnostic_db
    for uid in (1, 2, 3):
        add_user(session, models, uid)
    add_progress(session, models, 1, completed=True)
    add_progress(session, models, 2, age=30)
    add_attempt(session, models, 2, age=30)
    add_progress(session, models, 3)
    result = service.get_lesson_diagnostics(session, days=30, now=NOW)
    assert len(result) == 1
    row = result[0]
    assert row['opened'] == 3
    assert row['completed'] == 1
    assert row['submitted'] == 1
    assert row['idle_unfinished'] == 1
    assert row['idle_eligible'] == 1
    assert row['failed_attempts'] == 1
    assert row['completion_percent'] == 33.3


def test_student_detail_orders_path_and_bounds_recent_attempts(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1)
    add_progress(session, models, 1, completed=True, age=40)
    add_progress(session, models, 1, lesson_id=2)
    for number in range(1, 6):
        add_attempt(session, models, 1, number=number, age=6 - number, passed=number == 5)
    plan = sys.modules['app.daily_plan.models'].DailyPlanLog
    session.add(plan(user_id=1, created_at=NOW - timedelta(hours=5),
                     plan_date=NOW.date(), secured_at=None))
    session.flush()
    result = service.get_student_detail(session, 1, now=NOW)
    assert result['student']['user_id'] == 1
    assert [lesson['lesson_id'] for lesson in result['lessons']] == [1, 2]
    assert [attempt['number'] for attempt in result['lessons'][0]['recent_attempts']] == [5, 4, 3]
    assert result['lessons'][0]['attempts'] == 5
    assert result['lessons'][0]['failed_attempts'] == 4
    assert result['plan_days'] == 1
    assert result['secured_days'] == 0
    assert service.get_student_detail(session, 999, now=NOW) is None


def test_number_of_selects_does_not_grow_with_student_page(diagnostic_db):
    session, models = diagnostic_db
    for uid in range(1, 31):
        add_user(session, models, uid)
        add_progress(session, models, uid)
    statements = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)

    event.listen(session.bind, 'before_cursor_execute', record)
    try:
        service.get_students(session, per_page=1, now=NOW)
        small_count = len(statements)
        statements.clear()
        service.get_students(session, per_page=25, now=NOW)
        assert len(statements) == small_count
        assert small_count <= 5
    finally:
        event.remove(session.bind, 'before_cursor_execute', record)


def test_test_out_is_attainment_not_opening_or_idle_or_latest(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1)
    p = add_progress(session, models, 1, completed=True, age=100)
    p.data = {'test_out': True}
    session.flush()
    row = service.get_students(session, now=NOW)['students'][0]
    assert row['lessons_completed'] == 1
    assert row['lessons_tested_out'] == 1
    assert row['lessons_opened'] == 0
    assert row['latest_lesson'] is None
    assert row['last_activity_at'] is None
    assert row['status'] == 'no_lesson'
    assert service.get_students(session, lesson_id=1, now=NOW)['total'] == 0
    assert service.get_lesson_diagnostics(session, now=NOW) == []
    assert service.get_student_detail(session, 1, now=NOW)['lessons'][0]['test_out'] is True


def test_future_progress_timestamp_is_not_latest_learning(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1)
    p = add_progress(session, models, 1, age=100)
    p.last_activity = NOW + timedelta(days=1)
    add_attempt(session, models, 1, age=100)
    session.flush()
    row = service.get_students(session, now=NOW)['students'][0]
    assert row['last_activity_at'] == NOW - timedelta(hours=100)
    assert row['latest_lesson']['last_activity'] == NOW - timedelta(hours=100)
    assert row['status'] == 'idle_3d'


def test_source_and_activity_filters_are_independent_of_registration(diagnostic_db):
    session, models = diagnostic_db
    one = add_user(session, models, 1)
    one.acquisition_meta = {'utm_source': 'newsletter'}
    add_user(session, models, 2)
    add_progress(session, models, 1)
    add_progress(session, models, 2, age=100)
    session.flush()
    result = service.get_students(session, source='newsletter', last_activity_days=1, now=NOW)
    assert result['total'] == 1
    assert result['students'][0]['user_id'] == 1
    assert service.get_students(session, source='unknown', now=NOW)['students'][0]['user_id'] == 2
    assert service.get_students(session, last_activity_days=1, days=1, now=NOW)['total'] == 0


def test_module_completion_requires_every_catalogue_lesson_and_labels_testout(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1)
    add_progress(session, models, 1, completed=True, age=10)
    partial = service.get_students(session, now=NOW)['students'][0]
    assert partial['modules_completed'] == 0
    assert partial['latest_lesson']['module_lessons_total'] == 2
    assert partial['latest_lesson']['module_lessons_completed'] == 1
    synthetic = add_progress(session, models, 1, completed=True, lesson_id=2)
    synthetic.data = {'test_out': True}
    session.flush()
    finished = service.get_students(session, now=NOW)['students'][0]
    assert finished['modules_completed'] == 1
    assert finished['latest_lesson']['lesson_id'] == 1
    assert finished['latest_lesson']['module_lessons_completed'] == 2
    detail = service.get_student_detail(session, 1, now=NOW)
    assert detail['lessons'][1]['test_out'] is True
    assert detail['lessons'][0]['module_lessons_total'] == 2


def test_saved_position_exposes_only_valid_indexes_without_answer_text(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1)
    p = add_progress(session, models, 1)
    p.data = {'current_page': 2, 'item_index': '004', 'current_question': 'my secret answer',
              'current_index': True, 'question_index': -1, 'current_card': 1_000_000,
              'response_text': 'personal response', 'answers': ['private']}
    session.flush()
    position = service.get_student_detail(session, 1, now=NOW)['lessons'][0]['saved_position']
    assert position == {'current_page': 2, 'item_index': 4}


def test_each_lesson_drilldown_matches_its_diagnostic_count(diagnostic_db):
    session, models = diagnostic_db
    for uid in range(1, 7):
        add_user(session, models, uid)
    add_progress(session, models, 1, completed=True)
    add_progress(session, models, 2, age=30)
    add_attempt(session, models, 2, age=30)
    add_progress(session, models, 3)
    # A submission can exist even if the legacy progress row was not persisted.
    session.add(models[5](user_id=4, lesson_id=1, created_at=NOW - timedelta(hours=1)))
    # Synthetic attainment must not appear as a real lesson completion here.
    synthetic = add_progress(session, models, 5, completed=True)
    synthetic.data = {'test_out': True}
    # An old action in another lesson must not make lesson 1's drilldown idle.
    add_progress(session, models, 6, lesson_id=2, age=50)
    session.flush()
    diagnostic = next(row for row in service.get_lesson_diagnostics(session, now=NOW) if row['lesson_id'] == 1)
    for state, field, ids in (
        ('opened', 'opened', {1, 2, 3}),
        ('submitted', 'submitted', {2, 4}),
        ('completed', 'completed', {1}),
        ('idle_unfinished', 'idle_unfinished', {2}),
    ):
        result = service.get_students(session, lesson_id=1, lesson_state=state, now=NOW)
        assert result['total'] == diagnostic[field]
        assert {row['user_id'] for row in result['students']} == ids
        assert result['filters']['lesson_state'] == state
    assert service.get_students(session, lesson_state='idle_unfinished', now=NOW)['total'] == 6


def test_passive_completion_is_learning_progress_not_missing_submission(diagnostic_db):
    session, models = diagnostic_db
    for uid in range(1, 5):
        add_user(session, models, uid)
    session.get(models[4], 1).type = 'vocabulary'
    add_progress(session, models, 1, completed=True)
    add_progress(session, models, 2, completed=True, age=48)
    add_progress(session, models, 3, completed=True, age=100)
    add_progress(session, models, 4, completed=True, age=30)
    add_progress(session, models, 4, lesson_id=2)
    result = service.get_students(session, now=NOW)
    assert {row['user_id']: row['status'] for row in result['students']} == {
        1: 'progressing', 2: 'completed_no_next', 3: 'idle_3d', 4: 'progressing',
    }


def test_explicit_admin_detail_is_accessible_but_not_in_learner_cohorts(diagnostic_db):
    session, models = diagnostic_db
    add_user(session, models, 1, is_admin=True)
    add_progress(session, models, 1)
    assert service.get_students(session, now=NOW)['total'] == 0
    assert service.get_lesson_diagnostics(session, now=NOW) == []
    assert service.get_student_detail(session, 1, now=NOW)['student']['is_admin'] is True


def test_grammar_theory_is_excluded_but_real_grammar_and_legacy_translation_count(diagnostic_db):
    session, models = diagnostic_db
    for uid in (1, 2, 3):
        add_user(session, models, uid)
        add_progress(session, models, uid)
        add_attempt(session, models, uid, passed=True)
    session.get(models[4], 1).type = 'grammar'
    actual_grammar = session.query(models[2]).filter(models[2].user_id == 2).one()
    actual_grammar.total_questions = 3
    session.get(models[4], 2).type = 'translation'
    legacy = session.query(models[2]).filter(models[2].user_id == 3).one()
    legacy.lesson_id = 2
    session.flush()
    rows = {row['user_id']: row for row in service.get_students(session, now=NOW)['students']}
    assert rows[1]['graded_attempts'] == 0
    assert rows[1]['last_submission_at'] is None
    assert rows[2]['graded_attempts'] == 1
    assert rows[2]['last_submission_at'] is not None
    assert rows[3]['graded_attempts'] == 1
    assert rows[3]['last_submission_at'] is not None
    assert service.get_student_detail(session, 1, now=NOW)['lessons'][0]['recent_attempts'] == []
    diagnostic = next(row for row in service.get_lesson_diagnostics(session, now=NOW) if row['lesson_id'] == 1)
    assert diagnostic['submitted'] == 1
    assert diagnostic['attempts'] == 1


def test_graded_listening_counts_but_legacy_and_self_review_do_not(diagnostic_db):
    session, models = diagnostic_db
    for uid in (1, 2, 3):
        add_user(session, models, uid)
        add_progress(session, models, uid)
    session.get(models[4], 1).type = 'listening_immersion'
    add_attempt(session, models, 1, passed=True)
    add_attempt(session, models, 2, passed=True)
    graded = session.query(models[2]).filter(models[2].user_id == 2).one()
    graded.total_questions = 3
    graded.score = 50
    # A self-reviewed written answer is activity, never an automatic grade.
    session.add(models[8](user_id=3, lesson_id=1, created_at=NOW - timedelta(minutes=10), word_count=15))
    session.flush()
    rows = {row['user_id']: row for row in service.get_students(session, now=NOW)['students']}
    assert rows[1]['graded_attempts'] == 0
    assert rows[1]['avg_score'] is None
    assert rows[2]['graded_attempts'] == 1
    assert rows[2]['avg_score'] == 50
    assert rows[3]['graded_attempts'] == 0
    assert rows[3]['avg_score'] is None
    assert rows[3]['last_submission_at'] == NOW - timedelta(minutes=10)
    assert service.get_student_detail(session, 1, now=NOW)['lessons'][0]['recent_attempts'] == []
    assert service.get_student_detail(session, 2, now=NOW)['lessons'][0]['attempts'] == 1
