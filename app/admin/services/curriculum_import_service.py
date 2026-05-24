# app/admin/services/curriculum_import_service.py

"""
Сервис для импорта и обработки учебной программы (Curriculum Import Service)
Обрабатывает JSON данные и создает структуру уроков
"""

import logging
from datetime import UTC, datetime, timedelta

from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.study.models import UserWord
from app.utils.audio import normalize_listening
from app.utils.db import db
from app.words.models import Collection, CollectionWordLink, CollectionWords

logger = logging.getLogger(__name__)

ALLOWED_CEFR_LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')


class CurriculumImportService:
    """Сервис для импорта и обработки учебных материалов"""

    @staticmethod
    def get_level_name(level_code):
        """Возвращает название для кода уровня CEFR"""
        level_names = {
            'A1': 'Beginner',
            'A2': 'Elementary',
            'B1': 'Intermediate',
            'B2': 'Upper Intermediate',
            'C1': 'Advanced'
        }
        return level_names.get(level_code, f'Level {level_code}')

    @staticmethod
    def get_level_order(level_code):
        """Возвращает порядок для уровня CEFR"""
        level_orders = {
            'A1': 1,
            'A2': 2,
            'B1': 3,
            'B2': 4,
            'C1': 5
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

            # Формируем sentences как plain text (en\nru) для фронтенда
            sentences_text = None
            if word_data.get('example'):
                en = word_data.get('example', '')
                ru = word_data.get('example_translation', '')
                sentences_text = f"{en}<br>{ru}" if ru else en

            # Find or create the word
            word = CollectionWords.query.filter_by(english_word=english_word).first()
            if not word:
                word = CollectionWords(
                    english_word=english_word,
                    russian_word=translation,
                    level=level_code,
                    frequency_rank=word_data.get('frequency_rank', 0),
                    listening=normalize_listening(word_data.get('audio', ''), english_word),
                    sentences=sentences_text
                )
                db.session.add(word)
                db.session.flush()
            else:
                # Update all fields if provided
                if word_data.get('frequency_rank'):
                    word.frequency_rank = word_data['frequency_rank']
                # Always update both english and russian to fix any data issues
                word.english_word = english_word
                word.russian_word = translation
                # Update listening and sentences if provided
                if word_data.get('audio'):
                    word.listening = normalize_listening(word_data['audio'], english_word)
                if sentences_text:
                    word.sentences = sentences_text

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
    def process_grammar_lesson_content(lesson_data):
        """Build persisted content for a grammar lesson without losing rich sections.

        Older imports stored grammar as top-level rule/description/examples.
        Current module JSON can store the full explanation directly under
        content.sections, or wrapped in content.grammar_explanation.  Preserve
        those rich fields so example audio refs survive re-imports.
        """
        theory = lesson_data.get('theory', {}) or {}
        content = lesson_data.get('content', {}) or {}
        if not isinstance(content, dict):
            content = {}
        grammar_explanation = content.get('grammar_explanation', {}) or {}
        if not isinstance(grammar_explanation, dict):
            grammar_explanation = {}

        grammar_input = {
            'rule': (
                theory.get('rule', '')
                or grammar_explanation.get('rule', '')
                or content.get('rule', '')
            ),
            'description': (
                theory.get('description', '')
                or grammar_explanation.get('introduction', '')
                or content.get('description', '')
                or content.get('content', '')
            ),
            'examples': (
                theory.get('examples', [])
                or grammar_explanation.get('examples', [])
                or content.get('examples', [])
            ),
            'exercises': lesson_data.get('exercises', []) or content.get('exercises', []),
        }
        processed_grammar = CurriculumImportService.process_grammar(grammar_input)

        rich_source = grammar_explanation if grammar_explanation else content
        if grammar_explanation or content.get('sections'):
            processed_grammar['title'] = rich_source.get('title', '')
            processed_grammar['sections'] = rich_source.get('sections', [])
            processed_grammar['important_notes'] = rich_source.get('important_notes', [])
            processed_grammar['summary'] = rich_source.get('summary', {})
            if rich_source.get('tldr'):
                processed_grammar['tldr'] = rich_source['tldr']

        processed_grammar['xp_reward'] = lesson_data.get('xp_reward')
        return processed_grammar

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

        # Сохраняем оригинальный JSON до нормализации (для raw_content)
        original_data = data

        # Нормализация формата JSON (поддержка двух форматов)
        # Формат 1 (старый): {"level": "A1", "module": 6, "lessons": [...]}
        # Формат 2 (новый): {"module": {"id": 6, "level": "A1", "lessons": [...]}}
        if 'module' in data and isinstance(data['module'], dict):
            module_data = data['module']
            data = {
                'level': module_data.get('level'),
                'module': module_data.get('order') or module_data.get('id') or module_data.get('number'),
                'title': module_data.get('title'),
                'title_en': module_data.get('title_en'),
                'description': module_data.get('description', ''),
                'input_mode': module_data.get('input_mode', 'selection_only'),
                'prerequisites': module_data.get('prerequisites', []),
                'skills_learned': module_data.get('skills_learned', []),
                'total_xp': module_data.get('total_xp'),
                'estimated_time': module_data.get('estimated_time'),
                'lessons': module_data.get('lessons', [])
            }
            logger.info(f"Обнаружен новый формат JSON, level={data.get('level')}, module={data.get('module')}, input_mode={data.get('input_mode')}")

        # Проверяем наличие обязательных полей
        if 'level' not in data or 'module' not in data:
            raise ValueError("В JSON отсутствуют обязательные поля 'level' и 'module'")

        # 1. Создаем или находим уровень CEFR
        level_code = data['level']
        if level_code not in ALLOWED_CEFR_LEVELS:
            raise ValueError(
                f"Недопустимый уровень CEFR '{level_code}'. "
                f"Разрешены: {', '.join(ALLOWED_CEFR_LEVELS)}."
            )
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

        # Ищем модуль по level_id + number (единственный надёжный способ)
        # НЕ используем explicit_module_id для поиска — id в JSON относительный, не DB PK
        module = Module.query.filter_by(level_id=level.id, number=module_number).first()

        # Получаем prerequisites из JSON
        module_prerequisites = data.get('prerequisites', [])

        if not module:
            # Создаем новый модуль с явным ID если указан
            module_title = data.get('title', f"Module {module_number}")
            module = Module(
                level_id=level.id,
                number=module_number,
                title=module_title,
                description=module_description,
                raw_content=original_data,
                input_mode=data.get('input_mode', 'selection_only'),
                prerequisites=module_prerequisites if module_prerequisites else None
            )
            # НЕ используем explicit_module_id как PK — пусть БД генерирует ID
            db.session.add(module)
            db.session.flush()
            logger.info(f"Создан новый модуль: id={module.id}, number={module.number}")
        else:
            # Обновляем существующий модуль
            module.raw_content = original_data
            module.level_id = level.id
            module.number = module_number
            if data.get('title'):
                module.title = data.get('title')
            if module_description:
                module.description = module_description
            if data.get('input_mode'):
                module.input_mode = data.get('input_mode')
            if module_prerequisites:
                module.prerequisites = module_prerequisites

        # 3. Создаём уроки из списка data['lessons']
        # Pre-fetch all existing lessons for the module and build an external_key
        # index so that renumbered source files don't silently mutate the wrong
        # DB row. Identity resolution order: external_key first, then (module_id,
        # number), then explicit JSON id (within-module only).
        existing_module_lessons = Lessons.query.filter_by(module_id=module.id).all()
        _by_external_key: dict[str, 'Lessons'] = {}
        for _l in existing_module_lessons:
            if isinstance(_l.content, dict):
                _ek = _l.content.get('external_key')
                if _ek and isinstance(_ek, str) and _ek.strip():
                    _by_external_key[_ek.strip()] = _l

        # Position-based fallback index (original numbers before any renumbering).
        _by_original_number: dict = {_l.number: _l for _l in existing_module_lessons}

        # Type+title fallback for DB lessons that have no external_key.
        # Normalise to (type, stripped_lower_title) so whitespace/case differences
        # do not create phantom duplicates when source renumbers but keeps titles.
        _by_type_title: dict = {
            (_l.type, _l.title.strip().lower()): _l
            for _l in existing_module_lessons
            if _l.type and _l.title
        }

        # Pre-shift all existing lesson numbers to a high offset so that inserting
        # new lessons in the middle (or reassigning numbers) does not violate the
        # unique (module_id, number) index mid-loop.  Lessons not matched by any
        # source entry are restored to their original numbers after the loop.
        _SHIFT = 10000
        for _l in existing_module_lessons:
            _l.number = _l.number + _SHIFT
            _l.order = _l.order + _SHIFT
        if existing_module_lessons:
            db.session.flush()

        # Track numbers assigned during the loop so the restore pass can detect
        # collisions before they hit the unique (module_id, number) constraint.
        _used_numbers: set[int] = set()

        for lesson_data in data.get('lessons', []):
            # Нормализация формата урока (поддержка двух форматов)
            explicit_lesson_id = lesson_data.get('id')
            number = lesson_data.get('lesson_number') or lesson_data.get('order') or lesson_data.get('id')
            lesson_type = lesson_data.get('lesson_type') or lesson_data.get('type')
            title = lesson_data.get('title', '')

            # Маппинг типов уроков (flashcards -> card)
            type_mapping = {
                'flashcards': 'card',
            }
            lesson_type = type_mapping.get(lesson_type, lesson_type)

            # Ищем урок по stable external_key (приоритет над позицией, чтобы
            # переупорядочивание в источнике не перезаписывало чужой урок).
            lesson = None
            src_content = lesson_data.get('content') or {}
            src_external_key = src_content.get('external_key') if isinstance(src_content, dict) else None
            if src_external_key and isinstance(src_external_key, str) and src_external_key.strip():
                lesson = _by_external_key.get(src_external_key.strip())
                if lesson:
                    logger.debug(f"Найден урок по external_key={src_external_key!r}: id={lesson.id}")

            # Если не нашли по external_key — ищем по (type, title) для унаследованных
            # уроков без ключа, затем по оригинальной позиции как последний вариант.
            # (type, title) идёт первым: number — это порядковые метаданные, не identity.
            # Если у источника есть external_key, fallback срабатывает только на
            # legacy DB-уроках без external_key — иначе мы могли бы переписать
            # урок с одним ключом данными урока с другим ключом.
            def _is_legacy(_l) -> bool:
                if not isinstance(_l.content, dict):
                    return True
                existing_key = _l.content.get('external_key')
                return not (existing_key and isinstance(existing_key, str) and existing_key.strip())

            if not lesson:
                candidate = None
                if lesson_type and title:
                    candidate = _by_type_title.get((lesson_type, title.strip().lower()))
                if not candidate:
                    candidate = _by_original_number.get(number)
                if candidate and (not src_external_key or _is_legacy(candidate)):
                    lesson = candidate

            # Явный ID в JSON — это относительный порядковый номер внутри модуля,
            # не глобальный DB PK. Используем только как запасной вариант и только
            # для legacy уроков без external_key.
            if not lesson and explicit_lesson_id:
                existing = Lessons.query.get(explicit_lesson_id)
                if (
                    existing
                    and existing.module_id == module.id
                    and (not src_external_key or _is_legacy(existing))
                ):
                    lesson = existing

            if not lesson:
                lesson = Lessons(
                    module_id=module.id,
                    number=number,
                    title=title,
                    type=lesson_type if lesson_type != 'text' else 'text',
                    order=number,
                    description=lesson_data.get('grammar_focus') or title
                )
                # НЕ используем explicit_lesson_id - это относительные ID внутри модуля,
                # не глобально уникальные. Пусть БД генерирует ID автоматически.
                db.session.add(lesson)
                db.session.flush()
                logger.info(f"Создан урок: id={lesson.id}, number={number}, type={lesson_type}")
            else:
                # Update existing lesson metadata
                if title:
                    lesson.title = title
                if lesson_data.get('grammar_focus'):
                    lesson.description = lesson_data.get('grammar_focus')
                elif title:
                    lesson.description = title
                if lesson_type:
                    lesson.type = lesson_type if lesson_type != 'text' else 'text'
                lesson.number = number
                lesson.order = number

            # Обрабатываем контент по типу урока
            if lesson_type == 'grammar':
                lesson.content = CurriculumImportService.process_grammar_lesson_content(
                    lesson_data
                )

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
                lesson.content = {
                    'vocabulary': vocab_list,
                    'xp_reward': lesson_data.get('xp_reward')
                }

            elif lesson_type == 'card':
                # Карточки могут быть в content.cards или напрямую в cards
                content = lesson_data.get('content', {})
                cards = content.get('cards', []) if isinstance(content, dict) else []
                if not cards:
                    cards = lesson_data.get('cards', [])
                lesson.content = {
                    'settings': lesson_data.get('settings', {}),
                    'cards': cards,
                    'note': lesson_data.get('note', ''),
                    'xp_reward': lesson_data.get('xp_reward')
                }
            elif lesson_type == 'quiz':
                # Quiz может иметь exercises в content или напрямую
                content = lesson_data.get('content', {})
                exercises = content.get('exercises', []) if isinstance(content, dict) else []
                if not exercises:
                    exercises = lesson_data.get('exercises', [])
                lesson.content = {
                    'exercises': exercises,
                    'xp_reward': lesson_data.get('xp_reward')
                }
            elif lesson_type == 'text':
                content = lesson_data.get('content', {})
                if lesson_data.get('xp_reward'):
                    content['xp_reward'] = lesson_data.get('xp_reward')
                lesson.content = content
            elif lesson_type == 'final_test':
                content = lesson_data.get('content', {})
                lesson.content = {
                    'passing_score': content.get('passing_score', lesson_data.get('passing_score_percent', 75)),
                    'total_points': content.get('total_points', 100),
                    'test_sections': content.get('test_sections', []),
                    'exercises': lesson_data.get('exercises', []),
                    'xp_reward': lesson_data.get('xp_reward')
                }
            elif lesson_type in ('reading', 'listening_quiz', 'dialogue_completion_quiz',
                                 'ordering_quiz', 'translation_quiz', 'listening_immersion'):
                # Новые типы уроков - сохраняем content как есть
                content = lesson_data.get('content', {})
                if lesson_data.get('xp_reward'):
                    content['xp_reward'] = lesson_data.get('xp_reward')
                lesson.content = content
            else:
                # Для неизвестных типов сохраняем всё содержимое
                content = lesson_data.get('content', lesson_data)
                if isinstance(content, dict) and lesson_data.get('xp_reward'):
                    content['xp_reward'] = lesson_data.get('xp_reward')
                lesson.content = content

            # Preserve external_key in persisted content so re-imports use key-based matching
            if src_external_key and isinstance(lesson.content, dict):
                lesson.content['external_key'] = src_external_key.strip()

            _used_numbers.add(number)
            # Явно помечаем content как изменённый для SQLAlchemy
            flag_modified(lesson, 'content')
            # Принудительно сохраняем изменения урока
            db.session.flush()
            logger.info(f"Обновлён урок id={lesson.id}: type={lesson_type}, content_keys={list(lesson.content.keys()) if isinstance(lesson.content, dict) else 'not dict'}")

        # Restore any existing lessons that were pre-shifted but not matched by a
        # source entry (DB lessons absent from the new JSON).  Guard against
        # collisions: if the original number was taken by a new/renumbered lesson,
        # place the unmatched row beyond the highest currently-used number.
        _max_used = max(_used_numbers) if _used_numbers else 0
        for _l in existing_module_lessons:
            if _l.number >= _SHIFT:
                original_number = _l.number - _SHIFT
                original_order = _l.order - _SHIFT
                if original_number not in _used_numbers:
                    _l.number = original_number
                    _l.order = original_order
                    _used_numbers.add(original_number)
                else:
                    _max_used += 1
                    _l.number = _max_used
                    _l.order = _max_used
                    _used_numbers.add(_max_used)
                    logger.warning(
                        f"Урок id={_l.id}: original number={original_number} занят новым уроком — "
                        f"смещён на number={_max_used}"
                    )
                logger.warning(
                    f"Урок id={_l.id} (number={_l.number}) не найден в источнике — "
                    f"оставлен с исходным номером"
                )

        # 4. Сохраняем все изменения
        db.session.commit()
        logger.info(f"Commit выполнен для модуля {module.id}")

        # 5. Сбрасываем PostgreSQL последовательности чтобы избежать конфликтов ID
        CurriculumImportService._reset_sequences()

        # Возвращаем результат
        first_lesson = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.number).first()
        first_lesson_id = first_lesson.id if first_lesson else None

        result = {
            "level_id": level.id,
            "module_id": module.id,
            "lesson_id": first_lesson_id
        }

        logger.info("Импорт завершен успешно.")
        return result

    @staticmethod
    def _reset_sequences():
        """Сбрасывает PostgreSQL последовательности для таблиц с явными ID"""
        try:
            # Сброс последовательности для modules
            db.session.execute(db.text(
                "SELECT setval('modules_id_seq', COALESCE((SELECT MAX(id) FROM modules), 1), true)"
            ))
            # Сброс последовательности для lessons
            db.session.execute(db.text(
                "SELECT setval('lessons_id_seq', COALESCE((SELECT MAX(id) FROM lessons), 1), true)"
            ))
            db.session.commit()
            logger.info("PostgreSQL последовательности успешно сброшены")
        except Exception as e:
            logger.warning(f"Не удалось сбросить последовательности: {e}")

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
