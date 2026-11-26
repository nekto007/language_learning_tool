"""Server-owned correction queue for the opt-in web practice renderer."""

from copy import deepcopy
from fractions import Fraction
from typing import Any

from flask import request
from flask_login import current_user
from itsdangerous import BadData, SignatureExpired

from app.api.native_lessons import (
    NativeLessonError, _content, _digest, _guard_plan, _lesson_and_progress, _signer, _version, project_questions,
)
from app.curriculum.constants import get_lesson_passing_score, is_objective_practice
from app.curriculum.models import LessonAttempt, LessonProgress, Lessons
from app.curriculum.services.progress_service import _invalidate_user_progress_cache, _lock_progress_writer
from app.utils.db import db

FLOW = 'weighted_web_v1'


class WebPracticeRound(db.Model):
    """One resumable web round, independent of native progress versioning."""

    __tablename__ = 'web_practice_rounds'

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)
    revision = db.Column(db.String(64), nullable=False)
    progress_version = db.Column(db.String(64), nullable=False)
    web_course = db.Column(db.Boolean, nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    state = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.Index('ix_web_practice_round_resume', 'user_id', 'lesson_id', 'web_course', 'completed'),
    )


def _find_round(round_id: str, lesson_id: int) -> WebPracticeRound | None:
    return WebPracticeRound.query.filter_by(id=round_id, user_id=current_user.id, lesson_id=lesson_id).first()


def _active_round(lesson_id: int, sealed: dict) -> WebPracticeRound | None:
    return WebPracticeRound.query.filter_by(
        user_id=current_user.id, lesson_id=lesson_id, revision=sealed['revision'],
        progress_version=sealed['version'], web_course=sealed.get('web_course') is True, completed=False,
    ).first()


def _view(state: dict, round_id: str) -> dict:
    first = state['first']
    queued = state['queue']
    phase = 'final' if state.get('result') else 'first' if len(first) < len(state['question_ids']) else 'correction'
    if phase == 'correction' and not queued:
        phase = 'ready'
    question_id = state['question_ids'][len(first)] if phase == 'first' else (queued[0] if queued else None)
    return {
        'id': round_id, 'step': len(state['events']), 'phase': phase, 'question_id': question_id,
        'remaining': len(queued), 'first_correct': sum(event['feedback']['correct'] for event in first.values()),
        'result': state.get('result'),
    }


def _initial(question_ids: list[str]) -> dict:
    return {'question_ids': question_ids, 'events': [], 'first': {}, 'queue': [], 'solved': {}}


def attach_round(value: dict, lesson_id: int) -> None:
    """Opt in only the current web renderer. Earlier documents remain valid."""
    lesson = value['lesson']
    if not lesson.get('immediate_feedback') or not lesson.get('questions') or lesson.get('quiz_phase') != 'first':
        return
    sealed = _signer().loads(lesson['session_token'])
    if not sealed.get('web_course') and _guard_plan(lesson_id) == 'challenge':
        return
    requested = request.args.get('round')
    row = _find_round(requested, lesson_id) if requested and len(requested) == 32 else None
    if row and (row.revision != sealed['revision'] or row.web_course != bool(sealed.get('web_course'))
                or (not row.completed and row.progress_version != sealed['version'])):
        row = None
    row = row or _active_round(lesson_id, sealed)
    round_id = row.id if row else sealed['nonce']
    question_ids = [q['id'] for q in lesson['questions']]
    state = row.state if row else _initial(question_ids)
    sealed.update(web_round=FLOW, nonce=round_id)
    if row:
        sealed['started_at'] = state['started_at']
    if row and row.completed:
        sealed['version'] = row.progress_version
    lesson['session_token'] = _signer().dumps(sealed)
    lesson['web_round'] = _view(state, round_id)


def read_token(token: object, lesson_id: int) -> tuple[dict, bool]:
    if not isinstance(token, str):
        raise NativeLessonError('invalid_input')
    try:
        expired = False
        try:
            sealed = _signer().loads(token, max_age=21600)
        except SignatureExpired:
            expired = True
            sealed = _signer().loads(token)
    except BadData:
        raise NativeLessonError('lesson_changed', 409) from None
    if not isinstance(sealed, dict) or sealed.get('web_round') != FLOW:
        raise NativeLessonError('lesson_changed', 409)
    if sealed['user'] != current_user.id or sealed['lesson'] != lesson_id:
        raise NativeLessonError('access_denied', 403)
    return sealed, expired


def weighted_score(solved: dict[str, int], count: int) -> int:
    """Exact floor even at thresholds and after many unsuccessful checks."""
    return int(100 * sum((Fraction(4, 5) ** (attempt - 1) for attempt in solved.values()), Fraction()) / count)


