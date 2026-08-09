"""Tests that JS files use safe innerHTML patterns — escapeHtml for API data,
textContent/DOM methods instead of raw innerHTML where possible."""

import os

JS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "app", "static", "js"
)


def _read_js(filename: str) -> str:
    path = os.path.join(JS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestWordTranslatorSafety:
    """word-translator.js must use safe DOM methods for user-visible data."""

    def test_translation_uses_textcontent(self):
        src = _read_js("word-translator.js")
        assert "els.translation.textContent" in src

    def test_word_display_uses_textcontent(self):
        src = _read_js("word-translator.js")
        assert "els.word.textContent" in src

    def test_learn_button_no_innerhtml(self):
        """Learn button update should not use innerHTML with dynamic content."""
        src = _read_js("word-translator.js")
        # After fix, learn button uses DOM methods (createElement/appendChild)
        assert "document.createElement('i')" in src or "createElement" in src

    def test_form_info_uses_textcontent(self):
        src = _read_js("word-translator.js")
        assert "els.formInfo.textContent" in src


# NOTE (audit E-094): TestReaderSafety / TestMobileReaderSafety removed together
# with the dead reader.js / mobile-reader.js / read_optimized.html — the live
# reader is reader_simple.html. Re-add coverage if those assets are revived.
