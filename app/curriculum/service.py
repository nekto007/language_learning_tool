# app/curriculum/service.py

from datetime import datetime, UTC

from sqlalchemy import Date, cast, func

from app.curriculum.models import LessonProgress, Lessons, Module
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords


def get_user_level_progress(user_id):
    """
    Получает прогресс пользователя по всем уровням CEFR

    Args:
        user_id (int): ID пользователя

    Returns:
        dict: Словарь с данными о прогрессе пользователя по уровням
    """
    from app.curriculum.models import CEFRLevel

    # Получаем все уровни
    levels = CEFRLevel.query.all()
    level_ids = [level.id for level in levels]

    # Получаем все модули для этих уровней
    modules = Module.query.filter(Module.level_id.in_(level_ids)).all()
    module_ids = [module.id for module in modules]

    # Получаем все уроки для этих модулей
    lessons = Lessons.query.filter(Lessons.module_id.in_(module_ids)).all()
    lesson_ids = [lesson.id for lesson in lessons]

    # Получаем статистику по завершенным урокам
    completed_lessons = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.lesson_id.in_(lesson_ids),
        LessonProgress.status == 'completed'
    ).all()

    # Вычисляем прогресс для каждого уровня
    level_progress = {}

    for level in levels:
        # Получаем все уроки для этого уровня
        level_modules = [module for module in modules if module.level_id == level.id]
        level_module_ids = [module.id for module in level_modules]
        level_lessons = [lesson for lesson in lessons if lesson.module_id in level_module_ids]

        # Общее количество уроков на этом уровне
        total_lessons = len(level_lessons)

        # Количество завершенных уроков
        completed_lesson_ids = [progress.lesson_id for progress in completed_lessons]
        completed_count = sum(1 for lesson in level_lessons if lesson.id in completed_lesson_ids)

        # Вычисляем процент прогресса
        progress_percent = int((completed_count / total_lessons) * 100) if total_lessons > 0 else 0

        # Сохраняем данные о прогрессе
        level_progress[level.id] = {
            'level': level,
            'total_lessons': total_lessons,
            'completed_lessons': completed_count,
            'progress_percent': progress_percent
        }

    return level_progress


def get_user_active_lessons(user_id, limit=5):
    """
    Получает список активных уроков пользователя

    Args:
        user_id (int): ID пользователя
        limit (int): Максимальное количество уроков для возврата

    Returns:
        list: Список активных уроков с данными о прогрессе
    """
    # Получаем уроки, которые пользователь начал, но не завершил
    in_progress_lessons = db.session.query(
        Lessons,
        LessonProgress
    ).join(
        LessonProgress,
        Lessons.id == LessonProgress.lesson_id
    ).filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'in_progress'
    ).order_by(
        LessonProgress.last_activity.desc()
    ).limit(limit).all()

    # Форматируем результаты
    active_lessons = []
    for lesson, progress in in_progress_lessons:
        module = Module.query.get(lesson.module_id)
        level = module.level

        active_lessons.append({
            'lesson': lesson,
            'module': module,
            'level': level,
            'progress': progress,
            'last_activity': progress.last_activity
        })

    return active_lessons


def get_next_lesson(current_lesson_id):
    """
    Находит следующий урок после текущего в рамках модуля

    Args:
        current_lesson_id (int): ID текущего урока

    Returns:
        Lessons: Объект следующего урока или None, если текущий урок последний
    """
    current_lesson = Lessons.query.get(current_lesson_id)
    if not current_lesson:
        return None

    # Находим следующий урок в порядке 'order' в рамках модуля
    next_lesson = None
    if current_lesson.order is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == current_lesson.module_id,
            Lessons.order > current_lesson.order
        ).order_by(
            Lessons.order
        ).first()

    # Если урок с большим order не найден, пробуем найти по номеру урока
    if not next_lesson and current_lesson.number is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == current_lesson.module_id,
            Lessons.number > current_lesson.number
        ).order_by(
            Lessons.number
        ).first()

    return next_lesson


def complete_lesson(user_id, lesson_id, score=100.0):
    """
    Отмечает урок как завершенный для пользователя

    Args:
        user_id (int): ID пользователя
        lesson_id (int): ID урока
        score (float): Оценка за урок (0-100)

    Returns:
        LessonProgress: Объект прогресса урока или None при ошибке
    """
    progress = LessonProgress.query.filter_by(
        user_id=user_id,
        lesson_id=lesson_id
    ).first()

    # Track if this is an existing progress (for legacy attempt detection)
    existing_progress = progress is not None
    previous_score = progress.score if existing_progress else 0

    if not progress:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status='in_progress',
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC)
        )
        db.session.add(progress)

    progress.status = 'completed'
    progress.completed_at = datetime.now(UTC)
    progress.score = round(score, 2)
    progress.last_activity = datetime.now(UTC)

    try:
        # First commit to get progress.id
        db.session.commit()

        # Now create LessonAttempt record with valid progress_id
        from app.curriculum.models import LessonAttempt

        # Check if this is a legacy progress without attempts
        # If so, create a retroactive attempt for the previous completion
        # Only for existing progress that was already completed with a score
        if existing_progress and len(progress.attempts) == 0 and previous_score > 0:
            # Create retroactive attempt for the existing score
            legacy_attempt = LessonAttempt(
                user_id=user_id,
                lesson_id=lesson_id,
                lesson_progress_id=progress.id,
                attempt_number=1,
                started_at=progress.started_at,
                completed_at=progress.completed_at or progress.last_activity,
                score=progress.score,
                passed=(progress.score >= 70)
            )
            db.session.add(legacy_attempt)
            db.session.commit()
            db.session.refresh(progress)

        # Create new attempt
        attempt_number = len(progress.attempts) + 1
        attempt = LessonAttempt(
            user_id=user_id,
            lesson_id=lesson_id,
            lesson_progress_id=progress.id,
            attempt_number=attempt_number,
            started_at=progress.started_at,
            completed_at=progress.completed_at,
            score=score,
            passed=(score >= 70)  # Assuming 70% is passing score
        )
        db.session.add(attempt)
        db.session.commit()

        # Refresh to load relationships
        db.session.refresh(progress)

        # Award XP for completing lesson (optional - may not be available)
        try:
            from app.study.xp_service import XPService
            xp_breakdown = XPService.calculate_lesson_xp()
            XPService.award_xp(user_id, xp_breakdown['total_xp'])
        except (ImportError, AttributeError):
            pass  # XP service not available, skip

        return progress
    except Exception as e:
        db.session.rollback()
        return None


