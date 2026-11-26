"""Native, server-graded course lessons. The browser endpoints remain unchanged."""
import hashlib
import json
import logging
import re
from datetime import datetime, UTC
from html.parser import HTMLParser
from uuid import uuid4
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.curriculum.models import Lessons

from flask import Blueprint, Response, current_app, jsonify, request
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_lessons = Blueprint('api_native_lessons', __name__)
logger = logging.getLogger(__name__)
MAX_QUESTIONS = 100
COURSE_SESSION_SECONDS = 6 * 60 * 60


class NativeLessonError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if not self.hidden and tag in ('br', 'p', 'div', 'li', 'tr', 'h2', 'h3'):
            self.parts.append('\n')
        if not self.hidden and tag in ('td', 'th'):
            self.parts.append(' · ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in ('p', 'div', 'li', 'tr', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    if not isinstance(value, (str, int, float, bool)):
        return ''
    parser = _PlainText()
    parser.feed(str(value))
    text = '\n'.join(filter(None, (re.sub(r'[ \t\r]+', ' ', s).strip(' ·') for s in ''.join(parser.parts).split('\n')))).strip()
    if len(text) > 20000:
        raise NativeLessonError('unsupported_lesson', 422)
    return text


def _content(lesson):
    content = lesson.content
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            content = None
    if not isinstance(content, dict):
        raise NativeLessonError('unsupported_lesson', 422)
    return content


def _digest(content):
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _version(progress):
    if progress is None:
        return 'none'
    return _digest({'activity': str(progress.last_activity), 'status': progress.status, 'data': progress.data})


def _signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='native-course-v1')


def _session_type_matches(sealed: dict[str, object], lesson: 'Lessons') -> bool:
    # Keep pre-upgrade ordinary/correction sessions usable. A legacy untyped
    # document cannot prove it was opened as an independent, no-hints final.
    fallback = lesson.type if lesson.type != 'final_test' else None
    return sealed.get('lesson_type', fallback) == lesson.type


def project_questions(lesson):
    from app.api.native_content import is_extended, project
    if is_extended(lesson): return project(lesson)
    content = _content(lesson)
    if lesson.type not in ('grammar', 'quiz'):
        raise NativeLessonError('unsupported_lesson', 422)
    if lesson.type == 'quiz' and any(content.get(k) for k in ('audio', 'audio_url', 'video', 'video_url', 'transcript')):
        raise NativeLessonError('unsupported_lesson', 422)
    raw = content.get('exercises' if lesson.type == 'grammar' else 'questions')
    if lesson.type == 'grammar' and (raw is None or raw == []) and _theory(content):
        return []
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_QUESTIONS:
        raise NativeLessonError('unsupported_lesson', 422)
    supported = ({'', 'multiple_choice', 'true_false', 'fill_blank', 'fill-blank', 'fill_in_blank', 'fill-in-blank', 'error_correction', 'reorder', 'translation', 'transformation'} if lesson.type == 'grammar' else {'multiple_choice', 'true_false', 'fill_blank', 'fill_in_blank', 'fill-in-blank', 'translation', 'transformation', 'reorder', 'ordering'})
    from app.curriculum.language_support import language_support_mode, question_translation
    support = language_support_mode(lesson)
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or item.get('type', 'multiple_choice' if lesson.type == 'quiz' else '') not in supported:
            raise NativeLessonError('unsupported_lesson', 422)
        kind = item.get('type', 'multiple_choice' if lesson.type == 'quiz' else '')
        answer_fields = ('answer', 'correct_answer', 'correct', 'answers', 'correct_sentence') if lesson.type == 'grammar' else ('answer', 'correct_answer', 'correct', 'correct_index')
        if not any(key in item and item[key] is not None and item[key] != '' and item[key] != [] for key in answer_fields):
            raise NativeLessonError('unsupported_lesson', 422)
        if any(item.get(key) for key in ('audio', 'audio_url', 'image', 'image_url', 'video', 'video_url', 'transcript')):
            raise NativeLessonError('unsupported_lesson', 422)
        parts = [plain(item.get(key)) for key in ('question', 'prompt', 'text', 'sentence', 'incorrect_sentence')]
        prompt = '\n'.join(dict.fromkeys(p for p in parts if p))
        if not prompt and kind == 'reorder' and isinstance(item.get('words'), list):
            prompt = ' / '.join(plain(word) for word in item['words'])
        if not prompt:
            raise NativeLessonError('unsupported_lesson', 422)
        options = []
        if kind == 'true_false':
            options = [{'value': 'true', 'label': 'Верно / True'}, {'value': 'false', 'label': 'Неверно / False'}]
        elif kind == 'multiple_choice' or (lesson.type == 'quiz' and kind == 'fill_blank' and item.get('options')):
            choices = item.get('options')
            if not isinstance(choices, list) or not 2 <= len(choices) <= 12 or not all(isinstance(o, str) and plain(o) for o in choices):
                raise NativeLessonError('unsupported_lesson', 422)
            options = [{'value': str(i), 'label': plain(o)} for i, o in enumerate(choices)]
        instruction = plain(item.get('instruction')) or ('Выбери ответ' if options else 'Введи ответ')
        result.append({'id': str(index), 'prompt': prompt, 'instruction': instruction, 'options': options,
                       'input': 'choice' if options else 'text',
                       'translation': plain(question_translation(item)) if support in ('inline', 'toggle') else None})
    return result


