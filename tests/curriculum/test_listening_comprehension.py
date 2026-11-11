"""Listening comprehension uses server answers, never checkbox-made accuracy."""
import pytest
from unittest.mock import patch

from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, ListeningAttempt, Module
from tests.conftest import unique_level_code


@pytest.fixture
def listening_lesson(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Listening test', order=1)
    db_session.add(level)
    db_session.flush()
    module = Module(level_id=level.id, number=1, title='Listening comprehension')
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(module_id=module.id, number=1, order=1, type='listening_immersion',
                     title='Understand the conversation', content={
                         'text': 'They decided to postpone the meeting until Friday.',
                         'audio': '[sound:listening_test.mp3]',
                         'comprehension_questions': [
                             {'type': 'multiple_choice', 'question': 'What did they decide?',
                              'options': ['Postpone the meeting.', 'Cancel all meetings.'],
                              'correct': 'Postpone the meeting.',
                              'explanation': 'PRIVATE_EXPLANATION_NOT_FOR_INITIAL_DOM',
                              'evidence': 'PRIVATE_EVIDENCE_NOT_FOR_INITIAL_DOM'},
                             {'type': 'multiple_choice', 'question': 'When will they meet?',
                              'options': ['Monday.', 'Friday.'], 'correct': 'Friday.'},
                         ],
                     })
    db_session.add(lesson)
    db_session.commit()
    return lesson


@pytest.fixture
def learner_client(client, test_user):
    with client.session_transaction() as session:
        session['_user_id'] = str(test_user.id)
        session['_fresh'] = True
    return client


@pytest.fixture(autouse=True)
def quiet_rewards():
    with patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp', return_value=None) as curriculum_xp, \
            patch('app.daily_plan.linear.xp.maybe_award_listening_xp', return_value=None) as listening_xp, \
            patch('app.daily_plan.challenge.maybe_auto_complete_challenge', return_value=None):
        yield curriculum_xp, listening_xp


def _submit(client, lesson, payload):
    return client.post(f'/curriculum/api/lesson/{lesson.id}/submit', json=payload)


def test_questions_render_without_answer_key_explanation_or_evidence(learner_client, listening_lesson):
    response = learner_client.get(f'/curriculum/lesson/{listening_lesson.id}/listening-immersion')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'What did they decide?' in html
    assert 'When will they meet?' in html
    assert 'name="li-answer-0"' in html
    assert 'PRIVATE_EXPLANATION_NOT_FOR_INITIAL_DOM' not in html
    assert 'PRIVATE_EVIDENCE_NOT_FOR_INITIAL_DOM' not in html
    assert 'data-correct=' not in html
    assert 'data-answer=' not in html


@pytest.mark.parametrize('answers', [None, {}, {'0': '0'}])
def test_self_assessment_cannot_bypass_required_questions(
    db_session, test_user, learner_client, listening_lesson, answers,
):
    response = _submit(learner_client, listening_lesson,
                       {'self_assessed': True, 'score': 100, 'answers': answers})
    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False
    assert data['error'] == 'answers_required'
    progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=listening_lesson.id).first()
    assert progress is None or progress.status != 'completed'
    assert db_session.query(ListeningAttempt).filter_by(lesson_id=listening_lesson.id).count() == 0
    assert db_session.query(LessonAttempt).filter_by(lesson_id=listening_lesson.id).count() == 0


@pytest.mark.parametrize('answers,expected_score,expected_correct', [
    ({'0': '0', '1': '1'}, 100, 2),
    ({'0': '1', '1': '1'}, 50, 1),
    ({'0': '1', '1': '0'}, 0, 0),
])
def test_actual_answers_determine_score_and_attempts_not_client_claim(
    db_session, test_user, learner_client, listening_lesson, quiet_rewards,
    answers, expected_score, expected_correct,
):
    response = _submit(learner_client, listening_lesson,
                       {'self_assessed': True, 'score': 100, 'correct_answers': 999, 'answers': answers})
    assert response.status_code == 200
    result = response.get_json()
    assert result['completed'] is True  # Learning policy: attempt all questions, then review mistakes.
    assert result['score'] == expected_score
    assert result['correct_answers'] == expected_correct
    assert result['total_questions'] == 2
    assert result['feedback']['0']['evidence'] == 'PRIVATE_EVIDENCE_NOT_FOR_INITIAL_DOM'
    assert result['feedback']['0']['explanation'] == 'PRIVATE_EXPLANATION_NOT_FOR_INITIAL_DOM'
    progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=listening_lesson.id).one()
    assert progress.status == 'completed'
    assert progress.last_score == expected_score
    attempt = db_session.query(LessonAttempt).filter_by(user_id=test_user.id, lesson_id=listening_lesson.id).one()
    assert attempt.score == expected_score
    assert attempt.passed is (expected_score >= 70)
    assert attempt.correct_answers == expected_correct
    assert attempt.total_questions == 2
    listening_attempt = db_session.query(ListeningAttempt).filter_by(
        user_id=test_user.id, lesson_id=listening_lesson.id).one()
    assert listening_attempt.score == expected_score
    assert quiet_rewards[0].call_args.kwargs['score'] == expected_score
    assert quiet_rewards[1].call_args.kwargs['score'] == expected_score


