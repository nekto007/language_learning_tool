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

        # Award daily streak coin
        from app.achievements.streak_service import earn_daily_coin
        earn_daily_coin(user_id)

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
            StatisticsService.update_badge_stats(user_id)

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
