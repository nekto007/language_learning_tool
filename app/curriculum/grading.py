# app/curriculum/grading.py
"""Submission processing / grading functions for curriculum exercises."""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Optional

from app.curriculum.constants import PASSING_SCORE_DEFAULT
from app.utils.normalization import normalize_text

logger = logging.getLogger(__name__)


FINAL_TEST_MAX_ATTEMPTS_PER_DAY = 3
FINAL_TEST_ATTEMPT_WINDOW_HOURS = 24


def check_final_test_attempts_exhausted(
    user_id: int,
    lesson_id: int,
    db_session=None,
    max_attempts: int = FINAL_TEST_MAX_ATTEMPTS_PER_DAY,
    window_hours: int = FINAL_TEST_ATTEMPT_WINDOW_HOURS,
) -> Optional[dict]:
    """Return rate-limit dict if user has met or exceeded the final-test attempt cap
    within the rolling window. Admins are exempt. Returns None when allowed.

    Response on exhaustion:
        {"passed": False, "error": "attempts_exhausted",
         "retry_after": <ISO8601 UTC>, "max_attempts": N, "window_hours": H}
    """
    from app.auth.models import User
    from app.curriculum.models import LessonAttempt
    from app.utils.db import db as default_db

    session = db_session if db_session is not None else default_db.session
    if hasattr(session, 'session'):
        session = session.session

    user = session.get(User, user_id)
    if user is not None and getattr(user, 'is_admin', False):
        return None

    window_start = datetime.now(UTC) - timedelta(hours=window_hours)
    window_start_naive = window_start.replace(tzinfo=None)

    # Filter on completed_at, not started_at: production code in
    # complete_lesson reuses progress.started_at across every attempt
    # (set once on initial LessonProgress creation), so a started_at
    # filter would let the rolling window age out by 24h after the
    # first attempt and never gate a retry. completed_at is set fresh
    # per attempt.
    attempts = (
        session.query(LessonAttempt)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.lesson_id == lesson_id,
            LessonAttempt.completed_at.isnot(None),
            LessonAttempt.completed_at >= window_start_naive,
            LessonAttempt.passed.is_(False),
        )
        .order_by(LessonAttempt.completed_at.asc())
        .all()
    )

    if len(attempts) < max_attempts:
        return None

    oldest = attempts[0].completed_at
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    retry_after = oldest + timedelta(hours=window_hours)

    return {
        "passed": False,
        "error": "attempts_exhausted",
        "retry_after": retry_after.isoformat(),
        "max_attempts": max_attempts,
        "window_hours": window_hours,
    }


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
        # Typo tolerance only for single-word answers >=4 chars; on shorter
        # tokens a 1-edit window admits substantively different words
        # (e.g. "is"/"in", "a"/"o").
        if (
            ' ' not in correct_normalized
            and ' ' not in user_normalized
            and len(correct_normalized) >= 4
        ):
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
    if not correct_pairs:
        return False
    if len(user_pairs) != len(correct_pairs):
        return False

    def _key(p):
        if not isinstance(p, dict):
            return None
        # Content payloads use {english, russian}; user payloads use {left, right}.
        # Treat both shapes as equivalent so matching grading isn't a no-op.
        left = p.get('left') or p.get('english') or p.get('word')
        right = p.get('right') or p.get('russian') or p.get('translation')
        return (_normalize_answer(left), _normalize_answer(right))

    user_keys = [_key(p) for p in user_pairs]
    correct_keys = [_key(p) for p in correct_pairs]
    if any(k is None or k == ("", "") for k in user_keys):
        return False
    if any(k is None for k in correct_keys):
        return False
    return sorted(user_keys) == sorted(correct_keys)


