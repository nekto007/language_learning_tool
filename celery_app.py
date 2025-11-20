"""
Celery configuration and application factory

Usage:
    # Start Celery worker
    celery -A celery_app.celery worker --loglevel=info

    # Start Celery beat (for periodic tasks)
    celery -A celery_app.celery beat --loglevel=info
"""
import os
from celery import Celery
from celery.schedules import crontab


def make_celery(app_name=__name__):
    """
    Create Celery instance

    Uses Redis as message broker and result backend
    """
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    celery = Celery(
        app_name,
        broker=redis_url,
        backend=redis_url,
        include=[
            'app.tasks.book_tasks',
            'app.tasks.audio_tasks',
            'app.tasks.maintenance_tasks',
        ]
    )

    # Celery configuration
    celery.conf.update(
        # Task settings
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,

        # Task execution settings
        task_track_started=True,
        task_time_limit=3600,  # 1 hour max per task
        task_soft_time_limit=3300,  # 55 minutes soft limit
        worker_prefetch_multiplier=1,  # One task at a time per worker
        worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (prevent memory leaks)

        # Result backend settings
        result_expires=86400,  # Results expire after 24 hours
        result_backend_transport_options={
            'master_name': 'mymaster',
            'retry_on_timeout': True
        },

        # Rate limiting
        task_default_rate_limit='10/m',  # 10 tasks per minute default

        # Periodic tasks (Celery Beat)
        beat_schedule={
            # Clean up old task results daily at 3 AM
            'cleanup-old-results': {
                'task': 'app.tasks.maintenance_tasks.cleanup_old_results',
                'schedule': crontab(hour=3, minute=0),
            },
            # Clean up expired sessions daily at 4 AM
            'cleanup-expired-sessions': {
                'task': 'app.tasks.maintenance_tasks.cleanup_expired_sessions',
                'schedule': crontab(hour=4, minute=0),
            },
            # Clean up old Telegram tokens weekly on Sunday at 2 AM
            'cleanup-old-telegram-tokens': {
                'task': 'app.tasks.maintenance_tasks.cleanup_old_telegram_tokens',
                'schedule': crontab(hour=2, minute=0, day_of_week=0),
            },
            # Warm cache every 6 hours
            'warm-cache': {
                'task': 'app.tasks.maintenance_tasks.warm_cache',
                'schedule': crontab(minute=0, hour='*/6'),
            },
            # Generate daily statistics at midnight
            'daily-statistics': {
                'task': 'app.tasks.maintenance_tasks.generate_daily_statistics',
                'schedule': crontab(hour=0, minute=5),
            },
            # Clean up old audio files weekly on Monday at 1 AM
            'cleanup-old-audio': {
                'task': 'app.tasks.audio_tasks.cleanup_old_audio_files',
                'schedule': crontab(hour=1, minute=0, day_of_week=1),
            },
        },
    )

    return celery


# Create Celery instance
celery = make_celery()


if __name__ == '__main__':
    celery.start()
