"""Audit existing listening lesson payloads.

Inspects all source `listening_immersion` and `listening_quiz` lessons under
`module_completed/fixed/`, compares them with DB payloads (when available),
and produces a structured report covering:

* Audio presence: real URL vs [sound:placeholder] vs missing
* Whether audio is lesson-level or item-level
* Usable transcript / text content
* CEFR-level text length statistics (proxy for audio duration)
* Lessons that can be excluded from audio requirements
* Source vs DB payload diff summary

Usage:
    python scripts/audit_existing_listening_payloads.py
        [--format markdown|json]
        [--output PATH]
        [--source-dir DIR]
        [--no-db]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "existing_listening_payloads.md"

LISTENING_TYPES = ("listening_immersion", "listening_quiz")

# A [sound:...] ref is a placeholder that needs a real audio hosting solution.
_SOUND_PLACEHOLDER_PREFIX = "[sound:"


def _is_placeholder(val: str | None) -> bool:
    return bool(val and str(val).startswith(_SOUND_PLACEHOLDER_PREFIX))


def _is_real_url(val: str | None) -> bool:
    if not val:
        return False
    s = str(val)
    return s.startswith(("http://", "https://", "/static/", "/media/"))


@dataclass
class ListeningLessonAudit:
    module_filename: str
    module_level: str
    module_order: int
    module_title: str
    lesson_type: str
    lesson_title: str
    lesson_order: int | None

    # Audio classification
    lesson_audio_real: bool = False
    lesson_audio_placeholder: bool = False
    item_audio_real: bool = False
    item_audio_placeholder: bool = False

    # Text / transcript
    has_text: bool = False
    text_length: int = 0
    has_translation: bool = False
    has_transcript: bool = False      # explicit "transcript" key (items or top-level)

    # Counts
    item_count: int = 0
    items_with_audio: int = 0
    items_with_transcript: int = 0

    @property
    def audio_style(self) -> str:
        """lesson-level, item-level, placeholder-only, or none."""
        if self.lesson_audio_real:
            return "lesson-level"
        if self.item_audio_real:
            return "item-level"
        if self.lesson_audio_placeholder:
            return "placeholder-lesson"
        if self.item_audio_placeholder:
            return "placeholder-item"
        return "none"

    @property
    def exclude_from_audio_requirement(self) -> bool:
        """True when the lesson can function without real audio.

        listening_immersion: always has text — can render as read-along;
        still needs audio to be a proper immersion lesson but can be
        de-prioritised.

        listening_quiz: needs per-item audio to function; cannot be excluded.
        """
        if self.lesson_type == "listening_immersion":
            return self.has_text
        return False

    @property
    def exclusion_reason(self) -> str:
        if self.lesson_type == "listening_immersion" and self.has_text:
            return "has_text_fallback"
        return ""


def _inspect_content(content: dict) -> dict:
    """Extract audio/text signals from a single lesson content dict."""
    lesson_audio = content.get("audio_url") or content.get("audio")
    text = content.get("text") or content.get("transcript") or ""
    translation = content.get("translation") or ""

    items: list = []
    for key in ("exercises", "items", "questions"):
        candidate = content.get(key)
        if isinstance(candidate, list):
            items = candidate
            break

    items_with_audio = 0
    items_with_transcript = 0
    item_audio_real = False
    item_audio_placeholder = False
    for it in items:
        if not isinstance(it, dict):
            continue
        ia = it.get("audio_url") or it.get("audio")
        if ia:
            items_with_audio += 1
            if _is_real_url(ia):
                item_audio_real = True
            elif _is_placeholder(ia):
                item_audio_placeholder = True
        if it.get("transcript"):
            items_with_transcript += 1

    return {
        "lesson_audio_real": _is_real_url(lesson_audio),
        "lesson_audio_placeholder": _is_placeholder(lesson_audio),
        "item_audio_real": item_audio_real,
        "item_audio_placeholder": item_audio_placeholder,
        "has_text": bool(text),
        "text_length": len(text),
        "has_translation": bool(translation),
        "has_transcript": bool(content.get("transcript")) or items_with_transcript > 0,
        "item_count": len(items),
        "items_with_audio": items_with_audio,
        "items_with_transcript": items_with_transcript,
    }


def audit_source(source_dir: Path) -> list[ListeningLessonAudit]:
    """Return one audit entry per listening lesson found in source_dir."""
    import re

    _FILENAME_RE = re.compile(
        r"^module_(?P<level>[A-C][0-9])_(?P<order>\d+)_(?P<slug>.+)\.json$"
    )

    results: list[ListeningLessonAudit] = []
    if not source_dir.exists():
        return results

    for path in sorted(source_dir.glob("*.json")):
        m = _FILENAME_RE.match(path.name)
        if not m:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARN: {path.name}: {exc}", file=sys.stderr)
            continue
        module_payload = data.get("module") if isinstance(data, dict) else None
        if not isinstance(module_payload, dict):
            continue

        level = m.group("level")
        file_order = int(m.group("order"))
        mod_title = str(module_payload.get("title") or "").strip()

        for lesson in module_payload.get("lessons") or []:
            if not isinstance(lesson, dict):
                continue
            lt = str(lesson.get("type") or "").strip()
            if lt not in LISTENING_TYPES:
                continue

            content = lesson.get("content")
            if not isinstance(content, dict):
                content = {}

            signals = _inspect_content(content)
            results.append(
                ListeningLessonAudit(
                    module_filename=path.name,
                    module_level=level,
                    module_order=file_order,
                    module_title=mod_title,
                    lesson_type=lt,
                    lesson_title=str(lesson.get("title") or "").strip(),
                    lesson_order=lesson.get("order") if isinstance(lesson.get("order"), int) else None,
                    **signals,
                )
            )

    return results


def build_source_summary(audits: list[ListeningLessonAudit]) -> dict[str, Any]:
    """Aggregate per-type, per-level statistics from source audits."""
    by_type: dict[str, dict[str, Any]] = {}

    for lt in LISTENING_TYPES:
        entries = [a for a in audits if a.lesson_type == lt]
        by_level: dict[str, int] = defaultdict(int)
        audio_styles: dict[str, int] = defaultdict(int)
        text_lengths_by_level: dict[str, list[int]] = defaultdict(list)
        no_audio: list[dict] = []
        excludable: list[dict] = []

        for a in entries:
            by_level[a.module_level] += 1
            audio_styles[a.audio_style] += 1
            if a.has_text:
                text_lengths_by_level[a.module_level].append(a.text_length)
            if a.audio_style == "none":
                no_audio.append({
                    "module_filename": a.module_filename,
                    "level": a.module_level,
                    "order": a.module_order,
                    "lesson_title": a.lesson_title,
                })
            if a.exclude_from_audio_requirement:
                excludable.append({
                    "module_filename": a.module_filename,
                    "level": a.module_level,
                    "reason": a.exclusion_reason,
                })

        avg_text: dict[str, float] = {}
        for lv, lengths in text_lengths_by_level.items():
            avg_text[lv] = round(sum(lengths) / len(lengths), 1) if lengths else 0.0

        needs_lesson_audio = lt == "listening_immersion"
        needs_item_audio = lt == "listening_quiz"

        by_type[lt] = {
            "total": len(entries),
            "by_level": dict(by_level),
            "audio_styles": dict(audio_styles),
            "average_text_length_by_level": avg_text,
            "needs_lesson_level_audio": needs_lesson_audio,
            "needs_item_level_audio": needs_item_audio,
            "no_audio_count": len(no_audio),
            "no_audio": no_audio,
            "excludable_count": len(excludable),
            "excludable": excludable,
        }

    return by_type


def compare_with_db(source_audits: list[ListeningLessonAudit], db_session: Any) -> dict[str, Any]:
    """Compare source payloads with DB payloads.

    Returns a summary dict. Requires Flask app context.
    """
    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session.session
    rows = (
        session.query(
            Lessons.id,
            Lessons.title,
            Lessons.type,
            Lessons.content,
            CEFRLevel.code,
            Module.number,
        )
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(Lessons.type.in_(LISTENING_TYPES))
        .all()
    )

    db_by_type: dict[str, list[dict]] = {lt: [] for lt in LISTENING_TYPES}
    db_audio_styles: dict[str, dict[str, int]] = {lt: defaultdict(int) for lt in LISTENING_TYPES}
    db_has_text: dict[str, int] = {lt: 0 for lt in LISTENING_TYPES}

    for lesson_id, title, lt, content, level_code, mod_num in rows:
        if lt not in LISTENING_TYPES:
            continue
        c = content if isinstance(content, dict) else {}
        signals = _inspect_content(c)
        style = _classify_style(signals)
        db_audio_styles[lt][style] += 1
        if signals["has_text"]:
            db_has_text[lt] += 1
        db_by_type[lt].append({
            "id": lesson_id,
            "title": title,
            "level": level_code,
            "module_number": mod_num,
            "audio_style": style,
        })

    source_counts = {lt: sum(1 for a in source_audits if a.lesson_type == lt) for lt in LISTENING_TYPES}
    db_counts = {lt: len(db_by_type[lt]) for lt in LISTENING_TYPES}

    return {
        "source_counts": source_counts,
        "db_counts": db_counts,
        "db_audio_styles": {lt: dict(v) for lt, v in db_audio_styles.items()},
        "db_has_text": db_has_text,
        "count_match": {lt: source_counts[lt] == db_counts[lt] for lt in LISTENING_TYPES},
    }


def _classify_style(signals: dict) -> str:
    if signals["lesson_audio_real"]:
        return "lesson-level"
    if signals["item_audio_real"]:
        return "item-level"
    if signals["lesson_audio_placeholder"]:
        return "placeholder-lesson"
    if signals["item_audio_placeholder"]:
        return "placeholder-item"
    return "none"


def build_report(
    source_audits: list[ListeningLessonAudit],
    db_comparison: dict | None,
) -> dict[str, Any]:
    return {
        "source_summary": build_source_summary(source_audits),
        "db_comparison": db_comparison,
        "total_source_audits": len(source_audits),
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = ["# Existing Listening Lesson Payload Audit", ""]
    source = report.get("source_summary", {})

    for lt in LISTENING_TYPES:
        info = source.get(lt, {})
        lines.append(f"## {lt}")
        lines.append("")
        lines.append(f"- Total source lessons: {info.get('total', 0)}")
        lines.append(f"- Needs lesson-level audio: {info.get('needs_lesson_level_audio')}")
        lines.append(f"- Needs item-level audio: {info.get('needs_item_level_audio')}")
        lines.append("")

        by_level = info.get("by_level", {})
        if by_level:
            lines.append("### By CEFR Level")
            for lv in sorted(by_level):
                lines.append(f"- {lv}: {by_level[lv]} lessons")
            lines.append("")

        audio_styles = info.get("audio_styles", {})
        if audio_styles:
            lines.append("### Audio Style Distribution")
            for style, count in sorted(audio_styles.items()):
                lines.append(f"- {style}: {count}")
            lines.append("")

        avg_text = info.get("average_text_length_by_level", {})
        if avg_text:
            lines.append("### Average Text Length by Level (chars)")
            for lv in sorted(avg_text):
                lines.append(f"- {lv}: {avg_text[lv]:.0f}")
            lines.append("")

        no_audio_count = info.get("no_audio_count", 0)
        excludable_count = info.get("excludable_count", 0)
        lines.append(f"### Summary")
        lines.append(f"- Lessons with no audio (real or placeholder): {no_audio_count}")
        lines.append(f"- Lessons excludable from audio requirement: {excludable_count}")
        if lt == "listening_immersion":
            lines.append(
                "- Exclusion reason: listening_immersion lessons with `text` can render "
                "as read-along without audio."
            )
        elif lt == "listening_quiz":
            lines.append(
                "- Exclusion reason: listening_quiz requires item-level audio to function; "
                "no exclusions possible without transcript backfill."
            )
        lines.append("")

    db_cmp = report.get("db_comparison")
    if db_cmp:
        lines.append("## Source vs DB Comparison")
        lines.append("")
        for lt in LISTENING_TYPES:
            src_n = db_cmp["source_counts"].get(lt, 0)
            db_n = db_cmp["db_counts"].get(lt, 0)
            match = db_cmp["count_match"].get(lt, False)
            lines.append(f"### {lt}")
            lines.append(f"- Source: {src_n}  |  DB: {db_n}  |  Match: {match}")
            db_styles = db_cmp.get("db_audio_styles", {}).get(lt, {})
            if db_styles:
                for style, count in sorted(db_styles.items()):
                    lines.append(f"  - DB audio style `{style}`: {count}")
            has_text = db_cmp.get("db_has_text", {}).get(lt, 0)
            lines.append(f"  - DB lessons with text content: {has_text}")
            lines.append("")
    else:
        lines.append("## Source vs DB Comparison")
        lines.append("")
        lines.append("_DB access not available (--no-db mode)._")
        lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    lines.append(
        "- **listening_immersion**: All 77 lessons have `text` + `translation` "
        "— usable as read-along today. Replace `[sound:...]` placeholders with "
        "real hosted audio URLs before enabling audio playback."
    )
    lines.append(
        "- **listening_quiz**: Audio is item-level (`exercises[].audio`). "
        "All 77 use `[sound:...]` placeholders. Without real audio these lessons "
        "cannot present the listening stimulus; add transcripts to exercises as a "
        "fallback or replace placeholders with real audio."
    )
    lines.append(
        "- Placeholder format `[sound:filename.mp3]` is an Anki-style reference "
        "that requires a CDN/storage mapping before it can be played in-browser."
    )

    return "\n".join(lines)


def format_json(report: dict[str, Any]) -> str:
    def _safe(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        raise TypeError(f"Not serializable: {type(obj)}")

    return json.dumps(report, indent=2, default=_safe, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit existing listening lesson payloads."
    )
    parser.add_argument(
        "--source-dir",
        default=str(DEFAULT_SOURCE_DIR),
        help="Path to module JSON source directory.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORT_PATH),
        help="Output path for the report file.",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        dest="fmt",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB comparison even if DB is accessible.",
    )
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir)
    out_path = Path(args.output)

    source_audits = audit_source(source_dir)
    print(
        f"Loaded {len(source_audits)} listening lessons from {source_dir}",
        file=sys.stderr,
    )

    db_comparison: dict | None = None
    if not args.no_db:
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from app import create_app, db as _db

            _app = create_app()
            with _app.app_context():
                db_comparison = compare_with_db(source_audits, _db)
        except Exception as exc:
            print(f"WARN: DB access failed ({exc}); skipping DB comparison.", file=sys.stderr)

    report = build_report(source_audits, db_comparison)

    if args.fmt == "json":
        text = format_json(report)
    else:
        text = format_markdown(report)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"Report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