def _normalize_for_dictation(text: str) -> str:
    """Normalize dictation text: strip, lower, collapse whitespace, remove punctuation except apostrophes."""
    if not text:
        return ""
    s = str(text).lower().strip()
    # Remove all punctuation except apostrophes (to preserve contractions like don't, it's)
    s = re.sub(r"[^\w\s']", "", s)
    # Collapse multiple spaces
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def grade_dictation(user_text: str, transcript: str, hint_chars: int = 0) -> dict:
    """Grade a dictation exercise by comparing user text to the transcript word by word.

    Args:
        user_text: The text submitted by the user.
        transcript: The correct transcript text.
        hint_chars: Number of characters pre-filled per word on the client (server-side
            grading is unchanged — full word comparison is used regardless).

    Returns:
        dict with keys: score (0-100), passed (bool), correct_words (int),
        total_words (int), word_results (list of {word, user_word, correct}).
    """
    user_normalized = _normalize_for_dictation(user_text)
    transcript_normalized = _normalize_for_dictation(transcript)

    transcript_words = transcript_normalized.split() if transcript_normalized else []
    user_words = user_normalized.split() if user_normalized else []

    total_words = len(transcript_words)
    if total_words == 0:
        return {
            "score": 0,
            "passed": False,
            "correct_words": 0,
            "total_words": 0,
            "word_results": [],
        }

    correct_words = 0
    word_results = []
    for i, correct_word in enumerate(transcript_words):
        user_word = user_words[i] if i < len(user_words) else ""
        is_correct = user_word == correct_word
        if is_correct:
            correct_words += 1
        word_results.append({"word": correct_word, "user_word": user_word, "correct": is_correct})

    score = round(correct_words / total_words * 100)
    passed = score >= 80

    return {
        "score": score,
        "passed": passed,
        "correct_words": correct_words,
        "total_words": total_words,
        "word_results": word_results,
    }


