"""
Tests for curriculum service layer
Тесты сервисного слоя модуля curriculum
"""
import pytest
from datetime import datetime, timedelta, UTC

from app.curriculum.service import (
    get_user_level_progress,
    get_user_active_lessons,
    get_next_lesson,
    complete_lesson,
    process_quiz_submission,
    process_matching_submission,
    process_final_test_submission,
    process_grammar_submission,
    normalize_text,
    get_lesson_statistics,
    calculate_user_curriculum_progress,
    get_cards_for_lesson,
    smart_shuffle_cards,
)
from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
from app.study.models import UserWord, UserCardDirection
from app.words.models import CollectionWords


class TestUserProgress:
    """Тесты функций прогресса пользователя"""

    def test_get_user_level_progress_empty(self, app, db_session, test_user, test_level):
        """Тест прогресса без завершенных уроков"""
        with app.app_context():
            progress = get_user_level_progress(test_user.id)

            assert test_level.id in progress
            assert progress[test_level.id]['total_lessons'] == 0
            assert progress[test_level.id]['completed_lessons'] == 0
            assert progress[test_level.id]['progress_percent'] == 0

    def test_get_user_level_progress_with_completed(self, app, db_session, test_user, test_level, test_module, test_lesson_vocabulary):
        """Тест прогресса с завершенными уроками"""
        with app.app_context():
            # Создаем прогресс для урока
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                score=100.0,
            )
            db_session.add(progress)
            db_session.commit()

            level_progress = get_user_level_progress(test_user.id)

            assert test_level.id in level_progress
            assert level_progress[test_level.id]['total_lessons'] == 1
            assert level_progress[test_level.id]['completed_lessons'] == 1
            assert level_progress[test_level.id]['progress_percent'] == 100

    def test_get_user_active_lessons_empty(self, app, db_session, test_user):
        """Тест активных уроков когда их нет"""
        with app.app_context():
            active_lessons = get_user_active_lessons(test_user.id)

            assert len(active_lessons) == 0

    def test_get_user_active_lessons_with_progress(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест активных уроков с прогрессом"""
        with app.app_context():
            # Создаем прогресс in_progress
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress',
                score=50.0,
                last_activity=datetime.now(UTC)
            )
            db_session.add(progress)
            db_session.commit()

            active_lessons = get_user_active_lessons(test_user.id, limit=5)

            assert len(active_lessons) > 0

    def test_calculate_user_curriculum_progress_empty(self, app, db_session, test_user):
        """Тест расчета общего прогресса без завершенных уроков"""
        with app.app_context():
            progress = calculate_user_curriculum_progress(test_user.id)

            # User has no completed lessons, but curriculum lessons exist in DB
            assert progress['completed_lessons'] == 0
            # Progress should be 0% for new user with no completions
            assert progress['progress_percent'] == 0
            # total_lessons may be > 0 if curriculum exists in test DB
            assert progress['total_lessons'] >= 0

    def test_calculate_user_curriculum_progress_with_data(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест расчета общего прогресса с данными"""
        with app.app_context():
            # Создаем завершенный прогресс
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                score=90.0
            )
            db_session.add(progress)
            db_session.commit()

            curriculum_progress = calculate_user_curriculum_progress(test_user.id)

            assert curriculum_progress['completed_lessons'] == 1
            assert curriculum_progress['avg_score'] == 90.0


