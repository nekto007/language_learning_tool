import copy
import datetime
import logging
import re

from flask import request

logger = logging.getLogger(__name__)

try:
    from markupsafe import Markup
except ImportError:
    from flask import Markup


def url_params_with_updated_args(**updates):
    """
    Generate a dictionary of URL parameters based on current request args,
    but with specified parameters updated or removed.

    Usage in template:
    {{ url_for('endpoint', **url_params(page=2, sort='name')) }}

    Args:
        **updates: Parameters to update. Use None to remove a parameter.

    Returns:
        dict: Updated URL parameters
    """
    args = copy.deepcopy(request.args.to_dict(flat=True))

    # Update/add parameters
    for key, value in updates.items():
        if value is None:
            # Remove parameter if value is None
            if key in args:
                del args[key]
        else:
            # Add or update parameter
            args[key] = str(value)  # Convert values to strings for URL parameters

    return args


def format_chapter_text(text):
    """
    Format chapter text for HTML display
    Handles various newline patterns and converts to proper paragraphs
    """
    if not text:
        return ""
    
    # Handle different newline patterns
    # Escaped newlines from database
    text = text.replace('\\n\\n', '\n\n')
    text = text.replace('\\n', '\n')
    
    # Split into paragraphs
    if '\n\n' in text:
        paragraphs = text.split('\n\n')
    else:
        # If no double newlines, split by single newlines but be more conservative
        paragraphs = [text]
    
    html_parts = []
    for paragraph in paragraphs:
        clean_paragraph = paragraph.strip()
        if clean_paragraph:
            # Replace remaining single newlines with spaces within paragraphs
            clean_paragraph = clean_paragraph.replace('\n', ' ')
            # Clean up multiple spaces
            clean_paragraph = re.sub(r'\s+', ' ', clean_paragraph)
            html_parts.append(f'<p class="mb-4">{clean_paragraph}</p>')
    
    return Markup('\n'.join(html_parts))


