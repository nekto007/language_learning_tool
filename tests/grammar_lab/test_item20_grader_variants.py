"""Lesson audit item 20 — grammar-lab grading tolerance and practice order.

Guards:
* full-sentence fill-blank answers are compared with the author hint
  («(wake up)») stripped from the question;
* free-text answers (translation / transformation / error correction) accept
  contractions and lexical variants (mum / mom / mother) on both sides via
  the helper shared with the course translation grader;
* unseen exercises of a topic practice are served easiest-first, random
  within a difficulty level.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.curriculum.grading import (
    _strict_text_match,
    fold_lexical_variants,
    text_answer_variants,
)
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.grammar_lab.services.grammar_lab_service import GrammarLabService


def _ex(exercise_type, content):
    return SimpleNamespace(id=1, exercise_type=exercise_type, content=content)


@pytest.fixture
def grader():
    return GrammarExerciseGrader()


class TestFillBlankHint:
    def test_full_sentence_without_hint_is_accepted(self, grader):
        ex = _ex('fill_blank', {
            'question': 'Tom ___ (wake up) at sunrise every morning.',
            'correct_answer': 'wakes up', 'alternatives': [],
        })
        assert grader.grade(ex, 'Tom wakes up at sunrise every morning.')['is_correct']
        assert grader.grade(ex, 'tom wakes up at sunrise every morning')['is_correct']

    def test_full_sentence_with_hint_kept_is_still_accepted(self, grader):
        ex = _ex('fill_blank', {
            'question': 'Tom ___ (wake up) at sunrise every morning.',
            'correct_answer': 'wakes up', 'alternatives': [],
        })
        assert grader.grade(ex, 'Tom wakes up (wake up) at sunrise every morning.')['is_correct']

    def test_wrong_form_and_empty_stay_wrong(self, grader):
        ex = _ex('fill_blank', {
            'question': 'Tom ___ (wake up) at sunrise every morning.',
            'correct_answer': 'wakes up', 'alternatives': [],
        })
        assert not grader.grade(ex, 'wake up')['is_correct']
        assert not grader.grade(ex, 'Tom wake up at sunrise every morning.')['is_correct']
        assert not grader.grade(ex, '')['is_correct']

    def test_hintless_question_keeps_working(self, grader):
        ex = _ex('fill_blank', {
            'question': '___ your sister work as a nurse?',
            'correct_answer': 'Does', 'alternatives': [],
        })
        assert grader.grade(ex, 'does')['is_correct']
        assert grader.grade(ex, 'Does your sister work as a nurse?')['is_correct']
        assert not grader.grade(ex, 'Do')['is_correct']

    def test_empty_alternative_never_matches_empty_answer(self, grader):
        ex = _ex('fill_blank', {
            'question': 'She ___ (go) to work.', 'correct_answer': 'goes',
            'alternatives': [''],
        })
        assert not grader.grade(ex, '')['is_correct']
        assert not grader.grade(ex, '   ')['is_correct']


class TestLexicalVariants:
    def test_fold_maps_register_and_spelling(self):
        assert fold_lexical_variants('My Mom and my dad') == 'my mother and my father'
        assert fold_lexical_variants('the neighbors') == 'the neighbours'
        assert fold_lexical_variants('mother') == 'mother'

    def test_fold_is_whole_word_only(self):
        # «madam» / «dadaism» must not be touched.
        assert fold_lexical_variants('madam dadaism') == 'madam dadaism'

    def test_variants_intersect_for_same_sentence(self):
        assert text_answer_variants("My mom's a doctor") & text_answer_variants('My mum is a doctor.') == set()
        assert text_answer_variants("She's my mom") & text_answer_variants('She is my mother.')

    def test_course_strict_match_accepts_register(self):
        assert _strict_text_match('my mom works in a library', ['My mum works in a library.'])
        assert _strict_text_match('My mother works in a library', ['My mum works in a library.'])
        assert not _strict_text_match('My father works in a library', ['My mum works in a library.'])

    def test_lab_translation_accepts_register_and_contractions(self, grader):
        ex = _ex('translation', {
            'question': 'Моя мама работает в библиотеке.',
            'correct_answer': 'My mum works in a library.', 'alternatives': [],
        })
        assert grader.grade(ex, 'my mom works in a library')['is_correct']
        assert grader.grade(ex, 'My mother works in a library.')['is_correct']
        assert not grader.grade(ex, 'My father works in a library.')['is_correct']
        neg = _ex('translation', {
            'correct_answer': "She doesn't work as a cook.", 'alternatives': [],
        })
        assert grader.grade(neg, 'She does not work as a cook')['is_correct']
        assert grader.grade(neg, "she doesn't work as a cook")['is_correct']
        assert not grader.grade(neg, "She doesn't work as a cook here")['is_correct']

    def test_lab_translation_acceptable_answers_still_honoured(self, grader):
        ex = _ex('translation', {
            'correct_answer': 'Tom studies English at school.',
            'acceptable_answers': ['Tom learns English at school.'],
        })
        assert grader.grade(ex, 'tom learns english at school')['is_correct']

    def test_error_correction_accepts_expanded_contraction(self, grader):
        ex = _ex('error_correction', {
            'sentence': "The police officer don't talk to journalists.",
            'correct_answer': "The police officer doesn't talk to journalists.",
            'error_word': "don't", 'correct_word': "doesn't",
            'alternatives': ["doesn't"],
        })
        assert grader.grade(ex, 'The police officer does not talk to journalists.')['is_correct']
        assert grader.grade(ex, 'does not')['is_correct']
        assert grader.grade(ex, "doesn't")['is_correct']
        assert not grader.grade(ex, "don't")['is_correct']
        assert grader.grade(ex, '')['is_correct'] is False

    def test_transformation_accepts_contraction(self, grader):
        ex = _ex('transformation', {
            'question': 'Make it negative', 'correct_answer': 'I am not happy',
            'alternatives': [],
        })
        assert grader.grade(ex, "I'm not happy")['is_correct']
        assert not grader.grade(ex, 'I am happy')['is_correct']


@pytest.fixture
def graded_topic(db_session):
    topic = GrammarTopic(
        slug=f'item20-order-{uuid.uuid4().hex[:8]}', title='Order', title_ru='Порядок',
        level='A1', order=1, content={'introduction': 'x', 'sections': []},
        estimated_time=5, difficulty=1,
    )
    db_session.add(topic)
    db_session.flush()
    for i, difficulty in enumerate([3, 3, 2, 1, 2, 1, 3, 1]):
        db_session.add(GrammarExercise(
            topic_id=topic.id, exercise_type='fill_blank', difficulty=difficulty, order=i + 1,
            content={'question': f'Q{i} ___', 'correct_answer': 'x', 'alternatives': [],
                     'explanation': ''},
        ))
    db_session.commit()
    return topic


class TestPracticeOrder:
    def test_new_pool_is_served_easiest_first(self, db_session, test_user, graded_topic):
        service = GrammarLabService()
        with patch.object(service, 'award_xp', create=True):
            result = service.start_topic_practice(graded_topic.id, test_user.id, max_exercises=5)
        difficulties = [e['difficulty'] for e in result['exercises']]
        assert difficulties == sorted(difficulties)
        assert difficulties == [1, 1, 1, 2, 2]

    def test_order_within_a_level_is_not_fixed(self, db_session, test_user, graded_topic):
        service = GrammarLabService()
        seen = set()
        for _ in range(12):
            result = service.start_topic_practice(graded_topic.id, test_user.id, max_exercises=3)
            seen.add(tuple(e['id'] for e in result['exercises']))
        assert all(len(ids) == 3 for ids in seen)
        assert len(seen) > 1
