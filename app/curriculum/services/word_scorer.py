"""
Word Scorer for Vocabulary Selection

Implements a multi-factor scoring system for selecting the best vocabulary words
from a book for learning purposes.

Factors considered:
- Book frequency: How often the word appears in the book
- Global frequency: How common the word is in general English (inverse - prefer less common)
- CEFR level match: How well the word matches the target learning level
- TF-IDF: Words unique to this book (story-important words)
"""

import logging
import math
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from app.words.models import CollectionWords

logger = logging.getLogger(__name__)

# Scoring weights
WEIGHT_BOOK_FREQ = 0.3      # Частота в книге
WEIGHT_GLOBAL_FREQ = 0.2    # Глобальная частотность (инверсия)
WEIGHT_CEFR = 0.3           # Соответствие уровню
WEIGHT_TFIDF = 0.2          # Уникальность для книги

# Frequency thresholds
MIN_BOOK_FREQUENCY = 3          # Минимум вхождений в книге
TOP_FREQUENCY_PERCENTILE = 40   # Или top 40% по частоте

# Word limits
VOCABULARY_WORDS_PER_BLOCK = 20   # Было 20, оставляем
VOCABULARY_WORDS_PER_LESSON = 8   # Было 10
VOCABULARY_WORDS_PER_MODULE = 40  # Было 50

# CEFR levels
CEFR_LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
DEFAULT_LEVEL = 'B1'

# Approximate global corpus size for TF-IDF
GLOBAL_CORPUS_SIZE = 100000


