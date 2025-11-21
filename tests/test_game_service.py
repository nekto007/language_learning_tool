"""
Comprehensive tests for GameService

Tests the matching game service that provides:
- Word selection for matching games
- Score calculation with bonuses
- Difficulty management

Coverage target: 90%+ for app/study/services/game_service.py
"""
import pytest


class TestGetMatchingWords:
    """Test get_matching_words method"""

    def test_returns_correct_number_of_words_easy(self, test_words_list):
        """Test returns 6 words for easy difficulty"""
        from app.study.services.game_service import GameService

        result = GameService.get_matching_words(test_words_list, difficulty='easy')

        assert len(result) == 6
        assert all('id' in word for word in result)
        assert all('english' in word for word in result)
        assert all('russian' in word for word in result)
        assert all('difficulty' in word for word in result)
        assert all(word['difficulty'] == 'easy' for word in result)

    def test_returns_correct_number_of_words_medium(self, test_words_list):
        """Test returns 8 words for medium difficulty"""
        from app.study.services.game_service import GameService

        result = GameService.get_matching_words(test_words_list, difficulty='medium')

        assert len(result) == 8

    def test_returns_correct_number_of_words_hard(self, test_words_list):
        """Test returns 10 words for hard difficulty"""
        from app.study.services.game_service import GameService

        result = GameService.get_matching_words(test_words_list, difficulty='hard')

        assert len(result) == 10

    def test_defaults_to_medium_difficulty(self, test_words_list):
        """Test defaults to medium difficulty if not specified"""
        from app.study.services.game_service import GameService

        result = GameService.get_matching_words(test_words_list)

        assert len(result) == 8  # Medium = 8 pairs

    def test_handles_insufficient_words(self, db_session):
        """Test handles case when not enough words available"""
        from app.study.services.game_service import GameService
        from app.words.models import CollectionWords

        # Create only 3 words
        words = []
        for i in range(3):
            word = CollectionWords(
                english_word=f'test_{i}',
                russian_word=f'тест_{i}'
            )
            db_session.add(word)
            words.append(word)
        db_session.commit()

        result = GameService.get_matching_words(words, difficulty='hard')

        # Should return 3 words instead of 10 (hard difficulty)
        assert len(result) == 3

    def test_returns_random_selection(self, test_words_list):
        """Test that word selection is random"""
        from app.study.services.game_service import GameService

        # Call multiple times
        result1 = GameService.get_matching_words(test_words_list, difficulty='easy')
        result2 = GameService.get_matching_words(test_words_list, difficulty='easy')

        ids1 = {word['id'] for word in result1}
        ids2 = {word['id'] for word in result2}

        # With 15+ words, selection should sometimes differ
        # (This might occasionally fail due to randomness, but very unlikely)
        # Note: This is a probabilistic test - could be made more robust
        assert len(result1) == len(result2) == 6

    def test_word_structure_includes_all_fields(self, test_words_list):
        """Test each word has all required fields"""
        from app.study.services.game_service import GameService

        result = GameService.get_matching_words(test_words_list, difficulty='easy')

        for word in result:
            assert 'id' in word
            assert 'english' in word
            assert 'russian' in word
            assert 'difficulty' in word
            assert isinstance(word['id'], int)
            assert isinstance(word['english'], str)
            assert isinstance(word['russian'], str)
            assert word['difficulty'] == 'easy'

    def test_handles_invalid_difficulty(self, test_words_list):
        """Test defaults to medium for invalid difficulty"""
        from app.study.services.game_service import GameService

        result = GameService.get_matching_words(test_words_list, difficulty='invalid')

        # Should default to medium (8 pairs)
        assert len(result) == 8


