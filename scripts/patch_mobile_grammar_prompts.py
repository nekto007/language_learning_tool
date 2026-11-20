#!/usr/bin/env python3
"""Apply or restore reviewed prompt constraints and one accepted-answer expansion.

Read-only by default; no Flask, credentials, network or database access. Every
source and every change is checked before writing. The manifest records absent
fields explicitly, so rollback removes added instructions exactly. Live database
rollout is a separate operation that must preserve exercise identities/progress.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "MOBILE_GRAMMAR_EXERCISE_PROMPTS_20261120.json"


# Load the shared pure validator without executing Flask's package initializer.
import importlib.util
import sys

_SPEC = importlib.util.spec_from_file_location(
    "_llt_prompt_manifest", ROOT / "app" / "grammar_lab" / "prompt_manifest.py"
)
_SHARED = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SHARED
_SPEC.loader.exec_module(_SHARED)
PatchConflict = _SHARED.PatchConflict
parse_json = _SHARED.parse_json
byte_digest = _SHARED.byte_digest
validate_manifest = _SHARED.validate_manifest


@dataclass(frozen=True)
class PlannedFile:
    path: Path
    before: bytes
    after: bytes

    def report(self):
        return {
            "file": self.path.name,
            "changed": self.before != self.after,
            "before_sha256": byte_digest(self.before),
            "after_sha256": byte_digest(self.after),
        }


def _exercise(document, source, change):
    if (
        not isinstance(document, dict)
        or document.get("level") != source["level"]
        or document.get("module_id") != source["module_order"]
        or document.get("grammar_topic_slug") != source["grammar_topic_slug"]
    ):
        raise PatchConflict(f"Module identity changed: {source['path']}")
    for key in ("level", "module_order", "grammar_topic_slug"):
        if change.get(key) != source.get(key):
            raise PatchConflict("Manifest module metadata conflict")
    sessions = [
        session
        for session in document.get("sessions", [])
        if isinstance(session, dict) and session.get("session_number") == change["session_number"]
    ]
    if len(sessions) != 1:
        raise PatchConflict("Session absent or ambiguous")
    rows = [
        row
        for row in sessions[0].get("exercises", [])
        if isinstance(row, dict) and row.get("order") == change["exercise_order"]
    ]
    if (
        len(rows) != 1
        or rows[0].get("exercise_type") != change["exercise_type"]
        or rows[0].get("difficulty") != change.get("difficulty")
    ):
        raise PatchConflict("Exercise absent, ambiguous, or metadata changed")
    return rows[0]


def build_plan(root, manifest, *, rollback=False):
    sources, changes = validate_manifest(manifest)
    root = Path(root).resolve()
    result = []
    for source in sources:
        path = root / source["path"]
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
            raise PatchConflict(f"Missing, outside-root, or symlinked source: {path}")
        before_bytes = path.read_bytes()
        current_hash = byte_digest(before_bytes)
        if current_hash == source["sha256_before"]:
            current = "before"
        elif current_hash == source["sha256_after"]:
            current = "after"
        else:
            raise PatchConflict(f"Entire source changed: {source['path']}")
        document = parse_json(before_bytes)
        desired = "before" if rollback else "after"
        for change in [item for item in changes if item["source"] == source["path"]]:
            row = _exercise(document, source, change)
            if row.get("content") != change[f"content_{current}"]:
                raise PatchConflict("Reviewed content changed")
            # Replacing content keeps original insertion order from the manifest;
            # rollback also restores a field that was absent rather than null.
            row["content"] = copy.deepcopy(change[f"content_{desired}"])
        if current == desired:
            after_bytes = before_bytes
        else:
            newline = "\n" if desired == "after" or source.get("before_final_newline", True) else ""
            after_bytes = (json.dumps(document, ensure_ascii=False, indent=2) + newline).encode()
            if byte_digest(after_bytes) != source[f"sha256_{desired}"]:
                raise PatchConflict("Reconstructed source does not match reviewed file hash")
        result.append(PlannedFile(path, before_bytes, after_bytes))
    return result


def _atomic_write(path, raw):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_plan(plan):
    """Apply a complete preflight; back up bytes and restore own writes on error."""
    changed = [item for item in plan if item.before != item.after]
    for item in plan:
        if item.path.is_symlink() or item.path.read_bytes() != item.before:
            raise PatchConflict("Source changed after preflight")
    if not changed:
        return None
    backup = Path(tempfile.mkdtemp(prefix="llt-grammar-prompts-"))
    for item in changed:
        (backup / item.path.name).write_bytes(item.before)
    written = []
    try:
        for item in changed:
            if item.path.is_symlink() or item.path.read_bytes() != item.before:
                raise PatchConflict("Source changed during apply")
            _atomic_write(item.path, item.after)
            written.append(item)
    except Exception:
        for item in reversed(written):
            if not item.path.is_symlink() and item.path.read_bytes() == item.after:
                _atomic_write(item.path, item.before)
        raise
    return str(backup)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true", help="Write the fully checked local source plan")
    parser.add_argument(
        "--rollback", action="store_true", help="Restore reviewed fields; still read-only without --apply"
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = parse_json(args.manifest.read_bytes())
        plan = build_plan(args.root, manifest, rollback=args.rollback)
        report = {
            "pack": manifest["pack"],
            "applied": args.apply,
            "rollback": args.rollback,
            "files": [item.report() for item in plan],
            "backup": apply_plan(plan) if args.apply else None,
        }
    except (OSError, PatchConflict, KeyError, TypeError) as error:
        parser.exit(1, f"Refused prompt patch: {error}\n")
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
