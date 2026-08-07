#!/usr/bin/env python3
"""
Build reading lesson scaffolds for book courses without calling any LLM API.

The work is split into three steps so the text generation can be done by an
agent working in this repository instead of a paid API call:

  1. ``export``  writes pending lessons into batch files plus a prompt that
     describes exactly what to produce and where to save it.
  2. the agent reads ``<batch>.json`` and writes ``<batch>_result.json``.
  3. ``import``  validates those results and stores them in
     ``daily_lessons.annotations``.

Validation on import is strict: every annotated phrase must appear verbatim in
the lesson text, so invented quotes never reach the database.

Usage:
  python scripts/generate_reading_annotations.py status
  python scripts/generate_reading_annotations.py export --course-id=3
  python scripts/generate_reading_annotations.py export --course-id=3 --batch-size=8 --limit=40
  python scripts/generate_reading_annotations.py import --course-id=3
  python scripts/generate_reading_annotations.py import --file=work/.../batch_001_result.json
  python scripts/generate_reading_annotations.py import --course-id=3 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_OUT_ROOT = BASE_DIR / "work" / "reading_scaffolds"
DEFAULT_BATCH_SIZE = 6

READING_TYPES = (
    "reading", "reading_assignment", "reading_passage",
    "reading_part1", "reading_part2",
)

SCAFFOLD_KEYS = (
    "objectives", "before_reading", "annotations",
    "reflection", "self_check", "can_do",
)
ANNOTATION_TYPES = ("cultural", "lexical", "grammar")

OBJECTIVES_COUNT = 3
CAN_DO_COUNT = 3
BEFORE_READING_TASKS = 2
ANNOTATIONS_MIN, ANNOTATIONS_MAX = 4, 6
REFLECTION_MIN, REFLECTION_MAX = 1, 2
SELF_CHECK_COUNT = 3
MAX_GRAMMAR_ANNOTATIONS = 1


GENERATION_SPEC = """You are an expert English language teacher writing a structured reading
lesson scaffold for a book course. The student is a Russian speaker at level B1-B2.

For EVERY lesson in the batch file produce one scaffold object with ALL six sections:

1. "objectives" — exactly 3 short bullet points in Russian: what the student will do in this
   lesson (e.g. "познакомитесь с...", "поймёте...", "выучите...").

2. "before_reading" — an object with:
   - "goal": one sentence in Russian describing what to look for while reading
   - "tasks": exactly 2 focus questions (Russian or English)

3. "annotations" — 4 to 6 notes about phrases/words in THIS passage. Each has:
   - "phrase": an EXACT quote from the passage (see the hard rule below)
   - "type": one of "cultural", "lexical", "grammar"
   - "note": explanation in Russian with the English equivalent (1-2 sentences)
   - "quick_use": 1-2 example sentences showing how to use the phrase/word

   Selection principles:
   - roughly 1 cultural, 2-3 lexical, at most 1 grammar
   - each annotation must remove a comprehension obstacle, teach useful language,
     or explain cultural context
   - do NOT annotate every hard word, only those with real learning value
   - do not repeat the same phrase twice in one lesson

4. "reflection" — 1-2 open-ended thinking questions about the text (in English), each with:
   - "question", "hint" (a short nudge), "sample_answer" (1-2 sentences)

5. "self_check" — exactly 3 true/false statements about the text (in English), each with:
   - "statement", "answer" (JSON true/false), "explanation" (1 sentence)
   Mix the answers: at least one true AND at least one false.

6. "can_do" — exactly 3 short statements in Russian: what the student can do after the lesson.

HARD RULE — the import step rejects anything that breaks it:
every "phrase" must occur verbatim in that lesson's "slice_text". Whitespace and the shape of
quotes/apostrophes/dashes are normalised before comparison, but the wording, spelling and case
must match the passage exactly. Copy the phrase, never paraphrase or reconstruct it from memory.

