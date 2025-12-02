# app/curriculum/services/daily_slice_generator.py
"""
Daily Slice Generator v3.0

NEW ARCHITECTURE: Full book coverage with daily reading + practice pairs.

Each day consists of 2 lessons:
1. Reading Lesson - Fresh text slice (~800-1000 words depending on level)
2. Practice Lesson - Rotated type (vocabulary, grammar, comprehension, etc.) + SRS

This ensures 100% book coverage over ~100-200+ days instead of just 7.5%.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

import pytz

from app.books.models import Block, BlockVocab, Chapter, Task, TaskType
from app.curriculum.book_courses import BookCourseModule
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary, UserLessonProgress
from app.curriculum.services.comprehension_generator import ComprehensionMCQGenerator, ClozePracticeGenerator
from app.utils.db import db, word_book_link
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


class DailySliceGenerator:
    """
    Generates daily lesson pairs for book course modules (v3.0).

    NEW ARCHITECTURE (v3.0):
    - Each day has 2 lessons: Reading + Practice
    - Reading covers fresh text slice (~800-1000 words)
    - Practice rotates through 6 types with SRS integration
    - Full book coverage over ~100-200+ days
    - Module = chapters grouped, ends with Module Test
    """

    # Maximum modules per book course
    MAX_MODULES = 10

    # Words per day for reading lessons by CEFR level
    # (target, max) - target is middle of range, max is upper limit
    # Algorithm cuts at sentence boundaries, respecting max
    WORDS_PER_LEVEL = {
        'A1': (100, 150),    # Range: 50-150 words
        'A2': (125, 200),    # Range: 50-200 words
        'B1': (400, 600),    # Range: 200-600 words
        'B2': (700, 800),    # Range: 600-800 words
        'C1': (900, 1000),   # Range: 800-1000 words
        'C2': (1050, 1200),  # Range: 900-1200 words
    }
    WORDS_PER_LEVEL_DEFAULT = (400, 600)

    # Legacy practice rotation (for backward compatibility)
    PRACTICE_ROTATION = [
        'vocabulary',        # Day 1: New words from slice (10-15 words)
        'grammar_focus',     # Day 2: Grammar patterns from text
        'comprehension_mcq', # Day 3: MCQ test on reading
        'cloze_practice',    # Day 4: Open cloze + word formation
        'vocabulary_review', # Day 5: Vocabulary review (matching, fill-in)
        'summary_writing',   # Day 6: Summary of week's reading
    ]

    # NEW v3.1: Level-specific lesson schedules
    # For A1-A2: 8-day cycle, vocabulary/review comes BEFORE reading on some days
    LESSON_SCHEDULE_BEGINNER = [
        # Day 1: vocabulary → reading (learn words, then see in context)
        {'lesson1': 'vocabulary', 'lesson2': 'reading'},
        # Day 2: reading → grammar (read, then grammar from text)
        {'lesson1': 'reading', 'lesson2': 'grammar_focus'},
        # Day 3: reading → comprehension (read, then MCQ)
        {'lesson1': 'reading', 'lesson2': 'comprehension_mcq'},
        # Day 4: reading → cloze (read, then fill gaps)
        {'lesson1': 'reading', 'lesson2': 'cloze_practice'},
        # Day 5: vocabulary_review → reading (SRS review, then light reading)
        {'lesson1': 'vocabulary_review', 'lesson2': 'reading'},
        # Day 6: reading → summary (read, then write summary)
        {'lesson1': 'reading', 'lesson2': 'summary_writing'},
        # Day 7: vocabulary → reading (new words for dense text)
        {'lesson1': 'vocabulary', 'lesson2': 'reading'},
    ]
    # Day 8 will be module_test (added separately)

    # For B1+: 6-day cycle, reading always first
    LESSON_SCHEDULE_INTERMEDIATE = [
        {'lesson1': 'reading', 'lesson2': 'vocabulary'},
        {'lesson1': 'reading', 'lesson2': 'grammar_focus'},
        {'lesson1': 'reading', 'lesson2': 'comprehension_mcq'},
        {'lesson1': 'reading', 'lesson2': 'cloze_practice'},
        {'lesson1': 'reading', 'lesson2': 'vocabulary_review'},
        {'lesson1': 'reading', 'lesson2': 'summary_writing'},
    ]


    # Vocabulary limits
    VOCABULARY_WORDS_PER_LESSON = 20  # Max words per vocabulary lesson (reserve pool)
    VOCABULARY_WORDS_PER_MODULE = 50  # Max words tracked per module

    def __init__(self):
        self.timezone = pytz.timezone('Europe/Amsterdam')

    def generate_slices_for_module(self, module: BookCourseModule, block: Block) -> List[DailyLesson]:
        """
        Generate daily lesson pairs for a book course module (v3.1).

        NEW v3.1 Architecture:
        - Level-specific lesson schedules (A1-A2 vs B1+)
        - A1-A2: 8-day cycle, vocabulary sometimes BEFORE reading
        - B1+: 6-day cycle, reading always first
        - Covers 100% of module text over multiple days
        - Ends with Module Test

        Args:
            module: BookCourseModule instance
            block: Associated Block with chapters

        Returns:
            List of created DailyLesson instances
        """
        logger.info(f"Generating v3.1 daily lessons for module {module.id}")

        # Determine CEFR level and get word limits
        level = self._determine_level(module)
        target_words, max_words = self.WORDS_PER_LEVEL.get(level, self.WORDS_PER_LEVEL_DEFAULT)
        logger.info(f"Level: {level}, target: {target_words}, max: {max_words} words per day")

        # Select lesson schedule based on level
        is_beginner = level in ['A1', 'A2']
        schedule = self.LESSON_SCHEDULE_BEGINNER if is_beginner else self.LESSON_SCHEDULE_INTERMEDIATE
        schedule_len = len(schedule)
        logger.info(f"Using {'beginner (8-day)' if is_beginner else 'intermediate (6-day)'} schedule")

        # Get all chapters for this module
        chapters = sorted(block.chapters, key=lambda c: c.chap_num)
        if not chapters:
            logger.error(f"No chapters found for block {block.id}")
            return []

        # Combine all chapter text for this module
        module_text = self._combine_chapter_texts(chapters)
        total_words = len(module_text.split())
        logger.info(f"Module has {total_words} words from {len(chapters)} chapters")

        # Split module text into daily reading slices
        reading_slices = self._split_text_into_slices(module_text, target_words, max_words, chapters)
        num_slices = len(reading_slices)
        logger.info(f"Created {num_slices} reading slices")

        # Get vocabulary for the module
        module_vocabulary = self._get_block_vocabulary(block)

        # Generate lesson pairs for each day
        daily_lessons = []
        day_number = 1
        slice_index = 0

        while slice_index < num_slices:
            # Get schedule for this day (cycles through schedule)
            day_schedule = schedule[(day_number - 1) % schedule_len]
            lesson1_type = day_schedule['lesson1']
            lesson2_type = day_schedule['lesson2']

            # Get current slice data
            slice_data = reading_slices[slice_index]

            # Create Lesson 1
            lesson1 = self._create_lesson_by_type(
                module=module,
                day_number=day_number,
                lesson_type=lesson1_type,
                slice_data=slice_data,
                module_vocabulary=module_vocabulary,
                lesson_order=1
            )
            db.session.add(lesson1)
            db.session.flush()

            # Extract vocabulary if needed
            if lesson1_type in ['vocabulary', 'vocabulary_review']:
                self._extract_slice_vocabulary(lesson1, slice_data['text'], module_vocabulary)

            daily_lessons.append(lesson1)

            # Create Lesson 2 (if exists)
            if lesson2_type:
                lesson2 = self._create_lesson_by_type(
                    module=module,
                    day_number=day_number,
                    lesson_type=lesson2_type,
                    slice_data=slice_data,
                    module_vocabulary=module_vocabulary,
                    lesson_order=2
                )
                db.session.add(lesson2)
                db.session.flush()

                # Extract vocabulary if needed
                if lesson2_type in ['vocabulary', 'vocabulary_review']:
                    self._extract_slice_vocabulary(lesson2, slice_data['text'], module_vocabulary)

                daily_lessons.append(lesson2)

            day_number += 1
            slice_index += 1

        # Add Module Test as final lesson
        module_test = self._create_module_test_lesson(
            module=module,
            day_number=day_number,
            chapters=chapters,
            block=block
        )
        db.session.add(module_test)
        daily_lessons.append(module_test)

        # Update module metadata
        num_days = day_number  # day_number was incremented after module_test was added
        module.total_slices = len(daily_lessons)
        module.days_to_complete = num_days

        db.session.commit()
        logger.info(f"Generated {len(daily_lessons)} lessons ({num_slices} slices + test) for module {module.id}")

        return daily_lessons

    def _split_text_into_slices(self, text: str, target_words: int, max_words: int,
                                 chapters: List[Chapter]) -> List[Dict[str, Any]]:
        """
        Split text into slices of approximately target_words words.
        Splits at sentence boundaries, respecting max_words limit.

        Args:
            text: Full text to split
            target_words: Target words per slice (middle of range)
            max_words: Maximum words per slice (upper limit of range)
            chapters: List of chapters for tracking chapter_id

        Returns list of slice data dicts with text, word_count, positions, chapter_id.
        """
        sentences = self._split_into_sentences(text)
        slices = []
        current_slice = []
        current_word_count = 0
        current_position = 0

        # Track which chapter we're in
        chapter_boundaries = self._calculate_chapter_boundaries(chapters)
        current_chapter_idx = 0

        for sentence in sentences:
            sentence_words = len(sentence.split())

            # Check if adding this sentence would exceed max_words limit
            if current_word_count > 0 and current_word_count + sentence_words > max_words:
                # Save current slice
                slice_text = ' '.join(current_slice)
                chapter_id = chapters[min(current_chapter_idx, len(chapters) - 1)].id

                slices.append({
                    'text': slice_text,
                    'word_count': current_word_count,
                    'start_position': current_position - len(slice_text),
                    'end_position': current_position,
                    'chapter_id': chapter_id
                })

                # Start new slice
                current_slice = [sentence]
                current_word_count = sentence_words
            else:
                current_slice.append(sentence)
                current_word_count += sentence_words

            current_position += len(sentence) + 1

            # Update chapter index based on position
            while (current_chapter_idx < len(chapter_boundaries) - 1 and
                   current_position >= chapter_boundaries[current_chapter_idx + 1]):
                current_chapter_idx += 1

        # Don't forget the last slice
        if current_slice:
            slice_text = ' '.join(current_slice)
            chapter_id = chapters[min(current_chapter_idx, len(chapters) - 1)].id

            slices.append({
                'text': slice_text,
                'word_count': current_word_count,
                'start_position': current_position - len(slice_text),
                'end_position': current_position,
                'chapter_id': chapter_id
            })

        return slices

    def _calculate_chapter_boundaries(self, chapters: List[Chapter]) -> List[int]:
        """Calculate cumulative text positions where each chapter starts."""
        boundaries = [0]
        cumulative = 0

        for chapter in chapters:
            if chapter.text_raw:
                cumulative += len(chapter.text_raw) + 2  # +2 for \n\n separator
            boundaries.append(cumulative)

        return boundaries

    def _create_lesson_by_type(self, module: BookCourseModule, day_number: int,
                                lesson_type: str, slice_data: Dict[str, Any],
                                module_vocabulary: Dict[int, Dict],
                                lesson_order: int = 1) -> DailyLesson:
        """
        Create a lesson based on type (v3.1).

        Args:
            module: BookCourseModule instance
            day_number: Day number in the module
            lesson_type: Type of lesson (reading, vocabulary, grammar_focus, etc.)
            slice_data: Data about the text slice
            module_vocabulary: Vocabulary for the module
            lesson_order: 1 or 2 (first or second lesson of the day)

        Returns:
            DailyLesson instance
        """
        if lesson_type == 'reading':
            return self._create_reading_lesson(module, day_number, slice_data, lesson_order)
        else:
            return self._create_practice_lesson(
                module, day_number, lesson_type, slice_data, module_vocabulary, lesson_order
            )

    def _create_reading_lesson(self, module: BookCourseModule, day_number: int,
                                slice_data: Dict[str, Any], lesson_order: int = 1) -> DailyLesson:
        """Create a reading lesson for the day."""
        lesson = DailyLesson(
            book_course_module_id=module.id,
            slice_number=day_number,
            day_number=day_number,
            lesson_type='reading',
            chapter_id=slice_data['chapter_id'],
            slice_text=slice_data['text'],
            word_count=slice_data['word_count'],
            start_position=slice_data['start_position'],
            end_position=slice_data['end_position']
        )

        # Set availability based on lesson order
        lesson.available_at = self._calculate_available_at(day_number, lesson_order=lesson_order)

        return lesson

    def _create_practice_lesson(self, module: BookCourseModule, day_number: int,
                                 practice_type: str, slice_data: Dict[str, Any],
                                 module_vocabulary: Dict[int, Dict],
                                 lesson_order: int = 2) -> DailyLesson:
        """Create a practice lesson for the day with specified type."""
        # Generate task for comprehension_mcq and cloze_practice
        task_id = None
        if practice_type == 'comprehension_mcq':
            task_id = self._generate_mcq_task(module, slice_data['text'], day_number)
        elif practice_type == 'cloze_practice':
            task_id = self._generate_cloze_task(module, slice_data['text'], day_number)

        lesson = DailyLesson(
            book_course_module_id=module.id,
            slice_number=day_number,
            day_number=day_number,
            lesson_type=practice_type,
            chapter_id=slice_data['chapter_id'],
            slice_text=slice_data['text'][:500] + "..." if len(slice_data['text']) > 500 else slice_data['text'],
            word_count=0,  # Practice lessons don't have word count
            start_position=slice_data['start_position'],
            end_position=slice_data['end_position'],
            task_id=task_id
        )

        # Set availability based on lesson order
        lesson.available_at = self._calculate_available_at(day_number, lesson_order=lesson_order)

        return lesson

    def _generate_mcq_task(self, module: BookCourseModule, text: str, day_number: int) -> Optional[int]:
        """Generate and save MCQ task for comprehension lesson."""
        try:
            # Generate questions from text
            mcq_data = ComprehensionMCQGenerator.generate_questions(text, num_questions=10)

            if not mcq_data or not mcq_data.get('questions'):
                logger.warning(f"Failed to generate MCQ for module {module.id}, day {day_number}")
                return None

            # Note: We don't set block_id because of unique constraint (block_id, task_type)
            # Daily lesson tasks are standalone and linked via DailyLesson.task_id
            task = Task(
                block_id=None,  # No block_id to avoid constraint violation
                task_type=TaskType.reading_mcq,
                payload=mcq_data
            )
            db.session.add(task)
            db.session.flush()

            logger.info(f"Generated MCQ task {task.id} for module {module.id}, day {day_number}")
            return task.id

        except Exception as e:
            logger.error(f"Error generating MCQ task: {e}")
            return None

    def _generate_cloze_task(self, module: BookCourseModule, text: str, day_number: int) -> Optional[int]:
        """Generate and save Cloze task for cloze_practice lesson."""
        try:
            # Generate cloze exercise from text
            cloze_data = ClozePracticeGenerator.generate_cloze(text, num_gaps=8)

            if not cloze_data or not cloze_data.get('gaps'):
                logger.warning(f"Failed to generate Cloze for module {module.id}, day {day_number}")
                return None

            # Note: We don't set block_id because of unique constraint (block_id, task_type)
            # Daily lesson tasks are standalone and linked via DailyLesson.task_id
            task = Task(
                block_id=None,  # No block_id to avoid constraint violation
                task_type=TaskType.open_cloze,
                payload=cloze_data
            )
            db.session.add(task)
            db.session.flush()

            logger.info(f"Generated Cloze task {task.id} for module {module.id}, day {day_number}")
            return task.id

        except Exception as e:
            logger.error(f"Error generating Cloze task: {e}")
            return None

    def _create_module_test_lesson(self, module: BookCourseModule, day_number: int,
                                    chapters: List[Chapter], block: Block) -> DailyLesson:
        """Create the module test lesson."""
        # Try to find existing final test task
        final_test_task = Task.query.filter_by(
            block_id=block.id,
            task_type=TaskType.final_test
        ).first()

        lesson = DailyLesson(
            book_course_module_id=module.id,
            slice_number=999,  # Special number for module test
            day_number=day_number,
            lesson_type='module_test',
            chapter_id=chapters[0].id,
            slice_text="Module Test - Comprehensive Assessment",
            word_count=0,
            start_position=0,
            end_position=0,
            task_id=final_test_task.id if final_test_task else None
        )

        lesson.available_at = self._calculate_available_at(day_number, lesson_order=1)

        return lesson

    def _calculate_available_at(self, day_number: int, lesson_order: int = 1) -> Optional[datetime]:
        """
        Calculate when a lesson becomes available.
        Day 1 lessons are immediately available (None).
        Subsequent days available at 8:00 AM Amsterdam time.
        """
        if day_number == 1:
            return None

        base_date = datetime.now(self.timezone).date()
        lesson_date = base_date + timedelta(days=day_number - 1)

        return self.timezone.localize(
            datetime.combine(lesson_date, datetime.min.time().replace(hour=8))
        ).astimezone(pytz.UTC)

    def _combine_chapter_texts(self, chapters: List[Chapter]) -> str:
        """Combine all chapter texts into one module text."""
        texts = []
        for chapter in chapters:
            if chapter.text_raw:
                # Convert escaped newlines to real newlines
                text = chapter.text_raw.replace('\\n', '\n')
                texts.append(text)
        return '\n\n'.join(texts)

    def _extract_slice_vocabulary(self, daily_lesson: DailyLesson, text: str,
                                   module_vocabulary: Dict[int, Dict]):
        """
        Extract vocabulary words that appear in this slice.

        First tries to find words from module_vocabulary (BlockVocab).
        If not enough words found, falls back to word_book_link (all book words).
        Target: 10 words per vocabulary lesson.
        """
        TARGET_WORDS = 10
        text_lower = text.lower()
        words_in_slice = []
        used_word_ids = set()

        # 1. First, find words from module vocabulary
        for word_id, word_data in module_vocabulary.items():
            word_text = word_data['english'].lower()
            occurrences = len(re.findall(r'\b' + re.escape(word_text) + r'\b', text_lower))

            if occurrences > 0:
                context_sentence = self._find_context_sentence(text, word_text)
                words_in_slice.append({
                    'word_id': word_id,
                    'frequency': occurrences,
                    'context': context_sentence
                })
                used_word_ids.add(word_id)

        # 2. If not enough, get more words from the book via word_book_link
        if len(words_in_slice) < TARGET_WORDS:
            book_id = self._get_book_id_from_lesson(daily_lesson)
            if book_id:
                additional_words = self._get_words_from_book_in_text(
                    book_id, text, used_word_ids,
                    limit=TARGET_WORDS - len(words_in_slice)
                )
                words_in_slice.extend(additional_words)

        # Sort by frequency and take top N
        words_in_slice.sort(key=lambda x: x['frequency'], reverse=True)
        words_in_slice = words_in_slice[:self.VOCABULARY_WORDS_PER_LESSON]

        # Create SliceVocabulary entries
        for word_data in words_in_slice:
            slice_vocab = SliceVocabulary(
                daily_lesson_id=daily_lesson.id,
                word_id=word_data['word_id'],
                frequency_in_slice=word_data['frequency'],
                context_sentence=word_data['context']
            )
            db.session.add(slice_vocab)

        logger.info(f"Extracted {len(words_in_slice)} vocabulary words for lesson {daily_lesson.id}")

    def _find_context_sentence(self, text: str, word: str) -> Optional[str]:
        """Find a sentence containing the word for context."""
        sentences = self._split_into_sentences(text)
        word_pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        for sentence in sentences:
            if word_pattern.search(sentence):
                # Remove all quote characters from the sentence
                sentence = re.sub(r'["\'"«»""'']', '', sentence)
                # Clean up any double spaces that may result
                sentence = re.sub(r'\s+', ' ', sentence).strip()
                return sentence
        return None

    def _get_book_id_from_lesson(self, daily_lesson: DailyLesson) -> Optional[int]:
        """Get book_id from daily lesson's module -> course -> book."""
        try:
            if daily_lesson.module and daily_lesson.module.course:
                return daily_lesson.module.course.book_id
        except Exception:
            pass
        return None

    def _get_words_from_book_in_text(self, book_id: int, text: str,
                                      exclude_ids: set, limit: int) -> List[Dict]:
        """
        Find words from book's vocabulary that appear in the text.
        Uses word_book_link table to get all book words.
        """
        text_lower = text.lower()
        result = []

        # Get all words from the book, sorted by frequency
        book_words = (
            db.session.query(CollectionWords, word_book_link.c.frequency)
            .join(word_book_link, CollectionWords.id == word_book_link.c.word_id)
            .filter(word_book_link.c.book_id == book_id)
            .order_by(word_book_link.c.frequency.desc())
            .all()
        )

        for word, freq in book_words:
            if len(result) >= limit:
                break

            if word.id in exclude_ids:
                continue

            word_text = word.english_word.lower()
            occurrences = len(re.findall(r'\b' + re.escape(word_text) + r'\b', text_lower))

            if occurrences > 0:
                context_sentence = self._find_context_sentence(text, word_text)
                result.append({
                    'word_id': word.id,
                    'frequency': occurrences,
                    'context': context_sentence
                })
                exclude_ids.add(word.id)

        return result

    def _determine_level(self, module: BookCourseModule) -> str:
        """
        Determine the CEFR level for a module.
        Checks module.difficulty_level first, then falls back to course.level.

        Args:
            module: BookCourseModule instance

        Returns:
            CEFR level string (A1, A2, B1, B2, C1, C2)
        """
        # First check module's own difficulty level
        if module.difficulty_level:
            return module.difficulty_level

        # Then check the course's level
        if module.course and module.course.level:
            return module.course.level

        # Fallback to B1 as a sensible default
        return 'B1'

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences, handling common edge cases."""
        # First split by paragraph breaks
        paragraphs = re.split(r'\n\s*\n', text)

        sentences = []
        for para in paragraphs:
            # Normalize whitespace within paragraph
            para = re.sub(r'\s+', ' ', para).strip()
            if not para:
                continue

            # Split on sentence endings (.!?) followed by space or quote+space
            # Also split on closing quotes followed by space (end of dialogue)
            quote_chars = '"\'»""\u2019\u2018'
            para_sentences = re.split(r'(?<=[.!?])[' + quote_chars + r']*\s+', para)
            sentences.extend([s.strip() for s in para_sentences if s.strip()])

        return sentences

    def _get_block_vocabulary(self, block: Block) -> Dict[int, Dict]:
        """Get vocabulary words for a block as a dictionary."""
        vocab_entries = (db.session.query(BlockVocab, CollectionWords)
                         .join(CollectionWords)
                         .filter(BlockVocab.block_id == block.id)
                         .all())

        vocab_dict = {}
        for bv, word in vocab_entries:
            vocab_dict[word.id] = {
                'word': word,
                'frequency': bv.freq,
                'english': word.english_word,
                'russian': word.russian_word
            }

        return vocab_dict

    def unlock_next_lesson(self, user_id: int, enrollment_id: int):
        """
        Check and unlock the next lesson for a user based on their progress.
        Called after lesson completion or by scheduled task.
        """
        # Get last completed lesson
        last_completed = (UserLessonProgress.query
                          .filter_by(user_id=user_id,
                                     enrollment_id=enrollment_id,
                                     status='completed')
                          .join(DailyLesson)
                          .order_by(DailyLesson.day_number.desc())
                          .first())

        if not last_completed:
            # No lessons completed yet, first lesson should be available
            return

        # Find next lesson
        next_lesson = (DailyLesson.query
                       .filter(DailyLesson.book_course_module_id == last_completed.daily_lesson.book_course_module_id)
                       .filter(DailyLesson.day_number == last_completed.daily_lesson.day_number + 1)
                       .first())

        if next_lesson and next_lesson.available_at:
            # Update available_at to 24 hours after last completion
            next_available = last_completed.completed_at + timedelta(hours=24)

            # If calculated time is earlier than current available_at, update it
            if next_available < next_lesson.available_at:
                next_lesson.available_at = next_available
                db.session.commit()
                logger.info(f"Unlocked lesson {next_lesson.id} for user {user_id}")
