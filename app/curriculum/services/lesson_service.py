# app/curriculum/services/lesson_service.py

import logging
from datetime import UTC, datetime
from typing import Dict, List

from app.curriculum.models import Lessons
from app.study.models import UserWord
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


class LessonService:
    """Service for processing different lesson types"""

    @staticmethod
    def process_quiz_submission(
            lesson: Lessons,
            user_id: int,
            answers: Dict[int, int]
    ) -> Dict:
        """
        Process quiz submission and calculate score
        
        Args:
            lesson: Quiz lesson
            user_id: User ID
            answers: Dictionary of question_index -> selected_option_index
            
        Returns:
            Result dictionary with score and feedback
        """
        try:
            if lesson.type != 'quiz':
                raise ValueError("Not a quiz lesson")

            questions = lesson.content.get('questions', [])
            correct_count = 0
            total_count = len(questions)
            feedback = {}

            for idx, question in enumerate(questions):
                user_answer = answers.get(idx)
                correct_answer = question.get('correct')

                if user_answer == correct_answer:
                    correct_count += 1
                    feedback[idx] = {
                        'correct': True,
                        'user_answer': user_answer,
                        'correct_answer': correct_answer
                    }
                else:
                    feedback[idx] = {
                        'correct': False,
                        'user_answer': user_answer,
                        'correct_answer': correct_answer,
                        'explanation': question.get('explanation', '')
                    }

            score = round((correct_count / total_count * 100) if total_count > 0 else 0)
            completed = score >= lesson.content.get('passing_score', 70)

            # Update progress
            from app.curriculum.services.progress_service import ProgressService
            progress = ProgressService.create_or_update_progress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed' if completed else 'in_progress',
                score=score,
                data={
                    'answers': answers,
                    'feedback': feedback,
                    'attempt_at': datetime.now(UTC).isoformat()
                }
            )

            return {
                'success': True,
                'score': score,
                'correct_count': correct_count,
                'total_count': total_count,
                'completed': completed,
                'feedback': feedback
            }

        except Exception as e:
            logger.error(f"Error processing quiz submission: {str(e)}")
            return {
                'success': False,
                'error': 'Failed to process quiz submission'
            }

    @staticmethod
    def process_grammar_submission(
            lesson: Lessons,
            user_id: int,
            answers: Dict[int, str]
    ) -> Dict:
        """
        Process grammar exercise submission
        
        Args:
            lesson: Grammar lesson
            user_id: User ID
            answers: Dictionary of exercise_index -> user_answer
            
        Returns:
            Result dictionary with score and feedback
        """
        try:
            if lesson.type != 'grammar':
                raise ValueError("Not a grammar lesson")

            exercises = lesson.content.get('exercises', [])
            correct_count = 0
            total_count = len(exercises)
            feedback = {}

            for idx, exercise in enumerate(exercises):
                user_answer = answers.get(idx, '').strip().lower()
                correct_answer = exercise.get('answer', exercise.get('correct_answer', '')).strip().lower()

                # For fill-in-the-blank, check exact match
                if exercise.get('type') == 'fill_blank':
                    is_correct = user_answer == correct_answer
                else:
                    # For other types, allow some flexibility
                    is_correct = user_answer == correct_answer

                if is_correct:
                    correct_count += 1

                feedback[idx] = {
                    'correct': is_correct,
                    'user_answer': answers.get(idx, ''),
                    'correct_answer': exercise.get('answer', exercise.get('correct_answer', ''))
                }

            score = round((correct_count / total_count * 100) if total_count > 0 else 0)
            completed = score >= 70  # 70% passing score for grammar

            # Update progress
            from app.curriculum.services.progress_service import ProgressService
            progress = ProgressService.create_or_update_progress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed' if completed else 'in_progress',
                score=score,
                data={
                    'answers': answers,
                    'feedback': feedback,
                    'attempt_at': datetime.now(UTC).isoformat()
                }
            )

            return {
                'success': True,
                'score': score,
                'correct_count': correct_count,
                'total_count': total_count,
                'completed': completed,
                'feedback': feedback
            }

        except Exception as e:
            logger.error(f"Error processing grammar submission: {str(e)}")
            return {
                'success': False,
                'error': 'Failed to process grammar submission'
            }

    @staticmethod
    def process_matching_submission(
            lesson: Lessons,
            user_id: int,
            matches: List[Dict[str, int]]
    ) -> Dict:
        """
        Process matching exercise submission
        
        Args:
            lesson: Matching lesson
            user_id: User ID
            matches: List of match dictionaries with left_index and right_index
            
        Returns:
            Result dictionary with score and feedback
        """
        try:
            if lesson.type != 'matching':
                raise ValueError("Not a matching lesson")

            pairs = lesson.content.get('pairs', [])
            correct_count = 0
            total_count = len(pairs)

            # Create correct mapping
            correct_mapping = {i: i for i in range(len(pairs))}

            # Check user matches
            user_mapping = {}
            for match in matches:
                left_idx = match.get('left_index')
                right_idx = match.get('right_index')
                if left_idx is not None and right_idx is not None:
                    user_mapping[left_idx] = right_idx

            # Calculate correct matches
            for left_idx, right_idx in user_mapping.items():
                if correct_mapping.get(left_idx) == right_idx:
                    correct_count += 1

            score = round((correct_count / total_count * 100) if total_count > 0 else 0)
            completed = score >= 80  # 80% passing score for matching

            # Update progress
            from app.curriculum.services.progress_service import ProgressService
            progress = ProgressService.create_or_update_progress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed' if completed else 'in_progress',
                score=score,
                data={
                    'matches': matches,
                    'correct_count': correct_count,
                    'total_count': total_count,
                    'attempt_at': datetime.now(UTC).isoformat()
                }
            )

            return {
                'success': True,
                'score': score,
                'correct_count': correct_count,
                'total_count': total_count,
                'completed': completed
            }

        except Exception as e:
            logger.error(f"Error processing matching submission: {str(e)}")
            return {
                'success': False,
                'error': 'Failed to process matching submission'
            }

    @staticmethod
    def get_vocabulary_words(lesson: Lessons, user_id: int) -> List[Dict]:
        """
        Get vocabulary words for a lesson with user progress
        
        Args:
            lesson: Vocabulary lesson
            user_id: User ID
            
        Returns:
            List of word dictionaries with user status
        """
        try:
            words = []

            # Handle different content structures
            if isinstance(lesson.content, dict):
                word_list = lesson.content.get('words', lesson.content.get('items', []))
            elif isinstance(lesson.content, list):
                word_list = lesson.content
            else:
                word_list = []

            for word_data in word_list:
                # Get word from database
                english_word = word_data.get('front', word_data.get('word', ''))
                if english_word:
                    word = CollectionWords.query.filter_by(
                        english_word=english_word
                    ).first()

                    if word:
                        # Get user's learning status
                        user_word = UserWord.query.filter_by(
                            user_id=user_id,
                            word_id=word.id
                        ).first()

                        words.append({
                            'id': word.id,
                            'english': word.english_word,
                            'russian': word.russian_word,
                            'example': word_data.get('example', ''),
                            'hint': word_data.get('hint', ''),
                            'status': user_word.status if user_word else 'new',
                            'audio_url': word.audio_url if hasattr(word, 'audio_url') else None,
                            'level': word.level
                        })

            return words

        except Exception as e:
            logger.error(f"Error getting vocabulary words: {str(e)}")
            return []

    @staticmethod
    def process_final_test_submission(
            lesson: Lessons,
            user_id: int,
            data: Dict
    ) -> Dict:
        """
        Process final test submission (comprehensive test)
        
        Args:
            lesson: Final test lesson
            user_id: User ID
            data: Test submission data
            
        Returns:
            Result dictionary with score and completion status
        """
        try:
            # Final tests can combine multiple question types
            total_score = 0
            total_possible = 0
            section_results = {}

            # Process different sections
            if 'quiz_answers' in data:
                quiz_questions = lesson.content.get('quiz_questions', [])
                quiz_result = LessonService._process_quiz_section(
                    quiz_questions,
                    data['quiz_answers']
                )
                section_results['quiz'] = quiz_result
                total_score += quiz_result['score'] * quiz_result['weight']
                total_possible += quiz_result['weight']

            if 'grammar_answers' in data:
                grammar_exercises = lesson.content.get('grammar_exercises', [])
                grammar_result = LessonService._process_grammar_section(
                    grammar_exercises,
                    data['grammar_answers']
                )
                section_results['grammar'] = grammar_result
                total_score += grammar_result['score'] * grammar_result['weight']
                total_possible += grammar_result['weight']

            # Calculate overall score
            final_score = round((total_score / total_possible) if total_possible > 0 else 0)
            completed = final_score >= lesson.content.get('passing_score', 70)

            # Update progress
            from app.curriculum.services.progress_service import ProgressService
            progress = ProgressService.create_or_update_progress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed' if completed else 'in_progress',
                score=final_score,
                data={
                    'section_results': section_results,
                    'attempt_at': datetime.now(UTC).isoformat()
                }
            )

            return {
                'success': True,
                'score': final_score,
                'completed': completed,
                'section_results': section_results
            }

        except Exception as e:
            logger.error(f"Error processing final test: {str(e)}")
            return {
                'success': False,
                'error': 'Failed to process final test'
            }

    @staticmethod
    def _process_quiz_section(questions: List[Dict], answers: Dict[int, int]) -> Dict:
        """Helper method to process quiz section"""
        correct_count = 0
        total_count = len(questions)

        for idx, question in enumerate(questions):
            if answers.get(idx) == question.get('correct'):
                correct_count += 1

        score = round((correct_count / total_count * 100) if total_count > 0 else 0)

        return {
            'score': score,
            'correct_count': correct_count,
            'total_count': total_count,
            'weight': 1.0  # Default weight
        }

    @staticmethod
    def _process_grammar_section(exercises: List[Dict], answers: Dict[int, str]) -> Dict:
        """Helper method to process grammar section"""
        correct_count = 0
        total_count = len(exercises)

        for idx, exercise in enumerate(exercises):
            user_answer = answers.get(idx, '').strip().lower()
            correct_answer = exercise.get('answer', '').strip().lower()

            if user_answer == correct_answer:
                correct_count += 1

        score = round((correct_count / total_count * 100) if total_count > 0 else 0)

        return {
            'score': score,
            'correct_count': correct_count,
            'total_count': total_count,
            'weight': 1.0  # Default weight
        }