def grade_audio_fill_blank(user_answers: list, items: list) -> dict:
    """Grade an audio fill-in-blank exercise.

    Args:
        user_answers: List of strings, one per item (same order as items).
        items: List of item dicts with 'answer' (and optional 'options') fields.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), item_results (list of {answer, user_answer, correct}).
    """
    total = len(items or [])
    items = items or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }

    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_answer = user_answers[i] if i < len(user_answers) else ''
        correct_answer = item.get('answer', '')
        options = item.get('options')

        if options:
            # Multiple-choice mode: exact match after normalization
            is_correct = _normalize_answer(user_answer) == _normalize_answer(correct_answer)
        else:
            # Free-text mode: Levenshtein ≤1 for single-word, exact for multi-word
            is_correct = _strict_text_match(user_answer, [correct_answer])

        if is_correct:
            correct += 1
        item_results.append({
            'answer': correct_answer,
            'user_answer': user_answer,
            'correct': is_correct,
        })

    score = round(correct / total * 100)
    passed = score >= 70

    return {
        'score': score,
        'passed': passed,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_translation(user_answer: str, correct_answer: str) -> dict:
    """Grade a standalone translation exercise (Russian → English).

    Delegates to ``_strict_text_match``: exact match after normalization with
    Levenshtein ≤1 tolerance for single-word answers; multi-word requires exact.

    Returns:
        dict with keys: is_correct (bool), user_answer (str), correct_answer (str).
    """
    is_correct = _strict_text_match(user_answer, [correct_answer])
    return {
        'is_correct': is_correct,
        'user_answer': user_answer,
        'correct_answer': correct_answer,
    }


def grade_translation_multi(user_answers: list, items: list) -> dict:
    """Grade a multi-item guided translation lesson.

    Matches the audio_fill_blank / sentence_completion shape so the existing
    completion banner + restore-on-reload flow on the client can be reused
    unchanged.

    Args:
        user_answers: List[str], one per item in original order.
        items: List[dict] from ``content['items']`` with at least ``english``
            (and optional ``alternatives``).

    Returns:
        {score, passed, correct_items, total_items, item_results}.
        Each item_result: {answer, user_answer, correct}.
    """
    total = len(items or [])
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }
    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_answer = (user_answers[i] if i < len(user_answers) else '') or ''
        canonical = item.get('english', '') or ''
        candidates = [canonical]
        for alt in (item.get('alternatives') or []):
            if isinstance(alt, str) and alt.strip():
                candidates.append(alt)
        is_correct = _strict_text_match(user_answer, candidates)
        if is_correct:
            correct += 1
        item_results.append({
            'answer': canonical,
            'user_answer': user_answer,
            'correct': is_correct,
        })
    score = round(correct / total * 100)
    return {
        'score': score,
        'passed': score >= 70,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_sentence_correction(user_answer: str, correct_sentence: str) -> dict:
    """Grade a single-item sentence correction exercise.

    Compares the user's corrected sentence to the correct version using
    normalized exact match. No Levenshtein tolerance — the user must
    supply the exact corrected sentence (modulo punctuation/case).

    Returns:
        dict with keys: is_correct (bool), user_answer (str), correct_sentence (str).
    """
    is_correct = _normalize_answer(user_answer) == _normalize_answer(correct_sentence)
    return {
        'is_correct': is_correct,
        'user_answer': user_answer,
        'correct_sentence': correct_sentence,
    }


def grade_sentence_correction_multi(user_answers: list, items: list) -> dict:
    """Grade a multi-item sentence-correction exercise.

    Each item has its own ``correct_sentence``. The user's answer for the
    item is compared via normalized exact match (same rule as the single-
    item grader). Returns a sentence_completion-style summary so the
    submit endpoint and the client showResults can stay consistent across
    the two text-input lesson types.

    Args:
        user_answers: List of strings, one per item (same order as items).
        items: List of item dicts with at least ``correct_sentence``.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), item_results (list of {incorrect_sentence,
        correct_sentence, user_answer, correct, explanation, error_type,
        error_type_ru, translation}).
    """
    total = len(items or [])
    items = items or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }
    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_value = user_answers[i] if i < len(user_answers) else ''
        canonical = item.get('correct_sentence', '')
        is_correct = _normalize_answer(user_value) == _normalize_answer(canonical)
        if is_correct:
            correct += 1
        item_results.append({
            'incorrect_sentence': item.get('incorrect_sentence', ''),
            'correct_sentence': canonical,
            'user_answer': user_value,
            'correct': is_correct,
            'explanation': item.get('explanation', ''),
            'error_type': item.get('error_type', ''),
            'error_type_ru': item.get('error_type_ru', ''),
            'translation': item.get('translation', ''),
        })
    score = round(correct / total * 100)
    return {
        'score': score,
        'passed': score >= PASSING_SCORE_DEFAULT,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_sentence_completion(user_answers: list, items: list) -> dict:
    """Grade a sentence completion exercise.

    Each item has a ``prompt`` (sentence start) and an ``answer`` (expected
    completion). Grading uses exact match after normalization with Levenshtein
    ≤1 tolerance for single-word answers (same rule as fill_blank).

    Args:
        user_answers: List of strings, one per item (same order as items).
        items: List of item dicts with 'prompt' and 'answer' fields.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), item_results (list of {prompt, answer, user_answer, correct}).
    """
    total = len(items or [])
    items = items or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }

    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_answer = user_answers[i] if i < len(user_answers) else ''
        correct_answer = item.get('answer', '')
        is_correct = _strict_text_match(user_answer, [correct_answer])
        if is_correct:
            correct += 1
        item_results.append({
            'prompt': item.get('prompt', ''),
            'answer': correct_answer,
            'user_answer': user_answer,
            'correct': is_correct,
        })

    score = round(correct / total * 100)
    passed = score >= 70

    return {
        'score': score,
        'passed': passed,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_collocation_matching(user_pairs: list, correct_pairs: list) -> dict:
    """Grade a collocation matching exercise with partial scoring.

    Args:
        user_pairs: List of {phrase, translation} dicts submitted by the user.
        correct_pairs: List of {phrase, translation} dicts from lesson content.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), pair_results (list of {phrase, translation, correct}).
    """
    total = len(correct_pairs or [])
    correct_pairs = correct_pairs or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'pair_results': [],
        }

    # Build lookup: normalized_phrase → normalized_translation from user submission
    user_lookup: dict[str, str] = {}
    for p in (user_pairs or []):
        if isinstance(p, dict):
            phrase_key = _normalize_answer(p.get('phrase', ''))
            translation_val = _normalize_answer(p.get('translation', ''))
            if phrase_key:
                user_lookup[phrase_key] = translation_val

    correct = 0
    pair_results = []
    for item in correct_pairs:
        phrase = item.get('phrase', '')
        translation = item.get('translation', '')
        phrase_key = _normalize_answer(phrase)
        correct_val = _normalize_answer(translation)
        user_val = user_lookup.get(phrase_key, '')
        is_correct = bool(user_val and user_val == correct_val)
        if is_correct:
            correct += 1
        pair_results.append({
            'phrase': phrase,
            'translation': translation,
            'user_translation': item.get('translation', '') if is_correct else (
                next(
                    (p.get('translation', '') for p in (user_pairs or [])
                     if isinstance(p, dict) and _normalize_answer(p.get('phrase', '')) == phrase_key),
                    ''
                )
            ),
            'correct': is_correct,
        })

    score = round(correct / total * 100)
    passed = score >= 70

    return {
        'score': score,
        'passed': passed,
        'correct_items': correct,
        'total_items': total,
        'pair_results': pair_results,
    }


