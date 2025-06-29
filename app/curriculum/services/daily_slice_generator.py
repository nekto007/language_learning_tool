# app/curriculum/services/daily_slice_generator.py

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List

import pytz

from app.books.models import Block, BlockVocab, Chapter, Task
from app.curriculum.book_courses import BookCourseModule
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary, UserLessonProgress
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


class DailySliceGenerator:
    """
    Generates daily lesson slices from book chapters according to technical specification.
    Each slice is approximately 800 words and represents one day of learning.
    """

    SLICE_SIZE = 800  # Target words per slice
    SLICE_TOLERANCE = 50  # Allow +/- 50 words for better sentence boundaries
    # Lesson types rotation according to technical specification (section 3.1)
    LESSON_TYPES_ROTATION = [
        'reading_mcq',  # Reading MCQ - 10 questions
        'match_headings',  # Matching Headings - 6 paragraphs → 8 headings
        'open_cloze',  # Open Cloze - 8 gaps
        'word_formation',  # Word Formation - 8 items
        'keyword_transform',  # Key-Word Transformations - 6 sentences
        'grammar_sheet'  # Grammar mini-focus - 4-5 questions
    ]
    VOCABULARY_WORDS_PER_SLICE = 10  # Maximum vocabulary words per daily lesson

    def __init__(self):
        self.timezone = pytz.timezone('Europe/Amsterdam')

    def generate_slices_for_module(self, module: BookCourseModule, block: Block) -> List[DailyLesson]:
        """
        Generate all daily lesson slices for a book course module.
        
        Args:
            module: BookCourseModule instance
            block: Associated Block with chapters
            
        Returns:
            List of created DailyLesson instances
        """
        logger.info(f"Generating daily slices for module {module.id} (block {block.id})")

        # Get all chapters for this block
        chapters = sorted(block.chapters, key=lambda c: c.chap_num)
        if not chapters:
            logger.error(f"No chapters found for block {block.id}")
            return []

        # Get existing vocabulary for the block
        block_vocabulary = self._get_block_vocabulary(block)

        # Generate slices for all chapters
        all_slices = []
        day_number = 1

        for chapter in chapters:
            chapter_slices = self._slice_chapter(chapter, module, day_number, block_vocabulary)
            all_slices.extend(chapter_slices)
            # Each slice creates 3 lessons (vocabulary + reading + task), so increment by actual slice count
            day_number += len(chapter_slices) // 3

        # Set total slices and days to complete
        # Each day has 3 lessons, so actual days = total lessons / 3
        actual_days = len(all_slices) // 3
        module.total_slices = actual_days
        module.days_to_complete = actual_days + 1  # +1 for final test day

        # Create final test as last day
        final_test_lesson = self._create_final_test_lesson(module, block, day_number)
        if final_test_lesson:
            all_slices.append(final_test_lesson)

        db.session.commit()
        logger.info(f"Generated {len(all_slices)} daily lessons for module {module.id}")

        return all_slices

    def _slice_chapter(self, chapter: Chapter, module: BookCourseModule,
                       start_day: int, block_vocabulary: Dict[int, Dict]) -> List[DailyLesson]:
        """
        Slice a chapter into ~800 word daily lessons.
        
        Args:
            chapter: Chapter to slice
            module: Parent module
            start_day: Starting day number for this chapter
            block_vocabulary: Dictionary of vocabulary words for the block
            
        Returns:
            List of DailyLesson instances
        """
        text = chapter.text_raw
        if not text:
            logger.warning(f"Chapter {chapter.id} has no text")
            return []

        # Split text into sentences
        sentences = self._split_into_sentences(text)

        # Group sentences into slices of ~800 words
        slices = []
        current_slice = []
        current_word_count = 0
        slice_start_pos = 0

        for sentence in sentences:
            sentence_words = len(sentence.split())

            # Check if adding this sentence would exceed target size
            if current_word_count > 0 and current_word_count + sentence_words > self.SLICE_SIZE + self.SLICE_TOLERANCE:
                # Save current slice
                slice_text = ' '.join(current_slice)
                slices.append({
                    'text': slice_text,
                    'word_count': current_word_count,
                    'start_position': slice_start_pos,
                    'end_position': slice_start_pos + len(slice_text)
                })

                # Start new slice
                current_slice = [sentence]
                current_word_count = sentence_words
                slice_start_pos += len(slice_text) + 1
            else:
                current_slice.append(sentence)
                current_word_count += sentence_words

        # Don't forget the last slice
        if current_slice:
            slice_text = ' '.join(current_slice)
            slices.append({
                'text': slice_text,
                'word_count': current_word_count,
                'start_position': slice_start_pos,
                'end_position': slice_start_pos + len(slice_text)
            })

        # Create DailyLesson instances
        daily_lessons = []
        for i, slice_data in enumerate(slices):
            day_number = start_day + i
            slice_number = i + 1

            # According to technical specification (section 3.1), each day should have:
            # 1. Vocabulary (≤ 10 words from slice)
            # 2. Reading Passage (the slice itself)  
            # 3. Additional task (rotated type)

            # Determine rotated task type for this day
            task_type_index = (day_number - 1) % len(self.LESSON_TYPES_ROTATION)
            rotated_task_type = self.LESSON_TYPES_ROTATION[task_type_index]

            # Create three component lessons for this day's slice
            lesson_components = [
                ('vocabulary', 1),  # Component 1: Vocabulary
                ('reading_passage', 2),  # Component 2: Reading Passage
                (rotated_task_type, 3)  # Component 3: Rotated task
            ]

            for lesson_type, component_order in lesson_components:
                daily_lesson = DailyLesson(
                    book_course_module_id=module.id,
                    slice_number=slice_number,
                    day_number=day_number,
                    slice_text=slice_data['text'],
                    word_count=slice_data['word_count'],
                    start_position=slice_data['start_position'],
                    end_position=slice_data['end_position'],
                    chapter_id=chapter.id,
                    lesson_type=lesson_type
                )

                # Calculate available_at time - first lesson immediately available
                if day_number == 1:
                    daily_lesson.available_at = None
                else:
                    # Available at 8:00 AM Amsterdam time on the lesson day
                    base_date = datetime.now(self.timezone).date()
                    lesson_date = base_date + timedelta(days=day_number - 1)
                    daily_lesson.available_at = self.timezone.localize(
                        datetime.combine(lesson_date, datetime.min.time().replace(hour=8))
                    ).astimezone(pytz.UTC)

                db.session.add(daily_lesson)
                db.session.flush()  # Get ID for vocabulary association

                # Extract vocabulary only for vocabulary component
                if lesson_type == 'vocabulary':
                    self._extract_slice_vocabulary(daily_lesson, slice_data['text'], block_vocabulary)

                # Generate task for components that need them (not vocabulary or reading_passage)
                if lesson_type not in ['vocabulary', 'reading_passage']:
                    task = self._get_or_create_task_for_lesson(daily_lesson, module)
                    if task:
                        daily_lesson.task_id = task.id

                daily_lessons.append(daily_lesson)

        return daily_lessons

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

    def _extract_slice_vocabulary(self, daily_lesson: DailyLesson, text: str,
                                  block_vocabulary: Dict[int, Dict]):
        """
        Extract vocabulary words that appear in this specific slice.
        Limited to VOCABULARY_WORDS_PER_SLICE most frequent words.
        """
        text_lower = text.lower()
        words_in_slice = []

        # Find which block vocabulary words appear in this slice
        for word_id, word_data in block_vocabulary.items():
            word_text = word_data['english'].lower()

            # Count occurrences in slice
            occurrences = len(re.findall(r'\b' + re.escape(word_text) + r'\b', text_lower))

            if occurrences > 0:
                # Find context sentence
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
        words_in_slice = words_in_slice[:self.VOCABULARY_WORDS_PER_SLICE]

        # Create SliceVocabulary entries
        for word_data in words_in_slice:
            slice_vocab = SliceVocabulary(
                daily_lesson_id=daily_lesson.id,
                word_id=word_data['word_id'],
                frequency_in_slice=word_data['frequency'],
                context_sentence=word_data['context']
            )
            db.session.add(slice_vocab)

    def _get_or_create_task_for_lesson(self, daily_lesson: DailyLesson,
                                       module: BookCourseModule) -> Task:
        """Get existing task or create placeholder for lesson type."""
        from app.books.models import TaskType

        # Get TaskType enum value
        try:
            task_type_enum = getattr(TaskType, daily_lesson.lesson_type)
        except AttributeError:
            logger.warning(f"Unknown lesson type: {daily_lesson.lesson_type}")
            return None

        # Check if task already exists for this lesson type in the module's block
        if not module.block_id:
            logger.warning(f"Module {module.id} has no block_id")
            return None

        existing_task = (Task.query
                         .filter_by(block_id=module.block_id,
                                    task_type=task_type_enum)
                         .first())

        if existing_task:
            return existing_task

        # For now, return None - tasks should be generated by task generators
        # This is a placeholder for future integration
        return None

    def _create_final_test_lesson(self, module: BookCourseModule, block: Block,
                                  day_number: int) -> DailyLesson:
        """Create the final test lesson for a module."""
        from app.books.models import TaskType

        # Get final test task if it exists
        final_test_task = Task.query.filter_by(
            block_id=block.id,
            task_type=TaskType.final_test
        ).first()

        if not final_test_task:
            logger.info(f"No final test task found for block {block.id}, creating fallback final test lesson")
            # Create fallback final test lesson without task_id
            final_lesson = DailyLesson(
                book_course_module_id=module.id,
                slice_number=999,  # Special number for final test
                day_number=day_number,
                slice_text="Final Module Test - Comprehensive Assessment",
                word_count=0,
                start_position=0,
                end_position=0,
                chapter_id=block.chapters[0].id,  # Use first chapter as reference
                lesson_type='final_test',
                task_id=None  # No task yet, can be linked later
            )

            # Final test available after all other lessons
            base_date = datetime.now(self.timezone).date()
            lesson_date = base_date + timedelta(days=day_number - 1)
            final_lesson.available_at = self.timezone.localize(
                datetime.combine(lesson_date, datetime.min.time().replace(hour=8))
            ).astimezone(pytz.UTC)

            db.session.add(final_lesson)
            return final_lesson

        # Create final test lesson
        final_lesson = DailyLesson(
            book_course_module_id=module.id,
            slice_number=999,  # Special number for final test
            day_number=day_number,
            slice_text="Final Module Test",
            word_count=0,
            start_position=0,
            end_position=0,
            chapter_id=block.chapters[0].id,  # Use first chapter as reference
            lesson_type='final_test',
            task_id=final_test_task.id
        )

        # Final test available after all other lessons
        base_date = datetime.now(self.timezone).date()
        lesson_date = base_date + timedelta(days=day_number - 1)
        final_lesson.available_at = self.timezone.localize(
            datetime.combine(lesson_date, datetime.min.time().replace(hour=8))
        ).astimezone(pytz.UTC)

        db.session.add(final_lesson)

        return final_lesson

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