def process_grammar_submission(exercises, answers):
    """
    Обрабатывает ответы на грамматические упражнения

    Args:
        exercises (list): Список грамматических упражнений
        answers (dict): Словарь с ответами пользователя

    Returns:
        dict: Результаты проверки ответов
    """
    import json

    correct_count = 0
    total_count = len(exercises)
    feedback = {}

    for i, exercise in enumerate(exercises):
        # Преобразуем строковые ключи в числовые для совместимости
        str_i = str(i)

        # Обработка упражнения типа 'sentence_builder'
        if exercise.get('type') == 'sentence_builder':
            user_answer = answers.get(i, answers.get(str_i, []))
            correct_order = exercise.get('correct_order', [])

            # Сравниваем порядок слов
            is_correct = user_answer == correct_order

            if is_correct:
                correct_count += 1
                feedback[str_i] = {
                    'status': 'correct',
                    'message': 'Правильно!',
                    'user_answer': user_answer,
                    'correct_answer': correct_order
                }
            else:
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': f'Неправильно. Правильный порядок: {" ".join(correct_order)}',
                    'user_answer': user_answer,
                    'correct_answer': correct_order
                }
            continue

        # Обработка упражнения типа 'error_correction'
        if exercise.get('type') == 'error_correction':
            user_answer = answers.get(i, answers.get(str_i, ''))
            correct_answer = exercise.get('correct_sentence', exercise.get('answer', ''))

            # Нормализуем и сравниваем
            user_normalized = normalize_text(user_answer)
            correct_normalized = normalize_text(correct_answer)

            is_correct = user_normalized == correct_normalized

            if is_correct:
                correct_count += 1
                feedback[str_i] = {
                    'status': 'correct',
                    'message': 'Правильно!',
                    'user_answer': user_answer,
                    'correct_answer': correct_answer
                }
            else:
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': f'Неправильно. Правильный ответ: {correct_answer}',
                    'user_answer': user_answer,
                    'correct_answer': correct_answer
                }
            continue

        # Обработка упражнения типа 'reorder'
        if exercise.get('type') == 'reorder':
            user_answer = answers.get(i, answers.get(str_i, ''))
            correct_answer = exercise.get('answer', '')

            # Улучшенная нормализация предложений для сравнения
            def normalize_sentence(sentence):
                """Нормализует предложение для сравнения"""
                if not sentence:
                    return ""

                import re

                # Убираем лишние пробелы в начале и конце
                normalized = sentence.strip()

                # Убираем множественные пробелы между словами
                normalized = re.sub(r'\s+', ' ', normalized)

                # Убираем пробелы перед знаками препинания
                normalized = re.sub(r'\s+([.,!?;:])', r'\1', normalized)

                # Убираем пробелы после открывающих скобок и перед закрывающими
                normalized = re.sub(r'(\()\s+', r'\1', normalized)
                normalized = re.sub(r'\s+(\))', r'\1', normalized)

                # Для сравнения приводим к нижнему регистру, но сохраняем оригинал для проверки
                return normalized

            # Нормализуем оба ответа
            user_normalized = normalize_sentence(user_answer)
            correct_normalized = normalize_sentence(correct_answer)

            # Сначала проверяем точное совпадение (с учетом регистра)
            is_correct = user_normalized == correct_normalized

            # Если не совпадает, проверяем без учета регистра
            if not is_correct:
                is_correct = user_normalized.lower() == correct_normalized.lower()

            if is_correct:
                correct_count += 1
                feedback[str_i] = {
                    'status': 'correct',
                    'message': 'Правильно!',
                    'user_answer': user_answer,
                    'correct_answer': correct_answer
                }
            else:
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': f'Неправильно. Правильный порядок: {correct_answer}',
                    'user_answer': user_answer,
                    'correct_answer': correct_answer
                }
            continue

        # Обработка упражнения типа 'match'
        elif exercise.get('type') == 'match':
            pairs = exercise.get('pairs', [])
            user_matches_raw = answers.get(i, answers.get(str_i, '{}'))


            # Преобразуем JSON строку в словарь если нужно
            if isinstance(user_matches_raw, str):
                try:
                    user_matches = json.loads(user_matches_raw)
                except json.JSONDecodeError:
                    user_matches = {}
            else:
                user_matches = user_matches_raw


            # Проверяем ответы пользователя
            is_correct = True
            user_match_display = {}
            correct_match_display = {}

            # Создаем словарь правильных соответствий
            for idx, pair in enumerate(pairs):
                correct_match_display[pair['left']] = pair['right']

            # Проверяем, что все пары заполнены
            if len(user_matches) != len(pairs):
                is_correct = False
            else:
                # Проверяем каждое сопоставление
                for left_idx_str, right_idx_str in user_matches.items():
                    try:
                        left_idx = int(left_idx_str)
                        right_idx = int(right_idx_str)

                        if left_idx >= len(pairs) or right_idx >= len(pairs):
                            is_correct = False
                            continue

                        left_value = pairs[left_idx]['left']
                        user_right_value = pairs[right_idx]['right']
                        correct_right_value = pairs[left_idx]['right']

                        user_match_display[left_value] = user_right_value

                        # Проверяем соответствие
                        if user_right_value != correct_right_value:
                            is_correct = False
                    except (ValueError, IndexError, KeyError) as e:
                        is_correct = False
                        break

            if is_correct:
                correct_count += 1
                feedback[str_i] = {
                    'status': 'correct',
                    'message': 'Правильно! Все соответствия верны.',
                    'user_matches': user_match_display,
                    'correct_matches': correct_match_display
                }
            else:
                # Показываем правильные соответствия для обучения
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': 'Неправильно. Проверьте соответствия.',
                    'user_matches': user_match_display,
                    'correct_matches': correct_match_display
                }
            continue

        # Обработка для остальных типов упражнений
        user_answer = str(answers.get(i, answers.get(str_i, '')))
        if isinstance(user_answer, str):
            user_answer = user_answer.strip()

        # Получаем правильный ответ из упражнения
        correct_answer = None
        # Проверяем все возможные поля для правильного ответа
        if 'answer' in exercise:
            correct_answer = exercise['answer']
        elif 'correct_answer' in exercise:
            correct_answer = exercise['correct_answer']
        elif 'correct' in exercise:
            correct_answer = exercise['correct']
        elif 'answers' in exercise and isinstance(exercise['answers'], list) and len(exercise['answers']) > 0:
            correct_answer = exercise['answers'][0]
        else:
            correct_answer = None

        # Специальная обработка для разных типов упражнений
        exercise_type = exercise.get('type', '')

        # Обработка true_false
        if exercise_type == 'true_false':
            # Проверяем, что у нас есть правильный ответ
            if correct_answer is None:
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': 'Ошибка в упражнении - не найден правильный ответ',
                    'user_answer': user_answer,
                    'correct_answer': 'unknown'
                }
                continue

            # Преобразуем ответ пользователя в булево значение
            user_bool = user_answer.lower() == 'true' if isinstance(user_answer, str) else bool(user_answer)
            # Убеждаемся, что правильный ответ - булево значение
            correct_bool = correct_answer if isinstance(correct_answer, bool) else (
                    str(correct_answer).lower() == 'true')

            is_correct = user_bool == correct_bool

            if is_correct:
                correct_count += 1
                feedback[str_i] = {
                    'status': 'correct',
                    'message': 'Правильно!',
                    'user_answer': user_answer,
                    'correct_answer': correct_answer
                }
            else:
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': f'Неправильно. Правильный ответ: {"Верно" if correct_bool else "Неверно"}',
                    'user_answer': user_answer,
                    'correct_answer': correct_answer
                }
            continue

        # Обработка радио-кнопок (multiple_choice)
        elif exercise_type == 'multiple_choice' and 'options' in exercise:
            options = exercise['options']
            # Если правильный ответ - индекс
            if isinstance(correct_answer, (int, str)) and str(correct_answer).isdigit():
                correct_idx = int(correct_answer)
                # Проверяем, что пользователь отправил текст варианта
                if user_answer in options:
                    # Находим индекс выбранного варианта
                    user_idx = options.index(user_answer)
                    # Сравниваем индексы
                    user_answer = str(user_idx)
                    correct_answer = str(correct_idx)
                # Если пользователь отправил индекс
                elif user_answer.isdigit():
                    # Оставляем как есть для сравнения
                    correct_answer = str(correct_idx)
            # Если правильный ответ - текст
            else:
                # Если пользователь отправил индекс, преобразуем в текст
                if user_answer.isdigit() and int(user_answer) < len(options):
                    idx = int(user_answer)
                    user_answer = options[idx]

        # Преобразуем список в строку для сравнения
        if isinstance(correct_answer, list):
            # Для fill-in-blank упражнений с массивом ответов
            if exercise_type in ['fill-blank', 'fill_in_blank']:
                # Проверяем, если это начало предложения
                prompt_text = exercise.get('prompt', exercise.get('text', ''))
                is_sentence_start = prompt_text.strip().startswith('___') or prompt_text.strip().startswith('_')

                # if is_sentence_start:
                #     # Для начала предложения - точное сравнение с учетом регистра
                #     is_correct = user_answer.lower() in correct_answer.lower
                #     print(
                #         f"Checking against array with case sensitivity: '{user_answer}' in {correct_answer} = {is_correct}")
                # else:
                #     # Нормализуем для сравнения
                user_norm = user_answer.lower().strip()
                is_correct = any(user_norm == ans.lower().strip() for ans in correct_answer)

                if is_correct:
                    correct_count += 1
                    feedback[str_i] = {
                        'status': 'correct',
                        'message': 'Правильно!',
                        'user_answer': user_answer,
                        'correct_answer': correct_answer
                    }
                else:
                    feedback[str_i] = {
                        'status': 'incorrect',
                        'message': f'Неправильно. Правильный ответ: {correct_answer[0]}',
                        'user_answer': user_answer,
                        'correct_answer': correct_answer[0]
                    }
                continue
            else:
                # Для других типов берем первый элемент
                correct_answer = correct_answer[0] if correct_answer else "UNKNOWN"

        # Преобразуем все типы к строке для сравнения
        if not isinstance(correct_answer, str):
            correct_answer = str(correct_answer)


        # Используем улучшенную нормализацию для всех типов упражнений
        def normalize_answer(answer):
            """Нормализует ответ для корректного сравнения"""
            if not answer:
                return ""
            
            import re
            
            # Убираем лишние пробелы
            normalized = answer.strip()
            normalized = re.sub(r'\s+', ' ', normalized)
            
            # Нормализуем пробелы вокруг знаков препинания
            normalized = re.sub(r'\s*,\s*', ', ', normalized)  # "are,are" -> "are, are"
            normalized = re.sub(r'\s*\.\s*', '. ', normalized)
            normalized = re.sub(r'\s*!\s*', '! ', normalized)
            normalized = re.sub(r'\s*\?\s*', '? ', normalized)
            
            # Убираем скобки и кавычки
            for char in ["'", '"', "[", "]"]:
                normalized = normalized.replace(char, "")
            
            return normalized.strip()

        # Нормализуем оба ответа
        user_normalized = normalize_answer(user_answer)
        correct_normalized = normalize_answer(correct_answer)

        # Сначала проверяем с нормализацией без учета регистра
        is_correct = user_normalized.lower() == correct_normalized.lower()

        # Специальная проверка для упражнений, где важен регистр первой буквы
        if not is_correct and exercise_type in ['fill-blank', 'fill_in_blank']:
            # Проверяем, если это начало предложения
            prompt_text = exercise.get('prompt', exercise.get('text', ''))
            if prompt_text.strip().startswith('___') or prompt_text.strip().startswith('_'):
                # Для начала предложения проверяем точное совпадение нормализованных версий
                is_correct = user_normalized == correct_normalized
        

        if is_correct:
            correct_count += 1
            feedback[str_i] = {
                'status': 'correct',
                'message': 'Правильно!',
                'user_answer': user_answer,
                'correct_answer': correct_answer
            }
        else:
            feedback[str_i] = {
                'status': 'incorrect',
                'message': f'Неправильно. Правильный ответ: {correct_answer}',
                'user_answer': user_answer,
                'correct_answer': correct_answer
            }

    # Вычисляем оценку
    score = round((correct_count / total_count) * 100) if total_count > 0 else 0

    return {
        'correct_exercises': correct_count,
        'total_exercises': total_count,
        'correct_answers': correct_count,  # Keep for backward compatibility
        'total_questions': total_count,  # Keep for backward compatibility
        'score': score,
        'feedback': feedback,
        'timestamp': datetime.now(UTC).isoformat()
    }


