"""Merge immersion lesson entries from `content/immersion/*.json` into one or
more canonical source module JSON files under `module_completed/fixed/`.

For each `(level, module_number)` pair the script:

  * loads the source module file
  * loads matching entries from each `content/immersion/<type>_lessons.json`
  * builds a new `lessons[]` list in a fixed pedagogical order
    (easy → hard, final_test last)
  * renumbers local `id`, `number`, and `order` to 1..N
  * writes the merged module back (unless ``--dry-run``)

The merge is idempotent at the lesson-type level: once a lesson type is
present in the source module (regardless of payload content), re-running
will not insert another copy of that type or replace the existing lesson.
To update the payload of an already-inserted lesson, edit the source module
file directly or remove the lesson before re-running the script.

Each inserted lesson always carries `content.external_key` so downstream
import/diff tooling can key on stable identity instead of on `number`.

The pedagogical order is centralised in `LESSON_ORDER` (see below).

Usage
-----

Single module (legacy invocation, still supported):

    python scripts/merge_immersion_into_source_module.py \
        --level A1 --module-number 1 [--dry-run]

Batch invocations:

    # every source module
    python scripts/merge_immersion_into_source_module.py --all --dry-run

    # every module in one CEFR level
    python scripts/merge_immersion_into_source_module.py --level B1 --all-modules

    # write a per-module merge report
    python scripts/merge_immersion_into_source_module.py --all \
        --output-report reports/module_completed_json_merge_preview.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"
IMMERSION_DIR = PROJECT_ROOT / "content" / "immersion"


# Canonical pedagogical order. Types appearing in this list are inserted in
# this order. `flashcards` appears twice — first/second occurrences are
# disambiguated via the `tag` slot.
# `pronunciation` is intentionally excluded: Web Speech API is unreliable
# (no Firefox support, flaky on Safari for single short words). The
# speaking-skill track stays on shadow_reading.
LESSON_ORDER: list[tuple[str, str]] = [
    ("vocabulary", ""),
    ("flashcards", "first"),
    ("collocation_matching", ""),
    ("grammar", ""),
    ("sentence_completion", ""),
    ("sentence_correction", ""),
    ("quiz", ""),
    ("reading", ""),
    ("idiom", ""),
    ("listening_quiz", ""),
    ("audio_fill_blank", ""),
    ("dictation", ""),
    ("dialogue_completion_quiz", ""),
    ("ordering_quiz", ""),
    ("shadow_reading", ""),
    ("flashcards", "second"),
    ("translation_quiz", ""),
    ("translation", ""),
    ("listening_immersion", ""),
    ("writing_prompt", ""),
    ("final_test", ""),
]

# Immersion lesson types we may insert. Lesson types already present in the
# source module are skipped (they are left as-is in the merged list).
# `pronunciation` is deliberately omitted — see comment above.
NEW_LESSON_TYPES: tuple[str, ...] = (
    "dictation",
    "writing_prompt",
    "shadow_reading",
    "audio_fill_blank",
    "translation",
    "sentence_correction",
    "sentence_completion",
    "collocation_matching",
    "idiom",
)


_FILENAME_RE = re.compile(
    r"^module_(?P<level>[A-C][0-9])_(?P<order>\d+)_(?P<slug>.+)\.json$"
)


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def find_source_path(level: str, module_number: int, source_dir: Path | None = None) -> Path:
    base = source_dir or SOURCE_DIR
    matches = list(base.glob(f"module_{level}_{module_number}_*.json"))
    if not matches:
        raise FileNotFoundError(
            f"no source file matches level={level} module={module_number} under {base}"
        )
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous source files: {matches}")
    return matches[0]


def discover_modules(
    source_dir: Path,
    *,
    level: str | None = None,
    module_number: int | None = None,
) -> list[tuple[str, int, Path]]:
    """Return ``(level, module_number, path)`` triples for every source module
    matching the optional ``level`` / ``module_number`` filters."""
    out: list[tuple[str, int, Path]] = []
    if not source_dir.exists():
        return out
    for path in sorted(source_dir.glob("*.json")):
        m = _FILENAME_RE.match(path.name)
        if not m:
            continue
        lvl = m.group("level")
        num = int(m.group("order"))
        if level and lvl != level:
            continue
        if module_number is not None and num != module_number:
            continue
        out.append((lvl, num, path))
    return out


# ---------------------------------------------------------------------------
# Immersion entry parsing
# ---------------------------------------------------------------------------


def load_immersion_entries(
    level: str,
    module_number: int,
    *,
    immersion_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Return immersion-side entries matching this (level, module_number).
    Skips entries whose external_key starts with 'staging:'."""
    base = immersion_dir or IMMERSION_DIR
    entries: list[dict[str, Any]] = []
    if not base.exists():
        return entries
    for path in sorted(base.glob("*_lessons.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"WARN: {path.name}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, list):
            continue
        for entry in data:
            if not isinstance(entry, dict):
                continue
            ext = str(entry.get("external_key") or "")
            if ext.startswith("staging:"):
                continue
            if entry.get("level") != level:
                continue
            if entry.get("module_number") != module_number:
                continue
            entries.append(entry)
    return entries


def immersion_to_source_lesson(entry: dict[str, Any]) -> dict[str, Any]:
    """Translate an immersion-content entry into a module `lessons[]` shape.

    Embeds the immersion `external_key` inside `content.external_key` so the
    importer can match by stable identity.
    """
    content = dict(entry.get("content") or {})
    if "external_key" not in content and entry.get("external_key"):
        content["external_key"] = entry["external_key"]
    result: dict[str, Any] = {
        "type": entry["lesson_type"],
        "title": entry["title"],
        "content": content,
    }
    if entry.get("description"):
        result["description"] = entry["description"]
    if entry.get("title_en"):
        result["title_en"] = entry["title_en"]
    return result


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def _slot_for(lesson: dict[str, Any], seen_same_type: dict[str, int]) -> tuple[int, str]:
    """Return (position, tag) of the slot in LESSON_ORDER for a lesson.

    The first `flashcards` lesson gets tag="first", the second
    gets tag="second"; everything else uses tag="".
    """
    t = lesson.get("type", "")
    n = seen_same_type.get(t, 0)
    if t == "flashcards":
        tag = "first" if n == 0 else "second"
    else:
        tag = ""
    seen_same_type[t] = n + 1
    for i, (cand_type, cand_tag) in enumerate(LESSON_ORDER):
        if cand_type == t and cand_tag == tag:
            return i, tag
    return len(LESSON_ORDER) + n, tag


def _renumber(lessons: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, lesson in enumerate(lessons, start=1):
        lesson["id"] = idx
        lesson["number"] = idx
        lesson["order"] = idx
        out.append(lesson)
    return out


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_module(
    level: str,
    module_number: int,
    *,
    dry_run: bool = False,
    source_dir: Path | None = None,
    immersion_dir: Path | None = None,
) -> dict[str, Any]:
    """Merge immersion content into a single source module file."""
    source_path = find_source_path(level, module_number, source_dir=source_dir)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    module = source["module"]
    original_lessons: list[dict[str, Any]] = list(module.get("lessons") or [])
    original_types = [l.get("type") for l in original_lessons]

    immersion_entries = load_immersion_entries(level, module_number, immersion_dir=immersion_dir)
    new_entries_by_type: dict[str, list[dict[str, Any]]] = {}
    for e in immersion_entries:
        new_entries_by_type.setdefault(e["lesson_type"], []).append(e)

    # Build the union list: keep every original lesson and add any missing
    # new-type lesson. If a new-type lesson is already present (e.g. the file
    # has already been merged), keep the existing one and skip the immersion
    # copy.
    existing_types = set(original_types)
    union: list[dict[str, Any]] = list(original_lessons)
    added: list[dict[str, str]] = []
    for t in NEW_LESSON_TYPES:
        if t in existing_types:
            continue
        for entry in new_entries_by_type.get(t, []):
            inserted = immersion_to_source_lesson(entry)
            # Defensive: ensure every inserted lesson carries
            # content.external_key (the importer keys on it).
            content = inserted.setdefault("content", {})
            if "external_key" not in content and entry.get("external_key"):
                content["external_key"] = entry["external_key"]
            union.append(inserted)
            added.append({
                "type": t,
                "external_key": content.get("external_key") or "",
                "title": inserted.get("title", ""),
            })

    # Sort the union by canonical pedagogical order.
    seen: dict[str, int] = {}
    union_indexed = [(*_slot_for(l, seen), l) for l in union]
    union_indexed.sort(key=lambda triplet: (triplet[0], triplet[1]))
    ordered = [triplet[2] for triplet in union_indexed]

    # Renumber id/number/order to 1..N.
    ordered = _renumber(ordered)

    module["lessons"] = ordered
    source["module"] = module

    # Detect whether the on-disk file already matches the merged output,
    # so an idempotent re-run reports zero diff.
    new_blob = json.dumps(source, ensure_ascii=False, indent=2) + "\n"
    current_blob = source_path.read_text(encoding="utf-8")
    changed = new_blob != current_blob

    summary = {
        "level": level,
        "module_number": module_number,
        "source_path": str(source_path),
        "filename": source_path.name,
        "original_count": len(original_lessons),
        "added_count": len(added),
        "added_lessons": added,
        "final_count": len(ordered),
        "final_order": [{"type": l.get("type"), "title": l.get("title")} for l in ordered],
        "changed": changed,
    }

    if changed and not dry_run:
        source_path.write_text(new_blob, encoding="utf-8")

    return summary


def merge_batch(
    selectors: list[tuple[str, int]] | None,
    *,
    dry_run: bool = False,
    source_dir: Path | None = None,
    immersion_dir: Path | None = None,
    all_modules: bool = False,
    level: str | None = None,
) -> list[dict[str, Any]]:
    """Merge a batch of modules.

    If ``selectors`` is given it overrides ``all_modules``/``level`` and
    contains explicit ``(level, module_number)`` tuples. Otherwise every
    module matching the level filter is discovered on disk.
    """
    base = source_dir or SOURCE_DIR
    if selectors is None:
        selectors = [
            (lvl, num) for (lvl, num, _) in discover_modules(base, level=level)
        ]
    summaries: list[dict[str, Any]] = []
    for lvl, num in selectors:
        try:
            summary = merge_module(
                lvl,
                num,
                dry_run=dry_run,
                source_dir=source_dir,
                immersion_dir=immersion_dir,
            )
        except FileNotFoundError as exc:
            summaries.append({
                "level": lvl,
                "module_number": num,
                "error": str(exc),
            })
            continue
        summaries.append(summary)
    return summaries


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_summary_report(summaries: list[dict[str, Any]], *, dry_run: bool) -> str:
    lines: list[str] = []
    title_mode = "preview" if dry_run else "result"
    lines.append(f"# module_completed/fixed merge {title_mode}")
    lines.append("")
    mode = "dry-run" if dry_run else "apply"
    lines.append(f"_Mode_: **{mode}**")
    lines.append("")

    counter: Counter[str] = Counter()
    files_changed = 0
    files_unchanged = 0
    errors = 0
    for s in summaries:
        if "error" in s:
            errors += 1
            continue
        if s.get("changed"):
            files_changed += 1
        else:
            files_unchanged += 1
        for added in s.get("added_lessons", []):
            counter[added["type"]] += 1

    lines.append("## Overview")
    lines.append("")
    lines.append(f"- Modules processed: **{len(summaries)}**")
    lines.append(f"- Modules with changes: **{files_changed}**")
    lines.append(f"- Modules already-up-to-date: **{files_unchanged}**")
    if errors:
        lines.append(f"- Errors: **{errors}**")
    lines.append("")

    if counter:
        lines.append("### Inserted lesson types")
        lines.append("")
        lines.append("| lesson_type | inserted |")
        lines.append("| --- | ---: |")
        for t, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| {t} | {n} |")
        lines.append("")

    lines.append("## Per-module detail")
    lines.append("")
    for s in summaries:
        head = f"### {s.get('level')}/{s.get('module_number')}"
        filename = s.get("filename") or s.get("source_path", "")
        lines.append(f"{head} — `{filename}`")
        if "error" in s:
            lines.append("")
            lines.append(f"- ERROR: {s['error']}")
            lines.append("")
            continue
        lines.append("")
        lines.append(f"- Original lessons: {s['original_count']}")
        lines.append(f"- Added lessons: {s['added_count']}")
        lines.append(f"- Final lessons: {s['final_count']}")
        lines.append(f"- Changed: {'yes' if s['changed'] else 'no'}")
        if s["added_lessons"]:
            lines.append("- Inserted:")
            for a in s["added_lessons"]:
                ek = a.get("external_key") or "(no external_key)"
                lines.append(f"  - `{a['type']}` — `{ek}` — {a['title']}")
        lines.append("")
        lines.append("- Final order:")
        for i, l in enumerate(s["final_order"], 1):
            lines.append(f"  {i:>2}. `{l['type']}` — {l['title']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge immersion lessons into source module JSON files."
    )
    parser.add_argument("--level", help="CEFR level filter, e.g. A1")
    parser.add_argument("--module-number", type=int, help="Module number filter")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every module under module_completed/fixed/.",
    )
    parser.add_argument(
        "--all-modules",
        action="store_true",
        help="Process every module within the selected level "
        "(requires --level, ignored with --all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing any file.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write merged JSON files to disk (mutually exclusive with --dry-run).",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=SOURCE_DIR,
        help="Override source directory (defaults to module_completed/fixed).",
    )
    parser.add_argument(
        "--immersion-dir",
        type=Path,
        default=IMMERSION_DIR,
        help="Override immersion content directory.",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        help="Write a Markdown merge report to this path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.apply and args.dry_run:
        print("ERROR: --apply and --dry-run are mutually exclusive.", file=sys.stderr)
        return 2

    # Default to dry-run unless --apply is explicitly passed. This keeps batch
    # operations safe: nobody can accidentally rewrite 77 files.
    dry_run = True if (args.dry_run or not args.apply) else False

    # Determine selectors.
    if args.all:
        selectors = None
        level_filter = None
    elif args.all_modules:
        if not args.level:
            print("ERROR: --all-modules requires --level.", file=sys.stderr)
            return 2
        selectors = None
        level_filter = args.level
    elif args.level and args.module_number is not None:
        selectors = [(args.level, args.module_number)]
        level_filter = None
    else:
        print(
            "ERROR: pick one of: --all, --all-modules --level <L>, or "
            "--level <L> --module-number <N>.",
            file=sys.stderr,
        )
        return 2

    summaries = merge_batch(
        selectors,
        dry_run=dry_run,
        source_dir=args.source_dir,
        immersion_dir=args.immersion_dir,
        all_modules=bool(args.all or args.all_modules),
        level=level_filter,
    )

    report = render_summary_report(summaries, dry_run=dry_run)

    if args.output_report:
        args.output_report.parent.mkdir(parents=True, exist_ok=True)
        args.output_report.write_text(report, encoding="utf-8")
        print(f"Wrote report to {args.output_report}")

    # Always emit a short console summary so single-module invocations stay
    # readable.
    if len(summaries) == 1:
        s = summaries[0]
        if "error" in s:
            print(f"ERROR for {s.get('level')}/{s.get('module_number')}: {s['error']}")
            return 1
        print(f"Source: {s['source_path']}")
        print(f"Original lessons: {s['original_count']}")
        print(f"Added lessons: {s['added_count']}")
        for a in s["added_lessons"]:
            print(f"  + {a['type']:30}  {a['external_key']}")
        print(f"Final lessons: {s['final_count']}")
        print("\nFinal order:")
        for i, l in enumerate(s["final_order"], 1):
            print(f"  {i:2}. {l['type']:30}  {l['title']}")
        if dry_run:
            print("\n(dry-run — no file written)")
    else:
        changed = sum(1 for s in summaries if not s.get("error") and s.get("changed"))
        unchanged = sum(1 for s in summaries if not s.get("error") and not s.get("changed"))
        errored = sum(1 for s in summaries if s.get("error"))
        print(
            f"Processed {len(summaries)} module(s): "
            f"{changed} changed, {unchanged} unchanged, {errored} error(s)."
        )
        if dry_run:
            print("(dry-run — no files written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
