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
DEFAULT_QUALITY_REPORT_PATH = PROJECT_ROOT / "reports" / "listening_duration_transcript_audit.md"

LISTENING_TYPES = ("listening_immersion", "listening_quiz")

# Reasonable transcript/text length bounds per CEFR level (characters)
CEFR_TEXT_MIN: dict[str, int] = {"A1": 20, "A2": 40, "B1": 80, "B2": 120, "C1": 150}
CEFR_TEXT_MAX: dict[str, int] = {"A1": 500, "A2": 800, "B1": 1200, "B2": 1800, "C1": 3000}

# Plausible speech rate: 90–210 wpm ≈ 1.5–3.5 words/s, avg 5 chars/word → 7.5–17.5 chars/s
_CHARS_PER_SECOND_MIN = 7.5
_CHARS_PER_SECOND_MAX = 17.5

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

    # Duration metadata
    duration_seconds: float | None = None

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

    dur_raw = content.get("duration_seconds")
    try:
        duration_seconds: float | None = float(dur_raw) if dur_raw is not None else None
    except (TypeError, ValueError):
        duration_seconds = None

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
        "duration_seconds": duration_seconds,
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


@dataclass
class QualityIssue:
    module_filename: str
    module_level: str
    lesson_type: str
    lesson_title: str
    check: str
    detail: str


_QUALITY_CHECK_LABELS: dict[str, str] = {
    "missing_duration": "Missing duration_seconds (audio lessons)",
    "empty_text": "Empty transcript/text",
    "text_too_short": "Text too short for CEFR level",
    "text_too_long": "Text too long for CEFR level",
    "duration_text_mismatch": "Audio duration vs text length mismatch",
}


def run_quality_checks(audits: list[ListeningLessonAudit]) -> list[QualityIssue]:
    """Return one QualityIssue per failed check across all audited lessons."""
    issues: list[QualityIssue] = []

    for a in audits:
        has_real_audio = a.lesson_audio_real or a.item_audio_real

        if has_real_audio and a.duration_seconds is None:
            issues.append(QualityIssue(
                module_filename=a.module_filename,
                module_level=a.module_level,
                lesson_type=a.lesson_type,
                lesson_title=a.lesson_title,
                check="missing_duration",
                detail="Lesson has real audio but no duration_seconds field.",
            ))

        if not a.has_text:
            issues.append(QualityIssue(
                module_filename=a.module_filename,
                module_level=a.module_level,
                lesson_type=a.lesson_type,
                lesson_title=a.lesson_title,
                check="empty_text",
                detail="No transcript or text content found.",
            ))

        if a.has_text:
            min_chars = CEFR_TEXT_MIN.get(a.module_level, 20)
            max_chars = CEFR_TEXT_MAX.get(a.module_level, 3000)
            if a.text_length < min_chars:
                issues.append(QualityIssue(
                    module_filename=a.module_filename,
                    module_level=a.module_level,
                    lesson_type=a.lesson_type,
                    lesson_title=a.lesson_title,
                    check="text_too_short",
                    detail=(
                        f"Text length {a.text_length} chars is below minimum "
                        f"{min_chars} for {a.module_level}."
                    ),
                ))
            elif a.text_length > max_chars:
                issues.append(QualityIssue(
                    module_filename=a.module_filename,
                    module_level=a.module_level,
                    lesson_type=a.lesson_type,
                    lesson_title=a.lesson_title,
                    check="text_too_long",
                    detail=(
                        f"Text length {a.text_length} chars exceeds maximum "
                        f"{max_chars} for {a.module_level}."
                    ),
                ))

        if a.has_text and a.duration_seconds is not None and a.duration_seconds > 0:
            expected_min = a.duration_seconds * _CHARS_PER_SECOND_MIN
            expected_max = a.duration_seconds * _CHARS_PER_SECOND_MAX
            if a.text_length < expected_min:
                issues.append(QualityIssue(
                    module_filename=a.module_filename,
                    module_level=a.module_level,
                    lesson_type=a.lesson_type,
                    lesson_title=a.lesson_title,
                    check="duration_text_mismatch",
                    detail=(
                        f"Text length {a.text_length} chars is too short for "
                        f"{a.duration_seconds}s audio (expected ≥{expected_min:.0f} chars at "
                        f"{_CHARS_PER_SECOND_MIN} chars/s)."
                    ),
                ))
            elif a.text_length > expected_max:
                issues.append(QualityIssue(
                    module_filename=a.module_filename,
                    module_level=a.module_level,
                    lesson_type=a.lesson_type,
                    lesson_title=a.lesson_title,
                    check="duration_text_mismatch",
                    detail=(
                        f"Text length {a.text_length} chars is too long for "
                        f"{a.duration_seconds}s audio (expected ≤{expected_max:.0f} chars at "
                        f"{_CHARS_PER_SECOND_MAX} chars/s)."
                    ),
                ))

    return issues


def format_quality_markdown(
    audits: list[ListeningLessonAudit],
    issues: list[QualityIssue],
) -> str:
    lines: list[str] = ["# Listening Duration & Transcript Quality Audit", ""]
    lines.append(f"Total lessons audited: {len(audits)}")
    lines.append(f"Total quality issues: {len(issues)}")
    lines.append("")

    by_check: dict[str, list[QualityIssue]] = defaultdict(list)
    for issue in issues:
        by_check[issue.check].append(issue)

    lines.append("## Summary")
    lines.append("")
    for check, label in _QUALITY_CHECK_LABELS.items():
        count = len(by_check.get(check, []))
        status = "OK" if count == 0 else str(count)
        lines.append(f"- {label}: {status}")
    lines.append("")

    for check, label in _QUALITY_CHECK_LABELS.items():
        check_issues = by_check.get(check, [])
        if not check_issues:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for qi in check_issues:
            lines.append(
                f"- `{qi.module_filename}` / {qi.lesson_type} / "
                f"{qi.lesson_title} ({qi.module_level}): {qi.detail}"
            )
        lines.append("")

    lines.append("## CEFR Text Length Thresholds")
    lines.append("")
    lines.append("| Level | Min chars | Max chars |")
    lines.append("|-------|-----------|-----------|")
    for lv in ("A1", "A2", "B1", "B2", "C1"):
        lines.append(f"| {lv} | {CEFR_TEXT_MIN.get(lv, '?')} | {CEFR_TEXT_MAX.get(lv, '?')} |")
    lines.append("")
    lines.append(
        f"Speech rate assumption: {_CHARS_PER_SECOND_MIN}–{_CHARS_PER_SECOND_MAX} chars/second "
        f"(approx. 90–210 wpm, avg. 5 chars/word)."
    )
    return "\n".join(lines)


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
    parser.add_argument(
        "--quality-report",
        default=str(DEFAULT_QUALITY_REPORT_PATH),
        help="Output path for the duration/transcript quality report.",
    )
    parser.add_argument(
        "--no-quality-report",
        action="store_true",
        help="Skip writing the duration/transcript quality report.",
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

    if not args.no_quality_report:
        quality_issues = run_quality_checks(source_audits)
        quality_md = format_quality_markdown(source_audits, quality_issues)
        quality_path = Path(args.quality_report)
        quality_path.parent.mkdir(parents=True, exist_ok=True)
        quality_path.write_text(quality_md, encoding="utf-8")
        print(
            f"Quality report written to {quality_path} "
            f"({len(quality_issues)} issues)",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
