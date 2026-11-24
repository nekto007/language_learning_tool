"""Cookie/CSRF transport for the same course engine used by native clients."""

from functools import wraps
import re
from typing import Any
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
    if lesson.type == "final_test":
        return False
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
    from app.utils.time_utils import get_user_local_date

    if request.args.get("result_identity") == "1":
        return _practice_result_identity(lesson_id)
    value = course_document(lesson_id, deferred=True).get_json()
    value["account_id"] = str(current_user.id)
    value["lesson"]["study_day"] = get_user_local_date(current_user.id).isoformat()
    if value["lesson"]["type"] == "final_test":
        progress = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson_id).first()
        lesson = Lessons.query.get(lesson_id)
        answers = _legacy_final_answers(value["lesson"]["questions"], progress, lesson=lesson)
        if answers:
            value["lesson"]["resume_answers"] = answers
    return jsonify(value)


def _practice_result_identity(lesson_id: int) -> Any:
    """Revalidate a read-only browser result even when the plan is paused."""
    from app.api.native_lessons import _content, _digest, _lesson_and_progress

    lesson, _ = _lesson_and_progress(lesson_id)
    return jsonify(
        success=True, account_id=str(current_user.id),
        lesson={"id": lesson.id, "type": lesson.type, "content_revision": _digest(_content(lesson))},
    )


def _legacy_final_answers(questions: list[dict[str, Any]], progress: LessonProgress | None,
                          *, lesson: Lessons) -> dict[str, str]:
    """Migrate only learner input; never expose old client verdicts or keys.

    Legacy option values were visible labels rather than stable source IDs.
    Matching stored pairs alongside a display string. Reconstruct only values
    that fit the new editor exactly; ambiguous/stale input is left unanswered.
    """
    import json
    from app.api.native_content import _converted
    from app.api.native_lessons import NativeLessonError
    from app.curriculum.progress_drafts import final_draft_origin_matches

    if not progress or progress.status != "in_progress" or not isinstance(progress.data, dict):
        return {}
    if not final_draft_origin_matches(lesson, progress):
        return {}
    saved = progress.data.get("answers") or progress.data.get("user_answers")
    if not isinstance(saved, (dict, list)):
        return {}
    result = {}
    for q in questions:
        index = int(q["id"])
        entry = saved[index] if isinstance(saved, list) and index < len(saved) else (
            saved.get(q["id"], saved.get(index)) if isinstance(saved, dict) else None)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if not isinstance(value, str) or not value.strip() or len(value) > 20000:
            continue
        kind = q.get("input")
        if kind == "choice":
            options = q.get("options", [])
            value = next((o["value"] for o in options if o["label"] == value), value)
            if value not in {o["value"] for o in options}:
                continue
        elif kind == "order":
            options = q.get("options", [])
            remaining = value.split()
            indexes, unused = [], list(options)
            while remaining:
                option = next((o for o in unused if o["label"].split() == remaining[:len(o["label"].split())]), None)
                if not option:
                    break
                indexes.append(option["value"])
                remaining = remaining[len(option["label"].split()):]
                unused.remove(option)
            if remaining or unused:
                continue
            value = json.dumps(indexes)
        elif kind == "match":
            pairs = entry.get("pairs") if isinstance(entry, dict) else None
            if not isinstance(pairs, list):
                continue
            left, right = q.get("left_options", []), q.get("options", [])
            mapping = {}
            for pair in pairs:
                if not isinstance(pair, dict):
                    break
                ls = [o["value"] for o in left if o["label"] == pair.get("left")]
                rs = [o["value"] for o in right if o["label"] == pair.get("right")]
                if len(ls) != 1 or len(rs) != 1 or ls[0] in mapping:
                    break
                mapping[ls[0]] = rs[0]
            if len(mapping) != len(left) or len(set(mapping.values())) != len(right):
                continue
            value = json.dumps(mapping)
        elif len(value) > 2000:
            continue
        # Check structural transport constraints without grading any answer.
        # Source word/pair labels are sufficient for order/match validation.
        row = ({"words": [o["label"] for o in q["options"]]} if kind == "order"
               else {"pairs": [{} for _ in q.get("left_options", [])]})
        try:
            _converted(row, q, value, grammar=True)
        except NativeLessonError:
            continue
        result[q["id"]] = value
    return result


@lessons_bp.post("/api/lesson/<int:lesson_id>/practice/check")
@login_required
@limiter.limit("90 per minute", key_func=get_authenticated_user_key)
@course_errors
def practice_check(lesson_id):
    from app.api.native_lessons import course_answer_check

    return course_answer_check(lesson_id)


def _signed_attempt_id(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) else None


@lessons_bp.post("/api/lesson/<int:lesson_id>/practice/dispute")
@login_required
@limiter.limit("10 per minute", key_func=get_authenticated_user_key)
@course_errors
def practice_dispute(lesson_id: int) -> Any:
    from app.api.native_lessons import NativeLessonError, checked_course_answer
    from app.curriculum.answer_disputes import DISPUTABLE_LESSON_TYPES, record_rejected_answer
    from app.curriculum.services.progress_service import _invalidate_user_progress_cache
    from app.utils.db import db

    lesson, question, answer, feedback, sealed = checked_course_answer(
        lesson_id, lesson_types=DISPUTABLE_LESSON_TYPES,
    )
    if feedback["correct"] is not False:
        raise NativeLessonError("answer_not_rejected")
    correction = sealed.get("correction_attempt") if sealed.get("quiz_phase") == "correction" else None
    updated_learners = record_rejected_answer(
        db.session, lesson, question, answer, user_id=current_user.id,
        course_nonce=_signed_attempt_id(sealed.get("nonce")), course_correction_id=_signed_attempt_id(correction),
    )
    db.session.commit()
    for user_id in updated_learners:
        _invalidate_user_progress_cache(user_id)
    return jsonify(success=True)


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
        "final_test_lesson",
    }
    if (
        request.method != "GET"
        or not current_user.is_authenticated
        or (request.endpoint or "").split(".")[-1] not in endpoints
    ):
        return None
    lesson_id = (request.view_args or {}).get("lesson_id")
    lesson = Lessons.query.get(lesson_id) if lesson_id else None
    if lesson and (lesson.type == "final_test" or is_objective_practice(lesson)) and not uses_legacy_practice(lesson):
        target = url_for("learn.lesson_by_id", lesson_id=lesson_id)
        if request.query_string:
            target += "?" + request.query_string.decode("utf-8")
        return redirect(target)
