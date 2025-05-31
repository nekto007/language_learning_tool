import copy
import datetime

from flask import request


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


def init_template_utils(app):
    """
    Register template utility functions with the Flask app.

    Args:
        app: Flask application instance
    """

    @app.context_processor
    def utility_processor():
        return {
            'url_params': url_params_with_updated_args
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

        return dict(
            get_cefr_levels=get_cefr_levels,
            get_user_lessons=get_user_lessons,
            get_curriculum_progress=get_curriculum_progress,
            translate_lesson_type=translate_lesson_type
        )
