"""Register evidence from a rejected native first-round quiz check."""

import re
from typing import Any

from flask import current_app
from itsdangerous import BadData, SignatureExpired, URLSafeTimedSerializer

from app.api import native_lessons
from app.api.native_lessons import (
    COURSE_SESSION_SECONDS, NativeLessonError, _content, _digest, _version, checked_course_answer,
)
from app.api.quiz_corrections import FLOW
from app.auth.models import User
from app.curriculum.answer_disputes import (
    GRADER_VERSION,
    AnswerDisputeReport,
    NativeCourseDisputeReceipt,
    _hash,
    attach_native_course_dispute,
    lock_native_course_dispute,
)
from app.curriculum.models import LessonProgress, Lessons
from app.utils.db import db

_INPUTS = frozenset(('choice', 'text'))


def _receipt_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='native-quiz-dispute-v1')


def _first_quiz(sealed: dict[str, Any]) -> bool:
    nonce = sealed.get('nonce')
    return bool(
        sealed.get('lesson_type') == 'quiz' and sealed.get('quiz_flow') == FLOW
        and sealed.get('quiz_phase') == 'first' and isinstance(nonce, str)
        and re.fullmatch(r'[a-f0-9]{32}', nonce)
    )


def issue_quiz_dispute_receipt(
    lesson: Lessons, question: dict, answer: str, sealed: dict, session_token: str,
) -> str | None:
    input_kind = question.get('input')
    if (lesson.type != 'quiz' or not _first_quiz(sealed) or input_kind not in _INPUTS
            or len(answer) > 2000 or '\x00' in answer or sealed['revision'] != _digest(_content(lesson))):
        return None
    try:
        answer.encode('utf-8')
    except UnicodeEncodeError:
        return None
    return _receipt_signer().dumps({
        'session': session_token, 'grader': GRADER_VERSION, 'question': question['id'], 'kind': input_kind,
        'answer_digest': _hash(answer),
    })


def _accepted(receipt_id: str, user_id: int) -> int | None:
    row = (db.session.query(AnswerDisputeReport.dispute_id)
           .join(NativeCourseDisputeReceipt, NativeCourseDisputeReceipt.report_id == AnswerDisputeReport.id)
           .filter(NativeCourseDisputeReceipt.id == receipt_id, AnswerDisputeReport.user_id == user_id)
           .one_or_none())
    return row.dispute_id if row is not None else None


def _read_proof(lesson_id: int, user_id: int, data: object) -> tuple[dict, dict, dict]:
    if (not isinstance(data, dict) or set(data) != {'dispute_token', 'question_id', 'answer'}
            or not isinstance(data['dispute_token'], str) or not 0 < len(data['dispute_token']) <= 4096
            or not isinstance(data['question_id'], str) or not isinstance(data['answer'], str)
            or not data['answer'].strip() or len(data['answer']) > 2000):
        raise NativeLessonError('invalid_input')
    try:
        proof = _receipt_signer().loads(data['dispute_token'], max_age=COURSE_SESSION_SECONDS)
        if not isinstance(proof, dict) or not isinstance(proof.get('session'), str):
            raise NativeLessonError('dispute_receipt_invalid', 409)
        sealed = native_lessons._signer().loads(proof['session'], max_age=COURSE_SESSION_SECONDS)
    except SignatureExpired:
        raise NativeLessonError('dispute_session_expired', 409) from None
    except BadData:
        raise NativeLessonError('dispute_receipt_invalid', 409) from None
    if not isinstance(sealed, dict) or sealed.get('user') != user_id or sealed.get('lesson') != lesson_id:
        raise NativeLessonError('access_denied', 403)
    if not _first_quiz(sealed) or proof.get('kind') not in _INPUTS:
        raise NativeLessonError('dispute_receipt_invalid', 409)
    if proof.get('question') != data['question_id'] or proof.get('answer_digest') != _hash(data['answer']):
        raise NativeLessonError('invalid_input')
    return proof, sealed, data


def _checked_rejection(lesson_id: int, proof: dict, data: dict) -> tuple[Lessons, dict]:
    if proof.get('grader') != GRADER_VERSION:
        raise NativeLessonError('lesson_changed', 409)
    lesson, question, _, feedback, _ = checked_course_answer(
        lesson_id, lesson_types=frozenset(('quiz',)), strict_dispute_revision=True,
        body={'session_token': proof['session'], 'question_id': data['question_id'], 'answer': data['answer']},
    )
    if question.get('input') != proof['kind'] or feedback['correct'] is not False:
        raise NativeLessonError('answer_not_rejected')
    return lesson, question


def register_quiz_dispute(lesson_id: int, user_id: int, data: object) -> int:
    from app.curriculum.services.progress_service import _invalidate_user_progress_cache

    proof, sealed, body = _read_proof(lesson_id, user_id, data)
    receipt_id = _hash(proof)
    if (accepted := _accepted(receipt_id, user_id)) is not None:
        return accepted
    try:
        lesson, question = _checked_rejection(lesson_id, proof, body)
    except NativeLessonError:
        # Another request may have committed the same receipt while the check
        # was running and the learner or editor moved the session forward.
        if (accepted := _accepted(receipt_id, user_id)) is not None:
            return accepted
        raise
    try:
        # Match the review workflow's case -> lesson -> account lock order.
        # Submission holds the account row while it commits the attempt.
        case = lock_native_course_dispute(db.session, lesson, question, body['answer'])
        if (accepted := _accepted(receipt_id, user_id)) is not None:
            db.session.rollback()
            return accepted
        lesson = (Lessons.query.filter_by(id=lesson_id).populate_existing()
                  .with_for_update(read=True).one())
        if lesson.type != 'quiz' or sealed['revision'] != _digest(_content(lesson)):
            raise NativeLessonError('lesson_changed', 409)
        db.session.query(User.id).filter_by(id=user_id).with_for_update().one()
        progress = LessonProgress.query.filter_by(user_id=user_id, lesson_id=lesson_id).populate_existing().one_or_none()
        if sealed['version'] != _version(progress):
            raise NativeLessonError('dispute_session_closed', 409)
        owners = attach_native_course_dispute(db.session, case, user_id, NativeCourseDisputeReceipt(
            id=receipt_id, nonce=sealed['nonce'], input_kind=proof['kind'], answer=body['answer'],
        ))
        dispute_id = case.id
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    for owner in owners:
        _invalidate_user_progress_cache(owner)
    return dispute_id
