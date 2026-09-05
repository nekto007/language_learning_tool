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
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
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


def _run_resume_js(html: str, total: int) -> dict:
    """Execute the rendered app against a tiny DOM and return its resume state."""
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required for the final-test resume regression')
    scripts = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)
    app_script = next((s for s in scripts if 'window.FinalTestApp = {' in s), None)
    assert app_script, 'rendered FinalTestApp script not found'

    harness = f"""
globalThis.window = globalThis;
window.location = {{ href: '', search: '' }};
window.matchMedia = () => ({{ matches: false }});
globalThis.CSS = {{ escape: (value) => String(value) }};
globalThis.alert = () => {{}};

function classList() {{
  return {{ add() {{}}, remove() {{}}, toggle() {{}} }};
}}
function plainElement() {{
  return {{
    style: {{}}, hidden: false, disabled: false, value: '', textContent: '',
    innerHTML: '', className: '', classList: classList(), dataset: {{}},
    addEventListener() {{}}, setAttribute() {{}}, focus() {{}}, scrollIntoView() {{}},
    querySelectorAll() {{ return []; }}, querySelector() {{ return null; }}
  }};
}}

const startScreen = plainElement();
const testScreen = plainElement();
const progressBar = plainElement();
const currentNum = plainElement();
const currentSection = plainElement();
const cards = [];
const feedback = [];
for (let i = 0; i < {total}; i++) {{
  const answerControl = plainElement();
  const nextButton = plainElement();
  nextButton.className = 'quiz-next-btn-full';
  const icon = plainElement();
  const text = plainElement();
  const buttonText = plainElement();
  const fb = plainElement();
  fb.querySelector = (selector) => selector === '.feedback-icon' ? icon
    : selector === '.feedback-text' ? text
    : selector === '.btn-text' ? buttonText : null;
  feedback.push(fb);

  const card = plainElement();
  card.answerControl = answerControl;
  card.nextButton = nextButton;
  card.dataset = {{ sectionLabel: '', sectionPosition: '' }};
  card.querySelectorAll = (selector) => {{
    if (selector === '.answer-option') return [answerControl];
    if (selector === 'input, textarea, select') return [];
    if (selector === 'button[type="button"]') return [answerControl, nextButton];
    if (selector === 'button, input, textarea, select') return [answerControl, nextButton];
    return [];
  }};
  card.querySelector = (selector) => selector === '.quiz-next-btn-full' ? nextButton : null;
  cards.push(card);
}}

const domReady = [];
globalThis.document = {{
  addEventListener(event, callback) {{
    if (event === 'DOMContentLoaded') domReady.push(callback);
  }},
  querySelectorAll(selector) {{
    if (selector === '.question-card') return cards;
    return [];
  }},
  querySelector() {{ return null; }},
  createElement() {{ return plainElement(); }},
  getElementById(id) {{
    if (id === 'start-screen') return startScreen;
    if (id === 'test-screen') return testScreen;
    if (id === 'test-progress-bar') return progressBar;
    if (id === 'current-num') return currentNum;
    if (id === 'current-section') return currentSection;
    if (id.startsWith('question-')) return cards[Number(id.slice(9))];
    if (id.startsWith('feedback-')) return feedback[Number(id.slice(9))];
    return plainElement();
  }}
}};

{app_script}
domReady.forEach((callback) => callback());
const idx = FinalTestApp.state.currentQuestion;
process.stdout.write(JSON.stringify({{
  started: FinalTestApp.state.started,
  startHidden: startScreen.style.display === 'none',
  testVisible: testScreen.style.display === 'block',
  currentQuestion: idx,
  correctCount: FinalTestApp.state.correctCount,
  answerLocked: cards[idx].answerControl.disabled,
  nextEnabled: !cards[idx].nextButton.disabled,
  nextText: feedback[idx].querySelector('.btn-text').textContent
}}));
"""
    tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
    tmp.write(harness)
    tmp.close()
    try:
        result = subprocess.run([node, tmp.name], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(tmp.name)


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
        # auto-prefix follows the position among non-empty sections (review note)
        assert questions[1]['section_label'] == 'Раздел 2: C'
        assert [s['label'] for s in sections] == ['Раздел 1: A', 'Раздел 2: C']


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


class TestResumeAdversarial:

    def test_lies_in_snapshot_and_all_answered_last_question_is_locked(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(db_session, _module)
        answers = [
            {'value': 'ans0', 'text': 'ans0', 'correct': True},
            {'value': 'wrong', 'text': 'wrong', 'correct': False},
            {'value': 'ans2', 'text': 'ans2', 'correct': True},
        ]
        progress = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='in_progress',
            data={
                'current_question': 0,
                'answers': answers,
                'correct_answers': 999,
                'total_questions': 11,
            },
        )
        db_session.add(progress)
        db_session.commit()
        _login(client, test_user)

        html = client.get(f'/curriculum/lesson/{lesson.id}/final_test').get_data(as_text=True)
        resumed = _run_resume_js(html, total=11)
        assert resumed['started'] and resumed['startHidden'] and resumed['testVisible']
        assert resumed['currentQuestion'] == 3
        assert resumed['correctCount'] == 2
        assert resumed['answerLocked'] is False

        all_answers = [
            {'value': f'ans{i}', 'text': f'ans{i}', 'correct': i % 3 != 0}
            for i in range(11)
        ]
        progress.data = {
            'current_question': 0,
            'answers': all_answers,
            'correct_answers': -50,
            'total_questions': 11,
        }
        db_session.commit()

        html = client.get(f'/curriculum/lesson/{lesson.id}/final_test').get_data(as_text=True)
        completed_answers = _run_resume_js(html, total=11)
        assert completed_answers['started']
        assert completed_answers['currentQuestion'] == 10
        assert completed_answers['correctCount'] == 7
        assert completed_answers['answerLocked'] is True
        assert completed_answers['nextEnabled'] is True
        assert completed_answers['nextText'] == 'Показать результаты'


class TestProgressEndpointCannotCompleteAFinalTest:
    """Review of item 2 (Codex): final_test was missing from _SERVER_GRADED_TYPES,
    so a bare POST to /api/lesson/<id>/progress closed the module test past the
    grader and the attempt limit."""

    def test_forged_completion_is_stripped(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/progress',
                           json={'status': 'completed', 'score': 100})
        assert resp.status_code == 200
        db_session.expire_all()
        progress = LessonProgress.query.filter_by(user_id=test_user.id, lesson_id=lesson.id).first()
        assert progress is not None
        assert progress.status != 'completed'
        assert not progress.score

    def test_in_progress_snapshot_is_still_saved(self, app, db_session, _module, test_user, client):
        """saveProgress() from the test page keeps working — only completion is gated."""
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        snapshot = {'current_question': 2, 'answers': [{'value': 'ans0', 'text': 'ans0', 'correct': True}],
                    'correct_answers': 1, 'total_questions': 11}
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/progress',
                           json={'status': 'in_progress', 'data': snapshot})
        assert resp.status_code == 200
        db_session.expire_all()
        progress = LessonProgress.query.filter_by(user_id=test_user.id, lesson_id=lesson.id).first()
        assert progress.status == 'in_progress'
        assert progress.data['current_question'] == 2
        assert progress.data['answers'][0]['correct'] is True
