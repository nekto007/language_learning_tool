"""Atomic opt-in receipts for standalone web grammar attempts."""
import json
import re
from hashlib import sha256
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.api.native_lessons import NativeLessonError
from app.grammar_lab.answer_review import LAB_GRADER_VERSION, lab_revision
from app.grammar_lab.dispute_receipts import issue_rejection_receipt, normalized_lab_answer
from app.grammar_lab.models import GrammarAttempt, GrammarExercise
from app.utils.db import db

if TYPE_CHECKING:
    from app.grammar_lab.services import GrammarLabService


def submit_once(service: "GrammarLabService", user_id: int, exercise_id: int, data: dict[str, Any]) -> dict:
    """Look up or claim an attempt, grade once, then commit the receipt and progress."""
    try:
        key = str(UUID(data.get('submission_id')))
    except (ValueError, AttributeError, TypeError):
        raise NativeLessonError('invalid_input') from None
    revision = data.get('exercise_revision')
    session_id, source, time_spent = data.get('session_id'), data.get('source', 'topic_practice'), data.get('time_spent')
    if ('answer' not in data or not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{64}', revision)
            or (session_id is not None and (not isinstance(session_id, str) or len(session_id) > 100))
            or not isinstance(source, str) or not 0 < len(source) <= 50
            or (time_spent is not None and (type(time_spent) is not int or not 0 <= time_spent <= 2**31 - 1))):
        raise NativeLessonError('invalid_input')
    answer = data['answer']
    try:
        encoded = json.dumps([exercise_id, revision, answer, session_id, source, time_spent],
                             sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    except (ValueError, TypeError, RecursionError):
        raise NativeLessonError('invalid_input') from None
    if len(encoded) > 32768:
        raise NativeLessonError('invalid_input')
    digest = sha256(encoded).hexdigest()

    # Keep the authored revision stable until the attempt commits. A shared
    # lock allows distinct submissions against the same exercise to proceed.
    exercise = (GrammarExercise.query.filter_by(id=exercise_id)
                .populate_existing().with_for_update(read=True).one_or_none())
    attempts = GrammarAttempt.query.filter_by(user_id=user_id, submission_id=key)
    attempt = attempts.one_or_none()
    if exercise is None:
        if attempt is not None:
            raise NativeLessonError('submission_mismatch', 409)
        raise NativeLessonError('not_found', 404)
    revision_current = not (exercise.content or {}).get('guided_retired') and lab_revision(exercise) == revision
    if attempt is not None:
        return _replay(attempt, digest, exercise, answer, revision, revision_current)
    if not revision_current:
        raise NativeLessonError('lesson_changed', 409)

    insert = {'postgresql': pg_insert, 'sqlite': sqlite_insert}[db.session.get_bind().dialect.name]
    claim = db.session.execute(insert(GrammarAttempt).values(
        user_id=user_id, exercise_id=exercise_id, submission_id=key,
        is_correct=False, session_id=session_id, source=source, time_spent=time_spent,
    ).on_conflict_do_nothing(
        index_elements=['user_id', 'submission_id'],
        index_where=GrammarAttempt.submission_id.is_not(None),
    ))
    attempt = attempts.one()
    if claim.rowcount == 0:
        return _replay(attempt, digest, exercise, answer, revision, revision_current)

    result = service.submit_answer(
        exercise_id, user_id, answer, session_id=session_id, source=source, time_spent=time_spent,
        claimed_attempt=attempt,
    )
    if result.get('error'):
        raise NativeLessonError('grading_failed', 503)
    result_for_storage = {key: value for key, value in result.items() if key != 'is_correct'}
    # Text already lives in user_answer. Retain a typed JSON value only where
    # the grader returned something other than a string (e.g. matching).
    answer_from_attempt = isinstance(result_for_storage.get('user_answer'), str)
    if answer_from_attempt:
        result_for_storage.pop('user_answer')
    attempt.submission_receipt = {
        'digest': digest, 'grader_version': LAB_GRADER_VERSION,
        'answer_from_attempt': answer_from_attempt, 'response': result_for_storage,
    }
    result = _with_dispute_token(result, exercise, attempt, answer, revision)
    db.session.commit()
    return result


def _replay(attempt: GrammarAttempt, digest: str, exercise: GrammarExercise, answer: object,
            revision: str, revision_current: bool) -> dict:
    receipt = attempt.submission_receipt
    if not isinstance(receipt, dict):
        raise NativeLessonError('grading_failed', 503)
    if digest != receipt['digest']:
        raise NativeLessonError('submission_mismatch', 409)
    result = {**receipt['response'], 'is_correct': receipt.get('original_is_correct', attempt.is_correct)}
    if receipt['answer_from_attempt']:
        result['user_answer'] = attempt.user_answer
    if revision_current and receipt['grader_version'] == LAB_GRADER_VERSION:
        return _with_dispute_token(result, exercise, attempt, answer, revision)
    return result


def _with_dispute_token(
    result: dict, exercise: GrammarExercise, attempt: GrammarAttempt, answer: object, revision: str,
) -> dict:
    if result.get('is_correct') is False and normalized_lab_answer(exercise, answer) is not None:
        return {**result, 'dispute_token': issue_rejection_receipt(
            attempt.user_id, exercise.id, revision, answer, attempt_id=attempt.id,
        )}
    return result
