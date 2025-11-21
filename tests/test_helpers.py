"""Unit tests for helpers.py utility functions"""
import pytest
import os
import tempfile
import logging
from app.utils.helpers import (
    setup_logging,
    ensure_directory_exists,
    count_word_frequency,
    create_backup,
    load_text_file,
    save_text_file,
    parse_csv_line,
    url_params_with_updated_args
)


class TestSetupLogging:
    """Test setup_logging function"""

    def test_setup_logging_default_level(self):
        """Test setting up logging with default INFO level"""
        # Create a separate logger to test setup_logging
        test_logger = logging.getLogger('test_default')
        test_logger.handlers.clear()

        # Since setup_logging affects root logger, we test it doesn't raise errors
        # and that invalid levels do raise errors (tested in another test)
        try:
            setup_logging(log_level="INFO")
            # If no exception raised, test passes
            assert True
        except Exception as e:
            pytest.fail(f"setup_logging raised unexpected exception: {e}")

    def test_setup_logging_debug_level(self):
        """Test setting up logging with DEBUG level"""
        try:
            setup_logging(log_level="DEBUG")
            # If no exception raised, test passes
            assert True
        except Exception as e:
            pytest.fail(f"setup_logging raised unexpected exception: {e}")

    def test_setup_logging_warning_level(self):
        """Test setting up logging with WARNING level"""
        try:
            setup_logging(log_level="WARNING")
            # If no exception raised, test passes
            assert True
        except Exception as e:
            pytest.fail(f"setup_logging raised unexpected exception: {e}")

    def test_setup_logging_error_level(self):
        """Test setting up logging with ERROR level"""
        try:
            setup_logging(log_level="ERROR")
            # If no exception raised, test passes
            assert True
        except Exception as e:
            pytest.fail(f"setup_logging raised unexpected exception: {e}")

    def test_setup_logging_invalid_level(self):
        """Test error with invalid log level"""
        with pytest.raises(ValueError, match="Invalid log level"):
            setup_logging(log_level="INVALID")

    def test_setup_logging_with_file(self):
        """Test setting up logging with file handler"""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.log') as tmp:
            log_file = tmp.name

        try:
            setup_logging(log_level="INFO", log_file=log_file)
            # Verify file was created
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_setup_logging_with_invalid_file_path(self):
        """Test logging setup with invalid file path"""
        # Should not raise error, just skip file handler
        try:
            setup_logging(log_level="INFO", log_file="/nonexistent/path/test.log")
            # If no exception raised, test passes
            assert True
        except Exception as e:
            pytest.fail(f"setup_logging raised unexpected exception: {e}")


class TestEnsureDirectoryExists:
    """Test ensure_directory_exists function"""

    def test_ensure_directory_exists_creates_directory(self):
        """Test creating new directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = os.path.join(tmpdir, 'test_subdir')

            result = ensure_directory_exists(test_dir)

            assert result is True
            assert os.path.exists(test_dir)
            assert os.path.isdir(test_dir)

    def test_ensure_directory_exists_already_exists(self):
        """Test with existing directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ensure_directory_exists(tmpdir)

            assert result is True

    def test_ensure_directory_exists_nested_directories(self):
        """Test creating nested directories"""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = os.path.join(tmpdir, 'level1', 'level2', 'level3')

            result = ensure_directory_exists(nested_dir)

            assert result is True
            assert os.path.exists(nested_dir)


class TestCountWordFrequency:
    """Test count_word_frequency function"""

    def test_count_word_frequency_basic(self):
        """Test counting word frequencies"""
        words = ['apple', 'banana', 'apple', 'cherry', 'banana', 'apple']

        result = count_word_frequency(words)

        assert result == {'apple': 3, 'banana': 2, 'cherry': 1}

    def test_count_word_frequency_empty_list(self):
        """Test with empty list"""
        result = count_word_frequency([])

        assert result == {}

    def test_count_word_frequency_single_word(self):
        """Test with single word"""
        result = count_word_frequency(['hello'])

        assert result == {'hello': 1}

    def test_count_word_frequency_all_unique(self):
        """Test with all unique words"""
        words = ['one', 'two', 'three', 'four']

        result = count_word_frequency(words)

        assert result == {'one': 1, 'two': 1, 'three': 1, 'four': 1}

    def test_count_word_frequency_case_sensitive(self):
        """Test that counting is case-sensitive"""
        words = ['Apple', 'apple', 'APPLE']

        result = count_word_frequency(words)

        assert result == {'Apple': 1, 'apple': 1, 'APPLE': 1}


class TestCreateBackup:
    """Test create_backup function"""

    def test_create_backup_success(self):
        """Test successfully creating backup"""
        with tempfile.NamedTemporaryFile(delete=False, mode='w') as tmp:
            tmp.write('test content')
            tmp_path = tmp.name

        try:
            backup_path = create_backup(tmp_path)

            assert backup_path is not None
            assert os.path.exists(backup_path)
            assert backup_path.startswith(tmp_path)
            assert backup_path.endswith('.bak')

            # Verify content
            with open(backup_path, 'r') as f:
                assert f.read() == 'test content'
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if backup_path and os.path.exists(backup_path):
                os.unlink(backup_path)

    def test_create_backup_nonexistent_file(self):
        """Test creating backup of nonexistent file"""
        result = create_backup('/nonexistent/file.txt')

        assert result is None

    def test_create_backup_binary_file(self):
        """Test creating backup of binary file"""
        with tempfile.NamedTemporaryFile(delete=False, mode='wb') as tmp:
            tmp.write(b'\x00\x01\x02\x03')
            tmp_path = tmp.name

        try:
            backup_path = create_backup(tmp_path)

            assert backup_path is not None
            assert os.path.exists(backup_path)

            # Verify binary content
            with open(backup_path, 'rb') as f:
                assert f.read() == b'\x00\x01\x02\x03'
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if backup_path and os.path.exists(backup_path):
                os.unlink(backup_path)


