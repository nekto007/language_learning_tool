"""Restore an approved answer to its learner's verified submission."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import or_

from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute, AnswerDisputeReport, course_answer_hash
from app.curriculum.constants import get_lesson_passing_score
from app.curriculum.models import LessonAttempt, LessonProgress, Lessons
from app.daily_plan.linear.models import QuizErrorLog
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, UserGrammarExercise
from app.notifications.services import create_notification
from app.utils.db import db


def course_revision_matches(sealed: dict, lesson: Lessons, revision: str) -> bool:
    """Permit an open reporter session to finish after this exact approved edit."""
    if sealed.get('revision') == revision:
        return True
    if (lesson.type not in ('grammar', 'quiz') or not isinstance(sealed.get('nonce'), str)
            or not isinstance(sealed.get('revision'), str)):
        return False
    return db.session.query(AnswerDisputeReport.id).join(AnswerDispute).filter(
        AnswerDisputeReport.user_id == sealed['user'], AnswerDisputeReport.course_nonce == sealed['nonce'],
        AnswerDispute.lesson_id == lesson.id, AnswerDispute.status == 'applied',
        AnswerDispute.review['previous_revision'].as_string() == sealed['revision'],
        AnswerDispute.review['updated_revision'].as_string() == revision,
    ).first() is not None


def submitted_mistakes(questions: list[dict], feedback: list[dict], answers: dict) -> list[dict]:
    """Bind each rejected answer to the exact field and value actually submitted."""
    by_id = {q['id']: q for q in questions}
    return [
        {'question': row['prompt'], 'answer': row['answer'], 'question_id': row['id'],
         'answer_hash': course_answer_hash(by_id[row['id']], answers[row['id']])}
        for row in feedback if not row['correct']
    ]


def _credit_lab(report: AnswerDisputeReport, exercise: GrammarExercise) -> bool:
    if report.grammar_attempt_id is None:
        return False
    attempt = GrammarAttempt.query.filter_by(
        id=report.grammar_attempt_id, user_id=report.user_id, exercise_id=exercise.id,
    ).populate_existing().with_for_update().one_or_none()
    if attempt is None or attempt.is_correct:
        return False
    if isinstance(attempt.submission_receipt, dict):
        # Replaying a lost original response must still return its original grade.
        attempt.submission_receipt = {**attempt.submission_receipt, 'original_is_correct': False}
    attempt.is_correct = True
    progress = UserGrammarExercise.query.filter_by(
        user_id=report.user_id, exercise_id=exercise.id,
    ).populate_existing().with_for_update().one_or_none()
    if progress is not None and (progress.incorrect_count or 0) > 0:
        progress.incorrect_count -= 1
        progress.correct_count = (progress.correct_count or 0) + 1
    return True


def _resolve_correction(progress: LessonProgress, state: dict, qid: str,
                        previous_revision: str | None, updated_revision: str, now: datetime) -> None:
    """Remove only the confirmed question from this specific correction round."""
    pending = state.get('pending_ids')
    if (state.get('status') != 'pending' or not isinstance(pending, list) or qid not in pending
            or not state.get('attempt_id') or not previous_revision
            or state.get('revision') not in (previous_revision, updated_revision)):
        return
    state['pending_ids'] = [key for key in pending if key != qid]
    if state['revision'] == previous_revision:
        state['revision'] = updated_revision
    if not state['pending_ids']:
        state.update(status='completed', completed_at=now.isoformat())
        progress.status = 'completed'
        progress.completed_at = progress.completed_at or now
    errors = QuizErrorLog.query.filter(
        QuizErrorLog.user_id == progress.user_id, QuizErrorLog.lesson_id == progress.lesson_id,
        QuizErrorLog.resolved_at.is_(None),
        QuizErrorLog.question_payload['quiz_attempt_id'].as_string() == state['attempt_id'],
        QuizErrorLog.question_payload['question_index'].as_integer() == int(qid),
    ).all()
    for error in errors:
        error.resolved_at = now


def _correct_feedback(rows: object, qid: str, accepted: str) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if isinstance(row, dict) and row.get('id') == qid:
            row.update(correct=True, expected=accepted)


def _credit_course(report: AnswerDisputeReport, case: AnswerDispute, lesson: Lessons,
                   previous_revision: str | None) -> str | None:
    if not report.course_nonce:
        return None
    # Course submission serializes on the same account. Acquire in user-id order
    # in the outer loop before reading a current receipt or historical attempt.
    db.session.query(User.id).filter_by(id=report.user_id).with_for_update(read=True, key_share=True).one()
    progress = LessonProgress.query.filter_by(
        user_id=report.user_id, lesson_id=lesson.id,
    ).populate_existing().with_for_update().one_or_none()
    if progress is None:
        return None
    data = deepcopy(progress.data) if isinstance(progress.data, dict) else {}
    state = data.get('quiz_correction')
    if not isinstance(state, dict):
        state = {}
    qid = case.question_id
    if report.course_correction_id:
        if (state.get('attempt_id') != report.course_correction_id or state.get('status') != 'pending'
                or not isinstance(state.get('pending_ids'), list) or qid not in state['pending_ids']
                or not previous_revision or state.get('revision') != previous_revision):
            return None
        _resolve_correction(progress, state, qid, previous_revision, case.review['updated_revision'], report.created_at)
        progress.data = data
        return ('Исправление зачтено. Урок пройден.' if progress.status == 'completed' else
                'Исправление зачтено. Остались другие задания для разбора.')

    attempts = LessonAttempt.query.filter_by(
        user_id=report.user_id, lesson_id=lesson.id, lesson_progress_id=progress.id,
        submission_nonce=report.course_nonce,
    ).populate_existing().with_for_update().limit(2).all()
    if len(attempts) != 1:
        return None
    attempt = attempts[0]
    mistakes = attempt.mistakes
    if not isinstance(mistakes, list):
        return None
    matching = [m for m in mistakes if isinstance(m, dict) and m.get('question_id') == qid
                and m.get('answer_hash') == case.normalized_answer_hash]
    if (len(matching) != 1 or not attempt.completed_at or not attempt.total_questions
            or attempt.correct_answers is None or not 0 <= attempt.correct_answers < attempt.total_questions):
        return None
    attempt.mistakes = [mistake for mistake in mistakes if mistake is not matching[0]]
    attempt.correct_answers += 1
    attempt.score = round(100 * attempt.correct_answers / attempt.total_questions, 2)
    attempt.passed = attempt.score >= get_lesson_passing_score(lesson)
    receipt = data.get('_native_submission')
    if (not isinstance(receipt, dict) or receipt.get('nonce') != report.course_nonce
            or not isinstance(receipt.get('response'), dict)):
        # The learner may have submitted a newer round in the meantime.
        progress.best_score = max(progress.best_score or 0, progress.score or 0, attempt.score)
        progress.score = progress.best_score
    else:
        progress.record_score(attempt.score)
        response = receipt['response']
        response.update(score=attempt.score, correct_count=attempt.correct_answers, passed=attempt.passed)
        accepted = str(case.review.get('shown_answer') or matching[0].get('answer') or case.evidence['answer'])
        _correct_feedback(response.get('feedback'), qid, accepted)
        for key in ('correct_answers', 'correct_exercises', 'correct_items'):
            if key in data:
                data[key] = attempt.correct_answers
        data.update(score=attempt.score, passed=attempt.passed)
        if isinstance(data.get('feedback'), dict) and isinstance(data['feedback'].get(qid), dict):
            data['feedback'][qid].update(status='correct', message='Ответ верный.', correct_answer=accepted)
        if state.get('status') in ('pending', 'completed'):
            state.update(first_score=attempt.score, first_passed=attempt.passed,
                         first_correct_count=attempt.correct_answers)
            _correct_feedback(state.get('feedback'), qid, accepted)
            _resolve_correction(progress, state, qid, previous_revision, case.review['updated_revision'],
                                attempt.completed_at)
            completed = state.get('status') == 'completed'
            response.update(completed=completed, correction_pending=not completed)
            if isinstance(state.get('receipt'), dict) and isinstance(state['receipt'].get('response'), dict):
                state['receipt']['response'].update(score=attempt.score, passed=attempt.passed)
        elif attempt.passed and not data.get('quiz_correction'):
            progress.status = 'completed'
            progress.completed_at = progress.completed_at or attempt.completed_at
            if 'completed' in response:
                response['completed'] = True
        progress.data = data
    result = f'Ответ зачтён. Результат попытки — {attempt.score:g}%.'
    return result + (' Урок пройден.' if progress.status == 'completed' else '')


def credit_approved_reports(case: AnswerDispute, *, previous_revision: str | None = None) -> set[int]:
    """Settle reports atomically; callers invalidate the returned owners after commit."""
    course_owners = set()
    if case.status != 'applied':
        return course_owners
    reports = (AnswerDisputeReport.query.filter_by(dispute_id=case.id)
               .filter(or_(AnswerDisputeReport.thanked_at.is_(None), AnswerDisputeReport.credited_at.is_(None)))
               .order_by(AnswerDisputeReport.user_id).populate_existing().with_for_update().all())
    if not reports:
        return course_owners
    previous_revision = previous_revision or case.review.get('previous_revision')
    if case.grammar_exercise_id is not None:
        exercise = db.session.get(GrammarExercise, case.grammar_exercise_id)
        title = exercise.topic.title_ru
        link = '/grammar-lab/topic/' + quote(exercise.topic.slug, safe='')
    else:
        lesson = db.session.get(Lessons, case.lesson_id)
        title = lesson.title
        link = f'/learn/{lesson.id}/'
    now = datetime.now(UTC)
    for report in reports:
        if case.review.get('accepts_report') is False:
            if report.thanked_at is None:
                create_notification(
                    report.user_id, 'answer_review', title='Спасибо за внимательность!',
                    message=f'Мы исправили задание в «{title}». После повторной проверки оценка твоего ответа остаётся прежней.',
                    link=link, icon='💬',
                )
                report.thanked_at = now
            continue
        if report.credited_at is not None:
            result = 'Ответ зачтён.'
        elif case.grammar_exercise_id is not None:
            result = 'Ответ в упражнении зачтён.' if _credit_lab(report, exercise) else None
        else:
            result = _credit_course(report, case, lesson, previous_revision)
            if result is not None:
                course_owners.add(report.user_id)
        if result is not None:
            report.credited_at = report.credited_at or now
        if report.thanked_at is not None:
            continue
        result = result or 'Теперь проверка принимает твой вариант.'
        create_notification(report.user_id, 'answer_review', title='Спасибо за уточнение ответа!',
                            message=f'Мы приняли твой ответ в «{title}». {result}', link=link, icon='💬')
        report.thanked_at = now
    return course_owners
