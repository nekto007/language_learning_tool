"""Bearer-only account controls and deliberate vocabulary enrollment."""
from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user
from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import NativeLessonError, native_error, private_response
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_controls = Blueprint('api_native_controls', __name__)
api_native_controls.after_request(private_response)
api_native_controls.register_error_handler(NativeLessonError, native_error)


def _body(keys):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != set(keys):
        raise NativeLessonError('invalid_input')
    return body


@api_native_controls.get('/vocabulary/<int:word_id>')
@api_bearer_required
def word_detail(word_id):
    from app.api.words import get_word
    from app.study.models import UserWord
    response = get_word(word_id)
    if response.status_code != 200:
        return response
    body = response.get_json()
    owned = UserWord.query.filter_by(user_id=current_user.id, word_id=word_id).first()
    body['in_study'] = owned is not None and not owned.srs_excluded
    return jsonify(body)


@api_native_controls.post('/vocabulary/<int:word_id>/study')
@csrf.exempt
@api_bearer_required
@limiter.limit('30 per minute', key_func=get_authenticated_user_key)
def enroll_word(word_id):
    _body(())
    from app.modules.service import ModuleService
    from app.words.models import CollectionWords
    from app.study.models import UserWord
    from app.srs.cards import ensure_card_directions
    from app.study.deck_utils import ensure_word_in_default_deck
    from app.api.native_srs import _lock_user
    if not ModuleService.is_module_enabled_for_user(current_user.id, 'study'):
        raise NativeLessonError('access_denied', 403)
    word = db.session.get(CollectionWords, word_id)
    if word is None:
        raise NativeLessonError('not_found', 404)
    if not (word.english_word or '').strip() or not (word.russian_word or '').strip():
        raise NativeLessonError('unsupported_word', 422)
    try:
        _lock_user()
        owned = UserWord.get_or_create(current_user.id, word_id)
        owned.srs_excluded = False
        db.session.flush()
        ensure_card_directions(owned, source='native_dictionary')
        ensure_word_in_default_deck(current_user.id, word_id, owned.id)
        db.session.commit()
        return jsonify(success=True, word_id=word_id, in_study=True)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Native word enrollment failed user=%s word=%s', current_user.id, word_id)
        return jsonify(success=False, error='server_error'), 500


@api_native_controls.post('/plan/pause')
@csrf.exempt
@api_bearer_required
@limiter.limit('10 per minute', key_func=get_authenticated_user_key)
def pause_native():
    body = _body(('days',))
    if type(body['days']) is not int or not 1 <= body['days'] <= 14:
        raise NativeLessonError('invalid_input')
    from app.api.daily_plan import plan_pause
    return plan_pause()


@api_native_controls.post('/plan/resume')
@csrf.exempt
@api_bearer_required
@limiter.limit('10 per minute', key_func=get_authenticated_user_key)
def resume_native():
    _body(())
    from app.api.daily_plan import plan_resume
    return plan_resume()
