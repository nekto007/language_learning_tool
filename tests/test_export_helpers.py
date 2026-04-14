"""
Tests for app/admin/utils/export_helpers.py

Tests all 6 export functions: words (JSON/CSV/TXT) and audio lists (JSON/CSV/TXT).
Covers business logic, response headers, content formatting, edge cases, and encoding.
"""
import csv
import io
import json
from types import SimpleNamespace

import pytest

from app.admin.utils.export_helpers import (
    export_audio_list_csv,
    export_audio_list_json,
    export_audio_list_txt,
    export_words_csv,
    export_words_json,
    export_words_txt,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_word(english: str, russian: str, level: str = 'A1',
               status: str = None) -> SimpleNamespace:
    """Create a word-like object with optional status attribute."""
    word = SimpleNamespace(english_word=english, russian_word=russian, level=level)
    if status is not None:
        word.status = status
    return word


def _make_words_with_status(n: int = 3) -> list:
    """Create a list of words that have a status attribute."""
    data = [
        ('hello', '\u043f\u0440\u0438\u0432\u0435\u0442', 'A1', 'new'),
        ('book', '\u043a\u043d\u0438\u0433\u0430', 'A1', 'learning'),
        ('world', '\u043c\u0438\u0440', 'A2', 'mastered'),
    ]
    return [_make_word(e, r, l, s) for e, r, l, s in data[:n]]


def _make_words_without_status(n: int = 3) -> list:
    """Create a list of words without a status attribute."""
    data = [
        ('hello', '\u043f\u0440\u0438\u0432\u0435\u0442', 'A1'),
        ('book', '\u043a\u043d\u0438\u0433\u0430', 'A1'),
        ('world', '\u043c\u0438\u0440', 'A2'),
    ]
    return [_make_word(e, r, l) for e, r, l in data[:n]]


# ===========================================================================
# export_words_json
# ===========================================================================

class TestExportWordsJson:
    """Tests for export_words_json()"""

    def test_returns_valid_json_with_status(self, app):
        """Test JSON response body contains correct data for words with status"""
        words = _make_words_with_status()
        with app.test_request_context():
            resp = export_words_json(words, status='new')
        body = json.loads(resp.get_data(as_text=True))
        assert body['words_total'] == 3
        assert body['status_filter'] == 'new'
        assert len(body['words']) == 3
        assert body['words'][0]['english_word'] == 'hello'
        assert body['words'][0]['russian_word'] == '\u043f\u0440\u0438\u0432\u0435\u0442'
        assert body['words'][0]['status'] == 'new'
        assert 'export_date' in body

    def test_returns_valid_json_without_status(self, app):
        """Test JSON response for words that lack a status attribute"""
        words = _make_words_without_status()
        with app.test_request_context():
            resp = export_words_json(words)
        body = json.loads(resp.get_data(as_text=True))
        assert 'status' not in body['words'][0]
        assert body['status_filter'] is None

    def test_response_headers_json(self, app):
        """Test that response headers are correct for JSON export"""
        words = _make_words_with_status(1)
        with app.test_request_context():
            resp = export_words_json(words, status='learning')
        assert resp.headers['Content-Type'] == 'application/json; charset=utf-8'
        disposition = resp.headers['Content-Disposition']
        assert disposition.startswith('attachment; filename=words_export_learning_')
        assert disposition.endswith('.json')

    def test_filename_all_when_no_status(self, app):
        """Test filename uses 'all' when no status filter is given"""
        words = _make_words_without_status(1)
        with app.test_request_context():
            resp = export_words_json(words)
        disposition = resp.headers['Content-Disposition']
        assert 'words_export_all_' in disposition

    def test_empty_word_list(self, app):
        """Test export with an empty word list"""
        with app.test_request_context():
            resp = export_words_json([])
        body = json.loads(resp.get_data(as_text=True))
        assert body['words_total'] == 0
        assert body['words'] == []

    def test_unicode_characters_preserved(self, app):
        """Test that Cyrillic and special characters are preserved in JSON"""
        words = [_make_word('cafe', '\u043a\u0430\u0444\u0435')]
        with app.test_request_context():
            resp = export_words_json(words)
        text = resp.get_data(as_text=True)
        assert '\u043a\u0430\u0444\u0435' in text

    def test_level_none_when_missing(self, app):
        """Test that level is None when word object has no level attribute"""
        word = SimpleNamespace(english_word='test', russian_word='\u0442\u0435\u0441\u0442')
        with app.test_request_context():
            resp = export_words_json([word])
        body = json.loads(resp.get_data(as_text=True))
        assert body['words'][0]['level'] is None


# ===========================================================================
# export_words_csv
# ===========================================================================

class TestExportWordsCsv:
    """Tests for export_words_csv()"""

    def test_csv_with_status(self, app):
        """Test CSV output includes Status column when words have status"""
        words = _make_words_with_status()
        with app.test_request_context():
            resp = export_words_csv(words, status='new')
        text = resp.get_data(as_text=True)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert rows[0] == ['English', 'Russian', 'Level', 'Status']
        assert rows[1][0] == 'hello'
        assert rows[1][1] == '\u043f\u0440\u0438\u0432\u0435\u0442'
        assert rows[1][3] == 'new'

    def test_csv_without_status(self, app):
        """Test CSV output omits Status column when words lack status"""
        words = _make_words_without_status()
        with app.test_request_context():
            resp = export_words_csv(words)
        text = resp.get_data(as_text=True)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert rows[0] == ['English', 'Russian', 'Level']
        assert len(rows[1]) == 3

    def test_csv_response_headers(self, app):
        """Test response headers for CSV export"""
        words = _make_words_with_status(1)
        with app.test_request_context():
            resp = export_words_csv(words, status='mastered')
        assert resp.headers['Content-Type'] == 'text/csv; charset=utf-8'
        disposition = resp.headers['Content-Disposition']
        assert 'words_export_mastered_' in disposition
        assert disposition.endswith('.csv')

    def test_csv_empty_list(self, app):
        """Test CSV export with empty word list (header only)"""
        with app.test_request_context():
            resp = export_words_csv([])
        text = resp.get_data(as_text=True)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0] == ['English', 'Russian', 'Level']

    def test_csv_level_missing(self, app):
        """Test CSV level field is empty when word has no level attribute"""
        word = SimpleNamespace(english_word='apple', russian_word='\u044f\u0431\u043b\u043e\u043a\u043e')
        with app.test_request_context():
            resp = export_words_csv([word])
        text = resp.get_data(as_text=True)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert rows[1][2] == ''

    def test_csv_special_characters_escaped(self, app):
        """Test CSV properly escapes commas and quotes in word text"""
        word = _make_word("let's go", '\u0434\u0430\u0432\u0430\u0439, \u043f\u043e\u0439\u0434\u0451\u043c', 'A1', 'new')
        with app.test_request_context():
            resp = export_words_csv([word])
        text = resp.get_data(as_text=True)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert rows[1][0] == "let's go"
        assert rows[1][1] == '\u0434\u0430\u0432\u0430\u0439, \u043f\u043e\u0439\u0434\u0451\u043c'


