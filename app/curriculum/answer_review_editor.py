"""Preview and confirm a human decision on the original exercise revision."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from functools import partial

from app.admin.audit import log_admin_action
from app.auth.models import User
from app.curriculum import answer_review as worker
from app.curriculum.answer_disputes import AnswerDispute, current_dispute_row
from app.curriculum.answer_review_edits import answer_aliases
from app.curriculum.grading import _quiz_option_index
from app.curriculum.models import Lessons
from app.grammar_lab import answer_review as lab
from app.grammar_lab.guided_learning import check_answer
from app.grammar_lab.models import GrammarExercise
from app.utils.db import db

EDITABLE = frozenset({'pending', 'ready', 'notified', 'manual', 'revise', 'closed'})
_CONTENT_ACTIONS = {'add': 'valid_variant', 'replace': 'wrong_key'}


def editor_version(case: AnswerDispute) -> str:
    review = case.review or {}
    # Notification retries do not change the material or the editor's proposal.
    state = 'reviewed' if case.status in ('ready', 'notified') else case.status
    identity = [case.id, case.question_revision, case.grader_version, state, review.get('label'),
                review.get('patch'), review.get('decided_at'), review.get('status_after_notification')]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _check_action(case: AnswerDispute, action: str) -> None:
    if case.status not in EDITABLE:
        raise ValueError('Спор уже закрыт или материал устарел. Обновите карточку.')
    if action not in {*_CONTENT_ACTIONS, 'reject', 'revise'}:
        raise ValueError('Выберите действие.')
    if action == 'revise' and case.status == 'revise':
        raise ValueError('Спор уже сохранён на доработку.')


def _content_edit(case: AnswerDispute, action: str, answer: str, *, lock: bool) -> tuple:
    if not isinstance(answer, str) or not 0 < len(answer.strip()) <= 500 or not answer.strip().isprintable():
        raise ValueError('Введите один ответ длиной до 500 символов.')
    answer = answer.strip()
    label = _CONTENT_ACTIONS[action]
    submitted = case.evidence['answer']
    if case.grammar_exercise_id is not None:
        source = worker._current_lab_exercise(case, lock=lock)
        row = lab.effective_content(source) if source else None
    else:
        query = Lessons.query.filter_by(id=case.lesson_id)
        if lock:
            query = query.populate_existing().with_for_update(key_share=True)
        source = query.one_or_none()
        row = current_dispute_row(case, source) if source else None
    if row is None:
        raise ValueError('Задание изменилось после обращения. Сверьте актуальный материал.')

    candidate = answer
    is_lab = isinstance(source, GrammarExercise)
    question = None if is_lab else worker._question(source, case)
    is_choice = source.exercise_type == 'multiple_choice' if is_lab else question.get('input') == 'choice'
    options = row.get('options') or []
    if is_choice:
        index = _quiz_option_index(options, answer, prefer_literal=True)
        if index < 0:
            raise ValueError('Выберите один из вариантов, показанных ученику.')
        candidate = str(index)

    if is_lab:
        patch = lab.proposed_lab_edit(source, row, candidate, label)
        grade = partial(lab.grade_row, source)
        correct_key = 'is_correct'
    else:
        patch = worker.proposed_edit(source, row, question, candidate, label)
        grade = partial(check_answer, question=question, grammar=source.type == 'grammar')
        correct_key = 'correct'
    if not patch:
        raise ValueError('Такую правку проверка задания применить не может. Проверьте формат, действующий ключ и допустимые ответы.')

    resulting = {**row, **patch}
    before = grade(row, answer=submitted)
    after = grade(resulting, answer=submitted)
    if is_lab:
        shown, old_key = lab.display_review_answers(source, row, before)
        _, new_key = lab.display_review_answers(source, resulting, after)
    else:
        shown, old_key, new_key = before.get('answer'), before.get('expected'), after.get('expected')
        if action == 'replace' and not is_choice:
            # Quiz feedback joins the key and accepted aliases for the learner.
            # The editor needs the authored key on its own.
            key_field = next(key for key in worker.KEYS if key in patch)
            old_key, new_key = row[key_field], resulting[key_field]

    before_aliases = answer_aliases(row)
    removed_answers = []
    if action == 'replace':
        for value in dict.fromkeys([str(old_key), *before_aliases]):
            if not value.strip() or len(value) > 20000:
                continue
            trial = value
            if is_choice:
                index = _quiz_option_index(options, value, prefer_literal=True)
                if index < 0:
                    continue
                trial = str(index)
            if grade(row, answer=trial).get(correct_key) and not grade(resulting, answer=trial).get(correct_key):
                removed_answers.append(value)
    preview = {'action': action, 'answer': answer, 'before': str(old_key), 'after': str(new_key),
               'before_aliases': before_aliases, 'aliases': answer_aliases(resulting),
               'removed_answers': removed_answers, 'accepts_report': after.get(correct_key) is True}
    return source, patch, candidate, shown, preview


def editor_preview(case: AnswerDispute, action: str, answer: str) -> dict:
    _check_action(case, action)
    if action in _CONTENT_ACTIONS:
        return _content_edit(case, action, answer, lock=False)[-1]
    return {'action': action, 'answer': '', 'before': '', 'after': '', 'aliases': [],
            'removed_answers': [], 'accepts_report': False}


def editor_decide(case_id: int, user_id: int, version: str, action: str, answer: str) -> str:
    """Recheck access, the preview and the real grader before committing any writes."""
    actor = User.query.filter_by(id=user_id).populate_existing().with_for_update(key_share=True).one_or_none()
    if actor is None or not actor.can_edit_content:
        raise ValueError('Нет права редактировать контент.')
    case = AnswerDispute.query.filter_by(id=case_id).populate_existing().with_for_update().one_or_none()
    if case is None or editor_version(case) != version:
        raise ValueError('Спор изменился. Откройте карточку и ещё раз проверьте правку.')
    _check_action(case, action)
    review = dict(case.review or {})
    if action in _CONTENT_ACTIONS:
        source, patch, candidate, shown, preview = _content_edit(case, action, answer, lock=True)
        if review.get('model') and 'model_label' not in review:
            review['model_label'] = review.get('label')
        review.update(label=_CONTENT_ACTIONS[action], patch=patch, editor_answer=candidate, shown_answer=shown,
                      shown_key=preview['before'], resulting_key=preview['after'], accepts_report=preview['accepts_report'])
        case.review = review
        worker.apply_review_patch(case, source, patch)
        message = 'Правка сохранена.'
    else:
        case.status = 'dismissed' if action == 'reject' else 'revise'
        message = 'Спор отклонён.' if action == 'reject' else 'Спор сохранён на доработку.'
    case.review = {**(case.review or {}), 'decided_by_user_id': actor.id,
                   'editor_action': action, 'decided_at': datetime.now(UTC).isoformat()}
    case.next_attempt_at = None
    log_admin_action(user_id, f'answer_dispute.{action}', target_type='answer_dispute', target_id=case_id)
    worker.commit_decision(case)
    return message
