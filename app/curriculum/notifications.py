# app/curriculum/notifications.py

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from flask import render_template
from flask_login import current_user

from app.utils.db import db
from app.utils.email_utils import email_sender

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Types of notifications"""
    PROGRESS_MILESTONE = "progress_milestone"
    LESSON_COMPLETED = "lesson_completed"
    MODULE_COMPLETED = "module_completed"
    LEVEL_COMPLETED = "level_completed"
    STREAK_ACHIEVEMENT = "streak_achievement"
    QUIZ_SCORE = "quiz_score"
    SRS_REMINDER = "srs_reminder"
    ADMIN_ALERT = "admin_alert"
    SYSTEM_NOTIFICATION = "system_notification"


class NotificationPriority(Enum):
    """Notification priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationData:
    """Notification data structure"""
    type: NotificationType
    priority: NotificationPriority
    title: str
    message: str
    user_id: Optional[int] = None
    data: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.data is None:
            self.data = {}


class NotificationService:
    """Service for managing notifications"""

    def __init__(self):
        self.notification_queue = []
        self.user_preferences = {}

    def send_notification(self, notification: NotificationData,
                          channels: List[str] = None) -> bool:
        """
        Send notification through specified channels
        
        Args:
            notification: Notification data
            channels: List of channels ('in_app', 'email', 'push')
        
        Returns:
            Success status
        """
        if channels is None:
            channels = ['in_app']

        success = True

        try:
            for channel in channels:
                if channel == 'in_app':
                    success &= self._send_in_app_notification(notification)
                elif channel == 'email':
                    success &= self._send_email_notification(notification)
                elif channel == 'push':
                    success &= self._send_push_notification(notification)
                else:
                    logger.warning(f"Unknown notification channel: {channel}")

            # Log notification
            self._log_notification(notification, channels, success)

        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}")
            success = False

        return success

    def _send_in_app_notification(self, notification: NotificationData) -> bool:
        """Send in-app notification"""
        try:
            # Store in database for in-app display
            # This would require a notifications table
            # For now, we'll store in session or cache

            if notification.user_id:
                # Store user-specific notification
                self._store_user_notification(notification)
            else:
                # Store system-wide notification
                self._store_system_notification(notification)

            logger.info(f"In-app notification sent: {notification.title}")
            return True

        except Exception as e:
            logger.error(f"Error sending in-app notification: {str(e)}")
            return False

    def _send_email_notification(self, notification: NotificationData) -> bool:
        """Send email notification"""
        try:
            if not notification.user_id:
                return False

            # Get user email preferences
            user_prefs = self._get_user_preferences(notification.user_id)
            if not user_prefs.get('email_enabled', True):
                return True  # User disabled email notifications

            # Check if this notification type is enabled for email
            email_types = user_prefs.get('email_types', [])
            if notification.type.value not in email_types and email_types:
                return True  # Notification type not enabled for email

            # Get user email
            from app.auth.models import User
            user = User.query.get(notification.user_id)
            if not user or not user.email:
                return False

            # Render email template
            template_name = f"emails/curriculum/{notification.type.value}.html"

            try:
                html_content = render_template(template_name,
                                               notification=notification,
                                               user=user)
            except Exception:
                # Fallback to generic template
                html_content = render_template('emails/curriculum/generic.html',
                                               notification=notification,
                                               user=user)

            # Send email using email_sender
            email_sender.send_email(
                subject=notification.title,
                to_email=user.email,
                template_name='curriculum/generic',
                context={'notification': notification, 'user': user}
            )

            logger.info(f"Email notification sent to {user.email}")
            return True

        except Exception as e:
            logger.error(f"Error sending email notification: {str(e)}")
            return False

    def _send_push_notification(self, notification: NotificationData) -> bool:
        """Send push notification (placeholder for future implementation)"""
        try:
            # This would integrate with a push notification service
            # like Firebase Cloud Messaging or Apple Push Notification Service

            logger.info(f"Push notification would be sent: {notification.title}")
            return True

        except Exception as e:
            logger.error(f"Error sending push notification: {str(e)}")
            return False

    def _store_user_notification(self, notification: NotificationData):
        """Store user notification (in-memory for now)"""
        # In production, this would be stored in a database table
        pass

    def _store_system_notification(self, notification: NotificationData):
        """Store system notification (in-memory for now)"""
        # In production, this would be stored in a database table
        pass

    def _log_notification(self, notification: NotificationData,
                          channels: List[str], success: bool):
        """Log notification for analytics"""
        log_data = {
            'type': notification.type.value,
            'priority': notification.priority.value,
            'channels': channels,
            'success': success,
            'user_id': notification.user_id,
            'timestamp': notification.created_at.isoformat()
        }

        logger.info(f"Notification logged: {log_data}")

    def _get_user_preferences(self, user_id: int) -> Dict[str, Any]:
        """Get user notification preferences"""
        # This would typically be stored in database
        # For now, return default preferences
        return {
            'email_enabled': True,
            'push_enabled': True,
            'email_types': [
                NotificationType.LEVEL_COMPLETED.value,
                NotificationType.STREAK_ACHIEVEMENT.value,
                NotificationType.SRS_REMINDER.value
            ],
            'push_types': [
                NotificationType.LESSON_COMPLETED.value,
                NotificationType.QUIZ_SCORE.value,
                NotificationType.SRS_REMINDER.value
            ]
        }


