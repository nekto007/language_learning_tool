# app/grammar_lab/services/grader.py
"""
Exercise grader for Grammar Lab.

Grades different types of grammar exercises.
"""

import logging
import re
from typing import Any, Dict

from app.curriculum.grading import text_answer_variants
from app.grammar_lab.models import GrammarExercise

logger = logging.getLogger(__name__)


class GrammarExerciseGrader:
    """Grades grammar exercises"""

    def grade(self, exercise: GrammarExercise, user_answer: Any) -> Dict:
        """
        Grade an exercise answer.

        Args:
            exercise: GrammarExercise instance
            user_answer: User's answer (string, int, list depending on type)

        Returns:
            Dict with is_correct, correct_answer, explanation, user_answer
        """
        grader_method = getattr(self, f'_grade_{exercise.exercise_type}', None)
        if not grader_method:
            logger.error(f"Unknown exercise type: {exercise.exercise_type}")
            return {
                'is_correct': False,
                'error': f"Unknown exercise type: {exercise.exercise_type}"
            }

        try:
            result = grader_method(exercise, user_answer)
            if not isinstance(result, dict):
                raise TypeError(
                    f"grader must return a dict, got {type(result).__name__}"
                )

            # ``GrammarAttempt.is_correct`` is a strict SQL Boolean.  Keep the
            # contract enforcement here, before a malformed value can be added
            # to the session and make an unrelated query fail during autoflush.
            # Fail closed: an invalid grader result must never award progress.
            is_correct = result.get('is_correct')
            if not isinstance(is_correct, bool):
                logger.error(
                    "Grader contract violation for exercise %s (%s): "
                    "is_correct must be bool, got %s %r; treating as False",
                    exercise.id,
                    exercise.exercise_type,
                    type(is_correct).__name__,
                    is_correct,
                )
                result['is_correct'] = False

            return result
        except Exception as e:
            logger.error(f"Error grading exercise {exercise.id}: {e}")
            return {
                'is_correct': False,
                'error': str(e)
            }

    def _normalize_answer(self, answer: str) -> str:
        """Normalize answer for comparison"""
        if not answer:
            return ''
        # Lowercase, strip, remove extra spaces
        normalized = answer.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        # Remove spaces before punctuation (for reorder exercises)
        normalized = re.sub(r'\s+([.!?,;:])', r'\1', normalized)
        # Remove punctuation at the end
        normalized = re.sub(r'[.!?]+$', '', normalized)
        return normalized

    _HINT_RE = re.compile(r"\s*\([^()]*\)")

    @classmethod
    def _strip_hints(cls, text: str) -> str:
        """Drop parenthesised author hints — ``Tom ___ (wake up) at sunrise``
        → ``Tom ___ at sunrise`` — so a full-sentence answer can be compared
        with the question text the learner actually reproduces."""
        return cls._HINT_RE.sub('', text or '')

    @staticmethod
    def _same_text(user: str, candidate: str) -> bool:
        """Free-text equality that tolerates contractions (doesn't / does
        not) and lexical variants (mum / mom / mother) on both sides —
        shared with the course translation grader (``text_answer_variants``)
        so the two zones accept the same answers. Empty strings never match."""
        if not (user or '').strip() or not (candidate or '').strip():
            return False
        return bool(text_answer_variants(user) & text_answer_variants(candidate))

    def _text_matches(self, user: str, candidates) -> bool:
        """``user`` equals one of ``candidates`` after the lab normalisation
        or after contraction/lexical folding."""
        user_norm = self._normalize_answer(user)
        if not user_norm:
            return False
        for candidate in candidates:
            if candidate is None or not str(candidate).strip():
                continue
            if user_norm == self._normalize_answer(candidate):
                return True
            if self._same_text(user, str(candidate)):
                return True
        return False

    def _grade_fill_blank(self, exercise: GrammarExercise, answer: str) -> Dict:
        """Grade fill-in-the-blank exercise"""
        content = exercise.content
        candidates = [content.get('correct_answer', '')] + list(content.get('alternatives', []) or [])

        is_correct = self._text_matches(answer, candidates)

        # If not matched and question has a blank, check if user typed the
        # full sentence. The author hint in brackets («(wake up)») is NOT part
        # of what the learner reproduces, so it is stripped before the
        # substitution; the raw question is still tried for hint-less items.
        if not is_correct and '___' in (content.get('question') or ''):
            question = content.get('question', '')
            stripped = self._strip_hints(question)
            for candidate in candidates:
                if not str(candidate or '').strip():
                    continue
                for template in (stripped, question):
                    if self._text_matches(answer, [template.replace('___', str(candidate))]):
                        is_correct = True
                        break
                if is_correct:
                    break

        return {
            'is_correct': is_correct,
            'correct_answer': content.get('correct_answer', ''),
            'explanation': content.get('explanation', ''),
            'user_answer': answer
        }

    def _grade_multiple_choice(self, exercise: GrammarExercise, answer: Any) -> Dict:
        """Grade multiple choice exercise"""
        content = exercise.content
        correct_value = content.get('correct_answer')
        options = content.get('options', [])

        # correct_value can be index (int) or string (actual answer)
        if isinstance(correct_value, int):
            correct_index = correct_value
            if 0 <= correct_index < len(options):
                correct_answer_text = options[correct_index]
            elif 1 <= correct_index <= len(options):
                correct_answer_text = options[correct_index - 1]  # 1-indexed fallback
                correct_index = correct_index - 1
            else:
                correct_answer_text = str(correct_value)
        elif isinstance(correct_value, str) and correct_value in options:
            correct_index = options.index(correct_value)
            correct_answer_text = correct_value
        elif isinstance(correct_value, str) and correct_value.isdigit():
            # String index like "2" or "3"
            ci = int(correct_value)
            if 0 <= ci < len(options):
                correct_index = ci
                correct_answer_text = options[ci]
            elif 1 <= ci <= len(options):
                correct_index = ci - 1
                correct_answer_text = options[ci - 1]
            else:
                correct_index = None
                correct_answer_text = correct_value
        else:
            # Fallback: treat as string answer
            correct_index = None
            correct_answer_text = str(correct_value) if correct_value else ''

        # Handle both string and int answer from user
        try:
            user_index = int(answer)
        except (ValueError, TypeError):
            # User sent string answer - compare directly
            user_answer_text = str(answer) if answer else ''
            is_correct = self._normalize_answer(user_answer_text) == self._normalize_answer(correct_answer_text)
            return {
                'is_correct': is_correct,
                'correct_answer': correct_answer_text,
                'explanation': content.get('explanation', ''),
                'user_answer': user_answer_text
            }

        # Resolve user_index to text (with 1-indexed fallback)
        if 0 <= user_index < len(options):
            user_answer_text = options[user_index]
        elif 1 <= user_index <= len(options):
            user_answer_text = options[user_index - 1]
            user_index = user_index - 1  # normalize for comparison
        else:
            user_answer_text = str(answer)

        # User sent index
        if correct_index is not None:
            is_correct = user_index == correct_index
        else:
            # Compare by text
            is_correct = self._normalize_answer(user_answer_text) == self._normalize_answer(correct_answer_text)

        return {
            'is_correct': is_correct,
            'correct_answer': correct_answer_text,
            'explanation': content.get('explanation', ''),
            'user_answer': user_answer_text
        }

    def _grade_reorder(self, exercise: GrammarExercise, answer: Any) -> Dict:
        """Grade word reordering exercise"""
        content = exercise.content
        correct_sentence = self._normalize_answer(content.get('correct_answer', ''))

        # Answer can be either a string or a list of indices
        if isinstance(answer, list):
            # Convert indices to sentence
            words = content.get('words', [])
            try:
                user_sentence = ' '.join(words[i] for i in answer)
            except (IndexError, TypeError):
                user_sentence = ''
        else:
            user_sentence = answer

        user_normalized = self._normalize_answer(user_sentence)
        is_correct = user_normalized == correct_sentence

        return {
            'is_correct': is_correct,
            'correct_answer': content.get('correct_answer', ''),
            'explanation': content.get('explanation', ''),
            'user_answer': user_sentence
        }

    def _grade_error_correction(self, exercise: GrammarExercise, answer: str) -> Dict:
        """Grade error correction exercise

        Accepts either:
        - Just the corrected word (e.g., "are")
        - The full corrected sentence (e.g., "We are happy")
        """
        content = exercise.content
        # Either the corrected word OR the full sentence is accepted; the
        # comparison tolerates contractions and lexical variants, so «does
        # not talk» passes for a key written as «doesn't talk». The bool()
        # stays: an empty ``full_correct`` must never make a wrong answer
        # evaluate to '' when persisted to a Boolean column.
        candidates = (
            [content.get('correct_answer', ''), content.get('full_correct', '')]
            + list(content.get('alternatives', []) or [])
        )
        is_correct = bool(self._text_matches(answer, candidates))

        return {
            'is_correct': is_correct,
            'correct_answer': content.get('correct_answer', ''),
            'full_correct': content.get('full_correct', ''),
            'explanation': content.get('explanation', ''),
            'user_answer': answer
        }

    def _grade_transformation(self, exercise: GrammarExercise, answer: str) -> Dict:
        """Grade transformation exercise"""
        content = exercise.content
        correct = self._normalize_answer(content.get('correct_answer', ''))
        candidates = [content.get('correct_answer', '')] + list(content.get('alternatives', []) or [])

        is_correct = self._text_matches(answer, candidates)

        return {
            'is_correct': is_correct,
            'correct_answer': content.get('correct_answer', ''),
            'explanation': content.get('explanation', ''),
            'user_answer': answer
        }

    def _grade_translation(self, exercise: GrammarExercise, answer: str) -> Dict:
        """Grade translation exercise"""
        content = exercise.content
        # Check both 'alternatives' and 'acceptable_answers' fields
        alt_list = content.get('alternatives', []) or content.get('acceptable_answers', [])
        candidates = [content.get('correct_answer', '')] + list(alt_list or [])

        is_correct = self._text_matches(answer, candidates)

        return {
            'is_correct': is_correct,
            'correct_answer': content.get('correct_answer', ''),
            'explanation': content.get('explanation', ''),
            'key_grammar': content.get('key_grammar', ''),
            'user_answer': answer
        }

    def _grade_matching(self, exercise: GrammarExercise, answer: Any) -> Dict:
        """Grade matching exercise"""
        content = exercise.content
        pairs = content.get('pairs', [])

        # Answer should be a list of pairs like [[0, 1], [1, 0], ...]
        # or a dict like {"0": "1", "1": "0", ...}
        if not answer:
            return {
                'is_correct': False,
                'correct_answer': pairs,
                'explanation': content.get('explanation', ''),
                'user_answer': answer
            }

        # Build correct mapping
        correct_mapping = {i: i for i in range(len(pairs))}  # Same index = correct match

        # Parse user answer
        if isinstance(answer, dict):
            user_mapping = {int(k): int(v) for k, v in answer.items()}
        elif isinstance(answer, list):
            user_mapping = {pair[0]: pair[1] for pair in answer if len(pair) == 2}
        else:
            user_mapping = {}

        # Check if all mappings are correct
        is_correct = user_mapping == correct_mapping

        return {
            'is_correct': is_correct,
            'correct_answer': pairs,
            'explanation': content.get('explanation', ''),
            'user_answer': answer
        }

    def _grade_true_false(self, exercise: GrammarExercise, answer: Any) -> Dict:
        """Grade true/false exercise"""
        content = exercise.content
        correct = content.get('correct_answer')  # True or False or 0/1

        # Normalize the correct answer to boolean (True/False or 0/1 or str).
        if isinstance(correct, str):
            correct_bool = correct.lower() in ('true', '1', 'yes')
        else:
            correct_bool = bool(correct)

        # An unset/blank answer is never correct. Without this guard a missing
        # answer coerces to bool(None)/bool('') == False and would be scored
        # CORRECT for every false-statement item (correct_answer=False), e.g.
        # via a direct API submit with no selection.
        if answer is None or (isinstance(answer, str) and answer.strip() == ''):
            return {
                'is_correct': False,
                'correct_answer': 'True' if correct_bool else 'False',
                'explanation': content.get('explanation', ''),
                'user_answer': '',
            }

        if isinstance(answer, str):
            user_bool = answer.lower() in ('true', '1', 'yes')
        else:
            user_bool = bool(answer)

        is_correct = user_bool == correct_bool

        return {
            'is_correct': is_correct,
            'correct_answer': 'True' if correct_bool else 'False',
            'explanation': content.get('explanation', ''),
            'user_answer': 'True' if user_bool else 'False'
        }
