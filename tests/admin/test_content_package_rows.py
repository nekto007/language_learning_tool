"""Publish exact lesson rows while preserving other edits and history."""

from copy import deepcopy

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.admin.routes import content_packages
from app.admin.services.content_package_rows import writing_guard
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.models import Lessons, Module
from tests.admin.test_content_package_routes import APPLY, _audit_count, _page, _preview_id, _upload
from tests.admin.test_content_package_routes import staged_files as staged_files

pytestmark = pytest.mark.usefixtures('staged_files')


def _lesson(db_session: scoped_session, module: Module, number: int) -> Lessons:
    rows = [
        {'type': 'dialogue_completion', 'dialogue': 'A: Do you like this?\nB: ___',
         'options': ['Yes, I do.', 'Not really.'], 'correct': 'Yes, I do.'},
        {'type': 'dialogue_completion', 'dialogue': 'A: What is it?\nB: ___',
         'options': ['A lamp.', 'A box.'], 'correct': 'A lamp.'},
    ]
    lesson = Lessons(module_id=module.id, number=number, title=f'Test dialogue {number}', type='dialogue_completion_quiz',
                     content={'external_key': f'test:dialogue:{number}', 'exercises': rows, 'meta': {'safe': 1}})
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _patch(lesson: Lessons) -> dict:
    before = deepcopy(lesson.content['exercises'][0])
    after = {**before, 'options': ['Yes, I do.', 'Yes, it is.']}
    return {'kind': 'lesson_rows_v1', 'external_key': lesson.content['external_key'],
            'level': lesson.module.level.code, 'module_number': lesson.module.number,
            'lesson_type': lesson.type, 'changes': [{'path': ['exercises', 0], 'before': before, 'after': after}]}


def test_row_preview_preserves_neighbor_edits_and_module_metadata(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session, test_module: Module,
) -> None:
    lesson = _lesson(db_session, test_module, 13)
    package = _patch(lesson)
    old = deepcopy(lesson.content)
    preview = _page(admin_client, _upload(admin_client, {'dialogue.json': package}))
    preview_id = _preview_id(preview)
    diffs = preview.select_one('details').get_text()
    assert 'Задание 1 · Варианты ответа' in diffs and 'Not really.' in diffs and 'Yes, it is.' in diffs
    assert 'exercises / 1' not in diffs
    summary = preview.select_one('dl[aria-label="Сводка пакета"]').get_text()
    assert 'Изменённых заданий' in summary and 'Полей письменных работ' not in summary
    assert lesson.content == old and _audit_count(admin_user) == 0

    neighbor = {**old['exercises'][1], 'hint': 'A newer edit from another editor.'}
    lesson.content = {**old, 'exercises': [old['exercises'][0], neighbor], 'meta': {'after preview': True}}
    test_module.raw_content = {'preserved': [1, 2]}
    db_session.commit()
    _page(admin_client, admin_client.post(APPLY, data={'preview_id': preview_id}))
    db_session.refresh(lesson)
    assert lesson.content == {**old, 'exercises': [package['changes'][0]['after'], neighbor],
                              'meta': {'after preview': True}}
    assert test_module.raw_content == {'preserved': [1, 2]}
    assert _audit_count(admin_user) == 1

    stale = _page(admin_client, _upload(admin_client, {'dialogue.json': package}))
    assert stale.select_one('input[name=preview_id]') is None
    assert _audit_count(admin_user) == 1