class TestLessonCompletion:
    """Тесты завершения уроков"""

    def test_complete_lesson_first_time(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест первого завершения урока"""
        with app.app_context():
            result = complete_lesson(test_user.id, test_lesson_vocabulary.id, score=85.0)

            assert result is not None
            assert result.status == 'completed'
            assert result.score == 85.0
            assert len(result.attempts) == 1

            # Проверяем что прогресс создан в БД
            progress = LessonProgress.query.filter_by(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id
            ).first()

            assert progress is not None
            assert progress.status == 'completed'

    def test_complete_lesson_second_attempt(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест повторного завершения урока"""
        with app.app_context():
            # Первая попытка
            first_progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                score=60.0,
            )
            db_session.add(first_progress)
            db_session.commit()

            # Вторая попытка с лучшим результатом
            result = complete_lesson(test_user.id, test_lesson_vocabulary.id, score=90.0)

            assert len(result.attempts) == 2
            assert result.score == 90.0  # должен обновиться на лучший результат

    def test_get_next_lesson(self, app, db_session, test_module):
        """Тест получения следующего урока"""
        with app.app_context():
            # Создаем два урока
            lesson1 = Lessons(
                module_id=test_module.id,
                number=1,
                title='Lesson 1',
                type='vocabulary',
                order=0,
                content={}
            )
            lesson2 = Lessons(
                module_id=test_module.id,
                number=2,
                title='Lesson 2',
                type='quiz',
                order=1,
                content={}
            )
            db_session.add_all([lesson1, lesson2])
            db_session.commit()

            # Получаем следующий урок после lesson1
            next_lesson = get_next_lesson(lesson1.id)

            assert next_lesson is not None
            assert next_lesson.id == lesson2.id


class TestQuizProcessing:
    """Тесты обработки квизов"""

    def test_process_quiz_submission_all_correct(self, app, db_session):
        """Тест обработки квиза с правильными ответами"""
        with app.app_context():
            questions = [
                {
                    'type': 'multiple_choice',
                    'question': 'What is 2+2?',
                    'options': ['3', '4', '5'],
                    'correct': 1
                },
                {
                    'type': 'multiple_choice',
                    'question': 'What is 3+3?',
                    'options': ['5', '6', '7'],
                    'correct': 1
                }
            ]

            answers = {
                '0': 1,  # правильно
                '1': 1   # правильно
            }

            result = process_quiz_submission(questions, answers)

            assert result['total_questions'] == 2
            assert result['correct_answers'] == 2
            assert result['score'] == 100.0

    def test_process_quiz_submission_partial_correct(self, app, db_session):
        """Тест обработки квиза с частично правильными ответами"""
        with app.app_context():
            questions = [
                {
                    'type': 'multiple_choice',
                    'question': 'Q1',
                    'options': ['a', 'b', 'c'],
                    'correct': 0
                },
                {
                    'type': 'multiple_choice',
                    'question': 'Q2',
                    'options': ['a', 'b', 'c'],
                    'correct': 1
                }
            ]

            answers = {
                '0': 0,  # правильно
                '1': 2   # неправильно
            }

            result = process_quiz_submission(questions, answers)

            assert result['total_questions'] == 2
            assert result['correct_answers'] == 1
            assert result['score'] == 50.0

    def test_process_quiz_submission_translation(self, app, db_session):
        """Тест обработки translation вопросов"""
        with app.app_context():
            questions = [
                {
                    'type': 'translation',
                    'question': 'Hello',
                    'correct_answer': 'Привет'
                }
            ]

            answers = {
                '0': 'Привет'
            }

            result = process_quiz_submission(questions, answers)

            assert result['correct_answers'] == 1
            assert result['score'] == 100.0

    def test_process_quiz_submission_true_false(self, app, db_session):
        """Тест обработки true/false вопросов"""
        with app.app_context():
            questions = [
                {
                    'type': 'true_false',
                    'statement': 'The sky is blue',
                    'correct': True
                },
                {
                    'type': 'true_false',
                    'statement': 'The sun is cold',
                    'correct': False
                }
            ]

            answers = {
                '0': True,
                '1': False
            }

            result = process_quiz_submission(questions, answers)

            assert result['total_questions'] == 2
            assert result['correct_answers'] == 2
            assert result['score'] == 100.0


class TestMatchingProcessing:
    """Тесты обработки matching заданий"""

    def test_process_matching_submission_all_correct(self, app, db_session):
        """Тест matching с правильными ответами"""
        with app.app_context():
            pairs = [
                {'left': 'hello', 'right': 'привет'},
                {'left': 'goodbye', 'right': 'пока'}
            ]

            user_matches = {
                'hello': 'привет',
                'goodbye': 'пока'
            }

            result = process_matching_submission(pairs, user_matches)

            assert result['total_pairs'] == 2
            assert result['correct_matches'] == 2
            assert result['score'] == 100.0

    def test_process_matching_submission_partial(self, app, db_session):
        """Тест matching с частично правильными ответами"""
        with app.app_context():
            pairs = [
                {'left': 'hello', 'right': 'привет'},
                {'left': 'goodbye', 'right': 'пока'}
            ]

            user_matches = {
                'hello': 'привет',
                'goodbye': 'неправильно'
            }

            result = process_matching_submission(pairs, user_matches)

            assert result['total_pairs'] == 2
            assert result['correct_matches'] == 1
            assert result['score'] == 50.0


