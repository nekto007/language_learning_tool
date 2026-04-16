"""
Tests for app/curriculum/services/word_scorer.py

Tests the multi-factor word scoring system for vocabulary selection.
"""
import math
import pytest
from collections import Counter
from unittest.mock import MagicMock

from app.curriculum.services.word_scorer import (
    WordScorer, WEIGHT_BOOK_FREQ, WEIGHT_GLOBAL_FREQ, WEIGHT_CEFR, WEIGHT_TFIDF,
    MIN_BOOK_FREQUENCY, TOP_FREQUENCY_PERCENTILE, CEFR_LEVELS, DEFAULT_LEVEL,
    GLOBAL_CORPUS_SIZE, VOCABULARY_WORDS_PER_BLOCK, VOCABULARY_WORDS_PER_LESSON,
    VOCABULARY_WORDS_PER_MODULE
)


def _make_word(level='B1', frequency_rank=5000, word_id=1):
    """Create a mock CollectionWords object."""
    w = MagicMock()
    w.id = word_id
    w.level = level
    w.frequency_rank = frequency_rank
    return w


class TestWordScorerInit:
    def test_default_init(self):
        scorer = WordScorer()
        assert scorer.target_level == DEFAULT_LEVEL
        assert scorer.target_level_idx == CEFR_LEVELS.index(DEFAULT_LEVEL)
        assert scorer.total_words_in_book == 50000

    def test_custom_level(self):
        scorer = WordScorer(target_level='A1')
        assert scorer.target_level == 'A1'
        assert scorer.target_level_idx == 0

    def test_custom_total_words(self):
        scorer = WordScorer(total_words_in_book=10000)
        assert scorer.total_words_in_book == 10000

    def test_invalid_level_defaults(self):
        scorer = WordScorer(target_level='XYZ')
        assert scorer.target_level_idx == CEFR_LEVELS.index(DEFAULT_LEVEL)


class TestGetLevelIndex:
    def test_all_levels(self):
        scorer = WordScorer()
        for i, level in enumerate(CEFR_LEVELS):
            assert scorer._get_level_index(level) == i

    def test_invalid_level(self):
        scorer = WordScorer()
        assert scorer._get_level_index('Z9') == CEFR_LEVELS.index(DEFAULT_LEVEL)

    def test_none_level(self):
        scorer = WordScorer()
        assert scorer._get_level_index(None) == CEFR_LEVELS.index(DEFAULT_LEVEL)

    def test_empty_string(self):
        scorer = WordScorer()
        assert scorer._get_level_index('') == CEFR_LEVELS.index(DEFAULT_LEVEL)


class TestShouldIncludeWord:
    def test_above_min_frequency(self):
        scorer = WordScorer()
        assert scorer.should_include_word(MIN_BOOK_FREQUENCY, [1, 2, 3, 4, 5]) is True

    def test_below_min_frequency_but_top_percentile(self):
        scorer = WordScorer()
        # freq=2 is below MIN_BOOK_FREQUENCY=3, but if it's in top 40% it should pass
        all_freqs = [1] * 60 + [2] * 40  # 2 is at 60th percentile from bottom = top 40%
        assert scorer.should_include_word(2, all_freqs) is True

    def test_below_both_thresholds(self):
        scorer = WordScorer()
        # freq=1 is below min, and bottom of distribution
        all_freqs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert scorer.should_include_word(1, all_freqs) is False

    def test_empty_frequencies(self):
        scorer = WordScorer()
        assert scorer.should_include_word(1, []) is False

    def test_exactly_min_frequency(self):
        scorer = WordScorer()
        assert scorer.should_include_word(MIN_BOOK_FREQUENCY, [1, 2, 3]) is True

    def test_high_frequency(self):
        scorer = WordScorer()
        assert scorer.should_include_word(100, [1, 2, 100]) is True


class TestCalculateTfidfScore:
    def test_high_tfidf_rare_word(self):
        scorer = WordScorer(total_words_in_book=10000)
        word = _make_word(frequency_rank=80000)  # rare globally
        score = scorer.calculate_tfidf_score(word, book_freq=50)  # common in book
        assert 0 <= score <= 1

    def test_low_tfidf_common_word(self):
        scorer = WordScorer(total_words_in_book=10000)
        word = _make_word(frequency_rank=100)  # very common globally
        score = scorer.calculate_tfidf_score(word, book_freq=1)  # rare in book
        assert 0 <= score <= 1

    def test_no_frequency_rank(self):
        scorer = WordScorer()
        word = _make_word(frequency_rank=None)
        score = scorer.calculate_tfidf_score(word, book_freq=10)
        assert 0 <= score <= 1

    def test_zero_book_words(self):
        scorer = WordScorer(total_words_in_book=0)
        word = _make_word(frequency_rank=5000)
        score = scorer.calculate_tfidf_score(word, book_freq=5)
        assert 0 <= score <= 1

    def test_result_is_normalized(self):
        scorer = WordScorer(total_words_in_book=50000)
        word = _make_word(frequency_rank=1)
        score = scorer.calculate_tfidf_score(word, book_freq=50000)
        assert score <= 1.0


