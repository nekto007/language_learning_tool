"""Translation: contraction-aware grading, key hint words, pages of five
(lesson audit 2026-09-05, A3 / A7 / A2, owner decisions: expand contractions
on both sides, accept both readings of 'd, 2-3 key hint words).
"""
from __future__ import annotations

import re

import pytest

from app.curriculum.grading import (
    _contraction_variants,
    _strict_text_match,
    grade_translation_multi,
    process_quiz_submission,
)
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.curriculum.routes.lessons import (
    TRANSLATION_HINT_WORDS_MAX,
    TRANSLATION_PAGE_SIZE,
    _translation_key_hint_words,
)
from tests.conftest import unique_level_code

TEMPLATE = 'app/templates/curriculum/lessons/translation.html'


class TestContractions:

    @pytest.mark.parametrize('user, canonical', [
        ("He's my distant relative", 'He is my distant relative.'),
        ('He is my distant relative', "He's my distant relative."),
        ("I'm from Russia", 'I am from Russia.'),
        ("We'll meet tomorrow", 'We will meet tomorrow.'),
        ("They've finished", 'They have finished.'),
        ("I don't know", 'I do not know.'),
        ("She isn't here", 'She is not here.'),
        ("I can't swim", 'I cannot swim.'),
        ('I can not swim', "I can't swim."),
        ("We won't go", 'We will not go.'),
        ("You're right", 'You are right.'),
        ("Let's go", 'Let us go.'),
        ('He’s tired', 'He is tired.'),  # curly apostrophe
    ])
    def test_contractions_match_both_ways(self, user, canonical):
        assert _strict_text_match(user, [canonical])

    def test_d_accepts_both_readings(self):
        assert _strict_text_match("He'd like tea", ['He would like tea.'])
        assert _strict_text_match("He'd finished", ['He had finished.'])
        assert _strict_text_match('He would like tea', ["He'd like tea."])
        assert sorted(_contraction_variants("he'd go")) == ['he had go', 'he would go']

    @pytest.mark.parametrize('user, canonical', [
        ('I like apple', 'I like apples.'),          # no multi-word typo tolerance
        ('He is my relative', 'He is a relative.'),  # articles stay strict
        ("He's", 'His'),
        ('apples like I', 'I like apples'),
    ])
    def test_everything_else_stays_strict(self, user, canonical):
        assert not _strict_text_match(user, [canonical])

    def test_multi_item_grader_and_final_test_translation_benefit(self):
        items = [{'english': 'He is a doctor.', 'alternatives': []}, {'english': "I don't like tea.", 'alternatives': []}]
        result = grade_translation_multi(["He's a doctor", 'I do not like tea'], items)
        assert result['correct_items'] == 2 and result['score'] == 100
        ft = process_quiz_submission(
            [{'type': 'translation', 'question': 'Переведите', 'correct': 'My father is a doctor.'}],
            {'0': "My father's a doctor"},
        )
        assert ft['feedback']['0']['status'] == 'correct'


class TestKeyHintWords:

    def test_drops_function_words_and_keeps_the_longest(self):
        words = ['He', 'is', 'a', 'distant', 'relative', 'of', 'mine.']
        picked = _translation_key_hint_words(words, 'He is a distant relative of mine.')
        assert picked == ['distant', 'relative']
        assert len(picked) <= TRANSLATION_HINT_WORDS_MAX

    def test_at_most_three_longest_content_words(self):
        words = 'Tickets for this fashion show sold out within minutes.'.split()
        picked = _translation_key_hint_words(words, ' '.join(words))
        assert len(picked) == 3
        assert set(picked) <= {'Tickets', 'fashion', 'minutes', 'within'}
        assert 'for' not in picked and 'this' not in picked

    def test_no_authored_hint_words_means_no_hints(self):
        """The «open» mode relies on the section being absent."""
        assert _translation_key_hint_words([], 'Tickets sold out within minutes.') == []

    def test_short_a1_answer_is_not_handed_out_whole(self):
        picked = _translation_key_hint_words(['Hello!', 'Nice', 'to', 'meet', 'you.'], 'Hello! Nice to meet you.')
        assert 1 <= len(picked) <= 3
        assert 'you' not in picked and 'to' not in picked


@pytest.fixture()
def _module(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='TR Module', description='d',
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
        {'russian': f'Предложение {i}.', 'english': f'He is a distant relative of mine number {i}.',
         'hint_words': ['He', 'is', 'a', 'distant', 'relative', 'of', 'mine', 'number', f'{i}.'],
         'alternatives': []}
        for i in range(n)
    ]


class TestRender:

    def test_twelve_items_make_three_pages_and_chips_are_trimmed(self, app, db_session, _module, test_user, client):
        lesson = Lessons(module_id=_module.id, number=1, title='TR', type='translation', content={'items': _items(12)})
        db_session.add(lesson)
        db_session.commit()
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/translation').get_data(as_text=True)
        start = html.index('id="tr-items"')
        markup = html[start:html.index('<script', start)]
        assert TRANSLATION_PAGE_SIZE == 5
        assert markup.count('class="tr-page"') == 3
        assert [int(x) for x in re.findall(r'id="tr-answer-(\d+)"', markup)] == list(range(12))
        assert re.search(r'data-page="1"[^>]*hidden', markup) and not re.search(r'data-page="0"[^>]*hidden', markup)
        assert 'id="tr-pager"' in html and 'из 3' in html
        chips = re.findall(r'translation-chip--static">([^<]*)</span>', markup)
        assert len(chips) == 12 * 3
        assert set(chips) <= {'distant', 'relative', 'number'}
        db_session.expire_all()
        assert db_session.get(Lessons, lesson.id).content['items'][0]['hint_words'][0] == 'He'

    def test_source_is_wired(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            src = f.read()
        assert 'function showPage(' in src and 'function _showFirstPendingPage(' in src
        assert "_softRetryGivenUp(); _showFirstPendingPage();" in src
