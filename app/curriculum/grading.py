# app/curriculum/grading.py
"""Submission processing / grading functions for curriculum exercises."""

import json
import logging
import re
from datetime import datetime, UTC

from app.utils.normalization import normalize_text

logger = logging.getLogger(__name__)


def _normalize_answer(s):
    """Normalize answer for strict comparison: strip, lower, strip punctuation, collapse spaces."""
    if s is None:
        return ""
    return normalize_text(str(s))


def _levenshtein(a, b):
    """Compute Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _strict_text_match(user_answer, candidates):
    """
    Strict grading for fill-in-blank / translation answers.

    Exact match after normalization. For single-word candidates, allow
    Levenshtein distance ≤1 (typo tolerance). Multi-word answers require
    exact match — overlap heuristics are intentionally not used.
    """
    user_normalized = _normalize_answer(user_answer)
    if not user_normalized:
        return False
    for candidate in candidates:
        if candidate is None:
            continue
        correct_normalized = _normalize_answer(candidate)
        if not correct_normalized:
            continue
        if user_normalized == correct_normalized:
            return True
        if ' ' not in correct_normalized and ' ' not in user_normalized:
            if _levenshtein(user_normalized, correct_normalized) <= 1:
                return True
    return False


def _grade_matching_pairs(user_pairs, correct_pairs):
    """
    Server-side validation of matching pairs.

    Both inputs are lists of {"left": X, "right": Y} dicts. Returns True iff
    every correct pair has a corresponding user pair (order-independent),
    and the user submitted no extras.
    """
    if not isinstance(user_pairs, list) or not isinstance(correct_pairs, list):
        return False
    if len(user_pairs) != len(correct_pairs):
        return False

    def _key(p):
        if not isinstance(p, dict):
            return None
        return (_normalize_answer(p.get('left')), _normalize_answer(p.get('right')))

    user_keys = sorted(_key(p) for p in user_pairs)
    correct_keys = sorted(_key(p) for p in correct_pairs)
    if any(k is None or k == ("", "") for k in user_keys):
        return False
    return user_keys == correct_keys


def process_grammar_submission(exercises, answers):
    """
    Обрабатывает ответы на грамматические упражнения

    Args:
        exercises (list): Список грамматических упражнений
        answers (dict): Словарь с ответами пользователя

    Returns:
        dict: Результаты проверки ответов
    """
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

        if question_type in ['multiple_choice', 'dialogue_completion', 'listening_choice', 'reading_comprehension']:
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
            # Strict grading: exact match after normalization, with single-word
            # Levenshtein ≤1 typo tolerance. Multi-word overlap heuristics removed —
            # they previously credited substantively wrong answers.

            if correct_answer is None:
                is_correct = True
            else:
                if isinstance(correct_answer, list):
                    candidates = list(correct_answer)
                else:
                    candidates = [correct_answer]
                    candidates.extend(question.get('alternative_answers', []) or [])
                    candidates.extend(question.get('acceptable_answers', []) or [])

                is_correct = _strict_text_match(user_answer, candidates)


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
            # Server-side validation: client must submit explicit pairs.
            # Legacy clients sending 'completed' (no pairs) are rejected — they
            # cannot prove they actually solved the matching.
            correct_pairs = question.get('pairs', []) or []
            if 'pairs' in question:
                correct_answer = correct_pairs

            user_pairs = None
            if isinstance(user_answer, list):
                user_pairs = user_answer
            elif isinstance(user_answer, dict) and isinstance(user_answer.get('pairs'), list):
                user_pairs = user_answer['pairs']
            else:
                pairs_field = answers.get(f'{i}_pairs', answers.get(f'{str(i)}_pairs'))
                if isinstance(pairs_field, list):
                    user_pairs = pairs_field

            if user_pairs is None:
                is_correct = False
            else:
                is_correct = _grade_matching_pairs(user_pairs, correct_pairs)

        else:
            # Если нет правильного ответа и неизвестный тип - засчитываем как правильный
            if correct_answer is None:
                is_correct = True
            else:
                is_correct = False


        # Конвертируем индексы в текст для отображения (общая логика для correct/incorrect)
        display_user = user_answer
        display_correct = correct_answer
        if question_type in ('multiple_choice', 'dialogue_completion', 'listening_choice') and 'options' in question:
            opts = question['options']
            # correct_answer -> text
            if isinstance(correct_answer, int) and 0 <= correct_answer < len(opts):
                display_correct = opts[correct_answer]
            elif isinstance(correct_answer, str) and correct_answer.isdigit():
                idx = int(correct_answer)
                if 0 <= idx < len(opts):
                    display_correct = opts[idx]
                elif 1 <= idx <= len(opts):
                    display_correct = opts[idx - 1]
            # user_answer -> text
            if isinstance(user_answer, str) and user_answer.isdigit():
                uidx = int(user_answer)
                if 0 <= uidx < len(opts):
                    display_user = opts[uidx]
                elif 1 <= uidx <= len(opts):
                    display_user = opts[uidx - 1]

        # Формируем обратную связь
        if is_correct:
            correct_count += 1
            feedback[str(i)] = {
                'status': 'correct',
                'message': 'Правильно!',
                'user_answer': display_user,
                'correct_answer': display_correct
            }
        else:
            # Определяем текст правильного ответа для отображения
            if question_type in ('multiple_choice', 'dialogue_completion', 'listening_choice') and 'options' in question:
                # Уже сконвертировано выше в display_correct / display_user
                correct_text = str(display_correct)
                user_text = str(display_user)

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

            elif question_type == 'matching':
                # For matching questions, format pairs as readable text
                if isinstance(correct_answer, list):
                    correct_text = ', '.join(
                        f"{p.get('left', '')} → {p.get('right', '')}"
                        for p in correct_answer if isinstance(p, dict)
                    )
                elif 'pairs' in question:
                    correct_text = ', '.join(
                        f"{p.get('left', '')} → {p.get('right', '')}"
                        for p in question['pairs']
                    )
                else:
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
