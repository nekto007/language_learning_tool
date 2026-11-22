"""Weekly learner goal: meaningful evidence, shared exclusions and safe admin edits."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from app.admin.services.growth_service import (
    EXCLUSIONS_KEY, acquisition, build_report, exclusion_reason, get_report, load_overrides,
)
from app.admin.site_settings import get_site_setting, set_site_setting
from app.auth.models import User

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


def person(uid, *, age=20, **fields):
    return {'id': uid, 'username': f'learner_{uid}', 'email': '', 'is_admin': False,
            'active': True, 'created_at': NOW - timedelta(days=age), 'acquisition_meta': {},
            'onboarding_level': 'A1', **fields}


def work(uid, age=1, **fields):
    return {'user_id': uid, 'at': NOW - timedelta(days=age), 'kind': 'course', 'title': 'Quiz', **fields}


def path(uid, *, age=2, completed=False, **fields):
    return {'user_id': uid, 'lesson_id': 10, 'started_at': NOW - timedelta(days=age),
            'last_activity': NOW - timedelta(days=age), 'completed_at': NOW - timedelta(days=age) if completed else None,
            'status': 'completed' if completed else 'in_progress', 'title': 'First lesson', 'level': 'A1',
            'is_test_out': False, **fields}


def test_same_clean_population_in_goal_trend_sources_bottlenecks_and_rows():
    users = [person(1, is_admin=True), person(2, username='ios_audit_20261122_ca65eb'),
             person(3, acquisition_meta={'utm_source': 'family'}), person(4),
             person(5, username='latest_student'), person(6, username='protest')]
    overrides = {'3': {'excluded': True, 'reason': 'family'}}
    report = build_report(users, [path(2), path(3), path(4)],
                          [work(i) for i in (1, 2, 3, 5, 6)], now=NOW, overrides=overrides)
    assert report['total'] == 3
    assert report['active7'] == report['trend'][-1]['count'] == 2
    assert {u['id'] for u in report['learners']} == {4, 5, 6}
    assert len(report['excluded']) == 3
    assert sum(s['active7'] for s in report['sources']) == 2
    assert not any(s['label'] == 'family' for s in report['sources'])
    assert report['bottlenecks'][0]['user_ids'] == [4]


def test_precise_week_boundaries_deduplication_and_growth_decomposition():
    users = [person(i, age=40) for i in range(1, 6)]
    events = [work(1, 7), work(1, 8), work(1, 1, kind='words'), work(1, 1, kind='reading'),
              work(2, 8), work(3, 1), work(3, 30), work(4, 1), work(5, 15),
              work(5, -1), work(5, 50)]
    report = build_report(users, [], events, now=NOW)
    assert report['active7'] == 3  # Boundary included, multiple modules count once.
    assert report['previous7'] == 2
    assert (report['new_active'], report['retained'], report['returned'], report['lost']) == (1, 1, 1, 1)
    assert report['delta'] == report['new_active'] + report['returned'] - report['lost']
    assert report['trend'][-1]['count'] == 3
    assert report['trend'][-2]['count'] == 2
    learner = next(u for u in report['learners'] if u['id'] == 1)
    assert learner['days7'] == 2
    assert next(u for u in report['learners'] if u['id'] == 5)['last'] == NOW - timedelta(days=15)


def test_late_first_visit_is_not_return_and_immature_cohorts_are_not_failures():
    users = [person(1, age=10), person(2, age=10), person(3, age=.5), person(4, age=20)]
    events = [work(1, 7), work(2, 10), work(2, 9), work(3, .1), work(4, 12)]
    report = build_report(users, [], events, now=NOW)
    assert report['metrics']['first24']['eligible'] == 3
    assert report['metrics']['return7'] == {'count': 1, 'eligible': 3, 'percent': 33.3}
    assert report['metrics']['week2'] == {'count': 1, 'eligible': 1, 'percent': 100.0}


def test_openings_and_test_out_do_not_count_as_learning():
    report = build_report([person(1), person(2)],
                          [path(1), path(2, completed=True, is_test_out=True)], [], now=NOW)
    assert report['active7'] == 0
    assert report['learners'][0]['completed'] == 0


def test_failures_are_learning_but_resolved_attempts_stop_being_blockers():
    events = [work(1, 3, graded=True, lesson_id=10, passed=False),
              work(1, 2, graded=True, lesson_id=10, passed=False)]
    report = build_report([person(1)], [path(1)], events, now=NOW)
    assert report['active7'] == 1
    assert report['learners'][0]['state'] == 'errors'
    resolved = build_report([person(1)], [path(1, age=1, completed=True)],
                            [*events, work(1, 1, graded=True, lesson_id=10, passed=True)], now=NOW)
    assert resolved['learners'][0]['state'] == 'active'
    assert not resolved['bottlenecks']


def test_later_work_in_another_module_is_not_an_abandoned_lesson():
    report = build_report([person(1)], [path(1)], [work(1, 1, kind='reading')], now=NOW)
    assert not report['bottlenecks']
    assert report['learners'][0]['state'] == 'active'


def test_source_uses_evidence_and_never_invents_search_or_direct():
    assert acquisition(None)['label'] == 'Источник не сохранён'
    assert acquisition({'referrer': 'https://llt-english.com/login'})['evidence'] == 'Нет данных'
    source = acquisition({'referrer': 'https://www.google.com/search?q=private', 'landing_path': '/word/1?token=secret'})
    assert source['label'] == 'www.google.com'
    assert source['landing'] == '/word/1'
    assert 'private' not in json.dumps(source)
    assert acquisition({'utm_source': 'teacher', 'referrer': 'https://www.google.com'})['label'] == 'teacher'


def test_known_audit_can_be_restored_but_admin_stays_out():
    user = person(1, username='audit_android_1122160302')
    assert exclusion_reason(user, {})
    assert not exclusion_reason(user, {'1': {'excluded': False, 'reason': ''}})
    assert exclusion_reason({**user, 'is_admin': True}, {'1': {'excluded': False}}) == 'Администратор'


def make_user(session, **fields):
    name = f'growth_{uuid4().hex[:10]}'
    user = User(username=name, email=f'{name}@example.test', is_admin=False,
                created_at=datetime.now(UTC) - timedelta(days=20), **fields)
    user.set_password('test-password')
    session.add(user)
    session.flush()
    return user


def test_database_counts_real_work_but_not_login_opening_or_empty_session(db_session, test_lesson_quiz):
    from app.curriculum.models import LessonAttempt, LessonProgress
    from app.study.models import GameScore, StudySession

    now = datetime.now(UTC)
    empty, graded, words, game = [make_user(db_session) for _ in range(4)]
    db_session.add_all([
        StudySession(user_id=empty.id, start_time=now),
        LessonProgress(user_id=empty.id, lesson_id=test_lesson_quiz.id, status='in_progress',
                       started_at=now, last_activity=now),
        LessonAttempt(user_id=graded.id, lesson_id=test_lesson_quiz.id, attempt_number=1,
                      started_at=now, completed_at=now, score=0, passed=False, total_questions=3),
        StudySession(user_id=words.id, start_time=now - timedelta(minutes=5), end_time=now, words_studied=4),
        GameScore(user_id=game.id, game_type='matching', pairs_matched=2, date_achieved=now),
    ])
    db_session.flush()
    report = get_report(db_session, now=now + timedelta(seconds=1))
    rows = {u['id']: u for u in report['learners']}
    assert not rows[empty.id]['active7']
    assert all(rows[u.id]['active7'] for u in (graded, words, game))
    assert not report['missing']


def test_reading_needs_time_and_actual_progress(db_session, test_chapter):
    from app.books.reading_session import UserReadingSession

    now = datetime.now(UTC)
    quick, stationary, reader = [make_user(db_session) for _ in range(3)]
    for user, seconds, delta in ((quick, 20, .2), (stationary, 90, 0), (reader, 90, .2)):
        db_session.add(UserReadingSession(user_id=user.id, chapter_id=test_chapter.id,
                                         started_at=now - timedelta(seconds=seconds), ended_at=now,
                                         start_offset_pct=0, offset_delta=delta))
    db_session.flush()
    rows = {u['id']: u for u in get_report(db_session, now=now + timedelta(seconds=1))['learners']}
    assert not rows[quick.id]['active7'] and not rows[stationary.id]['active7']
    assert rows[reader.id]['active7']


def test_admin_page_and_reversible_exclusions_share_same_population(admin_client, db_session):
    user = make_user(db_session, acquisition_meta={'utm_source': 'teacher-pilot', 'landing_path': '/courses/'})
    db_session.commit()
    page = admin_client.get('/admin/growth')
    assert page.status_code == 200
    assert page.headers['Cache-Control'] == 'private, no-store'
    assert user.username in page.get_data(as_text=True)
    response = admin_client.post(f'/admin/growth/accounts/{user.id}/visibility',
                                 data={'action': 'exclude', 'reason': 'family'})
    assert response.status_code == 302
    assert load_overrides(db_session)[str(user.id)]['reason'] == 'family'
    assert db_session.get(User, user.id) is not None
    overview = admin_client.get('/admin/growth').get_data(as_text=True)
    assert user.username not in overview and 'teacher-pilot' not in overview
    settings = admin_client.get('/admin/growth?view=exclusions').get_data(as_text=True)
    assert user.username in settings and 'Семья' in settings
    admin_client.post(f'/admin/growth/accounts/{user.id}/visibility', data={'action': 'include'})
    assert user.username in admin_client.get('/admin/growth').get_data(as_text=True)


def test_filters_do_not_change_goal_and_id_search_is_exact(admin_client, db_session):
    user = make_user(db_session, acquisition_meta={'utm_source': 'test-source'})
    db_session.commit()
    page = BeautifulSoup(admin_client.get(f'/admin/growth?view=exclusions&q={user.id}').data, 'html.parser')
    assert len(page.select('tr[id^="account-"]')) == 1
    filtered = admin_client.get('/admin/growth?source=missing').get_data(as_text=True)
    assert user.username not in filtered
    assert 'Нет учеников по этим условиям' in filtered


def test_bottleneck_link_has_exact_same_members_as_its_counter(admin_client, db_session, test_lesson_quiz):
    from app.curriculum.models import LessonProgress

    recent = make_user(db_session)
    old = make_user(db_session)
    old.created_at = datetime.now(UTC) - timedelta(days=60)
    now = datetime.now(UTC) - timedelta(days=2)
    for user in (recent, old):
        db_session.add(LessonProgress(user_id=user.id, lesson_id=test_lesson_quiz.id,
                                     status='in_progress', started_at=now, last_activity=now))
    db_session.commit()
    report = get_report(db_session)
    stop = next(b for b in report['bottlenecks'] if b['id'] == test_lesson_quiz.id)
    assert stop['user_ids'] == [recent.id]
    page = admin_client.get(f'/admin/growth?lesson_id={test_lesson_quiz.id}').get_data(as_text=True)
    assert recent.username in page and old.username not in page


@pytest.mark.parametrize('data', [{'action': 'delete'}, {'action': 'exclude', 'reason': 'invented'}])
def test_invalid_exclusions_do_not_mutate_settings(admin_client, db_session, data):
    user = make_user(db_session)
    db_session.commit()
    before = get_site_setting(EXCLUSIONS_KEY, '{}', db_session=db_session)
    assert admin_client.post(f'/admin/growth/accounts/{user.id}/visibility', data=data).status_code == 400
    assert get_site_setting(EXCLUSIONS_KEY, '{}', db_session=db_session) == before


def test_corrupt_exclusion_settings_do_not_show_false_zero_goal(admin_client, db_session):
    set_site_setting(EXCLUSIONS_KEY, 'broken', db_session=db_session)
    db_session.commit()
    response = admin_client.get('/admin/growth')
    assert response.status_code == 503
    assert 'Не удалось рассчитать отчёт' in response.get_data(as_text=True)  # noqa: RUF001


@pytest.mark.parametrize('method,path', [('get', '/admin/growth'), ('get', '/admin/growth?view=exclusions'),
                                        ('post', '/admin/growth/accounts/1/visibility')])
def test_report_and_account_edits_require_admin(client, method, path):
    assert getattr(client, method)(path).status_code == 302


def test_exclusion_post_requires_csrf(admin_client, app, db_session):
    user = make_user(db_session)
    db_session.commit()
    original = app.config['WTF_CSRF_ENABLED']
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        response = admin_client.post(f'/admin/growth/accounts/{user.id}/visibility',
                                     data={'action': 'exclude', 'reason': 'test'},
                                     headers={'Accept': 'application/json'})
        assert response.status_code == 400
        assert str(user.id) not in load_overrides(db_session)
    finally:
        app.config['WTF_CSRF_ENABLED'] = original
