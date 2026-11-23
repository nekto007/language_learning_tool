"""The real layouts deliver goals with GA disabled and keep admins excluded."""
import pytest


@pytest.fixture
def production_metrics(app, monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', False)
    monkeypatch.setitem(app.config, 'DEBUG', False)
    monkeypatch.setitem(app.config, 'YANDEX_METRIKA_ID', '114597985')
    monkeypatch.setitem(app.config, 'GOOGLE_ANALYTICS_ID', '')


@pytest.mark.usefixtures('production_metrics')
@pytest.mark.parametrize('path,replay', [('/', True), ('/register', False), ('/privacy', False)])
def test_actual_layouts_load_counter_with_matching_csp(client, path, replay):
    response = client.get(path, base_url='https://llt-english.com')
    assert response.status_code == 200
    assert b'js/metrika.js' in response.data
    assert b'114597985' in response.data
    expected = b'"webvisor": true' if replay else b'"webvisor": false'
    assert expected in response.data
    assert 'https://mc.yandex.ru' in response.headers['Content-Security-Policy']


@pytest.mark.usefixtures('production_metrics')
def test_signup_goal_survives_redirect_and_is_consumed_once_without_ga(client):
    with client.session_transaction(base_url='https://llt-english.com') as session:
        session['_gtag_events'] = [{'name': 'signup_completed', 'params': {'method': 'email'}}]
    response = client.get('/register', base_url='https://llt-english.com')
    assert b'(["signup_completed"]).forEach' in response.data
    response = client.get('/register', base_url='https://llt-english.com')
    assert b'(["signup_completed"]).forEach' not in response.data


@pytest.mark.usefixtures('production_metrics')
def test_actual_admin_account_has_no_counter(client, admin_user):
    with client.session_transaction(base_url='https://llt-english.com') as session:
        session['_user_id'] = str(admin_user.id)
        session['_fresh'] = True
    response = client.get('/privacy', base_url='https://llt-english.com')
    assert response.status_code == 200
    assert b'js/metrika.js' not in response.data
    assert 'mc.yandex' not in response.headers['Content-Security-Policy']
