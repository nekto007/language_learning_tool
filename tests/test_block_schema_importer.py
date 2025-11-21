"""Tests for BlockSchemaImporter"""
import pytest
import tempfile
import json
import yaml
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from app.curriculum.services.block_schema_importer import BlockSchemaImporter, create_example_schema


@pytest.fixture
def mock_book():
    """Create mock book"""
    book = Mock()
    book.id = 1
    book.title = "Test Book"
    return book


@pytest.fixture
def mock_chapter():
    """Create mock chapter"""
    def _create_chapter(chap_num):
        chapter = Mock()
        chapter.id = chap_num
        chapter.book_id = 1
        chapter.chap_num = chap_num
        return chapter
    return _create_chapter


@pytest.fixture
def valid_schema_data():
    """Valid schema data for testing"""
    return [
        {
            'block': 1,
            'chapters': [1, 2],
            'grammar': 'Present_Perfect',
            'focus_vocab': 'family, feelings'
        },
        {
            'block': 2,
            'chapters': [3, 4],
            'grammar': 'Past_Simple',
            'focus_vocab': 'food, animals'
        }
    ]


class TestBlockSchemaImporterInit:
    """Test __init__ method"""

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_initialization(self, mock_book_model, mock_book):
        """Test importer initialization"""
        mock_book_model.query.get_or_404.return_value = mock_book

        importer = BlockSchemaImporter(book_id=1)

        assert importer.book_id == 1
        assert importer.book == mock_book
        mock_book_model.query.get_or_404.assert_called_once_with(1)


class TestImportFromFile:
    """Test import_from_file method"""

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_import_yaml_file(self, mock_book_model, mock_book, valid_schema_data):
        """Test importing from YAML file"""
        mock_book_model.query.get_or_404.return_value = mock_book

        # Create temp YAML file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(valid_schema_data, f)
            temp_path = f.name

        try:
            importer = BlockSchemaImporter(book_id=1)

            with patch.object(importer, 'import_from_data') as mock_import:
                mock_import.return_value = True
                result = importer.import_from_file(temp_path)

                assert result is True
                mock_import.assert_called_once()
                # Verify the data structure was passed correctly
                call_args = mock_import.call_args[0][0]
                assert len(call_args) == 2
                assert call_args[0]['block'] == 1
        finally:
            Path(temp_path).unlink()

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_import_json_file(self, mock_book_model, mock_book, valid_schema_data):
        """Test importing from JSON file"""
        mock_book_model.query.get_or_404.return_value = mock_book

        # Create temp JSON file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(valid_schema_data, f)
            temp_path = f.name

        try:
            importer = BlockSchemaImporter(book_id=1)

            with patch.object(importer, 'import_from_data') as mock_import:
                mock_import.return_value = True
                result = importer.import_from_file(temp_path)

                assert result is True
                mock_import.assert_called_once()
        finally:
            Path(temp_path).unlink()

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_import_nonexistent_file(self, mock_book_model, mock_book):
        """Test importing from non-existent file"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        result = importer.import_from_file('/nonexistent/path/file.yaml')

        assert result is False

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_import_unsupported_format(self, mock_book_model, mock_book):
        """Test importing from unsupported file format"""
        mock_book_model.query.get_or_404.return_value = mock_book

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("some content")
            temp_path = f.name

        try:
            importer = BlockSchemaImporter(book_id=1)
            result = importer.import_from_file(temp_path)

            assert result is False
        finally:
            Path(temp_path).unlink()


class TestImportFromData:
    """Test import_from_data method"""

    @patch('app.curriculum.services.block_schema_importer.db')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_successful_import(self, mock_book_model, mock_db, mock_book, valid_schema_data):
        """Test successful data import"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        with patch.object(importer, '_validate_schema') as mock_validate, \
             patch.object(importer, '_clear_existing_blocks') as mock_clear, \
             patch.object(importer, '_import_block') as mock_import_block:

            mock_validate.return_value = True
            mock_import_block.return_value = True

            result = importer.import_from_data(valid_schema_data)

            assert result is True
            mock_validate.assert_called_once_with(valid_schema_data)
            mock_clear.assert_called_once()
            assert mock_import_block.call_count == 2
            mock_db.session.commit.assert_called_once()

    @patch('app.curriculum.services.block_schema_importer.db')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_import_validation_failure(self, mock_book_model, mock_db, mock_book, valid_schema_data):
        """Test import with validation failure"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        with patch.object(importer, '_validate_schema') as mock_validate:
            mock_validate.return_value = False

            result = importer.import_from_data(valid_schema_data)

            assert result is False
            mock_db.session.commit.assert_not_called()

    @patch('app.curriculum.services.block_schema_importer.db')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_import_block_failure_triggers_rollback(self, mock_book_model, mock_db, mock_book, valid_schema_data):
        """Test rollback on block import failure"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        with patch.object(importer, '_validate_schema') as mock_validate, \
             patch.object(importer, '_clear_existing_blocks') as mock_clear, \
             patch.object(importer, '_import_block') as mock_import_block:

            mock_validate.return_value = True
            mock_import_block.return_value = False  # Simulate failure

            result = importer.import_from_data(valid_schema_data)

            assert result is False
            mock_db.session.rollback.assert_called_once()