def _theory(content):
    from app.api.native_theory import project_theory

    return project_theory(content, plain)


def _lesson_and_progress(lesson_id):
    from app.curriculum.models import Lessons, LessonProgress
    from app.curriculum.security import check_lesson_access
    lesson = Lessons.query.populate_existing().get(lesson_id)
    if lesson is None:
        raise NativeLessonError('not_found', 404)
    if not check_lesson_access(lesson_id):
        raise NativeLessonError('lesson_locked', 403)
    progress = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson_id).populate_existing().first()
    return lesson, progress


def _guard_plan(lesson_id):
    from app.daily_plan.service import get_daily_plan_unified
    from app.achievements.streak_service import compute_plan_steps
    from app.telegram.queries import get_daily_summary
    from app.utils.db import db
    from app.utils.time_utils import get_user_timezone_name
    tz = get_user_timezone_name(current_user.id, db.session)
    plan = get_daily_plan_unified(current_user.id, tz=tz)
    if plan.get('mode') == 'paused':
        raise NativeLessonError('plan_paused', 403)
    completed, *_ = compute_plan_steps(plan, get_daily_summary(current_user.id, tz=tz))
    required = plan.get('required') or []
    optional = plan.get('optional') or []
    done = lambda item: item.get('completed') or completed.get(item.get('id'), False)
    next_required = next((it for it in required if not done(it) and not it.get('skipped') and not it.get('blocked')), None)
    unlocked = plan.get('day_secured') or not required or all(done(it) or it.get('skipped') for it in required)
    next_optional = next((it for it in optional if not done(it)), None) if unlocked else None
    for item in required + optional:
        candidate_id = (item.get('data') or {}).get('lesson_id')
        if item.get('kind') in ('curriculum', 'listening', 'speaking', 'writing', 'challenge') and (candidate_id == lesson_id or item.get('id') == f'curriculum:{lesson_id}'):
            allowed = item in (next_required, next_optional) or (item in required and item.get('skipped'))
            if not item.get('blocked') and allowed:
                return item.get('kind')
    # Voluntary review may repeat an already completed lesson without reopening
    # it or allowing access to future, unstudied curriculum steps.
    from app.curriculum.models import LessonProgress
    reviewed = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson_id,
                                              status='completed').first()
    if getattr(reviewed, 'status', None) == 'completed':
        return 'review'
    raise NativeLessonError('lesson_locked', 403)


@api_native_lessons.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@api_native_lessons.errorhandler(NativeLessonError)
def native_error(error):
    return jsonify(success=False, error=error.code), error.status


@api_native_lessons.route('/lessons/<int:lesson_id>', methods=['GET'])
@api_bearer_required
@limiter.limit('60 per minute', key_func=get_authenticated_user_key)
def get_native_lesson(lesson_id):
    return course_document(lesson_id)