def process_quiz_submission(questions, answers):
    """
    Обрабатывает ответы на вопросы квиза для интерактивной версии

    Args:
        questions (list): Список вопросов квиза
        answers (dict): Словарь с ответами пользователя

    Returns:
        dict: Результаты проверки ответов
    """

    correct_count = 0
    total_count = len(questions)
    feedback = {}


    for i, question in enumerate(questions):

        # Support both integer and string keys (frontend may send '0', '1', etc.)
        user_answer = answers.get(str(i), answers.get(i, ''))
        question_type = question.get('type', 'multiple_choice')


        # Получаем правильный ответ используя hasOwnProperty equivalent
        correct_answer = None
        if 'answer' in question:
            correct_answer = question['answer']
        elif 'correct_answer' in question:
            correct_answer = question['correct_answer']
        elif 'correct' in question:
            correct_answer = question['correct']
        elif 'correct_index' in question:
            correct_answer = question['correct_index']


        # Проверяем правильность ответа в зависимости от типа вопроса
        is_correct = False

        # Special handling: fill_blank with options should be treated as multiple_choice
        if question_type == 'fill_blank' and 'options' in question:
            question_type = 'multiple_choice'

        if question_type in ['multiple_choice', 'dialogue_completion', 'listening_choice']:
            # Для множественного выбора сравниваем индексы или текст
            try:
                if isinstance(user_answer, str) and user_answer.isdigit():
                    user_idx = int(user_answer)
                elif isinstance(user_answer, int):
                    user_idx = user_answer
                else:
                    # user_answer is text, find its index in options
                    user_idx = -1
                    if 'options' in question and isinstance(user_answer, str):
                        options_stripped = [opt.strip() if isinstance(opt, str) else opt for opt in question['options']]
                        user_answer_stripped = user_answer.strip()

                        # Try exact match first
                        if user_answer_stripped in options_stripped:
                            user_idx = options_stripped.index(user_answer_stripped)
                        else:
                            # Try case-insensitive match
                            user_answer_lower = user_answer_stripped.lower()
                            for idx, option in enumerate(options_stripped):
                                option_lower = option.lower() if isinstance(option, str) else str(option).lower()
                                if option_lower == user_answer_lower:
                                    user_idx = idx
                                    break

                # Check if correct_answer is an index or the actual text
                if isinstance(correct_answer, str) and str(correct_answer).isdigit():
                    correct_idx = int(correct_answer)
                elif isinstance(correct_answer, int):
                    correct_idx = correct_answer
                else:
                    # correct_answer is the actual text, find its index in options
                    if 'options' in question:
                        # Try exact match first (with strip to remove spaces)
                        correct_answer_stripped = correct_answer.strip() if isinstance(correct_answer, str) else correct_answer
                        options_stripped = [opt.strip() if isinstance(opt, str) else opt for opt in question['options']]

                        if correct_answer_stripped in options_stripped:
                            correct_idx = options_stripped.index(correct_answer_stripped)
                        else:
                            # Try case-insensitive match
                            correct_answer_lower = correct_answer_stripped.lower() if isinstance(correct_answer_stripped, str) else str(correct_answer_stripped).lower()
                            for idx, option in enumerate(options_stripped):
                                option_lower = option.lower() if isinstance(option, str) else str(option).lower()
                                if option_lower == correct_answer_lower:
                                    correct_idx = idx
                                    break
                            else:
                                correct_idx = -1
                    else:
                        correct_idx = -1

                is_correct = user_idx == correct_idx

            except (ValueError, TypeError) as e:
                is_correct = False

        elif question_type == 'true_false':
            try:
                if isinstance(user_answer, str):
                    user_bool = user_answer.lower() == 'true'
                else:
                    user_bool = bool(user_answer)

                is_correct = user_bool == correct_answer

            except (ValueError, TypeError) as e:
                is_correct = False

        elif question_type in ['fill_in_blank', 'fill-in-blank', 'fill_blank', 'translation', 'transformation']:
            # Для текстовых вопросов проверяем с возможными правильными ответами

            if correct_answer is None:
                is_correct = True
            elif isinstance(correct_answer, list):
                # Если правильный ответ - массив вариантов

                def normalize_text(text):
                    """Нормализация текста для сравнения"""
                    if not text:
                        return ""
                    import re
                    # Приводим к нижнему регистру, убираем лишние пробелы и знаки препинания
                    normalized = re.sub(r'[^\w\s]', '', str(text).lower().strip())
                    normalized = re.sub(r'\s+', ' ', normalized)
                    return normalized

                user_normalized = normalize_text(user_answer)

                # Проверяем совпадение с любым из правильных ответов
                is_correct = False
                for correct_variant in correct_answer:
                    correct_normalized = normalize_text(correct_variant)

                    # Проверяем точное совпадение или содержание ключевых слов
                    if user_normalized == correct_normalized:
                        is_correct = True
                        break
                    elif len(correct_normalized.split()) <= 3:
                        # Для коротких ответов (1-3 слова) проверяем содержание
                        if correct_normalized in user_normalized:
                            is_correct = True
                            break
                    else:
                        # Для длинных ответов проверяем больше слов совпадений
                        correct_words = set(correct_normalized.split())
                        user_words = set(user_normalized.split())
                        common_words = correct_words.intersection(user_words)

                        # Если совпадает больше 60% ключевых слов
                        if len(common_words) >= len(correct_words) * 0.6:
                            is_correct = True
                            break

            else:
                # Если правильный ответ - строка

                # Специальная обработка для вопросов с альтернативными ответами
                alternative_answers = question.get('alternative_answers', [])
                acceptable_answers = question.get('acceptable_answers', [])
                all_possible_answers = [correct_answer] + alternative_answers + acceptable_answers


                def normalize_text(text):
                    """Нормализация текста для сравнения"""
                    if not text:
                        return ""
                    import re
                    normalized = re.sub(r'[^\w\s]', '', str(text).lower().strip())
                    normalized = re.sub(r'\s+', ' ', normalized)
                    return normalized

                user_normalized = normalize_text(user_answer)

                # Проверяем против всех возможных ответов
                is_correct = False
                for possible_answer in all_possible_answers:
                    correct_normalized = normalize_text(possible_answer)

                    # Проверяем точное совпадение или разумное содержание
                    if user_normalized == correct_normalized:
                        is_correct = True
                        break
                    elif len(correct_normalized.split()) <= 3:
                        # Для коротких ответов
                        if correct_normalized in user_normalized:
                            is_correct = True
                            break
                    else:
                        # Для длинных ответов проверяем пересечение слов
                        correct_words = set(correct_normalized.split())
                        user_words = set(user_normalized.split())
                        common_words = correct_words.intersection(user_words)
                        if len(common_words) >= len(correct_words) * 0.6:
                            is_correct = True
                            break


        elif question_type in ['reorder', 'ordering']:
            # For reorder/ordering questions, normalize and compare
            if correct_answer is None:
                is_correct = False
            else:
                def normalize_sentence(sentence):
                    """Normalize sentence for comparison"""
                    if not sentence:
                        return ""
                    import re
                    # Remove extra spaces
                    normalized = sentence.strip()
                    normalized = re.sub(r'\s+', ' ', normalized)
                    # Remove spaces before punctuation
                    normalized = re.sub(r'\s+([.,!?;:])', r'\1', normalized)
                    # Remove spaces after opening and before closing brackets
                    normalized = re.sub(r'(\()\s+', r'\1', normalized)
                    normalized = re.sub(r'\s+(\))', r'\1', normalized)
                    return normalized

                # Normalize both answers
                user_normalized = normalize_sentence(user_answer)
                correct_normalized = normalize_sentence(str(correct_answer))

                # First check exact match (case sensitive)
                is_correct = user_normalized == correct_normalized

                # If no match, check case insensitive
                if not is_correct:
                    is_correct = user_normalized.lower() == correct_normalized.lower()

        elif question_type == 'matching':
            # For matching questions, user_answer should be 'completed' if all pairs matched
            # We always consider matching as correct if user submitted it
            # (the frontend validates all pairs are matched before allowing submit)
            is_correct = user_answer == 'completed'

            # For display purposes, show the pairs if available
            if 'pairs' in question:
                correct_answer = question.get('pairs', [])

        else:
            # Если нет правильного ответа и неизвестный тип - засчитываем как правильный
            if correct_answer is None:
                is_correct = True
            else:
                is_correct = False


        # Формируем обратную связь
        if is_correct:
            correct_count += 1
            feedback[str(i)] = {
                'status': 'correct',
                'message': 'Правильно!',
                'user_answer': user_answer,
                'correct_answer': correct_answer
            }
        else:
            # Определяем текст правильного ответа для отображения
            if question_type == 'multiple_choice' and 'options' in question:
                # Получаем правильный текст ответа
                if isinstance(correct_answer, int) and 0 <= correct_answer < len(question['options']):
                    # correct_answer is an index
                    correct_text = question['options'][correct_answer]
                elif isinstance(correct_answer, str) and correct_answer.isdigit():
                    # correct_answer is a string index
                    idx = int(correct_answer)
                    if 0 <= idx < len(question['options']):
                        correct_text = question['options'][idx]
                    else:
                        correct_text = str(correct_answer)
                else:
                    # correct_answer is the actual text
                    correct_text = str(correct_answer)

                if isinstance(user_answer, str) and user_answer.isdigit():
                    user_idx = int(user_answer)
                    if 0 <= user_idx < len(question['options']):
                        user_text = question['options'][user_idx]
                    else:
                        user_text = user_answer
                else:
                    user_text = str(user_answer)

            elif question_type == 'true_false':
                correct_text = 'Правда' if correct_answer else 'Ложь'
                user_bool = str(user_answer).lower() == 'true' if isinstance(user_answer, str) else bool(user_answer)
                user_text = 'Правда' if user_bool else 'Ложь'

            elif question_type in ['fill_in_blank', 'fill-in-blank', 'translation']:
                # Для текстовых вопросов
                user_text = str(user_answer)

                if isinstance(correct_answer, list):
                    # Если несколько вариантов ответа
                    if len(correct_answer) == 1:
                        correct_text = correct_answer[0]
                    else:
                        correct_text = f"Возможные ответы: {', '.join(correct_answer)}"
                elif question_type == 'translation' and 'alternative_answers' in question:
                    # Для вопросов перевода с альтернативными ответами
                    all_answers = [str(correct_answer)]
                    if question['alternative_answers']:
                        all_answers.extend(question['alternative_answers'])
                    correct_text = ' / '.join(all_answers)
                else:
                    correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'

            elif question_type == 'reorder':
                # For reorder questions
                correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'
                user_text = str(user_answer)

            else:
                correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'
                user_text = str(user_answer)

            feedback[str(i)] = {
                'status': 'incorrect',
                'message': f'Неправильно. Правильный ответ: {correct_text}',
                'user_answer': user_text,
                'correct_answer': correct_text
            }

    # Вычисляем оценку
    score = round((correct_count / total_count) * 100) if total_count > 0 else 0


    return {
        'correct_answers': correct_count,
        'total_questions': total_count,
        'score': score,
        'feedback': feedback,
        'answers': answers,  # Сохраняем ответы пользователя
        'timestamp': datetime.now(UTC).isoformat()
    }


