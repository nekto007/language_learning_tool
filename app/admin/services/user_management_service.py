"""
User Management Service - admin operations for users

Responsibilities:
- User CRUD operations
- User statistics
- Module access management
"""
from typing import List, Dict, Optional
from datetime import UTC, datetime, timedelta
from sqlalchemy import func, distinct

from app.utils.db import db
from app.auth.models import User, ReferralLog
from app.study.models import UserWord
from app.curriculum.models import LessonProgress
from app.modules.models import UserModule


class UserManagementService:
    """Service for admin user management"""

    @classmethod
    def get_all_users(cls, page: int = 1, per_page: int = 50) -> Dict:
        """
        Get paginated list of users

        Returns:
            Dictionary with users and pagination info
        """
        pagination = User.query.order_by(User.created_at.desc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        return {
            'users': pagination.items,
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        }

    @classmethod
    def get_user_statistics(cls, user_id: int) -> Optional[Dict]:
        """Get detailed statistics for a user"""
        user = User.query.get(user_id)
        if not user:
            return None

        # Word statistics
        word_stats = db.session.query(
            UserWord.status,
            func.count(UserWord.id)
        ).filter(
            UserWord.user_id == user_id
        ).group_by(UserWord.status).all()

        word_counts = {status: count for status, count in word_stats}

        # Lesson progress
        lesson_stats = db.session.query(
            LessonProgress.status,
            func.count(LessonProgress.id)
        ).filter(
            LessonProgress.user_id == user_id
        ).group_by(LessonProgress.status).all()

        lesson_counts = {status: count for status, count in lesson_stats}

        # Module access
        module_count = UserModule.query.filter_by(
            user_id=user_id,
            is_enabled=True
        ).count()

        return {
            'user_id': user_id,
            'username': user.username,
            'email': user.email,
            'created_at': user.created_at,
            'words': {
                'total': sum(word_counts.values()),
                'new': word_counts.get('new', 0),
                'learning': word_counts.get('learning', 0),
                'review': word_counts.get('review', 0),
                'mastered': word_counts.get('mastered', 0)
            },
            'lessons': {
                'total': sum(lesson_counts.values()),
                'not_started': lesson_counts.get('not_started', 0),
                'in_progress': lesson_counts.get('in_progress', 0),
                'completed': lesson_counts.get('completed', 0)
            },
            'modules_enabled': module_count
        }

    @classmethod
    def get_user_detail(cls, user_id: int) -> Optional[Dict]:
        """Get comprehensive user profile for admin detail page."""
        user = User.query.get(user_id)
        if not user:
            return None

        from app.achievements.models import UserStatistics, StreakCoins, LessonGrade
        from app.grammar_lab.models import UserGrammarTopicStatus

        # Basic stats from get_user_statistics
        base_stats = cls.get_user_statistics(user_id)

        # Streak and achievements
        user_stats = UserStatistics.query.filter_by(user_id=user_id).first()
        streak_info = {
            'current': user_stats.current_streak_days if user_stats else 0,
            'longest': user_stats.longest_streak_days if user_stats else 0,
            'total_lessons': user_stats.total_lessons_completed if user_stats else 0,
            'total_badges': user_stats.total_badges if user_stats else 0,
            'badge_points': user_stats.total_badge_points if user_stats else 0,
        }

        # Coins
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        coins_info = {
            'balance': coins.balance if coins else 0,
            'total_earned': coins.total_earned if coins else 0,
            'total_spent': coins.total_spent if coins else 0,
        }

        # Grammar progress
        grammar_started = UserGrammarTopicStatus.query.filter_by(user_id=user_id).count()
        grammar_mastered = UserGrammarTopicStatus.query.filter_by(
            user_id=user_id, status='mastered'
        ).count()

        # Lesson grades
        grades = db.session.query(
            LessonGrade.grade,
            func.count(LessonGrade.id)
        ).filter(
            LessonGrade.user_id == user_id
        ).group_by(LessonGrade.grade).all()
        grade_counts = {g: c for g, c in grades}

        # Referrals made
        referrals_made = ReferralLog.query.filter_by(referrer_id=user_id).count()

        # Module access details
        user_modules = UserModule.query.filter_by(user_id=user_id, is_enabled=True).all()
        module_names = []
        for um in user_modules:
            from app.modules.models import SystemModule
            sm = SystemModule.query.get(um.module_id)
            if sm:
                module_names.append(sm.name)

        return {
            **base_stats,
            'user': user,
            'streak': streak_info,
            'coins': coins_info,
            'grammar': {
                'started': grammar_started,
                'mastered': grammar_mastered,
            },
            'grades': grade_counts,
            'referrals_made': referrals_made,
            'module_names': module_names,
            'last_login': user.last_login,
            'active': user.active,
            'is_admin': user.is_admin,
        }

    @classmethod
    def get_at_risk_users(cls, inactive_days: int = 7, min_streak: int = 3, limit: int = 10) -> List[Dict]:
        """Get users inactive 7+ days who previously had 3+ day streaks."""
        from app.achievements.models import UserStatistics

        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=inactive_days)

        rows = db.session.query(
            User.id,
            User.username,
            User.email,
            User.last_login,
            UserStatistics.longest_streak_days,
            UserStatistics.current_streak_days,
        ).join(
            UserStatistics, User.id == UserStatistics.user_id
        ).filter(
            User.active == True,
            UserStatistics.longest_streak_days >= min_streak,
            db.or_(
                User.last_login.is_(None),
                User.last_login < cutoff,
            ),
        ).order_by(
            UserStatistics.longest_streak_days.desc()
        ).limit(limit).all()

        return [{
            'id': r.id,
            'username': r.username,
            'email': r.email,
            'last_login': r.last_login,
            'longest_streak': r.longest_streak_days,
            'current_streak': r.current_streak_days,
        } for r in rows]

    @classmethod
    def export_users_csv(cls, search: str = '') -> List[Dict]:
        """Export users with key metrics for CSV download."""
        from app.achievements.models import UserStatistics, StreakCoins

        query = db.session.query(
            User.id,
            User.username,
            User.email,
            User.created_at,
            User.last_login,
            User.active,
            UserStatistics.total_lessons_completed,
            UserStatistics.current_streak_days,
            UserStatistics.longest_streak_days,
            StreakCoins.balance.label('coin_balance'),
        ).outerjoin(
            UserStatistics, User.id == UserStatistics.user_id
        ).outerjoin(
            StreakCoins, User.id == StreakCoins.user_id
        )

        if search:
            query = query.filter(
                db.or_(
                    User.username.ilike(f'%{search}%'),
                    User.email.ilike(f'%{search}%'),
                )
            )

        rows = query.order_by(User.created_at.desc()).all()

        return [{
            'id': r.id,
            'username': r.username,
            'email': r.email or '',
            'created_at': r.created_at.strftime('%Y-%m-%d') if r.created_at else '',
            'last_login': r.last_login.strftime('%Y-%m-%d') if r.last_login else '',
            'active': 'Да' if r.active else 'Нет',
            'lessons_completed': r.total_lessons_completed or 0,
            'current_streak': r.current_streak_days or 0,
            'longest_streak': r.longest_streak_days or 0,
            'coin_balance': r.coin_balance or 0,
        } for r in rows]

    @classmethod
    def toggle_user_module_access(cls, user_id: int, module_code: str, enabled: bool) -> bool:
        """Enable/disable module access for user"""
        user_module = UserModule.query.filter_by(
            user_id=user_id,
            module_code=module_code
        ).first()

        if user_module:
            user_module.is_enabled = enabled
        else:
            # Create new entry
            user_module = UserModule(
                user_id=user_id,
                module_code=module_code,
                is_enabled=enabled
            )
            db.session.add(user_module)

        db.session.commit()
        return True

    @classmethod
    def delete_user(cls, user_id: int) -> bool:
        """Delete a user and all associated data"""
        user = User.query.get(user_id)
        if not user:
            return False

        # Cascade deletes will handle related data
        db.session.delete(user)
        db.session.commit()
        return True

    @classmethod
    def toggle_user_status(cls, user_id: int) -> Optional[Dict]:
        """
        Toggle user active status

        Returns:
            Dictionary with updated user info or None if user not found
        """
        user = User.query.get(user_id)
        if not user:
            return None

        user.active = not user.active
        db.session.commit()

        return {
            'user_id': user.id,
            'username': user.username,
            'active': user.active
        }

    @classmethod
    def toggle_admin_status(cls, user_id: int, current_admin_id: int) -> tuple[bool, str]:
        """
        Toggle user admin status

        Args:
            user_id: ID of user to modify
            current_admin_id: ID of current admin making the change

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Prevent self-modification
        if user_id == current_admin_id:
            return False, "Cannot modify your own admin status"

        user = User.query.get(user_id)
        if not user:
            return False, "User not found"

        user.is_admin = not user.is_admin
        db.session.commit()

        return True, f"Admin status {'granted' if user.is_admin else 'revoked'} for {user.username}"

    @classmethod
    def toggle_mission_plan(cls, user_id: int) -> Optional[Dict]:
        """Toggle mission-based daily plan flag for a user."""
        user = User.query.get(user_id)
        if not user:
            return None

        user.use_mission_plan = not user.use_mission_plan
        db.session.commit()

        return {
            'user_id': user.id,
            'username': user.username,
            'use_mission_plan': user.use_mission_plan,
        }

    @classmethod
    def get_user_activity_stats(cls, days: int = 30) -> Dict:
        """
        Get user activity statistics for dashboard

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with registration, login, and hourly activity data
        """
        # Use datetime.now(UTC) and convert to naive for DB compatibility
        cutoff_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)

        # User registrations by date
        user_registrations = db.session.query(
            func.date(User.created_at).label('date'),
            func.count(User.id).label('count')
        ).filter(
            User.created_at >= cutoff_date
        ).group_by(
            func.date(User.created_at)
        ).all()

        # User logins by date
        user_logins = db.session.query(
            func.date(User.last_login).label('date'),
            func.count(User.id).label('count')
        ).filter(
            User.last_login >= cutoff_date
        ).group_by(
            func.date(User.last_login)
        ).all()

        # User activity by hour
        user_activity_by_hour = db.session.query(
            func.extract('hour', User.last_login).label('hour'),
            func.count(User.id).label('count')
        ).filter(
            User.last_login >= cutoff_date
        ).group_by(
            'hour'
        ).all()

        return {
            'user_registrations': user_registrations,
            'user_logins': user_logins,
            'user_activity_by_hour': user_activity_by_hour
        }