class ProgressNotificationManager:
    """Manager for progress-related notifications"""

    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service

    def on_lesson_completed(self, user_id: int, lesson_id: int, score: float):
        """Handle lesson completion notification"""
        from app.curriculum.models import Lessons

        lesson = Lessons.query.get(lesson_id)
        if not lesson:
            return

        # Create completion notification
        notification = NotificationData(
            type=NotificationType.LESSON_COMPLETED,
            priority=NotificationPriority.MEDIUM,
            title="Урок завершен!",
            message=f"Вы успешно завершили урок '{lesson.title}' с результатом {score:.1f}%",
            user_id=user_id,
            data={
                'lesson_id': lesson_id,
                'lesson_title': lesson.title,
                'score': score,
                'module_id': lesson.module_id
            }
        )

        # Send through appropriate channels
        channels = ['in_app']
        if score >= 80:  # High score deserves email notification
            channels.append('email')

        self.notification_service.send_notification(notification, channels)

        # Check for achievements
        self._check_lesson_achievements(user_id, lesson_id, score)

    def on_module_completed(self, user_id: int, module_id: int, average_score: float):
        """Handle module completion notification"""
        from app.curriculum.models import Module

        module = Module.query.get(module_id)
        if not module:
            return

        notification = NotificationData(
            type=NotificationType.MODULE_COMPLETED,
            priority=NotificationPriority.HIGH,
            title="Модуль завершен!",
            message=f"Поздравляем! Вы завершили модуль '{module.title}' со средним результатом {average_score:.1f}%",
            user_id=user_id,
            data={
                'module_id': module_id,
                'module_title': module.title,
                'average_score': average_score,
                'level_id': module.level_id
            }
        )

        self.notification_service.send_notification(notification, ['in_app', 'email'])

        # Check for level completion
        self._check_level_completion(user_id, module.level_id)

    def on_level_completed(self, user_id: int, level_id: int):
        """Handle level completion notification"""
        from app.curriculum.models import CEFRLevel

        level = CEFRLevel.query.get(level_id)
        if not level:
            return

        notification = NotificationData(
            type=NotificationType.LEVEL_COMPLETED,
            priority=NotificationPriority.HIGH,
            title="Уровень завершен!",
            message=f"Отличная работа! Вы успешно завершили уровень {level.code} - {level.name}",
            user_id=user_id,
            data={
                'level_id': level_id,
                'level_code': level.code,
                'level_name': level.name
            }
        )

        self.notification_service.send_notification(notification, ['in_app', 'email', 'push'])

    def on_streak_achievement(self, user_id: int, streak_days: int):
        """Handle learning streak achievement"""
        milestone_days = [7, 14, 30, 60, 100, 365]

        if streak_days in milestone_days:
            notification = NotificationData(
                type=NotificationType.STREAK_ACHIEVEMENT,
                priority=NotificationPriority.MEDIUM,
                title="Достижение разблокировано!",
                message=f"Потрясающе! Вы занимаетесь {streak_days} дней подряд!",
                user_id=user_id,
                data={
                    'streak_days': streak_days,
                    'achievement_level': self._get_streak_level(streak_days)
                }
            )

            channels = ['in_app']
            if streak_days >= 30:  # Major milestones get email
                channels.append('email')

            self.notification_service.send_notification(notification, channels)

    def on_quiz_score_achievement(self, user_id: int, lesson_id: int, score: float):
        """Handle quiz score achievements"""
        if score == 100:
            achievement_type = "perfect"
            title = "Идеальный результат!"
            message = "Поздравляем с безошибочным выполнением!"
        elif score >= 95:
            achievement_type = "excellent"
            title = "Отличный результат!"
            message = f"Великолепно! Результат {score:.1f}%"
        elif score >= 85:
            achievement_type = "good"
            title = "Хороший результат!"
            message = f"Хорошая работа! Результат {score:.1f}%"
        else:
            return  # No notification for lower scores

        notification = NotificationData(
            type=NotificationType.QUIZ_SCORE,
            priority=NotificationPriority.LOW,
            title=title,
            message=message,
            user_id=user_id,
            data={
                'lesson_id': lesson_id,
                'score': score,
                'achievement_type': achievement_type
            }
        )

        self.notification_service.send_notification(notification, ['in_app'])

    def send_srs_reminder(self, user_id: int, due_cards_count: int):
        """Send SRS review reminder"""
        if due_cards_count == 0:
            return

        notification = NotificationData(
            type=NotificationType.SRS_REMINDER,
            priority=NotificationPriority.MEDIUM,
            title="Время повторения!",
            message=f"У вас {due_cards_count} карточек готовы к повторению",
            user_id=user_id,
            data={
                'due_cards_count': due_cards_count
            }
        )

        # SRS reminders are good candidates for push notifications
        self.notification_service.send_notification(notification, ['in_app', 'push'])

    def _check_lesson_achievements(self, user_id: int, lesson_id: int, score: float):
        """Check for lesson-specific achievements"""
        # Check consecutive perfect scores
        from app.curriculum.models import LessonProgress

        recent_scores = db.session.query(LessonProgress.final_score) \
            .filter_by(user_id=user_id) \
            .filter(LessonProgress.final_score.isnot(None)) \
            .order_by(LessonProgress.last_activity.desc()) \
            .limit(5).all()

        if len(recent_scores) >= 3 and all(s[0] == 100 for s in recent_scores):
            self._send_achievement_notification(
                user_id,
                "Серия идеальных результатов!",
                "Три идеальных результата подряд!"
            )

    def _check_level_completion(self, user_id: int, level_id: int):
        """Check if user completed all modules in level"""
        from app.curriculum.models import Module, LessonProgress

        # Get all modules in level
        modules = Module.query.filter_by(level_id=level_id).all()

        # Check if all modules are completed
        completed_modules = 0
        for module in modules:
            # Check if module has completed lessons
            module_lessons = db.session.query(LessonProgress) \
                .join(Lessons) \
                .filter(Lessons.module_id == module.id) \
                .filter(LessonProgress.user_id == user_id) \
                .filter(LessonProgress.status == 'completed').count()

            if module_lessons > 0:  # At least some lessons completed
                completed_modules += 1

        # If all modules have progress, consider level completed
        if completed_modules == len(modules) and len(modules) > 0:
            self.on_level_completed(user_id, level_id)

    def _get_streak_level(self, days: int) -> str:
        """Get streak achievement level"""
        if days >= 365:
            return "legend"
        elif days >= 100:
            return "master"
        elif days >= 60:
            return "expert"
        elif days >= 30:
            return "dedicated"
        elif days >= 14:
            return "committed"
        else:
            return "beginner"

    def _send_achievement_notification(self, user_id: int, title: str, message: str):
        """Send generic achievement notification"""
        notification = NotificationData(
            type=NotificationType.PROGRESS_MILESTONE,
            priority=NotificationPriority.MEDIUM,
            title=title,
            message=message,
            user_id=user_id
        )

        self.notification_service.send_notification(notification, ['in_app'])


