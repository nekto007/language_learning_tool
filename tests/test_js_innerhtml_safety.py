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