def init_template_utils(app):
    """
    Register template utility functions with the Flask app.

    Args:
        app: Flask application instance
    """

    @app.context_processor
    def utility_processor():
        from datetime import datetime
        return {
            'url_params': url_params_with_updated_args,
            'now': datetime.now
        }

    @app.context_processor
    def inject_curriculum_data():
        """Инжектирует данные о курсах в шаблоны"""

        def get_cefr_levels():
            from app.curriculum.models import CEFRLevel
            return CEFRLevel.query.order_by(CEFRLevel.order).all()

        def get_user_lessons():
            from app.curriculum.models import Lessons, LessonProgress
            from flask_login import current_user

            if not current_user.is_authenticated:
                return []

            # Получаем 5 последних активных уроков пользователя
            lessons = Lessons.query.join(
                LessonProgress, Lessons.id == LessonProgress.lesson_id
            ).filter(
                LessonProgress.user_id == current_user.id,
                LessonProgress.status == 'in_progress'
            ).order_by(
                LessonProgress.last_activity.desc()
            ).limit(5).all()

            return lessons

        def get_curriculum_progress():
            """Получает прогресс пользователя по курсам для дашборда"""
            from app.curriculum.models import CEFRLevel, Lessons, Module, LessonProgress
            from flask_login import current_user

            if not current_user.is_authenticated:
                return []

            # Получаем все уровни
            levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

            result = []
            for level in levels:
                # Получаем все уроки для этого уровня
                level_modules = Module.query.filter_by(level_id=level.id).all()
                module_ids = [m.id for m in level_modules]

                if not module_ids:
                    continue  # Пропускаем уровни без модулей

                # Получаем все уроки для этих модулей
                lessons = Lessons.query.filter(Lessons.module_id.in_(module_ids)).all()

                if not lessons:
                    continue  # Пропускаем уровни без уроков

                # Получаем прогресс пользователя по этим урокам
                progress_records = LessonProgress.query.filter(
                    LessonProgress.user_id == current_user.id,
                    LessonProgress.lesson_id.in_([lesson.id for lesson in lessons])
                ).all()

                completed_lessons = [p for p in progress_records if p.status == 'completed']
                in_progress_lessons = [p for p in progress_records if p.status == 'in_progress']

                # Находим текущий урок пользователя
                current_lesson = None
                if in_progress_lessons:
                    # Берем урок с самой последней активностью
                    latest_progress = max(in_progress_lessons, key=lambda p: p.last_activity or datetime.datetime.min)
                    current_lesson = Lessons.query.get(latest_progress.lesson_id)

                # Вычисляем прогресс
                total_lessons = len(lessons)
                completed_count = len(completed_lessons)
                progress_percent = int((completed_count / total_lessons) * 100) if total_lessons > 0 else 0

                # Добавляем данные в результат
                result.append({
                    'level': level,
                    'progress': progress_percent,
                    'completed': completed_count,
                    'total': total_lessons,
                    'current_lesson': current_lesson
                })

            # Возвращаем только уровни, по которым есть прогресс или которые следующие в очереди
            active_levels = [level_data for level_data in result if level_data['progress'] > 0]

            # Если нет активных уровней, добавляем первый доступный уровень
            if not active_levels and result:
                active_levels = [result[0]]

            return active_levels

        def translate_lesson_type(lesson_type):
            """Переводит тип урока на русский язык"""
            translations = {
                'vocabulary': 'Словарь',
                'grammar': 'Грамматика',
                'quiz': 'Тест',
                'matching': 'Сопоставление',
                'text': 'Текст',
                'card': 'Карточки',
                'final_test': 'Итоговый тест'
            }
            return translations.get(lesson_type, lesson_type.capitalize())

        def get_lesson_url(lesson):
            """Получить URL для урока"""
            from app.curriculum.url_helpers import get_beautiful_lesson_url
            return get_beautiful_lesson_url(lesson)

        def get_active_book_course():
            """Возвращает активный книжный курс пользователя для навбара"""
            from flask_login import current_user
            if not current_user.is_authenticated:
                return None
            try:
                from app.curriculum.book_courses import BookCourseEnrollment
                enrollment = BookCourseEnrollment.query.filter_by(
                    user_id=current_user.id
                ).order_by(BookCourseEnrollment.last_activity.desc()).first()
                if enrollment:
                    return {
                        'course': enrollment.course,
                        'current_module': enrollment.current_module
                    }
            except Exception:
                logger.exception("Failed to get active book course for navbar")
            return None

        def get_active_curriculum_lesson():
            """Возвращает последний активный урок обычного курса для навбара"""
            from flask_login import current_user
            if not current_user.is_authenticated:
                return None
            try:
                from app.curriculum.models import LessonProgress, Lessons
                progress = LessonProgress.query.filter_by(
                    user_id=current_user.id,
                    status='in_progress'
                ).order_by(LessonProgress.last_activity.desc()).first()
                if progress:
                    lesson = Lessons.query.get(progress.lesson_id)
                    if lesson and lesson.module:
                        return {
                            'lesson': lesson,
                            'module': lesson.module,
                            'level': lesson.module.level,
                            'url': f'/learn/{lesson.id}/'
                        }
            except Exception:
                logger.exception("Failed to get active curriculum lesson for navbar")
            return None

        def get_active_grammar_topic():
            """Возвращает последнюю активную грамматическую тему для навбара"""
            from flask_login import current_user
            if not current_user.is_authenticated:
                return None
            try:
                from app.grammar_lab.models import UserGrammarTopicStatus, GrammarTopic
                status = UserGrammarTopicStatus.query.filter(
                    UserGrammarTopicStatus.user_id == current_user.id,
                    UserGrammarTopicStatus.status.in_(['theory_completed', 'practicing'])
                ).order_by(UserGrammarTopicStatus.updated_at.desc()).first()
                if status:
                    topic = GrammarTopic.query.get(status.topic_id)
                    if topic:
                        return topic
            except Exception:
                logger.exception("Failed to get active grammar topic for navbar")
            return None

        def get_words_due_count() -> int:
            """Return count of word cards due for review (for nav badge)."""
            from flask_login import current_user
            if not current_user.is_authenticated:
                return 0
            try:
                from app.study.models import UserCardDirection, UserWord
                from app.utils.db import db
                from sqlalchemy import func, or_
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                count = db.session.query(func.count(UserCardDirection.id)).join(
                    UserWord, UserCardDirection.user_word_id == UserWord.id
                ).filter(
                    UserWord.user_id == current_user.id,
                    UserWord.status.in_(['new', 'learning', 'review']),
                    UserCardDirection.direction == 'eng-rus',
                    or_(
                        UserCardDirection.next_review.is_(None),
                        UserCardDirection.next_review <= end_of_today
                    )
                ).scalar() or 0
                return count
            except Exception:
                return 0

        def get_grammar_due_count() -> int:
            """Return count of grammar exercises due for review (for nav badge)."""
            from flask_login import current_user
            if not current_user.is_authenticated:
                return 0
            try:
                from app.grammar_lab.models import UserGrammarExercise
                from app.utils.db import db
                from sqlalchemy import func, or_
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                count = db.session.query(func.count(UserGrammarExercise.id)).filter(
                    UserGrammarExercise.user_id == current_user.id,
                    UserGrammarExercise.state.in_(['learning', 'review', 'relearning']),
                    or_(
                        UserGrammarExercise.next_review.is_(None),
                        UserGrammarExercise.next_review <= end_of_today
                    )
                ).scalar() or 0
                return count
            except Exception:
                return 0

        return dict(
            get_cefr_levels=get_cefr_levels,
            get_user_lessons=get_user_lessons,
            get_curriculum_progress=get_curriculum_progress,
            translate_lesson_type=translate_lesson_type,
            get_lesson_url=get_lesson_url,
            get_active_book_course=get_active_book_course,
            get_active_curriculum_lesson=get_active_curriculum_lesson,
            get_active_grammar_topic=get_active_grammar_topic,
            get_words_due_count=get_words_due_count,
            get_grammar_due_count=get_grammar_due_count
        )

    @app.context_processor
    def inject_xp_data():
        """Inject user XP and level data into templates (cached for 60 seconds)"""
        from flask_login import current_user
        from app.study.models import UserXP
        from app.curriculum.cache import cache

        if not current_user.is_authenticated:
            return {}

        # Try to get from cache first
        cache_key = f'user_xp_{current_user.id}'
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        # Get user XP from database
        user_xp = UserXP.query.filter_by(user_id=current_user.id).first()

        if not user_xp:
            result = {
                'user_xp': 0,
                'user_level': 1,
                'xp_to_next_level': 100,
                'xp_progress_percent': 0
            }
            cache.set(cache_key, result, timeout=60)
            return result

        # Use progressive level system from UserXP model
        result = {
            'user_xp': user_xp.total_xp,
            'user_level': user_xp.level,
            'xp_to_next_level': user_xp.xp_needed_for_next - user_xp.xp_current_level,
            'xp_progress_percent': int(user_xp.level_progress_percent)
        }

        # Cache for 60 seconds
        cache.set(cache_key, result, timeout=60)
        return result

    # Register custom filters
    @app.template_filter('format_chapter_text')
    def format_chapter_text_filter(text):
        """Jinja filter to format chapter text with proper paragraphs"""
        return format_chapter_text(text)

    @app.template_filter('audio_filename')
    def audio_filename_filter(listening):
        """
        Jinja filter to extract clean audio filename.
        Supports both formats in DB:
        - Clean filename: pronunciation_en_word.mp3
        - Legacy Anki format: [sound:pronunciation_en_word.mp3]

        Usage: {{ word.listening|audio_filename }}
        """
        if not listening:
            return ''
        if listening.startswith('[sound:') and listening.endswith(']'):
            return listening[7:-1]
        return listening

    @app.template_filter('sanitize')
    def sanitize_filter(text):
        """
        Jinja filter to sanitize HTML content for safe rendering.
        Strips dangerous tags/attributes while preserving safe formatting HTML.

        Usage: {{ content|sanitize }} (instead of {{ content|safe }})
        """
        if not text:
            return Markup('')
        from app.curriculum.security import sanitize_html
        return Markup(sanitize_html(str(text)))

    @app.template_filter('unescape')
    def unescape_filter(text):
        """
        Jinja filter to decode HTML entities.
        Converts &#39; to ', &amp; to &, etc.

        Usage: {{ note|unescape }}
        """
        import html
        if not text:
            return ''
        return html.unescape(str(text))