def grade_pronunciation_match(recognized_text: str, target_word: str) -> dict:
    """Check whether a Web Speech API transcript matches the target pronunciation word.

    Uses the same normalization as fill_blank grading (strip/lower/punct) plus
    Levenshtein ≤1 tolerance for single-word targets (≥4 chars). Multi-word
    targets require exact match after normalization.

    Returns:
        dict with keys: matched (bool), recognized (str), target (str).
    """
    matched = _strict_text_match(recognized_text, [target_word])
    return {
        'matched': matched,
        'recognized': recognized_text,
        'target': target_word,
    }


def process_grammar_submission(exercises: list, answers: dict) -> dict:
    correct_count = 0
    total_count = len(exercises)
    feedback = {}

    for i, exercise in enumerate(exercises):
        # Преобразуем строковые ключи в числовые для совместимости
        str_i = str(i)

        if exercise.get('type') == 'sentence_builder':
            user_answer = answers.get(i, answers.get(str_i, []))
            correct_order = exercise.get('correct_order', [])
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

        if exercise.get('type') == 'error_correction':
            user_answer = answers.get(i, answers.get(str_i, ''))
            correct_answer = exercise.get('correct_sentence', exercise.get('answer', ''))
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

        if exercise.get('type') == 'reorder':
            user_answer = answers.get(i, answers.get(str_i, ''))
            correct_answer = exercise.get('answer', '')

            def normalize_sentence(sentence):
                if not sentence:
                    return ""
                normalized = sentence.strip()
                normalized = re.sub(r'\s+', ' ', normalized)
                normalized = re.sub(r'\s+([.,!?;:])', r'\1', normalized)
                normalized = re.sub(r'(\()\s+', r'\1', normalized)
                normalized = re.sub(r'\s+(\))', r'\1', normalized)
                return normalized

            user_normalized = normalize_sentence(user_answer)
            correct_normalized = normalize_sentence(correct_answer)
            is_correct = user_normalized == correct_normalized
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

        elif exercise.get('type') == 'match':
            pairs = exercise.get('pairs', [])
            user_matches_raw = answers.get(i, answers.get(str_i, '{}'))

            if isinstance(user_matches_raw, str):
                try:
                    user_matches = json.loads(user_matches_raw)
                except json.JSONDecodeError:
                    user_matches = {}
            else:
                user_matches = user_matches_raw

            is_correct = True
            user_match_display = {}
            correct_match_display = {}
            for idx, pair in enumerate(pairs):
                correct_match_display[pair['left']] = pair['right']

            if len(user_matches) != len(pairs):
                is_correct = False
            else:
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
                        if user_right_value != correct_right_value:
                            is_correct = False
                    except (ValueError, IndexError, KeyError):
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
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': 'Неправильно. Проверьте соответствия.',
                    'user_matches': user_match_display,
                    'correct_matches': correct_match_display
                }
            continue

        user_answer = str(answers.get(i, answers.get(str_i, '')))
        if isinstance(user_answer, str):
            user_answer = user_answer.strip()

        correct_answer = None
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

        exercise_type = exercise.get('type', '')

        if exercise_type == 'true_false':
            if correct_answer is None:
                feedback[str_i] = {
                    'status': 'incorrect',
                    'message': 'Ошибка в упражнении - не найден правильный ответ',
                    'user_answer': user_answer,
                    'correct_answer': 'unknown'
                }
                continue

            user_bool = user_answer.lower() == 'true' if isinstance(user_answer, str) else bool(user_answer)
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
                correct_answer = correct_answer[0] if correct_answer else "UNKNOWN"

        if not isinstance(correct_answer, str):
            correct_answer = str(correct_answer)

        def normalize_answer(answer):
            if not answer:
                return ""
            normalized = answer.strip()
            normalized = re.sub(r'\s+', ' ', normalized)
            normalized = re.sub(r'\s*,\s*', ', ', normalized)
            normalized = re.sub(r'\s*\.\s*', '. ', normalized)
            normalized = re.sub(r'\s*!\s*', '! ', normalized)
            normalized = re.sub(r'\s*\?\s*', '? ', normalized)
            for char in ["'", '"', "[", "]"]:
                normalized = normalized.replace(char, "")
            return normalized.strip()

        user_normalized = normalize_answer(user_answer)
        correct_normalized = normalize_answer(correct_answer)
        is_correct = user_normalized.lower() == correct_normalized.lower()

        # Sentence-start fill-blank: capitalization matters for the first word
        if not is_correct and exercise_type in ['fill-blank', 'fill_in_blank']:
            prompt_text = exercise.get('prompt', exercise.get('text', ''))
            if prompt_text.strip().startswith('___') or prompt_text.strip().startswith('_'):
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