def process_matching_submission(pairs, user_matches):
    """
    Обрабатывает ответы на упражнение по сопоставлению

    Args:
        pairs (list): Список пар для сопоставления
        user_matches (dict): Словарь с ответами пользователя

    Returns:
        dict: Результаты проверки ответов
    """
    correct_count = 0
    total_count = len(pairs)
    feedback = {}
    incorrect_matches = {}

    # Проверяем ответы пользователя
    for i, pair in enumerate(pairs):
        left = pair['left']
        right = pair['right']

        # Support two formats:
        # 1. Index-based: {'0': 1, '1': 0} - user_matches[left_index] = right_index
        # 2. Value-based: {'hello': 'привет'} - user_matches[left_value] = right_value

        # Try index-based first (check by index)
        user_match_index = user_matches.get(str(i)) or user_matches.get(i)

        if user_match_index is not None:
            # Index-based format
            try:
                user_match_index = int(user_match_index)
                user_matched_right = pairs[user_match_index]['right'] if 0 <= user_match_index < len(pairs) else None
            except (ValueError, IndexError):
                user_matched_right = None
        else:
            # Try value-based format (check by left value)
            user_matched_right = user_matches.get(left)

        is_correct = user_matched_right == right

        if is_correct:
            correct_count += 1
            feedback[i] = {
                'status': 'correct',
                'message': 'Правильно!',
                'user_match': user_matched_right,
                'correct_match': right
            }
        else:
            feedback[i] = {
                'status': 'incorrect',
                'message': f'Неправильно. \"{left}\" должно соответствовать \"{right}\"',
                'user_match': user_matched_right,
                'correct_match': right
            }
            # Добавляем в список неправильных
            incorrect_matches[str(i)] = {
                'user': user_matched_right,
                'correct': right
            }

    # Вычисляем оценку
    score = round((correct_count / total_count) * 100) if total_count > 0 else 0

    return {
        'correct_matches': correct_count,
        'total_pairs': total_count,
        'correct_pairs': correct_count,  # Alias
        'correct_answers': correct_count,  # Keep for backward compatibility
        'total_questions': total_count,  # Keep for backward compatibility
        'score': score,
        'feedback': feedback,
        'incorrect_matches': incorrect_matches,
        'timestamp': datetime.now(UTC).isoformat()
    }


