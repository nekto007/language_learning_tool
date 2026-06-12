"""Tests for difficult words (трудные слова)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.study.models import UserCardDirection, UserWord
from app.study.services.difficult_words_service import (
    DIFFICULT_LAPSES_THRESHOLD,
    build_practice_questions,
    get_difficult_words,
    split_example,
    unbury_words,
)


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_card(db_session, user_id, word, lapses=0, buried_until=None,
               state='review', next_review=None, direction='eng-rus'):
    uw = UserWord.query.filter_by(user_id=user_id, word_id=word.id).first()
    if uw is None:
        uw = UserWord(user_id=user_id, word_id=word.id)
        uw.status = 'review'
        db_session.add(uw)
        db_session.flush()
    ucd = UserCardDirection(user_word_id=uw.id, direction=direction)
    ucd.state = state
    ucd.lapses = lapses
    ucd.buried_until = buried_until
    ucd.next_review = next_review if next_review is not None else _now_naive()
    ucd.correct_count = 4
    ucd.incorrect_count = 4
    db_session.add(ucd)
    db_session.flush()
    return ucd


class TestSplitExample:
    def test_pipe_separated(self):
        en, ru = split_example('Hello, how are you?|Привет, как дела?')
        assert en == 'Hello, how are you?'
        assert ru == 'Привет, как дела?'

    def test_newline_separated(self):
        en, ru = split_example('I read a book.\nЯ читаю книгу.')
        assert en == 'I read a book.'
        assert ru == 'Я читаю книгу.'

    def test_br_tags(self):
        en, ru = split_example('I drink water.<br>Я пью воду.')
        assert en == 'I drink water.'
        assert ru == 'Я пью воду.'

    def test_empty(self):
        assert split_example(None) == ('', '')
        assert split_example('') == ('', '')


@pytest.mark.smoke
class TestGetDifficultWords:
    def test_high_lapses_included(self, db_session, test_user, test_words_list):
        _make_card(db_session, test_user.id, test_words_list[0],
                   lapses=DIFFICULT_LAPSES_THRESHOLD)
        result = get_difficult_words(test_user.id)
        assert len(result) == 1
        assert result[0]['word_id'] == test_words_list[0].id
        assert result[0]['lapses'] == DIFFICULT_LAPSES_THRESHOLD

    def test_low_lapses_excluded(self, db_session, test_user, test_words_list):
        _make_card(db_session, test_user.id, test_words_list[0],
                   lapses=DIFFICULT_LAPSES_THRESHOLD - 1)
        assert get_difficult_words(test_user.id) == []

    def test_buried_included_even_with_low_lapses(self, db_session, test_user, test_words_list):
        _make_card(db_session, test_user.id, test_words_list[0], lapses=1,
                   buried_until=_now_naive() + timedelta(days=3))
        result = get_difficult_words(test_user.id)
        assert len(result) == 1
        assert result[0]['buried_until'] is not None

    def test_expired_bury_not_marked(self, db_session, test_user, test_words_list):
        _make_card(db_session, test_user.id, test_words_list[0],
                   lapses=DIFFICULT_LAPSES_THRESHOLD,
                   buried_until=_now_naive() - timedelta(days=1))
        result = get_difficult_words(test_user.id)
        assert len(result) == 1
        assert result[0]['buried_until'] is None

    def test_aggregates_directions_per_word(self, db_session, test_user, test_words_list):
        word = test_words_list[0]
        _make_card(db_session, test_user.id, word, lapses=3, direction='eng-rus')
        _make_card(db_session, test_user.id, word, lapses=7, direction='rus-eng')
        result = get_difficult_words(test_user.id)
        assert len(result) == 1
        assert result[0]['lapses'] == 7
        assert result[0]['is_leech'] is True

    def test_buried_sorted_first(self, db_session, test_user, test_words_list):
        _make_card(db_session, test_user.id, test_words_list[0], lapses=9)
        _make_card(db_session, test_user.id, test_words_list[1], lapses=3,
                   buried_until=_now_naive() + timedelta(days=2))
        result = get_difficult_words(test_user.id)
        assert result[0]['word_id'] == test_words_list[1].id

    def test_other_users_words_excluded(self, db_session, test_user, second_user, test_words_list):
        _make_card(db_session, second_user.id, test_words_list[0], lapses=9)
        assert get_difficult_words(test_user.id) == []


class TestBuildPracticeQuestions:
    def _entry(self, word_id=1, english='resilient', russian='стойкий',
               example_en='She stayed resilient under pressure.',
               example_ru='Она оставалась стойкой под давлением.'):
        return {
            'word_id': word_id, 'english_word': english, 'russian_word': russian,
            'example_en': example_en, 'example_ru': example_ru,
        }

    def test_cloze_question_built(self):
        words = [self._entry(), self._entry(2, 'book', 'книга', 'I read a book.', '')]
        questions = build_practice_questions(words)
        q = questions[0]
        assert q['type'] == 'cloze'
        assert '____' in q['prompt']
        assert 'resilient' not in q['prompt']
        assert q['correct'] == 'resilient'
        assert 'resilient' in q['options']

    def test_inflected_form_blanked(self):
        words = [
            self._entry(example_en='These plants are resilients of nature.'),
            self._entry(2, 'book', 'книга', 'I read a book.', ''),
        ]
        q = build_practice_questions(words)[0]
        assert '____' in q['prompt']

    def test_fallback_to_translation_without_example(self):
        words = [
            self._entry(example_en=''),
            self._entry(2, 'book', 'книга', 'I read a book.', ''),
        ]
        q = build_practice_questions(words)[0]
        assert q['type'] == 'translation'
        assert q['prompt'] == 'стойкий'

    def test_skipped_without_example_and_translation(self):
        words = [
            self._entry(example_en='', russian=''),
            self._entry(2, 'book', 'книга', 'I read a book.', ''),
        ]
        questions = build_practice_questions(words)
        assert all(q['word_id'] != 1 for q in questions)

    def test_single_word_needs_distractor_pool(self):
        words = [self._entry()]
        assert build_practice_questions(words) == []
        questions = build_practice_questions(words, distractor_pool=['cat', 'dog'])
        assert len(questions) == 1
        assert len(questions[0]['options']) >= 2


@pytest.mark.smoke
class TestUnburyWords:
    def test_unburies_only_listed_words(self, db_session, test_user, test_words_list):
        c1 = _make_card(db_session, test_user.id, test_words_list[0], lapses=6,
                        buried_until=_now_naive() + timedelta(days=5))
        c2 = _make_card(db_session, test_user.id, test_words_list[1], lapses=6,
                        buried_until=_now_naive() + timedelta(days=5))
        n = unbury_words(test_user.id, [test_words_list[0].id])
        assert n == 1
        assert c1.buried_until is None
        assert c2.buried_until is not None

    def test_ignores_other_users_cards(self, db_session, test_user, second_user, test_words_list):
        c = _make_card(db_session, second_user.id, test_words_list[0], lapses=6,
                       buried_until=_now_naive() + timedelta(days=5))
        n = unbury_words(test_user.id, [test_words_list[0].id])
        assert n == 0
        assert c.buried_until is not None

    def test_empty_list_noop(self, db_session, test_user):
        assert unbury_words(test_user.id, []) == 0


@pytest.mark.smoke
class TestDifficultWordsRoutes:
    def test_list_page_renders(self, authenticated_client, db_session, test_user, test_words_list):
        _make_card(db_session, test_user.id, test_words_list[0], lapses=5)
        db_session.commit()
        resp = authenticated_client.get('/study/difficult-words')
        assert resp.status_code == 200
        assert 'Трудные слова'.encode() in resp.data

    def test_list_page_empty_state(self, authenticated_client):
        resp = authenticated_client.get('/study/difficult-words')
        assert resp.status_code == 200

    def test_practice_redirects_when_empty(self, authenticated_client):
        resp = authenticated_client.get('/study/difficult-words/practice')
        assert resp.status_code == 302

    def test_practice_renders_with_words(self, authenticated_client, db_session, test_user, test_words_list):
        for word in test_words_list[:4]:
            _make_card(db_session, test_user.id, word, lapses=5)
        db_session.commit()
        resp = authenticated_client.get('/study/difficult-words/practice')
        assert resp.status_code == 200
        assert b'dwp-quiz' in resp.data

    def test_complete_endpoint_unburies(self, authenticated_client, db_session, test_user, test_words_list):
        _make_card(db_session, test_user.id, test_words_list[0], lapses=6,
                   buried_until=_now_naive() + timedelta(days=5))
        db_session.commit()
        resp = authenticated_client.post(
            '/study/api/difficult-words/complete',
            json={'correct_word_ids': [test_words_list[0].id]},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['unburied'] == 1

    def test_complete_endpoint_rejects_non_list(self, authenticated_client):
        resp = authenticated_client.post(
            '/study/api/difficult-words/complete',
            json={'correct_word_ids': 'nope'},
        )
        assert resp.status_code == 400