def process_quiz_submission(questions: list, answers: dict) -> dict:
    correct_count = 0
    total_count = len(questions)
    feedback = {}

    for i, question in enumerate(questions):
        # Support both integer and string keys (frontend may send '0', '1', etc.)
        user_answer = answers.get(str(i), answers.get(i, ''))
        question_type = question.get('type', 'multiple_choice')

        correct_answer = None
        if 'answer' in question:
            correct_answer = question['answer']
        elif 'correct_answer' in question:
            correct_answer = question['correct_answer']
        elif 'correct' in question:
            correct_answer = question['correct']
        elif 'correct_index' in question:
            correct_answer = question['correct_index']
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
                        options_stripped = [opt.strip() if isinstance(opt, str) else opt for opt in question['options']]
                        correct_answer_stripped = (
                            correct_answer.strip() if isinstance(correct_answer, str) else correct_answer
                        )

                        if correct_answer_stripped in options_stripped:
                            correct_idx = options_stripped.index(correct_answer_stripped)
                        else:
                            correct_answer_lower = (
                                correct_answer_stripped.lower()
                                if isinstance(correct_answer_stripped, str)
                                else str(correct_answer_stripped).lower()
                            )
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

            except (ValueError, TypeError):
                is_correct = False

        elif question_type == 'true_false':
            try:
                if isinstance(user_answer, str):
                    user_bool = user_answer.lower() == 'true'
                else:
                    user_bool = bool(user_answer)

                is_correct = user_bool == correct_answer

            except (ValueError, TypeError):
                is_correct = False

        elif question_type in ['fill_in_blank', 'fill-in-blank', 'fill_blank', 'translation', 'transformation']:
            # Strict grading: exact match after normalization, with single-word
            # Levenshtein ≤1 typo tolerance. Multi-word overlap heuristics removed —
            # they previously credited substantively wrong answers.

            if correct_answer is None:
                is_correct = False
            else:
                if isinstance(correct_answer, list):
                    candidates = list(correct_answer)
                else:
                    candidates = [correct_answer]
                    candidates.extend(question.get('alternative_answers', []) or [])
                    candidates.extend(question.get('acceptable_answers', []) or [])

                is_correct = _strict_text_match(user_answer, candidates)


        elif question_type in ['reorder', 'ordering']:
            if correct_answer is None:
                is_correct = False
            else:
                def normalize_sentence(sentence):
                    if not sentence:
                        return ""
                    normalized = sentence.strip()
                    normalized = re.sub(r'\s+', ' ', normalized)
                    normalized = re.sub(r'\s+([.,!?;:])', r'\1', normalized)
                    normalized = re.sub(r'(\()\s+', r'\1', normalized)
                    normalized = re.sub(r'\s+(\))', r'\1', normalized)
                    return normalized

                user_normalized = normalize_sentence(user_answer)
                correct_normalized = normalize_sentence(str(correct_answer))
                is_correct = user_normalized == correct_normalized
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
            raw = user_answer
            # Frontend posts matching answers as a JSON-stringified dict
            # ({left_value: right_value, ...}); decode into pairs here so
            # the strict grader can compare keys against ``correct_pairs``.
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (ValueError, TypeError):
                    raw = None
            if isinstance(raw, list):
                user_pairs = raw
            elif isinstance(raw, dict):
                if isinstance(raw.get('pairs'), list):
                    user_pairs = raw['pairs']
                else:
                    user_pairs = [
                        {'left': k, 'right': v} for k, v in raw.items()
                    ]
            else:
                pairs_field = answers.get(f'{i}_pairs', answers.get(f'{str(i)}_pairs'))
                if isinstance(pairs_field, list):
                    user_pairs = pairs_field

            if user_pairs is None:
                is_correct = False
            else:
                is_correct = _grade_matching_pairs(user_pairs, correct_pairs)

        else:
            is_correct = correct_answer is None

        display_user = user_answer
        display_correct = correct_answer
        if question_type in ('multiple_choice', 'dialogue_completion', 'listening_choice') and 'options' in question:
            opts = question['options']
            if isinstance(correct_answer, int) and 0 <= correct_answer < len(opts):
                display_correct = opts[correct_answer]
            elif isinstance(correct_answer, str) and correct_answer.isdigit():
                idx = int(correct_answer)
                if 0 <= idx < len(opts):
                    display_correct = opts[idx]
                elif 1 <= idx <= len(opts):
                    display_correct = opts[idx - 1]
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
            if (
                question_type in ('multiple_choice', 'dialogue_completion', 'listening_choice')
                and 'options' in question
            ):
                correct_text = str(display_correct)
                user_text = str(display_user)

            elif question_type == 'true_false':
                correct_text = 'Правда' if correct_answer else 'Ложь'
                user_bool = str(user_answer).lower() == 'true' if isinstance(user_answer, str) else bool(user_answer)
                user_text = 'Правда' if user_bool else 'Ложь'

            elif question_type in ['fill_in_blank', 'fill-in-blank', 'translation']:
                user_text = str(user_answer)

                if isinstance(correct_answer, list):
                    if len(correct_answer) == 1:
                        correct_text = correct_answer[0]
                    else:
                        correct_text = f"Возможные ответы: {', '.join(correct_answer)}"
                elif question_type == 'translation' and 'alternative_answers' in question:
                    all_answers = [str(correct_answer)]
                    if question['alternative_answers']:
                        all_answers.extend(question['alternative_answers'])
                    correct_text = ' / '.join(all_answers)
                else:
                    correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'

            elif question_type == 'reorder':
                correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'
                user_text = str(user_answer)

            elif question_type == 'matching':
                # For matching questions, format pairs as readable text.
                # Content schemas vary: some carry ``left``/``right``, older
                # ones use ``english``/``russian`` or ``word``/``translation``.
                # Detail review handles all three — mirror that here so the
                # short "Что повторить" summary doesn't degrade to a row of
                # bare " → " arrows when the pair fields don't match.
                def _pair_left(p: dict) -> str:
                    return str(
                        p.get('left') or p.get('english')
                        or p.get('word') or p.get('term') or ''
                    )

                def _pair_right(p: dict) -> str:
                    return str(
                        p.get('right') or p.get('russian')
                        or p.get('translation') or p.get('match') or ''
                    )

                pairs_src = None
                if isinstance(correct_answer, list):
                    pairs_src = correct_answer
                elif 'pairs' in question:
                    pairs_src = question['pairs']

                if pairs_src is not None:
                    formatted = [
                        f"{_pair_left(p)} → {_pair_right(p)}"
                        for p in pairs_src if isinstance(p, dict)
                        and (_pair_left(p) or _pair_right(p))
                    ]
                    correct_text = ', '.join(formatted) if formatted else 'Не указан'
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

    score = round((correct_count / total_count) * 100) if total_count > 0 else 0

    return {
        'correct_answers': correct_count,
        'total_questions': total_count,
        'score': score,
        'feedback': feedback,
        'answers': answers,
        'timestamp': datetime.now(UTC).isoformat()
    }


