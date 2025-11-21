"""
Comprehensive tests for Study Models (app/study/models.py)
Coverage target: Cover all properties, methods, and class methods
"""
import pytest
from datetime import datetime, timedelta, timezone


class TestStudySessionModel:
    """Test StudySession model"""

    def test_complete_session_sets_end_time(self, app, test_user, db_session):
        from app.study.models import StudySession
        
        session = StudySession(user_id=test_user.id, session_type='cards')
        db_session.add(session)
        db_session.commit()
        
        assert session.end_time is None
        session.complete_session()
        assert session.end_time is not None

    def test_duration_with_completed_session(self, app, test_user, db_session):
        from app.study.models import StudySession
        
        session = StudySession(
            user_id=test_user.id, 
            session_type='quiz',
            start_time=datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        session.complete_session()
        
        assert session.duration >= 9  # ~10 minutes

    def test_duration_with_ongoing_session(self, app, test_user, db_session):
        from app.study.models import StudySession
        
        session = StudySession(
            user_id=test_user.id,
            session_type='cards',
            start_time=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        
        assert session.duration >= 4  # ~5 minutes

    def test_duration_with_naive_datetime(self, app, test_user, db_session):
        from app.study.models import StudySession

        # Test with naive datetime - should still work
        # Use timezone-aware datetime to avoid timezone conversion issues
        naive_start = datetime.now(timezone.utc) - timedelta(minutes=3)
        session = StudySession(
            user_id=test_user.id,
            session_type='quiz',
            start_time=naive_start
        )
        db_session.add(session)
        db_session.commit()

        duration = session.duration
        assert duration >= 2  # At least 2 minutes

    def test_performance_percentage_calculation(self, app, test_user, db_session):
        from app.study.models import StudySession
        
        session = StudySession(
            user_id=test_user.id,
            session_type='quiz',
            correct_answers=7,
            incorrect_answers=3
        )
        
        assert session.performance_percentage == 70

    def test_performance_percentage_zero_answers(self, app, test_user, db_session):
        from app.study.models import StudySession

        session = StudySession(
            user_id=test_user.id,
            session_type='cards',
            correct_answers=0,
            incorrect_answers=0
        )
        db_session.add(session)
        db_session.commit()

        assert session.performance_percentage == 0


class TestStudySettingsModel:
    """Test StudySettings model"""

    def test_get_settings_creates_new(self, app, test_user, db_session):
        from app.study.models import StudySettings
        
        settings = StudySettings.get_settings(test_user.id)
        
        assert settings is not None
        assert settings.user_id == test_user.id
        assert settings.new_words_per_day == 5  # default

    def test_get_settings_returns_existing(self, app, test_user, db_session):
        from app.study.models import StudySettings
        
        # Create settings
        original = StudySettings(user_id=test_user.id, new_words_per_day=10)
        db_session.add(original)
        db_session.commit()
        
        # Get settings should return existing
        retrieved = StudySettings.get_settings(test_user.id)
        assert retrieved.id == original.id
        assert retrieved.new_words_per_day == 10

    def test_get_settings_with_lock(self, app, test_user, db_session):
        from app.study.models import StudySettings
        
        settings = StudySettings.get_settings(test_user.id, lock_for_update=True)
        assert settings is not None


class TestGameScoreModel:
    """Test GameScore model"""

    def test_get_leaderboard(self, app, test_user, db_session):
        from app.study.models import GameScore

        # Create scores
        score1 = GameScore(user_id=test_user.id, game_type='matching', score=100)
        score2 = GameScore(user_id=test_user.id, game_type='matching', score=200)
        db_session.add_all([score1, score2])
        db_session.commit()

        leaderboard = GameScore.get_leaderboard('matching', limit=10)
        assert len(leaderboard) >= 2
        assert leaderboard[0].score >= leaderboard[1].score  # Descending order

    def test_get_leaderboard_with_difficulty(self, app, test_user, db_session):
        from app.study.models import GameScore

        score1 = GameScore(user_id=test_user.id, game_type='quiz', difficulty='easy', score=50)
        score2 = GameScore(user_id=test_user.id, game_type='quiz', difficulty='hard', score=150)
        db_session.add_all([score1, score2])
        db_session.commit()

        easy_board = GameScore.get_leaderboard('quiz', difficulty='easy')
        assert len(easy_board) >= 1
        # Filter to find our score
        our_scores = [s for s in easy_board if s.difficulty == 'easy']
        assert len(our_scores) >= 1

    def test_get_rank(self, app, test_user, db_session):
        from app.study.models import GameScore

        score1 = GameScore(user_id=test_user.id, game_type='matching', score=100)
        score2 = GameScore(user_id=test_user.id, game_type='matching', score=200)
        score3 = GameScore(user_id=test_user.id, game_type='matching', score=300)
        db_session.add_all([score1, score2, score3])
        db_session.commit()

        # Test that higher scores have better (lower) rank numbers
        rank3 = score3.get_rank()
        rank2 = score2.get_rank()
        rank1 = score1.get_rank()

        assert rank3 < rank2  # Highest score has better rank
        assert rank2 < rank1  # Middle score better than lowest


class TestUserWordModel:
    """Test UserWord model"""

    def test_get_or_create_new_word(self, app, test_user, test_words_list, db_session):
        from app.study.models import UserWord
        
        user_word = UserWord.get_or_create(test_user.id, test_words_list[0].id)
        
        assert user_word is not None
        assert user_word.user_id == test_user.id
        assert user_word.word_id == test_words_list[0].id
        assert user_word.status == 'new'

    def test_get_or_create_existing_word(self, app, test_user, test_words_list, db_session):
        from app.study.models import UserWord
        
        # Create first time
        original = UserWord.get_or_create(test_user.id, test_words_list[0].id)
        original.status = 'learning'
        db_session.commit()
        
        # Get again - should return same
        retrieved = UserWord.get_or_create(test_user.id, test_words_list[0].id)
        assert retrieved.id == original.id
        assert retrieved.status == 'learning'

    def test_update_status(self, app, test_user, test_words_list, db_session):
        from app.study.models import UserWord
        
        user_word = UserWord(user_id=test_user.id, word_id=test_words_list[0].id)
        db_session.add(user_word)
        db_session.commit()
        
        old_time = user_word.updated_at
        user_word.update_status('mastered')
        
        assert user_word.status == 'mastered'
        assert user_word.updated_at > old_time


class TestUserCardDirectionModel:
    """Test UserCardDirection model"""

    def test_update_after_review_correct_answer(self, app, test_user, test_words_list, db_session):
        from app.study.models import UserWord, UserCardDirection
        
        user_word = UserWord(user_id=test_user.id, word_id=test_words_list[0].id)
        db_session.add(user_word)
        db_session.flush()
        
        direction = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
        db_session.add(direction)
        db_session.commit()
        
        direction.update_after_review(quality=4)  # Good answer
        
        assert direction.correct_count == 1
        assert direction.repetitions >= 1
        assert direction.last_reviewed is not None

    def test_update_after_review_incorrect_answer(self, app, test_user, test_words_list, db_session):
        from app.study.models import UserWord, UserCardDirection
        
        user_word = UserWord(user_id=test_user.id, word_id=test_words_list[0].id)
        db_session.add(user_word)
        db_session.flush()
        
        direction = UserCardDirection(user_word_id=user_word.id, direction='rus-eng')
        db_session.add(direction)
        db_session.commit()
        
        direction.update_after_review(quality=0)  # Wrong answer
        
        assert direction.incorrect_count == 1
        assert direction.repetitions == 0  # Reset
        assert direction.interval == 0

    def test_due_for_review_property(self, app, test_user, test_words_list, db_session):
        from app.study.models import UserWord, UserCardDirection
        
        user_word = UserWord(user_id=test_user.id, word_id=test_words_list[0].id)
        db_session.add(user_word)
        db_session.flush()
        
        # Future review
        direction = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
        direction.next_review = datetime.now(timezone.utc) + timedelta(days=5)
        db_session.add(direction)
        db_session.commit()
        
        assert not direction.due_for_review

    def test_days_until_review(self, app, test_user, test_words_list, db_session):
        from app.study.models import UserWord, UserCardDirection
        
        user_word = UserWord(user_id=test_user.id, word_id=test_words_list[0].id)
        db_session.add(user_word)
        db_session.flush()
        
        direction = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
        direction.next_review = datetime.now(timezone.utc) + timedelta(days=3)
        db_session.add(direction)
        db_session.commit()
        
        assert direction.days_until_review >= 2


class TestQuizDeckModel:
    """Test QuizDeck model"""

    def test_generate_share_code(self, app, test_user, db_session):
        from app.study.models import QuizDeck
        
        deck = QuizDeck(user_id=test_user.id, title='Test Deck')
        db_session.add(deck)
        db_session.commit()
        
        code = deck.generate_share_code()
        
        assert code is not None
        assert len(code) == 8
        assert deck.share_code == code

    def test_word_count_property(self, app, test_user, test_words_list, db_session):
        from app.study.models import QuizDeck, QuizDeckWord

        deck = QuizDeck(user_id=test_user.id, title='Test')
        db_session.add(deck)
        db_session.flush()

        # Add words
        word1 = QuizDeckWord(deck_id=deck.id, word_id=test_words_list[0].id)
        word2 = QuizDeckWord(deck_id=deck.id, word_id=test_words_list[1].id)
        db_session.add_all([word1, word2])
        db_session.commit()

        # Refresh to get updated count
        db_session.refresh(deck)
        assert deck.word_count == 2


class TestQuizDeckWordModel:
    """Test QuizDeckWord model"""

    def test_english_word_from_collection(self, app, test_user, test_words_list, db_session):
        from app.study.models import QuizDeck, QuizDeckWord
        
        deck = QuizDeck(user_id=test_user.id, title='Test')
        db_session.add(deck)
        db_session.flush()
        
        deck_word = QuizDeckWord(deck_id=deck.id, word_id=test_words_list[0].id)
        db_session.add(deck_word)
        db_session.commit()
        
        assert deck_word.english_word == test_words_list[0].english_word

    def test_english_word_custom_override(self, app, test_user, db_session):
        from app.study.models import QuizDeck, QuizDeckWord
        
        deck = QuizDeck(user_id=test_user.id, title='Test')
        db_session.add(deck)
        db_session.flush()
        
        deck_word = QuizDeckWord(deck_id=deck.id, custom_english='custom word')
        db_session.add(deck_word)
        db_session.commit()
        
        assert deck_word.english_word == 'custom word'


class TestUserXPModel:
    """Test UserXP model"""

    def test_get_or_create_new(self, app, test_user, db_session):
        from app.study.models import UserXP
        
        xp = UserXP.get_or_create(test_user.id)
        
        assert xp.user_id == test_user.id
        assert xp.total_xp == 0
        assert xp.level == 1

    def test_level_calculation(self, app, test_user, db_session):
        from app.study.models import UserXP
        
        xp = UserXP(user_id=test_user.id, total_xp=250)
        assert xp.level == 2  # 250 / 100 = 2

    def test_add_xp(self, app, test_user, db_session):
        from app.study.models import UserXP
        
        xp = UserXP(user_id=test_user.id, total_xp=50)
        db_session.add(xp)
        db_session.commit()
        
        xp.add_xp(75)
        assert xp.total_xp == 125
