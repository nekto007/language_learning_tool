"""Distractor selection for themed quizzes.

The point of a themed quiz is that the wrong options belong to the theme: with
options drawn from the whole dictionary, «red» sits next to «стол» and «бежать»
and the answer is guessable without knowing the word.
"""
import pytest

from app.study.services.quiz_service import (
    THEMED_DISTRACTOR_QUOTA,
    QuizService,
    _answer_variants,
)


class FakeWord:
    """Duck-typed stand-in — the picker only reads id and the two word fields."""

    def __init__(self, id_, english, russian):
        self.id = id_
        self.english_word = english
        self.russian_word = russian


@pytest.fixture
def colors():
    # shadow/shade is a real collision in the seeded Colors set.
    return [
        FakeWord(1, 'shadow', 'тень'),
        FakeWord(2, 'shade', 'тень, оттенок'),
        FakeWord(3, 'red', 'красный'),
        FakeWord(4, 'blue', 'синий'),
        FakeWord(5, 'green', 'зелёный'),
        FakeWord(6, 'yellow', 'жёлтый'),
    ]


@pytest.fixture
def unrelated():
    return [
        FakeWord(90, 'table', 'стол'),
        FakeWord(91, 'run', 'бежать'),
        FakeWord(92, 'yesterday', 'вчера'),
        FakeWord(93, 'house', 'дом'),
    ]


class TestAnswerVariants:
    def test_splits_on_commas_and_normalises(self):
        assert _answer_variants('Тень, Оттенок ') == {'тень', 'оттенок'}

    def test_empty_input_yields_empty_set(self):
        assert _answer_variants(None) == set()
        assert _answer_variants('   ') == set()


class TestThemedDistractors:
    def test_prefers_the_themed_pool(self, colors, unrelated):
        themed_values = {w.russian_word for w in colors}
        red = colors[2]

        for _ in range(50):
            picked = QuizService._collect_distractors(
                red, 'красный', 'eng_to_rus', colors, unrelated
            )
            from_theme = sum(1 for value in picked if value in themed_values)
            assert from_theme == THEMED_DISTRACTOR_QUOTA

    def test_keeps_one_option_from_outside_the_theme(self, colors, unrelated):
        outside = {w.russian_word for w in unrelated}
        red = colors[2]

        for _ in range(50):
            picked = QuizService._collect_distractors(
                red, 'красный', 'eng_to_rus', colors, unrelated
            )
            assert sum(1 for value in picked if value in outside) == 1

    def test_never_offers_an_overlapping_translation(self, colors, unrelated):
        """shadow=«тень» must not be quizzed against shade=«тень, оттенок».

        Both answers would be defensible while only one is graded correct.
        """
        shadow = colors[0]
        for _ in range(200):
            picked = QuizService._collect_distractors(
                shadow, 'тень', 'eng_to_rus', colors, unrelated
            )
            assert 'тень, оттенок' not in picked

    def test_options_are_never_duplicated(self, colors, unrelated):
        red = colors[2]
        for _ in range(100):
            picked = QuizService._collect_distractors(
                red, 'красный', 'eng_to_rus', colors, unrelated
            )
            assert len(picked) == len(set(picked))

    def test_small_set_still_fills_three_options(self, unrelated):
        tiny = [FakeWord(3, 'red', 'красный'), FakeWord(4, 'blue', 'синий')]
        picked = QuizService._collect_distractors(
            tiny[0], 'красный', 'eng_to_rus', tiny, unrelated
        )
        assert len(picked) == 3

    def test_reverse_direction_uses_english(self, colors, unrelated):
        red = colors[2]
        picked = QuizService._collect_distractors(
            red, 'red', 'rus_to_eng', colors, unrelated
        )
        english = {w.english_word for w in colors + unrelated}
        assert picked and all(value in english for value in picked)
        assert 'red' not in picked


class TestWithoutAPool:
    """Decks, auto and linear-plan quizzes must keep their old behaviour."""

    def test_nothing_themed_leaks_in(self, colors, unrelated):
        themed_values = {w.russian_word for w in colors}
        red = colors[2]

        for _ in range(50):
            picked = QuizService._collect_distractors(
                red, 'красный', 'eng_to_rus', None, unrelated
            )
            assert all(value not in themed_values for value in picked)
