#!/usr/bin/env python3
"""Generate per-item audio clips for audio_fill_blank lessons.

For each item in an audio_fill_blank lesson, replaces '___' with the correct
answer to form a complete sentence, generates an MP3 clip, and (with --apply)
updates the lesson content in the DB so each item carries an audio_clip_url.

Examples:
  python scripts/generate_audio_fill_blank.py --dry-run
  python scripts/generate_audio_fill_blank.py --apply
  python scripts/generate_audio_fill_blank.py --apply --voice en-GB-SoniaNeural
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUDIO_DIR = ROOT / "app" / "static" / "audio" / "immersion" / "audio_fill_blank"
STATIC_PREFIX = "/static/audio/immersion/audio_fill_blank"
DEFAULT_VOICE = "en-US-AriaNeural"


def _make_base_slug(level_code: str, mod_num: int) -> str:
    return f"afb_{level_code}_{str(mod_num).zfill(2)}"


def _build_full_sentence(text_with_gap: str, answer: str) -> str:
    """Replace the first '___' in text_with_gap with the correct answer."""
    return text_with_gap.replace("___", answer, 1).strip()


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def _generate_edge_tts(text: str, output_path: Path, voice: str, rate: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(output_path))


async def run(*, dry_run: bool, apply: bool, voice: str, rate: str, force: bool) -> dict:
    from app import create_app
    from app.curriculum.models import Lessons
    from app.utils.db import db

    app = create_app()

    created = skipped = failed = updated_lessons = 0
    report_rows: list[str] = []

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        lessons = db.session.query(Lessons).filter(Lessons.type == "audio_fill_blank").all()
        total_lessons = len(lessons)

        for lesson in lessons:
            content = lesson.content if isinstance(lesson.content, dict) else {}
            items = content.get("items", [])
            if not items:
                continue

            mod = lesson.module
            level_code = (mod.level.code if mod and mod.level else "XX")
            mod_num = mod.number if mod else 0
            base_slug = _make_base_slug(level_code, mod_num)

            new_items = copy.deepcopy(items)
            lesson_modified = False

            for idx, item in enumerate(new_items):
                text_with_gap = item.get("text_with_gap") or ""
                answer = item.get("answer") or ""
                if not text_with_gap or not answer:
                    report_rows.append(f"SKIP lesson={lesson.id} item={idx}: missing text_with_gap or answer")
                    skipped += 1
                    continue

                filename = f"{base_slug}_item{idx}.mp3"
                output_path = AUDIO_DIR / filename
                clip_url = f"{STATIC_PREFIX}/{filename}"

                already_set = item.get("audio_clip_url") == clip_url
                exists = output_path.exists()

                if already_set and exists and not force:
                    report_rows.append(f"skip (exists): {filename}")
                    skipped += 1
                    continue

                full_sentence = _build_full_sentence(text_with_gap, answer)
                full_sentence = _clean_text(full_sentence)

                if dry_run:
                    report_rows.append(f"dry-run: {filename} <- {full_sentence!r}")
                    skipped += 1
                    continue

                try:
                    await _generate_edge_tts(full_sentence, output_path, voice=voice, rate=rate)
                    created += 1
                    report_rows.append(f"created: {filename} ({output_path.stat().st_size} bytes)")
                except Exception as exc:
                    failed += 1
                    report_rows.append(f"FAILED: {filename}: {exc}")
                    continue

                item["audio_clip_url"] = clip_url
                new_items[idx] = item
                lesson_modified = True

            if lesson_modified and apply:
                new_content = {**content, "items": new_items}
                lesson.content = new_content
                db.session.add(lesson)
                updated_lessons += 1

        if apply:
            db.session.commit()

    return {
        "total_lessons": total_lessons,
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "updated_lessons": updated_lessons,
        "rows": report_rows,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="Preview without generating or writing (default: False)")
    p.add_argument("--apply", action="store_true", default=False,
                   help="Generate audio and update DB")
    p.add_argument("--voice", default=DEFAULT_VOICE)
    p.add_argument("--rate", default="+0%", help="edge-tts rate, e.g. '-10%%'")
    p.add_argument("--force", action="store_true", default=False,
                   help="Regenerate even if file already exists")
    return p.parse_args()


async def async_main() -> int:
    args = parse_args()
    if not args.dry_run and not args.apply:
        print("No action selected. Use --dry-run or --apply.")
        print("Defaulting to --dry-run.")
        args.dry_run = True

    result = await run(
        dry_run=args.dry_run,
        apply=args.apply,
        voice=args.voice,
        rate=args.rate,
        force=args.force,
    )

    for row in result["rows"]:
        print(row)

    print()
    print(f"summary: lessons={result['total_lessons']}, "
          f"created={result['created']}, "
          f"skipped={result['skipped']}, "
          f"failed={result['failed']}, "
          f"db_updated={result['updated_lessons']}")
    return 1 if result["failed"] else 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
