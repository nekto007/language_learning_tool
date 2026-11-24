"""Signed proof of an answer rejected by standalone Grammar Lab practice."""

from typing import TYPE_CHECKING

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.api.native_lessons import NativeLessonError
from app.curriculum.answer_disputes import _hash
from app.utils.normalization import normalize_quiz_answer

if TYPE_CHECKING:
    from app.grammar_lab.models import GrammarExercise

_TEXT_TYPES = frozenset(("fill_blank", "translation", "error_correction", "transformation", "reorder"))
_RECEIPT_SECONDS = 6 * 60 * 60


def normalized_lab_answer(exercise: "GrammarExercise", answer: object) -> str | int | bool | dict | None:
    """Accept only answer shapes understood by the exercise's grader."""
    from app.curriculum.grading import _quiz_option_index
    from app.grammar_lab.answer_review import effective_content
    from app.grammar_lab.services.grader import GrammarExerciseGrader

    kind = exercise.exercise_type
    row = effective_content(exercise)
    if isinstance(answer, str) and (not answer.strip() or len(answer) > 20000):
        return None
    if kind == "multiple_choice":
        if type(answer) not in (int, str):
            return None
        index = _quiz_option_index(row.get("options", []), answer)
        return index if index >= 0 else None
    if kind == "true_false":
        return GrammarExerciseGrader._boolean_answer(answer)
    if kind == "matching":
        return _normalized_matches(answer, len(row.get("pairs", [])))
    if kind == "reorder" and isinstance(answer, list):
        words = row.get("words", [])
        if (len(answer) != len(words) or not all(type(i) is int for i in answer)
                or set(answer) != set(range(len(words)))):
            return None
        answer = " ".join(words[i] for i in answer)
    if kind in _TEXT_TYPES and isinstance(answer, str):
        return normalize_quiz_answer(answer)
    return None


def _normalized_matches(answer: object, count: int) -> dict[str, int] | None:
    if not count:
        return None
    if isinstance(answer, dict) and len(answer) == count:
        pairs = answer.items()
    elif isinstance(answer, list) and len(answer) == count:
        if not all(isinstance(pair, list) and len(pair) == 2 and all(type(i) is int for i in pair)
                   for pair in answer):
            return None
        pairs = answer
    else:
        return None
    normalized = {}
    for left, right in pairs:
        indexes = []
        for index in (left, right):
            if type(index) is str and len(index) <= 6 and index.isascii() and index.isdigit():
                index = int(index)
            if type(index) is not int or not 0 <= index < count:
                return None
            indexes.append(index)
        normalized[str(indexes[0])] = indexes[1]
    return normalized if len(normalized) == count else None


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="grammar-lab-dispute-v1")


def issue_rejection_receipt(user_id: int, exercise_id: int, revision: str, answer: object) -> str:
    from app.grammar_lab.answer_review import LAB_GRADER_VERSION

    return _signer().dumps({
        "user": user_id, "exercise": exercise_id, "revision": revision,
        "grader": LAB_GRADER_VERSION, "answer_digest": _hash(answer),
    })


def read_rejection_receipt(token: str, user_id: int, exercise_id: int) -> dict:
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise NativeLessonError("invalid_input")
    try:
        claims = _signer().loads(token, max_age=_RECEIPT_SECONDS)
    except BadSignature:
        raise NativeLessonError("dispute_receipt_invalid", 409) from None
    if not isinstance(claims, dict) or claims.get("user") != user_id or claims.get("exercise") != exercise_id:
        raise NativeLessonError("access_denied", 403)
    return claims


def verify_rejected_answer(claims: dict, exercise: "GrammarExercise", answer: object) -> object:
    from app.grammar_lab.answer_review import LAB_GRADER_VERSION, lab_revision

    if claims.get("grader") != LAB_GRADER_VERSION or claims.get("revision") != lab_revision(exercise):
        raise NativeLessonError("lesson_changed", 409)
    normalized = normalized_lab_answer(exercise, answer)
    if normalized is None or claims.get("answer_digest") != _hash(answer):
        raise NativeLessonError("invalid_input")
    return normalized
