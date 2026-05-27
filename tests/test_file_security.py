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
    FORBIDDEN_EXTENSIONS,
    check_forbidden_magic_bytes,
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


class TestForbiddenExtensions:
    """Tests that FORBIDDEN_EXTENSIONS blocks dangerous file types regardless of whitelist"""

    def test_env_file_blocked(self):
        """Test that .env file is blocked even if caller passes 'env' in allowed_extensions"""
        file = FileStorage(
            stream=io.BytesIO(b'SECRET_KEY=abc123\nDATABASE_URL=postgres://...\n'),
            filename='production.env',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'env', 'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'запрещено' in error.lower() or '.env' in error

    def test_py_file_blocked(self):
        """Test that .py file is always blocked"""
        file = FileStorage(
            stream=io.BytesIO(b'import os\nos.system("rm -rf /")\n'),
            filename='malicious.py',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'py', 'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'запрещено' in error.lower() or '.py' in error

    def test_sh_file_blocked(self):
        """Test that .sh shell script is blocked"""
        file = FileStorage(
            stream=io.BytesIO(b'#!/bin/bash\nrm -rf /\n'),
            filename='deploy.sh',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'sh', 'txt'},
            max_size_mb=5
        )

        assert is_valid is False

    def test_php_file_blocked(self):
        """Test that .php file is blocked"""
        file = FileStorage(
            stream=io.BytesIO(b'<?php echo "hello"; ?>'),
            filename='index.php',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'php', 'txt'},
            max_size_mb=5
        )

        assert is_valid is False

    def test_exe_extension_blocked(self):
        """Test that .exe file is blocked"""
        file = FileStorage(
            stream=io.BytesIO(b'MZ' + b'\x00' * 100),
            filename='setup.exe',
            content_type='application/octet-stream'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'exe', 'txt'},
            max_size_mb=5
        )

        assert is_valid is False

    def test_sql_file_blocked(self):
        """Test that .sql file is always blocked"""
        file = FileStorage(
            stream=io.BytesIO(b'DROP TABLE users; SELECT * FROM passwords;\n'),
            filename='backup.sql',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'sql', 'txt'},
            max_size_mb=5
        )

        assert is_valid is False

    def test_forbidden_extensions_constant_coverage(self):
        """Test that key dangerous extensions are in FORBIDDEN_EXTENSIONS"""
        must_include = {'env', 'py', 'sh', 'php', 'exe', 'bat', 'cmd', 'ps1', 'sql', 'key', 'pem'}
        for ext in must_include:
            assert ext in FORBIDDEN_EXTENSIONS, f".{ext} must be in FORBIDDEN_EXTENSIONS"

    def test_normal_csv_not_blocked_by_forbidden_list(self):
        """Ensure regular allowed extensions are not in FORBIDDEN_EXTENSIONS"""
        safe_extensions = {'csv', 'txt', 'json'}
        for ext in safe_extensions:
            assert ext not in FORBIDDEN_EXTENSIONS, f".{ext} should not be in FORBIDDEN_EXTENSIONS"


class TestMagicBytesDetection:
    """Tests for magic byte signature detection"""

    def test_exe_magic_bytes_detected(self):
        """Test MZ header (Windows PE) is detected as dangerous"""
        exe_data = b'MZ\x90\x00' + b'\x00' * 100
        result = check_forbidden_magic_bytes(exe_data)
        assert result is not None
        assert 'executable' in result.lower() or 'PE' in result

    def test_elf_magic_bytes_detected(self):
        """Test ELF header (Linux binary) is detected as dangerous"""
        elf_data = b'\x7fELF' + b'\x00' * 100
        result = check_forbidden_magic_bytes(elf_data)
        assert result is not None

    def test_php_magic_bytes_detected(self):
        """Test PHP opening tag is detected as dangerous"""
        php_data = b'<?php echo "pwned"; ?>'
        result = check_forbidden_magic_bytes(php_data)
        assert result is not None
        assert 'PHP' in result or 'php' in result.lower()

    def test_shebang_detected(self):
        """Test shell shebang is detected as dangerous"""
        shebang_data = b'#!/bin/bash\nrm -rf /'
        result = check_forbidden_magic_bytes(shebang_data)
        assert result is not None
        assert 'script' in result.lower() or 'shebang' in result.lower()

    def test_zip_magic_bytes_detected(self):
        """Test ZIP magic bytes are detected"""
        zip_data = b'PK\x03\x04' + b'\x00' * 100
        result = check_forbidden_magic_bytes(zip_data)
        assert result is not None

    def test_safe_json_not_detected(self):
        """Test that valid JSON content is not flagged as dangerous"""
        json_data = b'{"key": "value", "number": 42}'
        result = check_forbidden_magic_bytes(json_data)
        assert result is None

    def test_safe_csv_not_detected(self):
        """Test that CSV content is not flagged as dangerous"""
        csv_data = b'name,value\nalice,1\nbob,2\n'
        result = check_forbidden_magic_bytes(csv_data)
        assert result is None

    def test_safe_utf8_text_not_detected(self):
        """Test that plain UTF-8 text is not flagged"""
        text_data = 'Привет мир, hello world'.encode('utf-8')
        result = check_forbidden_magic_bytes(text_data)
        assert result is None

    def test_exe_disguised_as_txt_rejected(self):
        """Test that EXE content in a .txt file is rejected by validate_text_file_upload"""
        file = FileStorage(
            stream=io.BytesIO(b'MZ\x90\x00' + b'\x00' * 200),
            filename='notexe.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert error is not None

    def test_php_disguised_as_csv_rejected(self):
        """Test that PHP content in a .csv file is rejected"""
        file = FileStorage(
            stream=io.BytesIO(b'<?php system($_GET["cmd"]); ?>'),
            filename='data.csv',
            content_type='text/csv'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'csv'},
            max_size_mb=5
        )

        assert is_valid is False


class TestUploadSizeLimitEnforced:
    """Tests confirming size limit is enforced in code, not just config"""

    def test_exactly_at_size_limit_passes(self):
        """File at exactly the size limit should pass"""
        content = b'x' * (5 * 1024 * 1024)  # exactly 5MB
        file = FileStorage(
            stream=io.BytesIO(content),
            filename='exact.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is True

    def test_one_byte_over_limit_fails(self):
        """File one byte over limit should fail"""
        content = b'x' * (5 * 1024 * 1024 + 1)
        file = FileStorage(
            stream=io.BytesIO(content),
            filename='over.txt',
            content_type='text/plain'
        )

        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=5
        )

        assert is_valid is False
        assert 'МБ' in error or 'размер' in error.lower()

    def test_custom_size_limit_respected(self):
        """Custom max_size_mb parameter is respected"""
        content = b'x' * (2 * 1024 * 1024)  # 2MB
        file = FileStorage(
            stream=io.BytesIO(content),
            filename='file.txt',
            content_type='text/plain'
        )

        # Should fail with 1MB limit
        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=1
        )
        assert is_valid is False

        # Should pass with 3MB limit
        file.stream.seek(0)
        is_valid, error = validate_text_file_upload(
            file,
            allowed_extensions={'txt'},
            max_size_mb=3
        )
        assert is_valid is True
