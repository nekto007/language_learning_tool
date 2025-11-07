# app/achievements/services.py
"""
Service for managing lesson grades, user statistics, and achievement tracking
"""

from datetime import date, datetime, timezone
from typing import Optional, Dict, List

from sqlalchemy import func

from app.achievements.models import LessonGrade, UserStatistics
from app.study.models import Achievement, UserAchievement, UserXP
from app.utils.db import db


class GradingService:
    """Service for calculating and assigning lesson grades"""

    @staticmethod
    def calculate_grade(score: float) -> str:
        """
        Calculate letter grade from numeric score

        Args:
            score: Numeric score 0-100

        Returns:
            Letter grade: A, B, C, D, or F
        """
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'

    @staticmethod
    def assign_lesson_grade(user_id: int, lesson_id: int, score: float) -> LessonGrade:
        """
        Assign a grade for a lesson completion

        Args:
            user_id: User ID
            lesson_id: Lesson ID
            score: Score achieved (0-100)

        Returns:
            LessonGrade: The created or updated grade record
        """
        grade_letter = GradingService.calculate_grade(score)

        # Check if grade already exists
        existing_grade = LessonGrade.query.filter_by(
            user_id=user_id,
            lesson_id=lesson_id
        ).first()

        if existing_grade:
            # Update if new score is better
            existing_grade.attempts_count += 1
            if score > (existing_grade.best_attempt_score or 0):
                existing_grade.best_attempt_score = score
                # Update grade if improved
                new_grade = GradingService.calculate_grade(score)
                if new_grade < existing_grade.grade:  # A < B < C < D < F in ASCII
                    existing_grade.grade = new_grade
                    existing_grade.score = score
            existing_grade.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            return existing_grade
        else:
            # Create new grade
            lesson_grade = LessonGrade(
                user_id=user_id,
                lesson_id=lesson_id,
                grade=grade_letter,
                score=score,
                attempts_count=1,
                best_attempt_score=score
            )
            db.session.add(lesson_grade)
            db.session.commit()
            return lesson_grade


class StatisticsService:
    """Service for managing user statistics"""

    @staticmethod
    def get_or_create_statistics(user_id: int) -> UserStatistics:
        """Get or create user statistics record"""
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if not stats:
            stats = UserStatistics(user_id=user_id)
            db.session.add(stats)
            db.session.commit()
        return stats

    @staticmethod
    def update_on_lesson_completion(user_id: int, score: float, grade: str) -> UserStatistics:
        """
        Update user statistics after lesson completion

        Args:
            user_id: User ID
            score: Score achieved
            grade: Letter grade (A, B, C, D, F)

        Returns:
            UserStatistics: Updated statistics record
        """
        stats = StatisticsService.get_or_create_statistics(user_id)

        # Update overall stats
        stats.total_lessons_completed += 1
        stats.total_score_sum += score

        # Update grade counts
        grade_field = f'grade_{grade.lower()}_count'
        current_count = getattr(stats, grade_field, 0)
        setattr(stats, grade_field, current_count + 1)

        # Update streak
        today = date.today()
        if stats.last_activity_date:
            days_diff = (today - stats.last_activity_date).days
            if days_diff == 1:
                # Continue streak
                stats.current_streak_days += 1
                if stats.current_streak_days > stats.longest_streak_days:
                    stats.longest_streak_days = stats.current_streak_days
            elif days_diff > 1:
                # Reset streak
                stats.current_streak_days = 1
            # else: same day, no change
        else:
            # First activity
            stats.current_streak_days = 1
            stats.longest_streak_days = 1

        stats.last_activity_date = today
        stats.updated_at = datetime.now(timezone.utc)

        db.session.commit()
        return stats

    @staticmethod
    def update_badge_stats(user_id: int) -> None:
        """Update badge-related statistics"""
        stats = StatisticsService.get_or_create_statistics(user_id)

        # Count total badges
        total_badges = UserAchievement.query.filter_by(user_id=user_id).count()

        # Sum badge points
        total_points = db.session.query(func.sum(Achievement.xp_reward)).join(
            UserAchievement,
            Achievement.id == UserAchievement.achievement_id
        ).filter(UserAchievement.user_id == user_id).scalar() or 0

        stats.total_badges = total_badges
        stats.total_badge_points = total_points
        stats.updated_at = datetime.now(timezone.utc)

        db.session.commit()


