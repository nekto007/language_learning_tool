# app/achievements/services.py
"""
Service for managing lesson grades, user statistics, and achievement tracking
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.achievements.models import LessonGrade, UserStatistics
from app.study.models import Achievement, UserAchievement
from app.utils.db import db
from config.settings import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)


def grant_achievement(
    user_id: int,
    achievement_id: int,
    earned_at: Optional[datetime] = None,
) -> Tuple[UserAchievement, bool]:
    """Idempotent insert of UserAchievement, safe under concurrent calls.

    Returns (user_achievement, is_new). If a concurrent writer wins the race
    and the unique constraint fires on our INSERT, we roll back the savepoint
    and return the existing row instead of raising.
    """
    existing = UserAchievement.query.filter_by(
        user_id=user_id, achievement_id=achievement_id,
    ).first()
    if existing is not None:
        return existing, False

    ua = UserAchievement(
        user_id=user_id,
        achievement_id=achievement_id,
        earned_at=earned_at or datetime.now(timezone.utc),
    )
    try:
        with db.session.begin_nested():
            db.session.add(ua)
    except IntegrityError:
        existing = UserAchievement.query.filter_by(
            user_id=user_id, achievement_id=achievement_id,
        ).first()
        if existing is None:
            raise
        return existing, False
    return ua, True


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
            db.session.flush()
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

        # Award daily streak coin
        from app.achievements.streak_service import earn_daily_coin
        earn_daily_coin(user_id)

        db.session.commit()
        return stats

    @staticmethod
    def update_badge_stats(user_id: int, commit: bool = True) -> None:
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

        if commit:
            db.session.commit()
        else:
            db.session.flush()


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

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_awarded.append(achievement)

                    # Send notification
                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, achievement.name, achievement.icon)
                    except Exception as e:
                        logger.exception("Failed to send achievement notification for user %s: %s", user_id, e)

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

        # Define streak-based achievement requirements — codes must match seed.py
        streak_achievements = [
            ('daily_streak_3', 3),
            ('daily_streak_7', 7),
            ('daily_streak_14', 14),
            ('daily_streak_30', 30),
            ('daily_streak_60', 60),
            ('daily_streak_100', 100),
        ]

        for achievement_code, required_days in streak_achievements:
            if stats.current_streak_days >= required_days:
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_awarded.append(achievement)

                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, achievement.name, achievement.icon)
                    except Exception as e:
                        logger.exception("Failed to send streak achievement notification for user %s: %s", user_id, e)

        if newly_awarded:
            db.session.commit()
            StatisticsService.update_badge_stats(user_id)

        return newly_awarded

    @staticmethod
    def check_lesson_achievements(user_id: int, stats: UserStatistics) -> List[Achievement]:
        """Check and award lesson-count-based achievements.

        Codes must match seed.py: first_lesson, lessons_5, lessons_10,
        lessons_25, lessons_50, lessons_100.
        """
        newly_awarded = []

        lesson_achievements = [
            ('first_lesson', 1),
            ('lessons_5', 5),
            ('lessons_10', 10),
            ('lessons_25', 25),
            ('lessons_50', 50),
            ('lessons_100', 100),
        ]

        for achievement_code, required_count in lesson_achievements:
            if stats.total_lessons_completed >= required_count:
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_awarded.append(achievement)

                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, achievement.name, achievement.icon)
                    except Exception as e:
                        logger.exception("Failed to send lesson achievement notification for user %s: %s", user_id, e)

        if newly_awarded:
            db.session.commit()
            StatisticsService.update_badge_stats(user_id)

        return newly_awarded

    @staticmethod
    def check_book_achievements(user_id: int, stats: UserStatistics) -> List[Achievement]:
        """Check and award book-reading achievements.

        Codes must match seed.py: first_book, books_5, books_10, chapter_marathon.
        chapter_marathon: awarded when total_chapters_read >= 50.
        """
        newly_awarded = []

        book_achievements = [
            ('first_book', stats.total_books_completed, 1),
            ('books_5', stats.total_books_completed, 5),
            ('books_10', stats.total_books_completed, 10),
            ('chapter_marathon', stats.total_chapters_read, 50),
        ]

        for achievement_code, current_value, required_count in book_achievements:
            if current_value >= required_count:
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_awarded.append(achievement)

                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, achievement.name, achievement.icon)
                    except Exception as e:
                        logger.exception("Failed to send book achievement notification for user %s: %s", user_id, e)

        if newly_awarded:
            db.session.commit()
            StatisticsService.update_badge_stats(user_id)

        return newly_awarded

    @staticmethod
    def check_card_achievements(user_id: int, stats: UserStatistics) -> List[Achievement]:
        """Check and award SRS card-review achievements.

        Codes must match seed.py: cards_100, cards_500, cards_1000.
        """
        newly_awarded = []

        card_achievements = [
            ('cards_100', 100),
            ('cards_500', 500),
            ('cards_1000', 1000),
        ]

        reviewed = stats.total_cards_reviewed or 0
        for achievement_code, required_count in card_achievements:
            if reviewed >= required_count:
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_awarded.append(achievement)

                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, achievement.name, achievement.icon)
                    except Exception as e:
                        logger.exception("Failed to send card achievement notification for user %s: %s", user_id, e)

        if newly_awarded:
            db.session.commit()
            StatisticsService.update_badge_stats(user_id)

        return newly_awarded

    @staticmethod
    def check_level_achievements(user_id: int, stats: UserStatistics) -> List[Achievement]:
        """Check and award XP-level-based achievements.

        Codes must match seed.py: level_10, level_25, level_50.
        Current level is derived from stats.total_xp via get_level_info.
        """
        from app.achievements.xp_service import get_level_info

        newly_awarded = []

        level_info = get_level_info(int(stats.total_xp or 0))
        current_level = level_info.current_level

        level_achievements = [
            ('level_10', 10),
            ('level_25', 25),
            ('level_50', 50),
        ]

        for achievement_code, required_level in level_achievements:
            if current_level >= required_level:
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_awarded.append(achievement)

                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, achievement.name, achievement.icon)
                    except Exception as e:
                        logger.exception("Failed to send level achievement notification for user %s: %s", user_id, e)

        if newly_awarded:
            db.session.flush()
            StatisticsService.update_badge_stats(user_id, commit=False)

        return newly_awarded

    @staticmethod
    def check_words_learned_achievements(user_id: int) -> List[Achievement]:
        """Check and award word-learning achievements.

        "Learned" means UserWord.status == 'review' (all card directions
        graduated from the initial learning phase).

        Codes: words_learned_100 (≥100 review words),
               words_learned_500 (≥500 review words).
        """
        from app.study.models import UserWord
        from sqlalchemy import func

        review_count = db.session.query(func.count(UserWord.id)).filter(
            UserWord.user_id == user_id,
            UserWord.status == 'review',
        ).scalar() or 0

        newly_awarded = []

        words_achievements = [
            ('words_learned_100', 100),
            ('words_learned_500', 500),
        ]

        for achievement_code, required_count in words_achievements:
            if review_count >= required_count:
                achievement = Achievement.query.filter_by(code=achievement_code).first()
                if not achievement:
                    continue

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_awarded.append(achievement)

                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, achievement.name, achievement.icon)
                    except Exception as e:
                        logger.exception(
                            "Failed to send words-learned achievement notification "
                            "for user %s: %s", user_id, e,
                        )

        if newly_awarded:
            db.session.flush()
            StatisticsService.update_badge_stats(user_id, commit=False)

        return newly_awarded

    @staticmethod
    def check_matching_achievements(
        user_id: int,
        score_percentage: Optional[float] = None,
        duration_sec: Optional[int] = None,
    ) -> List[Achievement]:
        """Check and award matching-game achievements.

        Codes: matching_first (≥1 game completed), matching_perfect (100%
        accuracy), matching_speed (completed in <60 s).

        score_percentage / duration_sec are the current-game values.  When
        called without per-game context (e.g. from check_all_achievements),
        past GameScore rows are queried for backfill eligibility.
        """
        from app.study.models import GameScore
        from sqlalchemy import func

        newly_awarded = []

        game_count = db.session.query(func.count(GameScore.id)).filter(
            GameScore.user_id == user_id,
            GameScore.game_type == 'matching',
        ).scalar() or 0

        if game_count >= 1:
            ach = Achievement.query.filter_by(code='matching_first').first()
            if ach:
                _, is_new = grant_achievement(user_id, ach.id)
                if is_new:
                    newly_awarded.append(ach)
                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, ach.name, ach.icon)
                    except Exception as e:
                        logger.exception(
                            "Failed to send matching_first notification for user %s: %s", user_id, e
                        )

        perfect_eligible = (score_percentage is not None and score_percentage >= 100.0) or (
            db.session.query(GameScore.id).filter(
                GameScore.user_id == user_id,
                GameScore.game_type == 'matching',
                GameScore.pairs_matched == GameScore.total_pairs,
                GameScore.total_pairs > 0,
            ).first() is not None
        )
        if perfect_eligible:
            ach = Achievement.query.filter_by(code='matching_perfect').first()
            if ach:
                _, is_new = grant_achievement(user_id, ach.id)
                if is_new:
                    newly_awarded.append(ach)
                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, ach.name, ach.icon)
                    except Exception as e:
                        logger.exception(
                            "Failed to send matching_perfect notification for user %s: %s", user_id, e
                        )

        speed_eligible = (duration_sec is not None and 0 < duration_sec < 60) or (
            db.session.query(GameScore.id).filter(
                GameScore.user_id == user_id,
                GameScore.game_type == 'matching',
                GameScore.time_taken > 0,
                GameScore.time_taken < 60,
            ).first() is not None
        )
        if speed_eligible:
            ach = Achievement.query.filter_by(code='matching_speed').first()
            if ach:
                _, is_new = grant_achievement(user_id, ach.id)
                if is_new:
                    newly_awarded.append(ach)
                    try:
                        from app.notifications.services import notify_achievement
                        notify_achievement(user_id, ach.name, ach.icon)
                    except Exception as e:
                        logger.exception(
                            "Failed to send matching_speed notification for user %s: %s", user_id, e
                        )

        if newly_awarded:
            db.session.commit()
            StatisticsService.update_badge_stats(user_id)

        return newly_awarded

    @staticmethod
    def check_quiz_achievements(
        user_id: int,
        score: Optional[float] = None,
        total_questions: Optional[int] = None,
        time_taken: Optional[int] = None,
        has_streak: bool = False,
    ) -> List[Achievement]:
        """Award quiz-family achievements.

        Codes: first_quiz, quiz_master_10, quiz_master_50, high_score_90,
        speed_demon, quiz_streak_5, early_bird, night_owl, perfect_score.

        Per-game parameters (score, total_questions, time_taken, has_streak)
        are used when called from the quiz submit handler.  When called
        without context (e.g. from check_all_achievements) the method falls
        back to querying historical GameScore / QuizResult rows.
        """
        from app.study.models import GameScore, QuizResult

        codes_to_award: set[str] = set()

        total_quizzes = (
            db.session.query(func.count(GameScore.id))
            .filter(GameScore.user_id == user_id, GameScore.game_type == 'quiz')
            .scalar() or 0
        )

        if total_quizzes >= 1:
            codes_to_award.add('first_quiz')
        if total_quizzes >= 10:
            codes_to_award.add('quiz_master_10')
        if total_quizzes >= 50:
            codes_to_award.add('quiz_master_50')

        # high_score_90: current game OR historical
        current_high90 = (
            score is not None
            and (total_questions or 0) >= 10
            and score >= 90.0
        )
        historical_high90 = db.session.query(GameScore.id).filter(
            GameScore.user_id == user_id,
            GameScore.game_type == 'quiz',
            GameScore.total_questions >= 10,
            (GameScore.correct_answers * 100.0 / GameScore.total_questions) >= 90,
        ).first() is not None
        if current_high90 or historical_high90:
            codes_to_award.add('high_score_90')

        # perfect_score: 100% in any lesson or quiz game
        current_perfect = score is not None and score >= 100.0
        historical_perfect = db.session.query(GameScore.id).filter(
            GameScore.user_id == user_id,
            GameScore.total_questions > 0,
            GameScore.correct_answers == GameScore.total_questions,
        ).first() is not None
        if current_perfect or historical_perfect:
            codes_to_award.add('perfect_score')

        # speed_demon: quiz of 10+ questions in ≤2 minutes
        current_speed = (
            (total_questions or 0) >= 10 and (time_taken or 9999) <= 120
        )
        historical_speed = db.session.query(GameScore.id).filter(
            GameScore.user_id == user_id,
            GameScore.game_type == 'quiz',
            GameScore.total_questions >= 10,
            GameScore.time_taken > 0,
            GameScore.time_taken <= 120,
        ).first() is not None
        if current_speed or historical_speed:
            codes_to_award.add('speed_demon')

        # quiz_streak_5: 5+ consecutive correct in a quiz
        # Per-game: has_streak flag; historical: any quiz with correct_answers >= 5
        historical_streak5 = db.session.query(GameScore.id).filter(
            GameScore.user_id == user_id,
            GameScore.game_type == 'quiz',
            GameScore.correct_answers >= 5,
        ).first() is not None
        if has_streak or historical_streak5:
            codes_to_award.add('quiz_streak_5')

        # early_bird / night_owl: time of earliest/latest quiz session
        now = datetime.now(timezone.utc)
        early_row = db.session.query(GameScore.date_achieved).filter(
            GameScore.user_id == user_id,
            GameScore.game_type == 'quiz',
            func.extract('hour', GameScore.date_achieved) < 8,
        ).first()
        if early_row:
            codes_to_award.add('early_bird')

        night_row = db.session.query(GameScore.date_achieved).filter(
            GameScore.user_id == user_id,
            GameScore.game_type == 'quiz',
            func.extract('hour', GameScore.date_achieved) >= 23,
        ).first()
        if night_row:
            codes_to_award.add('night_owl')

        # Also check current invocation time for first-quiz context
        if not early_row and time_taken is not None and now.hour < 8:
            codes_to_award.add('early_bird')
        if not night_row and time_taken is not None and now.hour >= 23:
            codes_to_award.add('night_owl')

        return AchievementService._award_badges(user_id, codes_to_award)

    @staticmethod
    def check_perfect_quiz_achievements(
        user_id: int,
        score: Optional[float] = None,
    ) -> List[Achievement]:
        """Award perfect_quiz badge.

        Codes: perfect_quiz ("Пройдите квиз без ошибок").

        score is the current-game percentage (0-100). When called without
        per-game context (e.g. from check_all_achievements), past GameScore
        rows are queried for a perfect quiz.
        """
        from app.study.models import GameScore

        codes_to_award: set[str] = set()

        perfect_eligible = (score is not None and score >= 100.0) or (
            db.session.query(GameScore.id).filter(
                GameScore.user_id == user_id,
                GameScore.game_type == 'quiz',
                GameScore.correct_answers == GameScore.total_questions,
                GameScore.total_questions > 0,
            ).first() is not None
        )
        if perfect_eligible:
            codes_to_award.add('perfect_quiz')

        return AchievementService._award_badges(user_id, codes_to_award)

    @staticmethod
    def check_perfect_session_achievements(
        user_id: int,
        correct_answers: Optional[int] = None,
        total_answered: Optional[int] = None,
    ) -> List[Achievement]:
        """Award perfect_session badge.

        Codes: perfect_session ("Завершите сессию карточек с 100% правильных ответов").

        correct_answers / total_answered are the current-session values. When
        called without per-session context (e.g. from check_all_achievements),
        past StudySession rows are queried for a perfect session.
        """
        from app.study.models import StudySession

        codes_to_award: set[str] = set()

        if correct_answers is not None and total_answered is not None:
            perfect_eligible = total_answered > 0 and correct_answers == total_answered
        else:
            perfect_eligible = (
                db.session.query(StudySession.id).filter(
                    StudySession.user_id == user_id,
                    StudySession.correct_answers > 0,
                    StudySession.incorrect_answers == 0,
                ).first() is not None
            )
        if perfect_eligible:
            codes_to_award.add('perfect_session')

        return AchievementService._award_badges(user_id, codes_to_award)

    @staticmethod
    def check_mission_achievements(
        user_id: int,
        mission_type: str,
        completion_time: Optional[datetime] = None,
        duration_minutes: Optional[int] = None,
        tz: str = DEFAULT_TIMEZONE,
    ) -> List[Achievement]:
        """Award daily-plan mission-specific achievements after a plan completion.

        Evaluates:
        - mission_first: first-ever full plan completion
        - mission_progress_5 / mission_repair_5 / mission_reading_5:
          5 completions of the corresponding mission type
        - mission_week_perfect: 7 consecutive days of plan completions
        - mission_early_bird: plan completed before 09:00 local time
        - mission_night_owl: plan completed at or after 22:00 local time
        - mission_variety_3: all three mission types completed within last 7 days
        - mission_speed_demon: duration from first to last phase < 30 minutes

        Idempotent: never re-awards an existing badge (UserAchievement unique
        constraint on user_id + achievement_id is respected).
        """
        import pytz

        from app.achievements.models import StreakEvent
        from app.daily_plan.models import MissionType

        if isinstance(mission_type, MissionType):
            mission_type_value = mission_type.value
        else:
            mission_type_value = str(mission_type)

        if completion_time is None:
            completion_time = datetime.now(timezone.utc)
        elif completion_time.tzinfo is None:
            completion_time = completion_time.replace(tzinfo=timezone.utc)

        try:
            tz_obj = pytz.timezone(tz)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone(DEFAULT_TIMEZONE)

        local_dt = completion_time.astimezone(tz_obj)
        today_local = local_dt.date()

        codes_to_award: set[str] = {'mission_first'}

        type_counts = AchievementService._count_mission_completions_by_type(user_id)
        if type_counts.get('progress', 0) >= 5:
            codes_to_award.add('mission_progress_5')
        if type_counts.get('repair', 0) >= 5:
            codes_to_award.add('mission_repair_5')
        if type_counts.get('reading', 0) >= 5:
            codes_to_award.add('mission_reading_5')

        if AchievementService._is_perfect_week(user_id, today_local):
            codes_to_award.add('mission_week_perfect')

        if local_dt.hour < 9:
            codes_to_award.add('mission_early_bird')
        if local_dt.hour >= 22:
            codes_to_award.add('mission_night_owl')

        recent_types = AchievementService._get_recent_mission_types(
            user_id, today_local, days=7,
        )
        if recent_types >= {'progress', 'repair', 'reading'}:
            codes_to_award.add('mission_variety_3')

        if duration_minutes is not None and duration_minutes < 30:
            codes_to_award.add('mission_speed_demon')

        return AchievementService._award_badges(user_id, codes_to_award)

    @staticmethod
    def _count_mission_completions_by_type(user_id: int) -> Dict[str, int]:
        """Count completed plans per mission type.

        Joins `plan_completed` StreakEvents to `mission_selected` events by
        date. Returns a dict like {'progress': 7, 'repair': 3, 'reading': 1}.
        """
        from app.achievements.models import StreakEvent

        completed_dates = {
            e.event_date
            for e in StreakEvent.query.filter_by(
                user_id=user_id, event_type='plan_completed',
            )
        }
        if not completed_dates:
            return {}

        counts: Dict[str, int] = {}
        selected_events = StreakEvent.query.filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == 'mission_selected',
            StreakEvent.event_date.in_(completed_dates),
        )
        for event in selected_events:
            mt = (event.details or {}).get('mission_type')
            if mt:
                counts[mt] = counts.get(mt, 0) + 1
        return counts

    @staticmethod
    def _is_perfect_week(user_id: int, today_local: date) -> bool:
        """Return True if a plan was completed on each of the last 7 days."""
        from app.achievements.models import StreakEvent

        required_dates = {today_local - timedelta(days=i) for i in range(7)}
        completed_dates = {
            e.event_date
            for e in StreakEvent.query.filter(
                StreakEvent.user_id == user_id,
                StreakEvent.event_type == 'plan_completed',
                StreakEvent.event_date.in_(required_dates),
            )
        }
        return required_dates.issubset(completed_dates)

    @staticmethod
    def _get_recent_mission_types(
        user_id: int, today_local: date, days: int = 7,
    ) -> set[str]:
        """Return the set of mission types completed in the last `days` days."""
        from app.achievements.models import StreakEvent

        from_date = today_local - timedelta(days=days - 1)

        completed_dates = {
            e.event_date
            for e in StreakEvent.query.filter(
                StreakEvent.user_id == user_id,
                StreakEvent.event_type == 'plan_completed',
                StreakEvent.event_date >= from_date,
                StreakEvent.event_date <= today_local,
            )
        }
        if not completed_dates:
            return set()

        types: set[str] = set()
        for event in StreakEvent.query.filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == 'mission_selected',
            StreakEvent.event_date.in_(completed_dates),
        ):
            mt = (event.details or {}).get('mission_type')
            if mt:
                types.add(mt)
        return types

    @staticmethod
    def _award_badges(user_id: int, codes: set[str]) -> List[Achievement]:
        """Award each listed badge if not already owned. Flushes on change."""
        if not codes:
            return []

        achievements = Achievement.query.filter(Achievement.code.in_(codes)).all()
        if not achievements:
            return []

        by_id = {a.id: a for a in achievements}
        already_owned_ids = {
            ua.achievement_id
            for ua in UserAchievement.query.filter(
                UserAchievement.user_id == user_id,
                UserAchievement.achievement_id.in_(by_id.keys()),
            )
        }

        newly_awarded: List[Achievement] = []
        for achievement in achievements:
            if achievement.id in already_owned_ids:
                continue
            _, is_new = grant_achievement(user_id, achievement.id)
            if not is_new:
                continue
            newly_awarded.append(achievement)

            try:
                from app.notifications.services import notify_achievement
                notify_achievement(user_id, achievement.name, achievement.icon)
            except Exception:
                logger.exception(
                    "Failed to send mission badge notification for user %s "
                    "(badge %s)", user_id, achievement.code,
                )

        if newly_awarded:
            db.session.flush()
            StatisticsService.update_badge_stats(user_id, commit=False)

        return newly_awarded

    @staticmethod
    def get_unseen_badges(user_id: int) -> List[Dict]:
        """Return badges awarded to the user that have not yet been displayed.

        "Unseen" means UserAchievement.seen_at IS NULL — the user has not
        visited the dashboard since this badge was earned.

        Returns a list of dicts (safe for Jinja) ordered oldest-first so the
        popup stacks them naturally.
        """
        rows = (
            db.session.query(UserAchievement, Achievement)
            .join(Achievement, Achievement.id == UserAchievement.achievement_id)
            .filter(
                UserAchievement.user_id == user_id,
                UserAchievement.seen_at.is_(None),
            )
            .order_by(UserAchievement.earned_at.asc())
            .all()
        )
        return [
            {
                'user_achievement_id': ua.id,
                'id': a.id,
                'code': a.code,
                'name': a.name,
                'description': a.description,
                'icon': a.icon,
                'xp_reward': a.xp_reward,
                'category': a.category,
            }
            for ua, a in rows
        ]

    @staticmethod
    def mark_badges_seen(user_id: int, user_achievement_ids: Optional[List[int]] = None) -> int:
        """Stamp seen_at = now() on the user's unseen badges.

        If `user_achievement_ids` is None, marks every unseen badge owned by
        the user. Returns the number of rows updated. Commits on success.
        """
        now = datetime.now(timezone.utc)
        query = UserAchievement.query.filter(
            UserAchievement.user_id == user_id,
            UserAchievement.seen_at.is_(None),
        )
        if user_achievement_ids is not None:
            if not user_achievement_ids:
                return 0
            query = query.filter(UserAchievement.id.in_(user_achievement_ids))

        updated = query.update({UserAchievement.seen_at: now}, synchronize_session=False)
        if updated:
            db.session.commit()
        return updated

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
        lesson_achievements = AchievementService.check_lesson_achievements(user_id, stats)
        book_achievements = AchievementService.check_book_achievements(user_id, stats)
        card_achievements = AchievementService.check_card_achievements(user_id, stats)
        level_achievements = AchievementService.check_level_achievements(user_id, stats)
        words_achievements = AchievementService.check_words_learned_achievements(user_id)
        matching_achievements = AchievementService.check_matching_achievements(user_id)
        quiz_achievements = AchievementService.check_quiz_achievements(user_id)
        perfect_quiz_achievements = AchievementService.check_perfect_quiz_achievements(user_id)
        perfect_session_achievements = AchievementService.check_perfect_session_achievements(user_id)

        all_new = (grade_achievements + streak_achievements + lesson_achievements
                   + book_achievements + card_achievements + level_achievements
                   + words_achievements + matching_achievements
                   + quiz_achievements + perfect_quiz_achievements
                   + perfect_session_achievements)
        if all_new:
            db.session.commit()
            StatisticsService.update_badge_stats(user_id)
        return {
            'grade': grade_achievements,
            'streak': streak_achievements,
            'lessons': lesson_achievements,
            'books': book_achievements,
            'cards': card_achievements,
            'levels': level_achievements,
            'words': words_achievements,
            'matching': matching_achievements,
            'quiz': quiz_achievements,
            'perfect_quiz': perfect_quiz_achievements,
            'perfect_session': perfect_session_achievements,
            'all': all_new,
        }


def check_listening_achievements(user_id: int, db_session=None) -> List[Achievement]:
    """Award listening-related achievements after a ListeningAttempt is created.

    Checks:
    - listening_first: user has at least 1 ListeningAttempt
    - listening_week: 7-day consecutive listening streak
    - listening_master: avg score >= 90 over last 10 ListeningAttempt rows
    """
    from app.curriculum.models import ListeningAttempt
    from app.achievements.streak_service import get_listening_streak
    from sqlalchemy import func

    session = db_session if db_session is not None else db.session

    codes_to_award: set[str] = set()

    total = session.query(func.count(ListeningAttempt.id)).filter(
        ListeningAttempt.user_id == user_id,
    ).scalar() or 0

    if total >= 1:
        codes_to_award.add('listening_first')

    streak = get_listening_streak(user_id, db_session=session)
    if streak >= 7:
        codes_to_award.add('listening_week')

    if total >= 10:
        from sqlalchemy import select
        subq = (
            select(ListeningAttempt.score.label('score'))
            .where(ListeningAttempt.user_id == user_id)
            .order_by(ListeningAttempt.created_at.desc())
            .limit(10)
            .subquery()
        )
        last_10_avg = session.query(func.avg(subq.c.score)).scalar() or 0.0
        if last_10_avg >= 90.0:
            codes_to_award.add('listening_master')

    return AchievementService._award_badges(user_id, codes_to_award)


def check_writing_achievements(user_id: int, db_session=None) -> List[Achievement]:
    """Award writing-related achievements after a UserWritingAttempt is saved.

    Checks:
    - writing_first: user has at least 1 UserWritingAttempt
    - writing_streak_3: 3 consecutive days with writing attempts
    - writing_fluent: any attempt with word_count >= 100
    """
    from app.curriculum.models import UserWritingAttempt
    from app.achievements.streak_service import get_writing_streak
    from sqlalchemy import func

    session = db_session if db_session is not None else db.session

    codes_to_award: set[str] = set()

    total = session.query(func.count(UserWritingAttempt.id)).filter(
        UserWritingAttempt.user_id == user_id,
    ).scalar() or 0

    if total >= 1:
        codes_to_award.add('writing_first')

    streak = get_writing_streak(user_id, db_session=session)
    if streak >= 3:
        codes_to_award.add('writing_streak_3')

    fluent = session.query(UserWritingAttempt).filter(
        UserWritingAttempt.user_id == user_id,
        UserWritingAttempt.word_count >= 100,
    ).first()
    if fluent is not None:
        codes_to_award.add('writing_fluent')

    return AchievementService._award_badges(user_id, codes_to_award)


def check_speaking_achievements(user_id: int, db_session=None) -> List[Achievement]:
    """Award speaking-related achievements after a PronunciationAttempt is saved.

    Checks:
    - speaking_first: user has at least 1 PronunciationAttempt
    - speaking_streak_3: 3 consecutive days with pronunciation attempts
    - speaking_clear: 10 matched pronunciations total
    """
    from app.curriculum.models import PronunciationAttempt
    from app.achievements.streak_service import get_speaking_streak
    from sqlalchemy import func

    session = db_session if db_session is not None else db.session

    codes_to_award: set[str] = set()

    total = session.query(func.count(PronunciationAttempt.id)).filter(
        PronunciationAttempt.user_id == user_id,
    ).scalar() or 0

    if total >= 1:
        codes_to_award.add('speaking_first')

    streak = get_speaking_streak(user_id, db_session=session)
    if streak >= 3:
        codes_to_award.add('speaking_streak_3')

    matched_count = session.query(func.count(PronunciationAttempt.id)).filter(
        PronunciationAttempt.user_id == user_id,
        PronunciationAttempt.matched.is_(True),
    ).scalar() or 0
    if matched_count >= 10:
        codes_to_award.add('speaking_clear')

    return AchievementService._award_badges(user_id, codes_to_award)


def check_immersion_achievement(user_id: int, target_date, db_session=None, tz: str = 'UTC') -> List[Achievement]:
    """Award immersion_daily / immersion_week after all 4 skills practiced on target_date.

    target_date is the user's LOCAL date. tz must match the timezone used to derive it
    so that the UTC query window aligns correctly with the user's day.
    """
    from datetime import timedelta
    import pytz
    from app.curriculum.models import ListeningAttempt, UserWritingAttempt, PronunciationAttempt
    from app.books.reading_session import UserReadingSession
    from sqlalchemy import func

    session = db_session if db_session is not None else db.session

    try:
        tz_obj = pytz.timezone(tz)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.utc
    day_start_local = tz_obj.localize(datetime(target_date.year, target_date.month, target_date.day))
    day_start = day_start_local.astimezone(pytz.utc).replace(tzinfo=None)
    day_end = day_start + timedelta(days=1)
    day_start_tz = day_start.replace(tzinfo=timezone.utc)
    day_end_tz = day_end.replace(tzinfo=timezone.utc)

    has_listening = (session.query(func.count(ListeningAttempt.id)).filter(
        ListeningAttempt.user_id == user_id,
        ListeningAttempt.created_at >= day_start,
        ListeningAttempt.created_at < day_end,
    ).scalar() or 0) > 0

    has_writing = (session.query(func.count(UserWritingAttempt.id)).filter(
        UserWritingAttempt.user_id == user_id,
        UserWritingAttempt.created_at >= day_start,
        UserWritingAttempt.created_at < day_end,
    ).scalar() or 0) > 0

    has_speaking = (session.query(func.count(PronunciationAttempt.id)).filter(
        PronunciationAttempt.user_id == user_id,
        PronunciationAttempt.created_at >= day_start,
        PronunciationAttempt.created_at < day_end,
    ).scalar() or 0) > 0

    has_reading = (session.query(func.count(UserReadingSession.id)).filter(
        UserReadingSession.user_id == user_id,
        UserReadingSession.started_at >= day_start_tz,
        UserReadingSession.started_at < day_end_tz,
    ).scalar() or 0) > 0

    if not (has_listening and has_writing and has_speaking and has_reading):
        return []

    codes_to_award: set[str] = {'immersion_daily'}

    from app.achievements.streak_service import get_immersion_streak
    streak = get_immersion_streak(user_id, db_session=session, tz=tz)
    if streak >= 7:
        codes_to_award.add('immersion_week')

    return AchievementService._award_badges(user_id, codes_to_award)


_WEEKLY_MILESTONE_MAP: dict[int, tuple[str, int]] = {
    7: ('week_1', 100),
    28: ('week_4', 500),
    84: ('week_12', 2000),
}


def _week_label(weeks: int) -> str:
    """Return Russian plural for week count."""
    if weeks % 100 in range(11, 20):
        return 'недель'
    mod = weeks % 10
    if mod == 1:
        return 'неделя'
    if mod in (2, 3, 4):
        return 'недели'
    return 'недель'


def check_weekly_milestone_achievements(user_id: int, streak_days: int, db_session=None) -> List[Achievement]:
    """Grant weekly milestone achievement and bonus XP when streak hits 7/28/84 days.

    Idempotent: re-awarding is handled by grant_achievement's unique constraint.
    Returns list of newly granted Achievement objects.
    Caller must commit after this call (does flush only).
    """
    from app.achievements.xp_service import award_xp

    if streak_days not in _WEEKLY_MILESTONE_MAP:
        return []

    code, bonus_xp = _WEEKLY_MILESTONE_MAP[streak_days]
    weeks = streak_days // 7

    achievement = Achievement.query.filter_by(code=code).first()
    if achievement is None:
        return []

    _, is_new = grant_achievement(user_id, achievement.id)
    if not is_new:
        return []

    award_xp(user_id, bonus_xp, source=f'milestone_{code}')

    try:
        from app.notifications.services import create_notification
        create_notification(
            user_id, 'achievement',
            title=f'Серия {weeks} {_week_label(weeks)}! +{bonus_xp} XP',
            message=f'Вы занимаетесь {streak_days} дней подряд!',
            icon=achievement.icon,
            link='/study/stats',
        )
    except Exception:
        logger.exception(
            "Failed to send weekly milestone notification for user %s (streak=%s)",
            user_id, streak_days,
        )

    (db_session if db_session is not None else db.session).flush()
    return [achievement]


def check_challenge_achievements(user_id: int, db_session=None) -> List[Achievement]:
    """Award challenge-related achievements after a DailyChallengeCompletion is created.

    Checks:
    - challenge_first: user has at least 1 DailyChallengeCompletion
    - challenge_streak_7: 7-day consecutive challenge completion streak
    - challenger: 30 total challenge completions
    """
    from app.daily_plan.models import DailyChallenge, DailyChallengeCompletion
    from sqlalchemy import func
    import datetime as _dt

    session = db_session if db_session is not None else db.session

    codes_to_award: set[str] = set()

    total = session.query(func.count(DailyChallengeCompletion.id)).filter(
        DailyChallengeCompletion.user_id == user_id,
    ).scalar() or 0

    if total >= 1:
        codes_to_award.add('challenge_first')

    if total >= 30:
        codes_to_award.add('challenger')

    # Compute challenge streak inline (walk-backward same as get_challenge_streak).
    # Use user-local date: challenges are seeded per local day by maybe_auto_complete_challenge.
    from app.utils.time_utils import get_user_local_date
    today = get_user_local_date(user_id, db_session if db_session is not None else db)
    cutoff = today - _dt.timedelta(days=365)
    rows = (
        session.query(DailyChallenge.challenge_date)
        .join(DailyChallengeCompletion, DailyChallengeCompletion.challenge_id == DailyChallenge.id)
        .filter(
            DailyChallengeCompletion.user_id == user_id,
            DailyChallenge.challenge_date >= cutoff,
        )
        .distinct()
        .all()
    )
    active_dates = {row[0] for row in rows if row[0] is not None}
    streak = 0
    for offset in range(365):
        check_date = today - _dt.timedelta(days=offset)
        if check_date in active_dates:
            streak += 1
        elif offset == 0:
            continue  # today not done yet, check yesterday
        else:
            break

    if streak >= 7:
        codes_to_award.add('challenge_streak_7')

    return AchievementService._award_badges(user_id, codes_to_award)


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