def project_course_document(lesson: 'Lessons', questions: list[dict], content: dict) -> dict:
    """Project authored course material without consulting the learner's plan."""
    from app.curriculum.constants import get_lesson_passing_score
    from app.curriculum.language_support import language_support_mode
    from app.api.native_content import is_extended, extras
    payload = {'id': lesson.id, 'title': plain(lesson.title), 'type': lesson.type,
               'content_revision': _digest(content),
               'passing_score': get_lesson_passing_score(lesson), 'theory': _theory(content),
               'questions': questions, 'support_mode': language_support_mode(lesson)}
    if is_extended(lesson): payload.update(extras(lesson))
    from app.api.learning_guidance import learning_guidance
    payload.update(learning_guidance(lesson))
    from app.grammar_lab.guided_learning import learning_steps, question_help, lesson_reference
    if lesson.type == 'grammar':
        payload['learning_steps'] = learning_steps(content, len(questions))
    from app.api.native_content import rows_for
    from app.curriculum.constants import is_objective_practice
    if is_objective_practice(lesson) and language_support_mode(lesson) in ('inline', 'toggle'):
        for i, (row, question) in enumerate(zip(rows_for(lesson), questions, strict=True)):
            help_blocks = question_help(content, row, i, len(questions))
            if help_blocks:
                question['theory_help'] = help_blocks
        if not payload['theory']:
            payload['theory'] = lesson_reference(lesson)
    payload['immediate_feedback'] = bool(questions) and is_objective_practice(lesson)
    return payload


def course_document(lesson_id: int, *, deferred: bool = False, web_course: bool = False) -> Response:
    from app.api.native_content import NATIVE_PROJECTION_VERSION
    from app.curriculum.constants import is_objective_practice
    from app.grammar_lab.guided_learning import lesson_reference

    lesson, progress = _lesson_and_progress(lesson_id)
    if web_course and lesson.type != 'final_test' and not is_objective_practice(lesson):
        raise NativeLessonError('not_found', 404)
    lesson._native_challenge = not web_course and _guard_plan(lesson_id) == "challenge"
    questions = project_questions(lesson)
    content = _content(lesson)
    payload = project_course_document(lesson, questions, content)
    sealed = {'user': current_user.id, 'lesson': lesson_id, 'lesson_type': lesson.type,
              'revision': payload['content_revision'], 'version': _version(progress),
              'projection_version': NATIVE_PROJECTION_VERSION,
              'nonce': uuid4().hex, 'started_at': datetime.now(UTC).isoformat()}
    if web_course:
        sealed['web_course'] = True
    from app.api.quiz_corrections import FLOW, eligible, pending_state, project_correction

    if questions and eligible(lesson) and (deferred or request.args.get('quiz_flow') == FLOW or pending_state(progress)):
        sealed['quiz_flow'] = FLOW
        sealed['quiz_phase'] = 'first'
        payload['quiz_phase'] = 'first'
        correction = project_correction(lesson, progress, questions, content)
        if correction:
            payload.update(correction)
            # Forced review is about the failed grammar rule, independent of
            # whether this CEFR level displays translations/theory shortcuts.
            if correction['correction']['theory_required'] and not payload['theory']:
                payload['theory'] = lesson_reference(lesson)
                if not payload['theory']:
                    # Legacy quizzes may have neither an authored chapter nor
                    # a linked grammar lesson. Review the actual explanations
                    # instead of presenting an empty mandatory theory page.
                    blocks = [b for q in correction['questions'] for b in q.get('theory_help', [])]
                    if not blocks:
                        blocks = [{'title': 'Разбор задания', 'body': q['correction_help']['hint'], 'kind': 'text'}
                                  for q in correction['questions'] if q.get('correction_help', {}).get('hint')]
                    payload['theory'] = list({b['body']: b for b in blocks}.values())
            sealed['quiz_phase'] = 'correction'
            sealed['correction_attempt'] = correction['correction']['attempt_id']
    if lesson.type == 'writing_prompt':
        from app.curriculum.writing_context import writing_snapshot

        question = questions[0]
        sealed['writing_prompt_snapshot'] = writing_snapshot(payload['title'], question['prompt'], question.get('translation'))
    payload['session_token'] = _signer().dumps(sealed)
    return jsonify(success=True, lesson=payload)


@api_native_lessons.post('/lessons/<int:lesson_id>/check')
@csrf.exempt
@api_bearer_required
@limiter.limit('90 per minute', key_func=get_authenticated_user_key)
def check_native_learning_answer(lesson_id: int) -> Response:
    from app.api.native_quiz_disputes import issue_quiz_dispute_receipt

    body = request.get_json(silent=True)
    lesson, question, answer, feedback, sealed = checked_course_answer(lesson_id, body=body)
    response = {'success': True, 'feedback': feedback}
    if feedback['correct'] is False:
        token = issue_quiz_dispute_receipt(lesson, question, answer, sealed, body['session_token'])
        if token is not None:
            response['dispute_token'] = token
    return jsonify(response)