def process_final_test_submission(questions, user_answers):
    """
    Обрабатывает отправку контрольной точки и возвращает результаты

    Args:
        questions: список вопросов с правильными ответами
        user_answers: словарь ответов пользователя {question_index: answer}

    Returns:
        dict: результат с оценкой и обратной связью
    """
    # Support payloads with either 'questions' or 'exercises'
    # (For compatibility with changes in routes.py)
    correct_count = 0
    total_count = len(questions)
    feedback = {}


    for i, question in enumerate(questions):
        # Получаем ответ пользователя - поддержка обоих форматов (string and int keys)
        user_answer = user_answers.get(str(i), user_answers.get(i))

        # Получаем правильный ответ из вопроса
        correct_answer = question.get('answer')
        if correct_answer is None:
            correct_answer = question.get('correct_answer')
        if correct_answer is None:
            correct_answer = question.get('correct_index')
        if correct_answer is None:
            correct_answer = question.get('correct')  # Also check 'correct' field


        is_correct = False

        qtype = question.get('type', '')
        if qtype == 'multiple_choice':
            # Для multiple choice сравниваем индексы
            if user_answer is not None:
                try:
                    user_idx = int(user_answer)
                    is_correct = user_idx == correct_answer
                except (ValueError, TypeError):
                    is_correct = False

        elif qtype == 'true_false':
            # Для true/false сравниваем булевые значения
            if user_answer in ['true', 'false']:
                user_bool = user_answer == 'true'
                is_correct = user_bool == correct_answer

        elif qtype in ['fill_in_blank', 'translation']:
            # Для текстовых ответов нормализуем и сравниваем
            if user_answer:
                user_normalized = normalize_text(user_answer)

                # Проверяем множественные варианты ответов
                if isinstance(correct_answer, list):
                    for ans in correct_answer:
                        ans_normalized = normalize_text(ans)
                        if user_normalized == ans_normalized:
                            is_correct = True
                            break
                else:
                    correct_normalized = normalize_text(correct_answer)
                    is_correct = user_normalized == correct_normalized

        elif qtype == 'matching':
            # Для matching проверяем все пары
            if isinstance(user_answer, dict):
                correct_pairs = {pair['left']: pair['right'] for pair in question.get('pairs', [])}
                matches_correct = all(
                    user_answer.get(left) == right
                    for left, right in correct_pairs.items()
                )
                # Проверяем что все пары были сопоставлены
                all_answered = len(user_answer) == len(correct_pairs)
                is_correct = matches_correct and all_answered

        elif qtype == 'reorder':
            # Для reorder сравниваем составленное предложение
            if user_answer:
                user_normalized = normalize_text(user_answer)
                correct_normalized = normalize_text(correct_answer)
                is_correct = user_normalized == correct_normalized

        if is_correct:
            correct_count += 1

        # Сохраняем обратную связь
        feedback[str(i)] = {
            'is_correct': is_correct,
            'user_answer': user_answer,
            'correct_answer': correct_answer
        }

    # Вычисляем процент
    score = round((correct_count / total_count) * 100) if total_count > 0 else 0
    passed = score >= 70  # 70% is passing score


    return {
        'score': round(score, 1),
        'correct_answers': correct_count,
        'total_questions': total_count,
        'passed': passed,
        'feedback': feedback
    }


def normalize_text(text):
    """Нормализует текст для сравнения ответов"""
    if not text:
        return ""
    # Удаляем знаки препинания и лишние пробелы, приводим к нижнему регистру
    import re
    text = text.lower().strip()
    # Удаляем знаки препинания
    text = re.sub(r'[^\w\s]', '', text)
    # Заменяем множественные пробелы на один
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def get_lesson_statistics():
    """
    Получает статистику по всем урокам

    Returns:
        dict: Статистические данные по урокам
    """
    # Получаем общее количество уроков
    total_lessons = Lessons.query.count()

    # Получаем количество уроков по типам
    lesson_types = db.session.query(
        Lessons.type,
        func.count(Lessons.id)
    ).group_by(Lessons.type).all()

    # Получаем количество завершенных уроков
    completed_lessons = db.session.query(
        func.count(LessonProgress.id)
    ).filter(
        LessonProgress.status == 'completed'
    ).scalar()

    # Получаем средний балл по всем завершенным урокам
    avg_score = db.session.query(
        func.avg(LessonProgress.score)
    ).filter(
        LessonProgress.status == 'completed'
    ).scalar()

    # Получаем количество уроков по модулям
    lessons_by_module = db.session.query(
        Lessons.module_id,
        func.count(Lessons.id)
    ).group_by(Lessons.module_id).all()

    return {
        'total_lessons': total_lessons,
        'by_type': dict(lesson_types),  # Consistent naming
        'by_module': dict(lessons_by_module),  # Add missing field
        'lesson_types': dict(lesson_types),  # Keep for backward compatibility
        'completed_lessons': completed_lessons or 0,
        'avg_score': float(avg_score) if avg_score else 0
    }


def calculate_user_curriculum_progress(user_id):
    """
    Рассчитывает общий прогресс пользователя по учебному плану

    Args:
        user_id (int): ID пользователя

    Returns:
        dict: Данные о прогрессе пользователя
    """
    # Получаем общее количество уроков
    total_lessons = Lessons.query.count()

    # Получаем количество завершенных уроков пользователя
    completed_lessons = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed'
    ).count()

    # Вычисляем процент прогресса
    progress_percent = (completed_lessons / total_lessons) * 100 if total_lessons > 0 else 0

    # Получаем средний балл пользователя
    avg_score = db.session.query(
        func.avg(LessonProgress.score)
    ).filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed'
    ).scalar()

    # Получаем последний завершенный урок
    last_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed'
    ).order_by(
        LessonProgress.completed_at.desc()
    ).first()

    if last_completed:
        last_lesson = Lessons.query.get(last_completed.lesson_id)
        last_module = Module.query.get(last_lesson.module_id)
        last_level = last_module.level
    else:
        last_lesson = None
        last_module = None
        last_level = None

    return {
        'user_id': user_id,
        'total_lessons': total_lessons,
        'completed_lessons': completed_lessons,
        'progress_percent': progress_percent,
        'avg_score': float(avg_score) if avg_score else 0,
        'last_completed_lesson': last_lesson,
        'last_completed_module': last_module,
        'last_completed_level': last_level,
        'last_completed_at': last_completed.completed_at if last_completed else None
    }


