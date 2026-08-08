#!/usr/bin/env python3
"""Strip lesson audio references that belong to a different module.

Audit CNT-008 (cross-zone audit 2026-08-08). Five lesson clips are addressed
from two modules at once, and the two modules expect different answers:

* ``A2M22L6_ex1..4.mp3`` — owned by ``module_A2_22_holidays_traditions`` L8
  ("New Year" / "Many gifts" / "Last night"), also referenced by
  ``module_A2_7_healthy_lifestyle`` L8, whose questions are about exercise and
  sleep. Four of that lesson's six questions play audio about something else.
* ``A2M19L12_listen_1.mp3`` — owned by ``module_A2_19_music_art`` L18, also
  referenced once by ``module_A2_4_food_cooking`` L18.

Ownership is decided by the filename prefix: ``A2M22*`` belongs to A2 module 22.
The borrower's own clips do not exist, so there is nothing to redirect to —
regenerating them needs an external TTS run (manual, Post-Completion). Until
then the honest state is "no audio on this question", which is what this writes:
the borrowed reference is removed, the question keeps its text and options.

Deterministic and idempotent — a second run finds nothing to do.

Usage:
    python scripts/fix_borrowed_lesson_audio.py                # report
    python scripts/fix_borrowed_lesson_audio.py --apply        # JSON corpus
    python scripts/fix_borrowed_lesson_audio.py --apply --db   # + database
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "module_completed" / "fixed"

AUDIO_KEYS = ("audio", "audio_url", "audio_clip_url")

# `A2M22L6_ex1.mp3` / `A2M07L8_listen_1.mp3` → level A2, module 22 / 7.
_PREFIX_RE = re.compile(r"^(?P<level>[A-C][0-9])M(?P<module>\d+)", re.IGNORECASE)
# `module_A2_7_healthy_lifestyle.json` → level A2, module 7.
_FILENAME_RE = re.compile(r"^module_(?P<level>[A-C][0-9])_(?P<module>\d+)_")


def clip_owner(ref: str) -> tuple[str, int] | None:
    """(level, module_number) the filename claims, or None when it says nothing."""
    name = str(ref or "").replace("[sound:", "").replace("]", "").rsplit("/", 1)[-1]
    match = _PREFIX_RE.match(name)
    if not match:
        return None
    return match.group("level").upper(), int(match.group("module"))


def module_identity(filename: str) -> tuple[str, int] | None:
    match = _FILENAME_RE.match(filename)
    if not match:
        return None
    return match.group("level").upper(), int(match.group("module"))


def is_shareable(ref: str) -> bool:
    """Word-pronunciation clips are legitimately reused across modules."""
    name = str(ref or "").replace("[sound:", "").replace("]", "").rsplit("/", 1)[-1]
    return name.startswith("pronunciation_")


def collect_refs(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in AUDIO_KEYS:
                if isinstance(value, str):
                    out.append(value)
                elif isinstance(value, list):
                    out.extend(item for item in value if isinstance(item, str))
                continue
            collect_refs(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_refs(item, out)


def clip_name(ref: str) -> str:
    return str(ref or "").replace("[sound:", "").replace("]", "").rsplit("/", 1)[-1]


def find_borrowed(usage: dict[str, dict[tuple[str, int], list[str]]]) -> dict[str, tuple[str, int]]:
    """Map clip name → owning module, for clips claimed by more than one module.

    A clip is only "borrowed" when two *different* modules reference it. Among
    those modules, the owner is the one whose (level, number) the filename
    prefix names — that is how ``A2M22L6_ex1.mp3`` is pinned to A2 module 22
    rather than to the healthy-lifestyle module that also links it. Filenames
    that match none of the sharers are left alone and reported: the corpus
    numbers some clips on a legacy scheme, and guessing there would strip
    hundreds of perfectly good references.
    """
    owners: dict[str, tuple[str, int]] = {}
    ambiguous: list[str] = []

    for name, modules in usage.items():
        if len(modules) < 2:
            continue
        claimed = clip_owner(name)
        if claimed is not None and claimed in modules:
            owners[name] = claimed
        else:
            ambiguous.append(name)

    if ambiguous:
        print(f"  (skipped {len(ambiguous)} shared clip(s) with no identifiable owner)")
    return owners


def strip_named(node: Any, drop: set[str], removed: list[str]) -> Any:
    """Return `node` with every reference whose clip name is in `drop` removed."""
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in AUDIO_KEYS:
                if isinstance(value, str):
                    if clip_name(value) in drop:
                        removed.append(value)
                        continue
                    result[key] = value
                elif isinstance(value, list):
                    kept = []
                    for item in value:
                        if isinstance(item, str) and clip_name(item) in drop:
                            removed.append(item)
                            # Keep the slot so parallel arrays stay aligned.
                            kept.append("")
                        else:
                            kept.append(item)
                    result[key] = kept
                else:
                    result[key] = value
                continue
            result[key] = strip_named(value, drop, removed)
        return result
    if isinstance(node, list):
        return [strip_named(item, drop, removed) for item in node]
    return node


def build_usage(modules: dict[tuple[str, int], dict]) -> dict[str, set[tuple[str, int]]]:
    """clip name → set of modules referencing it (pronunciation clips excluded)."""
    usage: dict[str, set[tuple[str, int]]] = {}
    for identity, data in modules.items():
        module = data.get("module") or data
        refs: list[str] = []
        for lesson in module.get("lessons") or []:
            collect_refs(lesson.get("content") or {}, refs)
        for ref in refs:
            if is_shareable(ref):
                continue
            usage.setdefault(clip_name(ref), set()).add(identity)
    return usage


def fix_json_corpus(source_dir: Path, apply: bool) -> int:
    paths = {}
    modules = {}
    for path in sorted(source_dir.glob("module_*.json")):
        identity = module_identity(path.name)
        if identity is None:
            continue
        paths[identity] = path
        modules[identity] = json.loads(path.read_text(encoding="utf-8"))

    owners = find_borrowed(build_usage(modules))
    print(f"  cross-module lesson clips with a clear owner: {len(owners)}")

    total = 0
    for identity, data in modules.items():
        drop = {name for name, owner in owners.items() if owner != identity}
        if not drop:
            continue

        module = data.get("module") or data
        removed: list[str] = []
        for lesson in module.get("lessons") or []:
            lesson["content"] = strip_named(lesson.get("content") or {}, drop, removed)

        if removed:
            total += len(removed)
            print(f"  {paths[identity].name}: removed {sorted(set(removed))}")
            if apply:
                paths[identity].write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                )

    print(f"JSON corpus: {total} borrowed audio reference(s)")
    return total


def fix_database(apply: bool, source_dir: Path) -> int:
    """Apply the same removals to `lessons.content`.

    Ownership is derived from the JSON corpus, which is the authoring source of
    truth; the database is the import target.
    """
    from sqlalchemy.orm.attributes import flag_modified

    from app import create_app
    from app.curriculum.models import CEFRLevel, Lessons, Module
    from app.utils.db import db

    modules = {}
    for path in sorted(source_dir.glob("module_*.json")):
        identity = module_identity(path.name)
        if identity is not None:
            modules[identity] = json.loads(path.read_text(encoding="utf-8"))
    owners = find_borrowed(build_usage(modules))

    app = create_app()
    with app.app_context():
        rows = (
            db.session.query(Lessons, Module, CEFRLevel)
            .join(Module, Lessons.module_id == Module.id)
            .join(CEFRLevel, Module.level_id == CEFRLevel.id)
            .all()
        )
        total = 0
        for lesson, module, level in rows:
            identity = ((level.code or "").upper(), module.number or 0)
            drop = {name for name, owner in owners.items() if owner != identity}
            if not drop:
                continue
            removed: list[str] = []
            new_content = strip_named(lesson.content or {}, drop, removed)
            if not removed:
                continue
            total += len(removed)
            print(f"  lesson {lesson.id}: removed {sorted(set(removed))}")
            if apply:
                lesson.content = new_content
                flag_modified(lesson, "content")

        if apply:
            db.session.commit()
        print(f"database: {total} borrowed audio reference(s)")
        return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", action="store_true")
    parser.add_argument("--no-json", action="store_true")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    if not args.no_json:
        fix_json_corpus(source_dir, args.apply)
    if args.db:
        fix_database(args.apply, source_dir)
    if not args.apply:
        print("\ndry run — nothing written (pass --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
