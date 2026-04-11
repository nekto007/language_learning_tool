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


class TestDailyPlanNextEscaping:
    """daily-plan-next.js must escape all API data before innerHTML insertion."""

    def test_has_escape_html_function(self):
        src = _read_js("daily-plan-next.js")
        assert "function escapeHtml" in src

    def test_step_title_escaped(self):
        src = _read_js("daily-plan-next.js")
        assert "escapeHtml(data.step_title)" in src

    def test_step_icon_escaped(self):
        src = _read_js("daily-plan-next.js")
        assert "escapeHtml(data.step_icon)" in src

    def test_step_url_escaped(self):
        src = _read_js("daily-plan-next.js")
        assert "escapeHtml(data.step_url)" in src

    def test_steps_done_escaped(self):
        src = _read_js("daily-plan-next.js")
        assert "escapeHtml(data.steps_done)" in src

    def test_steps_total_escaped(self):
        src = _read_js("daily-plan-next.js")
        assert "escapeHtml(data.steps_total)" in src

    def test_no_raw_data_in_innerhtml(self):
        """No innerHTML should contain raw data.step_title without escaping."""
        src = _read_js("daily-plan-next.js")
        # Find all innerHTML lines that reference data.step_title
        for line in src.splitlines():
            if "innerHTML" in line and "data.step_title" in line:
                assert "escapeHtml(data.step_title)" in line, (
                    f"Unescaped data.step_title in innerHTML: {line.strip()}"
                )


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


class TestReaderSafety:
    """reader.js must use DOM methods for bookmark and form data."""

    def test_form_info_uses_dom(self):
        src = _read_js("reader.js")
        # form_text/base_form should use textContent, not innerHTML
        assert "em.textContent" in src or "createElement('em')" in src

    def test_bookmark_name_uses_textcontent(self):
        src = _read_js("reader.js")
        assert "span.textContent = bookmark.name" in src or "textContent = bookmark.name" in src

    def test_bookmark_context_uses_title_attr(self):
        src = _read_js("reader.js")
        assert "span.title = bookmark.context" in src or ".title = bookmark.context" in src


class TestMobileReaderSafety:
    """mobile-reader.js must use DOM methods for bookmark data."""

    def test_bookmarks_use_textcontent(self):
        src = _read_js("mobile-reader.js")
        assert "title.textContent = bookmark.name" in src
        assert "ctx.textContent = bookmark.context" in src

    def test_no_bookmark_innerhtml(self):
        """Bookmark rendering should not use innerHTML with bookmark data."""
        src = _read_js("mobile-reader.js")
        for line in src.splitlines():
            if "innerHTML" in line and "bookmark." in line:
                assert False, f"Unsafe innerHTML with bookmark data: {line.strip()}"
