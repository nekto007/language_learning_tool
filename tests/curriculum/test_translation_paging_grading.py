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
            [{'type': 'translation', 'question': 'Переведите', 'correct': 'He is a doctor.'}],
            {'0': "He's a doctor"},  # noun + 's stays possessive (review), pronoun + 's is the contraction
        )
        assert ft['feedback']['0']['status'] == 'correct'

    def test_possessive_s_does_not_alias_is_in_translation_or_final_test(self):
        """A noun possessive is not a contraction merely because ``'s`` fits."""
        user = "Google's history"
        canonical = 'Google is history.'
        assert not _strict_text_match(user, [canonical])
        standalone = grade_translation_multi(
            [user], [{'english': canonical, 'alternatives': []}]
        )
        assert standalone['correct_items'] == 0
        final_test = process_quiz_submission(
            [{'type': 'translation', 'question': 'Переведите', 'correct': canonical}],
            {'0': user},
        )
        assert final_test['feedback']['0']['status'] == 'incorrect'

    def test_each_ambiguous_contraction_expands_independently(self):
        assert _strict_text_match(
            "He'd said she'd leave.",
            ['He had said she would leave.'],
        )

    def test_s_also_has_the_has_reading(self):
        assert _strict_text_match(
            "She's finished her work.",
            ['She has finished her work.'],
        )


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
        assert picked == ['Hello', 'Nice', 'meet']
        assert 'you' not in picked and 'to' not in picked

    def test_one_word_answer_has_no_answer_shaped_hint(self):
        assert _translation_key_hint_words(['Hello!'], 'Hello!') == []


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


def _translation_lesson(db_session, module, english: str) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='TR check-item',
        type='translation',
        content={
            'items': [{
                'russian': 'Он врач.',
                'english': english,
                'hint_words': [],
                'alternatives': [],
            }],
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestCheckItemReveal:

    def test_contractions_do_not_change_final_reveal_contract(
        self, app, db_session, _module, test_user, client
    ):
        canonical = 'He is a doctor.'
        lesson = _translation_lesson(db_session, _module, canonical)
        _login(client, test_user)
        url = f'/curriculum/api/lesson/{lesson.id}/check-item'

        correct = client.post(
            url, json={'index': 0, 'answer': "He's a doctor", 'final': False}
        )
        assert correct.status_code == 200
        assert correct.get_json() == {
            'success': True, 'correct': True, 'answer': canonical,
        }

        pending = client.post(
            url, json={'index': 0, 'answer': 'He was a doctor', 'final': False}
        )
        assert pending.status_code == 200
        assert pending.get_json() == {'success': True, 'correct': False}

        revealed = client.post(
            url, json={'index': 0, 'answer': 'He was a doctor', 'final': True}
        )
        assert revealed.status_code == 200
        assert revealed.get_json() == {
            'success': True, 'correct': False, 'answer': canonical,
        }


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
