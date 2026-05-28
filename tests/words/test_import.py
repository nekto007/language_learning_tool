"""Tests for bulk word import: chunk_ids usage, duplicate prevention,
invalid CSV handling, and MAX_IMPORT_ROWS limit enforcement (Task 19).
"""
import io
from unittest.mock import patch, MagicMock

import pytest

from app.admin.services.word_management_service import WordManagementService, MAX_IMPORT_ROWS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(*rows, header=False):
    """Build a semicolon-delimited CSV string. Each row is a 5-tuple."""
    lines = []
    if header:
        lines.append('english_word;russian_translate;example_en;example_ru;level')
    for row in rows:
        lines.append(';'.join(str(c) for c in row))
    return '\n'.join(lines)


_BASE_ROW = ('apple', 'яблоко', 'An apple a day.', 'Яблоко в день.', 'A1')


# ---------------------------------------------------------------------------
# 1. parse_import_file — valid CSV (baseline)
# ---------------------------------------------------------------------------

class TestParseImportFileValid:
    @pytest.mark.smoke
    def test_valid_single_row_returns_word(self, db_session):
        content = _make_csv(_BASE_ROW)
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert errors == []
        # word not in DB — should be missing
        all_words = existing + missing
        assert len(all_words) == 1
        assert all_words[0]['english_word'] == 'apple'

    def test_header_row_is_skipped(self, db_session):
        content = _make_csv(_BASE_ROW, header=True)
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert errors == []
        assert len(existing) + len(missing) == 1

    def test_comment_lines_are_skipped(self, db_session):
        content = '# comment\n' + _make_csv(_BASE_ROW)
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert len(existing) + len(missing) == 1

    def test_empty_content_returns_empty(self, db_session):
        existing, missing, errors = WordManagementService.parse_import_file('')
        assert existing == []
        assert missing == []
        assert errors == []


# ---------------------------------------------------------------------------
# 2. Invalid CSV — wrong column count → errors list, not exception
# ---------------------------------------------------------------------------

class TestParseImportFileInvalidCSV:
    @pytest.mark.smoke
    def test_wrong_column_count_gives_error_not_exception(self, db_session):
        bad_csv = 'apple;яблоко'  # only 2 columns
        existing, missing, errors = WordManagementService.parse_import_file(bad_csv)
        assert existing == []
        assert missing == []
        assert len(errors) == 1
        assert 'неверный формат' in errors[0]['error']

    def test_partially_invalid_file_collects_errors_and_valid_rows(self, db_session):
        content = (
            _make_csv(_BASE_ROW) + '\n'
            'bad;row\n'
            + _make_csv(('banana', 'банан', 'A banana.', 'Банан.', 'A1'))
        )
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert len(errors) == 1
        assert len(existing) + len(missing) == 2

    def test_all_invalid_rows_returns_empty_words_with_errors(self, db_session):
        content = 'x;y\na;b\n'
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert existing == []
        assert missing == []
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# 3. Duplicate prevention — within-file duplicates
# ---------------------------------------------------------------------------

class TestWithinFileDuplicates:
    @pytest.mark.smoke
    def test_duplicate_word_in_file_is_skipped_with_error(self, db_session):
        content = (
            _make_csv(_BASE_ROW) + '\n'
            + _make_csv(_BASE_ROW)  # same word again
        )
        existing, missing, errors = WordManagementService.parse_import_file(content)
        # Only the first occurrence is accepted
        assert len(existing) + len(missing) == 1
        assert len(errors) == 1
        assert 'дублирующееся слово' in errors[0]['error']
        assert 'apple' in errors[0]['error']

    def test_three_copies_keeps_only_first(self, db_session):
        content = '\n'.join([_make_csv(_BASE_ROW)] * 3)
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert len(existing) + len(missing) == 1
        assert len(errors) == 2

    def test_different_words_no_dedup_error(self, db_session):
        content = (
            _make_csv(_BASE_ROW) + '\n'
            + _make_csv(('banana', 'банан', 'A banana.', 'Банан.', 'A1'))
        )
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert errors == []
        assert len(existing) + len(missing) == 2


