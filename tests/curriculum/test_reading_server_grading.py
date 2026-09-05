"""Reading lesson: server-graded comprehension (lesson audit 2026-09-05, A10 + A9 + B6).

Before: the client computed ``comprehension_results.score`` and both the
progress endpoint and the two text-lesson POST branches trusted it — an empty
JSON gave 100 and the full 15 XP; the answer key sat in the DOM
(``data-correct``); options rendered in source order; matching questions
rendered as a text input expecting «false».
Owner decisions: every question must be answered when the text has any; the
score never gates completion, it only scales XP; a text without questions
completes with ``score=None`` for XP.
"""
from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code


@pytest.fixture()
def _module(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='RD Module', description='d',
                    raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    return module


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


QUESTIONS = [
    {'type': 'multiple_choice', 'question': 'Where is Emma from?', 'options': ['Australia', 'Canada', 'Spain', 'Peru'],
     'correct': 'Australia', 'explanation': 'She says so.'},
    {'type': 'true_false', 'question': 'Emma is from Canada.', 'correct': False, 'explanation': 'Australia.'},
    {'type': 'fill_blank', 'question': 'Emma is from ___.', 'correct': 'Australia', 'explanation': ''},
    {'type': 'ordering', 'question': '', 'instruction': 'Restore the sentence', 'words': ['I', 'like', 'tea', '.'],
     'correct': 'I like tea.'},
    {'type': 'matching', 'question': '', 'instruction': 'Соотнесите', 'correct': False,
     'pairs': [{'english': 'cat', 'russian': 'кот'}, {'english': 'dog', 'russian': 'пёс'}, {'english': 'cow', 'russian': 'корова'}]},
]


def _make_lesson(db_session, module, questions=None) -> Lessons:
    content = {'title': 'Meeting', 'text': 'Hi! My name is Emma. I am from Australia.'}
    if questions is not None:
        content['exercises'] = questions
    lesson = Lessons(module_id=module.id, number=1, title='Reading', type='reading', content=content)
    db_session.add(lesson)
    db_session.commit()
    return lesson


ALL_CORRECT = {'0': 'Australia', '1': 'false', '2': 'Australia', '3': 'I like tea .',
               '4': [{'left': 'cat', 'right': 'кот'}, {'left': 'dog', 'right': 'пёс'}, {'left': 'cow', 'right': 'корова'}]}


def _progress(db_session, user_id, lesson_id):
    db_session.expire_all()
    return LessonProgress.query.filter_by(user_id=user_id, lesson_id=lesson_id).first()


class TestSubmitIsGradedServerSide:

    def test_all_correct_scores_100_and_completes(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                           json={'lesson_type': 'reading', 'answers': ALL_CORRECT, 'reading_time': 120})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data['success'] is True and data['completed'] is True
        assert data['score'] == 100 and data['correct_answers'] == 5 and data['total_questions'] == 5
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress.status == 'completed' and progress.score == 100
        assert progress.data['reading_time'] == 120
        assert progress.data['reading_answers']['4']['correct'] is True

    def test_client_score_is_ignored_and_a_low_score_still_completes(self, app, db_session, _module, test_user, client):
        """Owner: the score never gates completion — it only scales XP."""
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        answers = dict(ALL_CORRECT, **{'0': 'Peru', '1': 'true', '2': 'Spain', '3': 'tea like I .'})
        with patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp', return_value=None) as xp:
            resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                               json={'lesson_type': 'reading', 'answers': answers, 'score': 100,
                                     'comprehension_results': {'score': 100}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['score'] == 20 and data['correct_answers'] == 1
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress.status == 'completed'
        assert progress.score == 20
        assert xp.call_args.kwargs['score'] == 20  # XP scaled by the SERVER score

    def test_missing_answers_are_rejected(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                           json={'lesson_type': 'reading', 'answers': {'0': 'Australia', '1': ''}})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error'] == 'answers_required' and data['unanswered'] == [1, 2, 3, 4]
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress is None or progress.status != 'completed'

    def test_text_without_questions_completes_with_xp_score_none(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, questions=None)
        _login(client, test_user)
        with patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp', return_value=None) as xp:
            resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                               json={'lesson_type': 'reading', 'answers': {}, 'reading_time': 40})
        assert resp.status_code == 200 and resp.get_json()['score'] == 100
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress.status == 'completed' and progress.score == 100
        assert xp.call_args.kwargs['score'] is None  # «not graded» → full base, not «100 %»

    def test_legacy_text_route_post_uses_the_same_grader(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        resp = client.post(f'/curriculum/lesson/{lesson.id}/text',
                           json={'answers': dict(ALL_CORRECT, **{'0': 'Peru'}), 'comprehension_results': {'score': 100}})
        assert resp.status_code == 200
        assert resp.get_json()['score'] == 80
        resp = client.post(f'/curriculum/lesson/{lesson.id}/text', json={'answers': {}})
        assert resp.status_code == 400 and resp.get_json()['error'] == 'answers_required'


class TestProgressEndpointCannotCompleteAReading:

    def test_forged_completion_is_stripped(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/progress',
                           json={'status': 'completed', 'score': 100,
                                 'comprehension_results': {'score': 100, 'total': 5, 'correct': 5}})
        assert resp.status_code == 200
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress.status != 'completed' and not progress.score

    def test_answer_snapshot_is_still_saved(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/progress',
                           json={'data': {'reading_answers': {'0': {'value': 'Peru', 'type': 'fill_blank', 'correct': False}}}})
        assert resp.status_code == 200
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress.data['reading_answers']['0']['value'] == 'Peru'


class TestPerQuestionCheck:

    def _check(self, client, lesson, index, answer):
        return client.post(f'/curriculum/api/lesson/{lesson.id}/check-item', json={'index': index, 'answer': answer})

    def test_each_type_is_graded_and_revealed(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        assert self._check(client, lesson, 0, 'Australia').get_json()['correct'] is True
        wrong = self._check(client, lesson, 0, 'Peru').get_json()
        assert wrong['correct'] is False and wrong['answer'] == 'Australia' and wrong['explanation'] == 'She says so.'
        tf = self._check(client, lesson, 1, 'true').get_json()
        assert tf['correct'] is False and tf['answer'] is False
        assert self._check(client, lesson, 2, 'australia').get_json()['correct'] is True
        assert self._check(client, lesson, 3, 'I like tea .').get_json()['correct'] is True
        assert self._check(client, lesson, 3, 'tea I like .').get_json()['correct'] is False
        pairs = [{'left': 'cat', 'right': 'кот'}, {'left': 'dog', 'right': 'корова'}, {'left': 'cow', 'right': 'пёс'}]
        m = self._check(client, lesson, 4, pairs).get_json()
        assert m['correct'] is False
        assert {(p['left'], p['right']) for p in m['answer_pairs']} == {('cat', 'кот'), ('dog', 'пёс'), ('cow', 'корова')}
        assert self._check(client, lesson, 4, ALL_CORRECT['4']).get_json()['correct'] is True

    def test_bad_index_and_empty_answer(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        assert self._check(client, lesson, 99, 'x').status_code == 400
        assert self._check(client, lesson, 0, '   ').status_code == 400


class TestRender:

    def test_answer_key_is_not_in_the_dom_and_options_are_shuffled(self, app, db_session, _module, test_user, client):
        many = [
            {'type': 'multiple_choice', 'question': f'Q{i}', 'options': [f'ans{i}', f'b{i}', f'c{i}', f'd{i}'], 'correct': f'ans{i}'}
            for i in range(10)
        ]
        lesson = _make_lesson(db_session, _module, many)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/text').get_data(as_text=True)
        assert 'data-correct=' not in html and 'data-explanation=' not in html
        blocks = re.findall(r'data-question-index="(\d+)" data-question-type="multiple_choice"(.*?)</div>\s*<div class="answer-feedback"', html, re.S)
        assert len(blocks) == 10
        firsts = []
        for idx, body in blocks:
            options = re.findall(r'data-option="([^"]+)"', body)
            assert sorted(options) == sorted([f'ans{idx}', f'b{idx}', f'c{idx}', f'd{idx}'])
            firsts.append(options[0] == f'ans{idx}')
        assert not all(firsts), 'options rendered in source order'

    def test_lesson_content_is_not_mutated_by_rendering(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        for _ in range(3):
            client.get(f'/curriculum/lesson/{lesson.id}/text')
        db_session.expire_all()
        stored = db_session.get(Lessons, lesson.id).content['exercises']
        assert stored[0]['options'] == ['Australia', 'Canada', 'Spain', 'Peru']
        assert 'right_order' not in stored[4]

    def test_matching_renders_as_a_pair_widget(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, QUESTIONS)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/text').get_data(as_text=True)
        assert 'id="rd-match-4"' in html
        assert html.count('data-action="match-left"') == 3 and html.count('data-action="match-right"') == 3
        right = html.split('aria-label="Перевод"', 1)[1].split('</div>', 1)[0]
        assert sorted(int(x) for x in re.findall(r'data-pair-id="(\d+)"', right)) == [0, 1, 2]
        # no free-text input for the matching question
        block = html.split('data-question-index="4"', 1)[1].split('<div class="answer-feedback"', 1)[0]
        assert 'answer-input' not in block

    def test_completion_flow_source(self):
        with open('app/templates/curriculum/lessons/text.html', encoding='utf-8') as f:
            src = f.read()
        assert "'/check-item'" in src
        assert "lesson_type: 'reading'" in src and 'collectReadingAnswers()' in src
        assert 'READING_PASS_THRESHOLD' not in src
        assert 'canComplete = hasQuestions ? allAnswered : hasScrolledToBottom' in src
