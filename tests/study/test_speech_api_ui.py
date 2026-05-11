"""Tests for app/static/js/speech_api.js — structural/content checks.

Task 53: Web Speech API client integration.
JS unit tests (mock SpeechRecognition) are not automatable via pytest;
this module verifies the JS file structure and content as a smoke check.
"""
from __future__ import annotations

import re
from pathlib import Path

SPEECH_API_JS = (
    Path(__file__).parent.parent.parent
    / "app" / "static" / "js" / "speech_api.js"
)


def _source() -> str:
    return SPEECH_API_JS.read_text(encoding="utf-8")


class TestSpeechApiJsExists:
    def test_file_exists(self):
        assert SPEECH_API_JS.exists(), "speech_api.js not found"

    def test_exports_default(self):
        src = _source()
        assert "export default SpeechAPI" in src

    def test_class_defined(self):
        src = _source()
        assert "class SpeechAPI" in src

    def test_is_supported_method(self):
        src = _source()
        assert "isSupported" in src

    def test_start_recognition_method(self):
        src = _source()
        assert "startRecognition" in src

    def test_stop_recognition_method(self):
        src = _source()
        assert "stopRecognition" in src

    def test_lang_set_to_en_us(self):
        src = _source()
        assert "en-US" in src

    def test_continuous_false(self):
        src = _source()
        assert re.search(r"continuous\s*=\s*false", src)

    def test_interim_results_false(self):
        src = _source()
        assert re.search(r"interimResults\s*=\s*false", src)

    def test_unsupported_triggers_on_error(self):
        src = _source()
        # When isSupported() is false, startRecognition must call onError
        assert "onError" in src
        assert "not supported" in src.lower() or "SpeechRecognition not supported" in src

    def test_webkit_fallback(self):
        src = _source()
        assert "webkitSpeechRecognition" in src

    def test_on_result_calls_callback(self):
        src = _source()
        assert "onResult" in src
        assert "transcript" in src
