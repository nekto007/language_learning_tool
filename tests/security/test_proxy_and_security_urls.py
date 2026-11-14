"""Security-origin and proxy boundaries using Flask without the application DB."""
import pytest
from flask import Flask, jsonify, request

from app.middleware.proxy import apply_trusted_proxy
from app.middleware.security import add_security_headers
from app.utils.rate_limit_helpers import get_remote_address_key
from app.utils.url_helpers import canonical_external_url


def _minimal_app():
    server = Flask(__name__)
    server.config['SECRET_KEY'] = 'local-security-test'

    @server.get('/reset_password/<token>')
    def reset_password(token):
        return token

    return server


@pytest.mark.parametrize('origin', ['https://accounts.example', 'https://accounts.example:8443/config-path'])
def test_security_url_uses_configured_origin_despite_host_headers(origin):
    server = _minimal_app()
    server.config['SITE_URL'] = origin
    with server.test_request_context('/', base_url='http://hostile.example', headers={
        'X-Forwarded-Host': 'forwarded-hostile.example',
        'X-Forwarded-Proto': 'http',
    }):
        expected = 'https://accounts.example'
        if ':8443' in origin:
            expected += ':8443'
        assert canonical_external_url('reset_password', token='one-time-token') == (
            expected + '/reset_password/one-time-token'
        )


@pytest.mark.parametrize('configured', [
    None, '', '/relative', '//hostile.example', 'javascript:alert(1)',
    'https://user:pass@hostile.example', 'https://[invalid',
    42, {'url': 'https://hostile.example'},
])
def test_invalid_security_origin_falls_back_to_canonical_site(configured):
    server = _minimal_app()
    server.config['SITE_URL'] = configured
    with server.test_request_context('/', base_url='https://hostile.example'):
        assert canonical_external_url('reset_password', token='one-time-token') == (
            'https://llt-english.com/reset_password/one-time-token'
        )


def test_https_production_gets_hsts_when_flask_env_key_is_absent():
    server = _minimal_app()
    server.config.pop('ENV', None)
    assert not server.testing and not server.debug
    add_security_headers(server)
    response = server.test_client().get('/reset_password/token', base_url='https://accounts.example')
    assert response.headers['Strict-Transport-Security'] == 'max-age=31536000; includeSubDomains; preload'


@pytest.mark.parametrize('testing,debug,scheme', [
    (False, True, 'https'),
    (True, False, 'https'),
    (True, False, 'http'),
    (False, False, 'http'),
])
def test_hsts_is_absent_for_debug_testing_or_insecure_requests(testing, debug, scheme):
    server = _minimal_app()
    server.config.pop('ENV', None)
    server.testing = testing
    server.debug = debug
    add_security_headers(server)
    response = server.test_client().get('/reset_password/token', base_url=f'{scheme}://accounts.example')
    assert 'Strict-Transport-Security' not in response.headers


def _proxy_app():
    server = _minimal_app()
    # This is the same production middleware used by the real application,
    # exercised through the WSGI boundary rather than test_request_context.
    apply_trusted_proxy(server)

    @server.get('/probe')
    def probe():
        return jsonify(remote=get_remote_address_key(), host=request.host,
                       secure=request.is_secure, script_root=request.script_root)

    return server


def test_trusted_proxy_uses_rightmost_ip_and_preserves_original_host_and_mount():
    server = _proxy_app()
    client = server.test_client()
    for spoofed in ['1.2.3.4', '9.8.7.6, 192.0.2.200']:
        response = client.get('/probe', base_url='http://original.example', headers={
            'X-Forwarded-For': f'{spoofed}, 198.51.100.22',
            'X-Real-IP': '203.0.113.99',
            'X-Forwarded-Host': 'hostile.example',
            'X-Forwarded-Prefix': '/hostile-mount',
            'X-Forwarded-Proto': 'http, https',
        }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert response.get_json() == {
            'remote': '198.51.100.22', 'host': 'original.example',
            'secure': True, 'script_root': '',
        }


def test_raw_ip_headers_do_not_override_remote_addr_without_forwarded_chain():
    server = _proxy_app()
    response = server.test_client().get('/probe', base_url='http://original.example', headers={
        'X-Real-IP': '203.0.113.99', 'X-Forwarded-Host': 'hostile.example',
    }, environ_overrides={'REMOTE_ADDR': '192.0.2.8'})
    assert response.get_json()['remote'] == '192.0.2.8'
    assert response.get_json()['host'] == 'original.example'


def test_canonical_email_origin_remains_fixed_after_proxy_resolution():
    server = _minimal_app()
    server.config['SITE_URL'] = 'https://accounts.example'
    apply_trusted_proxy(server)

    @server.get('/email-link')
    def email_link():
        return canonical_external_url('reset_password', token='one-time-token')

    response = server.test_client().get('/email-link', base_url='http://hostile.example', headers={
        'X-Forwarded-Host': 'also-hostile.example', 'X-Forwarded-Proto': 'https',
    })
    assert response.get_data(as_text=True) == 'https://accounts.example/reset_password/one-time-token'
