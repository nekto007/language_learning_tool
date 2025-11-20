"""
Quiz Service - quiz generation and management

Responsibilities:
- Question generation (multiple choice, true/false, fill-in-blank)
- Quiz scoring
- Quiz result tracking
"""
from typing import List, Dict
import random

from app.utils.db import db
from app.words.models import CollectionWords


class QuizService:
    """Service for quiz operations"""

    QUESTION_TYPES = ['multiple_choice', 'true_false', 'fill_blank']

    @classmethod
    def generate_quiz_questions(cls, words: List[CollectionWords], count: int,
                                question_types: List[str] = None) -> List[Dict]:
        """
        Generate quiz questions from words

        Args:
            words: List of CollectionWords to generate questions from
            count: Number of questions to generate
            question_types: Types of questions to generate (default: all types)

        Returns:
            List of question dictionaries
        """
        if not question_types:
            question_types = cls.QUESTION_TYPES

        if not words or count <= 0:
            return []

        questions = []
        available_words = words.copy()

        for i in range(min(count, len(available_words))):
            # Select random word and question type
            word = random.choice(available_words)
            available_words.remove(word)
            q_type = random.choice(question_types)

            # Generate question based on type
            if q_type == 'multiple_choice':
                question = cls._generate_multiple_choice(word, words)
            elif q_type == 'true_false':
                question = cls._generate_true_false(word, words)
            else:  # fill_blank
                question = cls._generate_fill_blank(word)

            if question:
                questions.append(question)

        return questions

    @staticmethod
    def _generate_multiple_choice(word: CollectionWords, all_words: List[CollectionWords],
                                  direction: str = 'forward') -> Dict:
        """Generate multiple choice question"""
        # This is a simplified version - full implementation in routes.py
        if direction == 'forward':
            question_text = word.english_word
            correct_answer = word.russian_word
        else:
            question_text = word.russian_word
            correct_answer = word.english_word

        # Get wrong answers
        wrong_words = [w for w in all_words if w.id != word.id]
        wrong_answers = []
        for w in random.sample(wrong_words, min(3, len(wrong_words))):
            wrong_answers.append(w.russian_word if direction == 'forward' else w.english_word)

        # Combine and shuffle options
        options = [correct_answer] + wrong_answers
        random.shuffle(options)

        return {
            'type': 'multiple_choice',
            'word_id': word.id,
            'question': question_text,
            'options': options,
            'correct_answer': correct_answer,
            'direction': direction
        }

    @staticmethod
    def _generate_true_false(word: CollectionWords, all_words: List[CollectionWords],
                            direction: str = 'forward') -> Dict:
        """Generate true/false question"""
        is_true = random.choice([True, False])

        if direction == 'forward':
            question_word = word.english_word
            if is_true:
                translation = word.russian_word
            else:
                # Pick random wrong translation
                wrong_words = [w for w in all_words if w.id != word.id]
                if wrong_words:
                    translation = random.choice(wrong_words).russian_word
                else:
                    translation = word.russian_word
                    is_true = True
        else:
            question_word = word.russian_word
            if is_true:
                translation = word.english_word
            else:
                wrong_words = [w for w in all_words if w.id != word.id]
                if wrong_words:
                    translation = random.choice(wrong_words).english_word
                else:
                    translation = word.english_word
                    is_true = True

        return {
            'type': 'true_false',
            'word_id': word.id,
            'question': question_word,
            'translation': translation,
            'correct_answer': is_true,
            'direction': direction
        }

    @staticmethod
    def _generate_fill_blank(word: CollectionWords, direction: str = 'forward') -> Dict:
        """Generate fill-in-the-blank question"""
        if direction == 'forward':
            question = word.english_word
            answer = word.russian_word
        else:
            question = word.russian_word
            answer = word.english_word

        return {
            'type': 'fill_blank',
            'word_id': word.id,
            'question': f"Переведите: {question}",
            'correct_answer': answer,
            'direction': direction
        }

    @staticmethod
    def calculate_quiz_score(total_questions: int, correct_answers: int,
                            time_taken_seconds: int) -> Dict:
        """
        Calculate quiz score and XP

        Args:
            total_questions: Total number of questions
            correct_answers: Number of correct answers
            time_taken_seconds: Time taken in seconds

        Returns:
            Dictionary with score, percentage, and XP awarded
        """
        if total_questions == 0:
            return {'score': 0, 'percentage': 0, 'xp_awarded': 0}

        percentage = (correct_answers / total_questions) * 100

        # Base XP: 10 per correct answer
        base_xp = correct_answers * 10

        # Bonus for perfect score
        if correct_answers == total_questions:
            base_xp += 50

        # Time bonus (faster = more XP)
        avg_time_per_question = time_taken_seconds / total_questions
        if avg_time_per_question < 5:  # Very fast
            base_xp = int(base_xp * 1.5)
        elif avg_time_per_question < 10:  # Fast
            base_xp = int(base_xp * 1.2)

        return {
            'score': correct_answers,
            'total': total_questions,
            'percentage': round(percentage, 1),
            'xp_awarded': base_xp,
            'time_taken': time_taken_seconds
        }
