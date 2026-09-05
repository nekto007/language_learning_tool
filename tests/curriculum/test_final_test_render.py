"""Final test render: shuffled options, shuffled matching column, section
dividers, verdict-only mid-test feedback, resume on the first unanswered
question (lesson audit 2026-09-05, A9 / B17 / D-1..D-3).

The source JSON lists the correct option first in 48–70 % of option questions
and the template rendered them in source order; the matching right column was
merely reversed; the flatten dropped section boundaries; the mid-test feedback
revealed answers and explanations (and printed «Ответ не указан» for
listening_choice with the answer at index 0 and for matching); a reload after
answering N rolled the learner back to N.
"""
from __future__ import annotations

import json
import re

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.curriculum.routes.grammar_quiz_lessons import (
    _final_test_display_questions,
    _shuffle_question_options,
)
from tests.conftest import unique_level_code

TEMPLATE = 'app/templates/curriculum/lessons/final_test.html'


@pytest.fixture()
def _module(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='FT Module', description='d',
                    raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    return module


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _content() -> dict:
    mc = [
        {'type': 'multiple_choice', 'question': f'Q{i}', 'options': [f'ans{i}', f'b{i}', f'c{i}', f'd{i}'],
         'correct': f'ans{i}', 'explanation': 'because'}
        for i in range(6)
    ]
    lc = [
        {'type': 'listening_choice', 'question': f'L{i}', 'audio': '[sound:x.mp3]',
         'options': [f'heard{i}', f'x{i}', f'y{i}', f'z{i}'], 'correct': f'heard{i}'}
        for i in range(4)
    ]
    matching = {
        'type': 'matching', 'instruction': 'Соотнесите',
        'pairs': [{'left': 'cat', 'right': 'кот'}, {'left': 'dog', 'right': 'пёс'},
                  {'left': 'cow', 'right': 'корова'}, {'left': 'hen', 'right': 'курица'}],
    }
    return {
        'test_sections': [
            {'title': 'Раздел 1: Vocabulary', 'exercises': mc},
            {'title': 'Listening', 'exercises': lc},
            {'title': 'Раздел 3: Matching', 'exercises': [matching]},
        ],
        'passing_score': 75,
    }


def _make_lesson(db_session, module) -> Lessons:
    lesson = Lessons(module_id=module.id, number=1, title='Final', type='final_test', content=_content())
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _questions_json(html: str) -> list[dict]:
    m = re.search(r'questions: (\[.*?\]),\n\s*totalQuestions', html, re.S)
    assert m, 'finalTestData not found'
    return json.loads(m.group(1))


def _right_column_ids(html: str, question_index: int) -> list[int]:
    block = html.split(f'id="matching-right-{question_index}"', 1)[1].split('</div>', 1)[0]
    return [int(x) for x in re.findall(r'data-pair-id="(\d+)"', block)]


class TestOptionsShuffled:

    def test_answer_is_not_always_first_and_text_is_kept(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/final_test').get_data(as_text=True)
        questions = _questions_json(html)
        option_qs = [q for q in questions if q.get('options')]
        assert len(option_qs) == 10
        # correct stays TEXT (grading compares text) and is still one of the options
        for q in option_qs:
            assert q['correct'] in q['options']
        assert not all(q['options'][0] == q['correct'] for q in option_qs), 'options rendered in source order'

    def test_order_changes_between_renders(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        seen = set()
        for _ in range(6):
            html = client.get(f'/curriculum/lesson/{lesson.id}/final_test').get_data(as_text=True)
            seen.add(tuple(tuple(q['options']) for q in _questions_json(html) if q.get('options')))
        assert len(seen) > 1

    def test_lesson_content_is_not_mutated(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/final_test')
        db_session.expire_all()
        stored = db_session.get(Lessons, lesson.id).content
        for section in stored['test_sections']:
            for q in section['exercises']:
                if q.get('options'):
                    assert q['options'][0] == q['correct'], 'shuffle leaked into lesson.content'
                assert 'right_order' not in q and 'section_label' not in q


class TestShuffleHelper:

    def test_positional_answers_are_remapped(self):
        for _ in range(20):
            q = {'options': ['a', 'b', 'c', 'd'], 'correct_index': 0, 'correct': '2'}
            _shuffle_question_options(q)
            assert q['options'][q['correct_index']] == 'a'
            assert q['options'][int(q['correct'])] == 'c'

    def test_text_and_boolean_answers_are_untouched(self):
        q = {'options': ['a', 'b', 'c'], 'correct': 'b'}
        _shuffle_question_options(q)
        assert q['correct'] == 'b' and sorted(q['options']) == ['a', 'b', 'c']
        tf = {'type': 'true_false', 'correct': True}
        _shuffle_question_options(tf)
        assert tf == {'type': 'true_false', 'correct': True}


class TestMatchingColumnShuffled:

    def test_right_column_is_a_permutation_not_a_reverse(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        orders = set()
        for _ in range(8):
            html = client.get(f'/curriculum/lesson/{lesson.id}/final_test').get_data(as_text=True)
            ids = _right_column_ids(html, 10)
            assert sorted(ids) == [0, 1, 2, 3]
            orders.add(tuple(ids))
        assert orders != {(3, 2, 1, 0)}, 'right column still just reversed'


class TestSectionDividers:

    def test_dividers_and_labels(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/final_test').get_data(as_text=True)
        assert html.count('class="final-test-section-divider"') == 3
        assert 'Раздел 1: Vocabulary' in html
        assert 'Раздел 2: Listening' in html  # auto-prefixed
        assert 'Раздел 3: Matching' in html
        assert html.count('data-section-position="2"') == 4
        assert 'id="current-section"' in html

    def test_flat_content_has_no_dividers(self):
        questions, sections = _final_test_display_questions(
            {'exercises': [{'type': 'true_false', 'question': 'x', 'correct': True}]}, lesson_id=1,
        )
        assert sections == [] and 'section_start' not in questions[0]

    def test_empty_sections_are_skipped_in_numbering(self):
        content = {'test_sections': [
            {'title': 'A', 'exercises': [{'type': 'true_false', 'question': 'x', 'correct': True}]},
            {'title': 'B', 'exercises': []},
            {'title': 'C', 'exercises': [{'type': 'true_false', 'question': 'y', 'correct': False}]},
        ]}
        questions, sections = _final_test_display_questions(content, lesson_id=1)
        assert [s['position'] for s in sections] == [1, 2]
        assert [q['section_position'] for q in questions] == [1, 2]
        assert questions[1]['section_label'] == 'Раздел 3: C'


class TestVerdictOnlyFeedbackSource:

    def _src(self) -> str:
        with open(TEMPLATE, encoding='utf-8') as f:
            return f.read()

    def test_feedback_no_longer_reveals_answers_mid_test(self):
        src = self._src()
        assert 'showFeedback(questionIndex, isCorrect) {' in src
        assert 'showFeedback(questionIndex, isCorrect, ' not in src
        assert '{{ _("Ответ не указан") }}' not in src  # D-2 / D-3 fallback is gone
        assert "correctButton.classList.add('correct')" not in src
        assert 'Правильный ответ и объяснение — на экране результатов.' in src
        assert 'После каждого ответа вы увидите, верен ли он.' in src

    def test_resume_uses_first_unanswered_and_recomputes_tally(self):
        src = self._src()
        assert "if (!this.state.answers[i]) { firstOpen = i; break; }" in src
        assert 'this.state.answers[this.state.currentQuestion] = undefined;' not in src
        assert "this.showFeedback(index, !!saved.correct);" in src
