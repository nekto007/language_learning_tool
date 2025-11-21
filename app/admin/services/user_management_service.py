"""
User Management Service - admin operations for users

Responsibilities:
- User CRUD operations
- User statistics
- Module access management
"""
from typing import List, Dict, Optional
from datetime import UTC, datetime, timedelta
from sqlalchemy import func

from app.utils.db import db
from app.auth.models import User
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
