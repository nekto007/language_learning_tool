"""Contextual vocabulary must survive imports without redefining shared words."""
from copy import deepcopy
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import func

from app.admin.services.curriculum_import_service import (
    CURRICULUM_DICTIONARY_DEFAULTS,
    CURRICULUM_DICTIONARY_EXAMPLES,
    CurriculumImportService,
)
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.card_service import apply_lesson_card_context
from app.curriculum.routes import card_lessons, vocabulary_lessons
from app.words.models import Collection, CollectionWords


def _module(db_session):
    level = db_session.query(CEFRLevel).filter_by(code='B1').first()
    if level is None:
        level = CEFRLevel(code='B1', name='Intermediate', order=3)
        db_session.add(level)
        db_session.flush()
    number = (db_session.query(func.max(Module.number)).filter_by(level_id=level.id).scalar() or 0) + 1
    module = Module(level_id=level.id, number=number, title='Contextual senses')
    db_session.add(module)
    db_session.flush()
    return module


def _word(db_session, english, russian):
    word = db_session.query(CollectionWords).filter_by(english_word=english).first()
    if word is None:
        word = CollectionWords(english_word=english, russian_word=russian, level='A1')
        db_session.add(word)
    else:
        word.russian_word = russian
    db_session.flush()
    return word


@pytest.mark.parametrize('english,context', [
    ('account', 'аккаунт'), ('raise', 'повышение зарплаты'), ('abstract', 'абстрактный'),
])
@pytest.mark.parametrize('renderer', ['embedded', 'dedicated'])
def test_both_vocabulary_renderers_show_authored_sense(
    app, db_session, test_user, english, context, renderer,
):
    canonical = CURRICULUM_DICTIONARY_DEFAULTS[english]
    word = _word(db_session, english, canonical)
    module = _module(db_session)
    lesson = Lessons(module_id=module.id, number=1, order=1, title='Vocabulary', type='vocabulary',
                     content={'vocabulary': [{'english': english, 'russian': context,
                                              'example': f'This sentence uses {english} in context.'}]})
    db_session.add(lesson)
    db_session.flush()
    with app.test_request_context():
        login_user(test_user)
        with patch.object(vocabulary_lessons, 'render_template', side_effect=lambda _name, **values: values), \
                patch.object(vocabulary_lessons, 'get_next_lesson', return_value=None):
            if renderer == 'embedded':
                result = vocabulary_lessons.render_vocabulary_lesson(lesson)
            else:
                result = unwrap(vocabulary_lessons.vocabulary_lesson)(lesson.id)
    assert result['words'][0]['russian'] == context
    assert result['words'][0]['id'] == word.id
    assert word.russian_word == canonical


@pytest.mark.parametrize('payload', [
    {'russian': 'аккаунт'}, {'translation': 'аккаунт'}, {'back': 'аккаунт'},
])
def test_context_aliases_and_dictionary_fallback(payload):
    word = SimpleNamespace(russian_word='счёт')
    assert vocabulary_lessons._lesson_russian(payload, word) == 'аккаунт'
    assert vocabulary_lessons._lesson_russian({'russian': ' '}, word) == 'счёт'
    assert vocabulary_lessons._lesson_russian({}, None) == ''


@pytest.mark.parametrize('english,context', [
    ('account', 'аккаунт'), ('raise', 'повышение зарплаты'), ('abstract', 'абстрактный'),
])
def test_import_keeps_context_and_owner_dictionary_defaults(db_session, test_user, english, context):
    word = _word(db_session, english, context)
    word.sentences = 'An example from an unrelated meaning.'
    source = [{'english': english, 'russian': context, 'example': 'An authored example.'}]
    original = deepcopy(source)
    collection = Collection(name=f'Context {uuid4().hex}', created_by=test_user.id)
    db_session.add(collection)
    db_session.flush()
    CurriculumImportService.process_vocabulary(source, collection, 'C1')
    db_session.flush()
    assert word.russian_word == CURRICULUM_DICTIONARY_DEFAULTS[english]
    assert word.sentences == CURRICULUM_DICTIONARY_EXAMPLES[english]
    assert word.level == 'A1'
    assert source == original