# ===========================================================================
# export_words_txt
# ===========================================================================

class TestExportWordsTxt:
    """Tests for export_words_txt()"""

    def test_txt_with_status(self, app):
        """Test TXT output includes status when words have it"""
        words = _make_words_with_status(2)
        with app.test_request_context():
            resp = export_words_txt(words, status='learning')
        text = resp.get_data(as_text=True)
        lines = text.split('\n')
        assert lines[0].startswith('# Words Export')
        assert '# Status filter: learning' in lines[1]
        assert '# Total words: 2' in lines[2]
        assert 'hello | \u043f\u0440\u0438\u0432\u0435\u0442 | new' in text
        assert 'book | \u043a\u043d\u0438\u0433\u0430 | learning' in text

    def test_txt_without_status(self, app):
        """Test TXT output omits status field when words lack it"""
        words = _make_words_without_status(1)
        with app.test_request_context():
            resp = export_words_txt(words)
        text = resp.get_data(as_text=True)
        assert 'hello | \u043f\u0440\u0438\u0432\u0435\u0442' in text
        data_lines = [l for l in text.split('\n') if not l.startswith('#') and l.strip()]
        for line in data_lines:
            assert line.count('|') == 1

    def test_txt_no_status_filter_line_when_none(self, app):
        """Test that Status filter line is absent when status is None"""
        words = _make_words_without_status(1)
        with app.test_request_context():
            resp = export_words_txt(words)
        text = resp.get_data(as_text=True)
        assert '# Status filter' not in text

    def test_txt_response_headers(self, app):
        """Test response headers for TXT export"""
        words = _make_words_without_status(1)
        with app.test_request_context():
            resp = export_words_txt(words, status='new')
        assert resp.headers['Content-Type'] == 'text/plain; charset=utf-8'
        disposition = resp.headers['Content-Disposition']
        assert 'words_export_new_' in disposition
        assert disposition.endswith('.txt')

    def test_txt_empty_list(self, app):
        """Test TXT export with empty word list"""
        with app.test_request_context():
            resp = export_words_txt([])
        text = resp.get_data(as_text=True)
        assert '# Total words: 0' in text

    def test_txt_unicode_preserved(self, app):
        """Test that Cyrillic text is preserved correctly"""
        words = [_make_word('water', '\u0432\u043e\u0434\u0430')]
        with app.test_request_context():
            resp = export_words_txt(words)
        text = resp.get_data(as_text=True)
        assert '\u0432\u043e\u0434\u0430' in text