class AdminNotificationManager:
    """Manager for admin notifications"""

    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service

    def send_system_alert(self, title: str, message: str, priority: NotificationPriority = NotificationPriority.MEDIUM):
        """Send system alert to all admins"""
        # Get all admin users
        from app.auth.models import User
        admins = User.query.filter_by(is_admin=True).all()

        for admin in admins:
            notification = NotificationData(
                type=NotificationType.ADMIN_ALERT,
                priority=priority,
                title=title,
                message=message,
                user_id=admin.id
            )

            channels = ['in_app']
            if priority in [NotificationPriority.HIGH, NotificationPriority.URGENT]:
                channels.append('email')

            self.notification_service.send_notification(notification, channels)

    def alert_high_error_rate(self, error_rate: float, endpoint: str):
        """Alert admins about high error rate"""
        self.send_system_alert(
            title="Высокий уровень ошибок",
            message=f"Endpoint {endpoint} имеет уровень ошибок {error_rate:.1f}%",
            priority=NotificationPriority.HIGH
        )

    def alert_slow_performance(self, endpoint: str, response_time: float):
        """Alert admins about slow performance"""
        self.send_system_alert(
            title="Медленная производительность",
            message=f"Endpoint {endpoint} отвечает медленно: {response_time:.2f}s",
            priority=NotificationPriority.MEDIUM
        )

    def alert_database_issues(self, issue_description: str):
        """Alert admins about database issues"""
        self.send_system_alert(
            title="Проблемы с базой данных",
            message=issue_description,
            priority=NotificationPriority.HIGH
        )


