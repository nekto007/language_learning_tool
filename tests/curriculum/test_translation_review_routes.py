"""End-to-end reference review uses signed confirmation, never a fake score."""
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code

CANONICAL = 'The team studies a different language every month.'
UNKNOWN_VARIANT = 'Every month, a different language is studied by the team.'


@pytest.fixture
def review_lesson(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Translation review', order=1)
    db_session.add(level)
    db_session.flush()
    module = Module(level_id=level.id, number=1, title='Review module')
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(module_id=module.id, number=1, order=1, title='Review translation',
                     type='translation', content_version=1,
                     content={'mode': 'rubric', 'items': [
                         {'russian': 'Команда каждый месяц изучает другой язык.', 'english': CANONICAL,
                          'alternatives': [], 'hint_words': ['team', 'language']},
                     ]})
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
    with patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp', return_value=None) as xp, \
            patch('app.daily_plan.linear.xp.maybe_award_writing_xp', return_value=None), \
            patch('app.daily_plan.challenge.maybe_auto_complete_challenge', return_value=None):
        yield xp


def _check(client, lesson, answer=UNKNOWN_VARIANT, **payload):
    response = client.post(f'/curriculum/api/lesson/{lesson.id}/check-item',
                           json={'index': 0, 'answer': answer, **payload})
    assert response.status_code == 200
    return response.get_json()


def _submit(client, lesson, answer=UNKNOWN_VARIANT, token=None):
    response = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                           json={'answers': [answer], 'review_tokens': [token]})
    assert response.status_code == 200
    return response.get_json()


def test_unknown_variant_is_pending_and_does_not_complete_or_record_zero(
    db_session, test_user, learner_client, review_lesson,
):
    pending = _check(learner_client, review_lesson)
    assert pending['status'] == 'needs_review'
    assert pending['correct'] is None
    assert pending['reference_answer'] == CANONICAL
    result = _submit(learner_client, review_lesson)
    assert result['success'] is False
    assert result['error'] == 'review_required'
    assert result['score'] is None
    progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=review_lesson.id).first()
    assert progress is None or progress.status != 'completed'
    assert db_session.query(LessonAttempt).filter_by(user_id=test_user.id, lesson_id=review_lesson.id).count() == 0


def test_pending_token_cannot_be_used_as_a_final_confirmation(
    db_session, test_user, learner_client, review_lesson,
):
    pending = _check(learner_client, review_lesson)
    result = _submit(learner_client, review_lesson, token=pending['review_token'])
    assert result['success'] is False
    assert result['error'] == 'invalid_review_token'
    assert db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=review_lesson.id).count() == 0


@pytest.mark.parametrize('mode', ['rubric', 'open'])
def test_confirmed_review_completes_without_graded_attempt_or_accuracy(
    db_session, test_user, learner_client, review_lesson, quiet_rewards, mode,
):
    review_lesson.content = {**review_lesson.content, 'mode': mode}
    db_session.commit()
    pending = _check(learner_client, review_lesson)
    confirmed = _check(learner_client, review_lesson,
                       review_token=pending['review_token'], confirm_review=True)
    assert confirmed['status'] == 'self_reviewed'
    assert confirmed['review_token'] != pending['review_token']
    result = _submit(learner_client, review_lesson, token=confirmed['review_token'])
    assert result['success'] is True
    assert result['score'] is None
    assert result['assessment'] == 'self_review'
    assert result['correct_items'] == 0
    assert result['reviewed_items'] == [0]
    progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=review_lesson.id).one()
    assert progress.status == 'completed'
    assert progress.last_score is None
    assert progress.data['assessment'] == 'self_review'
    assert db_session.query(LessonAttempt).filter_by(user_id=test_user.id, lesson_id=review_lesson.id).count() == 0
    assert quiet_rewards.call_args.kwargs['score'] is None


def test_changed_answer_invalidates_confirmation_at_real_endpoint(learner_client, review_lesson):
    pending = _check(learner_client, review_lesson)
    result = _check(learner_client, review_lesson, answer='The team studies every language.',
                    review_token=pending['review_token'], confirm_review=True)
    assert result['success'] is False
    assert result['error'] == 'invalid_review_token'


def test_self_review_retry_preserves_best_score_but_has_no_latest_numeric_grade(
    db_session, test_user, learner_client, review_lesson,
):
    progress = LessonProgress(user_id=test_user.id, lesson_id=review_lesson.id, status='completed',
                              score=80, best_score=80, last_score=80)
    db_session.add(progress)
    db_session.commit()
    pending = _check(learner_client, review_lesson)
    confirmed = _check(learner_client, review_lesson, review_token=pending['review_token'], confirm_review=True)
    result = _submit(learner_client, review_lesson, token=confirmed['review_token'])
    assert result['assessment'] == 'self_review' and result['score'] is None
    db_session.refresh(progress)
    assert progress.best_score == 80 and progress.last_score is None
    assert progress.data['item_results'][0]['user_answer'] == UNKNOWN_VARIANT


def test_open_known_reference_keeps_automatic_grade(db_session, test_user, learner_client, review_lesson):
    review_lesson.content = {**review_lesson.content, 'mode': 'open'}
    db_session.commit()
    checked = _check(learner_client, review_lesson, answer=CANONICAL)
    assert checked['status'] == 'matched'
    result = _submit(learner_client, review_lesson, answer=CANONICAL)
    assert result['passed'] is True
    assert result['score'] == 100
    assert result.get('assessment') != 'self_review'
    assert db_session.query(LessonAttempt).filter_by(user_id=test_user.id, lesson_id=review_lesson.id).count() == 1


def test_guided_mode_keeps_strict_target_practice(learner_client, review_lesson, db_session):
    review_lesson.content = {**review_lesson.content, 'mode': 'guided'}
    db_session.commit()
    result = _check(learner_client, review_lesson, answer='They do not study any languages.')
    assert result['correct'] is False
    assert 'review_token' not in result
    assert 'status' not in result or result['status'] != 'needs_review'


def test_invalid_answer_is_visible_error_without_completion(db_session, learner_client, review_lesson):
    result = _check(learner_client, review_lesson, answer='Только русский текст.')
    assert result['success'] is False
    assert result['error'] == 'invalid_answer'
    assert db_session.query(LessonProgress).filter_by(lesson_id=review_lesson.id).count() == 0