class TestValidateSchema:
    """Test _validate_schema method"""

    @patch('app.curriculum.services.block_schema_importer.Chapter')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_valid_schema(self, mock_book_model, mock_chapter_model, mock_book, mock_chapter, valid_schema_data):
        """Test validation of valid schema"""
        mock_book_model.query.get_or_404.return_value = mock_book

        # Mock chapters exist
        mock_chapter_model.query.filter_by.return_value.first.side_effect = [
            mock_chapter(1), mock_chapter(2), mock_chapter(3), mock_chapter(4)
        ]

        importer = BlockSchemaImporter(book_id=1)
        result = importer._validate_schema(valid_schema_data)

        assert result is True

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_schema_not_list(self, mock_book_model, mock_book):
        """Test validation with non-list schema"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        result = importer._validate_schema({'block': 1})

        assert result is False

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_schema_block_not_dict(self, mock_book_model, mock_book):
        """Test validation with non-dict block"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        result = importer._validate_schema([1, 2, 3])

        assert result is False

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_missing_required_fields(self, mock_book_model, mock_book):
        """Test validation with missing required fields"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        invalid_schema = [{'block': 1}]  # Missing 'chapters'
        result = importer._validate_schema(invalid_schema)

        assert result is False

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_invalid_block_number(self, mock_book_model, mock_book):
        """Test validation with invalid block number"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        invalid_schema = [
            {'block': 0, 'chapters': [1, 2]}  # Block must be positive
        ]
        result = importer._validate_schema(invalid_schema)

        assert result is False

    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_empty_chapters_list(self, mock_book_model, mock_book):
        """Test validation with empty chapters list"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        invalid_schema = [{'block': 1, 'chapters': []}]
        result = importer._validate_schema(invalid_schema)

        assert result is False

    @patch('app.curriculum.services.block_schema_importer.Chapter')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_invalid_chapter_number(self, mock_book_model, mock_chapter_model, mock_book):
        """Test validation with invalid chapter number"""
        mock_book_model.query.get_or_404.return_value = mock_book
        importer = BlockSchemaImporter(book_id=1)

        invalid_schema = [{'block': 1, 'chapters': [1, -5]}]  # Negative chapter
        result = importer._validate_schema(invalid_schema)

        assert result is False

    @patch('app.curriculum.services.block_schema_importer.Chapter')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_nonexistent_chapter(self, mock_book_model, mock_chapter_model, mock_book):
        """Test validation with reference to non-existent chapter"""
        mock_book_model.query.get_or_404.return_value = mock_book
        mock_chapter_model.query.filter_by.return_value.first.return_value = None

        importer = BlockSchemaImporter(book_id=1)

        schema = [{'block': 1, 'chapters': [999]}]
        result = importer._validate_schema(schema)

        assert result is False


class TestClearExistingBlocks:
    """Test _clear_existing_blocks method"""

    @patch('app.curriculum.services.block_schema_importer.db')
    @patch('app.curriculum.services.block_schema_importer.Block')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_clears_blocks(self, mock_book_model, mock_block_model, mock_db, mock_book):
        """Test clearing existing blocks"""
        mock_book_model.query.get_or_404.return_value = mock_book

        block1 = Mock()
        block2 = Mock()
        mock_block_model.query.filter_by.return_value.all.return_value = [block1, block2]

        importer = BlockSchemaImporter(book_id=1)
        importer._clear_existing_blocks()

        assert mock_db.session.delete.call_count == 2
        mock_db.session.delete.assert_any_call(block1)
        mock_db.session.delete.assert_any_call(block2)


class TestImportBlock:
    """Test _import_block method"""

    @patch('app.curriculum.services.block_schema_importer.db')
    @patch('app.curriculum.services.block_schema_importer.BlockChapter')
    @patch('app.curriculum.services.block_schema_importer.Chapter')
    @patch('app.curriculum.services.block_schema_importer.Block')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_successful_block_import(self, mock_book_model, mock_block_model, mock_chapter_model,
                                     mock_block_chapter_model, mock_db, mock_book, mock_chapter):
        """Test successful block import"""
        mock_book_model.query.get_or_404.return_value = mock_book

        # Mock block creation
        mock_block = Mock()
        mock_block.id = 1
        mock_block_model.return_value = mock_block

        # Mock chapters
        ch1 = mock_chapter(1)
        ch2 = mock_chapter(2)
        mock_chapter_model.query.filter_by.return_value.first.side_effect = [ch1, ch2]

        importer = BlockSchemaImporter(book_id=1)

        block_data = {
            'block': 1,
            'chapters': [1, 2],
            'grammar': 'Present_Perfect',
            'focus_vocab': 'family'
        }

        result = importer._import_block(block_data)

        assert result is True
        mock_db.session.add.assert_called()
        mock_db.session.flush.assert_called_once()

    @patch('app.curriculum.services.block_schema_importer.db')
    @patch('app.curriculum.services.block_schema_importer.Block')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_block_import_exception(self, mock_book_model, mock_block_model, mock_db, mock_book):
        """Test block import with exception"""
        mock_book_model.query.get_or_404.return_value = mock_book
        mock_block_model.side_effect = Exception('Database error')

        importer = BlockSchemaImporter(book_id=1)

        block_data = {'block': 1, 'chapters': [1, 2]}
        result = importer._import_block(block_data)

        assert result is False


class TestGenerateDefaultSchema:
    """Test generate_default_schema method"""

    @patch('app.curriculum.services.block_schema_importer.Chapter')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_generates_schema_from_chapters(self, mock_book_model, mock_chapter_model, mock_book, mock_chapter):
        """Test generating default schema from chapters"""
        mock_book_model.query.get_or_404.return_value = mock_book

        # Mock 5 chapters
        chapters = [mock_chapter(i) for i in range(1, 6)]
        mock_chapter_model.query.filter_by.return_value.order_by.return_value.all.return_value = chapters

        importer = BlockSchemaImporter(book_id=1)
        result = importer.generate_default_schema()

        # Should create 3 blocks (2+2+1 chapters)
        assert len(result) == 3
        assert result[0]['block'] == 1
        assert result[0]['chapters'] == [1, 2]
        assert result[1]['chapters'] == [3, 4]
        assert result[2]['chapters'] == [5]

    @patch('app.curriculum.services.block_schema_importer.Chapter')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_generates_empty_schema_no_chapters(self, mock_book_model, mock_chapter_model, mock_book):
        """Test generating schema with no chapters"""
        mock_book_model.query.get_or_404.return_value = mock_book
        mock_chapter_model.query.filter_by.return_value.order_by.return_value.all.return_value = []

        importer = BlockSchemaImporter(book_id=1)
        result = importer.generate_default_schema()

        assert result == []


class TestExportSchema:
    """Test export_schema method"""

    @patch('app.curriculum.services.block_schema_importer.Block')
    @patch('app.curriculum.services.block_schema_importer.Book')
    def test_exports_existing_schema(self, mock_book_model, mock_block_model, mock_book):
        """Test exporting existing block schema"""
        mock_book_model.query.get_or_404.return_value = mock_book

        # Mock blocks with chapters
        block1 = Mock()
        block1.block_num = 1
        block1.grammar_key = 'Present_Perfect'
        block1.focus_vocab = 'family'
        ch1 = Mock(chap_num=1)
        ch2 = Mock(chap_num=2)
        block1.chapters = [ch1, ch2]

        block2 = Mock()
        block2.block_num = 2
        block2.grammar_key = None
        block2.focus_vocab = ''
        ch3 = Mock(chap_num=3)
        block2.chapters = [ch3]

        mock_block_model.query.filter_by.return_value.order_by.return_value.all.return_value = [block1, block2]

        importer = BlockSchemaImporter(book_id=1)
        result = importer.export_schema()

        assert len(result) == 2
        assert result[0]['block'] == 1
        assert result[0]['chapters'] == [1, 2]
        assert result[0]['grammar'] == 'Present_Perfect'
        assert result[1]['block'] == 2
        assert result[1]['chapters'] == [3]
        assert result[1]['grammar'] == ''


class TestCreateExampleSchema:
    """Test create_example_schema standalone function"""

    def test_creates_valid_yaml(self):
        """Test creating example YAML schema"""
        result = create_example_schema("My Test Book")

        assert "My Test Book" in result
        assert "block:" in result or "block: 1" in result
        assert "chapters:" in result

    def test_yaml_is_parseable(self):
        """Test that generated YAML can be parsed"""
        result = create_example_schema()

        # Extract just the YAML content (after comments)
        yaml_content = result.split('\n\n')[-1]
        parsed = yaml.safe_load(yaml_content)

        assert isinstance(parsed, list)
        assert len(parsed) == 3
        assert parsed[0]['block'] == 1
        assert parsed[0]['chapters'] == [1, 2]
