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

from app.books.models import Block, BlockVocab, Chapter, Task
from app.curriculum.book_courses import BookCourseModule
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary, UserLessonProgress
from app.utils.db import db
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

    # Practice lesson types - rotates every 6 days
    PRACTICE_ROTATION = [
        'vocabulary',        # Day 1: New words from slice (10-15 words)
        'grammar_focus',     # Day 2: Grammar patterns from text
        'comprehension_mcq', # Day 3: MCQ test on reading
        'cloze_practice',    # Day 4: Open cloze + word formation
        'vocabulary_review', # Day 5: Vocabulary review (matching, fill-in)
        'summary_writing',   # Day 6: Summary of week's reading
    ]


    # Vocabulary limits
    VOCABULARY_WORDS_PER_LESSON = 15  # Max words per vocabulary lesson
    VOCABULARY_WORDS_PER_MODULE = 50  # Max words tracked per module

    def __init__(self):
        self.timezone = pytz.timezone('Europe/Amsterdam')

    def generate_slices_for_module(self, module: BookCourseModule, block: Block) -> List[DailyLesson]:
        """
        Generate daily lesson pairs for a book course module (v3.0).

        NEW v3.0 Architecture:
        - Each day has 2 lessons: Reading + Practice
        - Reading lesson covers a text slice (~800-1000 words depending on level)
        - Practice lesson type rotates through PRACTICE_ROTATION
        - Covers 100% of module text over multiple days
        - Ends with Module Test

        Args:
            module: BookCourseModule instance
            block: Associated Block with chapters

        Returns:
            List of created DailyLesson instances
        """
        logger.info(f"Generating v3.0 daily lessons for module {module.id}")

        # Determine CEFR level and get word limits
        level = self._determine_level(module)
        target_words, max_words = self.WORDS_PER_LEVEL.get(level, self.WORDS_PER_LEVEL_DEFAULT)
        logger.info(f"Level: {level}, target: {target_words}, max: {max_words} words per day")

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
        num_days = len(reading_slices)
        logger.info(f"Created {num_days} reading slices")

        # Get vocabulary for the module
        module_vocabulary = self._get_block_vocabulary(block)

        # Generate lesson pairs for each day
        daily_lessons = []
        day_number = 1

        for slice_data in reading_slices:
            # Lesson 1: Reading
            reading_lesson = self._create_reading_lesson(
                module=module,
                day_number=day_number,
                slice_data=slice_data
            )
            db.session.add(reading_lesson)
            db.session.flush()
            daily_lessons.append(reading_lesson)

            # Lesson 2: Practice (rotated type)
            practice_type = self.PRACTICE_ROTATION[(day_number - 1) % len(self.PRACTICE_ROTATION)]
            practice_lesson = self._create_practice_lesson(
                module=module,
                day_number=day_number,
                practice_type=practice_type,
                slice_data=slice_data,
                module_vocabulary=module_vocabulary
            )
            db.session.add(practice_lesson)
            db.session.flush()

            # Extract vocabulary for vocabulary-type practice lessons
            if practice_type in ['vocabulary', 'vocabulary_review']:
                self._extract_slice_vocabulary(practice_lesson, slice_data['text'], module_vocabulary)

            daily_lessons.append(practice_lesson)
            day_number += 1

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
        module.total_slices = len(daily_lessons)
        module.days_to_complete = num_days + 1  # +1 for module test

        db.session.commit()
        logger.info(f"Generated {len(daily_lessons)} lessons ({num_days} days + test) for module {module.id}")

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

    def _create_reading_lesson(self, module: BookCourseModule, day_number: int,
                                slice_data: Dict[str, Any]) -> DailyLesson:
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

        # Set availability
        lesson.available_at = self._calculate_available_at(day_number, lesson_order=1)

        return lesson

    def _create_practice_lesson(self, module: BookCourseModule, day_number: int,
                                 practice_type: str, slice_data: Dict[str, Any],
                                 module_vocabulary: Dict[int, Dict]) -> DailyLesson:
        """Create a practice lesson for the day with rotated type."""
        lesson = DailyLesson(
            book_course_module_id=module.id,
            slice_number=day_number,
            day_number=day_number,
            lesson_type=practice_type,
            chapter_id=slice_data['chapter_id'],
            slice_text=slice_data['text'][:500] + "..." if len(slice_data['text']) > 500 else slice_data['text'],
            word_count=0,  # Practice lessons don't have word count
            start_position=slice_data['start_position'],
            end_position=slice_data['end_position']
        )

        # Set availability - practice available same day as reading
        lesson.available_at = self._calculate_available_at(day_number, lesson_order=2)

        return lesson

    def _create_module_test_lesson(self, module: BookCourseModule, day_number: int,
                                    chapters: List[Chapter], block: Block) -> DailyLesson:
        """Create the module test lesson."""
        from app.books.models import TaskType

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
                texts.append(chapter.text_raw)
        return '\n\n'.join(texts)

    def _extract_slice_vocabulary(self, daily_lesson: DailyLesson, text: str,
                                   module_vocabulary: Dict[int, Dict]):
        """Extract vocabulary words that appear in this slice."""
        text_lower = text.lower()
        words_in_slice = []

        for word_id, word_data in module_vocabulary.items():
            word_text = word_data['english'].lower()
            occurrences = len(re.findall(r'\b' + re.escape(word_text) + r'\b', text_lower))

            if occurrences > 0:
                sentences = self._split_into_sentences(text)
                context_sentence = None
                for sentence in sentences:
                    if word_text in sentence.lower():
                        context_sentence = sentence
                        break

                words_in_slice.append({
                    'word_id': word_id,
                    'frequency': occurrences,
                    'context': context_sentence
                })

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
        # Simple sentence splitting - can be enhanced with NLTK or spaCy
        text = text.replace('\n\n', ' <PARAGRAPH> ')
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

        # Split on sentence endings
        sentences = re.split(r'(?<=[.!?])\s+', text)

        # Restore paragraph breaks
        sentences = [s.replace(' <PARAGRAPH> ', '\n\n') for s in sentences]

        return [s.strip() for s in sentences if s.strip()]

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