def _record(state: dict, question: dict, answer: str, feedback: dict) -> None:
    from app.curriculum.answer_disputes import course_answer_hash

    question_id = question['id']
    rank = 1 + sum(event['question_id'] == question_id for event in state['events'])
    event = {'question_id': question_id, 'answer': answer, 'feedback': feedback, 'rank': rank,
             'answer_hash': course_answer_hash(question, answer)}
    first = question_id not in state['first']
    state['events'].append(event)
    if first:
        state['first'][question_id] = deepcopy(event)
    else:
        state['queue'].pop(0)
    if feedback['correct']:
        state['solved'][question_id] = rank
    else:
        state['queue'].append(question_id)


def _final_feedback(state: dict) -> list[dict]:
    solved = state['solved']
    winning = {event['question_id']: event['feedback'] for event in state['events']
               if solved.get(event['question_id']) == event['rank']}
    return [
        {**state['first'][qid]['feedback'], 'web_resolution': {
            'rank': solved[qid], 'answer': winning[qid].get('answer_display') or winning[qid]['answer'],
        }} for qid in state['question_ids']
    ]


def _finish(lesson: Lessons, progress: Any, sealed: dict, questions: list[dict], state: dict) -> dict:
    from app.api.native_content import grade, persist

    first = state['first']
    answers = {qid: first[qid]['answer'] for qid in state['question_ids']}
    passing = get_lesson_passing_score(lesson)
    scored, _, assessment, _ = grade(lesson, questions, answers, passing)
    # Stored first verdicts are the evidence the learner actually received.
    feedback = _final_feedback(state)
    first_correct = sum(f['correct'] for f in feedback)
    first_score = scored['score']
    score = weighted_score(state['solved'], len(questions))
    scored.update(score=score, passed=True, web_weighted={
        'round_id': sealed['nonce'], 'completed': True,
        'first_score': first_score, 'first_correct_count': first_correct,
    })
    return persist(lesson, progress, scored, feedback, assessment, True,
                   {key: value for key, value in sealed.items() if key != 'quiz_flow'}, passing,
                   answers=answers, questions=questions, xp_score=first_score, commit=False)


def check_round(lesson_id: int, body: object) -> dict:
    from app.api.native_content import NATIVE_PROJECTION_VERSION, check_course_answer

    if (not isinstance(body, dict) or set(body) != {'session_token', 'step', 'question_id', 'answer'}
            or type(body['step']) is not int or body['step'] < 0
            or not isinstance(body['question_id'], str) or not isinstance(body['answer'], str)):
        raise NativeLessonError('invalid_input')
    sealed, expired = read_token(body['session_token'], lesson_id)
    # Content moderation locks the lesson before reconciling the learner.
    Lessons.query.filter_by(id=lesson_id).with_for_update(read=True).first()
    _lock_progress_writer(current_user.id)
    lesson, progress = _lesson_and_progress(lesson_id)
    qid, answer, step = body['question_id'], body['answer'], body['step']
    row = _find_round(sealed['nonce'], lesson_id)
    if row and step < len(row.state['events']):
        event = row.state['events'][step]
        if (qid, answer) != (event['question_id'], event['answer']):
            raise NativeLessonError('round_step_changed', 409)
        return {'success': True, 'feedback': event['feedback'], 'round': _view(row.state, row.id)}

    if row and row.completed and step == len(row.state['events']) and not qid and not answer and row.state.get('explicit_finish'):
        return {'success': True, 'feedback': None, 'round': _view(row.state, row.id)}

    if (expired or sealed['lesson_type'] != lesson.type or not is_objective_practice(lesson)
            or sealed['projection_version'] != NATIVE_PROJECTION_VERSION
            or (row.revision if row else sealed['revision']) != _digest(_content(lesson))
            or sealed['version'] != _version(progress)):
        raise NativeLessonError('lesson_changed', 409)
    if not sealed.get('web_course') and _guard_plan(lesson_id) == 'challenge':
        raise NativeLessonError('access_denied', 403)
    questions = project_questions(lesson)
    by_id = {q['id']: q for q in questions}
    if row:
        if row.completed:
            raise NativeLessonError('round_step_changed', 409)
        state = deepcopy(row.state)
    else:
        if _active_round(lesson_id, sealed):
            raise NativeLessonError('round_step_changed', 409)
        state = _initial(list(by_id))
        state['started_at'] = sealed['started_at']
    before = _view(state, sealed['nonce'])
    if before['phase'] == 'ready' and not qid and not answer and step == before['step']:
        state['explicit_finish'] = True
        feedback = None
    else:
        if (qid, step) != (before['question_id'], before['step']):
            raise NativeLessonError('round_step_changed', 409)
        feedback = check_course_answer(lesson, by_id[qid], answer)
        _record(state, by_id[qid], answer, feedback)
    if row is None:
        row = WebPracticeRound(id=sealed['nonce'], user_id=current_user.id, lesson_id=lesson_id,
                               revision=sealed['revision'], progress_version=sealed['version'],
                               web_course=bool(sealed.get('web_course')), completed=False, state=state)
        db.session.add(row)
    if len(state['solved']) == len(by_id):
        sealed.update(started_at=state['started_at'], revision=row.revision)
        state['result'] = _finish(lesson, progress, sealed, questions, state)
        row.completed = True
    row.state = state
    db.session.commit()
    if row.completed:
        _invalidate_user_progress_cache(row.user_id)
    return {'success': True, 'feedback': feedback, 'round': _view(state, row.id)}


