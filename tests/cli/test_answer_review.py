"""Operational CLI checks use mocked AI and the existing disposable SQLite fixture."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.cli.answer_review import register_answer_review_commands
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.utils.db import db
from tests.api.test_account_deletion import native_app as _native_app


@pytest.fixture(scope='module')
def native_app(tmp_path_factory: Any) -> Any:
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def cli(native_app: Any, monkeypatch: Any) -> tuple[Any, Mock]:
    register_answer_review_commands(native_app)
    monkeypatch.setitem(native_app.config, 'OPENAI_API_KEY', 'private-test-key')
    monkeypatch.setitem(native_app.config, 'OPENAI_MODEL', 'test-model')
    classify = Mock(return_value={'label': 'valid_variant', 'reason': 'Тестовое объяснение.', 'model': 'test-model'})
    monkeypatch.setattr(ai, 'classify', classify)
    monkeypatch.setattr(ai.requests, 'post', Mock(side_effect=AssertionError('Live AI is forbidden in these tests')))
    return native_app.test_cli_runner(), classify


def _example(case_id: str = 'sample') -> dict[str, Any]:
    return {'id': case_id, 'row': {'type': 'translation', 'instruction': 'Переведи свободно.',
                                 'question': 'Я хожу в школу пешком.', 'correct_answer': 'I walk to school.'},
            'answer': 'I go to school on foot.'}


def _write(path: Path, cases: Any) -> Path:
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding='utf-8')
    return path


def test_default_classifies_one_synthetic_translation_without_queue_writes(cli: Any) -> None:
    runner, classify = cli
    before = AnswerDispute.query.count()
    result = runner.invoke(args=['answer-review-check'])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value['cases'] == 1 and value['results'][0]['id'] == 'synthetic-translation'
    assert classify.call_count == 1
    evidence = classify.call_args.args[0]
    assert evidence['row']['instruction'] and evidence['submitted_answer']
    assert evidence['question']['prompt'] == evidence['row']['question']
    assert 'private-test-key' not in result.output
    assert AnswerDispute.query.count() == before


def test_cases_preflight_and_choice_display_match_worker_input(cli: Any, tmp_path: Path) -> None:
    runner, classify = cli
    choice = {'id': 'choice', 'row': {'type': 'multiple_choice', 'instruction': 'Выбери слово.',
                                    'question': 'Choose a shop.', 'options': ['magazine', 'shop'], 'correct_answer': 'shop'},
              'answer': '0'}
    result = runner.invoke(args=['answer-review-check', '--cases', str(_write(tmp_path/'cases.json', [_example(), choice]))])
    assert result.exit_code == 0, result.output
    assert [x['id'] for x in json.loads(result.output)['results']] == ['sample', 'choice']
    assert classify.call_count == 2
    assert classify.call_args.args[0]['submitted_answer'] == 'magazine'
    assert classify.call_args.args[0]['expected'] == 'shop'


@pytest.mark.parametrize('cases', [[], {}, [_example(), _example()],
                                 [{**_example(), 'answer': []}], [{**_example(), 'id': '../bad'}],
                                 [{**_example(), 'gold': 'hidden'}],
                                 [_example(), {**_example('already-correct'), 'answer': 'I walk to school.'}]])
def test_invalid_batch_never_makes_a_partial_paid_call(cli: Any, tmp_path: Path, cases: Any) -> None:
    runner, classify = cli
    result = runner.invoke(args=['answer-review-check', '--cases', str(_write(tmp_path/'bad.json', cases))])
    assert result.exit_code != 0
    classify.assert_not_called()


def test_contacts_and_oversized_or_invalid_files_are_not_echoed_or_sent(cli: Any, tmp_path: Path) -> None:
    runner, classify = cli
    contact = _example()
    contact['row']['question'] = 'private-person@example.invalid'
    result = runner.invoke(args=['answer-review-check', '--cases', str(_write(tmp_path/'contact.json', [contact]))])
    assert result.exit_code != 0 and 'private-person' not in result.output
    for content in ('not json', 'sensitive' * 150000):
        path = tmp_path/'bad.json'; path.write_text(content)
        result = runner.invoke(args=['answer-review-check', '--cases', str(path)])
        assert result.exit_code != 0 and 'sensitive' not in result.output
    classify.assert_not_called()


def test_missing_configuration_never_prints_credentials_or_calls_ai(cli: Any, native_app: Any, monkeypatch: Any) -> None:
    runner, classify = cli
    monkeypatch.setitem(native_app.config, 'OPENAI_MODEL', '')
    result = runner.invoke(args=['answer-review-check'])
    assert result.exit_code != 0 and 'OPENAI_MODEL' in result.output
    assert 'private-test-key' not in result.output
    classify.assert_not_called()


def test_service_failure_preserves_completed_results_but_not_exception_secrets(cli: Any, tmp_path: Path) -> None:
    runner, classify = cli
    classify.side_effect = [classify.return_value, ai.ReviewServiceError('private-test-key and private payload')]
    result = runner.invoke(args=['answer-review-check', '--cases', str(_write(tmp_path/'cases.json', [_example('one'), _example('two')]))])
    assert result.exit_code != 0
    payload = json.loads(result.output.splitlines()[0])
    assert payload['error'] == 'review_unavailable'
    assert [row['id'] for row in payload['results']] == ['one']
    assert 'private-test-key' not in result.output and 'private payload' not in result.output


@pytest.fixture
def queued(native_app: Any) -> list[AnswerDispute]:
    unique = uuid4().hex
    code = next(f'Z{index}' for index in range(10) if not CEFRLevel.query.filter_by(code=f'Z{index}').first())
    level = CEFRLevel(code=code, name='Isolated CLI')
    db.session.add(level); db.session.flush()
    module = Module(level_id=level.id, number=1, title='Isolated CLI')
    db.session.add(module); db.session.flush()
    lesson = Lessons(module_id=module.id, number=1, type='quiz', title='Private fixture', content={})
    db.session.add(lesson); db.session.flush()
    rows = [AnswerDispute(lesson_id=lesson.id, question_id='0', question_revision=unique,
                          grader_version=1, normalized_answer_hash=unique+str(index), status=status,
                          evidence={'row': {'question': 'PRIVATE_EVIDENCE'}, 'answer': 'PRIVATE_ANSWER'},
                          review={'reason': 'PRIVATE_REVIEW'})
            for index, status in enumerate(('manual', 'revise', 'pending', 'notified'))]
    db.session.add_all(rows); db.session.commit()
    return rows


def test_default_status_only_exposes_metadata_and_is_read_only(cli: Any, queued: Any, monkeypatch: Any) -> None:
    runner, classify = cli
    before = [(row.id, row.status, deepcopy(row.evidence), deepcopy(row.review)) for row in queued]
    monkeypatch.setattr(db.session, 'commit', Mock(side_effect=AssertionError('Status must not commit')))
    result = runner.invoke(args=['answer-review-status'])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert queued[0].id in value['manual_ids'] and queued[1].id in value['manual_ids']
    assert queued[2].id not in value['manual_ids'] and queued[3].id not in value['manual_ids']
    assert value['manual_total'] >= 2 and value['counts']['pending'] >= 1
    assert 'PRIVATE_' not in result.output and 'private-test-key' not in result.output
    assert [(row.id, row.status, row.evidence, row.review) for row in queued] == before
    classify.assert_not_called()


def test_private_case_is_only_shown_when_explicitly_selected(cli: Any, queued: Any) -> None:
    runner, classify = cli
    row = queued[0]
    result = runner.invoke(args=['answer-review-status', '--case', str(row.id)])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value['id'] == row.id and value['lesson_id'] == row.lesson_id
    assert value['evidence'] == row.evidence and value['review'] == row.review
    assert 'private-test-key' not in result.output
    classify.assert_not_called()


def test_status_errors_are_safe(cli: Any, monkeypatch: Any) -> None:
    runner, classify = cli
    assert runner.invoke(args=['answer-review-status', '--case', '9999999']).exit_code != 0
    assert runner.invoke(args=['answer-review-status', '--case', '0']).exit_code != 0
    monkeypatch.setattr(db.session, 'query', Mock(side_effect=SQLAlchemyError('secret-database-password')))
    result = runner.invoke(args=['answer-review-status'])
    assert result.exit_code != 0 and 'secret-database-password' not in result.output
    classify.assert_not_called()


def test_status_bounds_manual_ids_and_reports_truncation(cli: Any, queued: Any) -> None:
    runner, classify = cli
    row = queued[0]
    db.session.add_all([AnswerDispute(lesson_id=row.lesson_id, question_id='0', question_revision=row.question_revision,
                                    grader_version=1, normalized_answer_hash=uuid4().hex,
                                    status='manual', evidence={'row': 'PRIVATE_EVIDENCE'}) for _ in range(102)])
    db.session.commit()
    result = runner.invoke(args=['answer-review-status'])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert len(value['manual_ids']) == 100 and value['manual_ids'] == sorted(value['manual_ids'])
    assert value['manual_ids_truncated'] is True and value['manual_total'] >= 102
    assert 'PRIVATE_EVIDENCE' not in result.output
    classify.assert_not_called()
