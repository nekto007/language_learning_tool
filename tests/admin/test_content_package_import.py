"""Publication must keep the learner's lesson identity and the admin's transaction."""
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.admin.services.content_package_import import apply_package, preview_package
from app.admin.services.curriculum_import_service import CurriculumImportService
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module


def _entry(name: str, data: dict) -> dict:
    return {'name': name + '.json', 'data': data}


def _final(key: str) -> dict:
    return {'external_key': key, 'test_sections': [
        {'title': 'Одежда', 'exercises': [
            {'type': 'translation', 'question': 'Рубашка', 'instruction': 'Переведи.',
             'correct': 'shirt', 'acceptable_answers': ['shirt', 'a shirt']},
            {'type': 'multiple_choice', 'question': 'Одна куртка рядом', 'options': ['this', 'these'], 'correct': 'this'},
            {'type': 'true_false', 'question': 'These shoes is blue.', 'correct': False}]}],
        'exercises': [], 'passing_score': 75, 'total_points': 100, 'xp_reward': 200}


def _module(number: int, key: str) -> dict:
    return {'module': {'level': 'A1', 'number': number, 'title': 'Одежда',
                       'lessons': [{'order': 1, 'title': 'Итог', 'type': 'final_test', 'content': _final(key)}]}}


@pytest.fixture
def stored(db_session) -> Lessons:
    level = CEFRLevel.query.filter_by(code='A1').first()
    if not level:
        level = CEFRLevel(code='A1', name='Beginner')
        db_session.add(level)
    module = Module(level=level, number=8819, title='Одежда')
    lesson = Lessons(module=module, number=18, order=18, title='Итог', type='final_test',
                     content={**_final(uuid4().hex), 'editor_note': 'keep'})
    db_session.add(lesson)
    db_session.flush()
    return lesson


def test_standalone_keeps_content_and_progress(db_session, stored: Lessons, test_user) -> None:
    key = stored.content['external_key']
    progress = LessonProgress(lesson_id=stored.id, user_id=test_user.id, status='completed', score=88)
    db_session.add(progress)
    db_session.flush()
    doc = _final(key)
    doc['test_sections'][0]['exercises'][0]['question'] = 'Слово «рубашка»'
    entries = [_entry('last', doc)]
    before = deepcopy(stored.content)
    preview = preview_package(entries)
    assert preview[0]['kind'] == 'final_test' and preview[0]['count'] == 3
    assert preview[0]['operation'] == 'update'
    assert stored.content == before
    original_id = stored.id
    with patch.object(db_session, 'commit', side_effect=AssertionError('premature commit')):
        apply_package(entries, preview)
        apply_package(entries, preview_package(entries))
    db_session.expire_all()
    assert stored.id == original_id
    assert stored.content == {**doc, 'editor_note': 'keep'}
    assert (progress.lesson_id, progress.score, progress.status) == (original_id, 88, 'completed')


@pytest.mark.parametrize('change', ['answer', 'content', 'metadata'])
def test_preview_rejects_changed_source_or_target(db_session, stored: Lessons, change: str) -> None:
    entries = [_entry('final', _final(stored.content['external_key']))]
    preview = preview_package(entries)
    if change == 'answer':
        entries[0]['data']['test_sections'][0]['exercises'][0]['correct'] = 'other'
    elif change == 'content':
        stored.content = {**stored.content, 'editor_note': 'newer'}
    else:
        stored.title = 'Поправка в админке'
    db_session.flush()
    before = deepcopy(stored.content)
    with pytest.raises(ValueError, match='изменилось'):
        apply_package(entries, preview)
    assert stored.content == before


def test_new_module_repeat_and_outer_rollback(db_session) -> None:
    entries = [_entry('module', _module(8820, uuid4().hex))]
    initial = preview_package(entries)
    assert initial[0]['kind'] == 'module' and initial[0]['count'] == 1
    assert initial[0]['operation'] == 'create'
    with patch.object(CurriculumImportService, '_reset_sequences', side_effect=AssertionError('sequence reset')):
        with db_session.begin_nested() as outer:
            apply_package(entries, initial)
            first = Module.query.filter_by(number=8820).one()
            lesson_id = first.lessons[0].id
            assert first.lessons[0].content['test_sections'] == entries[0]['data']['module']['lessons'][0]['content']['test_sections']
            with pytest.raises(ValueError, match='изменилось'):
                apply_package(entries, initial)
            apply_package(entries, preview_package(entries))
            assert [row.id for row in first.lessons] == [lesson_id]
            outer.rollback()
    assert Module.query.filter_by(number=8820).count() == 0


def test_late_failure_rolls_back_every_entry(db_session) -> None:
    entries = [_entry('one', _module(8821, uuid4().hex)), _entry('two', _module(8822, uuid4().hex))]
    preview = preview_package(entries)
    original = CurriculumImportService.import_curriculum_data

    def fail_late(data: dict, *, commit: bool) -> dict:
        result = original(data, commit=commit)
        if data['module']['number'] == 8822:
            raise ValueError('fixture failure')
        return result

    with patch.object(CurriculumImportService, 'import_curriculum_data', side_effect=fail_late):
        with pytest.raises(ValueError, match='fixture failure'):
            apply_package(entries, preview)
    assert Module.query.filter(Module.number.in_([8821, 8822])).count() == 0


def test_overlap_ambiguous_and_missing_identity(db_session, stored: Lessons) -> None:
    key = stored.content['external_key']
    final = _entry('test', _final(key))
    module = _entry('module', _module(stored.module.number, key))
    with pytest.raises(ValueError, match='в одном пакете'):
        preview_package([final, module])
    with pytest.raises(ValueError, match='ровно на один'):
        preview_package([_entry('unknown', _final('missing-' + uuid4().hex))])
    db_session.add(Lessons(module_id=stored.module_id, number=19, order=19, title='Копия',
                           type='final_test', content=_final(key)))
    db_session.flush()
    with pytest.raises(ValueError, match='ровно на один'):
        preview_package([final])


