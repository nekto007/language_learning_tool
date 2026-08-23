"""Unit tests for scripts/quality_pass_module_completed_json.py.

Covers the safe automatable transforms only: dictation/sentence_correction
mode addition, translation legacy → items[]+mode migration, writing_prompt
field enrichment, final_test stub instruction rewrites, and matching pair
shape normalisation. Tests use small in-memory inputs without touching
the real content pools.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

import quality_pass_module_completed_json as quality_pass_mod  # noqa: E402
from quality_pass_module_completed_json import (  # noqa: E402
    STUB_INSTRUCTIONS,
    _audio_path_exists,
    _enrich_writing_prompt_entry,
    _migrate_translation_entry,
    _patch_final_test_matching,
    _patch_final_test_stub,
)


# ---------------------------------------------------------------------------
# translation migration
# ---------------------------------------------------------------------------


def test_translation_migration_creates_items_and_mode_for_a1():
    entry = {
        "external_key": "x",
        "level": "A1",
        "content": {
            "russian": "Я здесь.",
            "english": "I am here.",
            "hint_words": ["I", "am", "here"],
        },
    }
    changed = _migrate_translation_entry(entry)
    assert changed is True
    assert entry["content"]["mode"] == "guided"
    items = entry["content"]["items"]
    assert len(items) == 1
    assert items[0]["russian"] == "Я здесь."
    assert items[0]["english"] == "I am here."
    assert items[0]["hint_words"] == ["I", "am", "here"]
    assert items[0]["alternatives"] == []
    for legacy_key in ("russian", "english", "hint_words", "alternatives"):
        assert legacy_key not in entry["content"]


def test_translation_migration_uses_open_mode_for_b1_plus():
    entry = {
        "external_key": "x",
        "level": "B2",
        "content": {"russian": "x", "english": "y"},
    }
    _migrate_translation_entry(entry)
    assert entry["content"]["mode"] == "open"


def test_translation_migration_is_idempotent():
    entry = {
        "external_key": "x",
        "level": "A1",
        "content": {
            "mode": "guided",
            "items": [{"russian": "Я.", "english": "I.", "hint_words": [], "alternatives": []}],
        },
    }
    changed = _migrate_translation_entry(entry)
    assert changed is False
    assert len(entry["content"]["items"]) == 1


# ---------------------------------------------------------------------------
# writing_prompt enrichment
# ---------------------------------------------------------------------------


def test_writing_prompt_enrichment_populates_all_curated_fields():
    entry = {
        "external_key": "x",
        "level": "A1",
        "description": "Опишите свой день.",
        "content": {
            "prompt": "Write about your day.",
            "min_words": 25,
            "example_response": "I get up at seven.",
            "checklist": ["a", "b", "c", "d"],
        },
    }
    changed = _enrich_writing_prompt_entry(entry)
    assert changed is True
    c = entry["content"]
    assert c["prompt_ru"] == "Опишите свой день."
    assert c["mode"] == "guided"
    assert c["min_sentences"] == 25 // 8
    assert c["template"] == ""
    assert c["hint_words"] == []
    assert c["target_phrases"] == []
    assert c["min_checklist"] == max(2, len(["a", "b", "c", "d"]) // 2)


def test_writing_prompt_enrichment_uses_structured_mode_for_b1_plus():
    entry = {"level": "B1", "description": "", "content": {"prompt": "x"}}
    _enrich_writing_prompt_entry(entry)
    assert entry["content"]["mode"] == "structured"
    # min_sentences fall-back ladder per CEFR
    assert entry["content"]["min_sentences"] == 6


def test_writing_prompt_enrichment_is_idempotent():
    entry = {
        "level": "A1",
        "description": "x",
        "content": {
            "prompt": "x",
            "prompt_ru": "ru",
            "mode": "guided",
            "min_sentences": 4,
            "template": "t",
            "hint_words": ["h"],
            "target_phrases": ["p"],
            "min_checklist": 2,
            "checklist": ["1", "2"],
        },
    }
    changed = _enrich_writing_prompt_entry(entry)
    assert changed is False


# ---------------------------------------------------------------------------
# final_test stub rewrite
# ---------------------------------------------------------------------------


def test_patch_final_test_stub_rewrites_known_phrases():
    content = {
        "test_sections": [
            {
                "questions": [
                    {
                        "type": "transformation",
                        "instruction": "Сделайте вопрос",
                        "sentence": "She runs.",
                        "correct": "Does she run?",
                    },
                    {
                        "type": "transformation",
                        "instruction": "Сделайте отрицание",
                        "sentence": "He plays.",
                        "correct": "He does not play.",
                    },
                ]
            }
        ]
    }
    edits = _patch_final_test_stub(content)
    assert edits == 2
    insts = [q["instruction"] for q in content["test_sections"][0]["questions"]]
    assert insts == [
        STUB_INSTRUCTIONS["Сделайте вопрос"],
        STUB_INSTRUCTIONS["Сделайте отрицание"],
    ]


def test_patch_final_test_stub_matches_case_insensitively():
    """Stub detection must casefold to align with the validator's
    case-insensitive `сделайте вопрос` placeholder check; otherwise the
    quality-pass and validator disagree and the rollout never converges."""
    content = {
        "test_sections": [
            {
                "questions": [
                    {
                        "type": "transformation",
                        "instruction": "СДЕЛАЙТЕ ВОПРОС",
                        "sentence": "She runs.",
                        "correct": "Does she run?",
                    },
                    {
                        "type": "transformation",
                        "instruction": "сделайте Вопрос",
                        "sentence": "He plays.",
                        "correct": "Does he play?",
                    },
                ]
            }
        ]
    }
    edits = _patch_final_test_stub(content)
    assert edits == 2
    canonical = STUB_INSTRUCTIONS["Сделайте вопрос"]
    insts = [q["instruction"] for q in content["test_sections"][0]["questions"]]
    assert insts == [canonical, canonical]


def test_patch_final_test_stub_skips_already_canonical():
    content = {
        "test_sections": [
            {
                "questions": [
                    {
                        "type": "transformation",
                        "instruction": "Преобразуйте утверждение в вопрос:",
                        "sentence": "x",
                        "correct": "y",
                    }
                ]
            }
        ]
    }
    assert _patch_final_test_stub(content) == 0


# ---------------------------------------------------------------------------
# matching pair normalisation
# ---------------------------------------------------------------------------


def test_patch_final_test_matching_normalises_left_right_with_cyrillic_left():
    content = {
        "test_sections": [
            {
                "questions": [
                    {
                        "type": "matching",
                        "pairs": [
                            {"left": "здравствуйте", "right": "hello"},
                            {"left": "до свидания", "right": "goodbye"},
                        ],
                    }
                ]
            }
        ]
    }
    edits = _patch_final_test_matching(content)
    assert edits == 1
    pairs = content["test_sections"][0]["questions"][0]["pairs"]
    assert pairs == [
        {"english": "hello", "russian": "здравствуйте"},
        {"english": "goodbye", "russian": "до свидания"},
    ]


def test_patch_final_test_matching_default_orientation_keeps_left_as_english():
    content = {
        "test_sections": [
            {
                "questions": [
                    {
                        "type": "matching",
                        "pairs": [{"left": "hello", "right": "здравствуйте"}],
                    }
                ]
            }
        ]
    }
    _patch_final_test_matching(content)
    assert content["test_sections"][0]["questions"][0]["pairs"] == [
        {"english": "hello", "russian": "здравствуйте"}
    ]


def test_patch_final_test_matching_skips_already_canonical():
    content = {
        "test_sections": [
            {
                "questions": [
                    {
                        "type": "matching",
                        "pairs": [{"english": "hello", "russian": "здравствуйте"}],
                    }
                ]
            }
        ]
    }
    assert _patch_final_test_matching(content) == 0


# ---------------------------------------------------------------------------
# _audio_path_exists: anki-style refs must hit the filesystem
# ---------------------------------------------------------------------------


def test_audio_path_exists_resolves_anki_marker_to_file(tmp_path, monkeypatch):
    """`[sound:foo.mp3]` must resolve to `<static>/audio/foo.mp3` and check
    existence, not return True unconditionally."""
    static_dir = tmp_path / "static"
    (static_dir / "audio").mkdir(parents=True)
    monkeypatch.setattr(quality_pass_mod, "STATIC_DIR", static_dir)

    assert _audio_path_exists("[sound:present.mp3]") is False
    (static_dir / "audio" / "present.mp3").write_bytes(b"\x00")
    assert _audio_path_exists("[sound:present.mp3]") is True
    assert _audio_path_exists("[sound:absent.mp3]") is False


def test_audio_path_exists_handles_static_paths(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    (static_dir / "audio" / "im").mkdir(parents=True)
    (static_dir / "audio" / "im" / "clip.mp3").write_bytes(b"\x00")
    monkeypatch.setattr(quality_pass_mod, "STATIC_DIR", static_dir)

    assert _audio_path_exists("/static/audio/im/clip.mp3") is True
    assert _audio_path_exists("/static/audio/im/missing.mp3") is False
    assert _audio_path_exists("") is False