@api_native_lessons.post('/lessons/<int:lesson_id>/dispute')
@csrf.exempt
@api_bearer_required
@limiter.limit('10 per minute', key_func=get_authenticated_user_key)
def dispute_native_quiz_answer(lesson_id: int) -> Response:
    from app.api.native_quiz_disputes import register_quiz_dispute

    dispute_id = register_quiz_dispute(lesson_id, current_user.id, request.get_json(silent=True))
    return jsonify(success=True, dispute_id=dispute_id)


def course_answer_check(lesson_id: int, *, allow_web_course: bool = False) -> Response:
    _, _, _, feedback, _ = checked_course_answer(lesson_id, allow_web_course=allow_web_course)
    return jsonify(success=True, feedback=feedback)


def checked_course_answer(
    lesson_id: int, *, lesson_types: frozenset[str] | None = None, body: object = None,
    strict_dispute_revision: bool = False,
    allow_web_course: bool = False,
) -> tuple['Lessons', dict, str, dict, dict]:
    """Check a session-bound answer without writing attempts or progress."""
    from app.api.native_content import NATIVE_PROJECTION_VERSION, rows_for

    if body is None:
        body = request.get_json(silent=True)
    if (not isinstance(body, dict) or set(body) - {'session_token', 'question_id', 'answer', 'help_level'}
            or not {'session_token', 'question_id', 'answer'} <= set(body)
            or not isinstance(body['session_token'], str) or not isinstance(body['question_id'], str)):
        raise NativeLessonError('invalid_input')
    try:
        sealed = _signer().loads(body['session_token'], max_age=COURSE_SESSION_SECONDS)
    except (BadSignature, SignatureExpired):
        raise NativeLessonError('lesson_changed', 409) from None
    if not isinstance(sealed, dict) or sealed.get('user') != current_user.id or sealed.get('lesson') != lesson_id:
        raise NativeLessonError('access_denied', 403)
    if sealed.get('web_round'):
        raise NativeLessonError('lesson_changed', 409)
    web_course = sealed.get('web_course') is True
    if web_course and not allow_web_course:
        raise NativeLessonError('access_denied', 403)
    lesson, progress = _lesson_and_progress(lesson_id)
    if not web_course:
        _guard_plan(lesson_id)
    content = _content(lesson)
    from app.curriculum.dispute_credit import course_revision_matches

    revision = _digest(content)
    revision_matches = (sealed.get('revision') == revision if strict_dispute_revision
                        else course_revision_matches(sealed, lesson, revision))
    if (not _session_type_matches(sealed, lesson) or not revision_matches
            or sealed.get('projection_version') != NATIVE_PROJECTION_VERSION):
        raise NativeLessonError('lesson_changed', 409)
    if sealed.get('version') != _version(progress):
        error = 'dispute_session_closed' if strict_dispute_revision else 'lesson_changed'
        raise NativeLessonError(error, 409)
    if lesson_types is not None and lesson.type not in lesson_types:
        raise NativeLessonError('not_found', 404)
    questions = project_questions(lesson)
    from app.curriculum.constants import is_objective_practice
    if not is_objective_practice(lesson):
        raise NativeLessonError('not_found', 404)
    correction = None
    if sealed.get('quiz_phase') == 'correction':
        from app.api.quiz_corrections import check_correction
        correction = check_correction(lesson, progress, sealed)
        if body['question_id'] not in correction['pending_ids']:
            raise NativeLessonError('invalid_input')
    level = body.get('help_level', 0)
    if (type(level) is not int or not 0 <= level <= 3
            or ('help_level' in body and not correction)):
        raise NativeLessonError('invalid_input')
    index = next((i for i, q in enumerate(questions) if q['id'] == body['question_id']), None)
    if index is None:
        raise NativeLessonError('invalid_input')
    row, question = rows_for(lesson)[index], questions[index]
    from app.api.native_content import check_course_answer
    feedback = check_course_answer(lesson, question, body['answer'])
    if correction:
        from app.api.quiz_corrections import correction_help
        feedback['correction_help'] = correction_help(row, question, body['answer'], feedback, level)
    return lesson, question, body['answer'], feedback, sealed


def _display_answer(question, value):
    text = str(value) if not isinstance(value, list) else ' / '.join(map(str, value))
    return next((o['label'] for o in question['options'] if o['value'] == text.lower()), plain(text))


def _award_theory_xp(lesson):
    from app.utils.db import db
    try:
        from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_linear_perfect_day
        if maybe_award_curriculum_xp(current_user.id, lesson, db_session=db, score=None) is not None:
            maybe_award_linear_perfect_day(current_user.id, db_session=db)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.warning('Native theory XP award failed user=%s lesson=%s', current_user.id, lesson.id, exc_info=True)


