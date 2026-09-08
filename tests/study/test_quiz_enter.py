"""Execute real quiz handlers: submit once, then Enter advances one question."""
from pathlib import Path
import shutil
import subprocess

import pytest


TEMPLATE = Path('app/templates/study/quiz.html').read_text(encoding='utf-8')


def function_source(start, end):
    return TEMPLATE[TEMPLATE.index(start):TEMPLATE.index(end)]


HANDLERS = '\n'.join([
    function_source('        function setupFillBlank(', '        function startQuestionTimer('),
    function_source('        async function submitAnswer(', '        async function completeQuiz('),
])

HARNESS = """
const assert = require('node:assert/strict');
const element = () => ({style: {display: 'none', setProperty() {}},
    classList: {add() {}, remove() {}}, setAttribute() {}, focus() {},
    querySelectorAll() { return []; }});
const submitAnswerBtn = element(), nextBtn = element(), fillBlankInput = element();
const multipleChoiceContainer = element(), fillBlankContainer = element();
const feedbackContainer = element(), feedbackText = element(), correctAnswer = element();
const correctCounter = element(), incorrectCounter = element();
const hintText = element(), hintBtn = element();
let answerSubmitted = false, selectedOption = null, timer = null, timeRemaining = 20;
let currentQuestionIndex = 0;
const sessionId = 42, csrfToken = 'test', MAX_RETRY_ATTEMPTS = 2;
const sessionStats = {total: 0, correct: 0, incorrect: 0};
const incorrectQuestions = [];
const questions = [
    {id: 'q1', word_id: 1, type: 'fill_blank', answer: 'torrent'},
    {id: 'q2', word_id: 2, type: 'fill_blank', answer: 'sopping'},
];
let requests = [], saved = 0, shown = [];
global.fetch = (url, options) => new Promise((resolve, reject) => {
    requests.push({url, payload: JSON.parse(options.body), resolve, reject});
});
global.setTimeout = () => 1;
function saveQuizState() { saved++; }
function showQuestion(index) {
    shown.push(index); currentQuestionIndex = index;
    resetQuestionState(); setupFillBlank(questions[index]);
}
function enter(repeat = false) {
    let prevented = false;
    fillBlankInput.onkeydown.call(fillBlankInput, {
        key: 'Enter', repeat, preventDefault() { prevented = true; }
    });
    assert.equal(prevented, true);
}
async function settle(index = 0) {
    requests[index].resolve({json: async () => ({success: true})});
    for (let i = 0; i < 10; i++) await Promise.resolve();
}
"""


@pytest.mark.parametrize('answer', ['torrent', 'wrong'])
def test_enter_checks_once_then_advances(answer):
    scenario = """
    resetQuestionState(); setupFillBlank(questions[0]);
    fillBlankInput.value = ANSWER;
    enter();
    for (let i = 0; i < 20; i++) { enter(); submitAnswer(); }
    assert.equal(sessionStats.total, 1);
    assert.equal(requests.length, 1);
    assert.equal(sessionStats.correct, ANSWER === 'torrent' ? 1 : 0);
    assert.equal(sessionStats.incorrect, ANSWER === 'torrent' ? 0 : 1);
    assert.equal(incorrectQuestions.length, ANSWER === 'torrent' ? 0 : 1);
    assert.equal(fillBlankInput.readOnly, true);
    assert.deepEqual(shown, []); // still saving: Enter must not advance
    await settle();
    enter(true); // a held key cannot skip a question when the response arrives
    assert.deepEqual(shown, []);
    enter();
    assert.deepEqual(shown, [1]);
    assert.equal(sessionStats.total, 1);
    assert.equal(fillBlankInput.readOnly, false);
    assert.equal(fillBlankInput.value, '');
    enter(); nextQuestion(); // empty next answer and duplicate next click
    assert.deepEqual(shown, [1]);
    assert.equal(requests.length, 1);
    fillBlankInput.value = 'sopping'; enter();
    assert.equal(sessionStats.total, 2);
    assert.equal(requests.length, 2);
    await settle(1);
    """.replace('ANSWER', repr(answer))
    run_node(scenario)


def test_empty_answer_and_key_repeat_do_not_submit():
    run_node("""
    resetQuestionState(); setupFillBlank(questions[0]);
    fillBlankInput.value = '   '; enter();
    fillBlankInput.value = 'torrent'; enter(true);
    assert.equal(requests.length, 0);
    assert.equal(sessionStats.total, 0);
    """)


def test_shared_lock_also_covers_multiple_choice_and_timeout():
    run_node("""
    resetQuestionState();
    questions[0] = {id: 'q1', type: 'multiple_choice', options: ['a', 'b'], answer: 'a'};
    selectedOption = '0';
    submitAnswer(); selectedOption = '1';
    for (let i = 0; i < 20; i++) submitAnswer();
    assert.equal(requests.length, 1);
    assert.equal(sessionStats.correct, 1);
    assert.equal(sessionStats.incorrect, 0);
    await settle();
    submitAnswer();
    assert.equal(sessionStats.total, 1);
    """)


def run_node(scenario):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for quiz keyboard regression tests')
    script = HARNESS + HANDLERS + '\n(async () => {\n' + scenario + (
        '\n})().catch(error => {console.error(error); process.exitCode = 1;});'
    )
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
