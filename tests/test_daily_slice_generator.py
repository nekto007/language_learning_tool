"""Tests for DailySliceGenerator v3.0"""
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
    def _create_chapter(chap_num, text="This is test text. It has sentences.", words=100):
        chapter = Mock()
        chapter.id = chap_num
        chapter.chap_num = chap_num
        chapter.text_raw = text
        chapter.words = words
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
        """Test generator initialization for v3.0"""
        # Test CEFR-based words per level (target, max)
        assert generator.WORDS_PER_LEVEL == {
            'A1': (100, 150),    # Range: 50-150 words
            'A2': (125, 200),    # Range: 50-200 words
            'B1': (400, 600),    # Range: 200-600 words
            'B2': (700, 800),    # Range: 600-800 words
            'C1': (900, 1000),   # Range: 800-1000 words
            'C2': (1050, 1200),  # Range: 900-1200 words
        }
        assert generator.WORDS_PER_LEVEL_DEFAULT == (400, 600)
        assert len(generator.PRACTICE_ROTATION) == 6
        assert generator.VOCABULARY_WORDS_PER_LESSON == 15
        assert generator.timezone.zone == 'Europe/Amsterdam'

    def test_practice_rotation_types(self, generator):
        """Test practice rotation has correct types"""
        expected_types = [
            'vocabulary',
            'grammar_focus',
            'comprehension_mcq',
            'cloze_practice',
            'vocabulary_review',
            'summary_writing',
        ]
        assert generator.PRACTICE_ROTATION == expected_types


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
    def test_generates_lesson_pairs(self, mock_db, generator, mock_module, mock_block, mock_chapter):
        """Test generating reading + practice pairs for v3.0"""
        # Create chapter with ~1600 words (should create 2 days of lessons)
        text = "This is a test sentence with words. " * 200  # ~1600 words
        ch1 = mock_chapter(1, text, 1600)
        mock_block.chapters = [ch1]

        with patch.object(generator, '_get_block_vocabulary') as mock_vocab:
            mock_vocab.return_value = {}

            result = generator.generate_slices_for_module(mock_module, mock_block)

            # Should create pairs (reading + practice) for each day + module test
            # ~1600 words / 800 per day = 2 days
            # 2 days * 2 lessons + 1 module test = 5 lessons
            assert len(result) >= 3  # At least 1 day + module test

    @patch('app.curriculum.services.daily_slice_generator.db')
    def test_sets_module_metadata(self, mock_db, generator, mock_module, mock_block, mock_chapter):
        """Test setting total_slices and days_to_complete"""
        text = "This is a test sentence with words. " * 100  # ~800 words
        ch1 = mock_chapter(1, text, 800)
        mock_block.chapters = [ch1]

        with patch.object(generator, '_get_block_vocabulary') as mock_vocab:
            mock_vocab.return_value = {}

            generator.generate_slices_for_module(mock_module, mock_block)

            # Should have metadata set
            assert mock_module.total_slices > 0
            assert mock_module.days_to_complete > 0


class TestSplitTextIntoSlices:
    """Test _split_text_into_slices method"""

    def test_splits_text_at_sentence_boundaries(self, generator, mock_chapter):
        """Test text is split at sentence boundaries"""
        # Create text with multiple sentences (~2000 words)
        # "This is sentence one. " = 5 words, * 200 = 1000 words
        text = "This is sentence one. " * 200 + "This is sentence two. " * 200
        chapters = [mock_chapter(1, text)]

        # target=700, max=800 (B2 level)
        slices = generator._split_text_into_slices(text, 700, 800, chapters)

        # Should create multiple slices (~2000 words / 700 = ~3 slices)
        assert len(slices) >= 2
        # Each slice should end with a complete sentence
        for slice_data in slices:
            assert slice_data['text'].strip().endswith('.')

    def test_respects_words_per_slice(self, generator, mock_chapter):
        """Test slices respect word count limit (max_words)"""
        text = "Word. " * 2000  # 2000 words
        chapters = [mock_chapter(1, text)]

        # target=700, max=800 (B2 level)
        slices = generator._split_text_into_slices(text, 700, 800, chapters)

        # Each slice should not exceed max_words (800)
        for slice_data in slices[:-1]:  # Except last which may be smaller
            assert slice_data['word_count'] <= 800

    def test_includes_chapter_id(self, generator, mock_chapter):
        """Test slices include chapter_id"""
        text = "Test text. " * 100
        chapters = [mock_chapter(1, text)]

        slices = generator._split_text_into_slices(text, 400, 600, chapters)

        for slice_data in slices:
            assert 'chapter_id' in slice_data


class TestCreateReadingLesson:
    """Test _create_reading_lesson method"""

    def test_creates_reading_lesson(self, generator, mock_module):
        """Test creating reading lesson"""
        slice_data = {
            'text': 'Test text for reading.',
            'word_count': 100,
            'start_position': 0,
            'end_position': 100,
            'chapter_id': 1
        }

        lesson = generator._create_reading_lesson(mock_module, 1, slice_data)

        assert lesson.lesson_type == 'reading'
        assert lesson.word_count == 100
        assert lesson.slice_text == 'Test text for reading.'

    def test_first_day_immediately_available(self, generator, mock_module):
        """Test day 1 lesson has no availability restriction"""
        slice_data = {
            'text': 'Test',
            'word_count': 10,
            'start_position': 0,
            'end_position': 10,
            'chapter_id': 1
        }

        lesson = generator._create_reading_lesson(mock_module, 1, slice_data)

        assert lesson.available_at is None


class TestCreatePracticeLesson:
    """Test _create_practice_lesson method"""

    def test_creates_practice_lesson(self, generator, mock_module):
        """Test creating practice lesson"""
        slice_data = {
            'text': 'Test text for practice.',
            'word_count': 100,
            'start_position': 0,
            'end_position': 100,
            'chapter_id': 1
        }

        lesson = generator._create_practice_lesson(
            mock_module, 1, 'vocabulary', slice_data, {}
        )

        assert lesson.lesson_type == 'vocabulary'
        assert lesson.word_count == 0  # Practice lessons have 0 word count

    def test_truncates_long_text(self, generator, mock_module):
        """Test long text is truncated for practice lessons"""
        long_text = "x" * 1000
        slice_data = {
            'text': long_text,
            'word_count': 500,
            'start_position': 0,
            'end_position': 1000,
            'chapter_id': 1
        }

        lesson = generator._create_practice_lesson(
            mock_module, 1, 'grammar_focus', slice_data, {}
        )

        assert len(lesson.slice_text) <= 503  # 500 + "..."


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
        """Test limiting to VOCABULARY_WORDS_PER_LESSON"""
        daily_lesson = Mock(id=1)
        text = " ".join([f"word{i}" for i in range(20)])  # 20 words

        # Create 20 vocabulary entries (more than limit of 15)
        block_vocabulary = {}
        for i in range(20):
            block_vocabulary[i] = {
                'english': f'word{i}',
                'russian': f'слово{i}',
                'frequency': i,
                'word': Mock()
            }

        generator._extract_slice_vocabulary(daily_lesson, text, block_vocabulary)

        # Should only add up to 15 words (VOCABULARY_WORDS_PER_LESSON)
        assert mock_db.session.add.call_count <= generator.VOCABULARY_WORDS_PER_LESSON

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