class TestFinalTestProcessing:
    """Тесты обработки финального теста"""

    def test_process_final_test_submission_all_correct(self, app, db_session):
        """Тест финального теста с правильными ответами"""
        with app.app_context():
            questions = [
                {
                    'type': 'multiple_choice',
                    'question': 'Q1',
                    'options': ['a', 'b', 'c'],
                    'correct': 0
                },
                {
                    'type': 'translation',
                    'question': 'Translate: hello',
                    'correct_answer': 'привет'
                }
            ]

            user_answers = {
                '0': 0,
                '1': 'привет'
            }

            result = process_final_test_submission(questions, user_answers)

            assert result['total_questions'] == 2
            assert result['correct_answers'] == 2
            assert result['score'] == 100.0
            assert result['passed'] is True

    def test_process_final_test_submission_failed(self, app, db_session):
        """Тест проваленного финального теста"""
        with app.app_context():
            questions = [
                {
                    'type': 'multiple_choice',
                    'question': 'Q1',
                    'options': ['a', 'b', 'c'],
                    'correct': 0
                },
                {
                    'type': 'multiple_choice',
                    'question': 'Q2',
                    'options': ['a', 'b', 'c'],
                    'correct': 1
                }
            ]

            user_answers = {
                '0': 1,  # неправильно
                '1': 2   # неправильно
            }

            result = process_final_test_submission(questions, user_answers)

            assert result['correct_answers'] == 0
            assert result['score'] == 0.0
            assert result['passed'] is False


class TestGrammarProcessing:
    """Тесты обработки грамматических упражнений"""

    def test_process_grammar_submission_fill_in_blank(self, app, db_session):
        """Тест fill_in_blank упражнений"""
        with app.app_context():
            exercises = [
                {
                    'type': 'fill_in_blank',
                    'sentence': 'I ___ a student',
                    'correct_answer': 'am'
                }
            ]

            answers = {
                '0': 'am'
            }

            result = process_grammar_submission(exercises, answers)

            assert result['total_exercises'] == 1
            assert result['correct_answers'] == 1
            assert result['score'] == 100.0

    def test_process_grammar_submission_multiple_choice(self, app, db_session):
        """Тест multiple_choice грамматических упражнений"""
        with app.app_context():
            exercises = [
                {
                    'type': 'multiple_choice',
                    'question': 'Choose correct form',
                    'options': ['am', 'is', 'are'],
                    'correct': 0
                }
            ]

            answers = {
                '0': 0
            }

            result = process_grammar_submission(exercises, answers)

            assert result['correct_answers'] == 1
            assert result['score'] == 100.0

    def test_process_grammar_submission_sentence_builder(self, app, db_session):
        """Тест sentence_builder упражнений"""
        with app.app_context():
            exercises = [
                {
                    'type': 'sentence_builder',
                    'words': ['I', 'am', 'student', 'a'],
                    'correct_order': ['I', 'am', 'a', 'student']
                }
            ]

            answers = {
                '0': ['I', 'am', 'a', 'student']
            }

            result = process_grammar_submission(exercises, answers)

            assert result['correct_answers'] == 1
            assert result['score'] == 100.0

    def test_process_grammar_submission_error_correction(self, app, db_session):
        """Тест error_correction упражнений"""
        with app.app_context():
            exercises = [
                {
                    'type': 'error_correction',
                    'incorrect_sentence': 'I is a student',
                    'correct_sentence': 'I am a student'
                }
            ]

            answers = {
                '0': 'I am a student'
            }

            result = process_grammar_submission(exercises, answers)

            assert result['correct_answers'] == 1
            assert result['score'] == 100.0

    def test_process_grammar_submission_reorder(self, app, db_session):
        """Тест reorder упражнений"""
        with app.app_context():
            exercises = [
                {
                    'type': 'reorder',
                    'answer': 'I am a student'
                }
            ]

            answers = {
                '0': 'I am a student'
            }

            result = process_grammar_submission(exercises, answers)

            assert result['correct_answers'] == 1
            assert result['score'] == 100.0

    def test_process_grammar_submission_reorder_case_insensitive(self, app, db_session):
        """Тест reorder с разным регистром"""
        with app.app_context():
            exercises = [
                {
                    'type': 'reorder',
                    'answer': 'I am a student'
                }
            ]

            answers = {
                '0': 'i am a student'  # lowercase
            }

            result = process_grammar_submission(exercises, answers)

            assert result['correct_answers'] == 1
            assert result['score'] == 100.0

    def test_process_grammar_submission_match(self, app, db_session):
        """Тест match упражнений"""
        with app.app_context():
            exercises = [
                {
                    'type': 'match',
                    'pairs': [
                        {'left': 'hello', 'right': 'привет'},
                        {'left': 'goodbye', 'right': 'пока'}
                    ]
                }
            ]

            # Match type expects indices, not values
            # '0': '0' means pair[0].left matches pair[0].right
            answers = {
                '0': {'0': '0', '1': '1'}
            }

            result = process_grammar_submission(exercises, answers)

            assert result['correct_answers'] == 1
            assert result['score'] == 100.0