# ---------------------------------------------------------------------------
# 4. MAX_IMPORT_ROWS limit
# ---------------------------------------------------------------------------

class TestMaxImportRows:
    @pytest.mark.smoke
    def test_constant_is_10000(self):
        assert MAX_IMPORT_ROWS == 10000

    def test_rows_beyond_limit_produce_limit_error(self, db_session):
        # Build a CSV with MAX_IMPORT_ROWS + 2 unique rows
        rows = [
            (f'word{i}', f'слово{i}', f'Sentence {i}.', f'Предложение {i}.', 'A1')
            for i in range(MAX_IMPORT_ROWS + 2)
        ]
        content = _make_csv(*rows)
        existing, missing, errors = WordManagementService.parse_import_file(content)
        # Accepted exactly MAX_IMPORT_ROWS rows
        assert len(existing) + len(missing) == MAX_IMPORT_ROWS
        # At least one limit error appended
        limit_errors = [e for e in errors if 'лимит импорта' in e['error']]
        assert len(limit_errors) >= 1

    def test_exactly_at_limit_no_limit_error(self, db_session):
        rows = [
            (f'word{i}', f'слово{i}', f'Sentence {i}.', f'Предложение {i}.', 'A1')
            for i in range(MAX_IMPORT_ROWS)
        ]
        content = _make_csv(*rows)
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert len(existing) + len(missing) == MAX_IMPORT_ROWS
        limit_errors = [e for e in errors if 'лимит импорта' in e['error']]
        assert len(limit_errors) == 0


# ---------------------------------------------------------------------------
# 5. chunk_ids used for large word sets
# ---------------------------------------------------------------------------

class TestChunkIdsUsedForLargeImport:
    @pytest.mark.smoke
    def test_find_existing_english_words_uses_chunk_ids(self, db_session):
        """_find_existing_english_words must split large sets into chunks."""
        with patch('app.admin.services.word_management_service.chunk_ids',
                   wraps=__import__(
                       'app.utils.db_utils', fromlist=['chunk_ids']
                   ).chunk_ids) as mock_chunk:
            large_set = {f'word{i}' for i in range(2500)}
            WordManagementService._find_existing_english_words(large_set)
            # chunk_ids must have been called
            assert mock_chunk.called
            # With chunk_size=1000 and 2500 items, expect 3 chunks
            call_args = mock_chunk.call_args
            assert call_args is not None

    def test_find_existing_empty_returns_empty_set(self, db_session):
        result = WordManagementService._find_existing_english_words(set())
        assert result == set()

    def test_find_existing_single_word_not_in_db(self, db_session):
        result = WordManagementService._find_existing_english_words({'zxqwerty_unique_word'})
        assert 'zxqwerty_unique_word' not in result


# ---------------------------------------------------------------------------
# 6. Invalid file upload — route-level CSV error handling (no 500)
# ---------------------------------------------------------------------------

class TestImportRouteInvalidCSV:
    def _make_upload(self, content, filename='import.csv', encoding='utf-8'):
        if isinstance(content, str):
            content = content.encode(encoding)
        return (io.BytesIO(content), filename)

    @pytest.mark.smoke
    def test_non_utf8_file_redirects_with_flash_not_500(self, admin_client):
        bad_bytes = b'apple;\xff\xfe;bad;bad;A1'
        data = {
            'action': 'preview',
            'translation_file': (io.BytesIO(bad_bytes), 'import.csv'),
        }
        resp = admin_client.post(
            '/admin/words/import-translations',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        # Should redirect (302) or show form (200) — never 500
        assert resp.status_code in (200, 302)

    def test_no_file_selected_redirects_not_500(self, admin_client):
        resp = admin_client.post(
            '/admin/words/import-translations',
            data={'action': 'preview'},
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)

    def test_invalid_csv_content_shows_errors_not_500(self, admin_client):
        content = b'col1|col2|col3'  # wrong delimiter
        data = {
            'action': 'preview',
            'translation_file': (io.BytesIO(content), 'import.csv'),
        }
        resp = admin_client.post(
            '/admin/words/import-translations',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code != 500
