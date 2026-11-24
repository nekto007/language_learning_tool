"""Cookie/CSRF browser transport and a separate Bearer-only native transport."""
from __future__ import annotations

from typing import Any
from flask import Blueprint, Response, jsonify, make_response, render_template, request
from flask_login import current_user, login_required

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.onboarding import onboarding_bp
from app.onboarding import placement_engine as engine
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


def _mutate(action: str, attempt_id: str = '') -> Response:
    try:
        if action == 'start':
            value = _body({'mode'})
            payload = engine.start(current_user.id, value['mode'])
        elif action in ('answer', 'draft'):
            value = _body({'question_id', 'answer', 'dont_know'} if action == 'answer' else {'question_id', 'answer'})
            if action == 'answer':
                payload = engine.answer(current_user.id, attempt_id, value['question_id'], value['answer'], value['dont_know'])
            else:
                payload = engine.save_draft(current_user.id, attempt_id, value['question_id'], value['answer'])
        else:
            _body(set())
            payload = (engine.adopt_level if action == 'apply' else engine.abandon)(current_user.id, attempt_id)
        db.session.commit()
        return private_response(jsonify(success=True, attempt=payload))
    except Exception:
        db.session.rollback()
        raise


@onboarding_bp.get('/placement')
@login_required
def placement_page() -> Response:
    return private_response(render_template('onboarding/placement.html'))


@onboarding_bp.get('/onboarding/placement/v2/status')
@login_required
def placement_status() -> Response:
    return private_response(jsonify(engine.status(current_user.id)))


@onboarding_bp.post('/onboarding/placement/v2/start')
@login_required
@limiter.limit('10 per hour', key_func=get_authenticated_user_key)
def placement_start_v2() -> Response:
    return _mutate('start')


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/answer')
@login_required
@limiter.limit('60 per minute', key_func=get_authenticated_user_key)
def placement_answer_v2(attempt_id: str) -> Response:
    return _mutate('answer', attempt_id)


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/draft')
@login_required
@limiter.limit('120 per minute', key_func=get_authenticated_user_key)
def placement_draft(attempt_id: str) -> Response:
    return _mutate('draft', attempt_id)


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/apply')
@login_required
def placement_apply(attempt_id: str) -> Response:
    return _mutate('apply', attempt_id)


@onboarding_bp.post('/onboarding/placement/v2/<attempt_id>/abandon')
@login_required
def placement_abandon(attempt_id: str) -> Response:
    return _mutate('abandon', attempt_id)


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
