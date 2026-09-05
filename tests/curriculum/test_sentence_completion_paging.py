"""Sentence completion: pages of five, level-based hint policy, hidden
generator artefact and mode-based instruction (lesson audit 2026-09-05,
A2 / A6-1 / A6-4 / A7). Owner: using a hint never costs XP.
"""
from __future__ import annotations

import re

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
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


class TestSource:

    def test_pages_and_hint_are_wired(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            src = f.read()
        assert 'function showPage(' in src and 'function _pageOf(' in src
        assert "closest('.sc-hint-btn')" in src
        assert 'if (_pageOf(i) !== currentPage) showPage(_pageOf(i), false);' in src
        assert 'item.context' in src  # existing conditional block kept
