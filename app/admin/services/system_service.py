# app/admin/services/system_service.py

"""
Сервис для управления системой (System Management Service)
Обрабатывает системную информацию, БД и статистику
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.auth.models import User
from app.books.models import Book
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.utils.db import db
from app.words.models import Collection, CollectionWords, Topic

logger = logging.getLogger(__name__)


class SystemService:
    """Сервис для управления системной информацией и БД"""

    @staticmethod
    def get_system_info():
        """
        Получает информацию о системе

        Returns:
            dict: Информация о системе, памяти, диске, БД и приложении
        """
        try:
            import platform
            import psutil
            import os
            from flask import current_app

            # Get system information
            system_info = {
                'platform': platform.platform(),
                'python_version': platform.python_version(),
                'flask_version': '2.x',
                'cpu_count': psutil.cpu_count(),
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory': {
                    'total': psutil.virtual_memory().total // (1024 * 1024),  # MB
                    'available': psutil.virtual_memory().available // (1024 * 1024),
                    'used': psutil.virtual_memory().used // (1024 * 1024),
                    'percent': psutil.virtual_memory().percent
                },
                'disk': {
                    'total': psutil.disk_usage('/').total // (1024 * 1024 * 1024),  # GB
                    'used': psutil.disk_usage('/').used // (1024 * 1024 * 1024),
                    'free': psutil.disk_usage('/').free // (1024 * 1024 * 1024),
                    'percent': psutil.disk_usage('/').percent
                }
            }

            # Database statistics
            db_stats = {
                'users': User.query.count(),
                'books': Book.query.count(),
                'words': CollectionWords.query.count(),
                'topics': Topic.query.count(),
                'collections': Collection.query.count(),
                'levels': CEFRLevel.query.count(),
                'modules': Module.query.count(),
                'lessons': Lessons.query.count()
            }

            # Application info
            app_info = {
                'debug': current_app.debug,
                'environment': os.environ.get('FLASK_ENV', 'production'),
                'database_url': current_app.config.get('SQLALCHEMY_DATABASE_URI', '').split('@')[
                    -1] if '@' in current_app.config.get('SQLALCHEMY_DATABASE_URI', '') else 'Local SQLite'
            }

            return {
                'system_info': system_info,
                'db_stats': db_stats,
                'app_info': app_info
            }

        except Exception as e:
            logger.error(f"Error getting system info: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def test_database_connection():
        """
        Тестирует подключение к базе данных

        Returns:
            dict: Статус подключения, версия, количество таблиц, размер БД
        """
        try:
            from config.settings import DB_CONFIG
            from app.repository import DatabaseRepository

            repo = DatabaseRepository(DB_CONFIG)
            with repo.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT version()")
                    version = cursor.fetchone()[0]

                    cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
                    table_count = cursor.fetchone()[0]

                    cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
                    db_size = cursor.fetchone()[0]

            return {
                'status': 'success',
                'message': 'Подключение успешно',
                'version': version,
                'table_count': table_count,
                'database_size': db_size
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Ошибка подключения: {str(e)}'
            }

    @staticmethod
    def get_word_status_statistics():
        """
        Получает статистику по статусам слов

        Returns:
            dict: Статистика по статусам слов и общие показатели
        """
        try:
            from app.study.models import UserWord

            status_stats = db.session.query(
                UserWord.status,
                func.count(UserWord.id).label('count'),
                func.count(func.distinct(UserWord.user_id)).label('users')
            ).group_by(UserWord.status).all()

            total_user_words = UserWord.query.count()
            total_unique_words = db.session.query(func.count(func.distinct(UserWord.word_id))).scalar()
            total_users_with_words = db.session.query(func.count(func.distinct(UserWord.user_id))).scalar()

            return {
                'status_breakdown': [
                    {
                        'status': stat.status,
                        'count': stat.count,
                        'users': stat.users,
                        'percentage': round((stat.count / total_user_words * 100), 1) if total_user_words > 0 else 0
                    }
                    for stat in status_stats
                ],
                'totals': {
                    'total_user_words': total_user_words,
                    'unique_words_tracked': total_unique_words,
                    'users_with_words': total_users_with_words
                }
            }
        except Exception as e:
            logger.error(f"Error getting word statistics: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def get_book_statistics():
        """
        Получает статистику по книгам

        Returns:
            dict: Топ-5 книг и общая статистика
        """
        try:
            top_books = db.session.query(
                Book.title,
                Book.words_total,
                Book.unique_words
            ).order_by(Book.words_total.desc()).limit(5).all()

            total_books = Book.query.count()
            words_total_all_books = db.session.query(func.sum(Book.words_total)).scalar() or 0
            total_unique_words_all = db.session.query(func.sum(Book.unique_words)).scalar() or 0

            return {
                'top_books': [
                    {
                        'title': book.title,
                        'words_total': book.words_total,
                        'unique_words': book.unique_words
                    }
                    for book in top_books
                ],
                'totals': {
                    'total_books': total_books,
                    'words_total_all_books': words_total_all_books,
                    'total_unique_words_all': total_unique_words_all
                }
            }
        except Exception as e:
            logger.error(f"Error getting book statistics: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def get_recent_db_operations():
        """
        Получает список недавних операций с БД

        Returns:
            dict: Недавние уроки и пользователи
        """
        try:
            recent_lessons = Lessons.query.order_by(Lessons.created_at.desc()).limit(5).all()

            # Use datetime.now(UTC) and convert to naive for DB compatibility
            week_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
            recent_users = User.query.filter(User.created_at >= week_ago).order_by(User.created_at.desc()).limit(5).all()

            return {
                'recent_lessons': [
                    {
                        'title': lesson.title,
                        'type': lesson.type,
                        'created_at': lesson.created_at.strftime('%Y-%m-%d %H:%M') if lesson.created_at else 'N/A'
                    }
                    for lesson in recent_lessons
                ],
                'recent_users': [
                    {
                        'username': user.username,
                        'created_at': user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else 'N/A'
                    }
                    for user in recent_users
                ]
            }
        except Exception as e:
            logger.error(f"Error getting recent operations: {str(e)}")
            return {'error': str(e)}