def test_row_package_stops_on_drift_and_rolls_back_when_audit_fails(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session, test_module: Module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _lesson(db_session, test_module, 13)
    second = _lesson(db_session, test_module, 14)
    zip_entries = {'1.json': _patch(first), '2.json': _patch(second)}
    first_old = deepcopy(first.content)
    second_old = deepcopy(second.content)
    pending = _preview_id(_page(admin_client, _upload(admin_client, zip_entries)))
    second.content = {**second_old, 'exercises': [{**second_old['exercises'][0], 'extra': 0}, second_old['exercises'][1]]}
    db_session.commit()
    page = _page(admin_client, admin_client.post(APPLY, data={'preview_id': pending}))
    conflict = page.select_one('[aria-labelledby=package-conflict]')
    assert 'Задание 1 · Другие исходные данные' in conflict.get_text(' ', strip=True)
    assert conflict.select_one('a')['href'] == f'/curriculum/admin/lesson/{second.id}/edit'
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.content == first_old and second.content['exercises'][0]['extra'] == 0
    assert _audit_count(admin_user) == 0

    zip_entries['2.json'] = _patch(second)
    pending = _preview_id(_page(admin_client, _upload(admin_client, zip_entries)))

    def fail(*_args: object, **kwargs: object) -> None:
        assert kwargs['required'] is True
        raise RuntimeError('synthetic audit failure')

    monkeypatch.setattr(content_packages, 'log_admin_action', fail)
    _page(admin_client, admin_client.post(APPLY, data={'preview_id': pending}))
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.content == first_old and second.content['exercises'][0]['options'] == ['Yes, I do.', 'Not really.']
    assert _audit_count(admin_user) == 0


@pytest.mark.parametrize(('reason', 'message'), [
    ('changed', 'Задание 1 · Варианты ответа'),
    ('moved', 'Исходное задание теперь на позиции 2'),
    ('ambiguous', 'Исходные данные совпадают у нескольких заданий'),  # noqa: RUF001 -- Russian UI message.
    ('missing', 'На указанном месте больше нет задания'),  # noqa: RUF001 -- Russian UI message.
])
def test_conflict_names_source_and_keeps_current_rows(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session, test_module: Module,
    reason: str, message: str,
) -> None:
    lesson = _lesson(db_session, test_module, 13)
    archive = {'rows/dialogue.json': _patch(lesson)}
    preview_id = _preview_id(_page(admin_client, _upload(admin_client, archive)))
    first, second = lesson.content['exercises']
    current = {
        'changed': [{**first, 'options': [first['correct'], 'Not today.']}, second],
        'moved': [second, first],
        'ambiguous': [first, second, first],
        'missing': [],
    }[reason]
    lesson.content = {**lesson.content, 'exercises': current}
    db_session.commit()
    for rejected in (
        _page(admin_client, admin_client.post(APPLY, data={'preview_id': preview_id})),
        _page(admin_client, _upload(admin_client, archive)),
    ):
        conflict = rejected.select_one('[aria-labelledby=package-conflict]')
        assert conflict is not None
        text = conflict.get_text(' ', strip=True)
        assert f'Урок 13 «{lesson.title}»' in text and message in text
        assert 'Пакет не применён' in text and 'rows/dialogue.json' in text
        assert 'проверить ZIP с актуальными исходными данными' in text  # noqa: RUF001 -- Russian UI message.
        assert 'exercises' not in text
        assert rejected.select_one('input[name=preview_id]') is None
    replay = _page(admin_client, admin_client.post(APPLY, data={'preview_id': preview_id}))
    assert 'Предпросмотр устарел' in replay.get_text(' ', strip=True)
    db_session.refresh(lesson)
    assert lesson.content['exercises'] == current and _audit_count(admin_user) == 0


def test_rejects_other_module_and_ambiguous_anchor(
    admin_client: FlaskClient, db_session: scoped_session, test_module: Module,
) -> None:
    lesson = _lesson(db_session, test_module, 13)
    wrong_module = {**_patch(lesson), 'module_number': test_module.number + 1}
    rejected = _page(admin_client, _upload(admin_client, {'row.json': wrong_module}))
    assert rejected.select_one('input[name=preview_id]') is None
    original = deepcopy(lesson.content)
    lesson.content = {**original, 'exercises': [original['exercises'][0], *original['exercises']]}
    db_session.commit()
    rejected = _page(admin_client, _upload(admin_client, {'row.json': _patch(lesson)}))
    assert rejected.select_one('input[name=preview_id]') is None


@pytest.mark.parametrize('mixed', [False, True], ids=['writing-only', 'mixed'])
def test_writing_patch_checks_and_changes_only_prompt_ru(
    admin_client: FlaskClient, db_session: scoped_session, test_module: Module, mixed: bool,
) -> None:
    original = {'external_key': 'test:writing:1', 'prompt': 'Write about a museum.',
                'prompt_ru': 'Расскажите про музэй.', 'min_words': 20}
    lesson = Lessons(module_id=test_module.id, number=17, type='writing_prompt',
                     title='Test writing', content=original)
    db_session.add(lesson)
    db_session.commit()
    corrected = 'Расскажите про музей.'
    package = {'kind': 'lesson_rows_v1', 'external_key': original['external_key'],
               'level': test_module.level.code, 'module_number': test_module.number, 'lesson_type': lesson.type,
                'writing_guard': writing_guard(original),
               'changes': [{'path': ['prompt_ru'], 'before': original['prompt_ru'], 'after': corrected}]}
    documents = {'writing.json': package}
    lessons_label = 'Уроков с точечными изменениями'  # noqa: RUF001 -- Russian UI label.
    expected = {'Файлов': '1', lessons_label: '1', 'Полей письменных работ': '1'}
    if mixed:
        dialogue = _lesson(db_session, test_module, 13)
        dialogue_patch = _patch(dialogue)
        before = deepcopy(dialogue.content['exercises'][1])
        dialogue_patch['changes'].append({'path': ['exercises', 1], 'before': before,
                                          'after': {**before, 'options': ['A lamp.', 'A window.']}})
        documents['dialogue.json'] = dialogue_patch
        expected.update({'Файлов': '2', lessons_label: '2', 'Изменённых заданий': '2'})
    preview = _page(admin_client, _upload(admin_client, documents))
    summary = preview.select_one('dl[aria-label="Сводка пакета"]')
    assert {item.dt.get_text(strip=True): item.dd.get_text(strip=True) for item in summary.select('div')} == expected
    detail = preview.find('summary', string='Задание на русском').parent.get_text()
    assert 'Задание на русском' in detail and corrected in detail and 'prompt_ru' not in detail
    lesson.content = {**original, 'technical_tag': 'Concurrent non-editorial metadata'}
    db_session.commit()
    applied = _page(admin_client, admin_client.post(APPLY, data={'preview_id': _preview_id(preview)}))
    message = applied.select_one('[role=alert]').get_text()
    for label, count in expected.items():
        assert f'{label} — {count}' in message
    assert ('Изменённых заданий' in message) == mixed
    db_session.refresh(lesson)
    assert lesson.content == {**original, 'prompt_ru': corrected, 'technical_tag': 'Concurrent non-editorial metadata'}


def test_writing_patch_rejects_shortened_rubric_or_nonqualifying_sample(
    admin_client: FlaskClient, db_session: scoped_session, test_module: Module,
) -> None:
    original = {'external_key': 'test:writing:rubric', 'prompt': 'Write about a museum.',
                'example_response': 'I visited a museum. I liked the exhibition.', 'min_sentences': 3,
                'min_words': 5, 'checklist': ['Named a place', 'Gave an opinion']}
    lesson = Lessons(module_id=test_module.id, number=17, type='writing_prompt',
                     title='Test writing rubric', content=original)
    db_session.add(lesson)
    db_session.commit()
    document = {'kind': 'lesson_rows_v1', 'external_key': original['external_key'],
                'level': test_module.level.code, 'module_number': test_module.number, 'lesson_type': lesson.type,
                'writing_guard': writing_guard(original)}
    for field, after in (('min_words', 1), ('min_sentences', 4), ('example_response', 'An even shorter sample.')):
        change = {'path': [field], 'before': original[field], 'after': after}
        page = _page(admin_client, _upload(admin_client, {'writing.json': {**document, 'changes': [change]}}))
        assert page.select_one('input[name=preview_id]') is None
        assert lesson.content == original

    after = original['example_response'] + ' The old maps were my favourite part.'
    change = {'path': ['example_response'], 'before': original['example_response'], 'after': after}
    page = _page(admin_client, _upload(admin_client, {'writing.json': {**document, 'changes': [change]}}))
    _page(admin_client, admin_client.post(APPLY, data={'preview_id': _preview_id(page)}))
    db_session.refresh(lesson)
    assert lesson.content == {**original, 'example_response': after}


def test_writing_patch_refuses_changed_prompt_even_when_threshold_matches(
    admin_client: FlaskClient, db_session: scoped_session, test_module: Module,
) -> None:
    baseline = {'external_key': 'test:writing:drift', 'prompt': 'Write about a museum.',
                'example_response': 'I visited a museum. I liked the exhibition.', 'min_sentences': 3, 'min_words': 5}
    lesson = Lessons(module_id=test_module.id, number=17, type='writing_prompt',
                     title='Test writing drift', content=baseline)
    db_session.add(lesson)
    db_session.commit()
    package = {'kind': 'lesson_rows_v1', 'external_key': baseline['external_key'],
               'level': test_module.level.code, 'module_number': test_module.number, 'lesson_type': lesson.type,
               'writing_guard': writing_guard(baseline),
               'changes': [{'path': ['min_sentences'], 'before': 3, 'after': 2}]}
    pending = _preview_id(_page(admin_client, _upload(admin_client, {'writing.json': package})))
    edited = {**baseline, 'prompt': 'Compare two museums.'}
    lesson.content = edited
    db_session.commit()
    result = _page(admin_client, admin_client.post(APPLY, data={'preview_id': pending}))
    assert 'образец изменились' in result.get_text()
    assert lesson.content == edited
    rejected = _page(admin_client, _upload(admin_client, {'writing.json': package}))
    assert rejected.select_one('input[name=preview_id]') is None


def test_applied_dispute_since_preview_blocks_row_patch(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session, test_module: Module,
) -> None:
    lesson = _lesson(db_session, test_module, 13)
    before = deepcopy(lesson.content)
    package = _patch(lesson)
    pending = _preview_id(_page(admin_client, _upload(admin_client, {'dialogue.json': package})))
    from app.api.native_lessons import _digest

    review = {'previous_revision': 'a' * 64, 'updated_revision': _digest(before)}
    decision = AnswerDispute(lesson_id=lesson.id, question_id='1', question_revision='b' * 64,
                             grader_version=1, normalized_answer_hash='c' * 64, status='applied',
                             evidence={'question': 'Second row'}, review=review)
    db_session.add(decision)
    db_session.commit()
    result = _page(admin_client, admin_client.post(APPLY, data={'preview_id': pending}))
    assert 'применённое решение спора' in result.get_text()
    db_session.refresh(lesson)
    assert lesson.content == before and decision.review == review and decision.status == 'applied'
    assert _audit_count(admin_user) == 0
