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


@pytest.fixture(autouse=True)
def isolated_final_projection(monkeypatch):
    # Renderer/projection coverage; actual plan ordering is tested separately.
    monkeypatch.setattr('app.api.native_lessons._guard_plan', lambda *args: 'curriculum')


def _practice_document(client, lesson):
    response = client.get(f'/curriculum/api/lesson/{lesson.id}/practice')
    assert response.status_code == 200, response.json
    return response.json['lesson']


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
        sess['_user_id'] = user.get_id()
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
        page = client.get(f'/curriculum/lesson/{lesson.id}/final_test', follow_redirects=True)
        assert 'guided-practice.js' in page.text and 'finalTestData' not in page.text
        questions = _practice_document(client, lesson)['questions']
        option_qs = [q for q in questions if q.get('input') == 'choice']
        assert len(option_qs) == 10
        for index, q in enumerate(option_qs):
            expected = f'ans{index}' if index < 6 else f'heard{index - 6}'
            assert expected in [option['label'] for option in q['options']]
            assert not {'correct', 'correct_answer', 'answer', 'explanation'} & q.keys()
        assert any(q['options'][0]['value'] != '0' for q in option_qs), 'options rendered in source order'

    def test_source_ids_and_shuffled_order_survive_reloading(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        seen = set()
        for _ in range(6):
            questions = _practice_document(client, lesson)['questions']
            seen.add(tuple(tuple((o['value'], o['label']) for o in q['options']) for q in questions))
        assert len(seen) == 1  # A restored draft retains stable transport IDs.

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

    def test_right_column_preserves_a_stable_permutation_and_pair_labels(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        orders = set()
        for _ in range(8):
            question = _practice_document(client, lesson)['questions'][10]
            ids = [int(option['value']) for option in question['options']]
            assert sorted(ids) == [0, 1, 2, 3]
            assert {o['value']: o['label'] for o in question['options']} == {'0': 'кот', '1': 'пёс', '2': 'корова', '3': 'курица'}
            orders.add(tuple(ids))
        assert len(orders) == 1


class TestSectionDividers:

    def test_dividers_and_labels(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module)
        _login(client, test_user)
        sections = [q['section'] for q in _practice_document(client, lesson)['questions']]
        assert sections == ['Раздел 1: Vocabulary'] * 6 + ['Listening'] * 4 + ['Раздел 3: Matching']

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

    def test_resume_drops_snapshot_verdicts_and_retains_editable_learner_input(
        self, app, db_session, _module, test_user, client
    ):
        from app.api.native_lessons import _digest, _signer

        lesson = _make_lesson(db_session, _module)

        def sign_origin(saved_answers: list[dict]) -> str:
            return _signer().dumps({
                'purpose': 'legacy_final_draft', 'user': test_user.id, 'lesson': lesson.id,
                'lesson_type': 'final_test', 'revision': _digest(lesson.content),
                'answers_digest': _digest(saved_answers),
            })

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

        assert 'resume_answers' not in _practice_document(client, lesson)
        progress.data = {**progress.data, '_native_legacy_draft_origin': sign_origin(answers)}
        db_session.commit()

        document = _practice_document(client, lesson)
        assert document['resume_answers'] == {'0': '0', '2': '0'}
        assert 'correct_answers' not in document and 'feedback' not in document
        all_answers = [{'value': q['options'][0]['label'], 'correct': True}
                       for q in document['questions'][:10]]
        all_answers.append({'value': 'display', 'correct': True, 'pairs': [
            {'left': 'cat', 'right': 'пёс', 'correct': True}, {'left': 'dog', 'right': 'кот', 'correct': True},
            {'left': 'cow', 'right': 'курица', 'correct': True}, {'left': 'hen', 'right': 'корова', 'correct': True}]})
        progress.data = {
            'current_question': 0,
            'answers': all_answers,
            'correct_answers': -50,
            'total_questions': 11,
            '_native_legacy_draft_origin': progress.data['_native_legacy_draft_origin'],
        }
        db_session.commit()

        assert 'resume_answers' not in _practice_document(client, lesson)
        progress.data = {**progress.data, '_native_legacy_draft_origin': sign_origin(all_answers)}
        db_session.commit()

        restored = _practice_document(client, lesson)
        assert len(restored['resume_answers']) == 11
        assert json.loads(restored['resume_answers']['10']) == {'0': '1', '1': '0', '2': '3', '3': '2'}
        assert 'correct_answers' not in restored and not restored['immediate_feedback']


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