def test_curriculum_reimport_preserves_unrelated_existing_dictionary_sense_and_example(db_session, test_user):
    english = f'shared_{uuid4().hex[:10]}'
    word = _word(db_session, english, 'словарное значение')
    word.sentences = 'An existing dictionary example.'
    collection = Collection(name=f'Context {uuid4().hex}', created_by=test_user.id)
    db_session.add(collection)
    db_session.flush()
    CurriculumImportService.process_vocabulary(
        [{'english': english, 'russian': 'контекстное значение', 'example': 'Another topic example.'}],
        collection, 'C1')
    db_session.flush()
    assert word.russian_word == 'словарное значение'
    assert word.sentences == 'An existing dictionary example.'


def test_import_fills_missing_dictionary_translation(db_session, test_user):
    english = f'empty_{uuid4().hex[:10]}'
    word = _word(db_session, english, None)
    collection = Collection(name=f'Context {uuid4().hex}', created_by=test_user.id)
    db_session.add(collection)
    db_session.flush()
    CurriculumImportService.process_vocabulary([{'english': english, 'russian': 'значение'}], collection, 'B1')
    db_session.flush()
    assert word.russian_word == 'значение'


def test_lesson_flashcard_context_preserves_ids_directions_and_global_payload():
    cards = [
        {'word_id': 1, 'direction_id': 10, 'direction': 'eng-rus', 'front': 'account', 'back': 'счёт',
         'english': 'account', 'interval': 7},
        {'word_id': 1, 'direction_id': 11, 'direction': 'rus-eng', 'front': 'счёт', 'back': 'account',
         'english': 'account', 'interval': 12},
        {'word_id': 2, 'direction_id': 12, 'direction': 'eng-rus', 'front': 'other', 'back': 'другое'},
    ]
    original = deepcopy(cards)
    result = apply_lesson_card_context(cards, {'cards': [
        {'front': 'account', 'back': 'аккаунт', 'example': 'Create an account.',
         'example_translation': 'Создайте аккаунт.'},
    ]})
    assert result[0]['back'] == 'аккаунт'
    assert result[1]['front'] == 'аккаунт'
    assert [row['word_id'] for row in result] == [1, 1, 2]
    assert [row['direction_id'] for row in result] == [10, 11, 12]
    assert result[0]['interval'] == 7
    assert result[1]['interval'] == 12
    assert result[0]['example_en'] == 'Create an account.'
    assert result[2] == cards[2]
    assert cards == original


@pytest.mark.parametrize('renderer', ['embedded', 'dedicated'])
def test_both_card_renderer_paths_apply_authored_translation(app, db_session, test_user, renderer):
    word = _word(db_session, 'account', 'счёт')
    module = _module(db_session)
    lesson = Lessons(module_id=module.id, number=1, order=1, title='Account flashcards', type='card',
                     content={'cards': [{'front': 'account', 'back': 'аккаунт', 'word_id': word.id}]})
    db_session.add(lesson)
    db_session.flush()
    canonical = {'word_id': word.id, 'direction_id': 99, 'direction': 'eng-rus',
                 'english': 'account', 'front': 'account', 'back': 'счёт'}
    with app.test_request_context():
        login_user(test_user)
        with patch.object(card_lessons, 'render_template', side_effect=lambda _name, **values: values), \
                patch.object(card_lessons, '_build_cards_for_words', return_value=[canonical]):
            if renderer == 'embedded':
                result = card_lessons.render_card_lesson(lesson)
            else:
                result = unwrap(card_lessons.card_lesson)(lesson.id)
    assert result['cards_data']['cards'][0]['back'] == 'аккаунт'
    assert result['fc_cards'][0]['back'] == 'аккаунт'
    assert result['fc_cards'][0]['word_id'] == word.id
    assert result['fc_cards'][0]['direction_id'] == 99
    assert word.russian_word == 'счёт'


