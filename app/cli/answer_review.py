"""Explicit classifier diagnostics and read-only access to answer-review cases."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import click
from flask import Flask, current_app
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.grading import process_quiz_submission
from app.utils.db import db

MANUAL_STATUSES = ('manual', 'revise')
MAX_CASES = 100
SYNTHETIC_CASE = {
    'id': 'synthetic-translation',
    'row': {
        'type': 'translation', 'instruction': 'Переведи свободно, сохрани смысл. Синонимы разрешены.',
        'question': 'Я хожу на работу пешком.', 'correct_answer': 'I walk to work.',
    },
    'answer': 'I go to work on foot.',
}


def _cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        values = [SYNTHETIC_CASE]
    else:
        try:
            if path.stat().st_size > 1_000_000:
                raise ValueError()
            values = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError):
            raise click.ClickException('Не удалось прочитать JSON-выборку (максимум 1 MB).') from None
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_CASES:
        raise click.ClickException(f'Ожидается массив из 1–{MAX_CASES} случаев.')
    seen: set[str] = set()
    result = []
    for case in values:
        if (not isinstance(case, dict) or set(case) != {'id', 'row', 'answer'}
                or not isinstance(case['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', case['id'])
                or case['id'] in seen or not isinstance(case['row'], dict)
                or not isinstance(case['answer'], str) or not case['answer'].strip()):
            raise click.ClickException('Некорректный формат случая или повторяющийся ID.')
        seen.add(case['id'])
        try:
            feedback = process_quiz_submission([case['row']], {'0': case['answer']})['feedback']['0']
        except (TypeError, ValueError, KeyError, AttributeError):
            raise click.ClickException(f'Случай {case["id"]} не подходит для курсового quiz.') from None
        if feedback['status'] != 'incorrect':
            raise click.ClickException(f'Ответ {case["id"]} уже принимается исходным грейдером.')
        row = case['row']
        question = {'prompt': row.get('question') or row.get('prompt') or row.get('sentence') or row.get('text') or '',
                    'instruction': row.get('instruction') or ''}
        if 'context' in row:
            question['context'] = row['context']
        evidence = {
            'row': case['row'],
            'question': question,
            'expected': feedback['correct_answer'], 'submitted_answer': feedback['user_answer'],
        }
        encoded = json.dumps(evidence, ensure_ascii=False)
        if len(encoded) > 10000 or ai.CONTACT.search(encoded):
            raise click.ClickException(f'Случай {case["id"]} требует локального разбора содержимого.')
        result.append({'id': case['id'], 'evidence': evidence})
    return result


def _status(case_id: int | None) -> dict[str, Any]:
    if case_id is not None:
        case = db.session.get(AnswerDispute, case_id)
        if case is None:
            raise click.ClickException('Дело не найдено.')
        return {
            'id': case.id, 'lesson_id': case.lesson_id, 'question_id': case.question_id,
            **({'grammar_exercise_id': case.grammar_exercise_id} if case.grammar_exercise_id is not None else {}),
            'status': case.status, 'question_revision': case.question_revision,
            'grader_version': case.grader_version, 'evidence': case.evidence, 'review': case.review,
        }
    counts = dict(db.session.query(AnswerDispute.status, func.count()).group_by(AnswerDispute.status).all())
    ids = db.session.query(AnswerDispute.id).filter(AnswerDispute.status.in_(MANUAL_STATUSES)).order_by(AnswerDispute.id).limit(100).all()
    manual_ids = [row[0] for row in ids]
    total = sum(counts.get(status, 0) for status in MANUAL_STATUSES)
    return {'counts': counts, 'manual_total': total, 'manual_ids': manual_ids,
            'manual_ids_truncated': total > len(manual_ids)}


def register_answer_review_commands(app: Flask) -> None:
    @app.cli.command('answer-review-check')
    @click.option('--cases', 'cases_path', type=click.Path(exists=True, dir_okay=False, path_type=Path),
                  help='JSON array of {id, row, answer}. Default: one synthetic translation.')
    def check_command(cases_path: Path | None) -> None:
        """Call the configured AI classifier explicitly; do not queue, apply or notify."""
        cases = _cases(cases_path)  # Validate every item before making the first paid request.
        key, model = current_app.config.get('OPENAI_API_KEY'), current_app.config.get('OPENAI_MODEL')
        if not isinstance(key, str) or not key.strip() or not isinstance(model, str) or not model.strip():
            raise click.ClickException('Настрой OPENAI_API_KEY и OPENAI_MODEL перед проверкой.')
        results = []
        for case in cases:
            try:
                verdict = ai.classify(case['evidence'], key=key.strip(), model=model.strip())
            except ai.ReviewServiceError:
                click.echo(json.dumps({'cases': len(cases), 'results': results, 'error': 'review_unavailable'}, ensure_ascii=False))
                raise click.ClickException('Проверка прервана: сервис не подтвердил результат. Готовые результаты выведены выше.') from None
            results.append({'id': case['id'], **verdict})
        click.echo(json.dumps({'cases': len(cases), 'results': results}, ensure_ascii=False))

    @app.cli.command('answer-review-status')
    @click.option('--case', 'case_id', type=click.IntRange(min=1),
                  help='Show private evidence/review for one case locally. Default: metadata only.')
    def status_command(case_id: int | None) -> None:
        """Read queue counts/manual IDs, or inspect one private case without modifying it."""
        try:
            value = _status(case_id)
        except SQLAlchemyError:
            raise click.ClickException('Не удалось прочитать очередь проверки ответов.') from None
        click.echo(json.dumps(value, ensure_ascii=False, sort_keys=True))
