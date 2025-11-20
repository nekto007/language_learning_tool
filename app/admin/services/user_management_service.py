"""
User Management Service - admin operations for users

Responsibilities:
- User CRUD operations
- User statistics
- Module access management
"""
from typing import List, Dict, Optional
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
