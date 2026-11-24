"""A short public entry, without changing existing comprehensive attempts."""
from typing import Any
from unittest.mock import patch
from datetime import timedelta

import pytest
from flask_login import login_user
from app.onboarding import placement_engine as engine
from app.onboarding.placement_models import PlacementAttempt, PlacementGuest, utcnow
from tests.test_placement_v2 import bank, complete

pytestmark = pytest.mark.smoke


def finish_starter(actor: int | str, correct: bool = True) -> dict[str, Any]:
    value = engine.start(actor, 'quick', scope='starter')
    while value['status'] == 'active':
        value = engine.answer(actor, value['id'], value['question']['id'], 'A correct answer' if correct else '', not correct)
    return value


@pytest.mark.parametrize('correct,level', [(False, 'A1'), (True, 'C1')])
def test_starter_uses_ten_unique_choice_questions_starting_at_a1(db_session: Any, test_user: Any, bank: Any, correct: bool, level: str) -> None:
    value = engine.start(test_user.id, 'quick', scope='starter')
    row = db_session.get(PlacementAttempt, value['id'])
    assert row.state['level'] == 0
    assert value['question_count'] == 10
    # Shipped mobile clients still recognise this quick upper bound. An early
    # completed result may contain fewer answers, as their validators permit.
    assert value['mode'] == 'quick' and value['max_questions'] == 14
    while value['status'] == 'active':
        q = value['question']
        assert q['input'] == 'choice' and q['skill'] in ('grammar', 'vocabulary')
        assert q['audio_url'] is None and q['passage'] is None
        value = engine.answer(test_user.id, value['id'], q['id'], 'A correct answer' if correct else '', not correct)
    row = db_session.get(PlacementAttempt, value['id'])
    assert len({q['id'] for q in row.state['asked']}) == 10
    assert value['answered'] == value['result']['total'] == 10
    assert value['result']['recommended_level'] == level
    domains = {d['id']: d['total'] for d in value['result']['domains']}
    assert domains == {'grammar': 5, 'vocabulary': 5, 'reading': 0, 'listening': 0, 'writing': 0}
    assert value['applied'] is False


def test_only_one_domain_correct_does_not_promote_a_novice(db_session: Any, test_user: Any, bank: Any) -> None:
    value = engine.start(test_user.id, 'quick', scope='starter')
    while value['status'] == 'active':
        knows = value['question']['skill'] == 'grammar'
        value = engine.answer(test_user.id, value['id'], value['question']['id'], 'A correct answer' if knows else '', not knows)
    assert value['result']['correct_count'] == 5
    assert value['result']['recommended_level'] == 'A1'


def test_starter_retry_resume_and_an_existing_long_test_are_not_overwritten(db_session: Any, test_user: Any, bank: Any) -> None:
    value = engine.start(test_user.id, 'quick', scope='starter')
    assert engine.start(test_user.id, 'quick') == value
    assert engine.start(test_user.id, 'quick', scope='starter') == value
    qid = value['question']['id']
    next_question = engine.answer(test_user.id, value['id'], qid, '', True)
    assert engine.answer(test_user.id, value['id'], qid, '', True) == next_question
    engine.abandon(test_user.id, value['id'])
    legacy = engine.start(test_user.id, 'quick')
    with pytest.raises(engine.PlacementError, match='active_attempt'):
        engine.start(test_user.id, 'quick', scope='starter')
    assert engine.status(test_user.id)['active']['id'] == legacy['id']


@pytest.mark.parametrize('scope', [False, [], {}, 'unknown'])
def test_invalid_scope_cannot_change_assessment_policy(db_session: Any, test_user: Any, bank: Any, scope: Any) -> None:
    with pytest.raises(engine.PlacementError, match='invalid_scope'):
        engine.start(test_user.id, 'quick', scope=scope)


