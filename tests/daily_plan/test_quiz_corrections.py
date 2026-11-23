"""A durable first round is followed by independent work and then repairs."""
from copy import deepcopy
from datetime import UTC, date, datetime
import json
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from app.daily_plan import quiz_corrections as qc
from tests.api.test_native_full_integration import native_app as _native_app, learner


@pytest.fixture(scope='module')
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def marker(score=40, created='2026-11-22T12:00:00+00:00'):
    return {'version': 1, 'attempt_id': uuid4().hex, 'status': 'pending',
            'created_at': created, 'first_score': score, 'first_passed': score >= 50,
            'pending_ids': ['q2', 'q4'], 'first_answers': {'secret': 'answer'},
            'feedback': [{'expected': 'private'}]}


def lesson(number):
    level = NS(order=1, code='A1')
    module = NS(number=1, title='Module', level=level)
    return NS(id=number, number=number, module=module, module_id=1,
              type='quiz', title=f'Lesson {number}', content={'questions': []})


def card(kind, number=None, completed=False, **data):
    if number is not None:
        data['lesson_id'] = number
    return {'id': f'{kind}:{number}', 'kind': kind, 'completed': completed,
            'section': 'required', 'url': None if completed else '/practice',
            'data': data, 'eta_minutes': 5}


@pytest.fixture
def project(monkeypatch):
    state = marker()
    q3 = lesson(3)
    pending = qc.PendingQuizCorrection(NS(status='in_progress', data={'quiz_correction': state}), q3, state)
    database = NS(session=NS(get=lambda model, number: lesson(number)))
    monkeypatch.setattr(qc, 'pending_quiz_corrections', lambda uid, db: [pending])
    monkeypatch.setattr('app.utils.time_utils.get_user_local_date', lambda uid, db: date(2026, 11, 22))
    monkeypatch.setattr('app.utils.time_utils.get_user_timezone_name', lambda uid, db: 'UTC')
    return state, database


def phases(items):
    return [(item['kind'], item['data'].get('quiz_phase'), item['data'].get('lesson_id')) for item in items]


@pytest.mark.parametrize('score', [40, 50, 60, 90])
def test_both_failed_and_passed_round_wait_for_srs_book(project, score):
    state, db = project
    state['first_score'] = score
    required = [card('curriculum', 3), card('srs'), card('reading'), card('curriculum', 4)]
    result, optional = qc.reconcile_quiz_corrections(7, db, required, [])
    assert phases(result) == [('curriculum', 'first_round', 3), ('srs', None, None),
                             ('reading', None, None), ('curriculum', 'correction', 3),
                             ('curriculum', None, 4)]
    assert result[0]['completed'] and not result[3]['completed']
    assert result[4]['blocked']
    assert not optional
    assert 'secret' not in json.dumps(result) and 'private' not in json.dumps(result)


def test_projection_is_idempotent_and_does_not_reset_or_mutate_work(project):
    _, db = project
    required = [card('curriculum', 3), card('srs', completed=True, goal_total=12, reviewed=12),
                card('reading', completed=True, goal_total=8, pages_read=8), card('curriculum', 4)]
    saved = deepcopy(required)
    first = qc.reconcile_quiz_corrections(7, db, required, [])
    second = qc.reconcile_quiz_corrections(7, db, *first)
    assert first == second
    assert required == saved
    assert first[0][1:3] == saved[1:3]
    assert len({item['id'] for item in first[0]}) == len(first[0])


def test_legacy_interleaved_book_is_moved_before_repairs(project):
    _, db = project
    required = [card('curriculum', 3), card('srs'), card('curriculum', 4), card('reading')]
    result, _ = qc.reconcile_quiz_corrections(7, db, required, [])
    assert [item['kind'] for item in result] == ['curriculum', 'srs', 'reading', 'curriculum', 'curriculum']
    assert result[3]['data']['quiz_phase'] == 'correction'