def test_protects_unrelated_lesson_on_reimport(db_session, stored: Lessons) -> None:
    doc = _module(stored.module.number, uuid4().hex)
    row = doc['module']['lessons'][0]
    row.update(order=stored.number, title='Другое занятие')
    with pytest.raises(ValueError, match='другим уроком'):
        preview_package([_entry('replace', doc)])


def test_distinct_modules_cannot_claim_the_same_final_key(db_session, stored: Lessons) -> None:
    key = uuid4().hex
    with pytest.raises(ValueError, match='разных модулей'):
        preview_package([_entry('one', _module(8840, key)), _entry('two', _module(8841, key))])
    foreign = _module(8840, stored.content['external_key'])
    with pytest.raises(ValueError, match='другом модуле'):
        preview_package([_entry('foreign', foreign)])
    foreign['module']['lessons'][0].update(type='quiz', content={
        'external_key': stored.content['external_key'],
        'exercises': [{'type': 'multiple_choice', 'question': 'Pick one', 'options': ['a', 'b'], 'correct': 'a'}],
    })
    with pytest.raises(ValueError, match='другом модуле'):
        preview_package([_entry('foreign-quiz', foreign)])


def test_legacy_final_can_gain_stable_key_in_own_module(db_session, stored: Lessons) -> None:
    key = stored.content['external_key']
    original_id = stored.id
    stored.content = {k: v for k, v in stored.content.items() if k != 'external_key'}
    db_session.flush()
    entries = [_entry('source', _module(stored.module.number, key))]
    preview = preview_package(entries)
    assert preview[0]['operation'] == 'update'
    apply_package(entries, preview)
    db_session.refresh(stored)
    assert stored.id == original_id and stored.content['external_key'] == key
    assert len(stored.module.lessons) == 1


@pytest.mark.parametrize('data', [
    {}, {'module': []}, {'module': {'level': 'A1', 'title': 'M', 'order': 1, 'lessons': []}},
    {'module': {'level': 'A1', 'title': 'M', 'order': True, 'lessons': [{}]}},
    {'external_key': 'test', 'test_sections': []},
    {'external_key': 'test', 'test_sections': [{'exercises': [{}]}]},
    {'external_key': 'test', 'test_sections': [{'exercises': [None]}]},
    {'external_key': 'test', 'exercises': [{'type': 'multiple_choice', 'question': '?', 'options': ['a', 'b'], 'correct': 'z'}]},
    {'external_key': 'test', 'exercises': [{'type': 'bad_type', 'question': '?', 'correct': 'a'}]},
])
def test_malformed_rejected_before_publish(db_session, data: dict) -> None:
    with pytest.raises(ValueError):
        preview_package([_entry('bad', data)])


@pytest.mark.parametrize('field', ['sections', 'questions'])
def test_module_preserves_final_and_quiz_question_formats(db_session, field: str) -> None:
    doc = _module(8823, uuid4().hex)
    final = doc['module']['lessons'][0]['content']
    sections = final.pop('test_sections')
    del final['exercises']
    final[field] = sections if field == 'sections' else sections[0]['exercises']
    final['pass_score'] = final.pop('passing_score')
    final['author_note'] = 'сохранить'
    questions = [dict(type='multiple_choice', question='Год?', options=['2000', '1990'], correct='1990')]
    doc['module']['lessons'].append({'order': 2, 'type': 'quiz', 'title': 'Даты',
                                    'content': {'questions': questions, 'xp_reward': 12, 'hint': 'год'}})
    entries = [_entry('module', doc)]
    apply_package(entries, preview_package(entries))
    written = Module.query.filter_by(number=8823).one()
    final_result, quiz_result = sorted(written.lessons, key=lambda lesson: lesson.number)
    assert final_result.content[field] == final[field]
    assert final_result.content['author_note'] == 'сохранить'
    assert final_result.content['pass_score'] == 75
    if field == 'questions':
        assert 'exercises' not in final_result.content
    assert quiz_result.content == doc['module']['lessons'][1]['content']


@pytest.mark.parametrize('competing_level', ['A1', 'B1'])
def test_concurrent_creation_with_one_key(app, competing_level: str) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.utils.db import db

    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Requires independent PostgreSQL transactions')
    number = 100_000 + uuid4().int % 100_000_000
    existing_levels = {row.code for row in CEFRLevel.query.all()}
    entries = [_entry('parallel', _module(number, uuid4().hex))]
    other_entries = deepcopy(entries)
    other_entries[0]['data']['module']['level'] = competing_level
    jobs = [(batch, preview_package(batch)) for batch in (entries, other_entries)]
    barrier = Barrier(2)

    def publish(batch: list[dict], preview: list[dict]) -> str:
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                apply_package(batch, preview)
            except ValueError as error:
                db.session.rollback()
                reason = 'изменилось' if competing_level == 'A1' else 'другом модуле'
                if reason not in str(error):
                    raise
                return 'stale'
            db.session.commit()
            return 'published'

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(publish, *job) for job in jobs]
            assert sorted(future.result(timeout=20) for future in results) == ['published', 'stale']
        module = Module.query.filter_by(number=number).one()
        assert len(module.lessons) == 1
    finally:
        db.session.rollback()
        module = Module.query.filter_by(number=number).one_or_none()
        if module:
            level = module.level
            db.session.delete(module)
            db.session.flush()
            if level.code not in existing_levels and not Module.query.filter_by(level_id=level.id).count():
                db.session.delete(level)
            db.session.commit()
