"""Language support helps understand tasks without changing answers or grades."""
import json
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.curriculum.language_support import language_support_mode, localized_option, question_translation
from app.curriculum.models import CEFRLevel, Lessons, Module


def _lesson(db_session, code, kind, content):
    level = db_session.query(CEFRLevel).filter_by(code=code).first()
    if level is None:
        level = CEFRLevel(code=code, name=code, order=1)
        db_session.add(level)
        db_session.flush()
    module = Module(level_id=level.id, number=981, title='Language support ' + uuid4().hex)
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(module_id=module.id, number=1, order=1, type=kind, title='Support test', content=content)
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_only_explicit_question_translations_can_be_used_as_question_support():
    assert question_translation({'audio_translation': 'Ответ', 'translation': 'Ответ',
                                 'transcript': 'Answer', 'audio_text': 'Answer'}) == ''
    assert question_translation({'question_ru': '  Вопрос?  '}) == 'Вопрос?'
    lesson = SimpleNamespace(module=None)
    assert language_support_mode(lesson) == 'off'
    assert localized_option('False', lesson) == 'False'


@pytest.mark.parametrize('code,mode', [('A1', 'inline'), ('A2', 'toggle'), ('B1', 'off'), ('B2', 'off'), ('C1', 'off')])
def test_quiz_support_preserves_canonical_options_and_keeps_audio_meaning_for_feedback(
    db_session, client, test_user, code, mode, tmp_path,
):
    question = {'type': 'listening_choice', 'question': 'The speaker has a leash.',
                'question_ru': 'У говорящего есть поводок.', 'prompt_role': 'question',
                'options': ['True', 'False'], 'correct': 'False', 'audio': '[sound:leash.mp3]',
                'audio_text': "I haven't got a leash.", 'audio_translation': 'У меня нет поводка.'}
    lesson = _lesson(db_session, code, 'listening_quiz', {'exercises': [question]})
    _login(client, test_user)
    response = client.get(f'/curriculum/lesson/{lesson.id}/quiz')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    card = re.search(r'id="question-0"(.*?)id="feedback-0"', html, re.S).group(1)
    assert 'У меня нет поводка.' not in card
    if mode == 'off':
        assert 'У говорящего есть поводок.' not in html
    else:
        assert 'У говорящего есть поводок.' in card
        assert 'Неверно / False' in card and 'Верно / True' in card
        assert ('<details class="quiz-question-translation">' in card) is (mode == 'toggle')
    payload = json.loads(re.search(r'questions: (.*),  // Options already shuffled', html).group(1))
    assert set(payload[0]['options']) == {'True', 'False'}
    from app.curriculum.grading import process_quiz_submission
    assert process_quiz_submission(payload, {'0': 'False'})['score'] == 100
    assert 'data-text="False"' in card and 'data-text="True"' in card
    # Rendering is presentation-only: it cannot redefine the persisted source.
    db_session.refresh(lesson)
    assert lesson.content['exercises'][0] == question
    (tmp_path / f'quiz-{code}.html').write_text(html)


def test_an_audio_utterance_is_not_shown_as_the_pre_answer_question(db_session, client, test_user):
    lesson = _lesson(db_session, 'A1', 'listening_quiz', {'exercises': [
        {'type': 'listening_choice', 'question': 'I am a teacher.', 'question_ru': 'Что вы услышали?',
         'prompt_role': 'audio', 'audio': '[sound:teacher.mp3]', 'audio_text': 'I am a teacher.',
         'audio_translation': 'Я учитель.', 'options': ['Я учитель.', 'Я студент.'], 'correct': 'Я учитель.'},
    ]})
    _login(client, test_user)
    html = client.get(f'/curriculum/lesson/{lesson.id}/quiz').get_data(as_text=True)
    card = re.search(r'id="question-0"(.*?)id="feedback-0"', html, re.S).group(1)
    assert '<h3 class="question-text">Что вы услышали?</h3>' in card
    assert '<h3 class="question-text">I am a teacher.</h3>' not in card


@pytest.mark.parametrize('code', ['A1', 'A2', 'B1'])
def test_reading_question_support_and_existing_line_translation_toggle(db_session, client, test_user, code):
    lesson = _lesson(db_session, code, 'reading', {
        'text': {'lines': [{'text': 'Hello, Anna.', 'translation': 'Привет, Анна.'}]},
        'exercises': [{'type': 'multiple_choice', 'question': 'Who is greeted?',
                       'question_ru': 'С кем здороваются?', 'options': ['Anna', 'Emma'], 'correct': 'Anna'}],
    })
    _login(client, test_user)
    response = client.get(f'/curriculum/lesson/{lesson.id}/text')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    if code == 'B1':
        assert 'С кем здороваются?' not in html
    else:
        assert 'id="reading-translations-toggle-all"' in html
        assert 'С кем здороваются?' in html
        assert ('<details class="reading-question-translation">' in html) is (code == 'A2')


@pytest.mark.parametrize('code', ['A1', 'A2'])
def test_final_test_preserves_authored_question_support_without_translating_the_answer(
    db_session, client, test_user, code,
):
    lesson = _lesson(db_session, code, 'final_test', {'exercises': [
        {'type': 'multiple_choice', 'question': 'Which word means a job?',
         'question_ru': 'Какое слово обозначает профессию?',
         'options': ['teacher', 'table', 'window'], 'correct': 'teacher'},
    ]})
    _login(client, test_user)
    response = client.get(f'/curriculum/lesson/{lesson.id}/final_test')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Какое слово обозначает профессию?' in html
    assert ('<details class="final-test-question-translation">' in html) is (code == 'A2')
    assert '>teacher<' in html
