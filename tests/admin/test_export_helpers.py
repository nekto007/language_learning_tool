# tests/admin/test_export_helpers.py

"""Unit tests for app/admin/utils/export_helpers.py.

Coverage target: bring export_helpers from 58% to 80%+.
"""

import json

import pytest


class TestSanitizeCsvCell:
    """Tests for _sanitize_csv_cell."""

    def test_clean_value_unchanged(self):
        from app.admin.utils.export_helpers import _sanitize_csv_cell

        assert _sanitize_csv_cell("hello") == "hello"
        assert _sanitize_csv_cell("test word") == "test word"

    @pytest.mark.parametrize("dangerous_char", ["=", "+", "-", "@", "\t", "\r"])
    def test_dangerous_prefix_gets_apostrophe(self, dangerous_char):
        from app.admin.utils.export_helpers import _sanitize_csv_cell

        val = f"{dangerous_char}formula"
        result = _sanitize_csv_cell(val)
        assert result.startswith("'")
        assert result[1:] == val

    def test_none_returns_empty_string(self):
        from app.admin.utils.export_helpers import _sanitize_csv_cell

        assert _sanitize_csv_cell(None) == ""

    def test_integer_coerced_to_string(self):
        from app.admin.utils.export_helpers import _sanitize_csv_cell

        assert _sanitize_csv_cell(42) == "42"

    def test_empty_string_unchanged(self):
        from app.admin.utils.export_helpers import _sanitize_csv_cell

        assert _sanitize_csv_cell("") == ""


class TestStreamCsvRows:
    """Tests for _stream_csv_rows."""

    def test_header_and_rows_yielded(self):
        from app.admin.utils.export_helpers import _stream_csv_rows

        headers = ["Col1", "Col2"]
        rows = [["a", "b"], ["c", "d"]]
        lines = list(_stream_csv_rows(headers, iter(rows)))
        assert len(lines) == 3  # header + 2 rows
        assert "Col1" in lines[0]
        assert "a" in lines[1]
        assert "c" in lines[2]


class TestExportWordsJson:
    """Tests for export_words_json."""

    @pytest.mark.smoke
    def test_returns_json_response(self, app):
        from unittest.mock import MagicMock

        from app.admin.utils.export_helpers import export_words_json

        word = MagicMock()
        word.english_word = "run"
        word.russian_word = "бежать"
        word.level = "A1"
        word.status = "active"

        with app.test_request_context():
            resp = export_words_json([word], status="active")

        assert resp.status_code == 200
        assert "application/json" in resp.content_type
        body = json.loads(resp.get_data(as_text=True))
        assert body["words_total"] == 1
        assert body["words"][0]["english_word"] == "run"
        assert body["status_filter"] == "active"

    def test_word_without_status_omits_field(self, app):
        from unittest.mock import MagicMock

        from app.admin.utils.export_helpers import export_words_json

        word = MagicMock(spec=["english_word", "russian_word", "level"])
        word.english_word = "cat"
        word.russian_word = "кот"
        word.level = "A1"

        with app.test_request_context():
            resp = export_words_json([word])

        body = json.loads(resp.get_data(as_text=True))
        assert "status" not in body["words"][0]

    def test_empty_list_returns_zero_total(self, app):
        from app.admin.utils.export_helpers import export_words_json

        with app.test_request_context():
            resp = export_words_json([])

        body = json.loads(resp.get_data(as_text=True))
        assert body["words_total"] == 0