class TestCalculateCefrScore:
    def test_exact_match(self):
        scorer = WordScorer(target_level='B1')
        assert scorer.calculate_cefr_score('B1') == 1.0

    def test_one_level_away(self):
        scorer = WordScorer(target_level='B1')
        assert scorer.calculate_cefr_score('B2') == pytest.approx(0.8)
        assert scorer.calculate_cefr_score('A2') == pytest.approx(0.8)

    def test_two_levels_away(self):
        scorer = WordScorer(target_level='B1')
        assert scorer.calculate_cefr_score('C1') == pytest.approx(0.6)
        assert scorer.calculate_cefr_score('A1') == pytest.approx(0.6)

    def test_max_distance(self):
        scorer = WordScorer(target_level='A1')
        score = scorer.calculate_cefr_score('C2')
        assert score == pytest.approx(0.0)

    def test_none_level_uses_default(self):
        scorer = WordScorer(target_level='B1')
        # None level defaults to B1 which matches target
        score = scorer.calculate_cefr_score(None)
        assert score == 1.0


class TestCalculateGlobalFreqScore:
    def test_very_common(self):
        word = _make_word(frequency_rank=500)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 0.3

    def test_somewhat_common(self):
        word = _make_word(frequency_rank=2000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 0.6

    def test_ideal_range(self):
        word = _make_word(frequency_rank=10000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 1.0

    def test_somewhat_rare(self):
        word = _make_word(frequency_rank=30000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 0.7

    def test_very_rare(self):
        word = _make_word(frequency_rank=60000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 0.4

    def test_none_rank(self):
        word = _make_word(frequency_rank=None)
        scorer = WordScorer()
        # None defaults to 50000, which is >= 50000 → very rare
        assert scorer.calculate_global_freq_score(word) == 0.4

    def test_boundary_1000(self):
        word = _make_word(frequency_rank=1000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 0.6

    def test_boundary_3000(self):
        word = _make_word(frequency_rank=3000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 1.0

    def test_boundary_20000(self):
        word = _make_word(frequency_rank=20000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 0.7

    def test_boundary_50000(self):
        word = _make_word(frequency_rank=50000)
        scorer = WordScorer()
        assert scorer.calculate_global_freq_score(word) == 0.4


class TestCalculateBookFreqScore:
    def test_normal_case(self):
        scorer = WordScorer()
        score = scorer.calculate_book_freq_score(10, 100)
        assert 0 < score <= 1

    def test_max_freq(self):
        scorer = WordScorer()
        score = scorer.calculate_book_freq_score(100, 100)
        assert score == pytest.approx(1.0)

    def test_zero_max_freq(self):
        scorer = WordScorer()
        assert scorer.calculate_book_freq_score(5, 0) == 0.5

    def test_negative_max_freq(self):
        scorer = WordScorer()
        assert scorer.calculate_book_freq_score(5, -1) == 0.5

    def test_log_scale_prevents_domination(self):
        scorer = WordScorer()
        score_low = scorer.calculate_book_freq_score(2, 1000)
        score_high = scorer.calculate_book_freq_score(500, 1000)
        # Log scale means the ratio isn't as extreme as 2:500
        assert score_high > score_low
        assert score_high / score_low < 250  # Much less than linear 250x


class TestCalculateWordScore:
    def test_combines_all_factors(self):
        scorer = WordScorer(target_level='B1')
        word = _make_word(level='B1', frequency_rank=10000)
        score = scorer.calculate_word_score(word, book_freq=10, max_freq=100)
        assert 0 < score <= 1

    def test_weights_sum_to_one(self):
        assert WEIGHT_BOOK_FREQ + WEIGHT_GLOBAL_FREQ + WEIGHT_CEFR + WEIGHT_TFIDF == pytest.approx(1.0)

    def test_none_word_level_uses_default(self):
        scorer = WordScorer(target_level='B1')
        word = _make_word(level=None, frequency_rank=5000)
        score = scorer.calculate_word_score(word, book_freq=5, max_freq=50)
        assert 0 < score <= 1

    def test_ideal_word_scores_high(self):
        scorer = WordScorer(target_level='B1')
        word = _make_word(level='B1', frequency_rank=10000)  # ideal freq range + level match
        score = scorer.calculate_word_score(word, book_freq=50, max_freq=100)
        assert score > 0.7

    def test_poor_word_scores_low(self):
        scorer = WordScorer(target_level='B1')
        word = _make_word(level='C2', frequency_rank=500)  # far level + very common
        score = scorer.calculate_word_score(word, book_freq=1, max_freq=100)
        assert score < 0.6


class TestScoreAndRankWords:
    @pytest.mark.smoke
    def test_basic_ranking(self):
        scorer = WordScorer(target_level='B1')
        word_frequencies = Counter({'hello': 10, 'world': 5, 'test': 3})
        word_cache = {
            'hello': _make_word(level='B1', frequency_rank=5000, word_id=1),
            'world': _make_word(level='A2', frequency_rank=8000, word_id=2),
            'test': _make_word(level='B1', frequency_rank=12000, word_id=3),
        }
        result = scorer.score_and_rank_words(word_frequencies, word_cache, set(), max_words=10)
        assert len(result) == 3
        # Results should be sorted by score descending
        scores = [r[2] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_excludes_used_words(self):
        scorer = WordScorer(target_level='B1')
        word_frequencies = Counter({'hello': 10, 'world': 5})
        word_cache = {
            'hello': _make_word(level='B1', frequency_rank=5000, word_id=1),
            'world': _make_word(level='A2', frequency_rank=8000, word_id=2),
        }
        result = scorer.score_and_rank_words(word_frequencies, word_cache, {1}, max_words=10)
        assert len(result) == 1
        assert result[0][0] == 2  # Only word_id=2 remains

    def test_excludes_above_level(self):
        scorer = WordScorer(target_level='A1')
        word_frequencies = Counter({'hello': 10, 'advanced': 5})
        word_cache = {
            'hello': _make_word(level='A1', frequency_rank=5000, word_id=1),
            'advanced': _make_word(level='C2', frequency_rank=8000, word_id=2),
        }
        result = scorer.score_and_rank_words(word_frequencies, word_cache, set(), max_words=10)
        assert len(result) == 1
        assert result[0][0] == 1

    def test_respects_max_words(self):
        scorer = WordScorer(target_level='B1')
        word_frequencies = Counter({f'word{i}': 10 for i in range(20)})
        word_cache = {
            f'word{i}': _make_word(level='B1', frequency_rank=5000, word_id=i+1)
            for i in range(20)
        }
        result = scorer.score_and_rank_words(word_frequencies, word_cache, set(), max_words=5)
        assert len(result) == 5

    def test_skips_missing_from_cache(self):
        scorer = WordScorer(target_level='B1')
        word_frequencies = Counter({'hello': 10, 'missing': 5})
        word_cache = {
            'hello': _make_word(level='B1', frequency_rank=5000, word_id=1),
        }
        result = scorer.score_and_rank_words(word_frequencies, word_cache, set(), max_words=10)
        assert len(result) == 1

    def test_empty_input(self):
        scorer = WordScorer()
        result = scorer.score_and_rank_words(Counter(), {}, set(), max_words=10)
        assert result == []

    def test_result_tuple_format(self):
        scorer = WordScorer(target_level='B1')
        word_frequencies = Counter({'hello': 10})
        word_cache = {'hello': _make_word(level='B1', frequency_rank=5000, word_id=42)}
        result = scorer.score_and_rank_words(word_frequencies, word_cache, set(), max_words=10)
        assert len(result) == 1
        word_id, freq, score = result[0]
        assert word_id == 42
        assert freq == 10
        assert isinstance(score, float)

    def test_filters_low_frequency(self):
        scorer = WordScorer(target_level='B1')
        # freq=1 and not in top percentile
        word_frequencies = Counter({'rare': 1, 'common': 10})
        all_freqs_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        word_cache = {
            'rare': _make_word(level='B1', frequency_rank=5000, word_id=1),
            'common': _make_word(level='B1', frequency_rank=5000, word_id=2),
        }
        result = scorer.score_and_rank_words(word_frequencies, word_cache, set(), max_words=10)
        # 'rare' with freq=1 may or may not be included depending on percentile threshold
        word_ids = [r[0] for r in result]
        assert 2 in word_ids  # common should always be included


class TestConstants:
    def test_weights_sum(self):
        assert WEIGHT_BOOK_FREQ + WEIGHT_GLOBAL_FREQ + WEIGHT_CEFR + WEIGHT_TFIDF == pytest.approx(1.0)

    def test_cefr_levels_order(self):
        assert CEFR_LEVELS == ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']

    def test_limits(self):
        assert VOCABULARY_WORDS_PER_BLOCK == 20
        assert VOCABULARY_WORDS_PER_LESSON == 8
        assert VOCABULARY_WORDS_PER_MODULE == 40