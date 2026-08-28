"""Normalise source module JSON files under `module_completed/fixed/`: each
lesson in `lessons[]` gets `id`, `number`, and `order` equal to its 1-based
position in the array.

Source-side `id` is a LOCAL identifier — 1..N within the module — used by
the admin importer (`app/admin/services/curriculum_import_service.py`) to
upsert lessons by `(module_id, number)`. It is NOT the DB primary key.

Stable lesson identity is the `content.external_key` field on every inserted
new-style lesson; this script never invents one. It only renumbers positions
so that the on-disk array, DB importer, and audit tooling agree.

This script does NOT write to DB. It only mutates the source JSON.

Usage
-----

Single module:

    python scripts/sync_source_module_with_db.py --level A1 --module-number 1
    python scripts/sync_source_module_with_db.py --level A1 --module-number 1 --dry-run

Batch:

    python scripts/sync_source_module_with_db.py --all --dry-run
    python scripts/sync_source_module_with_db.py --level B1 --all-modules --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"

_FILENAME_RE = re.compile(
    r"^module_(?P<level>[A-C][0-9])_(?P<order>\d+)_(?P<slug>.+)\.json$"
)


def find_source_path(level: str, module_number: int, source_dir: Path | None = None) -> Path:
    base = source_dir or SOURCE_DIR
    matches = list(base.glob(f"module_{level}_{module_number}_*.json"))
    if not matches:
        raise FileNotFoundError(f"no source file for {level}/{module_number}")
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous source files: {matches}")
    return matches[0]


def discover_modules(
    source_dir: Path,
    *,
    level: str | None = None,
    module_number: int | None = None,
) -> list[tuple[str, int, Path]]:
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


def renumber_module(
    level: str,
    module_number: int,
    *,
    dry_run: bool = False,
    source_dir: Path | None = None,
) -> dict[str, Any]:
    source_path = find_source_path(level, module_number, source_dir=source_dir)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    module = source["module"]
    lessons: list[dict[str, Any]] = module.get("lessons") or []

    for idx, lesson in enumerate(lessons, start=1):
        lesson["id"] = idx
        lesson["number"] = idx
        lesson["order"] = idx

    module["lessons"] = lessons
    source["module"] = module

    new_blob = json.dumps(source, ensure_ascii=False, indent=2) + "\n"
    current_blob = source_path.read_text(encoding="utf-8")
    changed = new_blob != current_blob

    if changed and not dry_run:
        source_path.write_text(new_blob, encoding="utf-8")

    return {
        "level": level,
        "module_number": module_number,
        "source_path": str(source_path),
        "filename": source_path.name,
        "lesson_count": len(lessons),
        "changed": changed,
        "lessons_overview": [
            {"position": idx, "id": l.get("id"), "type": l.get("type"), "title": l.get("title")}
            for idx, l in enumerate(lessons, start=1)
        ],
    }


def renumber_batch(
    selectors: list[tuple[str, int]] | None,
    *,
    dry_run: bool = False,
    source_dir: Path | None = None,
    level: str | None = None,
) -> list[dict[str, Any]]:
    base = source_dir or SOURCE_DIR
    if selectors is None:
        selectors = [
            (lvl, num) for (lvl, num, _) in discover_modules(base, level=level)
        ]
    summaries: list[dict[str, Any]] = []
    for lvl, num in selectors:
        try:
            summaries.append(
                renumber_module(
                    lvl, num, dry_run=dry_run, source_dir=source_dir,
                )
            )
        except FileNotFoundError as exc:
            summaries.append({
                "level": lvl,
                "module_number": num,
                "error": str(exc),
            })
    return summaries


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Renumber id/number/order to 1..N in source module JSON."
    )
    parser.add_argument("--level", help="CEFR level filter, e.g. A1")
    parser.add_argument("--module-number", type=int, help="Module number filter")
    parser.add_argument("--all", action="store_true",
                        help="Process every module under module_completed/fixed/.")
    parser.add_argument("--all-modules", action="store_true",
                        help="Process every module in the selected level "
                        "(requires --level).")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to disk (mutually exclusive with --dry-run).")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.apply and args.dry_run:
        print("ERROR: --apply and --dry-run are mutually exclusive.", file=sys.stderr)
        return 2
    dry_run = True if (args.dry_run or not args.apply) else False

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

    summaries = renumber_batch(
        selectors, dry_run=dry_run, source_dir=args.source_dir, level=level_filter,
    )

    if len(summaries) == 1 and "error" not in summaries[0]:
        s = summaries[0]
        print(f"Source: {s['source_path']}")
        print(f"Lessons: {s['lesson_count']}")
        print(f"Changed: {'yes' if s['changed'] else 'no'}\n")
        for l in s["lessons_overview"]:
            print(f"  #{l['position']:2}  id={l['id']:<3}  {l['type']:30}  {l['title']}")
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