class TestExportWordsCsv:
    """Tests for export_words_csv."""

    @pytest.mark.smoke
    def test_returns_csv_response(self, app):
        from unittest.mock import MagicMock

        from app.admin.utils.export_helpers import export_words_csv

        word = MagicMock()
        word.english_word = "jump"
        word.russian_word = "прыгать"
        word.level = "B1"
        word.status = "active"

        with app.test_request_context():
            resp = export_words_csv([word], status=None)

        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in resp.response
        )
        assert "English" in content
        assert "jump" in content

    def test_respects_max_export_rows(self, app):
        from unittest.mock import MagicMock

        from app.admin.utils.export_helpers import MAX_EXPORT_ROWS, export_words_csv

        words = []
        for i in range(MAX_EXPORT_ROWS + 500):
            w = MagicMock(spec=["english_word", "russian_word", "level"])
            w.english_word = f"word{i}"
            w.russian_word = f"слово{i}"
            w.level = "A1"
            words.append(w)

        with app.test_request_context():
            resp = export_words_csv(words)

        # Just check it doesn't crash and returns a valid response
        assert resp.status_code == 200

    def test_sanitizes_dangerous_prefix(self, app):
        from unittest.mock import MagicMock

        from app.admin.utils.export_helpers import export_words_csv

        word = MagicMock(spec=["english_word", "russian_word", "level"])
        word.english_word = "=FORMULA"
        word.russian_word = "формула"
        word.level = "A1"

        with app.test_request_context():
            resp = export_words_csv([word])

        content = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in resp.response
        )
        assert "'=FORMULA" in content
        assert "=FORMULA" not in content.replace("'=FORMULA", "")


class TestExportWordsTxt:
    """Tests for export_words_txt."""

    @pytest.mark.smoke
    def test_returns_txt_response(self, app):
        from unittest.mock import MagicMock

        from app.admin.utils.export_helpers import export_words_txt

        word = MagicMock()
        word.english_word = "walk"
        word.russian_word = "ходить"
        word.status = "active"

        with app.test_request_context():
            resp = export_words_txt([word], status="active")

        assert resp.status_code == 200
        assert "text/plain" in resp.content_type
        body = resp.get_data(as_text=True)
        assert "walk" in body
        assert "ходить" in body
        assert "active" in body

    def test_status_filter_line_appears(self, app):
        from unittest.mock import MagicMock

        from app.admin.utils.export_helpers import export_words_txt

        word = MagicMock()
        word.english_word = "fly"
        word.russian_word = "летать"
        word.status = "new"

        with app.test_request_context():
            resp = export_words_txt([word], status="new")

        body = resp.get_data(as_text=True)
        assert "Status filter: new" in body


class TestExportAudioListJson:
    """Tests for export_audio_list_json."""

    @pytest.mark.smoke
    def test_returns_json_with_forvo_urls(self, app):
        from app.admin.utils.export_helpers import export_audio_list_json

        with app.test_request_context():
            resp = export_audio_list_json(["apple", "run"], pattern="A1")

        assert resp.status_code == 200
        body = json.loads(resp.get_data(as_text=True))
        assert body["words_total"] == 2
        assert body["pattern_filter"] == "A1"
        assert any(w["word"] == "apple" for w in body["words"])
        assert any("forvo.com" in w["forvo_url"] for w in body["words"])

    def test_no_pattern_uses_all(self, app):
        from app.admin.utils.export_helpers import export_audio_list_json

        with app.test_request_context():
            resp = export_audio_list_json([])

        body = json.loads(resp.get_data(as_text=True))
        assert body["pattern_filter"] is None


class TestExportAudioListCsv:
    """Tests for export_audio_list_csv."""

    @pytest.mark.smoke
    def test_returns_csv_with_urls(self, app):
        from app.admin.utils.export_helpers import export_audio_list_csv

        with app.test_request_context():
            resp = export_audio_list_csv(["hello", "world"])

        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in resp.response
        )
        assert "English Word" in content
        assert "hello" in content
        assert "forvo.com" in content

    def test_sanitizes_dangerous_word(self, app):
        from app.admin.utils.export_helpers import export_audio_list_csv

        with app.test_request_context():
            resp = export_audio_list_csv(["=evil"])

        content = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in resp.response
        )
        assert "'=evil" in content


class TestExportAudioListTxt:
    """Tests for export_audio_list_txt."""

    @pytest.mark.smoke
    def test_returns_txt_with_forvo_urls(self, app):
        from app.admin.utils.export_helpers import export_audio_list_txt

        with app.test_request_context():
            resp = export_audio_list_txt(["cat", "dog"], pattern="B1")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "forvo.com/word/cat" in body
        assert "forvo.com/word/dog" in body
        assert "Pattern filter: B1" in body

    def test_no_pattern_no_filter_line(self, app):
        from app.admin.utils.export_helpers import export_audio_list_txt

        with app.test_request_context():
            resp = export_audio_list_txt(["test"])

        body = resp.get_data(as_text=True)
        assert "Pattern filter" not in body