Write the scaffolds only from the passage itself: no invented plot details, no unsupported
cultural claims, no answers that cannot be verified from the text."""


def _build_prompt(batch_path: Path, result_path: Path, batch: dict[str, Any]) -> str:
    """Render the per-batch instruction file that accompanies a batch export."""
    lessons = batch["lessons"]
    listing = "\n".join(
        f"  - lesson_id {item['lesson_id']} (day {item['day_number']}, "
        f"{item['char_count']} chars)"
        for item in lessons
    )
    schema = """{
  "batch_id": "%s",
  "scaffolds": [
    {
      "lesson_id": 123,
      "objectives": ["...", "...", "..."],
      "before_reading": {"goal": "...", "tasks": ["...", "..."]},
      "annotations": [
        {"phrase": "...", "type": "cultural|lexical|grammar", "note": "...", "quick_use": ["..."]}
      ],
      "reflection": [{"question": "...", "hint": "...", "sample_answer": "..."}],
      "self_check": [{"statement": "...", "answer": true, "explanation": "..."}],
      "can_do": ["...", "...", "..."]
    }
  ]
}""" % batch["batch_id"]

    return f"""# Reading scaffold batch {batch['batch_id']}

Course {batch['course_id']} — {batch['course_title']}
Lessons in this batch: {len(lessons)}

{listing}

Read `{batch_path}` and write `{result_path}`.
Produce one scaffold per lesson, in the same order, keyed by `lesson_id`.

Return JSON with this exact shape:

```json
{schema}
```

{GENERATION_SPEC}

When the file is written, import it:

    python scripts/generate_reading_annotations.py import --file={result_path}