class AchievementService:
    """Service for checking and awarding achievements based on statistics"""

    @staticmethod
    def check_grade_achievements(user_id: int, stats: UserStatistics) -> List[Achievement]:
        """
        Check and award grade-based achievements

        Args:
            user_id: User ID
            stats: User statistics

        Returns:
            List of newly awarded achievements
        """
        newly_awarded = []

        # Define grade-based achievement requirements
        # These should match achievement codes in the database
        grade_achievements = [
            ('first_perfect', 'grade_a_count', 1),   # First A grade
            ('excellent_5', 'grade_a_count', 5),     # 5 A grades
            ('perfect_10', 'grade_a_count', 10),     # 10 A grades
            ('perfect_25', 'grade_a_count', 25),     # 25 A grades
            ('good_student', 'grade_b_count', 10),   # 10 B grades
        ]

        for achievement_code, stat_field, required_count in grade_achievements:
            current_count = getattr(stats, stat_field, 0)

            if current_count >= required_count:
                # Check if user already has this achievement
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                existing = UserAchievement.query.filter_by(
                    user_id=user_id,
                    achievement_id=achievement.id
                ).first()

                if not existing:
                    # Award the achievement
                    user_achievement = UserAchievement(
                        user_id=user_id,
                        achievement_id=achievement.id,
                        earned_at=datetime.now(timezone.utc)
                    )
                    db.session.add(user_achievement)
                    newly_awarded.append(achievement)

        if newly_awarded:
            db.session.commit()
            # Update badge statistics
            StatisticsService.update_badge_stats(user_id)

        return newly_awarded

    @staticmethod
    def check_streak_achievements(user_id: int, stats: UserStatistics) -> List[Achievement]:
        """
        Check and award streak-based achievements

        Args:
            user_id: User ID
            stats: User statistics

        Returns:
            List of newly awarded achievements
        """
        newly_awarded = []

        # Define streak-based achievement requirements
        streak_achievements = [
            ('streak_3', 3),
            ('streak_7', 7),
            ('streak_14', 14),
            ('streak_30', 30),
        ]

        for achievement_code, required_days in streak_achievements:
            if stats.current_streak_days >= required_days:
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                existing = UserAchievement.query.filter_by(
                    user_id=user_id,
                    achievement_id=achievement.id
                ).first()

                if not existing:
                    user_achievement = UserAchievement(
                        user_id=user_id,
                        achievement_id=achievement.id,
                        earned_at=datetime.now(timezone.utc)
                    )
                    db.session.add(user_achievement)
                    newly_awarded.append(achievement)

        if newly_awarded:
            db.session.commit()
            StatisticsService.update_badge_stats(user_id)

        return newly_awarded

    @staticmethod
    def check_all_achievements(user_id: int) -> Dict[str, List[Achievement]]:
        """
        Check all possible achievements for a user

        Args:
            user_id: User ID

        Returns:
            Dictionary with categories of newly awarded achievements
        """
        stats = StatisticsService.get_or_create_statistics(user_id)

        grade_achievements = AchievementService.check_grade_achievements(user_id, stats)
        streak_achievements = AchievementService.check_streak_achievements(user_id, stats)

        return {
            'grade': grade_achievements,
            'streak': streak_achievements,
            'all': grade_achievements + streak_achievements
        }


def process_lesson_completion(user_id: int, lesson_id: int, score: float) -> Dict:
    """
    Complete workflow for lesson completion: assign grade, update stats, check achievements

    Args:
        user_id: User ID
        lesson_id: Lesson ID
        score: Score achieved (0-100)

    Returns:
        Dictionary with grade, statistics, and newly earned achievements
    """
    # 1. Assign grade
    lesson_grade = GradingService.assign_lesson_grade(user_id, lesson_id, score)

    # 2. Update statistics
    stats = StatisticsService.update_on_lesson_completion(user_id, score, lesson_grade.grade)

    # 3. Check for new achievements
    new_achievements = AchievementService.check_all_achievements(user_id)

    return {
        'grade': lesson_grade.grade,
        'grade_name': lesson_grade.grade_name,
        'score': score,
        'statistics': {
            'total_lessons': stats.total_lessons_completed,
            'average_score': stats.average_score,
            'current_streak': stats.current_streak_days,
            'longest_streak': stats.longest_streak_days,
            'total_badges': stats.total_badges,
        },
        'new_achievements': [
            {
                'id': a.id,
                'name': a.name,
                'description': a.description,
                'icon': a.icon,
                'xp': a.xp_reward
            }
            for a in new_achievements['all']
        ]
    }
