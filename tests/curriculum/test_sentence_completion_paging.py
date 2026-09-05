"""Sentence completion: pages of five, level-based hint policy, hidden
generator artefact and mode-based instruction (lesson audit 2026-09-05,
A2 / A6-1 / A6-4 / A7). Owner: using a hint never costs XP.
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
from app.curriculum.routes.lessons import (
    SENTENCE_COMPLETION_PAGE_SIZE,
    _sentence_completion_display_items,
    _sentence_completion_instruction,
)
from tests.conftest import unique_level_code

TEMPLATE = 'app/templates/curriculum/lessons/sentence_completion.html'


def _module(db_session, level_code: str):
    level = CEFRLevel(code=level_code, name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='SC Module', description='d',
                    raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    return module


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _items(n: int, context: str = 'vocab use', mode: str = '') -> list[dict]:
    return [
        {'prompt': f'Prompt {i}', 'answer': f'word{i}', 'prompt_after': 'here.', 'hint': f'w{"•" * 4}',
         'context': context, 'mode': mode}
        for i in range(n)
    ]


def _make_lesson(db_session, module, items, instruction=None) -> Lessons:
    content = {'items': items}
    if instruction is not None:
        content['instruction'] = instruction
    lesson = Lessons(module_id=module.id, number=1, title='SC', type='sentence_completion', content=content)
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _run_paging_js(html: str, item_count: int, after_ready: str = '') -> dict:
    """Run the rendered lesson JS against a minimal DOM and expose pager state."""
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required for the sentence-completion paging regression')
    scripts = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)
    app_script = next((script for script in scripts if 'function _retryGivenUp()' in script), None)
    assert app_script, 'rendered sentence-completion script not found'

    harness = r"""
globalThis.window = globalThis;
window.__moduleUrl = '/learn/';
globalThis.showSaveToast = () => {};
globalThis.alert = () => {};

function makeClassList() {
  const values = new Set();
  return {
    add(...names) { names.forEach((name) => values.add(name)); },
    remove(...names) { names.forEach((name) => values.delete(name)); },
    contains(name) { return values.has(name); },
    toggle(name, force) {
      if (force === undefined ? !values.has(name) : force) values.add(name);
      else values.delete(name);
    }
  };
}
function plainElement() {
  return {
    style: {}, hidden: false, disabled: false, value: '', textContent: '',
    innerHTML: '', className: '', dataset: {}, classList: makeClassList(),
    children: [],
    addEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    focus() {}, select() {}, scrollIntoView() {},
    appendChild(child) { this.children.push(child); return child; },
    querySelector() { return null; }, querySelectorAll() { return []; }
  };
}

const itemCountForHarness = __ITEM_COUNT__;
const inputs = [], feedback = [];
for (let i = 0; i < itemCountForHarness; i++) {
  const input = plainElement();
  input.dataset.index = String(i);
  input.classList.add('sentence-completion-input');
  input.getAttribute = (name) => name === 'data-index' ? String(i) : null;
  input.focus = () => { globalThis.focusedIndex = i; };
  inputs.push(input);
  feedback.push(plainElement());
}

let pagerWired = false;
let pageMutationBeforePagerWired = false;
const pageCountForHarness = Math.max(1, Math.ceil(itemCountForHarness / 5));
const pages = [];
for (let p = 0; p < pageCountForHarness; p++) {
  const page = plainElement();
  page.dataset.page = String(p);
  let hiddenValue = p !== 0;
  Object.defineProperty(page, 'hidden', {
    get() { return hiddenValue; },
    set(value) {
      if (!pagerWired) pageMutationBeforePagerWired = true;
      hiddenValue = value;
    }
  });
  page.querySelector = (selector) => {
    if (selector !== '.sentence-completion-input:not([disabled])') return null;
    const start = p * 5, end = Math.min(itemCountForHarness, start + 5);
    return inputs.slice(start, end).find((input) => !input.disabled) || null;
  };
  pages.push(page);
}

const elements = {};
[
  'sc-prev', 'sc-next', 'sc-page-num', 'sc-pager', 'sc-progress-fill',
  'sc-progress-current', 'sc-progress-label', 'completion-result',
  'result-summary', 'completion-next-area'
].forEach((id) => { elements[id] = plainElement(); });
elements['sc-next'].addEventListener = (event) => {
  if (event === 'click') pagerWired = true;
};
const progressBar = plainElement();
const meta = plainElement();
meta.getAttribute = (name) => name === 'content' ? 'csrf' : null;

