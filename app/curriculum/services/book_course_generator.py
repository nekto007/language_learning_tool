"""
Book Course Generator v3.0

This module creates structured language courses from books.

NEW ARCHITECTURE (v3.0):
- Aggregates book chapters into 6-10 modules
- Each day has 2 lessons: Reading + Practice (rotated type)
- Reading lessons cover ~800-1000 words depending on CEFR level
- Practice rotates: vocabulary, grammar, comprehension, cloze, review, summary
- Full book coverage over ~100-200+ days
- SRS integration in practice lessons
"""

import logging
from typing import Any, Dict, List, Optional
import math

from app.books.models import Block, BlockChapter, BlockVocab, Book, Task
from app.curriculum.book_courses import BookCourse, BookCourseModule
from app.curriculum.services.block_schema_importer import BlockSchemaImporter
from app.curriculum.services.daily_slice_generator import DailySliceGenerator
from app.curriculum.services.vocabulary_extractor import VocabularyExtractor
from app.utils.db import db

logger = logging.getLogger(__name__)

# Course structure constants
MAX_MODULES = 10  # Maximum modules per book course
MIN_MODULES = 6   # Minimum modules per book course


class BookCourseGenerator:
    """Generates complete courses from books with structured lessons"""

    def __init__(self, book_id: int):
        self.book_id = book_id
        self.book = Book.query.get_or_404(book_id)
        self.target_level = 'B1'  # Default level, updated in create_course_from_book

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
            print(f"[BOOK COURSE] Начало создания курса для книги: {self.book.title}", flush=True)
            logger.info(f"Starting course creation for book: {self.book.title}")

            # Store target level for vocabulary extraction
            self.target_level = level or 'B1'

            # Step 1: Create the course
            print(f"[BOOK COURSE] Шаг 1: Создание записи курса...", flush=True)
            course = self._create_book_course(course_title, course_description, level)
            if not course:
                print(f"[BOOK COURSE] Ошибка: не удалось создать курс", flush=True)
                return None
            print(f"[BOOK COURSE] Шаг 1: Курс создан (ID: {course.id})", flush=True)

            # Step 2: Import or generate block schema
            print(f"[BOOK COURSE] Шаг 2: Создание блоков...", flush=True)
            if not self._setup_blocks(schema_data):
                print(f"[BOOK COURSE] Ошибка: не удалось создать блоки", flush=True)
                db.session.rollback()
                return None
            blocks_count = Block.query.filter_by(book_id=self.book_id).count()
            print(f"[BOOK COURSE] Шаг 2: Блоки созданы ({blocks_count} блоков)", flush=True)

            # Step 3: Extract vocabulary for blocks
            print(f"[BOOK COURSE] Шаг 3: Извлечение словаря для блоков...", flush=True)
            if not self._extract_vocabulary():
                print(f"[BOOK COURSE] Предупреждение: извлечение словаря не удалось", flush=True)
                logger.warning("Vocabulary extraction failed, but continuing...")
            else:
                vocab_count = BlockVocab.query.join(Block).filter(Block.book_id == self.book_id).count()
                print(f"[BOOK COURSE] Шаг 3: Словарь извлечён ({vocab_count} слов)", flush=True)

            # Step 4: Generate tasks for blocks
            print(f"[BOOK COURSE] Шаг 4: Генерация заданий...", flush=True)
            if generate_tasks and not self._generate_tasks():
                print(f"[BOOK COURSE] Предупреждение: генерация заданий не удалась", flush=True)
                logger.warning("Task generation failed, but continuing...")
            else:
                print(f"[BOOK COURSE] Шаг 4: Задания сгенерированы", flush=True)

            # Step 5: Create course modules from blocks
            print(f"[BOOK COURSE] Шаг 5: Создание модулей курса...", flush=True)
            if not self._create_course_modules(course.id):
                print(f"[BOOK COURSE] Ошибка: не удалось создать модули", flush=True)
                db.session.rollback()
                return None
            modules_count = BookCourseModule.query.filter_by(course_id=course.id).count()
            print(f"[BOOK COURSE] Шаг 5: Модули созданы ({modules_count} модулей)", flush=True)

            # Step 6: Generate daily slices for all modules
            print(f"[BOOK COURSE] Шаг 6: Генерация уроков...", flush=True)
            if not self._generate_daily_slices(course.id):
                print(f"[BOOK COURSE] Предупреждение: генерация уроков не удалась", flush=True)
                logger.warning("Daily slice generation failed, but continuing...")
            else:
                print(f"[BOOK COURSE] Шаг 6: Уроки сгенерированы", flush=True)

            db.session.commit()
            print(f"[BOOK COURSE] Курс успешно создан: {course.title} (ID: {course.id})", flush=True)
            logger.info(f"Successfully created course: {course.title}")
            return course

        except Exception as e:
            print(f"[BOOK COURSE] Ошибка создания курса: {str(e)}", flush=True)
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
            # Check if blocks already exist WITH chapter links
            existing_blocks = Block.query.filter_by(book_id=self.book_id).count()
            existing_links = BlockChapter.query.join(Block).filter(Block.book_id == self.book_id).count()

            if existing_blocks > 0 and existing_links > 0:
                logger.info(f"Using existing {existing_blocks} blocks with {existing_links} chapter links for book {self.book_id}")
                print(f"[BOOK COURSE] Используем существующие {existing_blocks} блоков с {existing_links} связями", flush=True)
                return True

            # If blocks exist but no links, delete blocks and recreate
            if existing_blocks > 0 and existing_links == 0:
                logger.warning(f"Found {existing_blocks} blocks without chapter links, recreating...")
                print(f"[BOOK COURSE] Найдено {existing_blocks} блоков без связей с главами, пересоздаём...", flush=True)
                Block.query.filter_by(book_id=self.book_id).delete()
                db.session.flush()

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

            extractor = VocabularyExtractor(self.book_id, target_level=self.target_level)
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
        """
        Create BookCourseModule records by aggregating blocks into 6-8 modules.

        NEW v2.0 Architecture:
        - 19 blocks are aggregated into 6-8 modules
        - Each module covers multiple blocks/chapters
        - Module count depends on book size and CEFR level
        """
        try:
            blocks = Block.query.filter_by(book_id=self.book_id).order_by(Block.block_num).all()

            if not blocks:
                logger.error("No blocks found for module creation")
                return False

            # Calculate optimal number of modules (6-8)
            total_blocks = len(blocks)
            num_modules = self._calculate_optimal_modules(total_blocks)

            # Distribute blocks across modules
            block_distribution = self._distribute_blocks(blocks, num_modules)

            logger.info(f"Aggregating {total_blocks} blocks into {num_modules} modules")

            module_number = 1
            for module_blocks in block_distribution:
                if not module_blocks:
                    continue

                # Use first block as primary reference (for tasks, vocabulary)
                primary_block = module_blocks[0]

                # Combine chapter info from all blocks in this module
                all_chapters = []
                for block in module_blocks:
                    all_chapters.extend(block.chapters)

                chapter_count = len(all_chapters)
                chapter_nums = [ch.chap_num for ch in all_chapters]

                # Create module title based on chapter range (in Russian)
                if chapter_nums:
                    if len(chapter_nums) == 1:
                        title = f"Модуль {module_number}: Глава {chapter_nums[0]}"
                    else:
                        title = f"Модуль {module_number}: Главы {min(chapter_nums)}-{max(chapter_nums)}"
                else:
                    title = f"Модуль {module_number}"

                # Combine learning objectives from all blocks
                combined_objectives = []
                combined_grammar = []
                combined_vocab = []

                for block in module_blocks:
                    combined_objectives.extend(self._create_learning_objectives(block))
                    if block.grammar_key:
                        combined_grammar.append(block.grammar_key)
                    combined_vocab.extend(self._get_block_vocabulary(block.id))

                # Remove duplicates
                combined_objectives = list(dict.fromkeys(combined_objectives))[:5]
                combined_grammar = list(dict.fromkeys(combined_grammar))
                combined_vocab = list(dict.fromkeys(combined_vocab))[:15]

                # Calculate total reading time for all blocks in module
                total_reading_time = sum(
                    self._estimate_reading_time(block) for block in module_blocks
                )

                # Create placeholder lessons data - will be replaced by daily slices
                lessons_data = {'lessons': [], 'total_lessons': 0}

                # Create the module
                module = BookCourseModule(
                    course_id=course_id,
                    block_id=primary_block.id,  # Primary block reference
                    module_number=module_number,
                    title=title,
                    description=f"Изучение {chapter_count} глав с акцентом на лексику и грамматику",
                    estimated_reading_time=total_reading_time,
                    learning_objectives=combined_objectives,
                    vocabulary_focus=combined_vocab,
                    grammar_focus=combined_grammar,
                    literary_elements=[],
                    lessons_data=lessons_data,
                    difficulty_level=self._get_course_level(course_id),
                    order_index=module_number,
                    is_locked=module_number > 1  # Lock all except first module
                )

                db.session.add(module)
                db.session.flush()

                # Store primary block reference for daily slice generation
                module.block = primary_block

                # Store all blocks for this module (for vocabulary aggregation)
                module._all_blocks = module_blocks

                module_number += 1

            # Update course total_modules count
            course = BookCourse.query.get(course_id)
            course.total_modules = num_modules

            logger.info(f"Created {num_modules} aggregated modules for course {course_id}")
            return True

        except Exception as e:
            logger.error(f"Error creating course modules: {str(e)}")
            return False

    def _calculate_optimal_modules(self, total_blocks: int) -> int:
        """
        Calculate optimal number of modules based on block count and level.

        Target: 6-8 modules per course
        """
        if total_blocks <= MIN_MODULES:
            return total_blocks  # Can't aggregate if fewer blocks than min modules

        if total_blocks <= MAX_MODULES:
            return total_blocks  # One module per block if within range

        # For books with more blocks, aggregate to MAX_MODULES
        return MAX_MODULES

    def _distribute_blocks(self, blocks: List[Block], num_modules: int) -> List[List[Block]]:
        """
        Distribute blocks evenly across modules.

        Example: 19 blocks into 8 modules = [3, 2, 2, 3, 2, 2, 3, 2] blocks each
        """
        if num_modules >= len(blocks):
            # One block per module
            return [[block] for block in blocks]

        distribution = []
        blocks_per_module = len(blocks) / num_modules

        start_idx = 0
        for i in range(num_modules):
            # Calculate end index for this module
            end_idx = int(round((i + 1) * blocks_per_module))
            module_blocks = blocks[start_idx:end_idx]
            distribution.append(module_blocks)
            start_idx = end_idx

        return distribution

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
        """
        Estimate course duration in weeks based on v3.0 architecture.

        With ~800 words/day reading and full book coverage:
        - 50k words book = ~63 days = ~9 weeks
        - 100k words book = ~125 days = ~18 weeks
        - 185k words book = ~231 days = ~33 weeks
        """
        # Get total word count from chapters
        total_words = 0
        blocks = Block.query.filter_by(book_id=self.book_id).all()
        for block in blocks:
            for chapter in block.chapters:
                if chapter.words:
                    total_words += chapter.words

        if total_words == 0:
            # Fallback to old estimation
            return max(4, len(blocks) * 2)

        # Calculate days based on 800 words/day (B1 level)
        days = total_words // 800
        weeks = (days + 6) // 7  # Round up to nearest week

        return max(4, weeks)  # Minimum 4 weeks

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
        """Create learning objectives for a block (in Russian)"""
        objectives = []

        if block.grammar_key:
            objectives.append(f"Освоить грамматику: {block.grammar_key.replace('_', ' ')}")

        if block.focus_vocab:
            objectives.append(f"Изучить лексику по теме: {block.focus_vocab}")

        objectives.extend([
            "Развить навыки понимания прочитанного",
            "Практиковать лексику в контексте",
            "Развить критическое мышление через анализ текста"
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
        """
        Generate structured lessons for all modules in the course.

        NEW v2.0: Uses the block_id stored in each module, creates 6-10 lessons per module.
        """
        try:
            # Get all modules for this course
            modules = BookCourseModule.query.filter_by(course_id=course_id).order_by(BookCourseModule.order_index).all()

            if not modules:
                logger.warning("No modules found for lesson generation")
                return False

            slice_generator = DailySliceGenerator()
            success_count = 0

            # Track used words across ALL modules in the course to avoid repetition
            used_word_ids_in_course: set = set()

            for module in modules:
                try:
                    # Get the primary block for this module (stored during module creation)
                    block = Block.query.get(module.block_id)

                    if not block:
                        logger.warning(f"No block found for module {module.module_number} (block_id={module.block_id})")
                        continue

                    logger.info(f"Generating structured lessons for module {module.module_number}")

                    # Generate structured lessons for this module
                    # Pass used_word_ids_in_course to avoid word repetition between modules
                    daily_lessons = slice_generator.generate_slices_for_module(
                        module, block, used_word_ids_in_course
                    )

                    if daily_lessons:
                        # Update module lessons_data with structured lesson information
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
                            lessons_data['lessons'].append(lesson_info)

                        module.lessons_data = lessons_data
                        success_count += 1
                        logger.info(f"Generated {len(daily_lessons)} structured lessons for module {module.module_number}")
                    else:
                        logger.warning(f"No lessons generated for module {module.module_number}")

                except Exception as e:
                    logger.error(f"Error generating lessons for module {module.module_number}: {str(e)}")

            logger.info(f"Generated lessons for {success_count}/{len(modules)} modules")
            return success_count > 0

        except Exception as e:
            logger.error(f"Error in lesson generation: {str(e)}")
            return False

    def _get_lesson_title(self, lesson_type: str, day_number: int) -> str:
        """Get appropriate title for lesson type"""
        titles = {
            # v3.0 lesson types
            'reading': f'Day {day_number}: Reading',
            'vocabulary': f'Day {day_number}: Vocabulary',
            'grammar_focus': f'Day {day_number}: Grammar Focus',
            'comprehension_mcq': f'Day {day_number}: Comprehension Quiz',
            'cloze_practice': f'Day {day_number}: Cloze Practice',
            'vocabulary_review': f'Day {day_number}: Vocabulary Review',
            'summary_writing': f'Day {day_number}: Summary Writing',
            'module_test': 'Module Test',
            # Legacy v2.0 lesson types (for compatibility)
            'reading_part1': f'Day {day_number}: Reading Part 1',
            'reading_part2': f'Day {day_number}: Reading Part 2',
            'vocabulary_practice': f'Day {day_number}: Vocabulary Practice',
            'discussion': f'Day {day_number}: Discussion',
            'mixed_practice': f'Day {day_number}: Mixed Practice',
            # Legacy lesson types (for compatibility)
            'reading_mcq': f'Day {day_number}: Reading Comprehension',
            'match_headings': f'Day {day_number}: Match Headings',
            'open_cloze': f'Day {day_number}: Open Cloze Test',
            'word_formation': f'Day {day_number}: Word Formation',
            'keyword_transform': f'Day {day_number}: Key Word Transformations',
            'grammar_sheet': f'Day {day_number}: Grammar Focus',
            'final_test': 'Module Final Test',
            'reading_passage': f'Day {day_number}: Reading Passage'
        }
        return titles.get(lesson_type, f'Day {day_number}: Lesson')

    def _get_lesson_description(self, lesson_type: str) -> str:
        """Get description for lesson type"""
        descriptions = {
            # v3.0 lesson types
            'reading': 'Read today\'s text passage (~800-1000 words)',
            'vocabulary': 'Learn new vocabulary from the text (10-15 words)',
            'grammar_focus': 'Study grammar patterns from the text with exercises',
            'comprehension_mcq': 'Test your understanding with multiple choice questions',
            'cloze_practice': 'Practice with open cloze and word formation exercises',
            'vocabulary_review': 'Review vocabulary with matching and fill-in exercises',
            'summary_writing': 'Write a summary of what you\'ve read this week',
            'module_test': 'Comprehensive test covering all module material',
            # Legacy v2.0 lesson types (for compatibility)
            'reading_part1': 'Read first half of the text with comprehension questions',
            'reading_part2': 'Read second half of the text with comprehension questions',
            'vocabulary_practice': 'Practice vocabulary: cloze, word formation, matching',
            'discussion': 'Answer open-ended questions for reflection',
            'mixed_practice': 'Combined exercises covering all skills',
            # Legacy lesson types (for compatibility)
            'reading_mcq': 'Answer multiple choice questions about the text (10 questions)',
            'match_headings': 'Match paragraphs with appropriate headings (6 paragraphs → 8 headings)',
            'open_cloze': 'Fill in missing words in the text (8 gaps)',
            'word_formation': 'Transform words into correct forms (8 items)',
            'keyword_transform': 'Rewrite sentences using given key words (6 sentences)',
            'grammar_sheet': 'Grammar lesson with explanations and practice (4-5 questions)',
            'final_test': 'Comprehensive test covering all material (32-36 questions)',
            'reading_passage': 'Read the main text passage'
        }
        return descriptions.get(lesson_type, 'Complete the lesson')

    def _estimate_lesson_time(self, lesson_type: str) -> int:
        """Estimate time in minutes for lesson type"""
        times = {
            # v3.0 lesson types
            'reading': 25,              # ~800 words at 150-200 wpm
            'vocabulary': 15,           # 10-15 words
            'grammar_focus': 20,        # Grammar exercises
            'comprehension_mcq': 15,    # MCQ quiz
            'cloze_practice': 18,       # Cloze + word formation
            'vocabulary_review': 15,    # Review exercises
            'summary_writing': 20,      # Writing practice
            'module_test': 30,          # Comprehensive test
            # Legacy v2.0 lesson types (for compatibility)
            'reading_part1': 25,
            'reading_part2': 25,
            'vocabulary_practice': 18,
            'discussion': 20,
            'mixed_practice': 18,
            # Legacy lesson types (for compatibility)
            'reading_mcq': 15,
            'match_headings': 10,
            'open_cloze': 12,
            'word_formation': 10,
            'keyword_transform': 12,
            'grammar_sheet': 18,
            'final_test': 25,
            'reading_passage': 20
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