@api_native_lessons.route('/lessons/<int:lesson_id>/submit', methods=['POST'])
@csrf.exempt
@api_bearer_required
@limiter.limit('30 per minute', key_func=get_authenticated_user_key)
def submit_native_lesson(lesson_id):
    return course_submission(lesson_id)


def course_submission(lesson_id: int, *, allow_web_course: bool = False) -> Response | tuple[Response, int]:
    from app.api.native_content import NATIVE_PROJECTION_VERSION
    from app.auth.models import User
    from app.curriculum.constants import get_lesson_passing_score
    from app.curriculum.grading import process_grammar_submission, process_quiz_submission
    from app.curriculum.services.progress_service import ProgressService
    from app.utils.db import db
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'session_token', 'answers'} or not isinstance(data['session_token'], str):
        raise NativeLessonError('invalid_input')
    expired = False
    try:
        sealed = _signer().loads(data['session_token'], max_age=COURSE_SESSION_SECONDS)
    except SignatureExpired:
        # Expiry still forbids grading. A verified old nonce may only read its
        # committed receipt, after the same account and lesson access checks.
        try:
            sealed = _signer().loads(data['session_token'])
        except BadSignature:
            raise NativeLessonError('lesson_changed', 409) from None
        expired = True
    except BadSignature:
        raise NativeLessonError('lesson_changed', 409)
    if not isinstance(sealed, dict) or sealed.get('user') != current_user.id or sealed.get('lesson') != lesson_id:
        raise NativeLessonError('access_denied', 403)
    if sealed.get('web_round'):
        raise NativeLessonError('lesson_changed', 409)
    web_course = sealed.get('web_course') is True
    if web_course and not allow_web_course:
        raise NativeLessonError('access_denied', 403)
    if expired and (not isinstance(sealed.get('nonce'), str) or not sealed['nonce'].strip()):
        raise NativeLessonError('lesson_changed', 409)
    plan_error = None
    plan_kind = None
    if not expired and not web_course:
        try:
            plan_kind = _guard_plan(lesson_id)
        except NativeLessonError as error:
            plan_error = error
    # Serialize native submissions for this account. ProgressService commits the
    # response marker with the actual progress, before releasing this row lock.
    # A waiting duplicate then reads that marker instead of grading again.
    try:
        db.session.query(User.id).filter(User.id == current_user.id).with_for_update().one()
        lesson, progress = _lesson_and_progress(lesson_id)
        lesson._native_challenge = plan_kind == "challenge"
        saved = (progress.data or {}).get('_native_submission') if progress and isinstance(progress.data, dict) else None
        if isinstance(saved, dict) and saved.get('nonce') == sealed.get('nonce'):
            return jsonify(saved['response'])
        correction_saved = (progress.data or {}).get('quiz_correction') if progress and isinstance(progress.data, dict) else None
        receipt = correction_saved.get('receipt') if isinstance(correction_saved, dict) else None
        if isinstance(receipt, dict) and receipt.get('nonce') == sealed.get('nonce'):
            return jsonify(receipt['response'])
        if expired:
            raise NativeLessonError('lesson_changed', 409)
        if sealed.get('projection_version') != NATIVE_PROJECTION_VERSION:
            raise NativeLessonError('lesson_changed', 409)
        from app.curriculum.dispute_credit import course_revision_matches, submitted_mistakes

        revision = _digest(_content(lesson))
        if (not _session_type_matches(sealed, lesson)
                or not course_revision_matches(sealed, lesson, revision) or sealed.get('version') != _version(progress)):
            raise NativeLessonError('lesson_changed', 409)
        sealed['revision'] = revision
        if plan_error is not None:
            raise plan_error
        questions = project_questions(lesson)
        if sealed.get('quiz_phase') == 'correction':
            from app.api.quiz_corrections import check_correction
            correction = check_correction(lesson, progress, sealed)
            questions = [q for q in questions if q['id'] in correction['pending_ids']]
        answers = data['answers']
        if not isinstance(answers, dict) or set(answers) != {q['id'] for q in questions}:
            raise NativeLessonError('invalid_input')
        for q in questions:
            answer = answers[q['id']]
            if not isinstance(answer, str) or not answer.strip() or len(answer) > (50000 if q.get('input') in ('essay','long_text') else 20000 if q.get('input') in ('match','order','translation_review') else 2000):
                raise NativeLessonError('invalid_input')
            if q['options'] and q.get('input') in (None,'choice') and answer not in {o['value'] for o in q['options']}:
                raise NativeLessonError('invalid_input')
        from app.api.native_content import is_extended, grade as grade_extended, persist as persist_extended
        if sealed.get('quiz_phase') == 'correction':
            from app.api.quiz_corrections import submit_correction
            return jsonify(submit_correction(lesson, progress, sealed, questions, answers))
        from app.api.quiz_corrections import FLOW
        if is_extended(lesson) or sealed.get('quiz_flow') == FLOW:
            passing = get_lesson_passing_score(lesson)
            grade, feedback, assessment, completed = grade_extended(lesson, questions, answers, passing)
            return jsonify(persist_extended(lesson, progress, grade, feedback, assessment, completed, sealed, passing, answers=answers, questions=questions))
        content = _content(lesson)
        rows = content.get('exercises' if lesson.type == 'grammar' else 'questions', [])
        if not questions:
            response = {'success': True, 'lesson_id': lesson_id, 'score': None, 'passed': True,
                        'correct_count': 0, 'total_count': 0, 'feedback': []}
            saved_data = {'_native_submission': {'nonce': sealed['nonce'], 'response': response}}
            ProgressService.create_or_update_progress(current_user.id, lesson_id, status='completed', score=None, data=saved_data)
            _award_theory_xp(lesson)
        else:
            grader = process_grammar_submission if lesson.type == 'grammar' else process_quiz_submission
            grade = grader(rows, answers)
            if progress is None:
                # Preserve server-issued opening time for canonical attempt analytics.
                from app.curriculum.models import LessonProgress
                db.session.add(LessonProgress(user_id=current_user.id, lesson_id=lesson_id,
                    status='in_progress', started_at=datetime.fromisoformat(sealed['started_at'])))
            passing = get_lesson_passing_score(lesson)
            feedback = []
            for q, row in zip(questions, rows):
                checked = grade['feedback'][q['id']]
                feedback.append({'id': q['id'], 'prompt': q['prompt'], 'correct': checked['status'] == 'correct',
                                 'answer': _display_answer(q, answers[q['id']]),
                                 'expected': plain(checked.get('correct_answer', '')) if lesson.type=='quiz' and q['options'] and q['options'][0]['value'] not in ('true','false') else _display_answer(q, checked.get('correct_answer', '')),
                                 'explanation': plain(checked.get('explanation') or row.get('explanation'))})
            response = {'success': True, 'lesson_id': lesson_id, 'score': grade['score'],
                        'passed': grade['score'] >= passing, 'correct_count': grade['correct_answers'],
                        'total_count': grade['total_questions'], 'feedback': feedback}
            grade['_native_submission'] = {'nonce': sealed['nonce'], 'response': response}
            ProgressService.update_progress_with_grading(
                current_user.id, lesson, grade, passing_score=passing, submission_nonce=sealed['nonce'],
                submission_mistakes=submitted_mistakes(questions, feedback, answers),
            )
        return jsonify(response)
    except NativeLessonError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        logger.exception('Native lesson grading failed user=%s lesson=%s', current_user.id, lesson_id)
        return jsonify(success=False, error='grading_failed'), 500


