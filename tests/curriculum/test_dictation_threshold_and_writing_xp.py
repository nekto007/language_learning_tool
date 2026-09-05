"""Item 7 of the lesson audit (2026-09-05): dictation passes at 75 with
per-word mistakes on the attempt row; writing prompts pay the full base XP.
"""
from __future__ import annotations

from unittest.mock import patch

from app.curriculum.constants import PASSING_SCORE_DICTATION, get_lesson_passing_score
from app.curriculum.grading import grade_dictation
from app.curriculum.models import LessonAttempt, LessonProgress
from tests.curriculum.test_dictation_lesson import _login, _make_dictation_lesson
from tests.curriculum.test_writing_prompt import _make_writing_lesson


class TestDictationThreshold:

    def test_threshold_is_75(self):
        assert PASSING_SCORE_DICTATION == 75
        assert get_lesson_passing_score(type('L', (), {'type': 'dictation', 'content': {}})()) == 75

    def test_one_miss_in_four_passes_two_do_not(self):
        assert grade_dictation('the cat sat here', 'the cat sat on')['passed'] is True   # 3/4 = 75
        assert grade_dictation('the cat ran here', 'the cat sat on')['passed'] is False  # 2/4 = 50
        assert grade_dictation('the cat sat on a', 'the cat sat on the')['passed'] is True  # 4/5 = 80

    def test_submit_with_one_miss_completes_and_records_mistakes(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript='the cat sat on')
        _login(client, test_user)
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                           json={'user_text': 'the cat sat here', 'replay_count': 0, 'hint_chars': 0, 'lesson_type': 'dictation'})
        data = resp.get_json()
        assert data['passed'] is True and data['score'] == 75
        assert data['mistakes'] == [{'word': 'on', 'user_word': 'here'}]
        progress = LessonProgress.query.filter_by(user_id=test_user.id, lesson_id=lesson.id).first()
        assert progress.status == 'completed'
        attempt = LessonAttempt.query.filter_by(user_id=test_user.id, lesson_id=lesson.id).order_by(LessonAttempt.id.desc()).first()
        assert attempt is not None
        assert attempt.mistakes == [{'word': 'on', 'user_word': 'here'}]
        assert attempt.correct_answers == 3 and attempt.total_questions == 4

    def test_attempt_limit_cap_stays_below_the_threshold(self, app, db_session, test_user, client):
        """A revealed word must not complete the lesson at 75 either."""
        lesson = _make_dictation_lesson(db_session, transcript='Hello world')
        _login(client, test_user)
        for _ in range(3):
            client.post(f'/curriculum/api/lesson/{lesson.id}/dictation-word',
                        json={'index': 0, 'answer': 'Nope'}, content_type='application/json')
        data = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                           json={'user_text': 'Hello wrong', 'replay_count': 0, 'hint_chars': 0, 'lesson_type': 'dictation'}).get_json()
        assert data['passed'] is False and data['failed_by_attempt_limit'] is True
        assert data['score'] < PASSING_SCORE_DICTATION
        progress = LessonProgress.query.filter_by(user_id=test_user.id, lesson_id=lesson.id).first()
        assert progress.status != 'completed'


class TestWritingPromptXp:

    def test_completion_pays_the_full_base_not_the_checklist_share(self, app, db_session, test_user, client):
        from app.curriculum.routes.lessons import _DEFAULT_WRITING_CHECKLIST
        lesson = _make_writing_lesson(db_session, min_words=5)
        _login(client, test_user)
        with patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp', return_value=None) as xp, \
             patch('app.daily_plan.linear.xp.maybe_award_writing_xp', return_value=None):
            resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                               json={'response_text': ' '.join(['word'] * 40), 'checklist_completed': True,
                                     'checked_items': _DEFAULT_WRITING_CHECKLIST[:2], 'lesson_type': 'writing_prompt'},
                               content_type='application/json')
        assert resp.status_code == 200 and resp.get_json().get('completed') is True
        assert xp.call_args.kwargs['score'] is None  # honor system → «not graded» → full base
        progress = LessonProgress.query.filter_by(user_id=test_user.id, lesson_id=lesson.id).first()
        assert progress.status == 'completed'
