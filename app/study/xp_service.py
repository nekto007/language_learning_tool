"""
Service module for XP (Experience Points) and Achievements system.
Handles XP calculations, achievement checks, and rewards.
"""
from datetime import datetime, timezone
from typing import List, Dict, Any

from sqlalchemy import func
from app.utils.db import db
from app.study.models import (
    UserXP, Achievement, UserAchievement,
    QuizResult, GameScore, StudySession
)


class XPService:
    """Service for managing user XP and achievements"""

    # XP rewards configuration
    XP_PER_CORRECT_ANSWER = 10
    XP_STREAK_BONUS = 5  # Per question in streak (when streak >= 5)
    XP_QUIZ_COMPLETION = 20
    XP_PER_CARD_REVIEWED = 5
    XP_FLASHCARD_SESSION = 15
    XP_MATCHING_COMPLETION = 25
    XP_MATCHING_PERFECT = 15  # Bonus for 100% accuracy
    XP_LESSON_COMPLETION = 30
    XP_BOOK_CHAPTER = 50

    @staticmethod
    def calculate_quiz_xp(correct_answers: int, total_questions: int,
                          time_taken: int, has_streak: bool = False) -> Dict[str, Any]:
        """
        Calculate XP earned from a quiz.

        Args:
            correct_answers: Number of correct answers
            total_questions: Total number of questions
            time_taken: Time taken in seconds
            has_streak: Whether user had a streak of 5+ correct answers

        Returns:
            Dictionary with XP breakdown:
            {
                'base_xp': int,      # XP from correct answers
                'streak_bonus': int, # Bonus XP from streak
                'completion_bonus': int, # Bonus for completing quiz
                'total_xp': int
            }
        """
        # No XP for empty quiz
        if total_questions == 0:
            return {
                'base_xp': 0,
                'streak_bonus': 0,
                'completion_bonus': 0,
                'total_xp': 0
            }

        # Base XP from correct answers
        base_xp = correct_answers * XPService.XP_PER_CORRECT_ANSWER

        # Streak bonus (only if streak >= 5)
        streak_bonus = 0
        if has_streak:
            streak_bonus = XPService.XP_STREAK_BONUS * correct_answers

        # Completion bonus (only for quizzes with at least 1 question)
        completion_bonus = XPService.XP_QUIZ_COMPLETION

        total_xp = base_xp + streak_bonus + completion_bonus

        return {
            'base_xp': base_xp,
            'streak_bonus': streak_bonus,
            'completion_bonus': completion_bonus,
            'total_xp': total_xp
        }

    @staticmethod
    def calculate_flashcard_xp(cards_reviewed: int, correct_answers: int) -> Dict[str, Any]:
        """
        Calculate XP earned from a flashcard session.

        Args:
            cards_reviewed: Number of cards reviewed
            correct_answers: Number of correct answers

        Returns:
            Dictionary with XP breakdown
        """
        base_xp = cards_reviewed * XPService.XP_PER_CARD_REVIEWED
        # Only give completion bonus if at least 1 card was studied
        completion_bonus = XPService.XP_FLASHCARD_SESSION if cards_reviewed > 0 else 0
        total_xp = base_xp + completion_bonus

        return {
            'base_xp': base_xp,
            'completion_bonus': completion_bonus,
            'total_xp': total_xp
        }

    @staticmethod
    def calculate_matching_xp(score: float, total_pairs: int) -> Dict[str, Any]:
        """
        Calculate XP earned from a matching game.

        Args:
            score: Score percentage (0-100)
            total_pairs: Number of pairs matched

        Returns:
            Dictionary with XP breakdown
        """
        base_xp = XPService.XP_MATCHING_COMPLETION
        perfect_bonus = XPService.XP_MATCHING_PERFECT if score == 100 else 0
        total_xp = base_xp + perfect_bonus

        return {
            'base_xp': base_xp,
            'perfect_bonus': perfect_bonus,
            'total_xp': total_xp
        }

    @staticmethod
    def calculate_lesson_xp() -> Dict[str, Any]:
        """
        Calculate XP earned from completing a lesson.

        Returns:
            Dictionary with XP breakdown
        """
        total_xp = XPService.XP_LESSON_COMPLETION

        return {
            'completion_bonus': total_xp,
            'total_xp': total_xp
        }

    @staticmethod
    def calculate_book_chapter_xp() -> Dict[str, Any]:
        """
        Calculate XP earned from completing a book chapter.

        Returns:
            Dictionary with XP breakdown
        """
        total_xp = XPService.XP_BOOK_CHAPTER

        return {
            'completion_bonus': total_xp,
            'total_xp': total_xp
        }

    @staticmethod
    def award_xp(user_id: int, amount: int) -> UserXP:
        """
        Award XP to a user.

        Args:
            user_id: User ID
            amount: Amount of XP to award

        Returns:
            Updated UserXP object
        """
        user_xp = UserXP.get_or_create(user_id)
        user_xp.add_xp(amount)
        db.session.commit()
        return user_xp

    @staticmethod
    def check_quiz_achievements(user_id: int, quiz_data: Dict[str, Any]) -> List[Achievement]:
        """
        Check and award achievements based on quiz performance.

        Args:
            user_id: User ID
            quiz_data: Dictionary containing:
                - score: Score percentage (0-100)
                - total_questions: Number of questions
                - correct_answers: Number of correct answers
                - time_taken: Time in seconds
                - has_streak: Whether user had 5+ correct streak

        Returns:
            List of newly earned Achievement objects
        """
        newly_earned = []

        # Get user's existing achievements
        existing_codes = set(
            ach.achievement.code
            for ach in UserAchievement.query
                .join(Achievement)
                .filter(UserAchievement.user_id == user_id)
                .all()
        )

        # Check: First quiz
        if 'first_quiz' not in existing_codes:
            quiz_count = QuizResult.query.filter_by(user_id=user_id).count()
            if quiz_count == 1:  # This is their first quiz
                newly_earned.append(XPService._award_achievement(user_id, 'first_quiz'))

        # Check: Perfect score (100%)
        if 'perfect_score' not in existing_codes:
            if quiz_data.get('score') == 100:
                newly_earned.append(XPService._award_achievement(user_id, 'perfect_score'))

        # Check: Speed demon (10+ questions in under 2 minutes)
        if 'speed_demon' not in existing_codes:
            if quiz_data.get('total_questions', 0) >= 10 and quiz_data.get('time_taken', 999) <= 120:
                newly_earned.append(XPService._award_achievement(user_id, 'speed_demon'))

        # Check: Quiz streak of 5+
        if 'quiz_streak_5' not in existing_codes:
            if quiz_data.get('has_streak'):
                newly_earned.append(XPService._award_achievement(user_id, 'quiz_streak_5'))

        # Check: High score 90%+
        if 'high_score_90' not in existing_codes:
            if quiz_data.get('score', 0) >= 90 and quiz_data.get('total_questions', 0) >= 10:
                newly_earned.append(XPService._award_achievement(user_id, 'high_score_90'))

        # Check: Quiz master (10 quizzes)
        if 'quiz_master_10' not in existing_codes:
            quiz_count = QuizResult.query.filter_by(user_id=user_id).count()
            if quiz_count >= 10:
                newly_earned.append(XPService._award_achievement(user_id, 'quiz_master_10'))

        # Check: Quiz guru (50 quizzes)
        if 'quiz_master_50' not in existing_codes:
            quiz_count = QuizResult.query.filter_by(user_id=user_id).count()
            if quiz_count >= 50:
                newly_earned.append(XPService._award_achievement(user_id, 'quiz_master_50'))

        # Check: Early bird (before 8 AM)
        if 'early_bird' not in existing_codes:
            now = datetime.now()
            if now.hour < 8:
                newly_earned.append(XPService._award_achievement(user_id, 'early_bird'))

        # Check: Night owl (after 11 PM)
        if 'night_owl' not in existing_codes:
            now = datetime.now()
            if now.hour >= 23:
                newly_earned.append(XPService._award_achievement(user_id, 'night_owl'))

        return newly_earned

    @staticmethod
    def _award_achievement(user_id: int, achievement_code: str) -> Achievement:
        """
        Award an achievement to a user and give bonus XP.

        Args:
            user_id: User ID
            achievement_code: Achievement code

        Returns:
            Achievement object or None
        """
        achievement = Achievement.query.filter_by(code=achievement_code).first()
        if not achievement:
            return None

        # Check if already earned
        existing = UserAchievement.query.filter_by(
            user_id=user_id,
            achievement_id=achievement.id
        ).first()

        if existing:
            return None

        # Award achievement
        user_achievement = UserAchievement(
            user_id=user_id,
            achievement_id=achievement.id
        )
        db.session.add(user_achievement)

        # Award bonus XP
        if achievement.xp_reward > 0:
            user_xp = UserXP.get_or_create(user_id)
            user_xp.add_xp(achievement.xp_reward)

        db.session.commit()

        return achievement

    @staticmethod
    def get_user_stats(user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive user statistics for XP and achievements.

        Args:
            user_id: User ID

        Returns:
            Dictionary with user stats
        """
        user_xp = UserXP.get_or_create(user_id)

        # Get achievements
        earned_achievements = UserAchievement.query.filter_by(user_id=user_id).count()
        total_achievements = Achievement.query.count()

        # Get quiz stats
        quiz_count = QuizResult.query.filter_by(user_id=user_id).count()
        avg_score = db.session.query(func.avg(QuizResult.score_percentage))\
            .filter(QuizResult.user_id == user_id).scalar() or 0

        return {
            'total_xp': user_xp.total_xp,
            'level': user_xp.level,
            'achievements_earned': earned_achievements,
            'total_achievements': total_achievements,
            'quiz_count': quiz_count,
            'avg_quiz_score': round(avg_score, 1)
        }
