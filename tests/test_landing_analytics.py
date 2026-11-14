"""First-party preview events, signup attribution, and session-cohort reporting."""
import secrets
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.admin.services.landing_metrics import _counts, get_landing_overview
from app.auth.models import User
from app.landing.analytics import LandingVisit, get_or_create_visit, link_registration


def _visit(client, db_session):
    assert client.get('/?utm_source=preview_test&utm_medium=local').status_code == 200
    with client.session_transaction() as session:
        visit_id = session['landing_visit_id']
    return db_session.get(LandingVisit, visit_id)


def _event(client, visit, event, **extra):
    return client.post('/landing/events', json={
        'event': event, 'preview_id': visit.preview_id, **extra,
    })


def test_reload_keeps_session_and_variant(client, db_session):
    visit = _visit(client, db_session)
    assert len(visit.id) == 43
    assert visit.source == 'preview_test'
    assert visit.medium == 'local'
    assert client.get('/?utm_source=different').status_code == 200
    with client.session_transaction() as session:
        assert session['landing_visit_id'] == visit.id
    db_session.refresh(visit)
    assert visit.source == 'preview_test'


def test_variant_and_attribution_are_bounded_and_session_owned(app, db_session):
    with app.test_request_context('/'):
        from flask import session
        session['acq_meta'] = {'utm_source': 'x' * 500, 'utm_medium': ['invalid']}
        visit = get_or_create_visit('intro_am')
        assert visit.source == 'x' * 200
        assert visit.medium is None
        assert get_or_create_visit('can_swim').preview_id == 'intro_am'
        with pytest.raises(ValueError):
            get_or_create_visit('arbitrary')


def test_events_are_idempotent_and_keep_first_answer(client, db_session):
    visit = _visit(client, db_session)
    assert _event(client, visit, 'preview_started').status_code == 204
    assert _event(client, visit, 'preview_answered', correct=False).status_code == 204
    db_session.refresh(visit)
    started, answered = visit.started_at, visit.answered_at
    assert _event(client, visit, 'preview_started').status_code == 204
    assert _event(client, visit, 'preview_answered', correct=True).status_code == 204
    assert _event(client, visit, 'registration_clicked').status_code == 204
    db_session.refresh(visit)
    assert visit.first_correct is False
    assert visit.started_at == started
    assert visit.answered_at == answered
    assert visit.registration_clicked_at is not None
    assert visit.registered_at is None


def test_answer_arriving_before_start_still_records_logical_start(client, db_session):
    visit = _visit(client, db_session)
    assert _event(client, visit, 'preview_answered', correct=True).status_code == 204
    db_session.refresh(visit)
    assert visit.started_at == visit.answered_at


def test_return_to_signup_after_answer_records_the_qualifying_open(client, db_session):
    visit = _visit(client, db_session)
    assert client.get('/register?level=A1&entry=preview').status_code == 200
    db_session.refresh(visit)
    early_open = visit.registration_opened_at
    assert _event(client, visit, 'preview_answered', correct=True).status_code == 204
    assert client.get('/register?level=A1&entry=preview').status_code == 200
    db_session.refresh(visit)
    assert visit.registration_opened_at >= visit.answered_at >= early_open
    assert _counts([visit])['opened'] == 1


@pytest.mark.parametrize('payload', [
    None, [], 'preview_started', {},
    {'event': []}, {'event': 'unknown', 'preview_id': 'intro_am'},
    {'event': 'preview_started', 'preview_id': []},
    {'event': 'preview_answered', 'preview_id': 'intro_am', 'correct': 1},
    {'event': 'preview_answered', 'preview_id': 'intro_am', 'correct': 'false'},
    {'event': 'preview_started', 'preview_id': 'intro_am', 'correct': True},
    {'event': 'preview_started', 'preview_id': 'intro_am', 'utm_source': 'spoofed'},
    {'event': 'preview_started', 'preview_id': 'intro_am', 'answer': 'secret'},
    {'event': 'preview_started', 'preview_id': 'intro_am', 'user_id': 1},
    {'event': 'preview_started', 'preview_id': 'intro_am', 'timestamp': '2026-01-01'},
])
def test_endpoint_rejects_unbounded_payload(client, payload):
    assert client.post('/landing/events', json=payload).status_code == 400


def test_events_require_matching_session_and_rendered_variant(client, app, db_session):
    visit = _visit(client, db_session)
    assert _event(app.test_client(), visit, 'preview_started').status_code == 403
    other_variant = 'can_swim' if visit.preview_id != 'can_swim' else 'intro_am'
    assert client.post('/landing/events', json={
        'event': 'preview_started', 'preview_id': other_variant,
    }).status_code == 403
    db_session.refresh(visit)
    assert visit.started_at is None


def test_event_endpoint_uses_global_csrf(client, app, db_session, monkeypatch):
    visit = _visit(client, db_session)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    assert _event(client, visit, 'preview_started').status_code == 400
    from bs4 import BeautifulSoup
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    token = page.select_one('meta[name="csrf-token"]')['content']
    assert client.post('/landing/events', json={
        'event': 'preview_started', 'preview_id': visit.preview_id,
    }, headers={'X-CSRFToken': token}).status_code == 204