# ===========================================================================
# export_audio_list_json
# ===========================================================================

class TestExportAudioListJson:
    """Tests for export_audio_list_json()"""

    def test_audio_json_basic(self, app):
        """Test basic audio list JSON export"""
        words = ['hello', 'world']
        with app.test_request_context():
            resp = export_audio_list_json(words)
        body = json.loads(resp.get_data(as_text=True))
        assert body['words_total'] == 2
        assert body['pattern_filter'] is None
        assert body['purpose'] == 'forvo_audio_download_list'
        assert body['words'][0]['word'] == 'hello'
        assert body['words'][0]['forvo_url'] == 'https://forvo.com/word/hello/#en'

    def test_audio_json_with_pattern(self, app):
        """Test audio list JSON export with pattern filter"""
        words = ['cat', 'car']
        with app.test_request_context():
            resp = export_audio_list_json(words, pattern='ca*')
        body = json.loads(resp.get_data(as_text=True))
        assert body['pattern_filter'] == 'ca*'

    def test_audio_json_response_headers(self, app):
        """Test response headers for audio JSON export"""
        with app.test_request_context():
            resp = export_audio_list_json(['test'], pattern='t*')
        assert resp.headers['Content-Type'] == 'application/json; charset=utf-8'
        disposition = resp.headers['Content-Disposition']
        assert 'forvo_download_list_t' in disposition
        assert disposition.endswith('.json')

    def test_audio_json_empty_list(self, app):
        """Test audio JSON export with empty word list"""
        with app.test_request_context():
            resp = export_audio_list_json([])
        body = json.loads(resp.get_data(as_text=True))
        assert body['words_total'] == 0
        assert body['words'] == []

    def test_audio_json_forvo_url_format(self, app):
        """Test that Forvo URL has correct format"""
        words = ['ice cream']
        with app.test_request_context():
            resp = export_audio_list_json(words)
        body = json.loads(resp.get_data(as_text=True))
        assert body['words'][0]['forvo_url'] == 'https://forvo.com/word/ice cream/#en'

    def test_audio_json_filename_all_when_no_pattern(self, app):
        """Test filename uses 'all' when no pattern given"""
        with app.test_request_context():
            resp = export_audio_list_json(['test'])
        disposition = resp.headers['Content-Disposition']
        assert 'forvo_download_list_all_' in disposition