def test_optional_correction_preserves_completed_required(project):
    _, db = project
    required = [card('curriculum', 2, completed=True), card('srs', completed=True), card('reading', completed=True)]
    optional = [card('curriculum', 3), card('curriculum', 4)]
    result, continuation = qc.reconcile_quiz_corrections(7, db, required, optional)
    assert result == required
    assert [item['data'].get('quiz_phase') for item in continuation] == ['first_round', 'correction', None]
    assert all(item['section'] == 'optional' for item in continuation[:2])


def test_rollover_places_inherited_correction_before_new_goals(project):
    state, db = project
    state['created_at'] = '2026-11-21T23:00:00+00:00'
    required = [card('curriculum', 3), card('srs', goal_total=12), card('reading', goal_total=8), card('curriculum', 4)]
    saved = deepcopy(required)
    result, _ = qc.reconcile_quiz_corrections(7, db, required, [])
    assert phases(result)[:3] == [('curriculum', 'correction', 3), ('srs', None, None), ('reading', None, None)]
    assert not result[1]['completed'] and not result[2]['completed']
    assert required == saved
    assert not any(item['data'].get('quiz_phase') == 'first_round' for item in result)


@pytest.mark.parametrize(('now', 'expected_phase'), [
    ('2026-11-23T01:59:00+00:00', 'first_round'),
    ('2026-11-23T02:00:00+00:00', 'correction'),
])
def test_study_day_rolls_at_two_not_midnight(project, monkeypatch, now, expected_phase):
    from app.utils.time_utils import study_day_date_for_tz
    _, db = project
    today = study_day_date_for_tz('UTC', now_utc=datetime.fromisoformat(now))
    monkeypatch.setattr('app.utils.time_utils.get_user_local_date', lambda uid, db: today)
    result, _ = qc.reconcile_quiz_corrections(7, db, [card('curriculum', 3), card('srs'), card('reading')], [])
    assert result[0]['data']['quiz_phase'] == expected_phase


def test_changed_content_is_named_without_mutating_marker(project):
    state, db = project
    state['revision'] = 'old-revision'
    before = deepcopy(state)
    result, _ = qc.reconcile_quiz_corrections(7, db, [card('curriculum', 3), card('srs')], [])
    correction = next(item for item in result if item['data'].get('quiz_phase') == 'correction')
    assert correction['data']['quiz_material_changed']
    assert correction['title'].startswith('Повторить обновлённое задание')
    assert state == before


def test_skipped_first_round_does_not_skip_repairs_or_enable_quota(project):
    from app.daily_plan.plan import _apply_unified_skip_state, _annotate_unified_skip_quota
    _, db = project
    result, _ = qc.reconcile_quiz_corrections(7, db, [card('curriculum', 3), card('srs')], [])
    _apply_unified_skip_state(result, [('curriculum', 'lesson:3')])
    _annotate_unified_skip_quota(result, 0)
    correction = result[-1]
    assert correction['data']['quiz_phase'] == 'correction'
    assert not correction.get('skipped') and not correction.get('blocked')
    assert correction['data']['slot_skip_allowed'] is False


@pytest.mark.parametrize('data', [None, [], {}, {'quiz_correction': []},
    {'quiz_correction': {'version': 2, 'status': 'pending', 'attempt_id': 'a'}},
    {'quiz_correction': {'version': 1, 'status': 'pending', 'attempt_id': ''}}])
def test_legacy_or_invalid_marker_is_ignored(data):
    assert qc.correction_state_from_data(data) is None


@pytest.fixture
def course(native_app):
    from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
    from app.utils.db import db
    user, _ = learner(native_app)
    user.onboarding_completed = True
    user.timezone = 'UTC'
    code = uuid4().hex[:2].upper()
    while CEFRLevel.query.filter_by(code=code).first():
        code = uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name='Correction test', order=1000 + user.id)
    db.session.add(level)
    db.session.flush()
    module = Module(level_id=level.id, number=1, title='Correction module')
    db.session.add(module)
    db.session.flush()
    lessons = [Lessons(module_id=module.id, number=n, title=f'Lesson {n}', type='quiz', content={}) for n in range(1, 5)]
    db.session.add_all(lessons)
    db.session.flush()
    rows = [LessonProgress(user_id=user.id, lesson_id=unit.id, status='completed' if n < 3 else 'in_progress', score=40,
                           data={'quiz_correction': marker(created=datetime.now(UTC).isoformat())} if n == 3 else {})
            for n, unit in enumerate(lessons, 1)]
    db.session.add_all(rows)
    db.session.commit()
    return user, lessons, rows


