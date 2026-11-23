"""Cookie/CSRF transport for the same course engine used by native clients."""

from functools import wraps
from flask import jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import limiter
from app.curriculum.models import Lessons, LessonProgress
from app.curriculum.constants import is_objective_practice
from app.curriculum.routes.lessons import lessons_bp
from app.utils.rate_limit_helpers import get_authenticated_user_key


def render_practice(lesson):
    return render_template("curriculum/lessons/guided_practice.html", lesson=lesson)


def uses_legacy_practice(lesson):
    """Do not strand a pre-rollout browser draft in a different editor."""
    if request.args.get("ui") == "legacy":
        return True
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id, lesson_id=lesson.id, status="in_progress"
    ).first()
    data = progress.data if progress and isinstance(progress.data, dict) else {}
    if "_native_submission" in data or "quiz_correction" in data:
        return False
    return any(data.get(key) for key in ("answers", "user_answers", "word_attempts", "cm_misses"))


def course_errors(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from app.api.native_lessons import NativeLessonError, native_error

        try:
            response = view(*args, **kwargs)
        except NativeLessonError as error:
            response = native_error(error)
        from flask import make_response

        response = make_response(response)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    return wrapped


@lessons_bp.get("/api/lesson/<int:lesson_id>/practice")
@login_required
@limiter.limit("60 per minute", key_func=get_authenticated_user_key)
@course_errors
def practice_document(lesson_id):
    from app.api.native_lessons import course_document

    value = course_document(lesson_id, deferred=True).get_json()
    value["account_id"] = str(current_user.id)
    return jsonify(value)


@lessons_bp.post("/api/lesson/<int:lesson_id>/practice/check")
@login_required
@limiter.limit("90 per minute", key_func=get_authenticated_user_key)
@course_errors
def practice_check(lesson_id):
    from app.api.native_lessons import course_answer_check

    return course_answer_check(lesson_id)


@lessons_bp.post("/api/lesson/<int:lesson_id>/practice/submit")
@login_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
@course_errors
def practice_submit(lesson_id):
    from app.api.native_lessons import course_submission

    return course_submission(lesson_id)


@lessons_bp.before_request
def canonical_practice_entry():
    # Old bookmarked type-specific pages lead to the same new course UI.
    endpoints = {
        "lesson_detail",
        "grammar_lesson",
        "quiz_lesson",
        "text_lesson",
        "dictation_lesson",
        "audio_fill_blank_lesson",
        "translation_lesson",
        "sentence_correction_lesson",
        "sentence_completion_lesson",
        "collocation_matching_lesson",
        "listening_immersion_lesson",
    }
    if (
        request.method != "GET"
        or request.args.get("ui") == "legacy"
        or not current_user.is_authenticated
        or (request.endpoint or "").split(".")[-1] not in endpoints
    ):
        return None
    lesson_id = (request.view_args or {}).get("lesson_id")
    lesson = Lessons.query.get(lesson_id) if lesson_id else None
    if lesson and is_objective_practice(lesson) and not uses_legacy_practice(lesson):
        target = url_for("learn.lesson_by_id", lesson_id=lesson_id)
        if request.query_string:
            target += "?" + request.query_string.decode("utf-8")
        return redirect(target)