class NotificationTemplateManager:
    """Manager for notification templates"""

    @staticmethod
    def get_template_data(notification_type: NotificationType, data: Dict[str, Any]) -> Dict[str, str]:
        """Get template data for notification type"""

        templates = {
            NotificationType.LESSON_COMPLETED: {
                'title': "Урок завершен!",
                'message': "Вы успешно завершили урок '{lesson_title}' с результатом {score:.1f}%"
            },
            NotificationType.MODULE_COMPLETED: {
                'title': "Модуль завершен!",
                'message': "Поздравляем! Вы завершили модуль '{module_title}'"
            },
            NotificationType.LEVEL_COMPLETED: {
                'title': "Уровень завершен!",
                'message': "Отличная работа! Вы завершили уровень {level_code}"
            },
            NotificationType.STREAK_ACHIEVEMENT: {
                'title': "Достижение разблокировано!",
                'message': "Вы занимаетесь {streak_days} дней подряд!"
            }
        }

        template = templates.get(notification_type, {
            'title': "Уведомление",
            'message': "У вас новое уведомление"
        })

        # Format with data
        try:
            title = template['title'].format(**data)
            message = template['message'].format(**data)
        except (KeyError, ValueError):
            title = template['title']
            message = template['message']

        return {'title': title, 'message': message}


# Global instances
notification_service = NotificationService()
progress_notifications = ProgressNotificationManager(notification_service)
admin_notifications = AdminNotificationManager(notification_service)


def init_notifications(app):
    """Initialize notification system"""

    # Add notification endpoints
    @app.route('/curriculum/notifications/test')
    def test_notification():
        """Test notification system (admin only)"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        # Send test notification
        notification = NotificationData(
            type=NotificationType.SYSTEM_NOTIFICATION,
            priority=NotificationPriority.LOW,
            title="Тестовое уведомление",
            message="Система уведомлений работает корректно",
            user_id=current_user.id
        )

        success = notification_service.send_notification(notification, ['in_app', 'email'])

        return {'success': success, 'message': 'Test notification sent'}

    @app.route('/curriculum/notifications/admin/alert', methods=['POST'])
    def send_admin_alert():
        """Send admin alert (admin only)"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        from flask import request
        data = request.get_json()

        title = data.get('title', 'System Alert')
        message = data.get('message', '')
        priority = NotificationPriority(data.get('priority', 'medium'))

        admin_notifications.send_system_alert(title, message, priority)

        return {'success': True, 'message': 'Alert sent to all admins'}

    logger.info("Initialized curriculum notification system")


def notify_lesson_completed(user_id: int, lesson_id: int, score: float):
    """Convenience function to notify lesson completion"""
    progress_notifications.on_lesson_completed(user_id, lesson_id, score)


def notify_streak_achievement(user_id: int, streak_days: int):
    """Convenience function to notify streak achievement"""
    progress_notifications.on_streak_achievement(user_id, streak_days)


def notify_srs_reminder(user_id: int, due_cards_count: int):
    """Convenience function to send SRS reminder"""
    progress_notifications.send_srs_reminder(user_id, due_cards_count)


# Integration with metrics for automatic alerts
def setup_automatic_alerts():
    """Setup automatic alerts based on metrics"""
    from app.curriculum.metrics import metrics_collector

    def check_error_rates():
        """Check for high error rates and alert admins"""
        stats = metrics_collector.get_endpoint_stats()

        for endpoint_stat in stats:
            if (endpoint_stat['error_rate'] > 10 and  # More than 10% error rate
                    endpoint_stat['total_requests'] > 10):  # With significant traffic

                admin_notifications.alert_high_error_rate(
                    endpoint_stat['error_rate'],
                    endpoint_stat['endpoint']
                )

    def check_performance():
        """Check for slow performance and alert admins"""
        stats = metrics_collector.get_endpoint_stats()

        for endpoint_stat in stats:
            if (endpoint_stat['avg_response_time'] > 2.0 and  # Slower than 2 seconds
                    endpoint_stat['total_requests'] > 5):  # With some traffic

                admin_notifications.alert_slow_performance(
                    endpoint_stat['endpoint'],
                    endpoint_stat['avg_response_time']
                )

    # These would be called periodically by a scheduler
    # For now, they're just defined for manual use
    return check_error_rates, check_performance
