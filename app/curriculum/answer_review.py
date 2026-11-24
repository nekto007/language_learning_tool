"""Process distinct answer disputes and apply edits approved by a linked administrator."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from flask import Flask, current_app

from app.api.native_content import content_for
from app.api.native_lessons import NativeLessonError, project_questions
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute, current_dispute_row
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
    """Construct the limited edit ourselves, replay grading on a copy, keep all existing aliases."""
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
    if check_answer(row, question, answer, grammar=grammar)['correct']:
        return None
    if label == 'valid_variant':
        aliases = row.get('alternative_answers', [])
        if not isinstance(aliases, list) or answer in aliases:
            return None
        patch = {'alternative_answers': [*aliases, answer]}
    else:
        patch = {key: answer}
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


def review_case(case: AnswerDispute, *, key: str, model: str) -> None:
    answer = case.evidence['answer']
    exercise = None
    if case.grammar_exercise_id is not None:
        exercise = _current_lab_exercise(case)
        if exercise is None:
            case.status = 'stale'
            return
        row = lab.effective_content(exercise)
        result = lab.grade_row(exercise, row, answer)
        if result.get('error'):
            case.status = 'manual'
            return
        correct = result['is_correct']
        shown, expected = lab.display_review_answers(exercise, row, result)
        model_row = {k: v for k, v in row.items() if k in LAB_ROW_FIELDS}
        model_row['type'] = exercise.exercise_type
    else:
        lesson = db.session.get(Lessons, case.lesson_id)
        row = current_dispute_row(case, lesson) if lesson else None
        if row is None:
            case.status = 'stale'
            return
        question = _question(lesson, case)
        feedback = check_answer(row, question, answer, grammar=lesson.type == 'grammar')
        correct, shown, expected = feedback['correct'], feedback['answer'], feedback['expected']
        model_row = {k: v for k, v in row.items() if k in ROW_FIELDS}
    if correct:
        case.status = 'stale'
        return
    evidence = {'row': model_row,
                'question': case.evidence['question'], 'expected': expected, 'submitted_answer': shown}
    encoded = json.dumps(evidence, ensure_ascii=False)
    if len(encoded) > 10000 or len(str(shown)) > 500 or ai.CONTACT.search(encoded):
        case.review = {'label': 'manual', 'reason': 'Требуется локальный разбор содержимого.'}
        case.status = 'manual'
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
    case.status = 'closed' if review['label'] in ('learner_error', 'insufficient_context') else 'ready'


def decision_tag(case: AnswerDispute) -> str:
    payload = [case.question_revision, case.grader_version, case.review['label'], case.review.get('patch')]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:14]


def _telegram_card(case: AnswerDispute) -> tuple[str, dict | None]:
    review = case.review
    row = case.evidence['row']
    instructions = [case.evidence['question'].get('lesson_instruction'), row.get('instruction'),
                    case.evidence['question'].get('instruction'), case.evidence['question'].get('prompt'),
                    case.evidence['question'].get('context'), row.get('context'), row.get('constraints'), row.get('required_words')]
    question = '\n'.join(dict.fromkeys(str(s) for s in instructions if s))
    prefix = f"dispute:{case.id}:{decision_tag(case)}:"
    patch = review.get('patch')
    if patch:
        field, value = next(iter(patch.items()))
        if field in ('alternative_answers', 'alternatives'):
            change = 'Добавить допустимый ответ: ' + value[-1]
        else:
            change = f'Заменить ключ «{row.get(field)}» на «{value}»'
    else:
        change = 'Передать на разбор проверки и задания вручную'
    keyboard = [[{'text': 'Одобрить правку' if patch else 'В ручной разбор', 'callback_data': prefix + 'approve'}],
                [{'text': 'Отклонить', 'callback_data': prefix + 'reject'},
                 {'text': 'На доработку', 'callback_data': prefix + 'revise'}]]
    title = {'valid_variant': 'Возможен второй верный ответ', 'wrong_key': 'Возможная ошибка в ключе',
             'grader_issue': 'Возможная ошибка в проверке'}[review['label']]
    # Keep the complete instruction and proposed change visible when asking for approval.
    if case.grammar_exercise_id is not None:
        source = f'Grammar Lab · тема {review["topic_id"]}, упражнение {case.grammar_exercise_id}'
    else:
        source = f'Урок {case.lesson_id}, вопрос {int(case.question_id) + 1}'
    text = (f'{title} · спор {case.id}\n{source}\n'
            f'{question}\nОтвет ученика: {review["shown_answer"]}\n'
            f'Текущий ключ: {review["shown_key"]}\n{review["reason"]}\n\n{change}')
    if len(text.encode('utf-16-le')) // 2 > 4096:
        return (f'Спор {case.id} ({source}) требует ручного разбора. '
                'Полное условие превышает размер сообщения.'), None
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
        case.status = 'notified' if keyboard else 'manual'
    else:
        case.next_attempt_at = now + timedelta(minutes=10)


def decide(case_id: int, tag: str, action: str, sender: int, chat: int) -> str:
    if type(sender) is not int or sender <= 0 or sender != chat:
        return 'Решение доступно администратору'
    # Keep both the link and the administrator's role valid until the decision commits.
    if not TelegramUser.active_admin_links().filter(TelegramUser.telegram_id == sender).with_for_update(read=True).first():
        db.session.rollback()
        return 'Решение доступно администратору'
    case = AnswerDispute.query.filter_by(id=case_id).populate_existing().with_for_update().first()
    if not case or case.status not in ('ready', 'notified') or tag != decision_tag(case):
        db.session.rollback()
        return 'Карточка уже обработана или устарела'
    if action in ('reject', 'revise'):
        case.status = 'dismissed' if action == 'reject' else 'revise'
    elif action == 'approve' and case.grammar_exercise_id is not None:
        exercise = _current_lab_exercise(case, lock=True)
        patch = case.review.get('patch')
        if exercise is None:
            case.status = 'stale'
        elif not patch:
            case.status = 'manual'
        elif lab.proposed_lab_edit(exercise, lab.effective_content(exercise), case.evidence['answer'], case.review['label']) != patch:
            case.status = 'stale'
        else:
            lab.apply_lab_patch(exercise, patch)
            case.status = 'applied'
    elif action == 'approve':
        lesson = Lessons.query.filter_by(id=case.lesson_id).populate_existing().with_for_update().first()
        row = current_dispute_row(case, lesson) if lesson else None
        patch = case.review.get('patch')
        if row is None:
            case.status = 'stale'
        elif not patch:
            case.status = 'manual'
        elif proposed_edit(lesson, row, _question(lesson, case), case.evidence['answer'], case.review['label']) != patch:
            case.status = 'stale'
        else:
            content = content_for(lesson)
            rows = content.get('questions') if lesson.type == 'quiz' else None
            rows = rows or content['exercises']
            rows[int(case.question_id)].update(patch)
            lesson.content = content
            case.status = 'applied'
    else:
        db.session.rollback()
        return 'Неизвестное действие'
    case.review = {**case.review, 'decided_by': sender, 'decided_at': datetime.now(timezone.utc).isoformat()}
    status = case.status
    db.session.commit()
    return {'applied': 'Правка применена', 'manual': 'Передано на ручной разбор',
            'stale': 'Задание изменилось', 'dismissed': 'Отклонено', 'revise': 'На доработке'}[status]


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
        case.review = {'label': 'manual', 'reason': 'Требуется разбор формата задания.'}
        case.status = 'manual'
    db.session.commit()
    return True


def process_answer_disputes(app: Flask) -> None:
    with app.app_context():
        for _ in range(5):
            if not process_one():
                break