class TestTextNormalization:
    """Тесты нормализации текста"""

    def test_normalize_text_basic(self, app, db_session):
        """Тест базовой нормализации"""
        with app.app_context():
            assert normalize_text('Hello') == 'hello'
            assert normalize_text('  Hello  ') == 'hello'
            assert normalize_text('HELLO') == 'hello'

    def test_normalize_text_punctuation(self, app, db_session):
        """Тест нормализации с пунктуацией"""
        with app.app_context():
            assert normalize_text('Hello!') == 'hello'
            assert normalize_text('Hello.') == 'hello'
            assert normalize_text('Hello,') == 'hello'

    def test_normalize_text_multiple_spaces(self, app, db_session):
        """Тест нормализации множественных пробелов"""
        with app.app_context():
            assert normalize_text('Hello  World') == 'hello world'
            assert normalize_text('Hello   World') == 'hello world'


class TestLessonStatistics:
    """Тесты статистики уроков"""

    def test_get_lesson_statistics_empty(self, app, db_session):
        """Тест статистики без данных"""
        with app.app_context():
            stats = get_lesson_statistics()

            assert 'total_lessons' in stats
            assert 'by_type' in stats
            assert 'by_module' in stats

    def test_get_lesson_statistics_with_data(self, app, db_session, test_module, test_lesson_vocabulary, test_lesson_quiz):
        """Тест статистики с данными"""
        with app.app_context():
            stats = get_lesson_statistics()

            assert stats['total_lessons'] >= 2
            assert 'vocabulary' in stats['by_type']
            assert 'quiz' in stats['by_type']


class TestCardFunctions:
    """Тесты функций для карточек"""

    def test_smart_shuffle_cards_empty(self, app, db_session):
        """Тест перемешивания пустого списка карточек"""
        with app.app_context():
            result = smart_shuffle_cards([])
            assert result == []

    def test_smart_shuffle_cards_single(self, app, db_session):
        """Тест перемешивания одной карточки"""
        with app.app_context():
            cards = [{'id': 1, 'word': 'test'}]
            result = smart_shuffle_cards(cards)
            assert len(result) == 1
            assert result[0]['id'] == 1

    def test_smart_shuffle_cards_multiple(self, app, db_session):
        """Тест перемешивания нескольких карточек"""
        with app.app_context():
            cards = [
                {'id': 1, 'word': 'test1'},
                {'id': 2, 'word': 'test2'},
                {'id': 3, 'word': 'test3'}
            ]
            result = smart_shuffle_cards(cards)
            assert len(result) == 3
            # Проверяем что все карточки присутствуют
            result_ids = [card['id'] for card in result]
            assert set(result_ids) == {1, 2, 3}