def test_real_pending_query_and_restart_persistence(native_app, course):
    from app.utils.db import db
    user, lessons, _rows = course
    uid, qid = user.id, lessons[2].id
    assert [p.lesson.id for p in qc.pending_quiz_corrections(uid, db)] == [qid]
    db.session.remove()
    assert [p.lesson.id for p in qc.pending_quiz_corrections(uid, db)] == [qid]
    assert not qc.pending_quiz_corrections(uid + 100000, db)


def test_direct_access_blocks_even_already_open_later_draft(native_app, course, monkeypatch):
    from app.curriculum import security
    from app.utils.db import db
    user, lessons, rows = course
    monkeypatch.setattr(security, 'current_user', NS(id=user.id, is_authenticated=True, is_admin=False))
    monkeypatch.setattr(security, 'check_module_access', lambda module_id: True)
    assert security.check_lesson_access(lessons[2].id)
    assert not security.check_lesson_access(lessons[3].id)
    db.session.delete(rows[3])
    db.session.commit()
    assert not security.check_lesson_access(lessons[3].id)
    state = dict(rows[2].data['quiz_correction'], status='completed')
    rows[2].data = {'quiz_correction': state}
    rows[2].status = 'completed'
    db.session.commit()
    assert security.check_lesson_access(lessons[3].id)
    assert not qc.pending_quiz_corrections(user.id, db)


def test_completed_assisted_round_counts_without_raising_first_score(native_app, course):
    from app.daily_plan.items.curriculum import _lesson_meets_passing
    from app.utils.db import db
    _, lessons, rows = course
    row = rows[2]
    row.data = {'quiz_correction': dict(row.data['quiz_correction'], status='completed')}
    row.status = 'completed'
    db.session.commit()
    assert qc.is_completed_correction(row)
    assert _lesson_meets_passing(lessons[2], row.score, row.data)
    assert row.score == 40
    assert not _lesson_meets_passing(lessons[2], row.score, {})
    lessons[2].type = 'final_test'
    assert not _lesson_meets_passing(lessons[2], row.score, row.data)


def test_admin_and_completed_review_stay_accessible(native_app, course, monkeypatch):
    from app.curriculum import security
    from app.utils.db import db
    user, lessons, rows = course
    principal = NS(id=user.id, is_authenticated=True, is_admin=False)
    monkeypatch.setattr(security, 'current_user', principal)
    monkeypatch.setattr(security, 'check_module_access', lambda module_id: True)
    rows[3].status = 'completed'
    db.session.commit()
    assert security.check_lesson_access(lessons[3].id)
    principal.is_admin = True
    assert security.check_lesson_access(lessons[3].id)


def test_spine_stays_at_quiz_until_assisted_completion(native_app, course, monkeypatch):
    from app.daily_plan.linear import progression
    from app.utils.db import db
    from app.utils.request_cache import _get_cache
    user, lessons, rows = course
    monkeypatch.setattr(progression, '_user_min_level_order', lambda uid, database: lessons[0].module.level.order)
    monkeypatch.setattr('app.curriculum.security.check_module_access', lambda module_id, **kwargs: True)
    _get_cache().clear()
    assert progression.find_next_lesson_linear(user.id, db).id == lessons[2].id
    rows[2].status = 'completed'
    rows[2].data = {'quiz_correction': dict(rows[2].data['quiz_correction'], status='completed')}
    db.session.commit()
    _get_cache().clear()
    assert progression.find_next_lesson_linear(user.id, db).id == lessons[3].id