"""


_WS_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-",
    " ": " ",
})


def normalize_for_match(text: str) -> str:
    """Normalise a passage or a quote so they can be compared.

    Collapses whitespace, unifies typographic punctuation, drops the space some
    source texts leave before a comma, and folds case. A quote that differs from
    the passage only by a sentence-initial capital is still a verbatim quote; the
    protection against invented quotes comes from the substring check itself.
    """
    unified = _WS_RE.sub(" ", text.translate(_QUOTE_MAP))
    return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", unified).strip().casefold()


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_str_list(
    value: Any, field: str, expected: int, errors: list[str],
) -> None:
    if not isinstance(value, list):
        errors.append(f"{field}: expected a list, got {type(value).__name__}")
        return
    if len(value) != expected:
        errors.append(f"{field}: expected {expected} items, got {len(value)}")
    for i, item in enumerate(value):
        if not _is_nonempty_str(item):
            errors.append(f"{field}[{i}]: expected a non-empty string")


def _validate_before_reading(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"before_reading: expected an object, got {type(value).__name__}")
        return
    if not _is_nonempty_str(value.get("goal")):
        errors.append("before_reading.goal: expected a non-empty string")
    _check_str_list(value.get("tasks"), "before_reading.tasks", BEFORE_READING_TASKS, errors)


def _validate_annotations(value: Any, slice_text: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"annotations: expected a list, got {type(value).__name__}")
        return
    if not ANNOTATIONS_MIN <= len(value) <= ANNOTATIONS_MAX:
        errors.append(
            f"annotations: expected {ANNOTATIONS_MIN}-{ANNOTATIONS_MAX} items, got {len(value)}"
        )

    haystack = normalize_for_match(slice_text)
    grammar_count = 0
    seen: set[str] = set()

    for i, ann in enumerate(value):
        if not isinstance(ann, dict):
            errors.append(f"annotations[{i}]: expected an object")
            continue

        phrase = ann.get("phrase")
        if not _is_nonempty_str(phrase):
            errors.append(f"annotations[{i}].phrase: expected a non-empty string")
        else:
            needle = normalize_for_match(phrase)
            if needle not in haystack:
                errors.append(
                    f"annotations[{i}].phrase: {phrase!r} does not occur verbatim in slice_text"
                )
            if needle in seen:
                errors.append(f"annotations[{i}].phrase: duplicate phrase {phrase!r}")
            seen.add(needle)

        ann_type = ann.get("type")
        if ann_type not in ANNOTATION_TYPES:
            errors.append(
                f"annotations[{i}].type: expected one of {ANNOTATION_TYPES}, got {ann_type!r}"
            )
        elif ann_type == "grammar":
            grammar_count += 1

        if not _is_nonempty_str(ann.get("note")):
            errors.append(f"annotations[{i}].note: expected a non-empty string")

        quick_use = ann.get("quick_use")
        if not isinstance(quick_use, list) or not 1 <= len(quick_use) <= 2:
            errors.append(f"annotations[{i}].quick_use: expected a list of 1-2 examples")
        else:
            for j, example in enumerate(quick_use):
                if not _is_nonempty_str(example):
                    errors.append(
                        f"annotations[{i}].quick_use[{j}]: expected a non-empty string"
                    )

    if grammar_count > MAX_GRAMMAR_ANNOTATIONS:
        errors.append(
            f"annotations: at most {MAX_GRAMMAR_ANNOTATIONS} grammar note allowed, "
            f"got {grammar_count}"
        )


def _validate_reflection(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"reflection: expected a list, got {type(value).__name__}")
        return
    if not REFLECTION_MIN <= len(value) <= REFLECTION_MAX:
        errors.append(
            f"reflection: expected {REFLECTION_MIN}-{REFLECTION_MAX} items, got {len(value)}"
        )
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"reflection[{i}]: expected an object")
            continue
        for field in ("question", "hint", "sample_answer"):
            if not _is_nonempty_str(item.get(field)):
                errors.append(f"reflection[{i}].{field}: expected a non-empty string")


def _validate_self_check(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"self_check: expected a list, got {type(value).__name__}")
        return
    if len(value) != SELF_CHECK_COUNT:
        errors.append(f"self_check: expected {SELF_CHECK_COUNT} items, got {len(value)}")

    answers: list[bool] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"self_check[{i}]: expected an object")
            continue
        for field in ("statement", "explanation"):
            if not _is_nonempty_str(item.get(field)):
                errors.append(f"self_check[{i}].{field}: expected a non-empty string")
        answer = item.get("answer")
        if not isinstance(answer, bool):
            errors.append(f"self_check[{i}].answer: expected JSON true/false, got {answer!r}")
        else:
            answers.append(answer)

    if answers and not (any(answers) and not all(answers)):
        errors.append("self_check: answers must mix at least one true and one false")


def validate_scaffold(scaffold: Any, slice_text: str) -> list[str]:
    """Return a list of problems; an empty list means the scaffold is storable."""
    if not isinstance(scaffold, dict):
        return [f"scaffold: expected an object, got {type(scaffold).__name__}"]

    errors: list[str] = []
    missing = [key for key in SCAFFOLD_KEYS if key not in scaffold]
    if missing:
        errors.append(f"scaffold: missing keys {missing}")

    _check_str_list(scaffold.get("objectives"), "objectives", OBJECTIVES_COUNT, errors)
    _validate_before_reading(scaffold.get("before_reading"), errors)
    _validate_annotations(scaffold.get("annotations"), slice_text, errors)
    _validate_reflection(scaffold.get("reflection"), errors)
    _validate_self_check(scaffold.get("self_check"), errors)
    _check_str_list(scaffold.get("can_do"), "can_do", CAN_DO_COUNT, errors)
    return errors


def _query_lessons(args: argparse.Namespace, pending_only: bool):
    """Build the lesson query shared by export and status."""
    from app.curriculum.daily_lessons import DailyLesson
    from app.curriculum.book_courses import BookCourseModule

    query = DailyLesson.query.filter(
        DailyLesson.lesson_type.in_(READING_TYPES),
        DailyLesson.slice_text.isnot(None),
    )

    if getattr(args, "lesson_id", None):
        query = query.filter(DailyLesson.id == args.lesson_id)
    elif getattr(args, "module_id", None):
        query = query.filter(DailyLesson.book_course_module_id == args.module_id)
    elif getattr(args, "course_id", None):
        module_ids = [
            m.id for m in BookCourseModule.query.filter_by(course_id=args.course_id).all()
        ]
        query = query.filter(DailyLesson.book_course_module_id.in_(module_ids))

    if pending_only:
        query = query.filter(DailyLesson.annotations.is_(None))

    return query.order_by(DailyLesson.id)


def _chunk(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def make_batch_id(course_id: int, first_lesson_id: int, last_lesson_id: int) -> str:
    """Name a batch after the lessons it holds.

    The id must depend on content rather than on the position in the pending
    list: imported lessons drop out of that list, so a positional number would
    point at different lessons on the next export and the "result already
    exists" check would then skip lessons that were never generated.
    """
    return f"course_{course_id}_{first_lesson_id:05d}-{last_lesson_id:05d}"


def cmd_status(args: argparse.Namespace) -> int:
    """Print scaffold coverage per book course."""
    from app.curriculum.daily_lessons import DailyLesson
    from app.curriculum.book_courses import BookCourse, BookCourseModule
    from app.utils.db import db

    rows = db.session.query(
        BookCourse.id,
        BookCourse.title,
        db.func.count(DailyLesson.id),
        db.func.count(DailyLesson.annotations),
    ).join(
        BookCourseModule, BookCourseModule.course_id == BookCourse.id
    ).join(
        DailyLesson, DailyLesson.book_course_module_id == BookCourseModule.id
    ).filter(
        DailyLesson.lesson_type.in_(READING_TYPES),
        DailyLesson.slice_text.isnot(None),
    ).group_by(BookCourse.id, BookCourse.title).order_by(BookCourse.id).all()

    print(f"{'id':>4}  {'reading':>7}  {'done':>6}  {'pending':>7}  title")
    total_reading = total_done = 0
    for course_id, title, reading, done in rows:
        total_reading += reading
        total_done += done
        print(f"{course_id:>4}  {reading:>7}  {done:>6}  {reading - done:>7}  {title[:48]}")
    print(f"{'all':>4}  {total_reading:>7}  {total_done:>6}  {total_reading - total_done:>7}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write pending lessons into batch files plus their prompts."""
    from app.curriculum.book_courses import BookCourse

    lessons = _query_lessons(args, pending_only=not args.overwrite).all()
    if args.limit is not None:
        lessons = lessons[:args.limit]

    if not lessons:
        print("Nothing to export.")
        return 0

    course_id = args.course_id or lessons[0].module.course_id
    course = BookCourse.query.get(course_id)
    course_title = course.title if course else f"course {course_id}"

    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_ROOT / f"course_{course_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Exporting {len(lessons)} lessons from course {course_id} into {out_dir}")

    written = skipped = 0
    for chunk in _chunk(lessons, args.batch_size):
        batch_id = make_batch_id(course_id, chunk[0].id, chunk[-1].id)
        batch_path = out_dir / f"{batch_id}.json"
        result_path = out_dir / f"{batch_id}_result.json"

        if result_path.exists() and not args.force:
            skipped += 1
            continue

        batch = {
            "batch_id": batch_id,
            "course_id": course_id,
            "course_title": course_title,
            "lessons": [
                {
                    "lesson_id": lesson.id,
                    "day_number": lesson.day_number,
                    "module_id": lesson.book_course_module_id,
                    "lesson_type": lesson.lesson_type,
                    "char_count": len(lesson.slice_text or ""),
                    "slice_text": lesson.slice_text,
                }
                for lesson in chunk
            ],
        }

        batch_path.write_text(
            json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        (out_dir / f"{batch_id}_prompt.md").write_text(
            _build_prompt(batch_path, result_path, batch), encoding="utf-8",
        )
        written += 1
        print(f"  {batch_path.name}: {len(chunk)} lessons")

    print(f"\nWrote {written} batch file(s), skipped {skipped} already-answered batch(es).")
    if written:
        print("Next: generate each *_result.json, then run `import --course-id=%s`." % course_id)
    return 0


def _load_result_files(args: argparse.Namespace) -> list[Path]:
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Error: {path} does not exist")
            return []
        return [path]

    if args.out_dir:
        directory = Path(args.out_dir)
    elif args.course_id:
        directory = DEFAULT_OUT_ROOT / f"course_{args.course_id}"
    else:
        print("Error: --file, --course-id or --out-dir is required")
        return []

    if not directory.exists():
        print(f"Error: {directory} does not exist")
        return []
    return sorted(directory.glob("*_result.json"))


def cmd_import(args: argparse.Namespace) -> int:
    """Validate generated result files and store them in the database."""
    from app.curriculum.daily_lessons import DailyLesson
    from app.utils.db import db

    paths = _load_result_files(args)
    if not paths:
        print("No result files to import.")
        return 1

    saved = skipped = failed = 0

    for path in paths:
        print(f"\n=== {path.name} ===")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"  ERROR: cannot read file: {error}")
            failed += 1
            continue

        scaffolds = payload.get("scaffolds") if isinstance(payload, dict) else None
        if not isinstance(scaffolds, list):
            print("  ERROR: expected an object with a 'scaffolds' list")
            failed += 1
            continue

        for entry in scaffolds:
            if not isinstance(entry, dict):
                print(f"  ERROR: scaffold entry is not an object: {entry!r:.60}")
                failed += 1
                continue

            lesson_id = entry.get("lesson_id")
            lesson = DailyLesson.query.get(lesson_id) if lesson_id else None
            if lesson is None:
                print(f"  ERROR: lesson {lesson_id!r} not found")
                failed += 1
                continue
            if lesson.lesson_type not in READING_TYPES:
                print(f"  ERROR: lesson {lesson_id} is '{lesson.lesson_type}', not a reading lesson")
                failed += 1
                continue
            if lesson.annotations is not None and not args.overwrite:
                print(f"  SKIP: lesson {lesson_id} already has a scaffold (use --overwrite)")
                skipped += 1
                continue

            scaffold = {key: entry[key] for key in SCAFFOLD_KEYS if key in entry}
            errors = validate_scaffold(scaffold, lesson.slice_text or "")
            if errors:
                print(f"  INVALID lesson {lesson_id}:")
                for message in errors:
                    print(f"    - {message}")
                failed += 1
                continue

            if not args.dry_run:
                lesson.annotations = scaffold
            saved += 1
            print(
                f"  OK lesson {lesson_id}: "
                f"{len(scaffold['annotations'])} annotations, "
                f"{len(scaffold['reflection'])} reflection"
            )

    if args.dry_run:
        db.session.rollback()
        print(f"\nDry run: {saved} valid, {skipped} skipped, {failed} invalid. Nothing written.")
    else:
        db.session.commit()
        print(f"\nDone: {saved} saved, {skipped} skipped, {failed} invalid.")

    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export reading lessons for scaffold generation and import the results",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_selectors(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--course-id", type=int, help="Book course ID")
        sub.add_argument("--module-id", type=int, help="Specific module ID")
        sub.add_argument("--lesson-id", type=int, help="Specific daily lesson ID")

    status_parser = subparsers.add_parser("status", help="Show scaffold coverage per course")
    status_parser.set_defaults(func=cmd_status)

    export_parser = subparsers.add_parser("export", help="Write batch files for generation")
    add_selectors(export_parser)
    export_parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Lessons per batch file (default: {DEFAULT_BATCH_SIZE})",
    )
    export_parser.add_argument("--limit", type=int, help="Maximum lessons to export")
    export_parser.add_argument("--out-dir", help="Destination directory for batch files")
    export_parser.add_argument(
        "--overwrite", action="store_true",
        help="Include lessons that already have a scaffold",
    )
    export_parser.add_argument(
        "--force", action="store_true",
        help="Rewrite batches that already have a *_result.json next to them",
    )
    export_parser.set_defaults(func=cmd_export)

    import_parser = subparsers.add_parser("import", help="Validate and store generated results")
    import_parser.add_argument("--course-id", type=int, help="Import the default directory of this course")
    import_parser.add_argument("--file", help="Import a single *_result.json file")
    import_parser.add_argument("--out-dir", help="Directory holding *_result.json files")
    import_parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing scaffolds",
    )
    import_parser.add_argument(
        "--dry-run", action="store_true", help="Validate only, write nothing",
    )
    import_parser.set_defaults(func=cmd_import)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "export" and not (args.course_id or args.module_id or args.lesson_id):
        build_parser().error("export requires --course-id, --module-id or --lesson-id")
    if args.command == "export" and args.batch_size <= 0:
        build_parser().error("--batch-size must be positive")
    if args.command == "export" and args.limit is not None and args.limit <= 0:
        build_parser().error("--limit must be positive")

    from app import create_app
    app = create_app()
    with app.app_context():
        return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
