# app/admin/services/curriculum_import_service.py

"""
Сервис для импорта и обработки учебной программы (Curriculum Import Service)
Обрабатывает JSON данные и создает структуру уроков
"""
import json
import logging
from datetime import UTC, datetime, timedelta

from flask_login import current_user
from sqlalchemy import distinct, func

from app.auth.models import User
from app.books.models import Book
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import Collection, CollectionWordLink, CollectionWords

logger = logging.getLogger(__name__)


class CurriculumImportService:
    """Сервис для импорта и обработки учебных материалов"""

    @staticmethod
    def get_level_name(level_code):
        """Возвращает название для кода уровня CEFR"""
        level_names = {
            'A0': 'Pre-Beginner',
            'A1': 'Beginner',
            'A2': 'Elementary',
            'B1': 'Intermediate',
            'B2': 'Upper Intermediate',
            'C1': 'Advanced',
            'C2': 'Proficiency'
        }
        return level_names.get(level_code, f'Level {level_code}')

    @staticmethod
    def get_level_order(level_code):
        """Возвращает порядок для уровня CEFR"""
        level_orders = {
            'A0': 0,
            'A1': 1,
            'A2': 2,
            'B1': 3,
            'B2': 4,
            'C1': 5,
            'C2': 6
        }
        return level_orders.get(level_code, 99)

    @staticmethod
    def process_vocabulary(vocabulary_data, collection, level_code):
        """
        Обрабатывает словарь без тегов (поддержка двух форматов)

        Args:
            vocabulary_data: Список слов с переводами
            collection: Коллекция для добавления слов
            level_code: Код уровня CEFR
        """
        for word_data in vocabulary_data:
            # Поддержка обоих форматов: {word, translation} и {english, russian}
            english_word = (word_data.get('word') or word_data.get('english', '')).lower()
            translation = word_data.get('translation') or word_data.get('russian', '')

            # Find or create the word
            word = CollectionWords.query.filter_by(english_word=english_word).first()
            if not word:
                word = CollectionWords(
                    english_word=english_word,
                    russian_word=translation,
                    level=level_code,
                    frequency_rank=word_data.get('frequency_rank', 0)
                )
                db.session.add(word)
                db.session.flush()
            else:
                # Update translation or rank if provided
                if word_data.get('frequency_rank'):
                    word.frequency_rank = word_data['frequency_rank']
                word.russian_word = translation

            # Link the word to the collection
            existing = CollectionWordLink.query.filter_by(
                collection_id=collection.id,
                word_id=word.id
            ).first()
            if not existing:
                link = CollectionWordLink(collection_id=collection.id, word_id=word.id)
                db.session.add(link)

    @staticmethod
    def process_grammar(grammar_data):
        """
        Преобразует грамматические данные в формат для хранения

        Args:
            grammar_data: Словарь с грамматическими данными

        Returns:
            dict: Структурированные данные для хранения
        """
        exercises = []

        if 'exercises' in grammar_data:
            for exercise in grammar_data['exercises']:
                exercise_type = exercise.get('type')

                exercise_data = {
                    'type': exercise_type,
                    'text': exercise.get('prompt', ''),
                    'explanation': exercise.get('explanation', '')
                }

                if exercise_type == 'fill_in_blank':
                    exercise_data['answer'] = exercise.get('correct_answer', [])
                    if exercise.get('alternative_answers'):
                        exercise_data['alternative_answers'] = exercise.get('alternative_answers', [])
                elif exercise_type == 'multiple_choice':
                    exercise_data['options'] = exercise.get('options', [])
                    exercise_data['question'] = exercise.get('question', '')
                    exercise_data['answer'] = exercise.get('correct_index')
                elif exercise_type == 'true_false':
                    exercise_data['question'] = exercise.get('question', '')
                    exercise_data['answer'] = exercise.get('correct_answer')
                elif exercise_type == 'match':
                    exercise_data['pairs'] = exercise.get('pairs', [])
                elif exercise_type == 'reorder':
                    exercise_data['words'] = exercise.get('words', [])
                    exercise_data['answer'] = exercise.get('correct_answer', '')
                elif exercise_type == 'translation':
                    exercise_data['answer'] = exercise.get('correct_answer', '')
                    exercise_data['alternative_answers'] = exercise.get('alternative_answers', [])
                else:
                    # Для других типов сохраняем как есть
                    exercise_data['answer'] = exercise.get('answer', '')

                exercises.append(exercise_data)

        return {
            'rule': grammar_data.get('rule', ''),
            'description': grammar_data.get('description', ''),
            'examples': grammar_data.get('examples', []),
            'exercises': exercises
        }

    @staticmethod
    def import_curriculum_data(data):
        """
        Импортирует данные курса из JSON

        Args:
            data (dict): JSON-структура курса

        Returns:
            dict: Информация о созданных объектах
        """
        logger.info("Начинаем импорт данных курса из JSON")

        # Нормализация формата JSON (поддержка двух форматов)
        # Формат 1 (старый): {"level": "A1", "module": 6, "lessons": [...]}
        # Формат 2 (новый): {"module": {"id": 6, "level": "A1", "lessons": [...]}}
        if 'module' in data and isinstance(data['module'], dict):
            module_data = data['module']
            data = {
                'level': module_data.get('level'),
                'module': module_data.get('id') or module_data.get('number'),
                'title': module_data.get('title'),
                'description': module_data.get('description', ''),
                'lessons': module_data.get('lessons', [])
            }
            logger.info("Обнаружен новый формат JSON, выполнена нормализация")

        # Проверяем наличие обязательных полей
        if 'level' not in data or 'module' not in data:
            raise ValueError("В JSON отсутствуют обязательные поля 'level' и 'module'")

        # 1. Создаем или находим уровень CEFR
        level_code = data['level']
        level = CEFRLevel.query.filter_by(code=level_code).first()

        if not level:
            # Создаем новый уровень
            level_name = CurriculumImportService.get_level_name(level_code)
            level = CEFRLevel(
                code=level_code,
                name=level_name,
                description=f"Level {level_code}",
                order=CurriculumImportService.get_level_order(level_code)
            )
            db.session.add(level)
            db.session.flush()
            logger.info(f"Создан новый уровень: {level.code}")

        # 2. Создаем или находим модуль
        module_number = data['module']
        module_description = data.get('description', '')
        module = Module.query.filter_by(level_id=level.id, number=module_number).first()

        if not module:
            # Создаем новый модуль
            module_title = data.get('title', f"Module {module_number}")
            module = Module(
                level_id=level.id,
                number=module_number,
                title=module_title,
                description=module_description,
                raw_content=data
            )
            db.session.add(module)
            db.session.flush()
            logger.info(f"Создан новый модуль: {module.number}")
        else:
            # Обновляем существующий модуль
            module.raw_content = data
            if data.get('title'):
                module.title = data.get('title')
            if module_description:
                module.description = module_description

        # 3. Создаём уроки из списка data['lessons']
        for lesson_data in data.get('lessons', []):
            # Нормализация формата урока (поддержка двух форматов)
            number = lesson_data.get('lesson_number') or lesson_data.get('order') or lesson_data.get('id')
            lesson_type = lesson_data.get('lesson_type') or lesson_data.get('type')
            title = lesson_data.get('title', '')
            lesson = Lessons.query.filter_by(module_id=module.id, number=number).first()

            if not lesson:
                lesson = Lessons(
                    module_id=module.id,
                    number=number,
                    title=title,
                    type=lesson_type if lesson_type != 'text' else 'text',
                    order=number,
                    description=title
                )
                db.session.add(lesson)
                db.session.flush()
            else:
                # Update existing lesson metadata
                if title:
                    lesson.title = title
                    lesson.description = title
                if lesson_type:
                    lesson.type = lesson_type if lesson_type != 'text' else 'text'

            # Обрабатываем контент по типу урока
            if lesson_type == 'grammar':
                theory = lesson_data.get('theory', {})
                content = lesson_data.get('content', {})
                grammar_explanation = content.get('grammar_explanation', {})

                grammar_input = {
                    'rule': theory.get('rule', '') or grammar_explanation.get('rule', ''),
                    'description': theory.get('description', '') or grammar_explanation.get('introduction', ''),
                    'examples': theory.get('examples', []) or grammar_explanation.get('examples', []),
                    'exercises': lesson_data.get('exercises', []) or content.get('exercises', [])
                }
                lesson.content = CurriculumImportService.process_grammar(grammar_input)

            elif lesson_type == 'vocabulary':
                # Поддержка обоих форматов: words или content.vocabulary
                vocab_list = lesson_data.get('words', [])
                if not vocab_list and lesson_data.get('content'):
                    vocab_list = lesson_data['content'].get('vocabulary', [])
                # Создаем или получаем коллекцию
                collection_name = f"{module.title} - {level_code} Module {module_number} Vocabulary"
                collection = Collection.query.filter_by(name=collection_name).first()
                if not collection:
                    collection = Collection(
                        name=collection_name,
                        description=module.title,
                        created_by=current_user.id
                    )
                    db.session.add(collection)
                    db.session.flush()
                # Очищаем старые связи и обрабатываем слова
                CollectionWordLink.query.filter_by(collection_id=collection.id).delete()
                CurriculumImportService.process_vocabulary(vocab_list, collection, level_code)
                lesson.collection_id = collection.id
                lesson.content = vocab_list

            elif lesson_type == 'card':
                lesson.content = {
                    'settings': lesson_data.get('settings', {}),
                    'cards': lesson_data.get('cards', []),
                    'note': lesson_data.get('note', '')
                }
            elif lesson_type == 'quiz':
                lesson.content = {'exercises': lesson_data.get('exercises', [])}
            elif lesson_type == 'text':
                lesson.content = lesson_data.get('content', {})
            elif lesson_type == 'final_test':
                lesson.content = {
                    'passing_score_percent': lesson_data.get('passing_score_percent', 0),
                    'exercises': lesson_data.get('exercises', [])
                }
            else:
                lesson.content = lesson_data

        # 4. Сохраняем все изменения
        db.session.commit()

        # Возвращаем результат
        first_lesson = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.order).first()
        first_lesson_id = first_lesson.id if first_lesson else None

        result = {
            "level_id": level.id,
            "module_id": module.id,
            "lesson_id": first_lesson_id
        }

        logger.info("Импорт завершен успешно.")
        return result

    @staticmethod
    def get_word_status_statistics():
        """Получает статистику по статусам слов"""
        try:
            # Статистика по всем пользователям
            status_stats = db.session.query(
                UserWord.status,
                func.count(UserWord.id).label('count'),
                func.count(func.distinct(UserWord.user_id)).label('users')
            ).group_by(UserWord.status).all()

            # Общая статистика
            total_user_words = UserWord.query.count()
            total_unique_words = db.session.query(
                func.count(func.distinct(UserWord.word_id))
            ).scalar()
            total_users_with_words = db.session.query(
                func.count(func.distinct(UserWord.user_id))
            ).scalar()

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
    def get_recent_db_operations():
        """Получает список недавних операций с БД"""
        try:
            # Недавние уроки
            recent_lessons = Lessons.query.order_by(Lessons.created_at.desc()).limit(5).all()

            # Недавно зарегистрированные пользователи
            # Use datetime.now(UTC) and convert to naive for DB compatibility
            week_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
            recent_users = User.query.filter(
                User.created_at >= week_ago
            ).order_by(User.created_at.desc()).limit(5).all()

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

    @staticmethod
    def test_database_connection():
        """Тестирует подключение к базе данных"""
        try:
            from config.settings import DB_CONFIG
            from app.repository import DatabaseRepository

            repo = DatabaseRepository(DB_CONFIG)
            with repo.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT version()")
                    version = cursor.fetchone()[0]

                    # Дополнительные проверки
                    cursor.execute(
                        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
                    )
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
