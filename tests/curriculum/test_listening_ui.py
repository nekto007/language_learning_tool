"""Tests for listening lesson UI: audio speed control and transcript toggle."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_text_template() -> str:
    """Listening features now live in the dedicated listening_immersion.html template."""
    from pathlib import Path
    p = (
        Path(__file__).parent.parent.parent
        / "app" / "templates" / "curriculum" / "lessons"
        / "listening_immersion.html"
    )
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


# ---------------------------------------------------------------------------
# Task 2: Transcript toggle
# ---------------------------------------------------------------------------

class TestTranscriptToggleTemplate:
    """Verify the transcript toggle button and content wrapper are present."""

    def test_toggle_button_present(self):
        html = _read_text_template()
        assert 'id="transcript-toggle-btn"' in html

    def test_toggle_calls_toggleTranscript(self):
        html = _read_text_template()
        assert 'onclick="toggleTranscript()"' in html

    def test_transcript_content_div_present(self):
        html = _read_text_template()
        assert 'id="transcript-content"' in html

    def test_toggle_label_element_present(self):
        html = _read_text_template()
        assert 'id="transcript-toggle-label"' in html

    def test_b1plus_default_hidden_via_jinja(self):
        html = _read_text_template()
        # The Jinja template must conditionally add transcript--hidden for advanced users
        assert 'transcript--hidden' in html
        # The condition is driven by is_advanced
        assert 'is_advanced' in html

    def test_data_default_visible_attribute_present(self):
        html = _read_text_template()
        assert 'data-default-visible=' in html

    def test_b1plus_shows_show_text_label(self):
        html = _read_text_template()
        assert 'Показать текст' in html

    def test_a1a2_shows_hide_text_label(self):
        html = _read_text_template()
        assert 'Скрыть текст' in html

    def test_toggleTranscript_function_present(self):
        html = _read_text_template()
        assert 'function toggleTranscript(' in html

    def test_initTranscriptToggle_function_present(self):
        html = _read_text_template()
        assert 'function initTranscriptToggle(' in html

    def test_initTranscriptToggle_called_on_domcontentloaded(self):
        html = _read_text_template()
        assert 'initTranscriptToggle()' in html

    def test_localStorage_transcript_visible_key(self):
        html = _read_text_template()
        assert 'transcript_visible' in html

    def test_localStorage_setItem_transcript(self):
        html = _read_text_template()
        assert "localStorage.setItem('transcript_visible'" in html

    def test_localStorage_getItem_transcript(self):
        html = _read_text_template()
        assert "localStorage.getItem('transcript_visible')" in html


class TestTranscriptToggleCSS:
    """Verify CSS classes for the transcript toggle are defined."""

    def test_transcript_toggle_class_defined(self):
        css = _read_design_system_css()
        assert ".transcript-toggle {" in css or ".transcript-toggle{" in css

    def test_transcript_hidden_class_defined(self):
        css = _read_design_system_css()
        assert ".transcript--hidden {" in css or ".transcript--hidden{" in css

    def test_transcript_hidden_uses_display_none(self):
        css = _read_design_system_css()
        idx = css.find(".transcript--hidden")
        assert idx != -1
        snippet = css[idx:idx + 100]
        assert "display: none" in snippet or "display:none" in snippet

    def test_transcript_toggle_hover_defined(self):
        css = _read_design_system_css()
        assert ".transcript-toggle:hover" in css


# ---------------------------------------------------------------------------
# Task 7: Per-sentence replay in listening lessons
# ---------------------------------------------------------------------------

class TestSentenceReplayTemplate:
    """Verify per-sentence replay icons are rendered when sentences are present."""

    def test_sentence_replay_list_container_in_template(self):
        html = _read_text_template()
        assert 'sentence-replay-list' in html

    def test_sentence_replay_btn_class_in_template(self):
        html = _read_text_template()
        assert 'sentence-replay-btn' in html

    def test_sentences_conditional_check_present(self):
        # Template must guard replay list with if text_content.sentences
        html = _read_text_template()
        assert 'text_content.sentences' in html

    def test_replaySentence_function_defined(self):
        html = _read_text_template()
        assert 'function replaySentence(' in html

    def test_replaySentence_uses_currentTime(self):
        html = _read_text_template()
        assert 'audio.currentTime = startTime' in html

    def test_replaySentence_uses_play(self):
        html = _read_text_template()
        assert 'audio.play()' in html

    def test_replaySentence_uses_timeupdate_event(self):
        html = _read_text_template()
        assert 'timeupdate' in html

    def test_replaySentence_pauses_at_endTime(self):
        html = _read_text_template()
        assert 'audio.pause()' in html
        assert 'endTime' in html

    def test_fallback_when_no_sentences(self):
        # Sentences section is conditionally rendered — no hardcoded icon without data
        html = _read_text_template()
        # The replay button is inside {% if text_content.sentences %} block
        # Verify the block uses Jinja conditional (not always rendered)
        idx_if = html.find('{% if text_content.sentences %}')
        assert idx_if != -1, "sentences conditional block not found"
        idx_btn = html.find('sentence-replay-btn', idx_if)
        assert idx_btn != -1, "sentence-replay-btn should be inside sentences block"

    def test_onclick_passes_start_and_end_time(self):
        html = _read_text_template()
        assert 'replaySentence(' in html
        assert 'sentence.start_time' in html
        assert 'sentence.end_time' in html


class TestSentenceReplayCSS:
    """Verify CSS classes for sentence replay are defined."""

    def test_sentence_replay_list_class_defined(self):
        css = _read_design_system_css()
        assert ".sentence-replay-list" in css

    def test_sentence_replay_item_class_defined(self):
        css = _read_design_system_css()
        assert ".sentence-replay-item" in css

    def test_sentence_replay_btn_class_defined(self):
        css = _read_design_system_css()
        assert ".sentence-replay-btn" in css

    def test_sentence_replay_btn_hover_defined(self):
        css = _read_design_system_css()
        assert ".sentence-replay-btn:hover" in css

    def test_sentence_replay_text_class_defined(self):
        css = _read_design_system_css()
        assert ".sentence-replay-text" in css


# ---------------------------------------------------------------------------
# Task 34: Audio URL verification — content_commands CLI
# ---------------------------------------------------------------------------

class TestContentAuditAudioExpected:
    """Verify AUDIO_EXPECTED covers all required lesson types."""

    def test_dictation_in_audio_expected(self):
        from app.cli.content_commands import AUDIO_EXPECTED
        assert 'dictation' in AUDIO_EXPECTED

    def test_audio_fill_blank_in_audio_expected(self):
        from app.cli.content_commands import AUDIO_EXPECTED
        assert 'audio_fill_blank' in AUDIO_EXPECTED

    def test_shadow_reading_in_audio_expected(self):
        from app.cli.content_commands import AUDIO_EXPECTED
        assert 'shadow_reading' in AUDIO_EXPECTED

    def test_listening_immersion_in_audio_expected(self):
        from app.cli.content_commands import AUDIO_EXPECTED
        assert 'listening_immersion' in AUDIO_EXPECTED


class TestIsLocalPath:
    """Unit tests for _is_local_path helper."""

    def test_static_prefix_is_local(self):
        from app.cli.content_commands import _is_local_path
        assert _is_local_path('/static/audio/foo.mp3') is True

    def test_root_path_is_local(self):
        from app.cli.content_commands import _is_local_path
        assert _is_local_path('/audio/foo.mp3') is True

    def test_https_url_is_not_local(self):
        from app.cli.content_commands import _is_local_path
        assert _is_local_path('https://cdn.example.com/foo.mp3') is False

    def test_http_url_is_not_local(self):
        from app.cli.content_commands import _is_local_path
        assert _is_local_path('http://example.com/foo.mp3') is False

    def test_protocol_relative_not_local(self):
        from app.cli.content_commands import _is_local_path
        assert _is_local_path('//cdn.example.com/foo.mp3') is False

    def test_empty_string_not_local(self):
        from app.cli.content_commands import _is_local_path
        assert _is_local_path('') is False


class TestFormatReport:
    """Unit tests for _format_report helper."""

    def test_empty_list_no_lessons(self):
        from app.cli.content_commands import _format_report
        report = _format_report([])
        assert 'No lessons' in report

    def test_single_missing_lesson(self):
        from app.cli.content_commands import _format_report
        row = {
            'lesson_id': 42,
            'title': 'Test Dictation',
            'type': 'dictation',
            'module_number': 3,
            'module_title': 'Module 3',
            'level_code': 'A2',
            'level_order': 2,
            'lesson_number': 7,
            'audio_url': '',
            'status': 'missing',
        }
        report = _format_report([row])
        assert 'dictation' in report
        assert 'missing' in report
        assert 'Test Dictation' in report
        assert 'A2' in report

    def test_broken_local_status_appears(self):
        from app.cli.content_commands import _format_report
        row = {
            'lesson_id': 99,
            'title': 'Shadow Read',
            'type': 'shadow_reading',
            'module_number': 1,
            'module_title': 'Module 1',
            'level_code': 'B1',
            'level_order': 3,
            'lesson_number': 2,
            'audio_url': '/static/audio/nonexistent.mp3',
            'status': 'broken_local',
        }
        report = _format_report([row])
        assert 'broken_local' in report

    def test_count_line_present(self):
        from app.cli.content_commands import _format_report
        rows = [
            {
                'lesson_id': i,
                'title': f'L{i}',
                'type': 'dictation',
                'module_number': 1,
                'module_title': 'M',
                'level_code': 'A1',
                'level_order': 1,
                'lesson_number': i,
                'audio_url': '',
                'status': 'missing',
            }
            for i in range(3)
        ]
        report = _format_report(rows)
        assert '3' in report


class TestContentAuditOutputOption:
    """Verify --output flag writes report to a file."""

    def test_output_flag_writes_file(self, app, tmp_path):
        from click.testing import CliRunner
        from app.cli.content_commands import content_audit_cmd

        out_file = tmp_path / 'audio_report.txt'
        runner = CliRunner()
        with app.app_context():
            result = runner.invoke(content_audit_cmd, ['audio', '--output', str(out_file)])

        assert result.exit_code == 0, result.output
        assert out_file.exists()
        content = out_file.read_text()
        assert len(content) > 0

    def test_output_flag_prints_written_path(self, app, tmp_path):
        from click.testing import CliRunner
        from app.cli.content_commands import content_audit_cmd

        out_file = tmp_path / 'report.txt'
        runner = CliRunner()
        with app.app_context():
            result = runner.invoke(content_audit_cmd, ['audio', '-o', str(out_file)])

        assert 'Report written to' in result.output

    def test_no_output_flag_prints_to_stdout(self, app):
        from click.testing import CliRunner
        from app.cli.content_commands import content_audit_cmd

        runner = CliRunner()
        with app.app_context():
            result = runner.invoke(content_audit_cmd, ['audio'])

        assert result.exit_code == 0
        assert len(result.output) > 0
