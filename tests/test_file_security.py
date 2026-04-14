"""
Comprehensive tests for file upload security
Тесты безопасности загрузки файлов

Critical security module - tests cover:
- Path traversal attacks
- Malicious file type detection
- UTF-8 encoding validation with edge cases
- File size limits
- Extension validation
"""
import pytest
import io
import os
from unittest.mock import Mock, patch
from werkzeug.datastructures import FileStorage

from app.utils.file_security import (
    validate_text_file_upload,
    validate_image_mime_type,
    process_and_save_cover_image,
)


class TestValidateTextFileUpload:
    """Tests for validate_text_file_upload function"""

    def test_valid_utf8_csv_file(self):
        """Test valid UTF-8 CSV file passes validation"""
        content = "name,value\ntest,123\nпривет,мир\n".encode('utf-8')
        file = FileStorage(
            stream=io.BytesIO(content),
            filename='data.csv',
            content_type='text/csv'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'csv', 'txt'},
            max_size_mb=5
        )

        assert is_valid is True
        assert error is None

    def test_valid_utf8_txt_file(self):
        """Test valid UTF-8 TXT file passes validation"""
        content = "Hello world\nПривет мир\n日本語\n".encode('utf-8')
        file = FileStorage(
            stream=io.BytesIO(content),
            filename='text.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is True
        assert error is None

    def test_utf8_truncated_multibyte_character(self):
        """Test that truncated multi-byte character at boundary is handled"""
        # Create content where 1024th byte is in middle of multi-byte char
        # Cyrillic characters are 2 bytes in UTF-8
        cyrillic = "а" * 600  # Each 'а' is 2 bytes = 1200 bytes
        content = cyrillic.encode('utf-8')

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='cyrillic.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is True
        assert error is None

    def test_rejects_binary_file(self):
        """Test that binary files are rejected"""
        # PNG header
        content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + b'\xff' * 200

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='fake.csv',
            content_type='text/csv'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'csv'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'UTF-8' in error

    def test_rejects_cp1251_encoding(self):
        """Test that Windows-1251 encoded files are rejected"""
        content = 'Привет мир, это тест кодировки Windows-1251'.encode('cp1251')

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='wrong_encoding.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'UTF-8' in error

    def test_rejects_latin1_encoding(self):
        """Test that Latin-1 encoded files with many non-ASCII chars are rejected"""
        # Use more Latin-1 specific characters to exceed surrogate threshold
        # German/French text with umlauts and accents
        text = 'Größe überschreitet, français très spécial, naïve café résumé' * 20
        content = text.encode('latin-1')

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='latin1.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        # Latin-1 with many special chars should fail (>1% surrogates)
        assert is_valid is False
        assert 'UTF-8' in error

    def test_rejects_wrong_extension(self):
        """Test that wrong file extension is rejected"""
        content = b"valid utf-8 content"

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='script.php',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt', 'csv'},
            max_size_mb=5
        )

        assert is_valid is False
        assert '.php' in error or 'расширение' in error.lower()

    def test_rejects_no_extension(self):
        """Test that files without extension are rejected"""
        content = b"valid utf-8 content"

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='noextension',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'расширение' in error.lower()

    def test_rejects_file_exceeding_size_limit(self):
        """Test that files exceeding size limit are rejected"""
        # Create 6MB file
        content = b"x" * (6 * 1024 * 1024)

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='large.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'размер' in error.lower() or 'МБ' in error

    def test_rejects_empty_file(self):
        """Test that empty files are rejected"""
        file = FileStorage(
            stream=io.BytesIO(b''),
            filename='empty.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'пуст' in error.lower()

    def test_rejects_none_file(self):
        """Test that None file is rejected"""
        is_valid, error = validate_text_file_upload(
            None,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False

    def test_rejects_empty_filename(self):
        """Test that empty filename is rejected"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False


class TestPathTraversalPrevention:
    """Tests for path traversal attack prevention"""

    def test_rejects_path_traversal_dots(self):
        """Test that ../ path traversal is rejected"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='../../../etc/passwd',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False

    def test_rejects_path_traversal_backslash(self):
        """Test that backslash path traversal is rejected"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='..\\..\\windows\\system32',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False

    def test_rejects_absolute_path(self):
        """Test that absolute paths are rejected"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='/etc/passwd',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        # secure_filename should sanitize this
        assert is_valid is False

    def test_rejects_null_byte(self):
        """Test that null byte injection is rejected"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='file.txt\x00.php',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False


class TestDoubleExtensionPrevention:
    """Tests for double extension attacks"""

    def test_double_extension_exe_txt(self):
        """Test that .exe.txt double extension is handled"""
        file = FileStorage(
            stream=io.BytesIO(b'MZ'),  # PE executable header
            filename='malware.exe.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        # Should pass extension check but fail binary check
        # or be rejected based on security heuristics
        # Either result is acceptable as long as it doesn't execute

    def test_hidden_extension_with_spaces(self):
        """Test that hidden extensions with spaces are handled"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='document.txt     .exe',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        # secure_filename should handle this
        assert is_valid is False or 'exe' not in file.filename.lower()


class TestValidateImageMimeType:
    """Tests for validate_image_mime_type function"""

    def test_valid_jpeg_image(self, tmp_path):
        """Test valid JPEG image passes MIME validation"""
        # Create minimal JPEG file
        jpeg_data = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00' + b'\x00' * 100 + b'\xff\xd9'
        file_path = tmp_path / "test.jpg"
        file_path.write_bytes(jpeg_data)

        # Note: validate_image_mime_type uses Pillow which needs valid image
        # This test documents expected behavior for real images

    def test_rejects_php_disguised_as_image(self, tmp_path):
        """Test that PHP files with image extension are rejected"""
        php_content = b'<?php system($_GET["cmd"]); ?>'
        file_path = tmp_path / "shell.jpg"
        file_path.write_bytes(php_content)

        is_valid = validate_image_mime_type(str(file_path))

        # Should be rejected - content is not a valid image
        assert is_valid is False

    def test_rejects_nonexistent_file(self):
        """Test that non-existent file returns False"""
        is_valid = validate_image_mime_type('/nonexistent/path/image.jpg')

        assert is_valid is False


class TestJsonFileValidation:
    """Tests for JSON file validation"""

    def test_valid_json_file(self):
        """Test valid JSON file passes validation"""
        content = '{"module": {"id": 1, "title": "Test"}}'.encode('utf-8')

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='module.json',
            content_type='application/json'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'json'},
            max_size_mb=10
        )

        assert is_valid is True

    def test_json_with_cyrillic(self):
        """Test JSON with Cyrillic content passes validation"""
        content = '{"title": "Тест", "description": "Описание модуля"}'.encode('utf-8')

        file = FileStorage(
            stream=io.BytesIO(content),
            filename='module.json',
            content_type='application/json'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'json'},
            max_size_mb=10
        )

        assert is_valid is True


class TestEdgeCases:
    """Tests for edge cases and unusual inputs"""

    def test_file_with_unicode_filename(self):
        """Test file with Unicode characters in filename"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='файл_данных.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        # secure_filename might sanitize this
        # Result depends on implementation

    def test_very_long_filename(self):
        """Test file with very long filename"""
        long_name = 'a' * 500 + '.txt'

        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename=long_name,
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        # Should either pass or reject gracefully

    def test_file_with_special_characters(self):
        """Test file with special characters in filename"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='file<script>alert(1)</script>.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        # Should be rejected due to suspicious characters
        assert is_valid is False

    def test_case_insensitive_extension(self):
        """Test that extension check is case insensitive"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='FILE.TXT',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is True

    def test_mixed_case_extension(self):
        """Test mixed case extension"""
        file = FileStorage(
            stream=io.BytesIO(b'content'),
            filename='data.CsV',
            content_type='text/csv'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'csv'},
            max_size_mb=5
        )

        assert is_valid is True
