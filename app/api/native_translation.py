"""Authenticated lexical data for the on-device translator."""
from flask import Blueprint, jsonify, request

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import NativeLessonError, native_error, private_response
from app.reader_translation import service
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_translation = Blueprint('api_native_translation', __name__)
api_native_translation.after_request(private_response)
api_native_translation.register_error_handler(NativeLessonError, native_error)


@api_native_translation.post('/reader/lexicon')
@csrf.exempt
@api_bearer_required
@limiter.limit('120 per minute', key_func=get_authenticated_user_key)
def reader_lexicon():
    if request.content_length and request.content_length > 12000:
        raise NativeLessonError('invalid_input', 413)
    try:
        selected = service.selection(request.get_json(silent=True))
    except service.InvalidSelection as exc:
        raise NativeLessonError('invalid_input') from exc
    return jsonify(service.lookup(selected))
