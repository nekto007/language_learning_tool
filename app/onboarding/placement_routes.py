"""Cookie/CSRF browser transport and a separate Bearer-only native transport."""
from __future__ import annotations

from typing import Any
from flask import Blueprint, Response, jsonify, make_response, render_template, request, redirect, url_for
from flask_login import current_user, login_required

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.onboarding import onboarding_bp
from app.onboarding import placement_engine as engine
from app.onboarding.placement_guests import guest_actor, web_actor, web_rate_key
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_placement = Blueprint('api_native_placement', __name__)


def private_response(response: Any) -> Response:
    response = make_response(response)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Pragma'] = 'no-cache'
    return response


api_native_placement.after_request(private_response)


def error_response(error: engine.PlacementError) -> tuple[Response, int]:
    db.session.rollback()
    return private_response(jsonify(success=False, error=error.code)), error.status


api_native_placement.register_error_handler(engine.PlacementError, error_response)
onboarding_bp.register_error_handler(engine.PlacementError, error_response)


def _body(required: set[str], optional: set[str] | None = None) -> dict:
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise engine.PlacementError('invalid_input')
    return value


def _mutate(action: str, attempt_id: str = '', actor: int | str | None = None) -> Response:
    actor = current_user.id if actor is None else actor
    try:
        if action == 'start':
            value = _body({'mode'}, {'scope'})
            payload = engine.start(actor, value['mode'], scope=value.get('scope'))
        elif action in ('answer', 'draft'):
            value = _body({'question_id', 'answer', 'dont_know'} if action == 'answer' else {'question_id', 'answer'})
            if action == 'answer':
                payload = engine.answer(actor, attempt_id, value['question_id'], value['answer'], value['dont_know'])
            else:
                payload = engine.save_draft(actor, attempt_id, value['question_id'], value['answer'])
        else:
            _body(set())
            payload = (engine.adopt_level if action == 'apply' else engine.abandon)(actor, attempt_id)
        db.session.commit()
        return private_response(jsonify(success=True, attempt=payload))
    except Exception:
        db.session.rollback()
        raise


@onboarding_bp.get('/placement')
@limiter.limit('120 per hour', key_func=web_rate_key)
def placement_page() -> Response:
    guest = not current_user.is_authenticated
    actor = guest_actor() if guest else current_user.id
    onboarding_next = None
    if not guest and request.args.get('next'):
        from app.auth.routes import get_safe_redirect_url
        onboarding_next = get_safe_redirect_url(request.args['next'])
    simple = (guest and request.args.get('advanced') != '1') or request.args.get('start') == '1' or request.args.get('simple') == '1'
    response = private_response(render_template('onboarding/placement.html', placement_guest=guest, placement_actor=actor,
        placement_simple=simple, placement_force_start=request.args.get('start') == '1',
        onboarding_next=onboarding_next))
    if guest:
        from flask import session, current_app
        response.set_cookie('llt_placement_guest', session['placement_guest'], max_age=7 * 86400,
            httponly=True, secure=request.is_secure or current_app.config.get('SESSION_COOKIE_SECURE', False), samesite='Lax')
    return response


@onboarding_bp.get('/onboarding/placement/v2/status')
def placement_status() -> Response:
    return private_response(jsonify(engine.status(web_actor())))


@onboarding_bp.post('/onboarding/placement/v2/start')
@limiter.limit('10 per hour', key_func=web_rate_key)
def placement_start_v2() -> Response:
    return _mutate('start', actor=web_actor())


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/answer')
@limiter.limit('60 per minute', key_func=web_rate_key)
def placement_answer_v2(attempt_id: str) -> Response:
    return _mutate('answer', attempt_id, web_actor())


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/draft')
@limiter.limit('120 per minute', key_func=web_rate_key)
def placement_draft(attempt_id: str) -> Response:
    return _mutate('draft', attempt_id, web_actor())


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/apply')
def placement_apply(attempt_id: str) -> Response:
    return _mutate('apply', attempt_id, web_actor())


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/abandon')
def placement_abandon(attempt_id: str) -> Response:
    return _mutate('abandon', attempt_id, web_actor())


@api_native_placement.get('/placement/status')
@api_bearer_required
def native_status() -> Response:
    return jsonify(engine.status(current_user.id))


@api_native_placement.post('/placement/start')
@csrf.exempt
@api_bearer_required
@limiter.limit('10 per hour', key_func=get_authenticated_user_key)
def native_start() -> Response:
    return _mutate('start')


@api_native_placement.post('/placement/<attempt_id>/answer')
@csrf.exempt
@api_bearer_required
@limiter.limit('60 per minute', key_func=get_authenticated_user_key)
def native_answer(attempt_id: str) -> Response:
    return _mutate('answer', attempt_id)