def process_matching_submission(pairs: list, user_matches: dict) -> dict:
    correct_count = 0
    total_count = len(pairs)
    feedback = {}
    incorrect_matches = {}

    for i, pair in enumerate(pairs):
        left = pair['left']
        right = pair['right']

        # Two formats accepted: index-based {'0': 1} or value-based {'hello': 'привет'}
        user_match_index = user_matches.get(str(i)) or user_matches.get(i)

        if user_match_index is not None:
            try:
                user_match_index = int(user_match_index)
                user_matched_right = pairs[user_match_index]['right'] if 0 <= user_match_index < len(pairs) else None
            except (ValueError, IndexError):
                user_matched_right = None
        else:
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
            incorrect_matches[str(i)] = {
                'user': user_matched_right,
                'correct': right
            }

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


def process_final_test_submission(questions: list, user_answers: dict) -> dict:
    correct_count = 0
    total_count = len(questions)
    feedback = {}


    for i, question in enumerate(questions):
        # Получаем ответ пользователя - поддержка обоих форматов (string and int keys)
        user_answer = user_answers.get(str(i), user_answers.get(i))

        correct_answer = question.get('answer')
        if correct_answer is None:
            correct_answer = question.get('correct_answer')
        if correct_answer is None:
            correct_answer = question.get('correct_index')
        if correct_answer is None:
            correct_answer = question.get('correct')

        is_correct = False

        qtype = question.get('type', '')
        if qtype == 'multiple_choice':
            if user_answer is not None:
                try:
                    user_idx = int(user_answer)
                    is_correct = user_idx == correct_answer
                except (ValueError, TypeError):
                    is_correct = False

        elif qtype == 'true_false':
            if user_answer in ['true', 'false']:
                user_bool = user_answer == 'true'
                is_correct = user_bool == correct_answer

        elif qtype in ['fill_in_blank', 'translation']:
            if user_answer:
                user_normalized = normalize_text(user_answer)

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
            if isinstance(user_answer, dict):
                correct_pairs = {pair['left']: pair['right'] for pair in question.get('pairs', [])}
                matches_correct = all(
                    user_answer.get(left) == right
                    for left, right in correct_pairs.items()
                )
                all_answered = len(user_answer) == len(correct_pairs)
                is_correct = matches_correct and all_answered

        elif qtype == 'reorder':
            if user_answer:
                user_normalized = normalize_text(user_answer)
                correct_normalized = normalize_text(correct_answer)
                is_correct = user_normalized == correct_normalized

        if is_correct:
            correct_count += 1

        feedback[str(i)] = {
            'is_correct': is_correct,
            'user_answer': user_answer,
            'correct_answer': correct_answer
        }

    score = round((correct_count / total_count) * 100) if total_count > 0 else 0
    passed = score >= 70

    return {
        'score': round(score, 1),
        'correct_answers': correct_count,
        'total_questions': total_count,
        'passed': passed,
        'feedback': feedback
    }
