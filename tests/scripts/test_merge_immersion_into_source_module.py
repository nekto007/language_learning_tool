"""Unit tests for scripts/merge_immersion_into_source_module.py.

Cover:
- batch flag parsing
- discovery filters (--all, --level + --all-modules)
- canonical pedagogical ordering
- external_key insertion on every new lesson
- 1..N renumbering of id/number/order
- idempotency on re-run
- report rendering
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

import merge_immersion_into_source_module as mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_lessons() -> list[dict]:
    """The bare 12-lesson shape that 76 of 77 source modules currently use."""
    return [
        {"id": 1, "number": 1, "order": 1, "type": "vocabulary",
         "title": "Vocab", "content": {"vocabulary": [{"english": "x"}]}},
        {"id": 2, "number": 2, "order": 2, "type": "flashcards",
         "title": "Cards 1", "content": {"cards": [{"front": "a", "back": "b"}]}},
        {"id": 3, "number": 3, "order": 3, "type": "grammar",
         "title": "Grammar", "content": {"rule": "x"}},
        {"id": 4, "number": 4, "order": 4, "type": "quiz",
         "title": "Quiz", "content": {"items": [{"q": "q"}]}},
        {"id": 5, "number": 5, "order": 5, "type": "reading",
         "title": "Reading",
         "content": {"text": "x", "exercises": [{"q": "q"}]}},
        {"id": 6, "number": 6, "order": 6, "type": "listening_quiz",
         "title": "LQ", "content": {"audio_url": "/static/audio/x.mp3",
                                    "exercises": [{"q": "q"}]}},
        {"id": 7, "number": 7, "order": 7, "type": "dialogue_completion_quiz",
         "title": "DCQ", "content": {"items": [{"q": "q"}]}},
        {"id": 8, "number": 8, "order": 8, "type": "ordering_quiz",
         "title": "OQ", "content": {"items": [{"q": "q"}]}},
        {"id": 9, "number": 9, "order": 9, "type": "flashcards",
         "title": "Cards 2", "content": {"cards": [{"front": "c", "back": "d"}]}},
        {"id": 10, "number": 10, "order": 10, "type": "translation_quiz",
         "title": "TQ", "content": {"items": [{"q": "q"}]}},
        {"id": 11, "number": 11, "order": 11, "type": "listening_immersion",
         "title": "LI",
         "content": {"audio_url": "/static/audio/y.mp3", "text": "t"}},
        {"id": 12, "number": 12, "order": 12, "type": "final_test",
         "title": "FT", "content": {"test_sections": [{"q": "q"}]}},
    ]


def _write_source(dir_path: Path, filename: str, lessons: list[dict],
                  level: str = "A1") -> Path:
    payload = {"module": {"title": "Sample", "title_en": "Sample",
                          "level": level, "lessons": lessons}}
    out = dir_path / filename
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    return out


def _immersion_entry(level: str, module_number: int, lesson_type: str,
                     external_key: str | None = None,
                     content_override: dict | None = None) -> dict:
    base_content = {
        "dictation": {
            "audio_url": "/static/audio/d.mp3",
            "transcript": "Hello.",
        },
        "shadow_reading": {
            "audio_url": "/static/audio/s.mp3",
            "text": "Practice shadowing.",
        },
        "writing_prompt": {
            "prompt": "Write something.",
            "prompt_ru": "Напиши текст.",
            "checklist": ["greeting"],
            "min_sentences": 3,
        },
        "collocation_matching": {"pairs": [{"phrase": "x", "translation": "y"}]},
        "sentence_completion": {"items": [{"prompt": "p"}]},
        "sentence_correction": {"items": [{"wrong": "x", "right": "y"}]},
        "audio_fill_blank": {"items": [{
            "audio_clip_url": "/static/audio/a.mp3", "sentence": "x", "answer": "y",
        }]},
        "translation": {"items": [{"ru": "x", "en": "y"}], "mode": "ru-to-en"},
        "idiom": {"items": [{"idiom": "x", "meaning": "y"}]},
    }
    return {
        "external_key": external_key or f"immersion:{lesson_type}:{level}:{module_number:02}",
        "level": level,
        "module_number": module_number,
        "lesson_type": lesson_type,
        "title": f"{lesson_type} {level}-{module_number}",
        "title_en": f"{lesson_type} {level}-{module_number}",
        "description": f"desc for {lesson_type}",
        "tags": ["immersion"],
        "content": content_override if content_override else base_content[lesson_type],
    }


@pytest.fixture
def immersion_dir(tmp_path: Path) -> Path:
    d = tmp_path / "immersion"
    d.mkdir()
    for t in ("dictation", "shadow_reading", "writing_prompt",
              "collocation_matching", "sentence_completion",
              "sentence_correction", "audio_fill_blank", "translation"):
        entries = [_immersion_entry("A1", 1, t), _immersion_entry("A1", 2, t)]
        (d / f"{t}_lessons.json").write_text(
            json.dumps(entries, ensure_ascii=False), encoding="utf-8"
        )
    # idiom only exists at B1+; keep parity with the real data.
    idiom_entries = [_immersion_entry("B1", 1, "idiom")]
    (d / "idiom_lessons.json").write_text(
        json.dumps(idiom_entries, ensure_ascii=False), encoding="utf-8"
    )
    # staging entries must be filtered out.
    (d / "staging_smoke_lessons.json").write_text(
        json.dumps([{
            "external_key": "staging:smoke:A1:1",
            "level": "A1", "module_number": 1,
            "lesson_type": "dictation", "title": "STAGING",
            "content": {"audio_url": "/x.mp3", "transcript": "skip"},
        }], ensure_ascii=False),
        encoding="utf-8",
    )
    return d


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "modules"
    d.mkdir()
    _write_source(d, "module_A1_1_greetings.json", _base_lessons(), level="A1")
    _write_source(d, "module_A1_2_numbers.json", _base_lessons(), level="A1")
    _write_source(d, "module_B1_1_topic.json", _base_lessons(), level="B1")
    return d


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discover_modules_all(source_dir: Path):
    found = mod.discover_modules(source_dir)
    triples = [(lvl, num) for (lvl, num, _) in found]
    assert triples == [("A1", 1), ("A1", 2), ("B1", 1)]


def test_discover_modules_filter_by_level(source_dir: Path):
    found = mod.discover_modules(source_dir, level="A1")
    triples = [(lvl, num) for (lvl, num, _) in found]
    assert triples == [("A1", 1), ("A1", 2)]


def test_discover_modules_filter_by_level_and_number(source_dir: Path):
    found = mod.discover_modules(source_dir, level="A1", module_number=2)
    triples = [(lvl, num) for (lvl, num, _) in found]
    assert triples == [("A1", 2)]


# ---------------------------------------------------------------------------
# Single-module merge
# ---------------------------------------------------------------------------


def test_merge_inserts_missing_types_and_renumbers(source_dir: Path, immersion_dir: Path):
    summary = mod.merge_module(
        "A1", 1, dry_run=False,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    assert summary["added_count"] > 0
    assert summary["changed"] is True

    on_disk = json.loads((source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8"))
    lessons = on_disk["module"]["lessons"]
    # 12 original + 8 immersion types (dictation, shadow_reading, writing_prompt,
    # collocation_matching, sentence_completion, sentence_correction,
    # audio_fill_blank, translation).
    assert len(lessons) == 20
    # 1..N renumbering.
    for idx, l in enumerate(lessons, start=1):
        assert l["id"] == idx
        assert l["number"] == idx
        assert l["order"] == idx


def test_merge_skips_staging_entries(source_dir: Path, immersion_dir: Path):
    """staging:* external_keys must never be merged into source JSON."""
    mod.merge_module(
        "A1", 1, dry_run=False,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    on_disk = json.loads((source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8"))
    titles = [l["title"] for l in on_disk["module"]["lessons"]]
    assert "STAGING" not in titles


def test_merge_assigns_external_key_to_every_inserted_lesson(source_dir: Path, immersion_dir: Path):
    mod.merge_module(
        "A1", 1, dry_run=False,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    on_disk = json.loads((source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8"))
    inserted_types = {
        "dictation", "shadow_reading", "writing_prompt",
        "collocation_matching", "sentence_completion", "sentence_correction",
        "audio_fill_blank", "translation",
    }
    for l in on_disk["module"]["lessons"]:
        if l["type"] in inserted_types:
            assert l["content"].get("external_key"), (
                f"missing external_key on inserted {l['type']}"
            )


def test_merge_respects_canonical_order(source_dir: Path, immersion_dir: Path):
    mod.merge_module(
        "A1", 1, dry_run=False,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    on_disk = json.loads((source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8"))
    types = [l["type"] for l in on_disk["module"]["lessons"]]
    # Spot-check key canonical positions.
    assert types[0] == "vocabulary"
    assert types[1] == "flashcards"
    assert types[-1] == "final_test"
    # Both flashcards lessons appear, with the first one early and the second
    # one in the late-review slot.
    fc_positions = [i for i, t in enumerate(types) if t == "flashcards"]
    assert len(fc_positions) == 2
    assert fc_positions[0] < types.index("grammar")
    assert fc_positions[1] > types.index("ordering_quiz")


def test_merge_is_idempotent(source_dir: Path, immersion_dir: Path):
    first = mod.merge_module(
        "A1", 1, dry_run=False,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    assert first["changed"] is True
    second = mod.merge_module(
        "A1", 1, dry_run=False,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    assert second["changed"] is False
    assert second["added_count"] == 0


def test_merge_dry_run_does_not_write(source_dir: Path, immersion_dir: Path):
    before = (source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8")
    summary = mod.merge_module(
        "A1", 1, dry_run=True,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    after = (source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8")
    assert before == after
    # Summary should still record what would change.
    assert summary["added_count"] > 0
    assert summary["changed"] is True


def test_merge_does_not_insert_pronunciation(source_dir: Path, immersion_dir: Path):
    """`pronunciation` is intentionally excluded from automatic merges."""
    # Add a pronunciation immersion file and verify it's still ignored.
    pron = [_immersion_entry("A1", 1, "writing_prompt",
                              external_key="immersion:pronunciation:A1:01")]
    # Rewrite as a pronunciation lesson_type entry.
    pron[0]["lesson_type"] = "pronunciation"
    pron[0]["content"] = {"words": ["hello"]}
    (immersion_dir / "pronunciation_lessons.json").write_text(
        json.dumps(pron, ensure_ascii=False), encoding="utf-8"
    )
    mod.merge_module(
        "A1", 1, dry_run=False,
        source_dir=source_dir, immersion_dir=immersion_dir,
    )
    on_disk = json.loads((source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8"))
    assert all(l["type"] != "pronunciation" for l in on_disk["module"]["lessons"])


# ---------------------------------------------------------------------------
# Batch merge
# ---------------------------------------------------------------------------


def test_merge_batch_all(source_dir: Path, immersion_dir: Path):
    summaries = mod.merge_batch(
        None,
        dry_run=False,
        source_dir=source_dir,
        immersion_dir=immersion_dir,
        all_modules=True,
    )
    assert {s["filename"] for s in summaries} == {
        "module_A1_1_greetings.json",
        "module_A1_2_numbers.json",
        "module_B1_1_topic.json",
    }
    # B1/1 has idiom available and 0 of the limited types skipped (none of those
    # exist in B1 in our fixture). It still gets dictation/shadow/writing —
    # wait, our fixture only seeded those at A1. Let me check: only B1 had
    # idiom_lessons.json. So B1 gets exactly 1 insertion.
    by_level = {(s["level"], s["module_number"]): s for s in summaries}
    assert by_level[("B1", 1)]["added_count"] == 1


def test_merge_batch_filter_by_level(source_dir: Path, immersion_dir: Path):
    summaries = mod.merge_batch(
        None,
        dry_run=True,
        source_dir=source_dir,
        immersion_dir=immersion_dir,
        all_modules=True,
        level="A1",
    )
    assert len(summaries) == 2
    assert {(s["level"], s["module_number"]) for s in summaries} == {("A1", 1), ("A1", 2)}


def test_merge_batch_explicit_selectors(source_dir: Path, immersion_dir: Path):
    summaries = mod.merge_batch(
        [("A1", 1)],
        dry_run=True,
        source_dir=source_dir,
        immersion_dir=immersion_dir,
    )
    assert len(summaries) == 1
    assert summaries[0]["filename"] == "module_A1_1_greetings.json"


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def test_render_summary_report_lists_changes(source_dir: Path, immersion_dir: Path):
    summaries = mod.merge_batch(
        None,
        dry_run=True,
        source_dir=source_dir,
        immersion_dir=immersion_dir,
        all_modules=True,
    )
    report = mod.render_summary_report(summaries, dry_run=True)
    assert "module_completed/fixed merge preview" in report
    assert "module_A1_1_greetings.json" in report
    assert "Inserted lesson types" in report
    assert "dictation" in report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def test_cli_dry_run_writes_report(tmp_path: Path, source_dir: Path, immersion_dir: Path):
    report_path = tmp_path / "merge_preview.md"
    rc = mod.main([
        "--all",
        "--dry-run",
        "--source-dir", str(source_dir),
        "--immersion-dir", str(immersion_dir),
        "--output-report", str(report_path),
    ])
    assert rc == 0
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "Modules processed" in text


def test_cli_apply_and_dry_run_mutually_exclusive():
    rc = mod.main(["--all", "--apply", "--dry-run"])
    assert rc == 2


def test_cli_all_modules_requires_level():
    rc = mod.main(["--all-modules"])
    assert rc == 2


def test_cli_needs_a_selector():
    rc = mod.main([])
    assert rc == 2
