# app/grammar_lab/services/grader.py
"""
Exercise grader for Grammar Lab.

Grades different types of grammar exercises.
"""

from typing import Dict, Any, List
import re
import logging

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
            return grader_method(exercise, user_answer)
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
        # Remove punctuation at the end
        normalized = re.sub(r'[.!?]+$', '', normalized)
        return normalized

    def _grade_fill_blank(self, exercise: GrammarExercise, answer: str) -> Dict:
        """Grade fill-in-the-blank exercise"""
        content = exercise.content
        correct = self._normalize_answer(content.get('correct_answer', ''))
        alternatives = [self._normalize_answer(a) for a in content.get('alternatives', [])]
        user = self._normalize_answer(answer)

        is_correct = user == correct or user in alternatives

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
            correct_answer_text = options[correct_index] if 0 <= correct_index < len(options) else str(correct_value)
        elif isinstance(correct_value, str) and correct_value in options:
            correct_index = options.index(correct_value)
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

        # User sent index
        if correct_index is not None:
            is_correct = user_index == correct_index
        else:
            # Compare by text
            user_answer_text = options[user_index] if 0 <= user_index < len(options) else ''
            is_correct = self._normalize_answer(user_answer_text) == self._normalize_answer(correct_answer_text)

        user_answer_text = options[user_index] if 0 <= user_index < len(options) else str(answer)

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
        correct_word = self._normalize_answer(content.get('correct_answer', ''))
        full_correct = self._normalize_answer(content.get('full_correct', ''))
        alternatives = [self._normalize_answer(a) for a in content.get('alternatives', [])]
        user = self._normalize_answer(answer)

        # Check if user provided just the corrected word OR the full sentence
        is_correct = (
            user == correct_word or
            user in alternatives or
            (full_correct and user == full_correct)
        )

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
        alternatives = [self._normalize_answer(a) for a in content.get('alternatives', [])]
        user = self._normalize_answer(answer)

        is_correct = user == correct or user in alternatives

        return {
            'is_correct': is_correct,
            'correct_answer': content.get('correct_answer', ''),
            'explanation': content.get('explanation', ''),
            'user_answer': answer
        }

    def _grade_translation(self, exercise: GrammarExercise, answer: str) -> Dict:
        """Grade translation exercise"""
        content = exercise.content
        correct = self._normalize_answer(content.get('correct_answer', ''))
        # Check both 'alternatives' and 'acceptable_answers' fields
        alt_list = content.get('alternatives', []) or content.get('acceptable_answers', [])
        alternatives = [self._normalize_answer(a) for a in alt_list]
        user = self._normalize_answer(answer)

        is_correct = user == correct or user in alternatives

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

        # Normalize both to boolean
        if isinstance(correct, str):
            correct_bool = correct.lower() in ('true', '1', 'yes')
        else:
            correct_bool = bool(correct)

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