class TestEdgeCases:
    """Тесты граничных случаев и обработки ошибок"""

    def test_complete_lesson_invalid_user(self, app, db_session, test_lesson_vocabulary):
        """Тест завершения урока несуществующим пользователем"""
        with app.app_context():
            # Используем несуществующий user_id
            result = complete_lesson(999999, test_lesson_vocabulary.id, score=100.0)

            # Функция должна вернуть None из-за нарушения foreign key constraint
            # (проверка существования пользователя должна быть на уровне routes)
            assert result is None

    def test_complete_lesson_invalid_lesson(self, app, db_session, test_user):
        """Тест завершения несуществующего урока"""
        with app.app_context():
            # Используем несуществующий lesson_id
            result = complete_lesson(test_user.id, 999999, score=100.0)

            # Функция должна вернуть None из-за нарушения foreign key constraint
            # (проверка существования урока должна быть на уровне routes)
            assert result is None

    def test_process_quiz_empty_questions(self, app, db_session):
        """Тест обработки квиза без вопросов"""
        with app.app_context():
            result = process_quiz_submission([], {})

            assert result['total_questions'] == 0
            assert result['correct_answers'] == 0
            assert result['score'] == 0.0

    def test_process_quiz_empty_answers(self, app, db_session):
        """Тест обработки квиза без ответов"""
        with app.app_context():
            questions = [
                {
                    'type': 'multiple_choice',
                    'question': 'Q1',
                    'options': ['a', 'b'],
                    'correct': 0
                }
            ]

            result = process_quiz_submission(questions, {})

            assert result['total_questions'] == 1
            assert result['correct_answers'] == 0
            assert result['score'] == 0.0

    def test_normalize_text_empty(self, app, db_session):
        """Тест нормализации пустой строки"""
        with app.app_context():
            assert normalize_text('') == ''
            assert normalize_text('   ') == ''

    def test_normalize_text_none(self, app, db_session):
        """Тест нормализации None"""
        with app.app_context():
            # normalize_text должна обрабатывать None
            result = normalize_text(None)
            assert result == '' or result is None

    def test_get_next_lesson_invalid_id(self, app, db_session):
        """Тест get_next_lesson с несуществующим lesson_id"""
        with app.app_context():
            result = get_next_lesson(99999)
            assert result is None

    def test_get_next_lesson_by_number_fallback(self, app, db_session, test_module):
        """Тест get_next_lesson fallback к number когда order не работает"""
        with app.app_context():
            # Создаем уроки с number но без order
            lesson1 = Lessons(
                module_id=test_module.id,
                number=1,
                title='Lesson 1',
                type='vocabulary',
                order=None,  # Без order
                content={'words': []}
            )
            lesson2 = Lessons(
                module_id=test_module.id,
                number=2,
                title='Lesson 2',
                type='vocabulary',
                order=None,  # Без order
                content={'words': []}
            )
            db_session.add_all([lesson1, lesson2])
            db_session.commit()

            result = get_next_lesson(lesson1.id)
            assert result is not None
            assert result.id == lesson2.id

    def test_get_user_level_progress_with_multiple_modules(self, app, db_session, test_user, test_level):
        """Тест прогресса с несколькими модулями"""
        with app.app_context():
            # Создаем несколько модулей
            module1 = Module(
                level_id=test_level.id,
                number=1,
                title='Module 1',
                raw_content={}
            )
            module2 = Module(
                level_id=test_level.id,
                number=2,
                title='Module 2',
                raw_content={}
            )
            db_session.add_all([module1, module2])
            db_session.commit()

            # Добавляем уроки
            lesson1 = Lessons(
                module_id=module1.id,
                number=1,
                title='Lesson 1',
                type='vocabulary',
                order=0,
                content={'words': []}
            )
            lesson2 = Lessons(
                module_id=module2.id,
                number=1,
                title='Lesson 2',
                type='vocabulary',
                order=0,
                content={'words': []}
            )
            db_session.add_all([lesson1, lesson2])
            db_session.commit()

            # Завершаем первый урок
            complete_lesson(test_user.id, lesson1.id, 90.0)

            result = get_user_level_progress(test_user.id)
            assert len(result) > 0

    def test_process_matching_empty_pairs(self, app, db_session):
        """Тест matching с пустым списком пар"""
        with app.app_context():
            pairs = []
            user_matches = {}

            results = process_matching_submission(pairs, user_matches)
            assert results['correct_matches'] == 0
            assert results['total_pairs'] == 0
            assert results['score'] == 0