@api_native_lessons.route('/lessons/<int:lesson_id>/review', methods=['POST'])
@csrf.exempt
@api_bearer_required
@limiter.limit('60 per minute', key_func=get_authenticated_user_key)
def review_native_translation(lesson_id):
    data = request.get_json(silent=True)
    if not isinstance(data,dict) or not {'session_token','index','answer'} <= set(data) or set(data)-{'session_token','index','answer','review_token','confirm'}:
        raise NativeLessonError('invalid_input')
    try: sealed = _signer().loads(data['session_token'],max_age=COURSE_SESSION_SECONDS)
    except (BadSignature,SignatureExpired,TypeError): raise NativeLessonError('lesson_changed',409)
    if sealed.get('user') != current_user.id or sealed.get('lesson') != lesson_id:raise NativeLessonError('access_denied',403)
    lesson, _ = _lesson_and_progress(lesson_id)
    _guard_plan(lesson_id)
    if not _session_type_matches(sealed, lesson) or sealed.get('revision') != _digest(_content(lesson)):raise NativeLessonError('lesson_changed',409)
    from app.curriculum.translation_review import review_item
    result = review_item(lesson,current_user.id,data['index'],data['answer'],data.get('review_token'),data.get('confirm') is True)
    return jsonify(result), 200 if result.get('success') else 400
