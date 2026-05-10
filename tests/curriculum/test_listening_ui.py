"""Tests for listening lesson UI: audio speed control and transcript toggle."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_text_template() -> str:
    from pathlib import Path
    p = Path(__file__).parent.parent.parent / "app" / "templates" / "curriculum" / "lessons" / "text.html"
    return p.read_text(encoding="utf-8")


def _read_design_system_css() -> str:
    from pathlib import Path
    p = Path(__file__).parent.parent.parent / "app" / "static" / "css" / "design-system.css"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 1: Audio speed control
# ---------------------------------------------------------------------------

class TestAudioSpeedControlTemplate:
    """Verify the speed selector buttons are present in the template."""

    def test_speed_controls_container_present(self):
        html = _read_text_template()
        assert 'id="audio-speed-controls"' in html

    def test_all_four_speed_buttons_present(self):
        html = _read_text_template()
        for speed in ("0.75", "1", "1.25", "1.5"):
            assert f'data-speed="{speed}"' in html, f"Speed button {speed}x not found"

    def test_default_active_button_is_1x(self):
        html = _read_text_template()
        # The 1x button should carry the --active class initially
        assert 'data-speed="1"' in html
        # Find the line with data-speed="1" and check it has audio-speed-btn--active
        lines = html.splitlines()
        for line in lines:
            if 'data-speed="1"' in line and 'onclick="setAudioSpeed(1)"' in line:
                assert "audio-speed-btn--active" in line
                break
        else:
            pytest.fail("1x button with audio-speed-btn--active not found")

    def test_speed_buttons_have_correct_labels(self):
        html = _read_text_template()
        for label in ("0.75×", "1×", "1.25×", "1.5×"):
            assert label in html, f"Speed label '{label}' missing from template"

    def test_speed_controls_inside_audio_player_card(self):
        html = _read_text_template()
        card_start = html.find('listening-audio-player-card')
        card_end = html.find('</div>', card_start)
        assert card_start != -1
        assert 'audio-speed-controls' in html[card_start:card_start + 2000]

    def test_localStorage_key_in_js(self):
        html = _read_text_template()
        assert "listening_speed" in html

    def test_setAudioSpeed_function_present(self):
        html = _read_text_template()
        assert "function setAudioSpeed(" in html

    def test_initAudioSpeed_function_present(self):
        html = _read_text_template()
        assert "function initAudioSpeed(" in html

    def test_playbackRate_assignment_in_js(self):
        html = _read_text_template()
        assert "audio.playbackRate = speed" in html

    def test_initAudioSpeed_called_on_domcontentloaded(self):
        html = _read_text_template()
        assert "initAudioSpeed()" in html


class TestAudioSpeedControlCSS:
    """Verify CSS classes are defined in design-system.css."""

    def test_audio_speed_btn_class_defined(self):
        css = _read_design_system_css()
        assert ".audio-speed-btn {" in css or ".audio-speed-btn{" in css

    def test_audio_speed_btn_active_class_defined(self):
        css = _read_design_system_css()
        assert ".audio-speed-btn--active" in css

    def test_audio_speed_controls_class_defined(self):
        css = _read_design_system_css()
        assert ".audio-speed-controls" in css

    def test_active_button_uses_white_background(self):
        css = _read_design_system_css()
        idx = css.find(".audio-speed-btn--active")
        assert idx != -1
        snippet = css[idx:idx + 200]
        assert "background: white" in snippet or "background:white" in snippet


class TestAudioSpeedLogic:
    """Unit tests for the speed control JS logic (Python-side verification)."""

    VALID_SPEEDS = [0.75, 1.0, 1.25, 1.5]

    def test_valid_speed_values_covered(self):
        html = _read_text_template()
        for speed in self.VALID_SPEEDS:
            assert f"setAudioSpeed({speed})" in html or f"setAudioSpeed({int(speed)})" in html

    def test_invalid_speed_falls_back_to_1(self):
        html = _read_text_template()
        # The initAudioSpeed function should validate against allowed speeds
        assert "![0.75, 1, 1.25, 1.5].includes(speed)" in html or \
               "0.75, 1, 1.25, 1.5" in html

    def test_localStorage_setItem_call_present(self):
        html = _read_text_template()
        assert "localStorage.setItem('listening_speed'" in html

    def test_localStorage_getItem_call_present(self):
        html = _read_text_template()
        assert "localStorage.getItem('listening_speed')" in html
