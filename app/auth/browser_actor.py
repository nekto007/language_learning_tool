"""Optional page-bound account checks for long-lived browser tabs.

This marker adds no authority: normal endpoint authentication and CSRF still
run. It only rejects a request whose page belongs to a different account.
"""
import re
from urllib.parse import urlsplit

from flask import Response, jsonify, make_response, render_template, request
from flask_login import current_user

HEADER = 'X-LLT-Account-ID'
FORM_FIELD = '_llt_account_id'


def _canonical_account_id(value: object) -> str | None:
    if not isinstance(value, str) or re.fullmatch(r'[1-9][0-9]{0,9}', value) is None:
        return None
    return value if int(value) <= 2147483647 else None


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError:
        return None


def _account_changed() -> Response:
    if (HEADER in request.headers or request.is_json or '/api/' in request.path
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        response = make_response(jsonify(success=False, error='access_denied', account_changed=True), 403)
    else:
        response = make_response(render_template('errors/account_changed.html'), 403)
    response.headers['X-LLT-Account-Changed'] = '1'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def browser_actor_guard() -> Response | None:
    markers = []
    if HEADER in request.headers:
        markers.append(request.headers[HEADER])
    if (request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
            and request.mimetype in ('application/x-www-form-urlencoded', 'multipart/form-data')):
        # Do not consume a raw form-encoded webhook body as a side effect of
        # inspecting an optional marker. JSON/native requests stay untouched.
        if request.mimetype == 'application/x-www-form-urlencoded':
            request.get_data(cache=True)
        markers.extend(request.form.getlist(FORM_FIELD))
    if not markers:
        return None  # Native and pre-rollout callers retain their transport.
    actor = _canonical_account_id(markers[0])
    if actor is None or any(_canonical_account_id(value) != actor for value in markers):
        return _account_changed()
    if (request.headers.get('Sec-Fetch-Site') == 'cross-site'
            or ('Origin' in request.headers
                and _origin(request.headers['Origin']) != _origin(request.host_url))):
        return _account_changed()

    # Cookie endpoints and JWT endpoints can select different credentials.
    # When both are present they must agree, so a marked page cannot silently
    # switch identities merely by reaching a different API transport.
    principals = []
    if current_user.is_authenticated:
        principals.append(str(current_user.id))
    if request.headers.get('Authorization', '').startswith('Bearer '):
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
        from flask_jwt_extended.exceptions import JWTExtendedException
        from jwt import PyJWTError
        try:
            verify_jwt_in_request()
            principal = _canonical_account_id(get_jwt_identity())
            if principal:
                principals.append(principal)
        except (JWTExtendedException, PyJWTError):
            pass  # Endpoint authentication still rejects an invalid JWT.
    if not principals or any(principal != actor for principal in principals):
        return _account_changed()
    return None