@api_native_placement.post('/placement/<attempt_id>/draft')
@csrf.exempt
@api_bearer_required
@limiter.limit('120 per minute', key_func=get_authenticated_user_key)
def native_draft(attempt_id: str) -> Response:
    return _mutate('draft', attempt_id)


@api_native_placement.post('/placement/<attempt_id>/apply')
@csrf.exempt
@api_bearer_required
def native_apply(attempt_id: str) -> Response:
    return _mutate('apply', attempt_id)


@api_native_placement.post('/placement/<attempt_id>/abandon')
@csrf.exempt
@api_bearer_required
def native_abandon(attempt_id: str) -> Response:
    return _mutate('abandon', attempt_id)


@onboarding_bp.post('/placement/continue')
@limiter.limit('10 per hour', key_func=web_rate_key)
def placement_handoff() -> Response:
    from flask import session
    actor = web_actor()
    if type(actor) is int:
        return redirect(url_for('onboarding.placement_page'))
    state = engine.status(actor)
    if not state['latest']:
        raise engine.PlacementError('test_not_completed', 409)
    session['placement_handoff'] = actor
    simple = request.form.get('flow') == 'starter' and state['latest'].get('scope') == engine.STARTER_SCOPE
    session.pop('placement_apply_after_login', None)
    if simple:
        session['placement_apply_after_login'] = state['latest']['id']
    if request.form.get('destination') == 'login':
        if simple:
            return redirect(url_for('auth.login', next=url_for('words.dashboard')))
        return redirect(url_for('auth.login', next=url_for('onboarding.placement_page', result=1)))
    return redirect(url_for('auth.register', level=state['latest']['result']['recommended_level']))


@onboarding_bp.post('/onboarding/placement/v2/dismiss')
@login_required
def placement_dismiss() -> Response:
    from app.onboarding.placement_home import dismiss
    dismiss(current_user.id, _body({'key'})['key'])
    db.session.commit()
    return private_response(jsonify(success=True))


@api_native_placement.post('/placement/dismiss')
@csrf.exempt
@api_bearer_required
def native_dismiss() -> Response:
    from app.onboarding.placement_home import dismiss
    dismiss(current_user.id, _body({'key'})['key'])
    db.session.commit()
    return private_response(jsonify(success=True))


@onboarding_bp.get('/placement/review/<review_id>')
@login_required
def placement_review_page(review_id: str) -> Response:
    from app.onboarding.placement_reviews import owned_review, item_for, _today
    from uuid import uuid5, NAMESPACE_URL
    row = owned_review(current_user.id, review_id)
    item = item_for(row)
    if item is None:
        raise engine.PlacementError('not_found', 404)
    request_id = str(uuid5(NAMESPACE_URL, f'placement:{current_user.id}:{row.id}:{_today(current_user.id)}'))
    return private_response(render_template('onboarding/review.html', item=item, request_id=request_id,
        review_completed=row.completed_on == _today(current_user.id), practice=row.practice))


@onboarding_bp.post('/onboarding/placement/review/<review_id>/<action>')
@login_required
@limiter.limit('90 per minute', key_func=web_rate_key)
def placement_review_action(review_id: str, action: str) -> Response:
    from app.api.native_activities import start_activity_document, check_activity_document, submit_activity_document
    from app.api.native_lessons import NativeLessonError, native_error
    from app.onboarding.placement_reviews import owned_review, item_for
    row = owned_review(current_user.id, review_id)
    item = item_for(row)
    if item is None:
        raise engine.PlacementError('not_found', 404)
    functions = {'start': start_activity_document, 'check': check_activity_document, 'submit': submit_activity_document}
    if action not in functions:
        raise engine.PlacementError('not_found', 404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise engine.PlacementError('invalid_input')
    if action == 'start' and body.get('item_id') != item.id:
        raise engine.PlacementError('invalid_input')
    # For later actions the signed session must name this exact queue item.
    if action != 'start':
        from app.api.native_activities import _signer
        from app.study.models import NativeLearningRun
        from itsdangerous import BadSignature, SignatureExpired
        try:
            sealed = _signer().loads(body.get('session_token'), max_age=21600)
        except (BadSignature, SignatureExpired, TypeError):
            raise engine.PlacementError('attempt_closed', 409) from None
        run = NativeLearningRun.query.filter_by(user_id=current_user.id, session_id=sealed.get('session') if isinstance(sealed, dict) else None).first()
        if run is None or run.payload.get('item_id') != item.id:
            raise engine.PlacementError('access_denied', 403)
    try:
        response = functions[action]('grammar_review', body)
        from flask import make_response
        response = make_response(response)
        payload = response.get_json()
        if isinstance(payload, dict):
            payload['account_id'] = current_user.id
            return private_response(jsonify(payload)), response.status_code
        return response
    except NativeLessonError as error:
        db.session.rollback()
        return native_error(error)