def get_cards_for_lesson(lesson_id, user_id):
    """
    Получает карточки для урока типа 'card' из общего пула слов пользователя
    """
    from app.study.models import StudySettings

    lesson = Lessons.query.get_or_404(lesson_id)

    # Получаем или создаем прогресс урока
    progress = LessonProgress.query.filter_by(
        user_id=user_id,
        lesson_id=lesson_id
    ).first()

    if not progress:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status='in_progress',
            data={
                'studied_cards': {},  # {card_direction_id: {status, rating, timestamp, was_new}}
                'cards_studied': 0,
                'correct_answers': 0,
                'total_answers': 0,
                'card_progress': {}
            },
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC)
        )
        db.session.add(progress)
        db.session.commit()

    # Убедимся, что data содержит нужные поля
    if not progress.data:
        progress.data = {}
    if 'studied_cards' not in progress.data:
        progress.data['studied_cards'] = {}

    # Получаем данные об изученных карточках
    studied_cards = progress.data.get('studied_cards', {})  # {card_direction_id: {status, rating, timestamp}}
    shown_card_ids = list(studied_cards.keys())  # ID карточек которые уже показывались

    # Подсчитываем статистику на основе изученных карточек
    # Считаем только успешно пройденные карточки для лимитов
    new_cards_shown = 0
    review_cards_shown = 0

    for card_id, card_info in studied_cards.items():
        # Считаем все карточки (и passed и failed) для исключения из выдачи
        # Но для лимитов считаем только успешно пройденные
        if card_info.get('status') == 'passed':
            if card_info.get('was_new', True):
                new_cards_shown += 1
            else:
                review_cards_shown += 1


    # Определяем лимиты для урока
    lesson_number = lesson.number
    if lesson_number in [3, 5]:
        max_new_cards = 10
        max_review_cards = 20
    else:
        # Для других уроков используем стандартные настройки
        user_settings = StudySettings.get_settings(user_id)
        max_new_cards = user_settings.new_words_per_day
        max_review_cards = user_settings.reviews_per_day

    cards = []

    # 1. Получаем карточки для повторения (не больше лимита и не показанные ранее)
    remaining_reviews = max_review_cards - review_cards_shown
    if remaining_reviews > 0:
        due_directions = UserCardDirection.query.join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed.isnot(None),
            cast(UserCardDirection.next_review, Date) <= func.current_date(),
            ~UserCardDirection.id.in_([int(id) for id in shown_card_ids]) if shown_card_ids else True
        ).order_by(
            UserCardDirection.next_review.asc()
        ).limit(remaining_reviews).all()

        for direction in due_directions:
            user_word = UserWord.query.get(direction.user_word_id)
            word = CollectionWords.query.get(user_word.word_id)

            if word and word.russian_word:
                intervals = calculate_card_intervals(direction)

                card_data = {
                    'word_id': word.id,
                    'direction_id': direction.id,
                    'direction': direction.direction,
                    'front': word.english_word if direction.direction == 'eng-rus' else word.russian_word,
                    'back': word.russian_word if direction.direction == 'eng-rus' else word.english_word,
                    'examples': word.sentences,
                    'audio': f'{word.listening[7:-1]}' if word.get_download == 1 and word.listening else None,
                    'is_new': False,
                    'interval': direction.interval,
                    'ease_factor': direction.ease_factor,
                    'repetitions': direction.repetitions,
                    'session_attempts': direction.session_attempts,
                    'calculated_intervals': intervals
                }
                cards.append(card_data)

    # 2. Добавляем новые карточки (не больше лимита и не показанные ранее)
    remaining_new = max_new_cards - new_cards_shown
    if remaining_new > 0:
        new_directions = UserCardDirection.query.join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed.is_(None),
            UserCardDirection.repetitions == 0,
            ~UserCardDirection.id.in_([int(id) for id in shown_card_ids]) if shown_card_ids else True
        ).order_by(
            UserCardDirection.id.asc()
        ).limit(remaining_new).all()

        for direction in new_directions:
            user_word = UserWord.query.get(direction.user_word_id)
            word = CollectionWords.query.get(user_word.word_id)
            if word and word.russian_word:
                card_data = {
                    'word_id': word.id,
                    'direction_id': direction.id,
                    'direction': direction.direction,
                    'front': word.english_word if direction.direction == 'eng-rus' else word.russian_word,
                    'back': word.russian_word if direction.direction == 'eng-rus' else word.english_word,
                    'examples': word.sentences,
                    'audio': f'{word.listening[7:-1]}' if word.get_download == 1 and word.listening else None,
                    'is_new': True,
                    'interval': 0,
                    'ease_factor': 2.5,
                    'repetitions': 0
                }
                cards.append(card_data)

    # Перемешиваем карточки
    cards = smart_shuffle_cards(cards)

    # Подсчитываем текущие показатели
    new_cards_count = sum(1 for c in cards if c['is_new'])
    review_cards_count = sum(1 for c in cards if not c['is_new'])

    # Подсчитываем общее количество доступных карточек
    total_due = new_cards_count + review_cards_count


    return {
        'cards': cards,
        'total_due': total_due,
        'srs_settings': {
            'new_cards_per_day': max_new_cards,
            'reviews_per_day': max_review_cards,
            'show_hint_time': 7
        },
        'lesson_settings': {
            'min_cards_required': 1,  # Минимум 1 карточка для завершения
            'min_accuracy_required': 0  # Не требуем минимальной точности
        },
        'stats': {
            'new_cards_count': new_cards_count,
            'review_cards_count': review_cards_count,
            'new_cards_shown': new_cards_shown,
            'review_cards_shown': review_cards_shown,
            'new_cards_limit': max_new_cards,
            'reviews_limit': max_review_cards,
            'new_cards_remaining': max_new_cards - new_cards_shown,
            'reviews_remaining': max_review_cards - review_cards_shown,
            'total_due': total_due
        }
    }


def smart_shuffle_cards(cards):
    """
    Умное перемешивание карточек, чтобы не было подряд карточек одного слова

    Args:
        cards: список карточек

    Returns:
        list: перемешанный список карточек
    """
    import random

    if len(cards) <= 1:
        return cards

    # Группируем карточки по word_id (fallback to 'id' for test compatibility)
    word_groups = {}
    for card in cards:
        word_id = card.get('word_id', card.get('id'))
        if word_id is None:
            # If no identifying field, treat each card as unique
            word_id = id(card)
        if word_id not in word_groups:
            word_groups[word_id] = []
        word_groups[word_id].append(card)

    # Если у нас только одно слово, просто перемешиваем
    if len(word_groups) == 1:
        random.shuffle(cards)
        return cards

    # Создаем новый список, чередуя слова
    result = []
    word_ids = list(word_groups.keys())
    random.shuffle(word_ids)

    # Распределяем карточки так, чтобы карточки одного слова не шли подряд
    while any(word_groups.values()):
        for word_id in word_ids:
            if word_groups[word_id]:
                card = word_groups[word_id].pop(0)
                result.append(card)

    return result


