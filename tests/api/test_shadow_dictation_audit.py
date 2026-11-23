"""Synthetic API audit; speech confirmation here is local test data, not production QA."""
# ruff: noqa: F401,F811 -- imported pytest fixtures are discovered by name.
from tests.api.test_quiz_corrections import course, native_app, document, submit, progress_and_attempts


def setup_lesson(course, kind, content):
    from app.utils.db import db
    lesson = course[2]
    lesson.type, lesson.content = kind, content
    db.session.commit()


def test_shadow_has_actionable_instruction_text_and_explicit_confirmation(course):
    setup_lesson(course, 'shadow_reading', {'transcript': 'Hello. I am here.', 'audio_url': '/static/audio/example.mp3'})
    doc = document(course)
    assert doc['assessment'] == 'self_assessed'
    assert not doc['immediate_feedback'] and 'quiz_phase' not in doc
    assert 'вместе с записью' in doc['instruction']
    assert 'без автоматической оценки речи' in doc['instruction']
    assert any('Hello. I am here.' in b['body'] for b in doc['theory'])
    assert submit(course, doc, {'0': ''}).status_code == 400
    result = submit(course, doc, {'0': 'confirmed'})
    assert result.status_code == 200 and result.json['completed']
    assert result.json['score'] is None


def test_full_dictation_typographic_apostrophes_agree_in_check_and_submit(course):
    setup_lesson(course, 'dictation', {'transcript': "I'm here"})
    doc = document(course)
    headers, lesson, client = course[1:4]
    response = client.post(f'/api/native/lessons/{lesson.id}/check', headers=headers,
                          json={'session_token': doc['session_token'], 'question_id': '0', 'answer': 'I’m HERE!'})
    assert response.status_code == 200 and response.json['feedback']['correct']
    result = submit(course, doc, {'0': 'I’m HERE!'})
    assert result.status_code == 200 and result.json['score'] == 100
    assert result.json['completed'] and not result.json.get('correction_pending')


def test_extra_dictation_word_creates_correction_and_preserves_independent_word_accuracy(course):
    setup_lesson(course, 'dictation', {'transcript': 'I am here'})
    first = document(course)
    result = submit(course, first, {'0': 'I am here today'})
    assert result.status_code == 200, result.json
    assert result.json['score'] == 75 and result.json['correction_pending']
    assert result.json['units_correct'] == 3 and result.json['units_total'] == 4
    assert result.json['feedback'][0]['correct'] is False
    correction = document(course)
    assert correction['correction']['first_score'] == 75
    assert correction['correction']['first_units_total'] == 4
    done = submit(course, correction, {'0': 'I AM HERE!'})
    assert done.status_code == 200 and done.json['completed']
    assert done.json['score'] == 75 and done.json['correct_count'] == 1
    _, attempts = progress_and_attempts(course)
    assert len(attempts) == 1


def test_dictation_gap_scores_and_feedback_agree_after_an_extra_word(course):
    setup_lesson(course, 'dictation', {'gap_text': 'I {0} at {1}.',
                                     'gaps': [{'answer': 'am'}, {'answer': 'home'}]})
    first = document(course)
    result = submit(course, first, {'0': 'am extra', '1': 'HOME!'})
    assert result.status_code == 200, result.json
    assert result.json['score'] == 66.67
    assert result.json['units_correct'] == 2 and result.json['units_total'] == 3
    assert [q['correct'] for q in result.json['feedback']] == [False, True]
    assert [q['id'] for q in document(course)['questions']] == ['0']
