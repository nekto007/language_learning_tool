"""JWT-only native adapters for the existing book/reading operations."""

import math
from flask import Blueprint, request
from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import NativeLessonError, native_error, private_response
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_reading = Blueprint("api_native_reading", __name__)
api_native_reading.after_request(private_response)
api_native_reading.register_error_handler(NativeLessonError, native_error)


def _body(keys):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != set(keys):
        raise NativeLessonError("invalid_input")
    return body


def _id(value):
    if type(value) is not int or not 0 < value <= 2147483647:
        raise NativeLessonError("invalid_input")


def _offset(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise NativeLessonError("invalid_input")


@api_native_reading.route("/books/select", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
def select_book_native():
    body = _body(("book_id",))
    _id(body["book_id"])
    from app.api.books_catalog import select_book

    return select_book()


@api_native_reading.route("/reading/progress", methods=["PATCH"])
@csrf.exempt
@api_bearer_required
@limiter.limit("60 per minute", key_func=get_authenticated_user_key)
def save_reading_progress_native():
    body = _body(("book_id", "chapter_id", "offset_pct"))
    _id(body["book_id"])
    _id(body["chapter_id"])
    _offset(body["offset_pct"])
    from app.api.books import update_chapter_progress

    return update_chapter_progress()


@api_native_reading.route("/reading/start", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("60 per minute", key_func=get_authenticated_user_key)
def start_reading_native():
    body = _body(("chapter_id",))
    _id(body["chapter_id"])
    from app.books.api import reading_session_start

    return reading_session_start()


@api_native_reading.route("/reading/end", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("60 per minute", key_func=get_authenticated_user_key)
def end_reading_native():
    body = _body(("session_id", "current_offset_pct"))
    _id(body["session_id"])
    _offset(body["current_offset_pct"])
    from app.books.api import close_reading_session_response

    return close_reading_session_response(body, max_duration_seconds=90)