def rejected_round_answer(lesson_id: int, body: dict) -> tuple[Lessons, dict, str, dict]:
    """Resolve the exact rejected event recorded by a weighted web round."""
    from app.curriculum.answer_disputes import DISPUTABLE_LESSON_TYPES, course_answer_hash

    sealed, expired = read_token(body.get('session_token'), lesson_id)
    lesson, _ = _lesson_and_progress(lesson_id)
    if not sealed.get('web_course'):
        _guard_plan(lesson_id)
    if expired or lesson.type not in DISPUTABLE_LESSON_TYPES:
        raise NativeLessonError('not_found', 404)
    row = _find_round(sealed['nonce'], lesson_id)
    qid, answer = body.get('question_id'), body.get('answer')
    if not isinstance(qid, str) or not isinstance(answer, str) or not row or row.revision != _digest(_content(lesson)):
        raise NativeLessonError('lesson_changed', 409)
    question = next((q for q in project_questions(lesson) if q['id'] == qid), None)
    if question is None or not any(
        event['question_id'] == qid and event['answer'] == answer and not event['feedback']['correct']
        and event['answer_hash'] == course_answer_hash(question, answer) for event in row.state['events']
    ):
        raise NativeLessonError('answer_not_rejected')
    return lesson, question, answer, sealed


def credit_report(report: Any, case: Any, lesson: Lessons, previous_revision: str | None) -> tuple[bool, str | None]:
    """Move only the proven response's weight, preserving every other question."""
    from app.api.native_content import check_course_answer

    row = WebPracticeRound.query.filter_by(
        id=report.course_nonce, user_id=report.user_id, lesson_id=lesson.id,
    ).populate_existing().with_for_update().one_or_none()
    if row is None:
        return False, None
    revision = (case.review or {}).get('updated_revision')
    if not previous_revision or not revision or row.revision not in (previous_revision, revision):
        return True, None
    qid = case.question_id
    state = deepcopy(row.state)
    question = next((q for q in project_questions(lesson) if q['id'] == qid), None)
    if question is None:
        return True, None
    event = next((item for item in state['events'] if item['question_id'] == qid
                  and not item['feedback']['correct']
                  and item['answer_hash'] == case.normalized_answer_hash), None)
    if not event or not check_course_answer(lesson, question, event['answer'])['correct']:
        return True, None

    solved = state['solved']
    if qid in solved and solved[qid] <= event['rank']:
        return True, None
    solved[qid] = event['rank']
    state['queue'] = [key for key in state['queue'] if key != qid]
    if event['rank'] == 1:
        # The event is the original response receipt. Keep it and update the
        # judgement used in the first-pass review and weighted history.
        first = state['first'][qid]
        first['feedback'] = {**first['feedback'], 'correct': True, 'expected': first['feedback']['answer']}
    row.revision = revision
    if row.completed:
        progress = LessonProgress.query.filter_by(user_id=report.user_id, lesson_id=lesson.id).populate_existing().first()
        attempt = LessonAttempt.query.filter_by(
            user_id=report.user_id, lesson_id=lesson.id, submission_nonce=row.id,
        ).populate_existing().one_or_none()
        if progress is None or attempt is None:
            return True, None
        result = state['result']
        correct = sum(entry['feedback']['correct'] for entry in state['first'].values())
        score = weighted_score(solved, len(state['question_ids']))
        result['score'] = score
        if event['rank'] == 1:
            result['correct_count'] = correct
            result['web_weighted'].update(first_correct_count=correct,
                                          first_score=round(100 * correct / len(state['question_ids']), 2))

            attempt.correct_answers = correct
            attempt.mistakes = [item for item in attempt.mistakes if item.get('question_id') != qid]
        result['feedback'] = _final_feedback(state)
        attempt.score = score
        current = deepcopy(progress.data) if isinstance(progress.data, dict) else {}
        if current.get('web_weighted', {}).get('round_id') == row.id:
            progress.record_score(score)
            current.update(score=score, web_weighted=result['web_weighted'])
            current['_native_submission']['response'] = result
            if isinstance(current.get('feedback'), dict) and event['rank'] == 1 and qid in current['feedback']:
                current['feedback'][qid].update(status='correct', correct_answer=event['feedback']['answer'])
            progress.data = current
        else:
            progress.best_score = max(progress.best_score or 0, progress.score or 0, score)
            progress.score = progress.best_score
        row.state = state
        return True, f'Ответ зачтён. Результат попытки — {score}%.'
    row.state = state
    return True, 'Ответ зачтён в текущей попытке.'
