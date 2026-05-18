"""Audit inline audio references in listening_quiz lessons.

listening_quiz lessons embed per-exercise audio as Anki-style bracket notation:
    exercises[].audio = "[sound:A1M1L6_ex1.mp3]"

The quiz.html template resolves this to /static/audio/<filename> via JavaScript.
This script verifies that every referenced file exists somewhere under
app/static/audio/ (any subdirectory).

If files are missing it prints the list so they can be generated via
generate_audio.py. Unlike lesson-level audio_url audits (which show 0 for
listening_quiz because the lesson has no top-level audio_url), this script
works at the item level — matching the actual design intent.

Usage:
    python scripts/audit_listening_quiz_inline_audio.py [--output PATH]
    python scripts/audit_listening_quiz_inline_audio.py --no-db  # filesystem only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_BASE = PROJECT_ROOT / "app" / "static" / "audio"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "listening_quiz_inline_audio.md"

SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")


@dataclass
class ExerciseRef:
    lesson_id: int
    lesson_title: str
    exercise_idx: int
    filename: str
    exists: bool = False


@dataclass
class LessonAudit:
    lesson_id: int
    title: str
    refs: list[ExerciseRef] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.refs)

    @property
    def present(self) -> int:
        return sum(1 for r in self.refs if r.exists)

    @property
    def missing(self) -> int:
        return self.total - self.present

    @property
    def ok(self) -> bool:
        return self.missing == 0


def _build_audio_index(audio_base: Path) -> set[str]:
    """Return set of all filenames (basename only) under audio_base."""
    found: set[str] = set()
    for root, _dirs, files in os.walk(audio_base):
        for fn in files:
            found.add(fn)
    return found


def _extract_refs(exercises: list[dict[str, Any]], lesson_id: int, title: str) -> list[ExerciseRef]:
    refs = []
    for idx, ex in enumerate(exercises):
        audio_val = ex.get("audio", "")
        m = SOUND_RE.search(str(audio_val))
        if m:
            refs.append(ExerciseRef(
                lesson_id=lesson_id,
                lesson_title=title,
                exercise_idx=idx,
                filename=m.group(1),
            ))
    return refs


def audit_with_db() -> list[LessonAudit]:
    sys.path.insert(0, str(PROJECT_ROOT))
    from app import create_app
    from app.curriculum.models import Lessons

    app = create_app()
    results: list[LessonAudit] = []
    audio_index = _build_audio_index(AUDIO_BASE)

    with app.app_context():
        lessons = Lessons.query.filter_by(type="listening_quiz").order_by(Lessons.id).all()
        for lesson in lessons:
            content = lesson.content if isinstance(lesson.content, dict) else json.loads(lesson.content)
            exercises = content.get("exercises", content.get("questions", []))
            refs = _extract_refs(exercises, lesson.id, lesson.title)
            for ref in refs:
                ref.exists = ref.filename in audio_index
            results.append(LessonAudit(lesson_id=lesson.id, title=lesson.title, refs=refs))

    return results


def _render_report(results: list[LessonAudit], audio_index: set[str]) -> str:
    total_lessons = len(results)
    total_refs = sum(la.total for la in results)
    total_present = sum(la.present for la in results)
    total_missing = sum(la.missing for la in results)
    ok_lessons = sum(1 for la in results if la.ok)
    gap_lessons = total_lessons - ok_lessons

    lines: list[str] = [
        "# listening_quiz Inline Audio Audit",
        "",
        "## Design Note",
        "",
        "listening_quiz exercises store audio as Anki-style bracket notation:",
        "```",
        '    exercises[].audio = "[sound:A1M1L6_ex1.mp3]"',
        "```",
        "The quiz.html template resolves `[sound:NAME]` to `/static/audio/NAME` via",
        "JavaScript regex. This is intentional item-level audio, not lesson-level",
        "`audio_url`. Lesson-level audits (e.g. audit_immersion_data.py) correctly",
        "show 0 audio_url entries for listening_quiz — the design is per-exercise,",
        "not per-lesson.",
        "",
        "Files are expected under `app/static/audio/` (direct children) because the",
        "template constructs `/static/audio/{filename}` without any subdirectory.",
        "",
        "## Summary",
        "",
        f"- Total listening_quiz lessons audited: **{total_lessons}**",
        f"- Total exercise audio references: **{total_refs}**",
        f"- Files present on disk: **{total_present}** / {total_refs}",
        f"- Files missing: **{total_missing}**",
        f"- Lessons fully OK: **{ok_lessons}** / {total_lessons}",
        f"- Lessons with gaps: **{gap_lessons}**",
        "",
    ]

    if total_missing == 0:
        lines += [
            "## Result",
            "",
            "All referenced audio files are present on disk. No generation needed.",
            "",
        ]
    else:
        lines += [
            "## Missing Files",
            "",
            "The following files are referenced but not found under app/static/audio/:",
            "",
        ]
        for la in results:
            for ref in la.refs:
                if not ref.exists:
                    lines.append(
                        f"- `{ref.filename}` "
                        f"(lesson {ref.lesson_id}: {ref.lesson_title}, exercise {ref.exercise_idx})"
                    )
        lines += [
            "",
            "## Suggested Generation Command",
            "",
            "Because listening_quiz audio is item-level (per exercise sentence),",
            "generate_audio.py cannot produce these files from the lesson content alone.",
            "The correct approach is to author sentences for each exercise and generate",
            "them individually, or manually record/source MP3 clips.",
            "",
        ]

    lines += [
        "## Per-Lesson Detail",
        "",
        "| Lesson ID | Title | Refs | Present | Missing | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for la in results:
        status = "OK" if la.ok else f"MISSING {la.missing}"
        lines.append(
            f"| {la.lesson_id} | {la.title[:50]} | {la.total} | {la.present} | {la.missing} | {status} |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit listening_quiz inline audio references")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Report output path")
    parser.add_argument("--no-db", action="store_true", help="Skip DB query (no results, filesystem check only)")
    args = parser.parse_args()

    audio_index = _build_audio_index(AUDIO_BASE)

    if args.no_db:
        print("--no-db: skipping DB query, printing filesystem stats only")
        print(f"Audio files indexed under {AUDIO_BASE}: {len(audio_index)}")
        return

    print("Querying DB for listening_quiz lessons...")
    results = audit_with_db()

    total_missing = sum(la.missing for la in results)
    total_refs = sum(la.total for la in results)
    print(f"Lessons: {len(results)}, refs: {total_refs}, missing: {total_missing}")

    report = _render_report(results, audio_index)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Report written to {out_path}")

    if total_missing > 0:
        print(f"WARNING: {total_missing} audio files are missing. See report for details.")
        sys.exit(1)
    else:
        print("All audio references resolved. No gaps found.")


if __name__ == "__main__":
    main()
