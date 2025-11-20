"""
Game Service - matching game logic

Responsibilities:
- Game word selection
- Score calculation
- Difficulty management
"""
from typing import List, Dict, Tuple
import random

from app.words.models import CollectionWords


class GameService:
    """Service for matching game operations"""

    DIFFICULTY_SETTINGS = {
        'easy': {'pairs': 6, 'time_limit': 180},      # 3 minutes
        'medium': {'pairs': 8, 'time_limit': 150},    # 2.5 minutes
        'hard': {'pairs': 10, 'time_limit': 120}      # 2 minutes
    }

    @classmethod
    def get_matching_words(cls, words: List[CollectionWords], difficulty: str = 'medium') -> List[Dict]:
        """
        Select words for matching game

        Args:
            words: Available words to choose from
            difficulty: Game difficulty ('easy', 'medium', 'hard')

        Returns:
            List of word pairs for the game
        """
        settings = cls.DIFFICULTY_SETTINGS.get(difficulty, cls.DIFFICULTY_SETTINGS['medium'])
        pair_count = settings['pairs']

        if len(words) < pair_count:
            pair_count = len(words)

        selected_words = random.sample(words, pair_count)

        word_pairs = []
        for word in selected_words:
            word_pairs.append({
                'id': word.id,
                'english': word.english_word,
                'russian': word.russian_word,
                'difficulty': difficulty
            })

        return word_pairs

    @classmethod
    def calculate_matching_score(cls, difficulty: str, pairs_matched: int,
                                total_pairs: int, time_taken: int, moves: int) -> Dict:
        """
        Calculate score for matching game

        Args:
            difficulty: Game difficulty
            pairs_matched: Number of pairs correctly matched
            total_pairs: Total number of pairs
            time_taken: Time taken in seconds
            moves: Number of moves made

        Returns:
            Dictionary with score breakdown and XP
        """
        if total_pairs == 0:
            return {'total_score': 0, 'xp_awarded': 0}

        # Base score: 100 points per pair
        base_score = pairs_matched * 100

        # Completion bonus
        completion_bonus = 0
        if pairs_matched == total_pairs:
            completion_bonus = 200

        # Time bonus
        settings = cls.DIFFICULTY_SETTINGS.get(difficulty, cls.DIFFICULTY_SETTINGS['medium'])
        time_limit = settings['time_limit']
        time_remaining = max(0, time_limit - time_taken)
        time_bonus = int(time_remaining * 2)  # 2 points per second remaining

        # Efficiency bonus (fewer moves = better)
        min_moves = total_pairs * 2  # Perfect game
        if moves <= min_moves * 1.5:
            efficiency_bonus = 100
        elif moves <= min_moves * 2:
            efficiency_bonus = 50
        else:
            efficiency_bonus = 0

        # Difficulty multiplier
        difficulty_multiplier = {
            'easy': 1.0,
            'medium': 1.5,
            'hard': 2.0
        }.get(difficulty, 1.0)

        total_score = int((base_score + completion_bonus + time_bonus + efficiency_bonus) * difficulty_multiplier)

        # XP is 10% of score
        xp_awarded = int(total_score * 0.1)

        return {
            'base_score': base_score,
            'completion_bonus': completion_bonus,
            'time_bonus': time_bonus,
            'efficiency_bonus': efficiency_bonus,
            'difficulty_multiplier': difficulty_multiplier,
            'total_score': total_score,
            'xp_awarded': xp_awarded,
            'pairs_matched': pairs_matched,
            'total_pairs': total_pairs,
            'time_taken': time_taken,
            'moves': moves
        }
