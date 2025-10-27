"""
Book Course Generator

This module integrates the existing task generation system with the Book Courses system,
allowing any book to be converted into a complete course with lessons and tasks.
"""

import logging
from typing import Any, Dict, List, Optional

from app.books.models import Block, BlockVocab, Book, Task
from app.curriculum.book_courses import BookCourse, BookCourseModule
from app.curriculum.services.block_schema_importer import BlockSchemaImporter
from app.curriculum.services.daily_slice_generator import DailySliceGenerator
from app.curriculum.services.vocabulary_extractor import VocabularyExtractor
from app.utils.db import db

logger = logging.getLogger(__name__)


class BookCourseGenerator:
    """Generates complete courses from books"""

    def __init__(self, book_id: int):
        self.book_id = book_id
        self.book = Book.query.get_or_404(book_id)

    def create_course_from_book(
            self,
            course_title: str,
            course_description: str,
            level: str,
            schema_data: Optional[List[Dict]] = None,
            generate_tasks: bool = True
    ) -> Optional[BookCourse]:
        """Create a complete course from a book"""

        try:
            logger.info(f"Starting course creation for book: {self.book.title}")

            # Step 1: Create the course
            course = self._create_book_course(course_title, course_description, level)
            if not course:
                return None

            # Step 2: Import or generate block schema
            if not self._setup_blocks(schema_data):
                db.session.rollback()
                return None

            # Step 3: Extract vocabulary for blocks
            if not self._extract_vocabulary():
                logger.warning("Vocabulary extraction failed, but continuing...")

            # Step 4: Generate tasks for blocks
            if generate_tasks and not self._generate_tasks():
                logger.warning("Task generation failed, but continuing...")

            # Step 5: Create course modules from blocks
            if not self._create_course_modules(course.id):
                db.session.rollback()
                return None

            # Step 6: Generate daily slices for all modules
            if not self._generate_daily_slices(course.id):
                logger.warning("Daily slice generation failed, but continuing...")

            db.session.commit()
            logger.info(f"Successfully created course: {course.title}")
            return course

        except Exception as e:
            logger.error(f"Error creating course from book {self.book_id}: {str(e)}")
            db.session.rollback()
            return None

    def _create_book_course(self, title: str, description: str, level: str) -> Optional[BookCourse]:
        """Create the BookCourse record"""
        try:
            course = BookCourse(
                book_id=self.book_id,
                title=title,
                description=description,
                level=level,
                difficulty_score=self._calculate_difficulty_score(),
                estimated_duration_weeks=self._estimate_duration(),
                author_info=self._extract_author_info(),
                literary_themes=self._extract_themes(),
                language_features=self._extract_language_features(),
                is_active=True,
                is_featured=False
            )

            db.session.add(course)
            db.session.flush()

            logger.info(f"Created course: {course.title} (ID: {course.id})")
            return course

        except Exception as e:
            logger.error(f"Error creating course: {str(e)}")
            return None

    def _setup_blocks(self, schema_data: Optional[List[Dict]]) -> bool:
        """Setup blocks for the book using schema or defaults"""
        try:
            # Check if blocks already exist
            existing_blocks = Block.query.filter_by(book_id=self.book_id).count()
            if existing_blocks > 0:
                logger.info(f"Using existing {existing_blocks} blocks for book {self.book_id}")
                return True

            importer = BlockSchemaImporter(self.book_id)

            if schema_data:
                # Use provided schema
                success = importer.import_from_data(schema_data)
            else:
                # Generate default schema
                default_schema = importer.generate_default_schema()
                success = importer.import_from_data(default_schema)

            if success:
                block_count = Block.query.filter_by(book_id=self.book_id).count()
                logger.info(f"Setup {block_count} blocks for book {self.book_id}")
                return True
            else:
                logger.error("Failed to setup blocks")
                return False

        except Exception as e:
            logger.error(f"Error setting up blocks: {str(e)}")
            return False

    def _extract_vocabulary(self) -> bool:
        """Extract vocabulary for all blocks"""
        try:
            # Check if vocabulary already exists
            existing_vocab = BlockVocab.query.join(Block).filter(Block.book_id == self.book_id).count()
            if existing_vocab > 0:
                logger.info(f"Using existing vocabulary ({existing_vocab} entries) for book {self.book_id}")
                return True

            extractor = VocabularyExtractor(self.book_id)
            return extractor.extract_vocabulary_for_all_blocks(max_words_per_block=20)

        except Exception as e:
            logger.error(f"Error extracting vocabulary: {str(e)}")
            return False

    def _generate_tasks(self) -> bool:
        """Generate all task types for all blocks according to specification"""
        try:
            # Get all blocks for this book
            blocks = Block.query.filter_by(book_id=self.book_id).order_by(Block.block_num).all()

            if not blocks:
                logger.warning("No blocks found for task generation")
                return False

            success_count = 0

            # Import task generators
            from app.curriculum.services.task_generators import generate_all_task_types

            # Generate tasks for each block
            for block in blocks:
                try:
                    logger.info(f"Generating tasks for block {block.block_num}")

                    # Check if tasks already exist
                    existing_tasks = Task.query.filter_by(block_id=block.id).count()
                    if existing_tasks > 0:
                        logger.info(f"Block {block.block_num} already has {existing_tasks} tasks, skipping generation")
                        success_count += 1
                        continue

                    # Generate all task types for this block
                    generated_tasks = generate_all_task_types(block)

                    if generated_tasks:
                        success_count += 1
                        logger.info(f"Generated {len(generated_tasks)} tasks for block {block.block_num}")
                    else:
                        logger.warning(f"No tasks generated for block {block.block_num}")

                except Exception as e:
                    logger.error(f"Error generating tasks for block {block.block_num}: {str(e)}")

            logger.info(f"Generated tasks for {success_count}/{len(blocks)} blocks")
            return success_count > 0

        except Exception as e:
            logger.error(f"Error in task generation: {str(e)}")
            return False

    def _create_course_modules(self, course_id: int) -> bool:
        """Create BookCourseModule records from blocks"""
        try:
            blocks = Block.query.filter_by(book_id=self.book_id).order_by(Block.block_num).all()

            for block in blocks:
                # Count chapters in this block
                chapter_count = len(block.chapters)

                # Get tasks for this block (for legacy compatibility)
                tasks = Task.query.filter_by(block_id=block.id).all()

                # Create placeholder lessons data - will be replaced by daily slices
                lessons_data = {'lessons': [], 'total_lessons': 0}

                # Create the module
                module = BookCourseModule(
                    course_id=course_id,
                    block_id=block.id,  # Add block reference
                    module_number=block.block_num,
                    title=f"Block {block.block_num}",
                    description=f"Chapters {chapter_count} chapters focusing on {block.focus_vocab or 'general vocabulary'}",
                    estimated_reading_time=self._estimate_reading_time(block),
                    learning_objectives=self._create_learning_objectives(block),
                    vocabulary_focus=self._get_block_vocabulary(block.id),
                    grammar_focus=[block.grammar_key] if block.grammar_key else [],
                    literary_elements=[],
                    lessons_data=lessons_data,
                    difficulty_level=self._get_course_level(course_id),
                    order_index=block.block_num,
                    is_locked=block.block_num > 1  # Lock all except first block
                )

                db.session.add(module)
                db.session.flush()  # Get module ID for daily slice generation

                # Store block reference for daily slice generation
                module.block = block

            # Update course total_modules count
            course = BookCourse.query.get(course_id)
            course.total_modules = len(blocks)

            logger.info(f"Created {len(blocks)} modules for course {course_id}")
            return True

        except Exception as e:
            logger.error(f"Error creating course modules: {str(e)}")
            return False

    def _create_lessons_from_tasks(self, tasks: List[Task]) -> Dict[str, Any]:
        """Convert tasks to lessons data structure according to specification"""
        lessons = []
        lesson_number = 1

        # Complete lesson plan according to technical specification
        # 10 lesson types per block as specified in the document
        lesson_plan = [
            {
                'type': 'vocabulary',
                'title': 'Vocabulary Practice',
                'description': 'Study key vocabulary words (20 cards)',
                'estimated_time': 15
            },
            {
                'type': 'reading_passage',
                'title': 'Reading Passage',
                'description': 'Read the main text passage (650-750 words)',
                'estimated_time': 20
            },
            {
                'type': 'reading_mcq',
                'title': 'Reading Comprehension',
                'description': 'Answer multiple choice questions about the text (10 questions)',
                'estimated_time': 15
            },
            {
                'type': 'match_headings',
                'title': 'Match Headings',
                'description': 'Match paragraphs with appropriate headings (6 paragraphs → 8 headings)',
                'estimated_time': 10
            },
            {
                'type': 'open_cloze',
                'title': 'Open Cloze Test',
                'description': 'Fill in missing words in the text (8 gaps)',
                'estimated_time': 12
            },
            {
                'type': 'word_formation',
                'title': 'Word Formation',
                'description': 'Transform words into correct forms (8 items)',
                'estimated_time': 10
            },
            {
                'type': 'keyword_transform',
                'title': 'Key Word Transformations',
                'description': 'Rewrite sentences using given key words (6 sentences)',
                'estimated_time': 12
            },
            {
                'type': 'grammar_sheet',
                'title': 'Grammar Focus',
                'description': 'Grammar lesson with explanations and practice (4-5 questions)',
                'estimated_time': 18
            },
            {
                'type': 'text',
                'title': 'Literary Analysis',
                'description': 'Analyze literary elements and themes',
                'estimated_time': 15
            },
            {
                'type': 'final_test',
                'title': 'Module Test',
                'description': 'Comprehensive test covering all material (32-36 questions)',
                'estimated_time': 25
            }
        ]

        # Create lessons using existing tasks where available, generate placeholders otherwise
        task_by_type = {task.task_type: task for task in tasks}

        for lesson_info in lesson_plan:
            task = task_by_type.get(lesson_info['type'])

            lesson = {
                'lesson_number': lesson_number,
                'type': lesson_info['type'],
                'title': lesson_info['title'],
                'description': lesson_info['description'],
                'task_id': task.id if task else None,
                'estimated_time': lesson_info['estimated_time'],
                'max_score': 100
            }

            # Add specific content for lessons without tasks
            if not task:
                lesson['placeholder'] = True
                lesson['content'] = self._generate_placeholder_content(lesson_info['type'])

            lessons.append(lesson)
            lesson_number += 1

        return {
            'lessons': lessons,
            'total_lessons': len(lessons)
        }

    def _calculate_difficulty_score(self) -> float:
        """Calculate difficulty score for the book"""
        # Simple heuristic based on word count and average sentence length
        if hasattr(self.book, 'word_count') and self.book.word_count:
            # Longer books are generally more challenging
            length_score = min(self.book.word_count / 50000, 1.0) * 3

            # Add base difficulty
            base_score = 3.0

            return min(base_score + length_score, 10.0)

        return 5.0  # Default mid-range difficulty

    def _generate_placeholder_content(self, lesson_type: str) -> str:
        """Generate placeholder content for lessons without tasks"""
        placeholders = {
            'reading_assignment': f"Read chapters from the book focusing on the assigned sections. Pay attention to vocabulary, character development, and plot progression.",
            'reading_mcq': "Reading comprehension questions will be generated based on the text content.",
            'match_headings': "Match paragraph headings exercise will be created from the reading material.",
            'open_cloze': "Fill-in-the-blank exercise with 8 carefully selected gaps to test comprehension.",
            'word_formation': "Word formation exercises focusing on the vocabulary from this block.",
            'keyword_transform': "Sentence transformation exercises using key words from the reading.",
            'grammar_sheet': f"Grammar lesson focusing on specific language patterns found in this block.",
            'text': "Literary analysis covering themes, character development, and narrative techniques.",
        }

        return placeholders.get(lesson_type, "Lesson content will be provided based on the reading material.")

    def _estimate_duration(self) -> int:
        """Estimate course duration in weeks"""
        blocks = Block.query.filter_by(book_id=self.book_id).count()

        # Assume 1 week per 2 blocks, minimum 2 weeks
        weeks = max(2, (blocks + 1) // 2)
        return min(weeks, 12)  # Cap at 12 weeks

    def _extract_author_info(self) -> Dict[str, Any]:
        """Extract author information"""
        return {
            'name': self.book.author or 'Unknown',
            'nationality': '',
            'bio': ''
        }

    def _extract_themes(self) -> List[str]:
        """Extract literary themes from the book"""
        # This could be enhanced with NLP analysis
        return ['literature', 'reading comprehension', 'vocabulary building']

    def _extract_language_features(self) -> Dict[str, Any]:
        """Extract language features"""
        blocks = Block.query.filter_by(book_id=self.book_id).all()
        grammar_points = [block.grammar_key for block in blocks if block.grammar_key]
        vocab_themes = [block.focus_vocab for block in blocks if block.focus_vocab]

        return {
            'grammar_points': grammar_points,
            'vocabulary_themes': vocab_themes,
            'language_level': 'intermediate'
        }

    def _estimate_reading_time(self, block: Block) -> int:
        """Estimate reading time for a block in minutes"""
        # Assume average reading speed of 200 words per minute
        total_words = sum(chapter.words or 0 for chapter in block.chapters)
        return max(30, total_words // 200)

    def _create_learning_objectives(self, block: Block) -> List[str]:
        """Create learning objectives for a block"""
        objectives = []

        if block.grammar_key:
            objectives.append(f"Master {block.grammar_key.replace('_', ' ').title()} grammar")

        if block.focus_vocab:
            objectives.append(f"Learn vocabulary related to {block.focus_vocab}")

        objectives.extend([
            "Improve reading comprehension skills",
            "Practice vocabulary in context",
            "Develop critical thinking through analysis"
        ])

        return objectives

    def _get_block_vocabulary(self, block_id: int) -> List[str]:
        """Get vocabulary words for a block"""
        vocab_entries = BlockVocab.query.filter_by(block_id=block_id).limit(10).all()
        return [entry.word.english_word for entry in vocab_entries if entry.word]

    def _get_course_level(self, course_id: int) -> str:
        """Get the course level"""
        course = BookCourse.query.get(course_id)
        return course.level if course else 'B1'

    def _generate_daily_slices(self, course_id: int) -> bool:
        """Generate daily lesson slices for all modules in the course"""
        try:
            # Get all modules for this course
            modules = BookCourseModule.query.filter_by(course_id=course_id).order_by(BookCourseModule.order_index).all()

            if not modules:
                logger.warning("No modules found for daily slice generation")
                return False

            slice_generator = DailySliceGenerator()
            success_count = 0

            for module in modules:
                try:
                    # Get the corresponding block
                    block = Block.query.filter_by(book_id=self.book_id, block_num=module.module_number).first()

                    if not block:
                        logger.warning(f"No block found for module {module.module_number}")
                        continue

                    logger.info(f"Generating daily slices for module {module.module_number}")

                    # Generate slices for this module
                    daily_lessons = slice_generator.generate_slices_for_module(module, block)

                    if daily_lessons:
                        # Update module lessons_data with daily slice information
                        lessons_data = {
                            'lessons': [],
                            'total_lessons': len(daily_lessons)
                        }

                        for lesson in daily_lessons:
                            lesson_info = {
                                'lesson_number': lesson.day_number,
                                'type': lesson.lesson_type,
                                'title': self._get_lesson_title(lesson.lesson_type, lesson.day_number),
                                'description': self._get_lesson_description(lesson.lesson_type),
                                'daily_lesson_id': lesson.id,
                                'task_id': lesson.task_id,
                                'estimated_time': self._estimate_lesson_time(lesson.lesson_type),
                                'max_score': 100,
                                'available_at': lesson.available_at.isoformat() if lesson.available_at else None
                            }

                            # Add vocabulary lesson before each daily slice
                            if lesson.lesson_type != 'final_test':
                                vocab_lesson = {
                                    'lesson_number': lesson.day_number,
                                    'sub_lesson': 'a',
                                    'type': 'vocabulary',
                                    'title': f'Day {lesson.day_number} Vocabulary',
                                    'description': f'Study vocabulary from today\'s reading ({len(lesson.vocabulary)} words)',
                                    'daily_lesson_id': lesson.id,
                                    'estimated_time': 15,
                                    'max_score': 100,
                                    'available_at': lesson.available_at.isoformat() if lesson.available_at else None
                                }
                                lessons_data['lessons'].append(vocab_lesson)

                            lessons_data['lessons'].append(lesson_info)

                        module.lessons_data = lessons_data
                        success_count += 1
                        logger.info(f"Generated {len(daily_lessons)} daily lessons for module {module.module_number}")
                    else:
                        logger.warning(f"No daily lessons generated for module {module.module_number}")

                except Exception as e:
                    logger.error(f"Error generating daily slices for module {module.module_number}: {str(e)}")

            logger.info(f"Generated daily slices for {success_count}/{len(modules)} modules")
            return success_count > 0

        except Exception as e:
            logger.error(f"Error in daily slice generation: {str(e)}")
            return False

    def _get_lesson_title(self, lesson_type: str, day_number: int) -> str:
        """Get appropriate title for lesson type"""
        titles = {
            'reading_mcq': f'Day {day_number}: Reading Comprehension',
            'match_headings': f'Day {day_number}: Match Headings',
            'open_cloze': f'Day {day_number}: Open Cloze Test',
            'word_formation': f'Day {day_number}: Word Formation',
            'keyword_transform': f'Day {day_number}: Key Word Transformations',
            'grammar_sheet': f'Day {day_number}: Grammar Focus',
            'final_test': 'Module Final Test',
            'vocabulary': f'Day {day_number}: Vocabulary Practice'
        }
        return titles.get(lesson_type, f'Day {day_number}: Lesson')

    def _get_lesson_description(self, lesson_type: str) -> str:
        """Get description for lesson type"""
        descriptions = {
            'reading_mcq': 'Answer multiple choice questions about the text (10 questions)',
            'match_headings': 'Match paragraphs with appropriate headings (6 paragraphs → 8 headings)',
            'open_cloze': 'Fill in missing words in the text (8 gaps)',
            'word_formation': 'Transform words into correct forms (8 items)',
            'keyword_transform': 'Rewrite sentences using given key words (6 sentences)',
            'grammar_sheet': 'Grammar lesson with explanations and practice (4-5 questions)',
            'final_test': 'Comprehensive test covering all material (32-36 questions)',
            'vocabulary': 'Study key vocabulary words with interactive exercises'
        }
        return descriptions.get(lesson_type, 'Complete the lesson')

    def _estimate_lesson_time(self, lesson_type: str) -> int:
        """Estimate time in minutes for lesson type"""
        times = {
            'reading_mcq': 15,
            'match_headings': 10,
            'open_cloze': 12,
            'word_formation': 10,
            'keyword_transform': 12,
            'grammar_sheet': 18,
            'final_test': 25,
            'vocabulary': 15
        }
        return times.get(lesson_type, 15)


# Utility functions

def create_course_from_book_cli(
        book_id: int,
        title: str = None,
        description: str = None,
        level: str = 'B1',
        schema_file: str = None
) -> Optional[BookCourse]:
    """CLI function to create a course from a book"""

    book = Book.query.get(book_id)
    if not book:
        return None

    # Use defaults if not provided
    if not title:
        title = f"English Literature: {book.title}"

    if not description:
        description = f"Learn English through {book.title} by {book.author or 'Unknown Author'}"

    # Load schema if provided
    schema_data = None
    if schema_file:
        try:
            importer = BlockSchemaImporter(book_id)
            schema_data = importer.import_from_file(schema_file)
        except Exception as e:
            schema_data = None

    # Create the course
    generator = BookCourseGenerator(book_id)

    course = generator.create_course_from_book(
        course_title=title,
        course_description=description,
        level=level,
        schema_data=schema_data,
        generate_tasks=True
    )

    if course:
        return course
    else:
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a course from a book")
    parser.add_argument("book_id", type=int, help="Book ID")
    parser.add_argument("--title", help="Course title")
    parser.add_argument("--description", help="Course description")
    parser.add_argument("--level", default="B1", help="Course level (A1-C2)")
    parser.add_argument("--schema", help="Path to block schema file")

    args = parser.parse_args()

    create_course_from_book_cli(
        args.book_id,
        args.title,
        args.description,
        args.level,
        args.schema
    )
