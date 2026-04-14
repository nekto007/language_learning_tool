"""
Tests for curriculum lessons content validation.
Validates that all lessons can be loaded without errors.
"""
import pytest
from app import create_app
from app.curriculum.models import Lessons
from app.curriculum.validators import LessonContentValidator


class TestAllLessonsValidation:
    """Test that all lessons in database have valid content"""

    @pytest.fixture(autouse=True)
    def setup(self, app):
        """Setup test fixtures"""
        self.app = app

    def test_all_lessons_have_valid_content(self, app):
        """Check that all lessons pass content validation"""
        with app.app_context():
            lessons = Lessons.query.all()
            errors = []

            for lesson in lessons:
                if not lesson.content:
                    # Skip lessons without content
                    continue

                try:
                    is_valid, error_msg, cleaned = LessonContentValidator.validate(
                        lesson.type, lesson.content
                    )
                    if not is_valid:
                        errors.append({
                            'lesson_id': lesson.id,
                            'title': lesson.title,
                            'type': lesson.type,
                            'error': error_msg
                        })
                except ValueError as e:
                    # Skip unknown lesson types
                    if "Unknown lesson type" in str(e):
                        continue
                    errors.append({
                        'lesson_id': lesson.id,
                        'title': lesson.title,
                        'type': lesson.type,
                        'error': str(e)
                    })
                except Exception as e:
                    errors.append({
                        'lesson_id': lesson.id,
                        'title': lesson.title,
                        'type': lesson.type,
                        'error': str(e)
                    })

            if errors:
                error_report = "\n".join([
                    f"Lesson {e['lesson_id']} ({e['type']}): {e['title']}\n  Error: {e['error']}"
                    for e in errors
                ])
                pytest.fail(f"Found {len(errors)} lessons with invalid content:\n{error_report}")

    def test_all_lessons_by_type(self, app):
        """Check lessons grouped by type"""
        with app.app_context():
            lessons = Lessons.query.all()

            by_type = {}
            for lesson in lessons:
                if lesson.type not in by_type:
                    by_type[lesson.type] = {'total': 0, 'valid': 0, 'invalid': []}
                by_type[lesson.type]['total'] += 1

                if not lesson.content:
                    by_type[lesson.type]['valid'] += 1
                    continue

                try:
                    is_valid, error_msg, _ = LessonContentValidator.validate(
                        lesson.type, lesson.content
                    )
                    if is_valid:
                        by_type[lesson.type]['valid'] += 1
                    else:
                        by_type[lesson.type]['invalid'].append({
                            'id': lesson.id,
                            'title': lesson.title,
                            'error': error_msg
                        })
                except Exception as e:
                    by_type[lesson.type]['invalid'].append({
                        'id': lesson.id,
                        'title': lesson.title,
                        'error': str(e)
                    })

            # Print summary
            print("\n=== Lessons Validation Summary ===")
            total_invalid = 0
            for lesson_type, stats in sorted(by_type.items()):
                invalid_count = len(stats['invalid'])
                total_invalid += invalid_count
                status = "✓" if invalid_count == 0 else "✗"
                print(f"{status} {lesson_type}: {stats['valid']}/{stats['total']} valid")

                if stats['invalid']:
                    for inv in stats['invalid'][:3]:  # Show first 3 errors per type
                        print(f"    - ID {inv['id']}: {inv['error'][:100]}")
                    if len(stats['invalid']) > 3:
                        print(f"    ... and {len(stats['invalid']) - 3} more")

            assert total_invalid == 0, f"Found {total_invalid} invalid lessons"


class TestSpecificLessonTypes:
    """Test specific lesson types"""

    def test_grammar_lessons(self, app):
        """Test all grammar lessons"""
        with app.app_context():
            lessons = Lessons.query.filter_by(type='grammar').all()

            for lesson in lessons:
                if not lesson.content:
                    continue

                is_valid, error_msg, _ = LessonContentValidator.validate('grammar', lesson.content)
                assert is_valid, f"Grammar lesson {lesson.id} ({lesson.title}): {error_msg}"

    def test_quiz_lessons(self, app):
        """Test all quiz lessons"""
        with app.app_context():
            quiz_types = ['quiz', 'ordering_quiz', 'translation_quiz',
                         'listening_quiz', 'dialogue_completion_quiz']
            lessons = Lessons.query.filter(Lessons.type.in_(quiz_types)).all()

            for lesson in lessons:
                if not lesson.content:
                    continue

                is_valid, error_msg, _ = LessonContentValidator.validate('quiz', lesson.content)
                assert is_valid, f"Quiz lesson {lesson.id} ({lesson.title}): {error_msg}"

    def test_card_lessons(self, app):
        """Test all card/flashcard lessons"""
        with app.app_context():
            lessons = Lessons.query.filter(Lessons.type.in_(['card', 'flashcards'])).all()

            for lesson in lessons:
                if not lesson.content:
                    continue

                is_valid, error_msg, _ = LessonContentValidator.validate('card', lesson.content)
                assert is_valid, f"Card lesson {lesson.id} ({lesson.title}): {error_msg}"

    def test_vocabulary_lessons(self, app):
        """Test all vocabulary lessons"""
        with app.app_context():
            lessons = Lessons.query.filter_by(type='vocabulary').all()

            for lesson in lessons:
                if not lesson.content:
                    continue

                is_valid, error_msg, _ = LessonContentValidator.validate('vocabulary', lesson.content)
                assert is_valid, f"Vocabulary lesson {lesson.id} ({lesson.title}): {error_msg}"

    def test_text_lessons(self, app):
        """Test all text/reading lessons"""
        with app.app_context():
            lessons = Lessons.query.filter(Lessons.type.in_(['text', 'reading'])).all()

            for lesson in lessons:
                if not lesson.content:
                    continue

                is_valid, error_msg, _ = LessonContentValidator.validate('text', lesson.content)
                assert is_valid, f"Text lesson {lesson.id} ({lesson.title}): {error_msg}"