def test_import_preserves_descriptions_and_unused_final_exercises_without_merging(
    app, db_session, test_user, caplog,
):
    module = _module(db_session)
    canonical_question = {'type': 'multiple_choice', 'question': 'Canonical section?',
                          'options': ['yes', 'no'], 'correct': 'yes'}
    supplementary_question = {'type': 'multiple_choice', 'question': 'Different authored exercise?',
                              'options': ['first', 'second'], 'correct': 'second'}
    source = {'module': {'level': 'B1', 'order': module.number, 'title': module.title, 'lessons': [
        {'number': 1, 'order': 1, 'type': 'translation', 'title': 'Translation',
         'description': 'Передайте смысл, используя слова этого урока.', 'grammar_focus': 'fallback focus',
         'content': {'items': [{'russian': 'Привет.', 'english': 'Hello.'}], 'external_key': 'test:context:translation'}},
        {'number': 2, 'order': 2, 'type': 'final_test', 'title': 'Final test',
         'content': {'test_sections': [{'title': 'Canonical', 'exercises': [canonical_question]}],
                     'exercises': [supplementary_question], 'passing_score': 75,
                     'external_key': 'test:context:final', 'author_note': 'Keep editorial metadata'}},
    ]}}
    with app.test_request_context(), patch.object(CurriculumImportService, '_reset_sequences'):
        login_user(test_user)
        CurriculumImportService.import_curriculum_data(deepcopy(source))
        translation = db_session.query(Lessons).filter_by(module_id=module.id, number=1).one()
        final = db_session.query(Lessons).filter_by(module_id=module.id, number=2).one()
        assert translation.description == source['module']['lessons'][0]['description']
        assert final.content['exercises'] == [supplementary_question]
        assert final.content['test_sections'][0]['exercises'] == [canonical_question]
        assert final.content['author_note'] == 'Keep editorial metadata'
        assert 'sections remain authoritative' in caplog.text
        source['module']['lessons'][0]['description'] = 'Уточнённая авторская инструкция.'
        CurriculumImportService.import_curriculum_data(deepcopy(source))
        assert translation.description == 'Уточнённая авторская инструкция.'


def test_starter_survives_import_and_renders_builder_in_both_template_blocks(app, db_session, test_user, tmp_path):
    module = _module(db_session)
    starter = {'title': 'Представьтесь', 'goal': 'Три фразы',
               'lines': [{'english': 'My name is Anna.', 'russian': 'Меня зовут Анна.'}],
               'builder': {'template': 'My name is {name}. I am from {country}.',
                           'fields': [{'name': 'name', 'label': 'Имя', 'placeholder': 'Anna', 'max_length': 40},
                                      {'name': 'country', 'label': 'Страна', 'placeholder': 'Canada', 'max_length': 60}],
                           'button_label': 'Составить', 'result_title': 'Мои фразы'}}
    source = {'module': {'level': 'B1', 'order': module.number, 'title': module.title, 'lessons': [
        {'order': 1, 'type': 'vocabulary', 'title': 'Starter', 'content': {
            'external_key': 'test:starter:vocabulary', 'starter': starter,
            'vocabulary': [{'english': 'hello', 'russian': 'привет'}],
        }},
    ]}}
    with app.test_request_context(), patch.object(CurriculumImportService, '_reset_sequences'):
        login_user(test_user)
        CurriculumImportService.import_curriculum_data(deepcopy(source))
        lesson = db_session.query(Lessons).filter_by(module_id=module.id, number=1).one()
        assert lesson.content['starter'] == starter
        html = vocabulary_lessons.render_vocabulary_lesson(lesson)
        assert 'id="vocab-starter-form"' in html
        assert "addEventListener('submit'" in html
        assert 'My name is {name}. I am from {country}.' in html
        assert '.textContent = template.replace(' in html
        (tmp_path / 'vocabulary.html').write_text(html)


def test_reordering_preserves_lesson_identity_and_completed_progress(app, db_session, test_user):
    module = _module(db_session)
    lessons = [
        {'order': i, 'type': 'writing_prompt', 'title': f'Practice {i}',
         'content': {'external_key': f'test:reorder:{i}', 'prompt': 'Introduce yourself.', 'min_sentences': 3}}
        for i in range(1, 4)
    ]
    source = {'module': {'level': 'B1', 'order': module.number, 'title': module.title, 'lessons': lessons}}
    with app.test_request_context(), patch.object(CurriculumImportService, '_reset_sequences'):
        login_user(test_user)
        CurriculumImportService.import_curriculum_data(deepcopy(source))
        before = {l.content['external_key']: l.id for l in Lessons.query.filter_by(module_id=module.id)}
        old_last_id = before['test:reorder:3']
        progress = LessonProgress(user_id=test_user.id, lesson_id=old_last_id, status='completed', score=83)
        db_session.add(progress)
        db_session.commit()
        lessons[:] = [lessons[2], lessons[0], lessons[1]]
        for i, lesson in enumerate(lessons, 1):
            lesson['order'] = i
        CurriculumImportService.import_curriculum_data(deepcopy(source))
        after = {l.content['external_key']: l.id for l in Lessons.query.filter_by(module_id=module.id)}
        assert after == before
        assert db_session.get(Lessons, old_last_id).number == 1
        db_session.refresh(progress)
        assert progress.lesson_id == old_last_id and progress.status == 'completed' and progress.score == 83
