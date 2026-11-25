"""Edit a synthetic rendition and exercise the public demo's existing contract."""

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.achievements.models import StreakEvent, UserStatistics
from app.admin.audit import AdminAuditLog
from app.admin.site_settings import SiteSettings
from app.auth.models import User
from app.curriculum.models import LessonProgress
from app.landing.analytics import LandingVisit
from app.landing.previews import PREVIEWS, PREVIEWS_BY_ID
from tests.admin.test_materials import _page
from tests.api.test_grammar_lab_disputes import browser

INDEX = '/admin/public-pages/demo'
DEMO_ID = PREVIEWS[0]['id']
URL = f'{INDEX}/{DEMO_ID}'


def _fields(page: BeautifulSoup) -> dict[str, str]:
    form = page.select_one('input[name=revision]').find_parent('form')
    return {
        field['name']: field.get_text() if field.name == 'textarea' else field['value']
        for field in form.select('input[name]:not([type=radio]), input[type=radio]:checked, textarea[name]')
    }


def _landing(client: FlaskClient) -> BeautifulSoup:
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    return _page(client.get('/'))


def test_publish_demo_preserves_existing_guest_visit_and_scores_only_the_displayed_answer(
    app: Flask, admin_client: FlaskClient, db_session: scoped_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    monkeypatch.setattr('app.landing.routes.pick_preview', lambda: PREVIEWS[0])
    guest = app.test_client()
    old = _landing(guest)
    old_card = old.select_one('#landing-preview')
    assert old_card['data-preview-id'] == DEMO_ID
    before = (LessonProgress.query.count(), UserStatistics.query.count(), StreakEvent.query.count())
    with guest.session_transaction() as guest_session:
        visit_id = guest_session['landing_visit_id']

    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    navigation = _page(admin_client.get('/admin/public-pages'))
    assert navigation.select_one(f'a[href="{INDEX}"]')
    listing = _page(admin_client.get(INDEX))
    assert [node['href'].rsplit('/', 1)[-1] for node in listing.select(f'a[href^="{INDEX}/"]')] == list(PREVIEWS_BY_ID)
    fields = _fields(_page(admin_client.get(URL)))
    candidate = {
        **fields,
        'prompt': 'Synthetic ___ vessel.', 'instruction': 'Synthetic form instruction.',
        'option0': 'fills', 'option1': 'paint', 'option2': 'see', 'correct_option': '1',
        'explanation': 'Synthetic feedback for the selected option.', 'action': 'preview',
    }
    missing_csrf = {key: value for key, value in candidate.items() if key != 'csrf_token'}
    denied = admin_client.post(URL, data=missing_csrf, headers={'Accept': 'application/json'})
    assert denied.status_code == 400 and denied.json['csrf_expired']
    proof = _page(admin_client.post(URL, data=candidate))
    assert proof.select_one('input[name=preview_token]')['value']
    assert candidate['prompt'] in proof.text and candidate['explanation'] in proof.text
    assert 'paint · верно' in proof.text
    assert db_session.get(SiteSettings, f'landing_demo.{DEMO_ID}') is None
    assert _landing(guest).select_one('#landing-preview')['data-correct'] == old_card['data-correct']

    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    publish = {**_fields(proof), 'action': 'publish'}
    assert admin_client.post(URL, data={**publish, 'correct_option': '0'}).status_code == 409
    assert admin_client.post(URL, data=publish).status_code == 303
    assert admin_client.post(URL, data=publish).status_code == 409
    assert AdminAuditLog.query.filter_by(action=f'landing_demo.publish.{DEMO_ID}').count() == 1

    # A page opened earlier still grades client-side with its own displayed options and key.
    old_options = [node['value'] for node in old_card.select('input[type=radio]')]
    assert old_card['data-correct'] in old_options and old_card['data-correct'] != 'paint'
    g.pop('_login_user', None)
    event = guest.post('/landing/events', json={
        'event': 'preview_answered', 'preview_id': DEMO_ID, 'correct': True,
    }, headers={'X-CSRFToken': old.select_one('meta[name=csrf-token]')['content']})
    assert event.status_code == 204
    live = _landing(guest).select_one('#landing-preview')
    assert live['data-preview-id'] == DEMO_ID
    assert live['data-correct'] == 'paint'
    assert live['data-explanation'] == candidate['explanation']
    assert live.legend.get_text(strip=True) == candidate['prompt']
    assert [node['value'] for node in live.select('input[type=radio]')] == ['fills', 'paint', 'see']
    assert live.select_one('#preview-register')['href'].endswith('?level=A1&entry=preview')
    with guest.session_transaction() as guest_session:
        assert guest_session['landing_visit_id'] == visit_id
    assert db_session.get(LandingVisit, visit_id).first_correct is True
    assert (LessonProgress.query.count(), UserStatistics.query.count(), StreakEvent.query.count()) == before


@pytest.mark.parametrize('overrides', [
    {'prompt': 'No synthetic blank.'},
    {'prompt': 'Synthetic ___ and ___.'},
    {'prompt': 'Synthetic ____ extra underscore.'},
    {'option0': 'Duplicate', 'option1': 'duplicate'},
    {'correct_option': 'missing'},
    {'correct_option': '3'},
])
def test_invalid_demo_has_no_publish_token(admin_client: FlaskClient, overrides: dict) -> None:
    fields = _fields(_page(admin_client.get(URL)))
    result = admin_client.post(URL, data={**fields, **overrides, 'action': 'preview'})
    assert result.status_code == 422
    assert 'value="publish"' not in result.text


def test_demo_permission_and_unknown_id(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    assert admin_client.get(f'{INDEX}/synthetic_new').status_code == 404
    test_user.is_moderator = True
    db_session.commit()
    moderator, _ = browser(app, test_user)
    g.pop('_login_user', None)
    assert moderator.get(URL).status_code in (302, 403)
    assert moderator.post(URL, data={'action': 'publish'}).status_code in (302, 403)