def test_public_page_is_direct_and_advanced_modes_remain_available(client: Any, bank: Any) -> None:
    guest = client
    page = guest.get('/placement?start=1')
    assert b'data-simple="true"' in page.data and b'data-force-start="true"' in page.data
    assert b'id="placement-chooser" aria-label=' in page.data
    assert b'name="flow" value="starter"' in page.data
    advanced = guest.get('/placement?advanced=1')
    assert b'data-simple="false"' in advanced.data


def test_profile_retains_the_two_comprehensive_modes(authenticated_client: Any, bank: Any) -> None:
    profile = authenticated_client.get('/placement')
    assert b'data-simple="false"' in profile.data
    assert b'data-mode="quick"' in profile.data and b'data-mode="detailed"' in profile.data


def test_explicit_starter_registration_selects_level_and_skips_duplicate_onboarding(client: Any, db_session: Any, bank: Any) -> None:
    from uuid import uuid4
    from app.auth.models import User
    client.get('/placement?start=1')
    actor = PlacementGuest.query.one().key
    value = finish_starter(actor)
    chosen = client.post('/placement/continue', data={'flow': 'starter'})
    suffix = uuid4().hex[:10]
    with patch('app.auth.welcome_email.enqueue_welcome_email'):
        response = client.post(chosen.location, data={'username': 'starter_'+suffix,
            'email': suffix+'@example.com', 'password': 'Xk9$mP2vL!qw', 'password2': 'Xk9$mP2vL!qw'})
    assert response.status_code == 302
    user = User.query.filter_by(username='starter_'+suffix).one()
    row = db_session.get(PlacementAttempt, value['id'])
    assert row.user_id == user.id and row.applied_at is not None
    assert user.onboarding_completed and user.onboarding_level == 'C1'
    assert '/onboarding' in response.location
    follow = client.get(response.location)
    assert follow.status_code == 302 and '/onboarding' not in follow.location


def test_starter_login_preserves_today_when_learning_already_started(app: Any, client: Any, db_session: Any, test_user: Any, bank: Any) -> None:
    client.get('/placement?start=1')
    value = finish_starter(PlacementGuest.query.one().key)
    destination = client.post('/placement/continue', data={'flow': 'starter', 'destination': 'login'})
    assert 'dashboard' in destination.location
    with client.session_transaction() as saved:
        guest_session = dict(saved)
    with app.test_request_context('/login'):
        from flask import session
        session.update(guest_session)
        with patch('app.utils.activity_tracker.has_learning_activity', return_value=True):
            login_user(test_user)
    assert test_user.placement_pending_level == 'C1'
    assert test_user.onboarding_level != 'C1'
    assert db_session.get(PlacementAttempt, value['id']).applied_at is not None


def test_short_handoff_cannot_auto_apply_a_legacy_comprehensive_result(client: Any, db_session: Any, bank: Any) -> None:
    client.get('/placement')
    complete(PlacementGuest.query.one().key)
    client.post('/placement/continue', data={'flow': 'starter'})
    with client.session_transaction() as saved:
        assert 'placement_apply_after_login' not in saved


def test_more_recent_applied_account_result_wins_without_losing_guest_result(app: Any, client: Any, db_session: Any, test_user: Any, bank: Any) -> None:
    client.get('/placement')
    guest_result = finish_starter(PlacementGuest.query.one().key)
    db_session.get(PlacementAttempt, guest_result['id']).completed_at = utcnow() - timedelta(days=2)
    account_result = complete(test_user.id, correct=False)
    own = db_session.get(PlacementAttempt, account_result['id'])
    own.applied_at = utcnow()
    client.post('/placement/continue', data={'flow': 'starter'})
    with client.session_transaction() as saved:
        state = dict(saved)
    with app.test_request_context('/login'):
        from flask import session
        session.update(state)
        login_user(test_user)
    imported = db_session.get(PlacementAttempt, guest_result['id'])
    assert imported.user_id == test_user.id and imported.applied_at is None
    assert own.applied_at is not None