# ===========================================================================
# export_audio_list_csv
# ===========================================================================

class TestExportAudioListCsv:
    """Tests for export_audio_list_csv()"""

    def test_audio_csv_basic(self, app):
        """Test basic audio list CSV export"""
        words = ['apple', 'banana']
        with app.test_request_context():
            resp = export_audio_list_csv(words)
        text = resp.get_data(as_text=True)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert rows[0] == ['English Word', 'Forvo URL']
        assert rows[1][0] == 'apple'
        assert rows[1][1] == 'https://forvo.com/word/apple/#en'
        assert rows[2][0] == 'banana'

    def test_audio_csv_response_headers(self, app):
        """Test response headers for audio CSV export"""
        with app.test_request_context():
            resp = export_audio_list_csv(['test'], pattern='t*')
        assert resp.headers['Content-Type'] == 'text/csv; charset=utf-8'
        disposition = resp.headers['Content-Disposition']
        assert disposition.endswith('.csv')

    def test_audio_csv_empty_list(self, app):
        """Test audio CSV export with empty word list"""
        with app.test_request_context():
            resp = export_audio_list_csv([])
        text = resp.get_data(as_text=True)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) == 1

    def test_audio_csv_with_pattern(self, app):
        """Test audio CSV filename includes pattern"""
        with app.test_request_context():
            resp = export_audio_list_csv(['dog'], pattern='d*')
        disposition = resp.headers['Content-Disposition']
        assert 'forvo_download_list_d' in disposition


# ===========================================================================
# export_audio_list_txt
# ===========================================================================

class TestExportAudioListTxt:
    """Tests for export_audio_list_txt()"""

    def test_audio_txt_basic(self, app):
        """Test basic audio list TXT export"""
        words = ['hello', 'world']
        with app.test_request_context():
            resp = export_audio_list_txt(words)
        text = resp.get_data(as_text=True)
        assert 'https://forvo.com/word/hello/#en' in text
        assert 'https://forvo.com/word/world/#en' in text
        assert '# Total words: 2' in text

    def test_audio_txt_with_pattern(self, app):
        """Test audio TXT export with pattern filter"""
        words = ['cat']
        with app.test_request_context():
            resp = export_audio_list_txt(words, pattern='ca*')
        text = resp.get_data(as_text=True)
        assert '# Pattern filter: ca*' in text

    def test_audio_txt_no_pattern_line_when_none(self, app):
        """Test that Pattern filter line is absent when pattern is None"""
        words = ['test']
        with app.test_request_context():
            resp = export_audio_list_txt(words)
        text = resp.get_data(as_text=True)
        assert '# Pattern filter' not in text

    def test_audio_txt_response_headers(self, app):
        """Test response headers for audio TXT export"""
        with app.test_request_context():
            resp = export_audio_list_txt(['test'])
        assert resp.headers['Content-Type'] == 'text/plain; charset=utf-8'
        disposition = resp.headers['Content-Disposition']
        assert disposition.endswith('.txt')

    def test_audio_txt_empty_list(self, app):
        """Test audio TXT export with empty word list"""
        with app.test_request_context():
            resp = export_audio_list_txt([])
        text = resp.get_data(as_text=True)
        assert '# Total words: 0' in text
        data_lines = [l for l in text.split('\n') if not l.startswith('#') and l.strip()]
        assert len(data_lines) == 0

    def test_audio_txt_format_line_present(self, app):
        """Test that the format description line is included"""
        with app.test_request_context():
            resp = export_audio_list_txt(['test'])
        text = resp.get_data(as_text=True)
        assert '# Format: https://forvo.com/word/{word}/#en' in text

    def test_audio_txt_many_words(self, app):
        """Test audio TXT export with many words"""
        words = [f'word{i}' for i in range(100)]
        with app.test_request_context():
            resp = export_audio_list_txt(words)
        text = resp.get_data(as_text=True)
        assert '# Total words: 100' in text
        assert 'https://forvo.com/word/word0/#en' in text
        assert 'https://forvo.com/word/word99/#en' in text
