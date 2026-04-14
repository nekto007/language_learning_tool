"""
Tests for app/books/parsers.py

Tests text cleaning, file parsing, and metadata extraction functions.
"""
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from app.books.parsers import (
    clean_text, parse_book_file, parse_txt,
    extract_file_metadata, process_uploaded_book
)


class TestCleanText:
    def test_empty(self):
        assert clean_text('') == ''

    def test_none(self):
        assert clean_text(None) == ''

    def test_strips_whitespace(self):
        assert clean_text('  hello  ') == 'hello'

    def test_collapses_spaces(self):
        assert clean_text('hello    world') == 'hello world'

    def test_preserves_newlines_in_tabs(self):
        result = clean_text('hello\tworld')
        assert 'hello' in result and 'world' in result

    def test_removes_site_domains(self):
        result = clean_text('Hello world - example.com')
        assert 'example.com' not in result

    def test_removes_ru_domain(self):
        result = clean_text('Some text - site.ru')
        assert 'site.ru' not in result

    def test_handles_encoding(self):
        # Should handle valid UTF-8 text
        result = clean_text('Привет мир')
        assert result == 'Привет мир'


class TestParseTxt:
    def _write_temp(self, content, encoding='utf-8'):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                         encoding=encoding, delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_simple_format(self):
        path = self._write_temp('Hello world.\n\nSecond paragraph.')
        try:
            html, wc, uc = parse_txt(path, 'simple')
            assert '<p>' in html
            assert wc >= 2
        finally:
            os.unlink(path)

    def test_enhanced_format(self):
        path = self._write_temp('Hello world.\n\nSecond paragraph.')
        try:
            html, wc, uc = parse_txt(path, 'enhanced')
            assert '<p>' in html
            assert wc >= 2
        finally:
            os.unlink(path)

    def test_auto_format(self):
        path = self._write_temp('Hello world.')
        try:
            html, wc, uc = parse_txt(path, 'auto')
            assert '<div>' in html
            assert wc >= 2
        finally:
            os.unlink(path)

    def test_chapter_detection(self):
        path = self._write_temp('Chapter 1: Introduction\n\nSome text here.')
        try:
            html, wc, uc = parse_txt(path, 'enhanced')
            assert '<h2>' in html
            assert 'Chapter 1' in html
        finally:
            os.unlink(path)

    def test_chapter_without_title(self):
        path = self._write_temp('Chapter 2\n\nSome text here.')
        try:
            html, wc, uc = parse_txt(path, 'enhanced')
            assert '<h2>' in html
        finally:
            os.unlink(path)

    def test_word_count(self):
        path = self._write_temp('one two three four five')
        try:
            html, wc, uc = parse_txt(path, 'simple')
            assert wc == 5
            assert uc == 5
        finally:
            os.unlink(path)

    def test_unique_word_count(self):
        path = self._write_temp('hello hello world hello')
        try:
            html, wc, uc = parse_txt(path, 'simple')
            assert wc == 4
            assert uc == 2
        finally:
            os.unlink(path)

    def test_empty_file(self):
        path = self._write_temp('')
        try:
            html, wc, uc = parse_txt(path, 'enhanced')
            assert wc == 0
        finally:
            os.unlink(path)

    def test_non_english_ignored_in_count(self):
        path = self._write_temp('Привет мир hello')
        try:
            html, wc, uc = parse_txt(path, 'simple')
            assert wc == 1  # Only 'hello' counted
        finally:
            os.unlink(path)

    def test_latin1_fallback(self):
        # Create a file with latin-1 encoding
        f = tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False)
        f.write('Hello café world'.encode('latin-1'))
        f.close()
        try:
            html, wc, uc = parse_txt(f.name, 'simple')
            assert wc >= 2
        finally:
            os.unlink(f.name)