class WordScorer:
    """
    Scores words for vocabulary selection based on multiple factors.
    """

    def __init__(self, target_level: str = DEFAULT_LEVEL, total_words_in_book: int = 50000):
        """
        Initialize the word scorer.

        Args:
            target_level: Target CEFR level for the learner (A1-C2)
            total_words_in_book: Total word count in the book (for TF calculation)
        """
        self.target_level = target_level
        self.target_level_idx = self._get_level_index(target_level)
        self.total_words_in_book = total_words_in_book

    def _get_level_index(self, level: str) -> int:
        """Get numeric index for CEFR level"""
        if level and level in CEFR_LEVELS:
            return CEFR_LEVELS.index(level)
        return CEFR_LEVELS.index(DEFAULT_LEVEL)

    def should_include_word(self, book_freq: int, all_frequencies: List[int]) -> bool:
        """
        Determine if a word meets the frequency threshold.

        Combined threshold: word must have either:
        - At least MIN_BOOK_FREQUENCY occurrences, OR
        - Be in the top TOP_FREQUENCY_PERCENTILE% by frequency

        Args:
            book_freq: Frequency of the word in the book
            all_frequencies: List of all word frequencies in the book

        Returns:
            True if the word meets the threshold
        """
        # Absolute threshold: minimum occurrences
        if book_freq >= MIN_BOOK_FREQUENCY:
            return True

        # Relative threshold: top N% by frequency
        if all_frequencies:
            # Calculate the threshold for top 40%
            # 40% from top = 60th percentile from bottom
            sorted_freqs = sorted(all_frequencies)
            percentile_idx = int(len(sorted_freqs) * (100 - TOP_FREQUENCY_PERCENTILE) / 100)
            threshold = sorted_freqs[min(percentile_idx, len(sorted_freqs) - 1)]
            if book_freq >= threshold:
                return True

        return False

    def calculate_tfidf_score(self, word: CollectionWords, book_freq: int) -> float:
        """
        Calculate TF-IDF score for story importance.

        Words that are rare globally but frequent in this book get higher scores.
        This helps identify story-important words like "prophecy", "ministry", "wand".

        Args:
            word: CollectionWords object
            book_freq: Frequency of the word in this book

        Returns:
            TF-IDF score (higher = more story-important)
        """
        # TF (Term Frequency) - frequency in this book
        tf = book_freq / max(self.total_words_in_book, 1)

        # IDF (Inverse Document Frequency) - using global frequency rank as proxy
        # Lower frequency_rank = more common word = lower IDF
        # Higher frequency_rank = rarer word = higher IDF
        global_freq = word.frequency_rank if word.frequency_rank else 50000  # default for unknown

        # Normalize: if word is in top 1000 most common, IDF is low
        # if word is rare (rank > 50000), IDF is high
        idf = math.log(GLOBAL_CORPUS_SIZE / max(global_freq, 1))

        # Clamp to reasonable range [0, 1]
        tfidf = tf * idf
        max_tfidf = math.log(GLOBAL_CORPUS_SIZE)  # theoretical max
        normalized_tfidf = min(tfidf / max_tfidf, 1.0) if max_tfidf > 0 else 0

        return normalized_tfidf

    def calculate_cefr_score(self, word_level: str) -> float:
        """
        Calculate CEFR level match score.

        Words at the target level get highest score.
        Words below get slightly lower (already known territory).
        Words above target level are excluded elsewhere.

        Args:
            word_level: CEFR level of the word

        Returns:
            Score from 0 to 1 (1 = perfect match)
        """
        word_level_idx = self._get_level_index(word_level)
        distance = abs(self.target_level_idx - word_level_idx)

        # Perfect match = 1.0
        # Each level away reduces score by 0.2
        score = max(0, 1.0 - distance * 0.2)
        return score

    def calculate_global_freq_score(self, word: CollectionWords) -> float:
        """
        Calculate global frequency score (inverse - prefer medium frequency).

        Very common words (the, is, have) should be lower priority.
        Very rare words (flummoxed) also lower priority.
        Medium frequency words are ideal for learning.

        Args:
            word: CollectionWords object

        Returns:
            Score from 0 to 1 (1 = ideal frequency for learning)
        """
        freq_rank = word.frequency_rank if word.frequency_rank else 50000

        # Sweet spot: words ranked 3000-20000 are ideal
        # Too common (< 1000): student probably knows them
        # Too rare (> 50000): low utility

        if freq_rank < 1000:
            # Very common - low score
            return 0.3
        elif freq_rank < 3000:
            # Somewhat common
            return 0.6
        elif freq_rank < 20000:
            # Ideal learning range
            return 1.0
        elif freq_rank < 50000:
            # Somewhat rare
            return 0.7
        else:
            # Very rare
            return 0.4

    def calculate_book_freq_score(self, book_freq: int, max_freq: int) -> float:
        """
        Calculate book frequency score (normalized).

        Higher frequency in book = more useful to learn for this book.

        Args:
            book_freq: Frequency of word in the book
            max_freq: Maximum word frequency in the book

        Returns:
            Score from 0 to 1
        """
        if max_freq <= 0:
            return 0.5
        # Use log scale to prevent very high frequency words from dominating
        normalized = math.log(book_freq + 1) / math.log(max_freq + 1)
        return min(normalized, 1.0)

    def calculate_word_score(
            self,
            word: CollectionWords,
            book_freq: int,
            max_freq: int
    ) -> float:
        """
        Calculate overall score for a word.

        Combines all factors with weights.

        Args:
            word: CollectionWords object
            book_freq: Frequency of word in the book
            max_freq: Maximum word frequency in the book

        Returns:
            Combined score (higher = better candidate for vocabulary)
        """
        word_level = word.level or DEFAULT_LEVEL

        # Calculate individual scores
        book_freq_score = self.calculate_book_freq_score(book_freq, max_freq)
        global_freq_score = self.calculate_global_freq_score(word)
        cefr_score = self.calculate_cefr_score(word_level)
        tfidf_score = self.calculate_tfidf_score(word, book_freq)

        # Combine with weights
        total_score = (
                WEIGHT_BOOK_FREQ * book_freq_score +
                WEIGHT_GLOBAL_FREQ * global_freq_score +
                WEIGHT_CEFR * cefr_score +
                WEIGHT_TFIDF * tfidf_score
        )

        return total_score

    def score_and_rank_words(
            self,
            word_frequencies: Counter,
            word_cache: Dict[str, CollectionWords],
            used_words: Set[int],
            max_words: int
    ) -> List[Tuple[int, int, float]]:
        """
        Score and rank words for vocabulary selection.

        Args:
            word_frequencies: Counter with word frequencies from text
            word_cache: Dictionary mapping word text to CollectionWords
            used_words: Set of word IDs already used (to exclude)
            max_words: Maximum number of words to return

        Returns:
            List of tuples (word_id, frequency, score) sorted by score descending
        """
        all_frequencies = list(word_frequencies.values())
        max_freq = max(all_frequencies) if all_frequencies else 1

        candidates = []

        for word_text, freq in word_frequencies.items():
            # Check if word exists in database
            if word_text not in word_cache:
                continue

            db_word = word_cache[word_text]

            # Skip if already used
            if db_word.id in used_words:
                continue

            # Check frequency threshold
            if not self.should_include_word(freq, all_frequencies):
                continue

            # Get word level and check if it's within range
            word_level = db_word.level or DEFAULT_LEVEL
            word_level_idx = self._get_level_index(word_level)

            # Only include words at or below target level
            # (Don't give B1 students C2 vocabulary)
            if word_level_idx > self.target_level_idx:
                continue

            # Calculate score
            score = self.calculate_word_score(db_word, freq, max_freq)

            candidates.append({
                'word_id': db_word.id,
                'freq': freq,
                'score': score,
                'word': word_text,
                'level': word_level
            })

        # Sort by score (descending)
        candidates.sort(key=lambda x: x['score'], reverse=True)

        # Return top N
        result = [(c['word_id'], c['freq'], c['score']) for c in candidates[:max_words]]

        if result:
            logger.info(
                f"Scored {len(candidates)} words, returning top {len(result)} "
                f"for level {self.target_level}"
            )
            # Log top 5 for debugging
            for c in candidates[:5]:
                logger.debug(
                    f"  {c['word']} (level={c['level']}): "
                    f"freq={c['freq']}, score={c['score']:.3f}"
                )

        return result