class TestLoadTextFile:
    """Test load_text_file function"""

    def test_load_text_file_success(self):
        """Test loading text file"""
        with tempfile.NamedTemporaryFile(delete=False, mode='w') as tmp:
            tmp.write('line1\nline2\nline3\n')
            tmp_path = tmp.name

        try:
            result = load_text_file(tmp_path)

            assert result == ['line1', 'line2', 'line3']
        finally:
            os.unlink(tmp_path)

    def test_load_text_file_empty_file(self):
        """Test loading empty file"""
        with tempfile.NamedTemporaryFile(delete=False, mode='w') as tmp:
            tmp_path = tmp.name

        try:
            result = load_text_file(tmp_path)

            assert result == []
        finally:
            os.unlink(tmp_path)

    def test_load_text_file_with_whitespace(self):
        """Test that whitespace is stripped"""
        with tempfile.NamedTemporaryFile(delete=False, mode='w') as tmp:
            tmp.write('  line1  \n\tline2\t\n   line3   \n')
            tmp_path = tmp.name

        try:
            result = load_text_file(tmp_path)

            assert result == ['line1', 'line2', 'line3']
        finally:
            os.unlink(tmp_path)

    def test_load_text_file_nonexistent(self):
        """Test loading nonexistent file"""
        result = load_text_file('/nonexistent/file.txt')

        assert result is None

    def test_load_text_file_different_encoding(self):
        """Test loading file with different encoding"""
        with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='latin-1') as tmp:
            tmp.write('café\n')
            tmp_path = tmp.name

        try:
            result = load_text_file(tmp_path, encoding='latin-1')

            assert result == ['café']
        finally:
            os.unlink(tmp_path)


class TestSaveTextFile:
    """Test save_text_file function"""

    def test_save_text_file_success(self):
        """Test saving text file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, 'test.txt')
            content = ['line1', 'line2', 'line3']

            result = save_text_file(content, file_path)

            assert result is True
            assert os.path.exists(file_path)

            with open(file_path, 'r') as f:
                assert f.read() == 'line1\nline2\nline3\n'

    def test_save_text_file_creates_directory(self):
        """Test that it creates missing directories"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, 'subdir', 'test.txt')
            content = ['test']

            result = save_text_file(content, file_path)

            assert result is True
            assert os.path.exists(file_path)

    def test_save_text_file_empty_content(self):
        """Test saving empty content"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, 'empty.txt')

            result = save_text_file([], file_path)

            assert result is True
            assert os.path.exists(file_path)

            with open(file_path, 'r') as f:
                assert f.read() == ''

    def test_save_text_file_different_encoding(self):
        """Test saving with different encoding"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, 'test.txt')
            content = ['café', 'naïve']

            result = save_text_file(content, file_path, encoding='utf-8')

            assert result is True

            with open(file_path, 'r', encoding='utf-8') as f:
                assert f.read() == 'café\nnaïve\n'


class TestParseCsvLine:
    """Test parse_csv_line function"""

    def test_parse_csv_line_default_delimiter(self):
        """Test parsing CSV with default semicolon delimiter"""
        line = 'value1;value2;value3'

        result = parse_csv_line(line)

        assert result == ['value1', 'value2', 'value3']

    def test_parse_csv_line_custom_delimiter(self):
        """Test parsing CSV with custom delimiter"""
        line = 'value1,value2,value3'

        result = parse_csv_line(line, delimiter=',')

        assert result == ['value1', 'value2', 'value3']

    def test_parse_csv_line_with_whitespace(self):
        """Test that whitespace is stripped"""
        line = '  value1  ;  value2  ;  value3  '

        result = parse_csv_line(line)

        assert result == ['value1', 'value2', 'value3']

    def test_parse_csv_line_empty_values(self):
        """Test parsing with empty values"""
        line = 'value1;;value3'

        result = parse_csv_line(line)

        assert result == ['value1', '', 'value3']

    def test_parse_csv_line_single_value(self):
        """Test parsing single value"""
        line = 'value1'

        result = parse_csv_line(line)

        assert result == ['value1']


class TestUrlParamsWithUpdatedArgs:
    """Test url_params_with_updated_args function"""

    def test_url_params_add_new_parameter(self, app):
        """Test adding new parameter"""
        with app.test_request_context('/?page=1'):
            result = url_params_with_updated_args(sort='name')

            assert result == {'page': '1', 'sort': 'name'}

    def test_url_params_update_existing_parameter(self, app):
        """Test updating existing parameter"""
        with app.test_request_context('/?page=1&sort=date'):
            result = url_params_with_updated_args(page='2')

            assert result == {'page': '2', 'sort': 'date'}

    def test_url_params_remove_parameter(self, app):
        """Test removing parameter with None value"""
        with app.test_request_context('/?page=1&sort=name'):
            result = url_params_with_updated_args(sort=None)

            assert result == {'page': '1'}

    def test_url_params_multiple_updates(self, app):
        """Test updating multiple parameters at once"""
        with app.test_request_context('/?page=1&filter=active'):
            result = url_params_with_updated_args(page='2', sort='name', filter=None)

            assert result == {'page': '2', 'sort': 'name'}

    def test_url_params_empty_request_args(self, app):
        """Test with no existing parameters"""
        with app.test_request_context('/'):
            result = url_params_with_updated_args(page='1')

            assert result == {'page': '1'}

    def test_url_params_no_updates(self, app):
        """Test with no updates returns copy of existing args"""
        with app.test_request_context('/?page=1&sort=name'):
            result = url_params_with_updated_args()

            assert result == {'page': '1', 'sort': 'name'}
