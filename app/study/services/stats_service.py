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
    UserWord, GameScore, QuizResult, UserXP, Achievement, UserAchievement, StudySession
)
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
        today_sessions = StudySession.query.filter_by(user_id=user_id) \
            .filter(func.date(StudySession.start_time) == today).all()

        today_words_studied = sum(session.words_studied for session in today_sessions)
        today_time_spent = sum(session.duration for session in today_sessions)

        return {
            **word_stats,
            'mastery_percentage': int((word_stats['mastered'] / word_stats['total'] * 100) if word_stats['total'] > 0 else 0),
            'recent_sessions': recent_sessions,
            'study_streak': 0,  # TODO: implement streak calculation
            'today_words_studied': today_words_studied,
            'today_time_spent': today_time_spent
        }

    @staticmethod
    def get_user_word_stats(user_id: int) -> Dict:
        """Get user's word learning statistics"""
        # Count words by status
        stats = db.session.query(
            UserWord.status,
            func.count(UserWord.id)
        ).filter(
            UserWord.user_id == user_id
        ).group_by(
            UserWord.status
        ).all()

        status_counts = {status: count for status, count in stats}

        return {
            'new': status_counts.get('new', 0),
            'learning': status_counts.get('learning', 0),
            'review': status_counts.get('review', 0),
            'mastered': status_counts.get('mastered', 0),
            'total': sum(status_counts.values())
        }

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
                GameScore.created_at >= start_date
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
                func.sum(UserXP.xp_amount).label('total_xp')
            ).join(
                UserXP, User.id == UserXP.user_id
            ).filter(
                UserXP.earned_at >= start_date
            ).group_by(
                User.id, User.username
            ).order_by(
                desc('total_xp')
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
                existing = UserAchievement.query.filter_by(
                    user_id=user_id,
                    achievement_id=achievement.id
                ).first()

                if not existing:
                    ua = UserAchievement(
                        user_id=user_id,
                        achievement_id=achievement.id,
                        earned_at=datetime.now(timezone.utc)
                    )
                    db.session.add(ua)
                    newly_earned.append(achievement)

        if newly_earned:
            db.session.commit()

        return newly_earned