def process_card_review_for_lesson(lesson_id, user_id, word_id, direction, rating, session_data=None):
    """
    Обрабатывает оценку карточки в контексте урока

    Args:
        lesson_id: ID урока
        user_id: ID пользователя
        word_id: ID слова
        direction: Направление карточки ('eng-rus' или 'rus-eng')
        rating: Оценка (0-5)
        session_data: Дополнительные данные сессии (не используется больше для failed_attempts)

    Returns:
        dict: Результат обработки
    """
    # Получаем или создаем UserWord
    user_word = UserWord.get_or_create(user_id, word_id)

    # Получаем или создаем направление
    card_direction = UserCardDirection.query.filter_by(
        user_word_id=user_word.id,
        direction=direction
    ).first()

    if not card_direction:
        card_direction = UserCardDirection(
            user_word_id=user_word.id,
            direction=direction
        )
        db.session.add(card_direction)

    # Сначала получаем или создаем прогресс урока (нужно для обеих веток)
    progress = LessonProgress.query.filter_by(
        user_id=user_id,
        lesson_id=lesson_id
    ).first()

    if not progress:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status='in_progress',
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC),
            data={
                'cards_studied': 0,
                'correct_answers': 0,
                'total_answers': 0,
                'card_progress': {},
                'shown_card_ids': [],
                'new_cards_shown': 0,
                'review_cards_shown': 0
            }
        )
        db.session.add(progress)
        db.session.flush()  # Чтобы получить ID сразу
    else:
        # Убеждаемся, что data инициализирована правильно
        if not progress.data:
            progress.data = {}

        # Проверяем наличие всех необходимых полей и инициализируем отсутствующие
        required_fields = {
            'cards_studied': 0,
            'correct_answers': 0,
            'total_answers': 0,
            'studied_cards': {},  # {card_direction_id: {status, rating, timestamp, was_new}}
            'session_stats': {
                'start_time': None,
                'cards_attempted': 0,
                'accuracy': 100
            }
        }

        for field, default_value in required_fields.items():
            if field not in progress.data:
                progress.data[field] = default_value

        # ВАЖНО: убедимся, что поле обновляется в БД
        db.session.merge(progress)

    # При оценке 0 ("Не помню") - записываем информацию о карточке
    if rating == 0:
        # Записываем информацию о показанной карточке
        card_id_str = str(card_direction.id)
        if card_id_str not in progress.data['studied_cards']:
            was_new_card = card_direction.repetitions == 0
            progress.data['studied_cards'][card_id_str] = {
                'status': 'failed',
                'rating': rating,
                'timestamp': datetime.now(UTC).isoformat(),
                'was_new': was_new_card,
                'attempts': 1
            }
        else:
            # Увеличиваем количество попыток
            progress.data['studied_cards'][card_id_str]['attempts'] += 1
            progress.data['studied_cards'][card_id_str]['last_attempt'] = datetime.now(UTC).isoformat()

        # Увеличиваем счетчик попыток в текущей сессии
        card_direction.session_attempts += 1

        # Увеличиваем общий счетчик неправильных ответов
        card_direction.incorrect_count += 1

        # Обновляем время последней попытки
        card_direction.last_reviewed = datetime.now(UTC)

        # НЕ обновляем interval и next_review - карточка остается "просроченной"

        # Обновляем статистику урока
        progress.data['total_answers'] = progress.data.get('total_answers', 0) + 1

        # Обновляем прогресс карточки
        card_key = f"{word_id}-{direction}"
        if 'card_progress' not in progress.data:
            progress.data['card_progress'] = {}
        if card_key not in progress.data['card_progress']:
            progress.data['card_progress'][card_key] = {'correct': 0, 'incorrect': 0}
        progress.data['card_progress'][card_key]['incorrect'] += 1

        progress.last_activity = datetime.now(UTC)

        # Помечаем объект как измененный для SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(progress, 'data')

        db.session.commit()


        # Рассчитываем интервалы с учетом неудачных попыток
        next_intervals = calculate_card_intervals(card_direction)

        # Возвращаем результат без обновления интервалов
        return {
            'success': True,
            'interval': card_direction.interval,
            'next_review': card_direction.next_review.isoformat() if card_direction.next_review else None,
            'achievements': [],
            'daily_limit_reached': False,
            'failed_attempt': True,
            'session_attempts': card_direction.session_attempts,
            'calculated_intervals': next_intervals  # Добавляем рассчитанные интервалы
        }

    # Для оценок > 0 обрабатываем с учетом накопленных неудач
    effective_rating = rating

    # Корректируем оценку на основе количества неудачных попыток в этой сессии
    if card_direction.session_attempts > 0:
        # Если было 1-2 неудачи - снижаем оценку на количество неудач
        if card_direction.session_attempts <= 2:
            effective_rating = max(1, rating - card_direction.session_attempts)
        # Если было 3+ неудач - максимальная эффективная оценка = 2 ("сложно")
        else:
            effective_rating = min(2, rating)

    # Проверяем была ли это новая карточка до обработки рейтинга
    was_new_card = card_direction.repetitions == 0

    # Записываем информацию о успешно изученной карточке
    card_id_str = str(card_direction.id)
    if card_id_str not in progress.data['studied_cards']:
        progress.data['studied_cards'][card_id_str] = {
            'status': 'passed',
            'rating': rating,
            'effective_rating': effective_rating,
            'timestamp': datetime.now(UTC).isoformat(),
            'was_new': was_new_card,
            'attempts': card_direction.session_attempts + 1  # +1 for current successful attempt
        }
    else:
        # Обновляем существующую запись
        progress.data['studied_cards'][card_id_str].update({
            'status': 'passed',
            'rating': rating,
            'effective_rating': effective_rating,
            'last_success': datetime.now(UTC).isoformat(),
            'attempts': progress.data['studied_cards'][card_id_str].get('attempts', 0) + 1
        })

    # ВАЖНО: старую логику shown_card_ids больше не используем, так как теперь используем studied_cards

    # Обновляем SRS параметры с учетом эффективной оценки
    interval = card_direction.update_after_review(effective_rating)


    # Сбрасываем счетчик попыток текущей сессии после успешного ответа
    card_direction.session_attempts = 0

    # Если это первое успешное изучение карточки
    if card_direction.repetitions == 1 and rating >= 3:
        # Определяем противоположное направление
        if direction == 'eng-rus':
            opposite_direction = 'rus-eng'
        else:
            opposite_direction = 'eng-rus'

        # Проверяем, существует ли уже противоположное направление
        opposite_card = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction=opposite_direction
        ).first()

        if not opposite_card:
            # Создаем противоположное направление
            opposite_card = UserCardDirection(
                user_word_id=user_word.id,
                direction=opposite_direction
            )
            db.session.add(opposite_card)

    # Обновляем статистику урока
    progress.data['total_answers'] = progress.data.get('total_answers', 0) + 1

    # Увеличиваем счетчик изученных карточек только при первом успешном ответе
    card_key = f"{word_id}-{direction}"

    # Убеждаемся, что card_progress существует
    if 'card_progress' not in progress.data:
        progress.data['card_progress'] = {}

    if card_key not in progress.data['card_progress']:
        progress.data['cards_studied'] = progress.data.get('cards_studied', 0) + 1
        progress.data['card_progress'][card_key] = {'correct': 0, 'incorrect': 0}

    # Обновляем статистику правильных/неправильных ответов
    if rating >= 3:
        progress.data['correct_answers'] = progress.data.get('correct_answers', 0) + 1
        progress.data['card_progress'][card_key]['correct'] += 1
    else:
        progress.data['card_progress'][card_key]['incorrect'] += 1

    progress.last_activity = datetime.now(UTC)

    # Проверяем, завершен ли урок (для уроков 3 и 5)
    lesson = Lessons.query.get(lesson_id)
    if lesson.number in [3, 5]:
        # Проверяем, есть ли еще доступные карточки
        cards_data = get_cards_for_lesson(lesson_id, user_id)
        if not cards_data['cards']:  # Нет больше карточек для показа
            progress.status = 'completed'
            progress.completed_at = datetime.now(UTC)

    # Помечаем объект как измененный для SQLAlchemy
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(progress, 'data')

    # Коммитим все изменения
    db.session.commit()

    # Подсчитываем статистику на основе studied_cards
    studied_cards = progress.data.get('studied_cards', {})
    total_studied = len([c for c in studied_cards.values() if c.get('status') == 'passed'])
    new_cards_studied = len(
        [c for c in studied_cards.values() if c.get('status') == 'passed' and c.get('was_new', True)])
    review_cards_studied = len(
        [c for c in studied_cards.values() if c.get('status') == 'passed' and not c.get('was_new', True)])

    # Проверяем достижения (если нужно)
    achievements = []

    # Проверяем дневные лимиты
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(
            db.session.query(UserWord.id).filter_by(user_id=user_id)
        ),
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.repetitions == 1
    ).scalar() or 0

    from app.study.models import StudySettings
    user_settings = StudySettings.get_settings(user_id)

    # Для уроков 3 и 5 используем их лимиты
    if lesson.number in [3, 5]:
        daily_limit = 10  # лимит новых карточек для уроков 3 и 5
        # Подсчитываем изученные новые карточки в этой сессии урока
        studied_cards = progress.data.get('studied_cards', {})
        lesson_new_cards_studied = len(
            [c for c in studied_cards.values() if c.get('status') == 'passed' and c.get('was_new', True)])
        daily_limit_reached = lesson_new_cards_studied >= daily_limit
    else:
        daily_limit = user_settings.new_words_per_day
        daily_limit_reached = new_cards_today >= daily_limit

    # Рассчитываем интервалы для следующего показа (после обновления)
    next_intervals = calculate_card_intervals(card_direction)

    return {
        'success': True,
        'interval': interval,
        'next_review': card_direction.next_review.isoformat() if card_direction.next_review else None,
        'achievements': achievements,
        'daily_limit_reached': daily_limit_reached,
        'calculated_intervals': next_intervals,
        'daily_stats': {
            'new_cards_today': new_cards_today,
            'new_cards_limit': daily_limit,
            'lesson_new_cards_studied': new_cards_studied,
            'lesson_review_cards_studied': review_cards_studied
        }
    }