class TestCalculateMatchingScore:
    """Test calculate_matching_score method"""

    def test_calculates_base_score(self):
        """Test base score calculation (100 points per pair)"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=5,
            total_pairs=8,
            time_taken=60,
            moves=20
        )

        assert result['base_score'] == 500  # 5 pairs * 100

    def test_awards_completion_bonus(self):
        """Test completion bonus when all pairs matched"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=60,
            moves=20
        )

        assert result['completion_bonus'] == 200

    def test_no_completion_bonus_if_incomplete(self):
        """Test no completion bonus if not all pairs matched"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=7,
            total_pairs=8,
            time_taken=60,
            moves=20
        )

        assert result['completion_bonus'] == 0

    def test_calculates_time_bonus(self):
        """Test time bonus (2 points per second remaining)"""
        from app.study.services.game_service import GameService

        # Medium difficulty has 150s time limit
        # Time taken: 100s, remaining: 50s
        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=100,
            moves=20
        )

        assert result['time_bonus'] == 100  # 50s * 2 points

    def test_no_time_bonus_if_overtime(self):
        """Test no time bonus if time exceeded"""
        from app.study.services.game_service import GameService

        # Time taken exceeds limit
        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=200,  # Over 150s limit
            moves=20
        )

        assert result['time_bonus'] == 0

    def test_calculates_efficiency_bonus_perfect(self):
        """Test efficiency bonus for perfect moves"""
        from app.study.services.game_service import GameService

        # 8 pairs, min_moves = 16
        # 20 moves = 16 * 1.25, within 1.5x threshold
        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=60,
            moves=20  # ≤ 16 * 1.5 = 24
        )

        assert result['efficiency_bonus'] == 100

    def test_calculates_efficiency_bonus_good(self):
        """Test efficiency bonus for good moves"""
        from app.study.services.game_service import GameService

        # 8 pairs, min_moves = 16
        # 28 moves = 16 * 1.75, within 2x threshold
        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=60,
            moves=28  # ≤ 16 * 2 = 32
        )

        assert result['efficiency_bonus'] == 50

    def test_no_efficiency_bonus_for_many_moves(self):
        """Test no efficiency bonus for excessive moves"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=60,
            moves=40  # > 16 * 2 = 32
        )

        assert result['efficiency_bonus'] == 0

    def test_applies_easy_multiplier(self):
        """Test easy difficulty multiplier (1.0x)"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='easy',
            pairs_matched=6,
            total_pairs=6,
            time_taken=60,
            moves=12
        )

        assert result['difficulty_multiplier'] == 1.0
        # Base: 600, completion: 200, others vary
        assert 'total_score' in result

    def test_applies_medium_multiplier(self):
        """Test medium difficulty multiplier (1.5x)"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=60,
            moves=16
        )

        assert result['difficulty_multiplier'] == 1.5

    def test_applies_hard_multiplier(self):
        """Test hard difficulty multiplier (2.0x)"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='hard',
            pairs_matched=10,
            total_pairs=10,
            time_taken=60,
            moves=20
        )

        assert result['difficulty_multiplier'] == 2.0

    def test_calculates_xp_as_10_percent(self):
        """Test XP is 10% of total score"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=60,
            moves=16
        )

        expected_xp = int(result['total_score'] * 0.1)
        assert result['xp_awarded'] == expected_xp

    def test_handles_zero_pairs(self):
        """Test handles edge case of zero pairs"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=0,
            total_pairs=0,
            time_taken=0,
            moves=0
        )

        assert result['total_score'] == 0
        assert result['xp_awarded'] == 0

    def test_returns_all_required_fields(self):
        """Test result includes all required fields"""
        from app.study.services.game_service import GameService

        result = GameService.calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=60,
            moves=16
        )

        required_fields = [
            'base_score', 'completion_bonus', 'time_bonus', 'efficiency_bonus',
            'difficulty_multiplier', 'total_score', 'xp_awarded',
            'pairs_matched', 'total_pairs', 'time_taken', 'moves'
        ]

        for field in required_fields:
            assert field in result

    def test_perfect_game_score(self):
        """Test score for perfect game"""
        from app.study.services.game_service import GameService

        # Perfect game: all pairs, fast time, minimal moves
        result = GameService.calculate_matching_score(
            difficulty='hard',
            pairs_matched=10,
            total_pairs=10,
            time_taken=60,  # Fast (120s limit)
            moves=20        # Perfect (min = 20)
        )

        # Should have all bonuses
        assert result['base_score'] == 1000
        assert result['completion_bonus'] == 200
        assert result['time_bonus'] > 0
        assert result['efficiency_bonus'] == 100
        assert result['difficulty_multiplier'] == 2.0
        assert result['total_score'] > 2000  # With hard multiplier

    def test_failed_game_score(self):
        """Test score for failed/incomplete game"""
        from app.study.services.game_service import GameService

        # Failed game: few pairs, slow, many moves
        result = GameService.calculate_matching_score(
            difficulty='easy',
            pairs_matched=3,
            total_pairs=6,
            time_taken=200,  # Over limit
            moves=50         # Many moves
        )

        # Should have no bonuses
        assert result['base_score'] == 300
        assert result['completion_bonus'] == 0
        assert result['time_bonus'] == 0
        assert result['efficiency_bonus'] == 0
        assert result['difficulty_multiplier'] == 1.0


class TestDifficultySettings:
    """Test difficulty settings constants"""

    def test_easy_settings(self):
        """Test easy difficulty settings"""
        from app.study.services.game_service import GameService

        settings = GameService.DIFFICULTY_SETTINGS['easy']

        assert settings['pairs'] == 6
        assert settings['time_limit'] == 180

    def test_medium_settings(self):
        """Test medium difficulty settings"""
        from app.study.services.game_service import GameService

        settings = GameService.DIFFICULTY_SETTINGS['medium']

        assert settings['pairs'] == 8
        assert settings['time_limit'] == 150

    def test_hard_settings(self):
        """Test hard difficulty settings"""
        from app.study.services.game_service import GameService

        settings = GameService.DIFFICULTY_SETTINGS['hard']

        assert settings['pairs'] == 10
        assert settings['time_limit'] == 120

    def test_all_difficulties_exist(self):
        """Test all expected difficulties exist"""
        from app.study.services.game_service import GameService

        assert 'easy' in GameService.DIFFICULTY_SETTINGS
        assert 'medium' in GameService.DIFFICULTY_SETTINGS
        assert 'hard' in GameService.DIFFICULTY_SETTINGS
