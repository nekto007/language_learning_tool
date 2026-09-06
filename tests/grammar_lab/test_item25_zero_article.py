"""Lesson audit item 25 — zero-article fill_blank items in the grammar lab.

A2-13 / A2-14 author the «no article» answer as an em dash («—»), which a
learner cannot type. The lab grader accepts the usual zero-article markers
(«-», «—», «нет артикля», …) and the full sentence with the blank simply
removed — but only when the expected answer is such a marker.
"""
from types import SimpleNamespace

import pytest

from app.grammar_lab.services.grader import GrammarExerciseGrader


def _ex(content):
    return SimpleNamespace(id=1, exercise_type='fill_blank', content=content)


@pytest.fixture
def grader():
    return GrammarExerciseGrader()


ZERO = _ex({
    'question': 'My uncle lives in ___ France near the border. (— или «-», если артикль не нужен)',
    'correct_answer': '—', 'alternatives': [],
})
THE = _ex({'question': 'We sailed across ___ Atlantic Ocean.', 'correct_answer': 'the', 'alternatives': []})


class TestZeroArticleMarkers:
    @pytest.mark.parametrize('answer', ['—', '-', '–', 'x', 'нет', 'нет артикля', 'без артикля', 'no article', 'None', ' - '])
    def test_markers_are_accepted(self, grader, answer):
        assert grader.grade(ZERO, answer)['is_correct']

    def test_full_sentence_without_article_is_accepted(self, grader):
        assert grader.grade(ZERO, 'My uncle lives in France near the border.')['is_correct']
        assert grader.grade(ZERO, 'my uncle lives in france near the border')['is_correct']

    def test_article_and_empty_stay_wrong(self, grader):
        assert not grader.grade(ZERO, 'the')['is_correct']
        assert not grader.grade(ZERO, 'a')['is_correct']
        assert not grader.grade(ZERO, '')['is_correct']
        assert not grader.grade(ZERO, 'My uncle lives in the France near the border.')['is_correct']

    def test_marker_is_not_a_wildcard_for_real_answers(self, grader):
        for answer in ('—', '-', 'нет', 'none'):
            assert not grader.grade(THE, answer)['is_correct']
        assert grader.grade(THE, 'the')['is_correct']
        assert not grader.grade(THE, 'We sailed across Atlantic Ocean.')['is_correct']