const domReady = [];
globalThis.document = {
  addEventListener(event, callback) {
    if (event === 'DOMContentLoaded') domReady.push(callback);
  },
  querySelectorAll(selector) { return selector === '.sc-page' ? pages : []; },
  querySelector(selector) {
    if (selector === 'meta[name="csrf-token"]') return meta;
    if (selector === '.lesson-shell__progress-bar[role="progressbar"]') return progressBar;
    const match = selector.match(/^\.sc-page\[data-page="(\d+)"\]$/);
    return match ? pages[Number(match[1])] : null;
  },
  createElement() { return plainElement(); },
  getElementById(id) {
    if (id.startsWith('answer-')) return inputs[Number(id.slice(7))] || null;
    if (id.startsWith('feedback-')) return feedback[Number(id.slice(9))] || null;
    return elements[id] || null;
  }
};

const fetchUrls = [];
globalThis.fetch = async (url) => {
  fetchUrls.push(String(url));
  return { ok: true, async json() { return {}; } };
};

__APP_SCRIPT__
domReady.forEach((callback) => callback());
__AFTER_READY__
process.stdout.write(JSON.stringify({
  currentPage,
  pageHidden: pages.map((page) => page.hidden),
  pagerHidden: elements['sc-pager'].hidden,
  pagerWired,
  pageMutationBeforePagerWired,
  finalizing: _finalizing,
  submitFetches: fetchUrls.filter((url) => url.endsWith('/submit')).length,
  progressFetches: fetchUrls.filter((url) => url.endsWith('/progress')).length,
  pending: Array.from({length: itemCountForHarness}, (_, i) => itemState[i] || 'pending'),
  enabled: inputs.map((input) => !input.disabled),
  focusedIndex: globalThis.focusedIndex ?? null
}));
"""
    harness = (harness.replace('__ITEM_COUNT__', str(item_count))
               .replace('__APP_SCRIPT__', app_script)
               .replace('__AFTER_READY__', after_ready))
    tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
    tmp.write(harness)
    tmp.close()
    try:
        result = subprocess.run([node, tmp.name], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(tmp.name)


class TestHelpers:

    def test_artefact_context_is_hidden_and_source_untouched(self):
        source = [{'prompt': 'a', 'answer': 'b', 'context': 'vocab use'},
                  {'prompt': 'c', 'answer': 'd', 'context': 'Подберите глагол, который сочетается:'}]
        display = _sentence_completion_display_items(source)
        assert display[0]['context'] == '' and display[1]['context'].startswith('Подберите')
        assert source[0]['context'] == 'vocab use'

    def test_instruction_by_dominant_mode(self):
        assert _sentence_completion_instruction(_items(5), None).startswith('Впишите слово из словаря')
        assert _sentence_completion_instruction(_items(5, mode='collocation'), None).startswith('Подберите слово')
        assert _sentence_completion_instruction(_items(5, mode='transformation'), '  ').startswith('Измените форму')
        mixed = _items(3, mode='collocation') + _items(3, mode='transformation')
        assert _sentence_completion_instruction(mixed, None) == 'Заполните пропуск в каждом предложении.'
        assert _sentence_completion_instruction(_items(5), 'Вставьте форму BE.') == 'Вставьте форму BE.'


class TestRender:

    def _markup(self, html: str) -> str:
        start = html.index('id="completion-items-list"')
        return html[start:html.index('<script', start)]

    def test_thirteen_items_make_three_pages_with_global_indices(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, _module(db_session, unique_level_code()), _items(13))
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/sentence-completion').get_data(as_text=True)
        markup = self._markup(html)
        assert SENTENCE_COMPLETION_PAGE_SIZE == 5
        assert markup.count('class="sc-page"') == 3
        assert re.search(r'data-page="1"[^>]*hidden', markup) and re.search(r'data-page="2"[^>]*hidden', markup)
        assert not re.search(r'data-page="0"[^>]*hidden', markup)
        assert [int(x) for x in re.findall(r'id="answer-(\d+)"', markup)] == list(range(13))
        assert 'id="sc-pager"' in html and 'из 3' in html

    def test_four_items_have_no_pager(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, _module(db_session, unique_level_code()), _items(4))
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/sentence-completion').get_data(as_text=True)
        assert 'id="sc-pager"' not in html and self._markup(html).count('class="sc-page"') == 1

    def test_artefact_context_is_not_rendered_but_real_context_is(self, app, db_session, test_user, client):
        items = _items(2) + _items(1, context='Подберите глагол, который сочетается:')
        lesson = _make_lesson(db_session, _module(db_session, unique_level_code()), items)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/sentence-completion').get_data(as_text=True)
        assert 'vocab use' not in html
        assert 'Подберите глагол, который сочетается:' in html

    def test_derived_instruction_is_shown_when_content_has_none(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, _module(db_session, unique_level_code()), _items(3, mode='transformation'))
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/sentence-completion').get_data(as_text=True)
        assert 'Измените форму слова' in html


class TestHintPolicy:

    def test_a1_sees_the_hint_in_the_placeholder(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, _module(db_session, 'A1'), _items(2))
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/sentence-completion').get_data(as_text=True)
        assert 'placeholder="w••••"' in html
        start = html.index('id="completion-items-list"')
        assert 'sc-hint-btn' not in html[start:html.index('<script', start)]

    def test_b1_gets_a_hint_button_and_a_neutral_placeholder(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, _module(db_session, 'B1'), _items(2))
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/sentence-completion').get_data(as_text=True)
        assert 'placeholder="ответ"' in html and 'placeholder="w••••"' not in html
        assert html.count('class="sc-hint-btn"') == 2
        assert 'data-hint="w••••"' in html

    def test_lesson_content_is_not_mutated(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, _module(db_session, 'C1'), _items(3))
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/sentence-completion')
        db_session.expire_all()
        assert db_session.get(Lessons, lesson.id).content['items'][0]['context'] == 'vocab use'


class TestPagingStateAdversarial:

    def test_reload_opens_first_pending_page_without_finalizing(
        self, app, db_session, test_user, client
    ):
        lesson = _make_lesson(
            db_session, _module(db_session, unique_level_code()), _items(12)
        )
        saved_items = [
            {
                'state': 'pending' if i == 10 else 'correct',
                'attempts': [],
                'value': '' if i == 10 else f'word{i}',
                **({} if i == 10 else {'answer': f'word{i}'}),
            }
            for i in range(12)
        ]
        db_session.add(LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='in_progress',
            data={'items': saved_items},
        ))
        db_session.commit()
        _login(client, test_user)

        html = client.get(
            f'/curriculum/lesson/{lesson.id}/sentence-completion'
        ).get_data(as_text=True)
        state = _run_paging_js(html, item_count=12)

        assert state['currentPage'] == 2
        assert state['pageHidden'] == [True, True, False]
        assert state['pending'][10] == 'pending' and state['enabled'][10]
        assert state['finalizing'] is False and state['submitFetches'] == 0
        # DOMContentLoaded listeners execute in registration order: pager
        # wiring is installed before restore calls showPage().
        assert state['pagerWired'] and not state['pageMutationBeforePagerWired']

    def test_failed_restore_retry_reopens_page_of_first_reset_item(
        self, app, db_session, test_user, client
    ):
        lesson = _make_lesson(
            db_session, _module(db_session, unique_level_code()), _items(12)
        )
        item_results = [
            {
                'prompt': f'Prompt {i}',
                'answer': f'word{i}',
                'user_answer': f'word{i}' if i < 7 or i == 11 else 'wrong',
                'correct': i < 7 or i == 11,
            }
            for i in range(12)
        ]
        db_session.add(LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='in_progress',
            data={
                'item_results': item_results,
                'correct_items': 8,
                'total_items': 12,
                'score': 67,
                'passed': False,
            },
        ))
        db_session.commit()
        _login(client, test_user)

        html = client.get(
            f'/curriculum/lesson/{lesson.id}/sentence-completion'
        ).get_data(as_text=True)
        state = _run_paging_js(html, item_count=12, after_ready='_retryGivenUp();')

        # First wrong item is global index 7, hence page 2 (zero-based page 1).
        assert state['currentPage'] == 1
        assert state['pageHidden'] == [True, False, True]
        assert state['pagerHidden'] is False
        assert state['pending'][7:11] == ['pending'] * 4
        assert all(state['enabled'][7:11])
        assert state['focusedIndex'] == 7
        assert state['finalizing'] is False and state['submitFetches'] == 0
        assert state['progressFetches'] == 1


class TestSource:

    def test_pages_and_hint_are_wired(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            src = f.read()
        assert 'function showPage(' in src and 'function _pageOf(' in src
        assert "closest('.sc-hint-btn')" in src
        assert 'if (_pageOf(i) !== currentPage) showPage(_pageOf(i), false);' in src
        assert 'item.context' in src  # existing conditional block kept