def test_retry_retains_best_but_records_latest_real_result(db_session, test_user, learner_client, listening_lesson):
    assert _submit(learner_client, listening_lesson, {'answers': {'0': '0', '1': '1'}}).status_code == 200
    assert _submit(learner_client, listening_lesson, {'answers': {'0': '1', '1': '0'}}).status_code == 200
    progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=listening_lesson.id).one()
    assert progress.best_score == 100
    assert progress.last_score == 0
    assert progress.data['score'] == 0
    assert db_session.query(LessonAttempt).filter_by(lesson_id=listening_lesson.id).count() == 2
    assert db_session.query(ListeningAttempt).filter_by(lesson_id=listening_lesson.id).count() == 2


def test_legacy_lesson_without_questions_keeps_checkbox_completion(db_session, learner_client, listening_lesson):
    listening_lesson.content = {'text': 'A legacy dialog.', 'audio': '[sound:legacy.mp3]'}
    db_session.commit()
    response = _submit(learner_client, listening_lesson, {'self_assessed': True})
    assert response.status_code == 200
    assert response.get_json()['completed'] is True
    assert db_session.query(ListeningAttempt).filter_by(lesson_id=listening_lesson.id).count() == 1


def test_saved_result_restores_explanations_and_retry_clears_only_display(
    db_session, test_user, learner_client, listening_lesson, tmp_path,
):
    _submit(learner_client, listening_lesson, {'answers': {'0': '1', '1': '0'}})
    url = f'/curriculum/lesson/{listening_lesson.id}/listening-immersion'
    html = learner_client.get(url).get_data(as_text=True)
    assert 'showListeningResult({' in html
    assert 'PRIVATE_EXPLANATION_NOT_FOR_INITIAL_DOM' in html
    assert 'PRIVATE_EVIDENCE_NOT_FOR_INITIAL_DOM' in html
    assert 'Попытка завершена' in html and 'Попробовать ещё раз' in html
    (tmp_path / 'listening-result.html').write_text(html)

    retry_html = learner_client.get(url + '?retry=true').get_data(as_text=True)
    assert 'showListeningResult({' not in retry_html
    assert 'PRIVATE_EXPLANATION_NOT_FOR_INITIAL_DOM' not in retry_html
    assert 'PRIVATE_EVIDENCE_NOT_FOR_INITIAL_DOM' not in retry_html
    progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=listening_lesson.id).one()
    assert progress.status == 'completed' and progress.last_score == 0
    assert db_session.query(LessonAttempt).filter_by(lesson_id=listening_lesson.id).count() == 1


def test_listening_quiz_type_link_redirects_to_canonical_quiz_preserving_query(
    db_session, learner_client, listening_lesson,
):
    from urllib.parse import parse_qs, urlparse

    listening_lesson.type = 'listening_quiz'
    listening_lesson.content = {'exercises': [
        {'type': 'listening_choice', 'question': 'What is said?', 'options': ['Hello', 'Goodbye'],
         'correct': 'Hello', 'audio': '[sound:greeting.mp3]', 'audio_text': 'Hello'},
    ]}
    db_session.commit()
    url = f'/curriculum/lesson/{listening_lesson.id}/listening_quiz'
    response = learner_client.get(url + '?retry=true&from=linear_plan&tag=a&tag=b')
    assert response.status_code == 302
    location = urlparse(response.location)
    assert location.path == f'/curriculum/lesson/{listening_lesson.id}/quiz'
    assert parse_qs(location.query) == {'retry': ['true'], 'from': ['linear_plan'], 'tag': ['a', 'b']}
    assert learner_client.get(location.path).status_code == 200


def test_listening_quiz_alias_does_not_accept_another_lesson_type(learner_client, listening_lesson):
    response = learner_client.get(f'/curriculum/lesson/{listening_lesson.id}/listening_quiz')
    assert response.status_code == 404


@pytest.mark.parametrize('prompt,options,correct', [
    ('She can dance very well.', ['True', 'False'], 'True'),
    ('The speaker has a leash.', ['True', 'False'], 'False'),
    ('I ___ swim.', ['can', "can't", 'do'], 'can'),
])
def test_listening_choice_displays_the_statement_or_question_above_options(
    db_session, learner_client, listening_lesson, prompt, options, correct,
):
    listening_lesson.type = 'listening_quiz'
    listening_lesson.content = {'exercises': [
        {'type': 'listening_choice', 'question': prompt, 'options': options, 'correct': correct,
         'instruction': 'Прослушайте реплику. Верно ли утверждение?',
         'audio': '[sound:statement.mp3]', 'audio_text': 'PRIVATE_AUDIO_TRANSCRIPT'},
    ]}
    db_session.commit()
    html = learner_client.get(f'/curriculum/lesson/{listening_lesson.id}/quiz').get_data(as_text=True)
    expected = f'<h3 class="question-text">{prompt}</h3>'
    assert expected in html
    assert '<h3 class="question-text">PRIVATE_AUDIO_TRANSCRIPT</h3>' not in html
    assert html.index(expected) < html.index('data-action="play-question-audio"')
