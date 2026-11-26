"""Process distinct answer disputes and apply edits confirmed by an authorized content editor."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from flask import Flask, current_app

from app.api.native_content import content_for
from app.api.native_lessons import NativeLessonError, _digest, project_questions
from app.auth.models import User
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import (
    AnswerDispute,
    AnswerDisputeReport,
    course_dispute_channels,
    current_dispute_row,
)
from app.curriculum.answer_review_edits import replace_text_key
from app.curriculum.models import Lessons
from app.grammar_lab import answer_review as lab
from app.grammar_lab.guided_learning import check_answer
from app.grammar_lab.models import GrammarExercise
from app.telegram.models import TelegramUser
from app.utils.db import db

log = logging.getLogger(__name__)
TEXT_TYPES = {'translation', 'transformation', 'error_correction', 'fill_in_blank', 'fill_blank', 'fill-in-blank', 'fill-blank'}
KEYS = ('correct_answer', 'correct', 'answer', 'correct_sentence')
ROW_FIELDS = {'instruction', 'question', 'prompt', 'text', 'sentence', 'question_ru', 'translation',
              'type', 'context', 'constraints', 'required_words', 'options', 'pairs', 'words', 'tokens',
              'explanation', 'acceptable_answers', 'alternatives',
              'alternative_answers', 'correct_index', 'answers', *KEYS}
LAB_ROW_FIELDS = ROW_FIELDS | {'original', 'statement', 'key_grammar', 'full_correct', 'theory_help',
                               'source_lang', 'target_lang'}


def _question(lesson: Lessons, case: AnswerDispute) -> dict:
    return next(q for q in project_questions(lesson) if q['id'] == case.question_id)


def _choice_key_edit(row: dict, question: dict, answer: str, *, grammar: bool) -> dict | None:
    """Correct a single authored key only when the real grader switches precisely those two choices."""
    options = row.get('options')
    fields = [k for k in (*KEYS, 'correct_index', 'answers') if k in row]
    if (row.get('type', 'multiple_choice') != 'multiple_choice' or len(fields) != 1
            or not isinstance(options, list) or not 2 <= len(options) <= 12
            or not all(isinstance(option, str) for option in options) or len(set(options)) != len(options)):
        return None
    ids = [o['value'] for o in question.get('options', [])]
    if set(ids) != {str(index) for index in range(len(options))} or answer not in ids:
        return None
    field = fields[0]
    original = row[field]
    if type(original) is int:
        value = int(answer)
    elif isinstance(original, str) and field != 'correct_index' and original in options:
        value = options[int(answer)]
    elif isinstance(original, str) and original in ids:
        value = answer
    else:
        return None
    before = [i for i in ids if check_answer(row, question, i, grammar=grammar)['correct']]
    updated = {**row, field: value}
    after = [i for i in ids if check_answer(updated, question, i, grammar=grammar)['correct']]
    return {field: value} if len(before) == 1 and answer not in before and after == [answer] else None


def proposed_edit(lesson: Lessons, row: dict, question: dict, answer: str, label: str) -> dict | None:
    """Construct the limited edit ourselves, replay the real grader before proposing it."""
    if (label not in {'valid_variant', 'wrong_key'}
            or '<' in answer or '>' in answer or not answer.isprintable()
            or row.get('guided_key') or content_for(lesson).get('learning_steps')):
        return None
    grammar = lesson.type == 'grammar'
    if question.get('input') == 'choice' and label == 'wrong_key':
        return _choice_key_edit(row, question, answer, grammar=grammar)
    if (row.get('type') not in TEXT_TYPES or question.get('input') not in ('text', 'short_text', None)
            or question.get('options')):
        return None
    keys = [key for key in KEYS if key in row]
    if len(keys) != 1 or not isinstance(row[keys[0]], str):
        return None
    key = keys[0]
    original = row[key]
    if not original.strip() or len(original) > 500:
        return None
    if label == 'valid_variant' and check_answer(row, question, answer, grammar=grammar)['correct']:
        return None
    if label == 'valid_variant':
        aliases = row.get('alternative_answers', [])
        if not isinstance(aliases, list) or answer in aliases:
            return None
        patch = {'alternative_answers': [*aliases, answer]}
    else:
        patch = replace_text_key(row, key, answer)
    updated = {**row, **patch}
    if not check_answer(updated, question, answer, grammar=grammar)['correct']:
        return None
    if check_answer(updated, question, original, grammar=grammar)['correct'] != (label == 'valid_variant'):
        return None
    return patch


def _current_lab_exercise(case: AnswerDispute, *, lock: bool = False) -> GrammarExercise | None:
    query = GrammarExercise.query.filter_by(id=case.grammar_exercise_id)
    if lock:
        query = query.populate_existing().with_for_update()
    exercise = query.first()
    if (not exercise or not isinstance(exercise.content, dict) or exercise.content.get('guided_retired')
            or case.grader_version != lab.LAB_GRADER_VERSION or lab.lab_revision(exercise) != case.question_revision):
        return None
    return exercise


def _notify_all() -> bool:
    return current_app.config.get('ANSWER_REVIEW_NOTIFY_ALL', True)


def _finish_without_verdict(case: AnswerDispute, status: str, reason: str) -> None:
    case.review = {'label': status, 'reason': reason}
    case.status = status
    if _notify_all():
        # The details can be sensitive or obsolete. Send only a reference to the case.
        case.review = {**case.review, 'status_after_notification': status}
        case.status = 'ready'


def review_case(case: AnswerDispute, *, key: str, model: str) -> None:
    answer = case.evidence['answer']
    exercise = None
    if case.grammar_exercise_id is not None:
        exercise = _current_lab_exercise(case)
        if exercise is None:
            _finish_without_verdict(case, 'stale', 'Версия упражнения изменилась после отправки.')
            return
        row = lab.effective_content(exercise)
        result = lab.grade_row(exercise, row, answer)
        if result.get('error'):
            _finish_without_verdict(case, 'manual', 'Формат ответа требует ручного разбора.')
            return
        correct = result['is_correct']
        shown, expected = lab.display_review_answers(exercise, row, result)
        model_row = {k: v for k, v in row.items() if k in LAB_ROW_FIELDS}
        model_row['type'] = exercise.exercise_type
    else:
        lesson = db.session.get(Lessons, case.lesson_id)
        row = current_dispute_row(case, lesson) if lesson else None
        if row is None:
            _finish_without_verdict(case, 'stale', 'Версия задания изменилась после отправки.')
            return
        question = _question(lesson, case)
        feedback = check_answer(row, question, answer, grammar=lesson.type == 'grammar')
        correct, shown, expected = feedback['correct'], feedback['answer'], feedback['expected']
        model_row = {k: v for k, v in row.items() if k in ROW_FIELDS}
    if correct:
        _finish_without_verdict(case, 'stale', 'Актуальная проверка уже принимает этот ответ.')
        return
    evidence = {'row': model_row,
                'question': case.evidence['question'], 'expected': expected, 'submitted_answer': shown}
    encoded = json.dumps(evidence, ensure_ascii=False)
    if len(encoded) > 10000 or len(str(shown)) > 500 or ai.CONTACT.search(encoded):
        _finish_without_verdict(case, 'manual', 'Требуется локальный разбор содержимого.')
        return
    review = ai.classify(evidence, key=key, model=model)
    if exercise is not None:
        review['topic_id'] = exercise.topic_id
        review['patch'] = lab.proposed_lab_edit(exercise, row, answer, review['label'])
    else:
        review['patch'] = proposed_edit(lesson, row, question, answer, review['label'])
    review['shown_answer'] = shown
    review['shown_key'] = expected
    case.review = review
    negative = review['label'] in ('learner_error', 'insufficient_context')
    case.status = 'closed' if negative and not _notify_all() else 'ready'


def _card_source(case: AnswerDispute) -> str:
    origin = (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
    if case.grammar_exercise_id is not None:
        exercise = db.session.get(GrammarExercise, case.grammar_exercise_id)
        topic = exercise.topic if exercise else None
        heading = f'Сайт · Grammar Lab · {topic.level} · {topic.title_ru}' if topic else 'Сайт · Grammar Lab'
        label = f'Тема {topic.id} · ' if topic else ''
        source = f'{heading}\n{label}Упражнение №{case.grammar_exercise_id}'
        path = f'/admin/grammar-lab/exercises/{case.grammar_exercise_id}/edit'
    else:
        lesson = db.session.get(Lessons, case.lesson_id)
        heading = ' · '.join(('Курс', *course_dispute_channels(db.session, case.id)))  # noqa: RUF001 -- Russian card title.
        if lesson:
            heading += f' · {lesson.module.level.code} · Модуль {lesson.module.number} «{lesson.module.title}»'
        title = f' «{lesson.title}»' if lesson else ''
        source = f'{heading}\nУрок {case.lesson_id}{title}, вопрос {int(case.question_id) + 1}'
        path = f'/curriculum/admin/lesson/{case.lesson_id}/view'

    reporters = (db.session.query(User.id, User.username).join(AnswerDisputeReport, AnswerDisputeReport.user_id == User.id)
                 .filter(AnswerDisputeReport.dispute_id == case.id).order_by(AnswerDisputeReport.id))
    names = []
    visible = reporters.limit(3).all()
    for user_id, username in visible:
        # Only the account's display login belongs here. Some accounts use an email as their login.
        name = username if username and username.isprintable() and not ai.CONTACT.search(username) else ''
        names.append(f'{name} (ID {user_id})' if name else f'ID {user_id}')
    people = ', '.join(names)
    if len(names) == 3:
        extra = reporters.order_by(None).count() - len(names)
        if extra:
            people += f' и ещё {extra}'
    if len(visible) == 1:
        attribution = f'От ученика: {people}\n{origin}/admin/users/{visible[0].id}'
    elif visible:
        attribution = f'От учеников: {people}'
    else:
        attribution = 'Автор обращения не сохранён'
    return f'{source}\n{origin}{path}\n{attribution}'


def dispute_admin_url(case_id: int) -> str:
    origin = (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
    return f'{origin}/admin/answer-disputes/{case_id}'


def _telegram_card(case: AnswerDispute) -> tuple[str, dict | None]:
    review = case.review
    source = _card_source(case)
    if review.get('status_after_notification'):
        return f'Спор {case.id}\n{source}\n{review["reason"]}\n{dispute_admin_url(case.id)}', None

    row = case.evidence['row']
    instructions = [case.evidence['question'].get('lesson_instruction'), row.get('instruction'),
                    case.evidence['question'].get('instruction'), case.evidence['question'].get('prompt'),
                    row.get('statement'), row.get('original'), row.get('sentence'),
                    case.evidence['question'].get('context'), row.get('context'), row.get('constraints'), row.get('required_words')]
    words = row.get('words')
    if isinstance(words, list) and words and all(isinstance(word, str) for word in words):
        instructions.append('Слова задания: ' + ' · '.join(words))
    question = '\n'.join(dict.fromkeys(str(s) for s in instructions if s))
    patch = review.get('patch')
    if patch:
        field, value = next(iter(patch.items()))
        if field in ('alternative_answers', 'alternatives'):
            change = 'Добавить допустимый ответ: ' + value[-1]
        else:
            change = f'Заменить ключ «{row.get(field)}» на «{value}»'
    else:
        change = 'Проверьте задание в админке.'
    keyboard = [[{'text': 'Открыть спор в админке', 'url': dispute_admin_url(case.id)}]]
    title = {'valid_variant': 'Возможен второй верный ответ', 'wrong_key': 'Возможная ошибка в ключе',
             'grader_issue': 'Возможная ошибка в проверке', 'learner_error': 'Модель считает ответ неверным',
             'insufficient_context': 'Модели не хватило контекста'}[review['label']]
    text = (f'{title} · спор {case.id}\n{source}\n'
            f'{question}\nОтвет ученика: {review["shown_answer"]}\n'
            f'Текущий ключ: {review["shown_key"]}\nРазбор: {review["reason"]}\n\n{change}')
    if len(text.encode('utf-16-le')) // 2 > 4096:
        return (f'Спор {case.id} ({source}) требует ручного разбора. '
                f'Полное условие в админке: {dispute_admin_url(case.id)}'), None
    return text, {'inline_keyboard': keyboard}


def _notify_admins(case: AnswerDispute, recipients: list[int], now: datetime) -> None:
    from app.telegram.bot import send_message

    text, keyboard = _telegram_card(case)
    delivered = set(case.review.get('notified_telegram_ids', []))
    for recipient in recipients:
        if recipient not in delivered and send_message(recipient, text, parse_mode=None, reply_markup=keyboard):
            delivered.add(recipient)
    case.review = {**case.review, 'notified_telegram_ids': sorted(delivered)}
    if delivered.issuperset(recipients):
        case.status = case.review.get('status_after_notification') or ('notified' if keyboard else 'manual')
    else:
        case.next_attempt_at = now + timedelta(minutes=10)


def apply_review_patch(case: AnswerDispute, source: Lessons | GrammarExercise, patch: dict) -> None:
    """Apply the verified patch to the locked material in the caller's transaction."""
    if isinstance(source, GrammarExercise):
        lab.apply_lab_patch(source, patch)
        revisions = {'updated_revision': lab.lab_revision(source)}
    else:
        content = content_for(source)
        previous = _digest(content)
        rows = content.get('questions') if source.type == 'quiz' else None
        rows = rows or content['exercises']
        rows[int(case.question_id)].update(patch)
        source.content = content
        revisions = {'previous_revision': previous, 'updated_revision': _digest(content)}
    case.review = {**(case.review or {}), **revisions}
    case.status = 'applied'