def test_actual_registration_links_funnel_and_keeps_inflight_event_session(client, db_session):
    visit = _visit(client, db_session)
    assert _event(client, visit, 'preview_answered', correct=True).status_code == 204
    assert client.get('/register?level=A1&entry=preview').status_code == 200
    db_session.refresh(visit)
    opened = visit.registration_opened_at
    assert opened is not None
    suffix = uuid.uuid4().hex[:10]
    response = client.post('/register?level=A1&entry=preview', data={
        'username': f'preview_{suffix}', 'email': f'preview_{suffix}@example.com',
        'password': 'StrongPreview#2947', 'password2': 'StrongPreview#2947',
    })
    assert response.status_code == 302
    db_session.refresh(visit)
    user = db_session.get(User, visit.user_id)
    assert user is not None
    assert user.email == f'preview_{suffix}@example.com'
    assert user.onboarding_level == 'A1'
    assert user.acquisition_meta['entry_point'] == 'landing_preview'
    assert visit.registered_at >= opened
    assert user.acquisition_meta['utm_source'] == 'preview_test'
    # fetch(keepalive) may complete after signup has logged the user in.
    assert _event(client, visit, 'registration_clicked').status_code == 204
    totals = get_landing_overview(db_session)['totals']
    assert totals['registered'] >= 1


@pytest.mark.parametrize('url', [
    '/register', '/register?entry=preview',
    '/register?level=B1&entry=preview', '/register?level=invalid&entry=preview',
])
def test_ordinary_signup_get_does_not_claim_preview_open(client, db_session, url):
    visit = _visit(client, db_session)
    assert client.get(url).status_code == 200
    db_session.refresh(visit)
    assert visit.registration_opened_at is None


def test_missing_analytics_table_does_not_rollback_pending_user(app, db_session):
    suffix = uuid.uuid4().hex[:10]
    with app.test_request_context('/'):
        from flask import session
        session['landing_visit_id'] = secrets.token_urlsafe(32)
        db_session.execute(text('ALTER TABLE landing_visits RENAME TO landing_visits_unavailable'))
        try:
            user = User(username=f'savepoint_{suffix}', email=f'{suffix}@example.com', active=True)
            user.set_password('StrongPreview#2947')
            db_session.add(user)
            db_session.flush()
            link_registration(user)
            # Querying after the missing-table error proves the outer transaction
            # is still usable, with the actual pending User still present.
            assert db_session.get(User, user.id) is user
            assert db_session.query(User).filter_by(username=user.username).one().id == user.id
        finally:
            db_session.execute(text('ALTER TABLE landing_visits_unavailable RENAME TO landing_visits'))


def test_metrics_use_visit_created_cohorts_and_ordered_steps(db_session):
    now = datetime.utcnow()
    prefix = uuid.uuid4().hex
    source = f'cohort_{prefix}'
    base = dict(preview_id='intro_am', source=source)
    rows = [
        LandingVisit(id=secrets.token_urlsafe(32), created_at=now - timedelta(days=1),
                     started_at=now, answered_at=now, registration_opened_at=now,
                     registered_at=now, first_correct=False, **base),
        # A registration without the demo sequence is a landing registration only.
        LandingVisit(id=secrets.token_urlsafe(32), created_at=now,
                     registered_at=now, **base),
        # Opened signup before answering: not an ordered preview conversion.
        LandingVisit(id=secrets.token_urlsafe(32), created_at=now, started_at=now,
                     answered_at=now, registration_opened_at=now - timedelta(seconds=1),
                     registered_at=now, first_correct=True, **base),
        # Old landing, recent registration stays outside the selected cohort.
        LandingVisit(id=secrets.token_urlsafe(32), created_at=now - timedelta(days=40),
                     started_at=now, answered_at=now, registration_opened_at=now,
                     registered_at=now, **base),
    ]
    db_session.add_all(rows)
    db_session.commit()
    overview = get_landing_overview(db_session, days=7)
    row = next(row for row in overview['by_source'] if row['source'] == source)
    assert (row['visits'], row['started'], row['answered'], row['opened'], row['registered']) == (3, 2, 2, 1, 1)
    assert row['all_registered'] == 3
    assert row['correct_pct'] == 50.0
    assert row['conversion_pct'] == 33.3


def test_empty_denominators_are_not_zero_percent():
    counts = _counts([])
    assert counts['visits'] == 0
    assert counts['conversion_pct'] is None
    assert counts['correct_pct'] is None
    assert counts['registered_pct'] is None


def test_admin_shows_session_units_and_local_demo_funnel(admin_client, db_session):
    response = admin_client.get('/admin/acquisition')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Демо на лендинге: до регистрации' in html
    assert 'сессия браузера, а не человек' in html
    assert 'независимо от GA4' in html
