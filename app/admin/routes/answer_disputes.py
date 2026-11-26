"""Private editorial queue for disputed course and Grammar Lab answers."""
# ruff: noqa: RUF001 -- moderation forms and messages are in Russian.
from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Query

from app.admin.services.guided_disputes import guided_topic_for_dispute
from app.admin.utils.decorators import content_editor_required
from app.admin.utils.request_validators import escape_like
from app.auth.models import User
from app.curriculum.answer_review_ai import LABELS
from app.curriculum.answer_disputes import (
    AnswerDispute,
    AnswerDisputeReport,
    NativeCourseDisputeReceipt,
    course_dispute_channels,
    course_report_channel_labels,
)
from app.curriculum.answer_review_edits import answer_aliases
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.telegram.models import TelegramUser
from app.utils.db import db

answer_disputes_bp = Blueprint('answer_disputes_admin', __name__)
_QUEUES = {
    'work': ('pending', 'ready', 'notified', 'manual'),
    'revise': ('revise',),
    'history': ('applied', 'dismissed', 'closed', 'stale'),
}
_STATUS = {
    'pending': 'Ожидает проверки', 'ready': 'Ожидает решения', 'notified': 'Ожидает решения',
    'manual': 'Ручная проверка', 'revise': 'На доработке', 'applied': 'Исправлено',
    'dismissed': 'Отклонено', 'closed': 'Закрыто после проверки', 'stale': 'Версия задания изменилась',
}
_PER_PAGE = 25
_REPORTS_PER_PAGE = 50
_PREVIEW_TTL = 1800
_STRONG_REASON = re.compile(r'(?<!\*)\*\*(?![\s*])((?:[^*\r\n]|\*(?!\*))+?)(?<![\s*])\*\*(?!\*)')


@answer_disputes_bp.after_request
def private_response(response: Response) -> Response:
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _joined_cases() -> Query:
    return (
        db.session.query(AnswerDispute, Lessons.title.label('lesson_title'), Module.title.label('module_title'),
                         Module.number.label('module_number'), CEFRLevel.code.label('course_level'),
                         GrammarTopic.level.label('lab_level'), GrammarTopic.title_ru.label('topic_ru'),
                         GrammarTopic.title.label('topic_en'), GrammarTopic.id.label('topic_id'))
        .outerjoin(Lessons, Lessons.id == AnswerDispute.lesson_id)
        .outerjoin(Module, Module.id == Lessons.module_id)
        .outerjoin(CEFRLevel, CEFRLevel.id == Module.level_id)
        .outerjoin(GrammarExercise, GrammarExercise.id == AnswerDispute.grammar_exercise_id)
        .outerjoin(GrammarTopic, GrammarTopic.id == GrammarExercise.topic_id)
    )


