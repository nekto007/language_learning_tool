"""Tests for DailySliceGenerator"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import pytz

from app.curriculum.services.daily_slice_generator import DailySliceGenerator


@pytest.fixture
def generator():
    """Create DailySliceGenerator instance"""
    return DailySliceGenerator()


@pytest.fixture
def mock_module():
    """Create mock BookCourseModule"""
    module = Mock()
    module.id = 1
    module.block_id = 10
    return module


@pytest.fixture
def mock_block():
    """Create mock Block"""
    block = Mock()
    block.id = 10
    block.book_id = 1
    return block


@pytest.fixture
def mock_chapter():
    """Create mock Chapter"""
    def _create_chapter(chap_num, text="This is test text. It has sentences."):
        chapter = Mock()
        chapter.id = chap_num
        chapter.chap_num = chap_num
        chapter.text_raw = text
        return chapter
    return _create_chapter


@pytest.fixture
def sample_text():
    """Sample text for slicing (exactly 800 words + a bit)"""
    # Create text with exactly the right length for testing
    sentence = "This is a test sentence with exactly ten words here now. "
    return sentence * 85  # ~850 words


class TestInit:
    """Test __init__ method"""

    def test_initialization(self, generator):
        """Test generator initialization"""
        # Test CEFR-based slice sizes
        assert generator.SLICE_SIZE_BY_LEVEL == {
            'A1': 200, 'A2': 300, 'B1': 400,
            'B2': 600, 'C1': 800, 'C2': 1000
        }
        assert generator.SLICE_SIZE_DEFAULT == 800
        assert generator.SLICE_TOLERANCE == 50
        assert len(generator.LESSON_TYPES_ROTATION) == 6
        assert generator.VOCABULARY_WORDS_PER_SLICE == 10
        assert generator.timezone.zone == 'Europe/Amsterdam'


class TestDetermineLevel:
    """Test _determine_level method - CEFR level determination"""

    def test_uses_module_difficulty_level(self, generator, mock_module):
        """Test that module.difficulty_level is preferred"""
        mock_module.difficulty_level = 'C1'
        mock_module.course = Mock(level='B1')

        result = generator._determine_level(mock_module)

        assert result == 'C1'

    def test_falls_back_to_course_level(self, generator, mock_module):
        """Test fallback to course level when module has no difficulty_level"""
        mock_module.difficulty_level = None
        mock_module.course = Mock(level='B2')

        result = generator._determine_level(mock_module)

        assert result == 'B2'

    def test_defaults_to_b1(self, generator, mock_module):
        """Test default B1 when no level specified"""
        mock_module.difficulty_level = None
        mock_module.course = None

        result = generator._determine_level(mock_module)

        assert result == 'B1'

    def test_defaults_to_b1_when_course_has_no_level(self, generator, mock_module):
        """Test default B1 when course exists but has no level"""
        mock_module.difficulty_level = None
        mock_module.course = Mock(level=None)

        result = generator._determine_level(mock_module)

        assert result == 'B1'


class TestGenerateSlicesForModule:
    """Test generate_slices_for_module method"""

    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_no_chapters_returns_empty(self, mock_db, generator, mock_module, mock_block):
        """Test with block having no chapters"""
        mock_block.chapters = []

        result = generator.generate_slices_for_module(mock_module, mock_block)

        assert result == []

    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_generates_slices_for_chapters(self, mock_db, generator, mock_module, mock_block, mock_chapter):
        """Test generating slices for chapters"""
        ch1 = mock_chapter(1, "Short text. Another sentence.")
        ch2 = mock_chapter(2, "More text here. And another one.")
        mock_block.chapters = [ch1, ch2]

        with patch.object(generator, '_get_block_vocabulary') as mock_vocab, \
             patch.object(generator, '_slice_chapter') as mock_slice, \
             patch.object(generator, '_create_final_test_lesson') as mock_final:

            mock_vocab.return_value = {}
            # Each chapter creates 3 lessons (vocab, reading, task)
            mock_slice.side_effect = [
                [Mock(), Mock(), Mock()],  # ch1
                [Mock(), Mock(), Mock()]   # ch2
            ]
            mock_final.return_value = Mock()

            result = generator.generate_slices_for_module(mock_module, mock_block)

            # 6 lessons from chapters + 1 final test
            assert len(result) == 7
            assert mock_slice.call_count == 2
            mock_final.assert_called_once()
            mock_db.session.commit.assert_called()

    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_sets_module_metadata(self, mock_db, generator, mock_module, mock_block, mock_chapter):
        """Test setting total_slices and days_to_complete"""
        ch1 = mock_chapter(1)
        mock_block.chapters = [ch1]

        with patch.object(generator, '_get_block_vocabulary') as mock_vocab, \
             patch.object(generator, '_slice_chapter') as mock_slice, \
             patch.object(generator, '_create_final_test_lesson') as mock_final:

            mock_vocab.return_value = {}
            # 3 lessons = 1 day
            mock_slice.return_value = [Mock(), Mock(), Mock()]
            mock_final.return_value = Mock()

            generator.generate_slices_for_module(mock_module, mock_block)

            # 3 lessons / 3 = 1 day
            assert mock_module.total_slices == 1
            # +1 for final test day
            assert mock_module.days_to_complete == 2


class TestSliceChapter:
    """Test _slice_chapter method"""

    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_empty_chapter_returns_empty(self, mock_db, generator, mock_module, mock_chapter):
        """Test slicing chapter with no text"""
        chapter = mock_chapter(1, "")

        result = generator._slice_chapter(chapter, mock_module, 1, {})

        assert result == []

    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_creates_three_lessons_per_slice(self, mock_db, mock_lesson_class, generator,
                                             mock_module, mock_chapter):
        """Test creating vocab, reading, and task lessons"""
        chapter = mock_chapter(1, "Short text. Another sentence.")

        with patch.object(generator, '_extract_slice_vocabulary'), \
             patch.object(generator, '_get_or_create_task_for_lesson') as mock_task:

            mock_task.return_value = None

            result = generator._slice_chapter(chapter, mock_module, 1, {})

            # Should create 3 lessons: vocabulary, reading_passage, and rotated task
            assert len(result) == 3
            assert mock_db.session.add.call_count >= 3

    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_rotates_lesson_types(self, mock_db, mock_lesson_class, generator,
                                  mock_module, mock_chapter):
        """Test lesson type rotation"""
        chapter = mock_chapter(1, "Text. " * 100)

        with patch.object(generator, '_extract_slice_vocabulary'), \
             patch.object(generator, '_get_or_create_task_for_lesson'):

            # Mock lesson creation to capture lesson types
            created_lessons = []

            def mock_lesson_init(**kwargs):
                lesson = Mock()
                for key, value in kwargs.items():
                    setattr(lesson, key, value)
                created_lessons.append(lesson)
                return lesson

            mock_lesson_class.side_effect = mock_lesson_init

            result = generator._slice_chapter(chapter, mock_module, 1, {})

            # First slice should have: vocabulary, reading_passage, reading_mcq (index 0)
            lesson_types = [lesson.lesson_type for lesson in created_lessons]
            assert 'vocabulary' in lesson_types
            assert 'reading_passage' in lesson_types
            assert 'reading_mcq' in lesson_types  # First in rotation

    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_first_lesson_immediately_available(self, mock_db, mock_lesson_class,
                                                generator, mock_module, mock_chapter):
        """Test that day 1 lesson has no available_at restriction"""
        chapter = mock_chapter(1, "Short text.")

        with patch.object(generator, '_extract_slice_vocabulary'), \
             patch.object(generator, '_get_or_create_task_for_lesson'):

            created_lessons = []

            def mock_lesson_init(**kwargs):
                lesson = Mock()
                for key, value in kwargs.items():
                    setattr(lesson, key, value)
                created_lessons.append(lesson)
                return lesson

            mock_lesson_class.side_effect = mock_lesson_init

            generator._slice_chapter(chapter, mock_module, 1, {})

            # All day 1 lessons should have available_at = None
            for lesson in created_lessons:
                if lesson.day_number == 1:
                    assert lesson.available_at is None


class TestSplitIntoSentences:
    """Test _split_into_sentences method"""

    def test_splits_on_periods(self, generator):
        """Test splitting on periods"""
        text = "First sentence. Second sentence. Third sentence."

        result = generator._split_into_sentences(text)

        assert len(result) == 3
        assert result[0] == "First sentence."
        assert result[1] == "Second sentence."

    def test_handles_question_marks(self, generator):
        """Test splitting on question marks"""
        text = "Is this a question? Yes it is! Great."

        result = generator._split_into_sentences(text)

        assert len(result) == 3

    def test_normalizes_whitespace(self, generator):
        """Test whitespace normalization"""
        text = "First sentence.    Second   sentence."

        result = generator._split_into_sentences(text)

        assert "    " not in result[0]
        assert "   " not in result[1]

    def test_handles_paragraph_breaks(self, generator):
        """Test paragraph break preservation"""
        text = "First paragraph.\n\nSecond paragraph."

        result = generator._split_into_sentences(text)

        # Paragraph breaks are replaced with <PARAGRAPH> marker
        assert '<PARAGRAPH>' in ''.join(result)


class TestGetBlockVocabulary:
    """Test _get_block_vocabulary method"""

    @patch('app.curriculum.services.daily_slice_generator.db')
    @patch('app.curriculum.services.daily_slice_generator.CollectionWords')
    @patch('app.curriculum.services.daily_slice_generator.BlockVocab')
    def test_returns_vocabulary_dict(self, mock_vocab_model, mock_word_model,
                                     mock_db, generator, mock_block):
        """Test getting vocabulary as dictionary"""
        # Mock vocabulary entry
        bv = Mock()
        bv.freq = 10

        word = Mock()
        word.id = 1
        word.english_word = "hello"
        word.russian_word = "привет"

        mock_db.session.query.return_value.join.return_value.filter.return_value.all.return_value = [
            (bv, word)
        ]

        result = generator._get_block_vocabulary(mock_block)

        assert 1 in result
        assert result[1]['english'] == "hello"
        assert result[1]['russian'] == "привет"
        assert result[1]['frequency'] == 10

    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_returns_empty_dict_no_vocabulary(self, mock_db, generator, mock_block):
        """Test with no vocabulary"""
        mock_db.session.query.return_value.join.return_value.filter.return_value.all.return_value = []

        result = generator._get_block_vocabulary(mock_block)

        assert result == {}


class TestExtractSliceVocabulary:
    """Test _extract_slice_vocabulary method"""

    @patch('app.curriculum.services.daily_slice_generator.db')
    @patch('app.curriculum.services.daily_slice_generator.SliceVocabulary')
    def test_extracts_words_from_text(self, mock_slice_vocab, mock_db, generator):
        """Test extracting vocabulary words from slice text"""
        daily_lesson = Mock(id=1)
        text = "Hello world. This is a test. Hello again."

        block_vocabulary = {
            1: {'english': 'hello', 'russian': 'привет', 'frequency': 10, 'word': Mock()},
            2: {'english': 'test', 'russian': 'тест', 'frequency': 5, 'word': Mock()}
        }

        generator._extract_slice_vocabulary(daily_lesson, text, block_vocabulary)

        # Should add vocabulary entries for words found in text
        assert mock_db.session.add.call_count == 2

    @patch('app.curriculum.services.daily_slice_generator.db')
    @patch('app.curriculum.services.daily_slice_generator.SliceVocabulary')
    def test_limits_to_max_words(self, mock_slice_vocab, mock_db, generator):
        """Test limiting to VOCABULARY_WORDS_PER_SLICE"""
        daily_lesson = Mock(id=1)
        text = " ".join([f"word{i}" for i in range(20)])  # 20 words

        # Create 15 vocabulary entries (more than limit)
        block_vocabulary = {}
        for i in range(15):
            block_vocabulary[i] = {
                'english': f'word{i}',
                'russian': f'слово{i}',
                'frequency': i,
                'word': Mock()
            }

        generator._extract_slice_vocabulary(daily_lesson, text, block_vocabulary)

        # Should only add up to 10 words (VOCABULARY_WORDS_PER_SLICE)
        assert mock_db.session.add.call_count <= generator.VOCABULARY_WORDS_PER_SLICE

    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_no_words_found(self, mock_db, generator):
        """Test with no vocabulary words in text"""
        daily_lesson = Mock(id=1)
        text = "Some random text without vocabulary words."
        block_vocabulary = {
            1: {'english': 'hello', 'russian': 'привет', 'frequency': 10, 'word': Mock()}
        }

        generator._extract_slice_vocabulary(daily_lesson, text, block_vocabulary)

        # Should not add any vocabulary
        mock_db.session.add.assert_not_called()


class TestGetOrCreateTaskForLesson:
    """Test _get_or_create_task_for_lesson method"""

    @patch('app.books.models.TaskType')
    @patch('app.curriculum.services.daily_slice_generator.Task')
    def test_returns_existing_task(self, mock_task_model, mock_task_type,
                                   generator, mock_module):
        """Test returning existing task"""
        daily_lesson = Mock(lesson_type='reading_mcq')
        mock_module.block_id = 10

        # Mock TaskType enum
        mock_task_type.reading_mcq = 'reading_mcq'

        existing_task = Mock()
        mock_task_model.query.filter_by.return_value.first.return_value = existing_task

        result = generator._get_or_create_task_for_lesson(daily_lesson, mock_module)

        assert result == existing_task

    @patch('app.curriculum.services.daily_slice_generator.Task')
    def test_returns_none_for_unknown_type(self, mock_task_model, generator, mock_module):
        """Test with unknown lesson type"""
        daily_lesson = Mock(lesson_type='unknown_type')
        mock_module.block_id = 10

        result = generator._get_or_create_task_for_lesson(daily_lesson, mock_module)

        assert result is None

    @patch('app.curriculum.services.daily_slice_generator.Task')
    def test_returns_none_no_block_id(self, mock_task_model, generator, mock_module):
        """Test with module having no block_id"""
        daily_lesson = Mock(lesson_type='reading_mcq')
        mock_module.block_id = None

        result = generator._get_or_create_task_for_lesson(daily_lesson, mock_module)

        assert result is None


class TestCreateFinalTestLesson:
    """Test _create_final_test_lesson method"""

    @patch('app.books.models.TaskType')
    @patch('app.curriculum.services.daily_slice_generator.db')
    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.Task')
    def test_creates_lesson_with_task(self, mock_task_model, mock_lesson_class,
                                     mock_db, mock_task_type, generator,
                                     mock_module, mock_block, mock_chapter):
        """Test creating final test with existing task"""
        mock_block.chapters = [mock_chapter(1)]

        # Mock TaskType enum
        mock_task_type.final_test = 'final_test'

        final_task = Mock(id=100)
        mock_task_model.query.filter_by.return_value.first.return_value = final_task

        created_lesson = Mock()
        mock_lesson_class.return_value = created_lesson

        result = generator._create_final_test_lesson(mock_module, mock_block, 5)

        assert result == created_lesson
        mock_db.session.add.assert_called_with(created_lesson)

    @patch('app.books.models.TaskType')
    @patch('app.curriculum.services.daily_slice_generator.db')
    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.Task')
    def test_creates_fallback_lesson_no_task(self, mock_task_model, mock_lesson_class,
                                            mock_db, mock_task_type, generator,
                                            mock_module, mock_block, mock_chapter):
        """Test creating final test without task"""
        mock_block.chapters = [mock_chapter(1)]

        # Mock TaskType enum
        mock_task_type.final_test = 'final_test'

        mock_task_model.query.filter_by.return_value.first.return_value = None

        created_lesson = Mock()
        mock_lesson_class.return_value = created_lesson

        result = generator._create_final_test_lesson(mock_module, mock_block, 5)

        assert result == created_lesson
        # Verify fallback lesson was created
        call_kwargs = mock_lesson_class.call_args[1]
        assert call_kwargs['lesson_type'] == 'final_test'
        assert call_kwargs['slice_number'] == 999


class TestUnlockNextLesson:
    """Test unlock_next_lesson method"""

    @patch('app.curriculum.services.daily_slice_generator.db')
    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.UserLessonProgress')
    def test_no_completed_lessons(self, mock_progress_model, mock_lesson_model,
                                  mock_db, generator):
        """Test with no completed lessons"""
        mock_progress_model.query.filter_by.return_value.join.return_value.order_by.return_value.first.return_value = None

        # Should return early without error
        generator.unlock_next_lesson(1, 1)

        mock_db.session.commit.assert_not_called()

    @patch('app.curriculum.services.daily_slice_generator.db')
    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.UserLessonProgress')
    def test_unlocks_next_lesson(self, mock_progress_model, mock_lesson_model,
                                 mock_db, generator):
        """Test unlocking next lesson"""
        # Mock last completed
        last_completed = Mock()
        last_completed.completed_at = datetime(2025, 1, 15, 10, 0, 0)
        last_completed.daily_lesson.book_course_module_id = 1
        last_completed.daily_lesson.day_number = 1

        mock_progress_model.query.filter_by.return_value.join.return_value.order_by.return_value.first.return_value = last_completed

        # Mock next lesson
        next_lesson = Mock()
        next_lesson.available_at = datetime(2025, 1, 20, 8, 0, 0)  # Far in future
        mock_lesson_model.query.filter.return_value.filter.return_value.first.return_value = next_lesson

        generator.unlock_next_lesson(1, 1)

        # Should update available_at to 24 hours after completion
        expected_time = last_completed.completed_at + timedelta(hours=24)
        assert next_lesson.available_at == expected_time
        mock_db.session.commit.assert_called_once()

    @patch('app.curriculum.services.daily_slice_generator.DailyLesson')
    @patch('app.curriculum.services.daily_slice_generator.UserLessonProgress')
    def test_no_next_lesson(self, mock_progress_model, mock_lesson_model, generator):
        """Test when there is no next lesson"""
        last_completed = Mock()
        last_completed.daily_lesson.book_course_module_id = 1
        last_completed.daily_lesson.day_number = 10

        mock_progress_model.query.filter_by.return_value.join.return_value.order_by.return_value.first.return_value = last_completed
        mock_lesson_model.query.filter.return_value.filter.return_value.first.return_value = None

        # Should not error
        generator.unlock_next_lesson(1, 1)