def commit_decision(case: AnswerDispute) -> None:
    from app.curriculum.dispute_credit import credit_approved_reports
    from app.curriculum.services.progress_service import _invalidate_user_progress_cache

    updated_learners = credit_approved_reports(case) if case.status == 'applied' else set()
    db.session.commit()
    for user_id in updated_learners:
        _invalidate_user_progress_cache(user_id)


def process_one() -> bool:
    from sqlalchemy import or_
    key, model = current_app.config.get('OPENAI_API_KEY'), current_app.config.get('OPENAI_MODEL')
    states = []
    recipients = []
    if key and model:
        states.append('pending')
    if current_app.config.get('TELEGRAM_BOT_TOKEN'):
        links = TelegramUser.active_admin_links().with_entities(TelegramUser.telegram_id)
        recipients = [link.telegram_id for link in links.order_by(TelegramUser.telegram_id)]
        if recipients:
            states.append('ready')
    if not states:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    case = (AnswerDispute.query.filter(AnswerDispute.status.in_(states),
                                       or_(AnswerDispute.next_attempt_at.is_(None), AnswerDispute.next_attempt_at <= now))
            .order_by(AnswerDispute.id).with_for_update(skip_locked=True).first())
    if not case:
        db.session.rollback()
        return False
    try:
        case.next_attempt_at = None
        if case.status == 'pending':
            review_case(case, key=key, model=model)
        else:
            _notify_admins(case, recipients, now)
    except ai.ReviewServiceError as exc:
        log.warning('Answer review %s deferred: %s', case.id, exc)
        case.next_attempt_at = now + timedelta(hours=1)
    except NativeLessonError:
        _finish_without_verdict(case, 'manual', 'Требуется разбор формата задания.')
    db.session.commit()
    return True


def process_answer_disputes(app: Flask) -> None:
    with app.app_context():
        for _ in range(5):
            if not process_one():
                break