def _display(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _reason_parts(value: object) -> list[tuple[str, bool]]:
    """Keep legacy emphasis markers separate from text escaped by the template."""
    if value is None:
        return []
    text = str(value)
    parts = []
    end = 0
    for match in _STRONG_REASON.finditer(text):
        if match.start() > end:
            parts.append((text[end:match.start()], False))
        parts.append((match[1], True))
        end = match.end()
    if end < len(text):
        parts.append((text[end:], False))
    return parts


def _case_data(row: Any, *, is_admin: bool) -> dict:
    case = row[0]
    evidence = case.evidence or {}
    raw, question, review = evidence.get('row') or {}, evidence.get('question') or {}, case.review or {}
    lab = case.grammar_exercise_id is not None
    if lab:
        title = f'Grammar Lab · {row.lab_level} · {row.topic_ru or row.topic_en} · Упражнение №{case.grammar_exercise_id}'
        source_url = url_for('grammar_lab_admin.edit_exercise', exercise_id=case.grammar_exercise_id) if is_admin else ''
    else:
        title = (f'Курс · {row.course_level} · Модуль {row.module_number} «{row.module_title}»'
                 f' · Урок №{case.lesson_id} «{row.lesson_title}» · Вопрос {int(case.question_id) + 1}')
        source_url = url_for('curriculum_admin.view_lesson', lesson_id=case.lesson_id) if is_admin else ''
    prompt = (question.get('prompt') or raw.get('question') or raw.get('statement') or raw.get('sentence')
              or raw.get('original') or '')
    instructions = [question.get('lesson_instruction'), question.get('instruction') or raw.get('instruction'),
                    question.get('context') or raw.get('context')]
    options = raw.get('options') or []
    key = next((raw[k] for k in ('correct_answer', 'correct', 'answer', 'correct_sentence', 'correct_index', 'answers')
                if raw.get(k) is not None), None)
    answer = evidence.get('answer')
    if options:
        if type(key) is int and 0 <= key < len(options):
            key = options[key]
        if str(answer).isascii() and str(answer).isdigit() and len(str(answer)) <= 4 and int(answer) < len(options):
            answer = options[int(answer)]
    if raw.get('words') and isinstance(answer, list) and all(
        type(i) is int and 0 <= i < len(raw['words']) for i in answer
    ):
        answer = ' '.join(raw['words'][i] for i in answer)
    editor_action = review.get('editor_action')
    aliases = answer_aliases(raw)
    outcome_action, editor_answer, resulting_key = editor_action, None, None
    if case.status == 'applied':
        outcome_action = editor_action or ('add' if review.get('label') == 'valid_variant' else 'replace')
        editor_answer = review.get('shown_answer', answer)
        if outcome_action == 'add':
            editor_answer = review.get('editor_answer', editor_answer)
        resulting_key = review.get('resulting_key', key if outcome_action == 'add' else editor_answer)
    elif case.status in ('dismissed', 'revise'):
        outcome_action = 'reject' if case.status == 'dismissed' else 'revise'
    ai_label = review.get('model_label') or review.get('label')
    if ai_label not in LABELS or (editor_action and not review.get('model') and not review.get('reason')):
        ai_label = None
    return dict(id=case.id, status=case.status, status_label=_STATUS.get(case.status, case.status),
                source='lab' if lab else 'course', source_title=title, source_url=source_url,
                question=_display(prompt), instruction='\n'.join(dict.fromkeys(_display(s) for s in instructions if s)),
                words=raw.get('words') or [], options=[_display(o) for o in options], pairs=raw.get('pairs') or [],
                answer=_display(answer if editor_action in ('add', 'replace') else review.get('shown_answer', answer)),
                key=_display(review.get('shown_key', key)), aliases=aliases,
                ai_label=ai_label, ai_reason=review.get('reason') if ai_label else None, created_at=case.created_at,
                processing_note=None if ai_label else review.get('reason'),
                editor_action=outcome_action, editor_answer=_display(editor_answer), resulting_key=_display(resulting_key),
                decided_at=review.get('decided_at'), decided_by=None)


def _next_case_id(case_id: int) -> int | None:
    query = db.session.query(AnswerDispute.id).filter(AnswerDispute.status.in_(_QUEUES['work']),
                                                      AnswerDispute.id != case_id)
    row = query.order_by(AnswerDispute.created_at.asc(), AnswerDispute.id.asc()).first()
    return row.id if row else None


@answer_disputes_bp.get('/answer-disputes')
@content_editor_required
def index() -> str:
    queue = request.args.get('queue', 'work')
    if queue != 'all' and queue not in _QUEUES:
        queue = 'work'
    source = request.args.get('source', '')
    if source not in ('lab', 'course'):
        source = ''
    q = request.args.get('q', '').strip()[:200]
    sort = 'oldest' if request.args.get('sort') == 'oldest' else 'newest'
    query = _joined_cases()
    if source:
        column = AnswerDispute.grammar_exercise_id if source == 'lab' else AnswerDispute.lesson_id
        query = query.filter(column.isnot(None))
    if q:
        needle = f'%{escape_like(q)}%'
        json_question = AnswerDispute.evidence['question']['prompt'].as_string()
        json_instruction = AnswerDispute.evidence['question']['instruction'].as_string()
        json_answer = AnswerDispute.evidence['answer'].as_string()
        terms = [c.ilike(needle, escape='\\') for c in (
            Lessons.title, Module.title, GrammarTopic.title_ru, GrammarTopic.title, json_question,
            json_instruction, json_answer,
        )]
        number = q.removeprefix('#')
        if number.isascii() and number.isdigit() and len(number) <= 10 and int(number) <= 2**31 - 1:
            terms.extend(c == int(number) for c in (AnswerDispute.id, AnswerDispute.grammar_exercise_id,
                                                    AnswerDispute.lesson_id))
        query = query.filter(or_(*terms))
    counts = dict(query.with_entities(AnswerDispute.status, func.count(AnswerDispute.id))
                  .group_by(AnswerDispute.status).all())
    queue_counts = {name: sum(counts.get(status, 0) for status in statuses) for name, statuses in _QUEUES.items()}
    queue_counts['all'] = sum(counts.values())
    total = queue_counts[queue]
    pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    page = min(pages, max(1, request.args.get('page', default=1, type=int)))
    if queue != 'all':
        query = query.filter(AnswerDispute.status.in_(_QUEUES[queue]))
    order = AnswerDispute.id.asc() if sort == 'oldest' else AnswerDispute.id.desc()
    date = AnswerDispute.created_at.asc() if sort == 'oldest' else AnswerDispute.created_at.desc()
    rows = query.order_by(date, order).limit(_PER_PAGE).offset((page - 1) * _PER_PAGE).all()
    ids = [row[0].id for row in rows]
    reporters = dict(db.session.query(AnswerDisputeReport.dispute_id, func.count(AnswerDisputeReport.id))
                     .filter(AnswerDisputeReport.dispute_id.in_(ids)).group_by(AnswerDisputeReport.dispute_id)) if ids else {}
    is_admin = bool(current_user.is_admin)
    cases = [{**_case_data(row, is_admin=is_admin), 'reporter_count': reporters.get(row[0].id, 0)} for row in rows]
    return render_template('admin/answer_disputes/index.html', cases=cases, queue_counts=queue_counts, queue=queue,
                           source=source, q=q, sort=sort, total=total, page=page, pages=pages, can_see_reporters=is_admin)


def _decision_author(review: dict) -> str | None:
    if user_id := review.get('decided_by_user_id'):
        user = db.session.get(User, user_id)
        return f'{user.username} · ID {user_id}' if user else f'Аккаунт №{user_id}'
    if tg_id := review.get('decided_by'):
        joined = db.session.query(User.username).join(TelegramUser, TelegramUser.user_id == User.id)
        actor = joined.filter(TelegramUser.telegram_id == tg_id).first()
        return f'{actor.username} · Telegram' if actor else 'Администратор в Telegram'
    return None


def _detail(case_id: int, *, error: str | None = None, preview: dict | None = None, preview_token: str | None = None,
            action: str = '', answer: str | None = None) -> str:
    from app.curriculum.answer_review_editor import EDITABLE, editor_version

    row = _joined_cases().filter(AnswerDispute.id == case_id).first_or_404()
    dispute = row[0]
    is_admin = bool(current_user.is_admin)
    case = _case_data(row, is_admin=is_admin)
    guided_topic = guided_topic_for_dispute(dispute)
    case['guided_topic_id'] = guided_topic.id if guided_topic else None
    case['ai_reason_parts'] = _reason_parts(case['ai_reason'])
    case['processing_note_parts'] = _reason_parts(case['processing_note'])
    query = AnswerDisputeReport.query.filter_by(dispute_id=case_id)
    total = query.count()
    pages = max(1, (total + _REPORTS_PER_PAGE - 1) // _REPORTS_PER_PAGE)
    page = min(pages, max(1, request.args.get('reporters_page', default=1, type=int)))
    native_reported = exists().where(NativeCourseDisputeReceipt.report_id == AnswerDisputeReport.id)
    channels = course_dispute_channels(db.session, case_id) if dispute.lesson_id is not None else []
    reporters = []
    if is_admin:
        people = query.join(User, User.id == AnswerDisputeReport.user_id).add_columns(
            User.username, native_reported.label('native_reported'),
        )
        reporters = [dict(user_id=r.user_id, username=name, created_at=r.created_at, credited_at=r.credited_at,
                          thanked_at=r.thanked_at, profile_url=url_for('user_admin.user_detail', user_id=r.user_id),
                          channels=course_report_channel_labels(r.course_web_reported, native))
                     for r, name, native in people.order_by(AnswerDisputeReport.id).limit(_REPORTS_PER_PAGE)
                     .offset((page - 1) * _REPORTS_PER_PAGE)]
    version = editor_version(dispute)
    editable = dispute.status in EDITABLE
    case.update(reporters=reporters, reporter_count=total, channels=channels, version=version, editable=editable,
                decided_by=_decision_author(dispute.review or {}) if is_admin else None)
    return render_template('admin/answer_disputes/detail.html', case=case, reporters=reporters,
                           reporters_page=page, reporters_pages=pages, version=version, can_see_reporters=is_admin,
                           next_case_id=_next_case_id(case_id), editable=editable, preview=preview,
                           preview_token=preview_token, error=error, action=action, answer=answer if answer is not None
                           else case['answer'])


@answer_disputes_bp.get('/answer-disputes/<int:case_id>')
@content_editor_required
def detail(case_id: int) -> str:
    return _detail(case_id)


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt='answer-dispute-editor-preview-v1')


def _preview_digest(value: dict) -> str:
    material = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return sha256(material.encode()).hexdigest()


@answer_disputes_bp.post('/answer-disputes/<int:case_id>/preview')
@content_editor_required
def preview(case_id: int) -> tuple[str, int] | str:
    from app.curriculum.answer_review_editor import editor_preview, editor_version

    case = AnswerDispute.query.get_or_404(case_id)
    version = request.form.get('version', '')
    action = request.form.get('action', '')
    answer = request.form.get('answer', '')
    if version != editor_version(case):
        return _detail(case_id, error='За это время спор изменился. Проверьте его ещё раз.'), 409
    if action not in ('add', 'replace', 'reject', 'revise') or len(answer) > 2000:
        return _detail(case_id, error='Проверьте действие и длину ответа.'), 400
    try:
        change = editor_preview(case, action, answer)
    except ValueError as exc:
        return _detail(case_id, error=str(exc), action=action, answer=answer), 400
    token = _signer().dumps([current_user.id, case.id, version, action, answer, _preview_digest(change)])
    return _detail(case_id, preview=change, preview_token=token, action=action, answer=answer)


@answer_disputes_bp.post('/answer-disputes/<int:case_id>/decide')
@content_editor_required
def decide(case_id: int) -> Response | tuple[str, int]:
    from app.curriculum.answer_review_editor import editor_decide, editor_preview, editor_version

    case = AnswerDispute.query.get_or_404(case_id)
    token = request.form.get('preview_token', '')
    if len(token) > 16000:
        abort(400)
    try:
        actor, target, version, action, answer, digest = _signer().loads(token, max_age=_PREVIEW_TTL)
        if actor != current_user.id or target != case.id:
            raise ValueError('Предпросмотр принадлежит другому администратору или спору.')
        if version != editor_version(case):
            raise ValueError('За это время спор изменился. Проверьте его ещё раз.')
        if digest != _preview_digest(editor_preview(case, action, answer)):
            raise ValueError('Содержимое задания изменилось. Откройте новый предпросмотр.')
        result = editor_decide(case.id, current_user.id, version, action, answer)
    except BadData:
        return _detail(case_id, error='Предпросмотр недействителен или истёк. Подготовьте его ещё раз.'), 409
    except ValueError as exc:
        db.session.rollback()
        return _detail(case_id, error=str(exc)), 409
    flash(result, 'success')
    if request.form.get('next') == '1':
        next_id = _next_case_id(case.id)
        return redirect(url_for('.detail', case_id=next_id) if next_id else url_for('.index'), code=303)
    return redirect(url_for('.detail', case_id=case.id), code=303)