class TestParseBookFile:
    def test_txt_dispatch(self):
        path = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        path.write('Hello world')
        path.close()
        try:
            html, wc, uc = parse_book_file(path.name, '.txt')
            assert wc >= 2
        finally:
            os.unlink(path.name)

    def test_txt_uppercase_ext(self):
        path = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        path.write('Hello world')
        path.close()
        try:
            html, wc, uc = parse_book_file(path.name, '.TXT')
            assert wc >= 2
        finally:
            os.unlink(path.name)

    def test_unsupported_format(self):
        with pytest.raises(ValueError, match='Unsupported'):
            parse_book_file('/fake/path', '.xyz')


class TestExtractFileMetadata:
    def test_txt_from_filename(self):
        metadata = extract_file_metadata('/path/to/My Book.txt', '.txt')
        assert metadata['title'] == 'My Book'
        assert metadata['author'] == ''

    def test_unknown_format(self):
        metadata = extract_file_metadata('/path/to/file.xyz', '.xyz')
        assert metadata['title'] == 'file'

    def test_fb2_with_nonexistent_file(self):
        metadata = extract_file_metadata('/nonexistent/file.fb2', '.fb2')
        assert metadata['title'] == ''

    def test_epub_with_nonexistent_file(self):
        metadata = extract_file_metadata('/nonexistent/file.epub', '.epub')
        assert metadata['title'] == ''

    def test_docx_with_nonexistent_file(self):
        metadata = extract_file_metadata('/nonexistent/file.docx', '.docx')
        assert metadata['title'] == ''


class TestProcessUploadedBook:
    def test_no_file(self):
        with pytest.raises(ValueError, match='Invalid file'):
            process_uploaded_book(None, 'Test')

    def test_no_filename_attr(self):
        with pytest.raises(ValueError, match='Invalid file'):
            process_uploaded_book('not a file', 'Test')

    def test_with_mock_file(self):
        mock_file = MagicMock()
        mock_file.filename = 'test.txt'

        content = 'Hello world. This is a test book.'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            temp_path = f.name

        def mock_save(path):
            import shutil
            shutil.copy(temp_path, path)

        mock_file.save = mock_save

        try:
            result = process_uploaded_book(mock_file, 'Test Book')
            assert 'content' in result
            assert result['word_count'] >= 2
            assert result['unique_words'] >= 2
        finally:
            os.unlink(temp_path)


class TestParseFb2:
    def test_valid_fb2(self):
        fb2_content = '''<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
  <description>
    <title-info>
      <book-title>Test Book</book-title>
      <author>
        <first-name>John</first-name>
        <last-name>Doe</last-name>
      </author>
    </title-info>
  </description>
  <body>
    <section>
      <title><p>Chapter One</p></title>
      <p>Hello world paragraph.</p>
      <p>Second paragraph here.</p>
    </section>
  </body>
</FictionBook>'''
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.fb2',
                                         encoding='utf-8', delete=False)
        f.write(fb2_content)
        f.close()
        try:
            html, wc, uc = parse_book_file(f.name, '.fb2')
            assert '<h2>' in html
            assert wc >= 2
        finally:
            os.unlink(f.name)

    def test_fb2_metadata(self):
        from app.books.parsers import extract_fb2_metadata
        fb2_content = '''<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
  <description>
    <title-info>
      <book-title>My Title</book-title>
      <author>
        <first-name>Jane</first-name>
        <last-name>Smith</last-name>
      </author>
    </title-info>
  </description>
  <body><section><p>text</p></section></body>
</FictionBook>'''
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.fb2',
                                         encoding='utf-8', delete=False)
        f.write(fb2_content)
        f.close()
        try:
            metadata = extract_fb2_metadata(f.name)
            assert metadata['title'] == 'My Title'
            assert 'Jane' in metadata['author']
            assert 'Smith' in metadata['author']
        finally:
            os.unlink(f.name)

    def test_fb2_invalid_xml(self):
        from app.books.parsers import extract_fb2_metadata
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.fb2', delete=False)
        f.write('not valid xml at all')
        f.close()
        try:
            metadata = extract_fb2_metadata(f.name)
            assert metadata['title'] == ''
        finally:
            os.unlink(f.name)