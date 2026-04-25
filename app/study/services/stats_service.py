"""
Stats Service - statistics and leaderboards

Responsibilities:
- User statistics
- Leaderboard generation
- Achievement tracking
"""
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, desc

from app.utils.db import db
from app.study.models import (
    UserWord, GameScore, QuizResult, Achievement, UserAchievement, StudySession,
    UserCardDirection
)
from app.achievements.models import UserStatistics
from app.auth.models import User


class StatsService:
    """Service for statistics and leaderboards"""

    @staticmethod
    def get_user_stats(user_id: int) -> Dict:
        """Get comprehensive user statistics"""
        # Word statistics
        word_stats = StatsService.get_user_word_stats(user_id)

        # Recent sessions
        recent_sessions = StudySession.query.filter_by(user_id=user_id) \
            .order_by(StudySession.start_time.desc()).limit(10).all()

        # Today's statistics
        today = datetime.now(timezone.utc).date()
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_sessions = StudySession.query.filter_by(user_id=user_id) \
            .filter(func.date(StudySession.start_time) == today).all()

        # Count unique cards studied today (not total review actions)
        # New cards: first_reviewed is today
        new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.first_reviewed >= today_start,
            UserCardDirection.first_reviewed.isnot(None)
        ).scalar() or 0

        # Review cards: last_reviewed is today but first_reviewed was before today
        reviews_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.last_reviewed >= today_start,
            UserCardDirection.first_reviewed < today_start,
            UserCardDirection.first_reviewed.isnot(None)
        ).scalar() or 0

        today_words_studied = new_cards_today + reviews_today
        today_time_spent = sum(session.duration for session in today_sessions)

        return {
            **word_stats,
            'mastery_percentage': int((word_stats['mastered'] / word_stats['total'] * 100) if word_stats['total'] > 0 else 0),
            'recent_sessions': recent_sessions,
            'study_streak': StatsService._get_streak(user_id),
            'today_words_studied': today_words_studied,
            'today_time_spent': today_time_spent
        }

    @staticmethod
    def _get_streak(user_id: int) -> int:
        try:
            from app.telegram.queries import get_current_streak
            return get_current_streak(user_id)
        except Exception:
            return 0

    @staticmethod
    def get_user_word_stats(user_id: int) -> Dict:
        """Get user's word learning statistics. Delegates to SRSStatsService."""
        from app.srs.stats_service import srs_stats_service
        stats = srs_stats_service.get_words_stats(user_id)
        return {
            'new': stats['new_count'],
            'learning': stats['learning_count'],
            'review': stats['review_count'],
            'mastered': stats['mastered_count'],
            'total': stats['total'],
        }

    @staticmethod
    def get_accuracy_trend(user_id: int, days: int = 30) -> List[Dict]:
        """Get daily accuracy (correct/total) for the last N days."""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        sessions = StudySession.query.filter(
            StudySession.user_id == user_id,
            StudySession.start_time >= start_date,
            StudySession.words_studied > 0,
        ).order_by(StudySession.start_time).all()

        daily: Dict[str, Dict] = {}
        for s in sessions:
            day = s.start_time.strftime('%Y-%m-%d')
            if day not in daily:
                daily[day] = {'correct': 0, 'total': 0}
            daily[day]['correct'] += (s.correct_answers or 0)
            daily[day]['total'] += (s.correct_answers or 0) + (s.incorrect_answers or 0)

        result = []
        for day_str in sorted(daily.keys()):
            d = daily[day_str]
            pct = round(d['correct'] / d['total'] * 100) if d['total'] > 0 else 0
            result.append({'date': day_str, 'accuracy': pct, 'total': d['total']})
        return result

    @staticmethod
    def get_mastered_over_time(user_id: int, days: int = 30) -> List[Dict]:
        """Get cumulative mastered words count per day for the last N days."""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Get cards that reached mastery (review state with interval >= threshold)
        mastered_cards = db.session.query(
            func.date(UserCardDirection.last_reviewed).label('day'),
            func.count(UserCardDirection.id)
        ).join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserCardDirection.state == 'review',
            UserCardDirection.interval >= UserWord.MASTERED_THRESHOLD_DAYS,
            UserCardDirection.last_reviewed >= start_date,
            UserCardDirection.last_reviewed.isnot(None),
        ).group_by(func.date(UserCardDirection.last_reviewed)).all()

        result = []
        for day, count in mastered_cards:
            result.append({'date': str(day), 'count': count})
        return sorted(result, key=lambda x: x['date'])

    @staticmethod
    def get_study_heatmap(user_id: int, days: int = 30) -> Dict:
        """Get study session counts by day of week and hour."""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        sessions = StudySession.query.filter(
            StudySession.user_id == user_id,
            StudySession.start_time >= start_date,
        ).all()

        # day_of_week: 0=Monday, 6=Sunday
        heatmap: Dict[int, Dict[int, int]] = {}
        for dow in range(7):
            heatmap[dow] = {}

        for s in sessions:
            dow = s.start_time.weekday()
            hour = s.start_time.hour
            heatmap[dow][hour] = heatmap[dow].get(hour, 0) + 1

        # Convert to list format for Chart.js
        day_names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        data_points = []
        for dow in range(7):
            for hour in range(24):
                count = heatmap[dow].get(hour, 0)
                if count > 0:
                    data_points.append({'x': hour, 'y': dow, 'v': count})

        return {'day_names': day_names, 'data': data_points}

    @staticmethod
    def get_leaderboard(game_type: str = 'all', period_days: int = 30, limit: int = 10) -> List[Dict]:
        """
        Get leaderboard for a game type

        Args:
            game_type: Type of game ('quiz', 'matching', 'all')
            period_days: Number of days to include
            limit: Maximum number of entries

        Returns:
            List of leaderboard entries with user info and scores
        """
        start_date = datetime.now(timezone.utc) - timedelta(days=period_days)

        if game_type == 'quiz':
            # Quiz leaderboard based on QuizResult
            results = db.session.query(
                User.id,
                User.username,
                func.count(QuizResult.id).label('games_played'),
                func.avg(QuizResult.score).label('avg_score'),
                func.max(QuizResult.score).label('best_score')
            ).join(
                QuizResult, User.id == QuizResult.user_id
            ).filter(
                QuizResult.completed_at >= start_date
            ).group_by(
                User.id, User.username
            ).order_by(
                desc('avg_score')
            ).limit(limit).all()

            return [
                {
                    'rank': idx + 1,
                    'user_id': r.id,
                    'username': r.username,
                    'games_played': r.games_played,
                    'avg_score': round(r.avg_score, 1),
                    'best_score': r.best_score
                }
                for idx, r in enumerate(results)
            ]

        elif game_type == 'matching':
            # Matching game leaderboard
            results = db.session.query(
                User.id,
                User.username,
                func.count(GameScore.id).label('games_played'),
                func.max(GameScore.score).label('best_score'),
                func.avg(GameScore.score).label('avg_score')
            ).join(
                GameScore, User.id == GameScore.user_id
            ).filter(
                GameScore.game_type == 'matching',
                GameScore.date_achieved >= start_date
            ).group_by(
                User.id, User.username
            ).order_by(
                desc('best_score')
            ).limit(limit).all()

            return [
                {
                    'rank': idx + 1,
                    'user_id': r.id,
                    'username': r.username,
                    'games_played': r.games_played,
                    'best_score': r.best_score,
                    'avg_score': round(r.avg_score, 1)
                }
                for idx, r in enumerate(results)
            ]

        else:  # 'all' - XP leaderboard
            results = db.session.query(
                User.id,
                User.username,
                UserStatistics.total_xp.label('total_xp')
            ).join(
                UserStatistics, User.id == UserStatistics.user_id
            ).order_by(
                desc(UserStatistics.total_xp)
            ).limit(limit).all()

            return [
                {
                    'rank': idx + 1,
                    'user_id': r.id,
                    'username': r.username,
                    'total_xp': r.total_xp or 0
                }
                for idx, r in enumerate(results)
            ]

    @staticmethod
    def get_user_achievements(user_id: int) -> Dict:
        """
        Get user's achievements

        Returns:
            Dictionary with earned and available achievements
        """
        # Get all achievements
        all_achievements = Achievement.query.order_by(Achievement.xp_reward.desc()).all()

        # Get user's earned achievements
        earned = db.session.query(
            Achievement, UserAchievement.earned_at
        ).join(
            UserAchievement, Achievement.id == UserAchievement.achievement_id
        ).filter(
            UserAchievement.user_id == user_id
        ).all()

        earned_ids = {a.id for a, _ in earned}

        return {
            'earned': [
                {
                    'id': a.id,
                    'code': a.code,
                    'name': a.name,
                    'description': a.description,
                    'icon': a.icon,
                    'xp_reward': a.xp_reward,
                    'earned_at': earned_at
                }
                for a, earned_at in earned
            ],
            'available': [
                {
                    'id': a.id,
                    'code': a.code,
                    'name': a.name,
                    'description': a.description,
                    'icon': a.icon,
                    'xp_reward': a.xp_reward
                }
                for a in all_achievements if a.id not in earned_ids
            ],
            'total_earned': len(earned),
            'total_available': len(all_achievements)
        }

    @staticmethod
    def check_and_award_achievements(user_id: int) -> List[Achievement]:
        """
        Check if user earned any new achievements

        Returns:
            List of newly earned Achievement objects
        """
        # This is a placeholder - full implementation would check various conditions
        # and award achievements based on user progress
        newly_earned = []

        # Example: Award "First Word" achievement
        word_count = UserWord.query.filter_by(user_id=user_id).count()
        if word_count >= 1:
            achievement = Achievement.query.filter_by(code='first_word').first()
            if achievement:
                from app.achievements.services import grant_achievement

                _, is_new = grant_achievement(user_id, achievement.id)
                if is_new:
                    newly_earned.append(achievement)

        if newly_earned:
            db.session.commit()

        return newly_earned

    @staticmethod
    def get_xp_leaderboard(limit: int = 100) -> List[Dict]:
        """
        Get XP leaderboard (all time)

        Args:
            limit: Maximum number of entries

        Returns:
            List of users with XP and level
        """
        results = db.session.query(
            User.id,
            User.username,
            UserStatistics.total_xp
        ).join(
            UserStatistics, User.id == UserStatistics.user_id
        ).order_by(
            desc(UserStatistics.total_xp)
        ).limit(limit).all()

        from app.achievements.xp_service import get_level_info

        return [
            {
                'id': row.id,
                'username': row.username,
                'total_xp': row.total_xp or 0,
                'level': get_level_info(row.total_xp or 0).current_level,
            }
            for row in results
        ]

    @staticmethod
    def get_achievement_leaderboard(limit: int = 100) -> List[Dict]:
        """
        Get achievement leaderboard (all time)

        Args:
            limit: Maximum number of entries

        Returns:
            List of users with achievement counts
        """
        results = db.session.query(
            User.id,
            User.username,
            func.count(UserAchievement.id).label('achievement_count')
        ).join(
            UserAchievement, User.id == UserAchievement.user_id
        ).group_by(
            User.id, User.username
        ).order_by(
            desc('achievement_count')
        ).limit(limit).all()

        return [
            {
                'id': row.id,
                'username': row.username,
                'achievement_count': row.achievement_count
            }
            for row in results
        ]

    @staticmethod
    def get_user_xp_rank(user_id: int) -> Optional[int]:
        """Get user's XP rank"""
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if not stats or not stats.total_xp:
            return None

        higher_xp_count = db.session.query(
            func.count(UserStatistics.id)
        ).filter(
            UserStatistics.total_xp > stats.total_xp
        ).scalar()

        return (higher_xp_count or 0) + 1

    @staticmethod
    def get_user_achievement_rank(user_id: int) -> Optional[int]:
        """Get user's achievement rank"""
        user_achievement_count = UserAchievement.query.filter_by(user_id=user_id).count()
        if user_achievement_count == 0:
            return None

        # Count users with more achievements
        higher_achievement_count = db.session.query(
            func.count(func.distinct(UserAchievement.user_id))
        ).filter(
            UserAchievement.user_id.in_(
                db.session.query(UserAchievement.user_id)
                .group_by(UserAchievement.user_id)
                .having(func.count(UserAchievement.id) > user_achievement_count)
            )
        ).scalar()

        return (higher_achievement_count or 0) + 1

    @staticmethod
    def get_achievements_by_category(user_id: int) -> Dict:
        """
        Get all achievements grouped by category with user's progress

        Returns:
            Dictionary with achievements by category and stats
        """
        # Get all achievements
        all_achievements = Achievement.query.order_by(
            Achievement.category, Achievement.xp_reward
        ).all()

        # Get user's earned achievements
        user_achievements = UserAchievement.query.filter_by(
            user_id=user_id
        ).all()
        earned_ids = {ua.achievement_id for ua in user_achievements}

        # Group by category
        achievements_by_category = {}
        for ach in all_achievements:
            if ach.category not in achievements_by_category:
                achievements_by_category[ach.category] = []

            achievements_by_category[ach.category].append({
                'achievement': ach,
                'earned': ach.id in earned_ids,
                'earned_at': next(
                    (ua.earned_at for ua in user_achievements if ua.achievement_id == ach.id),
                    None
                )
            })

        # Calculate stats
        total_achievements = len(all_achievements)
        earned_count = len(earned_ids)
        total_xp_earned = sum(
            ach.xp_reward for ach in all_achievements if ach.id in earned_ids
        )

        return {
            'by_category': achievements_by_category,
            'total_achievements': total_achievements,
            'earned_count': earned_count,
            'progress_percentage': round(earned_count / total_achievements * 100) if total_achievements > 0 else 0,
            'total_xp_earned': total_xp_earned
        }

    @staticmethod
    def get_badges_showcase(user_id: int, recent_limit: int = 5, teaser_limit: int = 3) -> Dict:
        """Badges showcase for dashboard: recent earned + teaser of next unearned.

        Returns:
            dict with:
              - recent: list of most recently earned badges (up to recent_limit)
              - teasers: list of not-yet-earned badges shown as silhouettes
              - earned_count, total_count
        """
        total_count = db.session.query(func.count(Achievement.id)).scalar() or 0

        earned_rows = (
            db.session.query(UserAchievement, Achievement)
            .join(Achievement, Achievement.id == UserAchievement.achievement_id)
            .filter(UserAchievement.user_id == user_id)
            .order_by(UserAchievement.earned_at.desc())
            .all()
        )
        earned_ids = {a.id for _ua, a in earned_rows}
        earned_count = len(earned_ids)

        recent = [
            {
                'id': a.id,
                'code': a.code,
                'name': a.name,
                'description': a.description,
                'icon': a.icon,
                'category': a.category,
                'xp_reward': a.xp_reward,
                'earned_at': ua.earned_at,
            }
            for ua, a in earned_rows[:recent_limit]
        ]

        teasers = []
        if earned_count < total_count and teaser_limit > 0:
            teaser_query = Achievement.query
            if earned_ids:
                teaser_query = teaser_query.filter(~Achievement.id.in_(earned_ids))
            unearned = (
                teaser_query
                .order_by(Achievement.xp_reward.asc(), Achievement.id.asc())
                .limit(teaser_limit)
                .all()
            )
            teasers = [
                {
                    'id': a.id,
                    'code': a.code,
                    'name': a.name,
                    'description': a.description,
                    'icon': a.icon,
                    'category': a.category,
                    'xp_reward': a.xp_reward,
                }
                for a in unearned
            ]

        return {
            'recent': recent,
            'teasers': teasers,
            'earned_count': earned_count,
            'total_count': total_count,
        }
