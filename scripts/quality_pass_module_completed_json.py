"""Task 4 quality pass for module_completed JSON rollout.

Audits per-type quality across:
- content/immersion/<type>_lessons.json (source pools used by the merge script)
- module_completed/fixed/module_*.json (source modules that will be patched)

Applies safe automatable fixes:
- Adds `mode` to dictation pool (default: "cloze").
- Adds `mode` to sentence_correction pool (default: "guided").
- Migrates translation pool entries to the items[] + mode schema.
- Enriches writing_prompt pool with `prompt_ru`, `mode`, `min_sentences`,
  `template`, `hint_words`, `target_phrases`, and `min_checklist`.
- Rewrites stub final_test transformation instructions in source modules
  to the canonical "Преобразуйте утверждение в вопрос/отрицание:" phrasing.
- Normalises final_test matching pairs to {english, russian} shape.

Items requiring human content authoring (per-item audio generation,
collocation pair retuning by topic, progression rewrites at B1/B2/C1,
target-phrase selection per module) are listed in the deferred section
of the generated report with concrete reasons and owners.

Usage:
    python scripts/quality_pass_module_completed_json.py --dry-run
    python scripts/quality_pass_module_completed_json.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
IMMERSION_DIR = REPO_ROOT / "content" / "immersion"
MODULES_DIR = REPO_ROOT / "module_completed" / "fixed"
STATIC_DIR = REPO_ROOT / "app" / "static"
REPORT_PATH = REPO_ROOT / "reports" / "module_completed_json_quality_review.md"


STUB_INSTRUCTIONS = {
    "Сделайте вопрос": "Преобразуйте утверждение в вопрос:",
    "Сделать вопрос": "Преобразуйте утверждение в вопрос:",
    "Сделайте отрицание": "Преобразуйте утверждение в отрицание:",
}

# Lookup keyed by case-folded instruction so case variants like "сделайте Вопрос"
# or "СДЕЛАЙТЕ ВОПРОС" still match the validator's case-insensitive
# placeholder detector.
_STUB_INSTRUCTIONS_FOLDED: dict[str, str] = {
    k.casefold(): v for k, v in STUB_INSTRUCTIONS.items()
}


def _stub_instruction_target(instruction: str) -> str | None:
    """Return the canonical replacement for a stub instruction, or None."""
    if not instruction:
        return None
    return _STUB_INSTRUCTIONS_FOLDED.get(instruction.casefold())


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _dump_json(path: Path, data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


_ANKI_AUDIO_RE = re.compile(r"^\[sound:(?P<name>[^\]]+)\]$")


def _audio_path_exists(audio_url: str) -> bool:
    if not audio_url:
        return False
    ref = audio_url.strip()
    m = _ANKI_AUDIO_RE.match(ref)
    if m:
        return (STATIC_DIR / "audio" / m.group("name")).exists()
    rel = ref.lstrip("/")
    if rel.startswith("static/"):
        rel = rel[len("static/") :]
    return (STATIC_DIR / rel).exists()


def _audit_audio_fill_blank(pool: list[dict]) -> dict:
    """Audit audio_fill_blank pool."""
    findings = {
        "entries": len(pool),
        "items_total": 0,
        "items_missing_audio_clip_url": 0,
        "items_missing_options": 0,
        "items_missing_answer": 0,
        "missing_pool_modules": [],  # level/module covered
    }
    coverage = set()
    for entry in pool:
        coverage.add((entry["level"], entry.get("module_number")))
        for item in entry.get("content", {}).get("items", []):
            findings["items_total"] += 1
            if not item.get("audio_clip_url"):
                findings["items_missing_audio_clip_url"] += 1
            if not item.get("options"):
                findings["items_missing_options"] += 1
            if not item.get("answer"):
                findings["items_missing_answer"] += 1
    findings["coverage"] = sorted(coverage)
    return findings


def _audit_dictation(pool: list[dict]) -> dict:
    findings = {
        "entries": len(pool),
        "missing_mode": 0,
        "missing_audio_url": 0,
        "audio_files_missing": [],
    }
    for entry in pool:
        c = entry["content"]
        if "mode" not in c:
            findings["missing_mode"] += 1
        url = c.get("audio_url")
        if not url:
            findings["missing_audio_url"] += 1
        elif not _audio_path_exists(url):
            findings["audio_files_missing"].append(entry["external_key"])
    return findings


def _audit_shadow_reading(pool: list[dict]) -> dict:
    findings = {
        "entries": len(pool),
        "missing_audio_url": 0,
        "missing_translation": 0,
        "audio_files_missing": [],
        "text_length_by_level": defaultdict(list),
    }
    for entry in pool:
        c = entry["content"]
        url = c.get("audio_url")
        if not url:
            findings["missing_audio_url"] += 1
        elif not _audio_path_exists(url):
            findings["audio_files_missing"].append(entry["external_key"])
        if not c.get("translation"):
            findings["missing_translation"] += 1
        text = c.get("text", "")
        findings["text_length_by_level"][entry["level"]].append(len(text))
    findings["text_length_by_level"] = dict(findings["text_length_by_level"])
    return findings


def _audit_translation(pool: list[dict]) -> dict:
    findings = {
        "entries": len(pool),
        "legacy_schema_entries": 0,
        "missing_mode": 0,
        "items_total": 0,
        "items_missing_alternatives": 0,
    }
    for entry in pool:
        c = entry["content"]
        if "items" not in c:
            findings["legacy_schema_entries"] += 1
        else:
            for it in c["items"]:
                findings["items_total"] += 1
                if "alternatives" not in it:
                    findings["items_missing_alternatives"] += 1
        if "mode" not in c:
            findings["missing_mode"] += 1
    return findings


def _audit_writing_prompt(pool: list[dict]) -> dict:
    required = (
        "prompt_ru",
        "mode",
        "min_sentences",
        "template",
        "hint_words",
        "target_phrases",
        "min_checklist",
    )
    findings = {"entries": len(pool), "missing_fields": Counter()}
    for entry in pool:
        c = entry["content"]
        for k in required:
            if k not in c:
                findings["missing_fields"][k] += 1
    return findings


def _audit_collocation_matching(pool: list[dict]) -> dict:
    findings = {
        "entries": len(pool),
        "bad_pair_shape": 0,
        "items_total": 0,
        "coverage": [],
    }
    coverage = set()
    for entry in pool:
        coverage.add((entry["level"], entry.get("module_number")))
        for pair in entry["content"].get("pairs", []):
            findings["items_total"] += 1
            if not (isinstance(pair, dict) and "phrase" in pair and "translation" in pair):
                findings["bad_pair_shape"] += 1
    findings["coverage"] = sorted(coverage)
    return findings


def _audit_sentence_completion(pool: list[dict]) -> dict:
    findings = {
        "entries": len(pool),
        "missing_items": 0,
        "items_total": 0,
        "items_missing_answer": 0,
    }
    for entry in pool:
        items = entry["content"].get("items", [])
        if not items:
            findings["missing_items"] += 1
        for it in items:
            findings["items_total"] += 1
            if not it.get("answer"):
                findings["items_missing_answer"] += 1
    return findings


def _audit_sentence_correction(pool: list[dict]) -> dict:
    findings = {
        "entries": len(pool),
        "missing_mode": 0,
        "items_missing_explanation": 0,
    }
    for entry in pool:
        c = entry["content"]
        if "mode" not in c:
            findings["missing_mode"] += 1
        # Pool stores single-item correction; "items" may not exist for legacy.
        items = c.get("items", [c]) if "items" in c else [c]
        for it in items:
            if not it.get("explanation"):
                findings["items_missing_explanation"] += 1
    return findings


def _audit_idiom(pool: list[dict]) -> dict:
    findings = {"entries": len(pool), "coverage": []}
    coverage = set()
    for entry in pool:
        coverage.add((entry["level"], entry.get("module_number")))
    findings["coverage"] = sorted(coverage)
    return findings


def _audit_final_test_stubs() -> dict:
    findings = {
        "stub_modules": [],
        "non_standard_matching_modules": [],
        "parse_errors": [],
    }
    for fp in sorted(MODULES_DIR.glob("module_*.json")):
        try:
            m = _load_json(fp)
        except Exception as exc:
            findings["parse_errors"].append(f"{fp.name}: {exc}")
            continue
        for l in m.get("module", {}).get("lessons", []):
            if l.get("type") != "final_test":
                continue
            sections = (
                l.get("content", {}).get("test_sections")
                or l.get("content", {}).get("sections")
                or []
            )
            for sec in sections:
                for qkey in ("questions", "items", "exercises"):
                    items = sec.get(qkey)
                    if not isinstance(items, list):
                        continue
                    for q in items:
                        inst = (q.get("instruction") or "").strip()
                        if (
                            q.get("type") in ("transformation", "sentence_transformation")
                            and _stub_instruction_target(inst) is not None
                        ):
                            findings["stub_modules"].append((fp.name, inst))
                        if q.get("type") == "matching":
                            pairs = q.get("pairs", [])
                            for p in pairs:
                                if isinstance(p, dict) and (
                                    "left" in p or "right" in p
                                ) and not ("english" in p and "russian" in p):
                                    findings["non_standard_matching_modules"].append(
                                        fp.name
                                    )
                                    break
    findings["non_standard_matching_modules"] = sorted(
        set(findings["non_standard_matching_modules"])
    )
    return findings


def _migrate_translation_entry(entry: dict) -> bool:
    """Migrate legacy translation pool entry to items[] + mode schema.

    Returns True when the entry was changed.
    """
    c = entry["content"]
    if "items" in c and "mode" in c:
        return False
    changed = False
    if "items" not in c:
        items = [
            {
                "russian": c.get("russian", ""),
                "english": c.get("english", ""),
                "hint_words": c.get("hint_words", []),
                "alternatives": c.get("alternatives", []),
            }
        ]
        c["items"] = items
        for k in ("russian", "english", "hint_words", "alternatives"):
            c.pop(k, None)
        changed = True
    if "mode" not in c:
        level = (entry.get("level") or "A1").upper()
        c["mode"] = "guided" if level in ("A1", "A2") else "open"
        changed = True
    return changed


def _build_prompt_ru(entry: dict) -> str:
    """Heuristic Russian prompt from existing description + module hint."""
    desc = entry.get("description") or ""
    return desc.strip() or "Напишите ответ на задание, опираясь на тему модуля."


def _enrich_writing_prompt_entry(entry: dict) -> bool:
    c = entry["content"]
    level = (entry.get("level") or "A1").upper()
    changed = False
    if "prompt_ru" not in c:
        c["prompt_ru"] = _build_prompt_ru(entry)
        changed = True
    if "mode" not in c:
        c["mode"] = "guided" if level in ("A1", "A2") else "structured"
        changed = True
    if "min_sentences" not in c:
        min_words = c.get("min_words")
        if isinstance(min_words, int) and min_words > 0:
            c["min_sentences"] = max(3, min_words // 8)
        else:
            c["min_sentences"] = {"A1": 4, "A2": 5, "B1": 6, "B2": 7, "C1": 8}.get(level, 5)
        changed = True
    if "template" not in c:
        c["template"] = ""
        changed = True
    if "hint_words" not in c:
        c["hint_words"] = []
        changed = True
    if "target_phrases" not in c:
        c["target_phrases"] = []
        changed = True
    if "min_checklist" not in c:
        checklist = c.get("checklist") or []
        if checklist:
            c["min_checklist"] = max(2, len(checklist) // 2)
        else:
            c["min_checklist"] = 2
        changed = True
    return changed


def _patch_final_test_stub(content: dict) -> int:
    """Rewrite stub transformation instructions; returns count of edits."""
    edits = 0
    sections = content.get("test_sections") or content.get("sections") or []
    for sec in sections:
        for qkey in ("questions", "items", "exercises"):
            items = sec.get(qkey)
            if not isinstance(items, list):
                continue
            for q in items:
                inst = (q.get("instruction") or "").strip()
                target = _stub_instruction_target(inst)
                if (
                    q.get("type") in ("transformation", "sentence_transformation")
                    and target is not None
                ):
                    q["instruction"] = target
                    edits += 1
    return edits


def _patch_final_test_matching(content: dict) -> int:
    """Rewrite {left,right} matching pairs to {english,russian}."""
    edits = 0
    sections = content.get("test_sections") or content.get("sections") or []
    for sec in sections:
        for qkey in ("questions", "items", "exercises"):
            items = sec.get(qkey)
            if not isinstance(items, list):
                continue
            for q in items:
                if q.get("type") != "matching":
                    continue
                pairs = q.get("pairs", [])
                new_pairs = []
                patched = False
                for p in pairs:
                    if (
                        isinstance(p, dict)
                        and ("left" in p or "right" in p)
                        and not ("english" in p and "russian" in p)
                    ):
                        left = p.get("left", "")
                        right = p.get("right", "")
                        # Refuse to rewrite half-formed pairs; emitting
                        # {english: x, russian: ""} would self-inflict a
                        # final-test-matching-shape error on the next validation.
                        if not (isinstance(left, str) and left.strip()
                                and isinstance(right, str) and right.strip()):
                            new_pairs.append(p)
                            continue
                        # If the left side looks Russian, swap.
                        extra = {k: v for k, v in p.items() if k not in ("left", "right")}
                        if re.search(r"[А-Яа-яЁё]", left) and not re.search(r"[А-Яа-яЁё]", right):
                            new_pairs.append({"english": right, "russian": left, **extra})
                        else:
                            new_pairs.append({"english": left, "russian": right, **extra})
                        patched = True
                    else:
                        new_pairs.append(p)
                if patched:
                    q["pairs"] = new_pairs
                    edits += 1
    return edits


def run(apply_changes: bool) -> dict:
    findings = {}

    # Audit pools
    pools_files = {
        "audio_fill_blank": IMMERSION_DIR / "audio_fill_blank_lessons.json",
        "dictation": IMMERSION_DIR / "dictation_lessons.json",
        "shadow_reading": IMMERSION_DIR / "shadow_reading_lessons.json",
        "translation": IMMERSION_DIR / "translation_lessons.json",
        "writing_prompt": IMMERSION_DIR / "writing_prompt_lessons.json",
        "collocation_matching": IMMERSION_DIR / "collocation_matching_lessons.json",
        "sentence_completion": IMMERSION_DIR / "sentence_completion_lessons.json",
        "sentence_correction": IMMERSION_DIR / "sentence_correction_lessons.json",
        "idiom": IMMERSION_DIR / "idiom_lessons.json",
    }

    audits = {
        "audio_fill_blank": _audit_audio_fill_blank,
        "dictation": _audit_dictation,
        "shadow_reading": _audit_shadow_reading,
        "translation": _audit_translation,
        "writing_prompt": _audit_writing_prompt,
        "collocation_matching": _audit_collocation_matching,
        "sentence_completion": _audit_sentence_completion,
        "sentence_correction": _audit_sentence_correction,
        "idiom": _audit_idiom,
    }

    for name, path in pools_files.items():
        pool = _load_json(path)
        findings[name] = audits[name](pool)
        findings[name]["pool_path"] = str(path.relative_to(REPO_ROOT))

    final_test = _audit_final_test_stubs()
    findings["final_test_module_audit"] = final_test

    # Baseline gap counts — derived from the pre-fix audit so the report always
    # documents what was originally missing, even if the fixes were already
    # applied in a previous run.
    baseline = {
        "dictation_mode_missing": findings["dictation"]["missing_mode"],
        "sentence_correction_mode_missing": findings["sentence_correction"]["missing_mode"],
        "translation_legacy_entries": findings["translation"]["legacy_schema_entries"],
        "writing_prompt_curated_field_gaps": dict(findings["writing_prompt"]["missing_fields"]),
        "final_test_stub_instructions": len(findings["final_test_module_audit"]["stub_modules"]),
        "final_test_left_right_matching_modules": len(
            findings["final_test_module_audit"]["non_standard_matching_modules"]
        ),
    }
    findings["baseline"] = baseline

    # Apply fixes
    applied = {
        "dictation_mode_added": 0,
        "sentence_correction_mode_added": 0,
        "translation_migrated": 0,
        "writing_prompt_enriched": 0,
        "final_test_stubs_patched": 0,
        "final_test_matching_patched": 0,
    }

    pool = _load_json(pools_files["dictation"])
    for entry in pool:
        if "mode" not in entry["content"]:
            entry["content"]["mode"] = "cloze"
            applied["dictation_mode_added"] += 1
    if apply_changes and applied["dictation_mode_added"]:
        _dump_json(pools_files["dictation"], pool)

    pool = _load_json(pools_files["sentence_correction"])
    for entry in pool:
        if "mode" not in entry["content"]:
            entry["content"]["mode"] = "guided"
            applied["sentence_correction_mode_added"] += 1
    if apply_changes and applied["sentence_correction_mode_added"]:
        _dump_json(pools_files["sentence_correction"], pool)

    pool = _load_json(pools_files["translation"])
    for entry in pool:
        if _migrate_translation_entry(entry):
            applied["translation_migrated"] += 1
    if apply_changes and applied["translation_migrated"]:
        _dump_json(pools_files["translation"], pool)

    pool = _load_json(pools_files["writing_prompt"])
    for entry in pool:
        if _enrich_writing_prompt_entry(entry):
            applied["writing_prompt_enriched"] += 1
    if apply_changes and applied["writing_prompt_enriched"]:
        _dump_json(pools_files["writing_prompt"], pool)

    # Apply module-level fixes for final_test stubs + matching shape.
    for fp in sorted(MODULES_DIR.glob("module_*.json")):
        try:
            m = _load_json(fp)
        except Exception:
            continue
        touched = False
        for l in m.get("module", {}).get("lessons", []):
            if l.get("type") != "final_test":
                continue
            content = l.get("content", {})
            stub_edits = _patch_final_test_stub(content)
            match_edits = _patch_final_test_matching(content)
            if stub_edits or match_edits:
                touched = True
                applied["final_test_stubs_patched"] += stub_edits
                applied["final_test_matching_patched"] += match_edits
        if apply_changes and touched:
            _dump_json(fp, m)

    findings["applied"] = applied
    return findings


def _format_report(findings: dict, apply_changes: bool) -> str:
    lines: list[str] = []
    lines.append("# Task 4 — per-type quality review")
    lines.append("")
    lines.append(
        "Mode: **apply**" if apply_changes else "Mode: **dry-run** (no files written)"
    )
    lines.append("")
    lines.append("## Baseline gaps and automatable fixes")
    lines.append("")
    baseline = findings["baseline"]
    applied = findings["applied"]
    lines.append("| Dimension | Baseline gap | Fix applied this run |")
    lines.append("| --- | ---: | ---: |")
    lines.append(
        f"| dictation entries missing `mode` | {baseline['dictation_mode_missing']} | {applied['dictation_mode_added']} |"
    )
    lines.append(
        f"| sentence_correction entries missing `mode` | {baseline['sentence_correction_mode_missing']} | {applied['sentence_correction_mode_added']} |"
    )
    lines.append(
        f"| translation entries using legacy single-sentence schema | {baseline['translation_legacy_entries']} | {applied['translation_migrated']} |"
    )
    wp_gaps = baseline["writing_prompt_curated_field_gaps"]
    if wp_gaps:
        max_gap = max(wp_gaps.values())
    else:
        max_gap = 0
    lines.append(
        f"| writing_prompt entries missing one or more curated fields (worst field) | {max_gap} | {applied['writing_prompt_enriched']} |"
    )
    lines.append(
        f"| final_test stub `transformation` instructions in source modules | {baseline['final_test_stub_instructions']} | {applied['final_test_stubs_patched']} |"
    )
    lines.append(
        f"| final_test `{{left, right}}` matching modules in source modules | {baseline['final_test_left_right_matching_modules']} | {applied['final_test_matching_patched']} |"
    )
    lines.append("")
    lines.append(
        "Baseline numbers reflect the state of source files measured at the start of this run. After a successful `--apply` they go to zero on subsequent runs — the script is idempotent by design."
    )
    lines.append("")
    lines.append("### Historical baseline (captured 2026-05-18)")
    lines.append("")
    lines.append(
        "The first run of `scripts/quality_pass_module_completed_json.py --apply` on 2026-05-18 reported the following pre-fix counts. They are preserved here for the historical record."
    )
    lines.append("")
    lines.append("| Dimension | Original gap |")
    lines.append("| --- | ---: |")
    lines.append("| dictation entries missing `mode` | 77 |")
    lines.append("| sentence_correction entries missing `mode` | 25 |")
    lines.append("| translation entries using legacy single-sentence schema | 25 |")
    lines.append("| writing_prompt entries missing every curated field (`prompt_ru`, `mode`, `min_sentences`, `template`, `hint_words`, `target_phrases`, `min_checklist`) | 77 |")
    lines.append("| final_test stub `transformation` instructions in source modules | 3 (`module_A2_15_household_chores.json` ×2, `module_A2_7_healthy_lifestyle.json` ×1) |")
    lines.append("| final_test `{left, right}` matching modules | 1 (`module_A1_12_daily_habits.json` — 2 questions; `module_A1_2_numbers_and_colors.json` already mixed canonical+legacy, normalised in passing) |")
    lines.append("")

    # Per-type audit
    lines.append("## Per-type audit")
    lines.append("")
    afb = findings["audio_fill_blank"]
    lines.append("### `audio_fill_blank`")
    lines.append("")
    lines.append(f"- pool: `{afb['pool_path']}`")
    lines.append(
        f"- entries: {afb['entries']} (pool covers 25 modules across A1-C1, 5 per level)"
    )
    lines.append(f"- total items: {afb['items_total']}")
    lines.append(
        f"- items missing `audio_clip_url`: **{afb['items_missing_audio_clip_url']}** (blocking)"
    )
    lines.append(
        f"- items missing `options`: {afb['items_missing_options']} (acceptable for open-input mode but inconsistent across pool)"
    )
    lines.append(f"- items missing `answer`: {afb['items_missing_answer']}")
    lines.append("")

    dic = findings["dictation"]
    lines.append("### `dictation`")
    lines.append("")
    lines.append(f"- pool: `{dic['pool_path']}`")
    lines.append(f"- entries: {dic['entries']}")
    lines.append(f"- entries missing `mode` before fix: {dic['missing_mode']}")
    lines.append(
        f"- audio files missing on disk: {len(dic['audio_files_missing'])}"
    )
    if dic["audio_files_missing"]:
        sample = ", ".join(dic["audio_files_missing"][:5])
        lines.append(f"  - sample: {sample}")
    lines.append("")

    sr = findings["shadow_reading"]
    lines.append("### `shadow_reading`")
    lines.append("")
    lines.append(f"- pool: `{sr['pool_path']}`")
    lines.append(f"- entries: {sr['entries']}")
    lines.append(
        f"- entries missing translation: {sr['missing_translation']}, missing audio_url: {sr['missing_audio_url']}"
    )
    lines.append(
        f"- audio files missing on disk: {len(sr['audio_files_missing'])}"
    )
    lines.append("- text-length progression (chars per level, median):")
    for lvl in ("A1", "A2", "B1", "B2", "C1"):
        vals = sr["text_length_by_level"].get(lvl, [])
        if not vals:
            continue
        median = sorted(vals)[len(vals) // 2]
        lines.append(f"  - {lvl}: {len(vals)} entries, median {median} chars, max {max(vals)}")
    lines.append("")

    tr = findings["translation"]
    lines.append("### `translation`")
    lines.append("")
    lines.append(f"- pool: `{tr['pool_path']}`")
    lines.append(f"- entries: {tr['entries']}")
    lines.append(
        f"- legacy single-sentence entries before fix: {tr['legacy_schema_entries']} (migrated)"
    )
    missing_mode_after = max(0, tr["missing_mode"] - applied["translation_migrated"])
    lines.append(f"- entries still missing `mode` after fix: {missing_mode_after}")
    lines.append("")

    wp = findings["writing_prompt"]
    lines.append("### `writing_prompt`")
    lines.append("")
    lines.append(f"- pool: `{wp['pool_path']}`")
    lines.append(f"- entries: {wp['entries']}")
    lines.append("- missing fields BEFORE fix:")
    for k, v in wp["missing_fields"].most_common():
        lines.append(f"  - `{k}`: {v}")
    lines.append(
        "- automatable fix populated default values for every missing field. `target_phrases`, `template`, and `hint_words` are stub-empty; per-module curation is deferred (see below)."
    )
    lines.append("")

    cm = findings["collocation_matching"]
    lines.append("### `collocation_matching`")
    lines.append("")
    lines.append(f"- pool: `{cm['pool_path']}`")
    lines.append(
        f"- entries: {cm['entries']} (covers 25 modules; remaining 52 source modules use generic per-level fallbacks)"
    )
    lines.append(f"- items: {cm['items_total']}, bad pair shape: {cm['bad_pair_shape']}")
    lines.append("")

    sc = findings["sentence_completion"]
    lines.append("### `sentence_completion`")
    lines.append("")
    lines.append(f"- pool: `{sc['pool_path']}`")
    lines.append(
        f"- entries: {sc['entries']} (covers 25 modules; remaining modules will fall back to pool by level when merged)"
    )
    lines.append(f"- items: {sc['items_total']}, items missing answer: {sc['items_missing_answer']}")
    lines.append("")

    scorr = findings["sentence_correction"]
    lines.append("### `sentence_correction`")
    lines.append("")
    lines.append(f"- pool: `{scorr['pool_path']}`")
    lines.append(f"- entries: {scorr['entries']}")
    lines.append(
        f"- missing `mode` before fix: {scorr['missing_mode']} (fix applied)"
    )
    lines.append(
        f"- items missing `explanation`: {scorr['items_missing_explanation']}"
    )
    lines.append("")

    id_ = findings["idiom"]
    lines.append("### `idiom`")
    lines.append("")
    lines.append(f"- pool: `{id_['pool_path']}`")
    lines.append(
        f"- entries: {id_['entries']} (B1+ only; covers 15 modules of ~31 B1/B2/C1 source modules)"
    )
    lines.append("")

    ft = findings["final_test_module_audit"]
    lines.append("### `final_test` (per-module audit of `module_completed/fixed/`)")
    lines.append("")
    if ft["stub_modules"]:
        lines.append("- stub instructions detected:")
        for fname, inst in ft["stub_modules"]:
            target = _stub_instruction_target(inst) or inst
            lines.append(f"  - `{fname}`: `{inst}` → `{target}`")
    else:
        lines.append("- stub instructions detected: none")
    if ft["non_standard_matching_modules"]:
        lines.append("- modules with `{left, right}` matching pairs (normalised):")
        for fname in ft["non_standard_matching_modules"]:
            lines.append(f"  - `{fname}`")
    else:
        lines.append("- non-standard matching pair modules: none")
    if ft["parse_errors"]:
        lines.append("- parse errors (module skipped from audit):")
        for err in ft["parse_errors"]:
            lines.append(f"  - {err}")
    lines.append("")

    # Deferred items
    lines.append("## Deferred items (require human content authoring)")
    lines.append("")
    lines.append(
        "Every entry below is **explicitly deferred** with reason and owner. Task 5 (Apply) must not run for these dimensions until they are resolved."
    )
    lines.append("")
    lines.append("| Type / scope | Reason | Owner | Status |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(
        "| audio_fill_blank per-item audio | 125/125 items lack `audio_clip_url`; per-item MP3 generation pipeline (`scripts/generate_audio_fill_blank.py`) must run | content/audio | deferred |"
    )
    lines.append(
        "| audio_fill_blank / translation / sentence_completion / sentence_correction / collocation_matching coverage | each pool covers ~25 of 77 source modules; per-topic authoring needed before remaining modules can receive non-generic content | content | deferred |"
    )
    lines.append(
        "| writing_prompt per-module curation | `prompt_ru`, `template`, `hint_words`, `target_phrases` populated with structural defaults but require module-topic-aware authoring | content | deferred |"
    )
    lines.append(
        "| translation per-module curation | items[] migrated mechanically from legacy single-sentence schema; per-module re-authoring to add 3-5 progression-aware sentences is deferred | content | deferred |"
    )
    lines.append(
        "| idiom coverage | pool covers 15 B1+ modules; remaining B1/B2/C1 modules need authored idioms | content | deferred |"
    )
    lines.append(
        "| sentence_completion / sentence_correction ambiguity review | requires native-speaker pass to confirm accepted alternatives and explanation clarity | language QA | deferred |"
    )
    lines.append(
        "| collocation_matching per-topic pair retuning | pool was generated per-level pool, not per-module; module-topic alignment is a Task 4 manual gate | content | deferred |"
    )
    lines.append(
        "| Progression review (text/audio length, hint density, distractor plausibility) | requires per-module level-aware editorial review across A1→C1 ladder; automatable metrics emitted above (shadow_reading text-length medians) only flag candidates, not violations | language QA | deferred |"
    )
    lines.append(
        "| final_test type-coverage of new lesson types | mechanical stub patches applied; rewriting final tests to assess every newly inserted lesson type per module is per-module content work | content | deferred |"
    )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- The automatable fixes in this pass are schema-completion only. They do not invent content."
    )
    lines.append(
        "- Task 5 (apply source JSON updates) must wait until the deferred items above are closed or explicitly accepted as known caveats by the content owner."
    )
    lines.append(
        "- Re-running this script is idempotent: once the pools carry `mode`/`items[]`/curated fields, the fix counters report zero on subsequent runs."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes back to disk; default is dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (default).",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=REPORT_PATH,
        help="Where to write the quality review report.",
    )
    args = parser.parse_args()

    apply_changes = args.apply and not args.dry_run
    findings = run(apply_changes=apply_changes)
    report = _format_report(findings, apply_changes=apply_changes)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(report, encoding="utf-8")
    print(f"Report written: {args.report_path.relative_to(REPO_ROOT)}")
    print(json.dumps(findings["applied"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
