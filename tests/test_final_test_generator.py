"""Tests for FinalTestGenerator"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.curriculum.services.final_test_generator import (
    FinalTestGenerator,
    generate_final_tests_for_book
)


@pytest.fixture
def generator():
    """Create FinalTestGenerator instance"""
    return FinalTestGenerator()


@pytest.fixture
def mock_block():
    """Create mock Block"""
    block = Mock()
    block.id = 10
    block.block_num = 1
    block.grammar_key = "Present_Perfect"
    block.focus_vocab = "family, feelings"
    return block


@pytest.fixture
def mock_vocab_task():
    """Create mock vocabulary task"""
    task = Mock()
    task.task_type = 'vocabulary'
    task.payload = {
        'cards': [
            {'front': 'hello', 'back': {'definition': 'greeting'}},
            {'front': 'world', 'back': {'definition': 'planet Earth'}},
            {'front': 'test', 'back': {'definition': 'examination'}},
        ]
    }
    return task


@pytest.fixture
def mock_reading_task():
    """Create mock reading MCQ task"""
    task = Mock()
    task.task_type = 'reading_mcq'
    task.payload = {
        'passage': 'This is a test passage.',
        'questions': [
            {
                'question': 'What is this?',
                'options': ['A passage', 'A book', 'A test', 'Nothing'],
                'correct_answer': 0,
                'explanation': 'It is a passage'
            }
        ]
    }
    return task


class TestInit:
    """Test __init__ method"""

    def test_initialization(self, generator):
        """Test generator initialization"""
        assert generator.target_question_count == 34
        assert generator.min_questions == 32
        assert generator.max_questions == 36


class TestGenerateFinalTest:
    """Test generate_final_test method"""

    @patch('app.curriculum.services.final_test_generator.Task')
    @patch('app.curriculum.services.final_test_generator.Block')
    def test_generates_test_successfully(self, mock_block_model, mock_task_model,
                                        generator, mock_block):
        """Test successful test generation"""
        mock_block_model.query.get_or_404.return_value = mock_block
        mock_task_model.query.filter_by.return_value.all.return_value = []

        with patch.object(generator, '_generate_test_sections') as mock_sections:
            mock_sections.return_value = [
                {
                    'type': 'vocabulary',
                    'title': 'Vocabulary',
                    'instructions': 'Test instructions',
                    'questions': [
                        {'type': 'multiple_choice', 'points': 1}
                    ]
                }
            ]

            result = generator.generate_final_test(10)

            assert result is not None
            assert result['type'] == 'final_test'
            assert 'Block 1' in result['title']
            assert 'questions' in result
            assert result['metadata']['block_id'] == 10

    @patch('app.curriculum.services.final_test_generator.Task')
    @patch('app.curriculum.services.final_test_generator.Block')
    def test_returns_none_no_sections(self, mock_block_model, mock_task_model,
                                     generator, mock_block):
        """Test returns None when no sections generated"""
        mock_block_model.query.get_or_404.return_value = mock_block
        mock_task_model.query.filter_by.return_value.all.return_value = []

        with patch.object(generator, '_generate_test_sections') as mock_sections:
            mock_sections.return_value = []

            result = generator.generate_final_test(10)

            assert result is None

    @patch('app.curriculum.services.final_test_generator.Task')
    @patch('app.curriculum.services.final_test_generator.Block')
    def test_handles_exception(self, mock_block_model, mock_task_model, generator):
        """Test exception handling"""
        mock_block_model.query.get_or_404.side_effect = Exception("Database error")

        result = generator.generate_final_test(10)

        assert result is None


class TestGenerateTestSections:
    """Test _generate_test_sections method"""

    def test_creates_multiple_sections(self, generator, mock_block):
        """Test creating multiple test sections"""
        with patch.object(generator, '_create_vocabulary_section') as mock_vocab, \
             patch.object(generator, '_create_reading_comprehension_section') as mock_reading, \
             patch.object(generator, '_create_grammar_section') as mock_grammar, \
             patch.object(generator, '_create_completion_section') as mock_completion, \
             patch.object(generator, '_create_word_formation_section') as mock_word_form:

            mock_vocab.return_value = {'type': 'vocabulary', 'questions': []}
            mock_reading.return_value = {'type': 'reading', 'questions': []}
            mock_grammar.return_value = {'type': 'grammar', 'questions': []}
            mock_completion.return_value = None
            mock_word_form.return_value = None

            result = generator._generate_test_sections(mock_block, {})

            assert len(result) == 3
            mock_vocab.assert_called_once()
            mock_reading.assert_called_once()
            mock_grammar.assert_called_once()


class TestCreateVocabularySection:
    """Test _create_vocabulary_section method"""

    def test_creates_from_task(self, generator, mock_block, mock_vocab_task):
        """Test creating vocabulary section from task"""
        task_map = {'vocabulary': mock_vocab_task}

        with patch.object(generator, '_generate_vocab_options') as mock_options, \
             patch.object(generator, '_shuffle_options') as mock_shuffle:

            mock_options.return_value = ['option1', 'option2', 'option3', 'option4']

            result = generator._create_vocabulary_section(mock_block, task_map)

            assert result is not None
            assert result['type'] == 'vocabulary'
            assert len(result['questions']) <= 10
            assert all(q['type'] == 'multiple_choice' for q in result['questions'])

    def test_creates_basic_section_no_task(self, generator, mock_block):
        """Test creating basic vocabulary section without task"""
        task_map = {}

        with patch.object(generator, '_create_basic_vocabulary_section') as mock_basic:
            mock_basic.return_value = {
                'type': 'vocabulary',
                'questions': [{'type': 'multiple_choice'}]
            }

            result = generator._create_vocabulary_section(mock_block, task_map)

            mock_basic.assert_called_once_with(mock_block)
            assert result is not None


class TestCreateBasicVocabularySection:
    """Test _create_basic_vocabulary_section method"""

    @patch('app.curriculum.services.final_test_generator.BlockVocab')
    def test_creates_from_block_vocab(self, mock_vocab_model, generator, mock_block):
        """Test creating from block vocabulary"""
        # Mock vocabulary entry
        vocab_entry = Mock()
        vocab_entry.word = Mock(
            english_word='hello',
            russian_word='привет'
        )

        mock_vocab_model.query.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [
            vocab_entry
        ]

        result = generator._create_basic_vocabulary_section(mock_block)

        assert result is not None
        assert result['type'] == 'vocabulary'
        assert len(result['questions']) == 1
        assert 'hello' in result['questions'][0]['question']

    @patch('app.curriculum.services.final_test_generator.BlockVocab')
    def test_returns_none_no_vocab(self, mock_vocab_model, generator, mock_block):
        """Test returns None when no vocabulary"""
        mock_vocab_model.query.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = generator._create_basic_vocabulary_section(mock_block)

        assert result is None

    @patch('app.curriculum.services.final_test_generator.BlockVocab')
    def test_skips_entries_without_word(self, mock_vocab_model, generator, mock_block):
        """Test skipping entries without word"""
        vocab_entry = Mock()
        vocab_entry.word = None

        mock_vocab_model.query.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [
            vocab_entry
        ]

        result = generator._create_basic_vocabulary_section(mock_block)

        # Should return empty section or None
        assert result is None or len(result['questions']) == 0


class TestCreateReadingComprehensionSection:
    """Test _create_reading_comprehension_section method"""

    def test_creates_from_mcq_task(self, generator, mock_block, mock_reading_task):
        """Test creating from reading MCQ task"""
        task_map = {'reading_mcq': mock_reading_task}

        result = generator._create_reading_comprehension_section(mock_block, task_map)

        assert result is not None
        assert result['type'] == 'reading_comprehension'
        assert 'passage' in result
        assert len(result['questions']) == 1
        assert result['questions'][0]['points'] == 2  # Reading worth more

    def test_limits_questions_to_8(self, generator, mock_block):
        """Test limiting questions to 8"""
        reading_task = Mock()
        reading_task.payload = {
            'passage': 'Test passage',
            'questions': [{'question': f'Q{i}'} for i in range(15)]
        }
        task_map = {'reading_mcq': reading_task}

        result = generator._create_reading_comprehension_section(mock_block, task_map)

        assert len(result['questions']) == 8

    def test_returns_none_no_task(self, generator, mock_block):
        """Test returns None when no reading task"""
        result = generator._create_reading_comprehension_section(mock_block, {})

        assert result is None


class TestCreateGrammarSection:
    """Test _create_grammar_section method"""

    def test_creates_from_keyword_transform_task(self, generator, mock_block):
        """Test creating from keyword transformation task"""
        kt_task = Mock()
        kt_task.payload = {
            'questions': [
                {
                    'sentence1': 'I started work here 5 years ago.',
                    'keyword': 'been',
                    'sentence2': "I've _____ here for 5 years.",
                    'answer': 'been working'
                }
            ]
        }
        task_map = {'keyword_transform': kt_task}

        result = generator._create_grammar_section(mock_block, task_map)

        assert result is not None
        assert result['type'] == 'grammar'
        assert len(result['questions']) >= 1
        assert result['questions'][0]['points'] == 2

    def test_adds_grammar_questions_from_block(self, generator, mock_block):
        """Test adding grammar questions based on block focus"""
        with patch.object(generator, '_generate_grammar_questions') as mock_grammar:
            mock_grammar.return_value = [
                {'type': 'grammar', 'points': 1}
            ]

            result = generator._create_grammar_section(mock_block, {})

            assert result is not None
            mock_grammar.assert_called_with('Present_Perfect')

    def test_returns_none_no_questions(self, generator):
        """Test returns None when no questions can be generated"""
        block = Mock(grammar_key=None)

        with patch.object(generator, '_generate_grammar_questions') as mock_grammar:
            mock_grammar.return_value = []

            result = generator._create_grammar_section(block, {})

            assert result is None


class TestCreateScoringSystem:
    """Test _create_scoring_system method"""

    def test_calculates_total_points(self, generator):
        """Test calculating total points"""
        sections = [
            {
                'type': 'vocabulary',
                'questions': [{'points': 1}, {'points': 1}, {'points': 1}]
            },
            {
                'type': 'reading',
                'questions': [{'points': 2}, {'points': 2}]
            }
        ]

        result = generator._create_scoring_system(sections)

        assert result['total_points'] == 7  # 3 + 4
        assert result['section_points']['vocabulary'] == 3
        assert result['section_points']['reading'] == 4
        assert result['pass_percentage'] == 70
        assert 'grading_scale' in result


class TestCalculateTimeLimit:
    """Test _calculate_time_limit method"""

    def test_calculates_time_limit(self, generator):
        """Test time limit calculation"""
        result = generator._calculate_time_limit(20)

        # 20 questions * 2 minutes = 40, but minimum is 45
        assert result == 45

    def test_respects_minimum(self, generator):
        """Test minimum time limit"""
        result = generator._calculate_time_limit(10)

        assert result == 45

    def test_scales_with_questions(self, generator):
        """Test scaling with question count"""
        result = generator._calculate_time_limit(50)

        assert result == 100  # 50 * 2


class TestGetTestInstructions:
    """Test _get_test_instructions method"""

    def test_returns_instructions(self, generator):
        """Test getting test instructions"""
        result = generator._get_test_instructions()

        assert isinstance(result, str)
        assert len(result) > 0
        assert 'comprehensive test' in result.lower()
        assert 'instructions' in result.lower()


class TestSaveFinalTestTask:
    """Test save_final_test_task method"""

    @patch('app.books.models.TaskType')
    @patch('app.curriculum.services.final_test_generator.db')
    @patch('app.curriculum.services.final_test_generator.Task')
    def test_creates_new_task(self, mock_task_model, mock_db, mock_task_type, generator):
        """Test creating new final test task"""
        mock_task_type.final_test = 'final_test'
        mock_task_model.query.filter_by.return_value.first.return_value = None

        with patch.object(generator, 'generate_final_test') as mock_generate:
            mock_generate.return_value = {'type': 'final_test', 'questions': []}

            result = generator.save_final_test_task(10)

            assert result is True
            mock_db.session.add.assert_called_once()
            mock_db.session.commit.assert_called_once()

    @patch('app.books.models.TaskType')
    @patch('app.curriculum.services.final_test_generator.db')
    @patch('app.curriculum.services.final_test_generator.Task')
    def test_updates_existing_task(self, mock_task_model, mock_db, mock_task_type, generator):
        """Test updating existing final test task"""
        mock_task_type.final_test = 'final_test'

        existing_task = Mock()
        mock_task_model.query.filter_by.return_value.first.return_value = existing_task

        with patch.object(generator, 'generate_final_test') as mock_generate:
            mock_generate.return_value = {'type': 'final_test', 'questions': []}

            result = generator.save_final_test_task(10)

            assert result is True
            assert existing_task.payload == mock_generate.return_value
            mock_db.session.add.assert_not_called()  # Not adding new, updating existing
            mock_db.session.commit.assert_called_once()

    @patch('app.books.models.TaskType')
    @patch('app.curriculum.services.final_test_generator.db')
    @patch('app.curriculum.services.final_test_generator.Task')
    def test_returns_false_no_payload(self, mock_task_model, mock_db, mock_task_type, generator):
        """Test returns False when generation fails"""
        mock_task_type.final_test = 'final_test'
        mock_task_model.query.filter_by.return_value.first.return_value = None

        with patch.object(generator, 'generate_final_test') as mock_generate:
            mock_generate.return_value = None

            result = generator.save_final_test_task(10)

            assert result is False
            mock_db.session.add.assert_not_called()

    @patch('app.books.models.TaskType')
    @patch('app.curriculum.services.final_test_generator.db')
    @patch('app.curriculum.services.final_test_generator.Task')
    def test_rolls_back_on_error(self, mock_task_model, mock_db, mock_task_type, generator):
        """Test rollback on database error"""
        mock_task_type.final_test = 'final_test'
        mock_task_model.query.filter_by.side_effect = Exception("Database error")

        result = generator.save_final_test_task(10)

        assert result is False
        mock_db.session.rollback.assert_called_once()


class TestGenerateFinalTestsForBook:
    """Test generate_final_tests_for_book utility function"""

    @patch('app.books.models.Book')
    @patch('app.curriculum.services.final_test_generator.Block')
    def test_generates_for_all_blocks(self, mock_block_model, mock_book_model):
        """Test generating tests for all blocks in book"""
        mock_book = Mock(id=1)
        mock_book_model.query.get.return_value = mock_book

        block1 = Mock(id=1)
        block2 = Mock(id=2)
        mock_block_model.query.filter_by.return_value.all.return_value = [block1, block2]

        with patch.object(FinalTestGenerator, 'save_final_test_task') as mock_save:
            mock_save.return_value = True

            result = generate_final_tests_for_book(1)

            assert result == 2
            assert mock_save.call_count == 2

    @patch('app.books.models.Book')
    def test_returns_zero_book_not_found(self, mock_book_model):
        """Test returns 0 when book not found"""
        mock_book_model.query.get.return_value = None

        result = generate_final_tests_for_book(999)

        assert result == 0

    @patch('app.books.models.Book')
    @patch('app.curriculum.services.final_test_generator.Block')
    def test_counts_failures(self, mock_block_model, mock_book_model):
        """Test counting successful vs failed generations"""
        mock_book = Mock(id=1)
        mock_book_model.query.get.return_value = mock_book

        block1 = Mock(id=1)
        block2 = Mock(id=2)
        block3 = Mock(id=3)
        mock_block_model.query.filter_by.return_value.all.return_value = [block1, block2, block3]

        with patch.object(FinalTestGenerator, 'save_final_test_task') as mock_save:
            # First succeeds, second fails, third succeeds
            mock_save.side_effect = [True, False, True]

            result = generate_final_tests_for_book(1)

            assert result == 2  # 2 out of 3 succeeded
