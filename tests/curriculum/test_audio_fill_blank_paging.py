"""Audio fill-blank: shuffled options and paged items (lesson audit 2026-09-05, A9/B9).

The source JSON lists the correct option first in 1 656/1 656 items and the
template rendered them in source order, so the lesson could be passed with
«always the first button». Twenty items also sat on one page under a single
master clip. Options are now reshuffled on every render (the owner's call:
a stable order could be memorised) and items are grouped into pages of five
that keep their global indices.
"""
from __future__ import annotations

import re

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.curriculum.routes.lessons import AFB_PAGE_SIZE, _afb_display_items
from tests.conftest import unique_level_code


@pytest.fixture()
def _module(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='AFB Module', description='d',
                    raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    return module


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _items(n: int) -> list[dict]:
    return [
        {'text_with_gap': f'Sentence {i} has a ___ here.', 'answer': f'ans{i}',
         'options': [f'ans{i}', f'd{i}a', f'd{i}b', f'd{i}c']}
        for i in range(n)
    ]


def _make_lesson(db_session, module, n: int) -> Lessons:
    lesson = Lessons(module_id=module.id, number=1, title='afb', type='audio_fill_blank',
                     content={'audio_url': '/audio/afb.mp3', 'items': _items(n)})
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _lesson_markup(html: str) -> str:
    """The items section only — base.html carries <script> tags in <head>."""
    start = html.index('id="afb-items"')
    return html[start:html.index('</section>', start)]


def _rendered_options(html: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for m in re.finditer(r'id="afb-options-(\d+)"(.*?)</div>', html, re.S):
        out[int(m.group(1))] = re.findall(r'data-option="([^"]*)"', m.group(2))
    return out


class TestOptionsAreShuffled:

    def test_first_option_is_not_always_the_answer(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 12)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/audio-fill-blank').get_data(as_text=True)
        rendered = _rendered_options(html)
        assert len(rendered) == 12
        first_is_answer = [opts[0] == f'ans{i}' for i, opts in rendered.items()]
        # (1/4)^12 ≈ 6e-8 chance of a false failure.
        assert not all(first_is_answer), 'options rendered in source order — answer first everywhere'
        for i, opts in rendered.items():
            assert sorted(opts) == sorted([f'ans{i}', f'd{i}a', f'd{i}b', f'd{i}c'])

    def test_lesson_row_is_not_mutated_by_rendering(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 6)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/audio-fill-blank')
        db_session.expire_all()
        stored = db_session.get(Lessons, lesson.id).content['items']
        for i, item in enumerate(stored):
            assert item['options'][0] == f'ans{i}', 'shuffle leaked into lesson.content'

    def test_order_changes_between_renders(self, app, db_session, _module, test_user, client):
        """The owner asked for a fresh order on every load, not a stable one."""
        lesson = _make_lesson(db_session, _module, 12)
        _login(client, test_user)
        orders = set()
        for _ in range(6):
            html = client.get(f'/curriculum/lesson/{lesson.id}/audio-fill-blank').get_data(as_text=True)
            orders.add(tuple(tuple(v) for _, v in sorted(_rendered_options(html).items())))
        assert len(orders) > 1


class TestDisplayItemsHelper:

    def test_copies_and_shuffles_without_touching_source(self):
        source = _items(8)
        snapshot = [list(it['options']) for it in source]
        display = _afb_display_items(source)
        assert [it['options'] for it in source] == snapshot
        assert len(display) == 8
        assert all(sorted(d['options']) == sorted(s) for d, s in zip(display, snapshot))
        assert any(d['options'] != s for d, s in zip(display, snapshot))

    def test_free_text_and_single_option_items_pass_through(self):
        display = _afb_display_items([
            {'text_with_gap': 'a ___', 'answer': 'x'},
            {'text_with_gap': 'b ___', 'answer': 'y', 'options': ['y']},
            'garbage',
        ])
        assert display == [
            {'text_with_gap': 'a ___', 'answer': 'x'},
            {'text_with_gap': 'b ___', 'answer': 'y', 'options': ['y']},
        ]


class TestItemsArePaged:

    def test_twelve_items_make_three_pages_with_global_indices(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 12)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/audio-fill-blank').get_data(as_text=True)
        markup = _lesson_markup(html)
        assert AFB_PAGE_SIZE == 5
        assert markup.count('class="afb-page"') == 3
        assert re.search(r'data-page="1"[^>]*hidden', markup)
        assert re.search(r'data-page="2"[^>]*hidden', markup)
        assert not re.search(r'data-page="0"[^>]*hidden', markup)
        # Items keep their global order and indices inside the pages.
        assert [int(x) for x in re.findall(r'id="afb-item-(\d+)"', markup)] == list(range(12))
        assert 'id="afb-pager"' in markup
        assert 'из 3' in markup
        assert 'afb-master-audio--sticky' in html  # the player card sits above the items

    def test_short_lesson_has_one_page_and_no_pager(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 4)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/audio-fill-blank').get_data(as_text=True)
        markup = _lesson_markup(html)
        assert markup.count('class="afb-page"') == 1
        assert 'id="afb-pager"' not in markup
        assert 'afb-master-audio--sticky' not in html

    def test_submit_still_grades_by_global_index(self, app, db_session, _module, test_user, client):
        """Paging is a view: the answers list stays aligned with content.items."""
        lesson = _make_lesson(db_session, _module, 7)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/audio-fill-blank')
        answers = [f'ans{i}' for i in range(7)]
        answers[6] = 'wrong'
        resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                           json={'answers': answers, 'lesson_type': 'audio_fill_blank', 'replay_count': 0})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['correct_items'] == 6 and data['total_items'] == 7
        assert data['item_results'][6]['correct'] is False

    def test_completed_restore_then_retry_reload_preserves_global_indices(
        self, app, db_session, _module, test_user, client
    ):
        """A completed replay expands pages; retry survives reload without reindexing."""
        lesson = _make_lesson(db_session, _module, 11)
        _login(client, test_user)
        url = f'/curriculum/lesson/{lesson.id}/audio-fill-blank'

        client.get(url)
        completed = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={
                'answers': [f'ans{i}' for i in range(11)],
                'lesson_type': 'audio_fill_blank',
                'replay_count': 0,
            },
        ).get_json()
        assert completed['passed'] is True

        completed_html = client.get(url).get_data(as_text=True)
        assert 'function _restoreCompleted()' in completed_html
        assert '_showAllPages();' in completed_html
        assert "page.hidden = false" in completed_html
        assert "pager.hidden = true" in completed_html

        # The retry flag lives in the session until submission.  A plain reload
        # must therefore remain a fresh paged attempt, not replay completion.
        client.get(f'{url}?retry=true')
        retry_html = client.get(url).get_data(as_text=True)
        assert 'function _restoreCompleted()' not in retry_html
        markup = _lesson_markup(retry_html)

        item_indices = [
            int(x) for x in re.findall(
                r'<article class="lesson-shell__card afb-item"[^>]*data-index="(\d+)"',
                markup,
                re.S,
            )
        ]
        option_indices = [
            int(x) for x in re.findall(
                r'class="option-btn afb-option-btn"[^>]*data-index="(\d+)"',
                markup,
                re.S,
            )
        ]
        assert item_indices == list(range(11))
        assert set(option_indices) == set(range(11))
        assert all(option_indices.count(i) == 4 for i in range(11))
        assert re.search(r'data-page="1"[^>]*hidden', markup)
        assert re.search(r'data-page="2"[^>]*hidden', markup)

        retry_answers = [f'ans{i}' for i in range(11)]
        retry_answers[8] = 'wrong-on-page-two'
        retried = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={
                'answers': retry_answers,
                'lesson_type': 'audio_fill_blank',
                'replay_count': 0,
            },
        ).get_json()
        assert retried['total_items'] == 11
        assert retried['item_results'][8]['correct'] is False
        assert all(
            result['correct'] is (idx != 8)
            for idx, result in enumerate(retried['item_results'])
        )