# Комбинированный сервис: возвращает список карточек и при отсутствии due-карточек — время следующего ревью.
def get_card_session_for_lesson(lesson_id, user_id):
    """
    Комбинированный сервис: возвращает список карточек и при отсутствии due-карточек — время следующего ревью.
    """
    # Получаем due-карточки и статистику
    session_data = get_cards_for_lesson(lesson_id, user_id)
    cards = session_data.get('cards', [])
    # Если есть карточки для изучения сегодня, next_review_time не нужен
    if cards:
        session_data['next_review_time'] = None
        return session_data

    # Иначе ищем ближайший следующий review
    from datetime import datetime
    next_dir = (
        UserCardDirection.query.join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        )
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.next_review > datetime.now(UTC)
        )
        .order_by(UserCardDirection.next_review)
        .first()
    )

    # Формируем текстовое представление времени до следующего review
    if not next_dir:
        session_data['next_review_time'] = "Нет запланированных повторений"
    else:
        delta = next_dir.next_review - datetime.now(UTC)
        if delta.days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                minutes = delta.seconds // 60
                session_data['next_review_time'] = f"{minutes} минут"
            else:
                session_data['next_review_time'] = f"{hours} часов"
        elif delta.days == 1:
            session_data['next_review_time'] = "завтра"
        elif delta.days < 7:
            session_data['next_review_time'] = f"{delta.days} дней"
        elif delta.days < 30:
            weeks = delta.days // 7
            session_data['next_review_time'] = f"{weeks} недель"
        else:
            months = delta.days // 30
            session_data['next_review_time'] = f"{months} месяцев"

    return session_data


def calculate_card_intervals(card_direction):
    """
    Рассчитывает интервалы для карточки с учетом текущего состояния и неудачных попыток

    Args:
        card_direction: объект UserCardDirection

    Returns:
        dict: словарь с интервалами для каждой оценки
    """
    ease_factor = card_direction.ease_factor
    current_interval = card_direction.interval
    session_attempts = card_direction.session_attempts

    # Базовые интервалы
    if card_direction.repetitions == 0 or current_interval == 0:
        # Для новых карточек
        base_intervals = {
            'again': 0,  # Повтор сейчас
            'hard': 1,
            'good': 3,
            'easy': 7
        }
    else:
        # Для повторяющихся карточек
        base_intervals = {
            'again': 0,  # Всегда повтор сейчас
            'hard': max(1, round(current_interval * 0.8)),
            'good': max(1, round(current_interval * ease_factor)),
            'easy': max(1, round(current_interval * ease_factor * 1.3))
        }

    # Корректируем интервалы с учетом неудачных попыток
    adjusted_intervals = {}

    # again (0) - всегда повтор сейчас
    adjusted_intervals['again'] = 0

    # Для остальных оценок учитываем неудачные попытки
    for rating_name, rating_value in [('hard', 2), ('good', 4), ('easy', 5)]:
        # Рассчитываем эффективную оценку
        if session_attempts > 0:
            if session_attempts <= 2:
                effective_rating = max(1, rating_value - session_attempts)
            else:
                effective_rating = min(2, rating_value)
        else:
            effective_rating = rating_value

        # Применяем логику из update_after_review
        if card_direction.repetitions == 0:
            # Первое изучение
            if effective_rating >= 3:
                if effective_rating == 3:
                    interval = 1
                elif effective_rating == 4:
                    interval = 3
                else:  # 5
                    interval = 7
            else:
                interval = 1
        else:
            # Повторения
            if effective_rating < 3:
                interval = 1
            else:
                # Используем базовый интервал для данной оценки
                base = base_intervals[rating_name]

                if effective_rating == 3:
                    interval = max(1, round(base * 0.8))
                elif effective_rating == 4:
                    interval = base
                else:  # 5
                    interval = max(1, round(base * 1.3))

        adjusted_intervals[rating_name] = interval

    return adjusted_intervals


def sync_lesson_cards_to_words(lesson):
    """
    Синхронизирует карточки из JSON урока с таблицей collection_words.
    Если слово уже существует - обновляет, если нет - создает.
    Обновляет JSON урока, добавляя word_id к каждой карточке.

    Args:
        lesson: Объект урока (Lessons)

    Returns:
        tuple: (success: bool, message: str, updated_count: int, created_count: int)
    """
    import json
    import logging

    logger = logging.getLogger(__name__)

    if not lesson.content:
        logger.warning(f"Lesson {lesson.id} has no content")
        return False, "Урок не имеет контента", 0, 0

    try:
        # Parse content
        content = json.loads(lesson.content) if isinstance(lesson.content, str) else lesson.content

        if not isinstance(content, dict) or 'cards' not in content:
            return False, "Контент не содержит поле 'cards'", 0, 0

        cards = content['cards']
        if not isinstance(cards, list):
            return False, "Поле 'cards' должно быть списком", 0, 0

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Process each card
        for idx, card in enumerate(cards):
            if not isinstance(card, dict):
                continue

            # Skip if already has word_id
            if 'word_id' in card and card['word_id']:
                skipped_count += 1
                continue

            english = card.get('back', '').strip()
            russian = card.get('front', '').strip()

            if not english:
                logger.warning(f"Card {idx} (id={card.get('id')}) missing 'back' field (English)")
                continue

            # Check if word exists
            word = CollectionWords.query.filter_by(english_word=english).first()

            if word:
                # Update existing word
                if russian and not word.russian_word:
                    word.russian_word = russian
                if card.get('audio') and not word.listening:
                    word.listening = card.get('audio')

                # Update sentences if we have examples
                if card.get('example') and card.get('example_translation'):
                    try:
                        sentences_data = json.loads(word.sentences) if word.sentences else []
                    except:
                        sentences_data = []

                    # Add example if not already present
                    new_example = {
                        'en': card.get('example'),
                        'ru': card.get('example_translation')
                    }
                    if new_example not in sentences_data:
                        sentences_data.append(new_example)
                        word.sentences = json.dumps(sentences_data, ensure_ascii=False)

                updated_count += 1
                logger.info(f"Updated word: {english} (ID: {word.id})")
            else:
                # Create new word
                sentences_data = []
                if card.get('example') and card.get('example_translation'):
                    sentences_data.append({
                        'en': card.get('example'),
                        'ru': card.get('example_translation')
                    })

                word = CollectionWords(
                    english_word=english,
                    russian_word=russian,
                    listening=card.get('audio', ''),
                    sentences=json.dumps(sentences_data, ensure_ascii=False) if sentences_data else None,
                    level='A0',  # Default level
                    get_download=1 if card.get('audio') else 0
                )
                db.session.add(word)
                db.session.flush()  # Get ID without committing
                created_count += 1
                logger.info(f"Created word: {english} (ID: {word.id})")

            # Add word_id to card
            card['word_id'] = word.id

        # Update lesson content with word_ids
        # IMPORTANT: Mark column as modified for SQLAlchemy to detect changes in JSONB
        from sqlalchemy.orm.attributes import flag_modified
        lesson.content = content
        flag_modified(lesson, 'content')
        db.session.commit()

        message = f"Создано: {created_count}, Обновлено: {updated_count}, Пропущено: {skipped_count}"
        logger.info(f"Sync completed for lesson {lesson.id}: {message}")

        return True, message, updated_count, created_count

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error syncing lesson cards: {str(e)}")
        return False, f"Ошибка: {str(e)}", 0, 0
