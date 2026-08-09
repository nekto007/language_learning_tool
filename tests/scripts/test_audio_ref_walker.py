"""Regression tests for CNT-004 / CNT-003 (cross-zone audit 2026-08-08).

CNT-004 — ``_iter_audio_refs`` in ``validate_module_completed_json.py`` visited
only the top level plus ``items``/``questions``/``exercises`` and
``test_sections[].exercises[]``. Everything else — ``vocabulary[].audio``,
``cards[].audio``, ``sections[].table[].audio``, ``text.lines[].audio``,
``sections[].rules[].audio`` — was invisible, along with the list form
``audio: [...]``. That is where all 1570 missing clips live, so the validator
reported ``missing=0`` while the corpus was full of dead references.

CNT-003 — ``scripts/clear_missing_word_audio.py`` is the mitigation: stop
advertising a speaker button for a clip that is not on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.clear_missing_word_audio import audio_filename, file_exists
from scripts.validate_module_completed_json import _iter_audio_refs


def _refs(content: dict) -> dict[str, str]:
    return dict(_iter_audio_refs(content))


class TestWalkerReachesEveryNesting:
    @pytest.mark.parametrize('content,expected_path', [
        ({'vocabulary': [{'audio': '/static/audio/v.mp3'}]}, 'vocabulary[0].audio'),
        ({'cards': [{'audio': '/static/audio/c.mp3'}]}, 'cards[0].audio'),
        ({'text': {'lines': [{'audio': '/static/audio/l.mp3'}]}}, 'text.lines[0].audio'),
        (
            {'sections': [{'table': [{'audio': '/static/audio/t.mp3'}]}]},
            'sections[0].table[0].audio',
        ),
        (
            {'sections': [{'rules': [{'audio': '/static/audio/r.mp3'}]}]},
            'sections[0].rules[0].audio',
        ),
        (
            {'test_sections': [{'exercises': [{'audio': '/static/audio/e.mp3'}]}]},
            'test_sections[0].exercises[0].audio',
        ),
        ({'items': [{'audio_url': '/static/audio/i.mp3'}]}, 'items[0].audio_url'),
    ])
    def test_nested_reference_is_found(self, content, expected_path):
        assert expected_path in _refs(content)

    def test_list_form_is_expanded(self):
        refs = _refs({'cards': [{'audio': ['/static/audio/a.mp3', '/static/audio/b.mp3']}]})

        assert refs['cards[0].audio[0]'] == '/static/audio/a.mp3'
        assert refs['cards[0].audio[1]'] == '/static/audio/b.mp3'

    def test_arbitrary_depth_is_reached(self):
        content = {'a': {'b': [{'c': {'d': [{'audio': '/static/audio/deep.mp3'}]}}]}}

        assert '/static/audio/deep.mp3' in _refs(content).values()

    def test_top_level_url_still_counts(self):
        assert _refs({'url': '/static/audio/top.mp3'})['url'] == '/static/audio/top.mp3'

    def test_generic_nested_url_is_not_mistaken_for_audio(self):
        """`url` is generic — a nested cover image must not become an audio ref."""
        refs = _refs({'cover': {'url': 'https://img.example/pic.png'}})

        assert refs == {}

    def test_empty_strings_are_skipped(self):
        assert _refs({'vocabulary': [{'audio': '   '}]}) == {}


class TestMissingAudioDetection:
    @pytest.mark.parametrize('ref,expected', [
        ('/static/audio/x.mp3', 'x.mp3'),
        ('static/audio/x.mp3', 'x.mp3'),
        ('[sound:y.mp3]', 'y.mp3'),
        ('z.mp3', 'z.mp3'),
        ('https://cdn.example/a.mp3', None),
        ('', None),
        (None, None),
    ])
    def test_filename_extraction(self, ref, expected):
        assert audio_filename(ref) == expected

    def test_present_file_is_reported_present(self, tmp_path):
        (tmp_path / 'here.mp3').write_bytes(b'0')

        assert file_exists('/static/audio/here.mp3', tmp_path) is True

    def test_absent_file_is_reported_absent(self, tmp_path):
        assert file_exists('/static/audio/gone.mp3', tmp_path) is False

    def test_external_url_fails_open(self, tmp_path):
        """We cannot verify a remote host, so we must not delete the reference."""
        assert file_exists('https://cdn.example/a.mp3', tmp_path) is True


class TestVocabularyTemplateHandlesFailure:
    def test_play_has_a_catch(self):
        template = (
            Path(__file__).resolve().parents[2]
            / 'app' / 'templates' / 'curriculum' / 'lessons' / 'vocabulary.html'
        ).read_text(encoding='utf-8')

        assert 'audioPlayer.play()' in template
        assert 'played.catch(' in template
        assert 'markAudioUnavailable(btn)' in template
        assert 'function markAudioUnavailable(btn)' in template

    def test_an_aborted_play_does_not_disable_the_button(self):
        """One shared Audio element: starting word B aborts word A's play().

        That rejection says nothing about A's clip, so it must not take A's
        speaker out of the tab order for the rest of the lesson.
        """
        template = (
            Path(__file__).resolve().parents[2]
            / 'app' / 'templates' / 'curriculum' / 'lessons' / 'vocabulary.html'
        ).read_text(encoding='utf-8')

        catch_at = template.index('played.catch(')
        mark_at = template.index('markAudioUnavailable(btn)', catch_at)
        assert "'AbortError'" in template[catch_at:mark_at]

    def test_unavailable_state_is_styled(self):
        css = (
            Path(__file__).resolve().parents[2]
            / 'app' / 'static' / 'css' / 'vocabulary-cards.css'
        ).read_text(encoding='utf-8')

        assert '.audio-btn-card--unavailable' in css