def test_skip_endpoints_do_not_write_or_consume_quota(native_app, course, monkeypatch):
    from app.daily_plan.models import DailyPlanEvent, LessonSkip
    from app.daily_plan import plan
    from app.utils.db import db
    user, lessons, _rows = course
    monkeypatch.setitem(native_app.config, 'WTF_CSRF_ENABLED', False)
    client = native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
    correction = card('curriculum', lessons[2].id, quiz_phase='correction')
    monkeypatch.setattr(plan, 'get_daily_plan', lambda uid, database: {'required': [correction]})
    old_events = DailyPlanEvent.query.filter_by(user_id=user.id).count()
    old_skips = LessonSkip.query.filter_by(user_id=user.id).count()
    response = client.post('/api/daily-plan/skip-lesson', json={'lesson_id': lessons[2].id})
    assert response.status_code == 400, response.json
    assert response.json['error'] == 'correction_required'
    response = client.post('/api/daily-plan/events', json={
        'event_type': 'slot_skipped', 'step_kind': 'curriculum', 'reason_text': 'too_hard'})
    assert response.status_code == 400, response.json
    assert response.json['error'] == 'correction_required'
    assert DailyPlanEvent.query.filter_by(user_id=user.id).count() == old_events
    assert LessonSkip.query.filter_by(user_id=user.id).count() == old_skips


def test_reconciler_is_applied_in_unified_plan_without_changing_frozen_snapshot(native_app, course, monkeypatch):
    from app.daily_plan import plan, snapshot
    from app.daily_plan.linear import progression
    from app.utils.db import db
    from app.utils.request_cache import _get_cache
    user, lessons, _rows = course
    original = [card('curriculum', lessons[2].id), card('srs', completed=True, reviewed=12),
                card('reading', completed=True, pages_read=8), card('curriculum', lessons[3].id)]
    for item in original:
        item['title'] = item['id']
        item['completion_signal'] = 'lesson_completed'
    frozen = {'items': deepcopy(original)}
    saved = deepcopy(frozen)
    monkeypatch.setattr(progression, 'find_next_lesson_state', lambda uid, database: (lessons[2], None))
    monkeypatch.setattr(progression, 'get_user_level_progress',
                        lambda *args, **kwargs: NS(level='A1', percent=50, lessons_remaining_in_level=2))
    monkeypatch.setattr(plan, '_compute_module_progress', lambda *args: None)
    monkeypatch.setattr(plan, 'build_optional', lambda *args, **kwargs: ([], False))
    monkeypatch.setattr(plan, 'build_setup', lambda *args: [])
    monkeypatch.setattr(snapshot, 'resolve_snapshot_for_today', lambda *args: frozen)
    monkeypatch.setattr(snapshot, 'overlay_completion', lambda *args: deepcopy(original))
    _get_cache().clear()
    first = plan.get_daily_plan(user.id, db)
    second = plan.get_daily_plan(user.id, db)
    assert first['required'] == second['required']
    assert len(first['required']) == 5
    assert first['required'][1]['data']['reviewed'] == 12
    assert first['required'][2]['data']['pages_read'] == 8
    assert first['required'][1]['completed'] and first['required'][2]['completed']
    assert first['required'][3]['data']['quiz_phase'] == 'correction'
    assert first['required'][4]['blocked']
    assert frozen == saved


def test_assisted_completion_is_seen_by_snapshot_and_today_history(native_app, course):
    from app.daily_plan.items.curriculum import _curriculum_done_today, get_curriculum_lessons_completed_today
    from app.daily_plan.snapshot import _curriculum_lesson_done_today
    from app.utils.db import db
    user, lessons, rows = course
    row = rows[2]
    row.status = 'completed'
    row.data = {'quiz_correction': dict(row.data['quiz_correction'], status='completed')}
    row.completed_at = row.last_activity = datetime.now(UTC).replace(tzinfo=None)
    db.session.commit()
    assert _curriculum_done_today(user.id, db)
    assert _curriculum_lesson_done_today(user.id, lessons[2].id, db)
    assert lessons[2].id in [item.id for item in get_curriculum_lessons_completed_today(user.id, db)]


def test_unreadable_attempt_date_does_not_restart_a_pause_every_day(project):
    state, db = project
    state['created_at'] = 'legacy-unreadable-date'
    result, _ = qc.reconcile_quiz_corrections(7, db, [card('curriculum', 3), card('srs'), card('reading')], [])
    assert result[0]['data']['quiz_phase'] == 'correction'
