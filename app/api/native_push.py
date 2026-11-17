"""Mobile push registration, opt-in settings and device-secret revocation."""
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import NativeLessonError, native_error, private_response
from app.notifications.apns import APNsClient, configured
from app.notifications.push_models import PushDevice, PushPreference
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key
from app.utils.time_utils import get_user_timezone_name

api_native_push = Blueprint('api_native_push', __name__)
api_native_push.after_request(private_response)
api_native_push.register_error_handler(NativeLessonError, native_error)


def _body(keys):
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) != set(keys):
        raise NativeLessonError('invalid_input')
    return value


def _identity(value):
    try:
        identifier = str(UUID(value['installation_id']))
    except (ValueError, TypeError, AttributeError):
        raise NativeLessonError('invalid_input')
    secret = value['installation_secret']
    if not isinstance(secret, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', secret):
        raise NativeLessonError('invalid_input')
    return identifier, hashlib.sha256(secret.encode()).hexdigest()


def _reply():
    preference = db.session.get(PushPreference, current_user.id)
    return jsonify(success=True, enabled=bool(preference and preference.enabled),
                   hours=preference.hours if preference else [9, 15, 20],
                   timezone=get_user_timezone_name(current_user.id), ready=configured())


@api_native_push.get('/push/settings')
@api_bearer_required
def push_settings():
    return _reply()


@api_native_push.put('/push/settings')
@csrf.exempt
@api_bearer_required
@limiter.limit('20 per minute', key_func=get_authenticated_user_key)
def update_push_settings():
    value = _body(('enabled', 'hours'))
    hours = value['hours']
    if type(value['enabled']) is not bool or not isinstance(hours, list) or len(hours) != 3:
        raise NativeLessonError('invalid_input')
    if any(type(h) is not int or not 8 <= h <= 21 for h in hours) or any(b-a < 2 for a, b in zip(hours, hours[1:])):
        raise NativeLessonError('invalid_input')
    # Serialize preference creation/update with device registration for this account.
    from app.auth.models import User
    db.session.query(User).filter_by(id=current_user.id).with_for_update().first()
    preference = db.session.get(PushPreference, current_user.id)
    if preference is None:
        preference = PushPreference(user_id=current_user.id)
        db.session.add(preference)
    preference.enabled = value['enabled']
    preference.hours = hours
    db.session.commit()
    return _reply()


@api_native_push.post('/push/devices')
@csrf.exempt
@api_bearer_required
@limiter.limit('30 per minute', key_func=get_authenticated_user_key)
def register_push_device():
    value = _body(('installation_id', 'installation_secret', 'token', 'environment'))
    identifier, digest = _identity(value)
    token = value['token']
    if not isinstance(token, str) or not re.fullmatch(r'(?:[a-fA-F0-9]{2}){16,256}', token):
        raise NativeLessonError('invalid_input')
    if value['environment'] not in ('sandbox', 'production'):
        raise NativeLessonError('invalid_input')
    device = db.session.query(PushDevice).filter_by(id=identifier).with_for_update().first()
    if device and not hmac.compare_digest(device.secret_hash, digest):
        raise NativeLessonError('access_denied', 403)
    if device is None:
        device = PushDevice(id=identifier, secret_hash=digest)
        db.session.add(device)
    device.user_id = current_user.id
    device.token = token.lower()
    device.environment = value['environment']
    device.auth_version = str(current_user.auth_version())
    device.active = True
    device.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise NativeLessonError('device_conflict', 409)
    return _reply()


@api_native_push.post('/push/revoke')
@csrf.exempt
@limiter.limit('60 per minute')
def revoke_push_device():
    # Works after logout or offline logout retry; a random Keychain secret is
    # required, never cookie authentication or a public installation UUID alone.
    identifier, digest = _identity(_body(('installation_id', 'installation_secret')))
    device = db.session.query(PushDevice).filter_by(id=identifier).with_for_update().first()
    if device and hmac.compare_digest(device.secret_hash, digest):
        device.active = False
        db.session.commit()
    return jsonify(success=True)


@api_native_push.post('/push/test')
@csrf.exempt
@api_bearer_required
@limiter.limit('1 per minute', key_func=get_authenticated_user_key)
def test_push():
    identifier, digest = _identity(_body(('installation_id', 'installation_secret')))
    device = db.session.get(PushDevice, identifier)
    if not device or device.user_id != current_user.id or not device.active or not hmac.compare_digest(device.secret_hash, digest):
        raise NativeLessonError('not_found', 404)
    if not configured():
        return jsonify(success=False, error='push_unavailable'), 503
    now = datetime.now(timezone.utc)
    try:
        with APNsClient() as sender:
            result = sender.send(device, title='Уведомления LLT English',
                body='Всё готово! Напомним о занятиях, если сегодня ты ещё не занимался.',
                collapse_id='study-test', expires_at=int((now+timedelta(minutes=5)).timestamp()),
                account_key='account:' + current_user.username, is_test=True)
    except Exception:
        current_app.logger.warning('APNs test could not be sent')
        return jsonify(success=False, error='push_unavailable'), 503
    if result.invalid_device:
        device.active = False
        db.session.commit()
    return (jsonify(success=True) if result.accepted else (jsonify(success=False, error='push_unavailable'), 503))
