#!/usr/bin/env python3
"""Clear `CollectionWords.listening` where the referenced clip is not on disk.

Audit CNT-003 (cross-zone audit 2026-08-08): `collection_words.listening` is
populated for ~19 890 words, but only a few dozen `pronunciation_*.mp3` files
actually exist. `app/curriculum/routes/vocabulary_lessons.py` copies `listening`
into `audio_url`, and `curriculum/lessons/vocabulary.html` renders the speaker
button purely on "is `audio_url` non-empty" — so 1 498 of the 1 580 course words
show a control that plays nothing.

Generating the missing clips needs an external TTS run (manual, tracked in the
plan's Post-Completion section). Until then the honest state is "no audio
recorded", which this script writes: `listening = NULL` and `get_download = 0`
for every word whose file is absent. Re-running after a TTS batch is safe — the
script only touches rows whose file is still missing.

Idempotent. Dry-run by default.

Usage:
    python scripts/clear_missing_word_audio.py            # report only
    python scripts/clear_missing_word_audio.py --apply
    python scripts/clear_missing_word_audio.py --apply --limit 500
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO_DIR = ROOT / "app" / "static" / "audio"

_ANKI_RE = re.compile(r"^\[sound:(?P<name>.+)\]$")


def audio_filename(ref: str) -> str | None:
    """Reduce a stored `listening` value to a bare filename, or None."""
    ref = (ref or "").strip()
    if not ref:
        return None

    anki = _ANKI_RE.match(ref)
    if anki:
        ref = anki.group("name").strip()

    if ref.startswith(("http://", "https://")):
        return None  # external host — not ours to verify

    # `/static/audio/x.mp3`, `static/audio/x.mp3` and bare `x.mp3` all appear.
    return ref.rsplit("/", 1)[-1] or None


def file_exists(ref: str, audio_dir: Path) -> bool:
    """True when the clip is present (or when we cannot tell — fail open)."""
    name = audio_filename(ref)
    if name is None:
        return True
    return (audio_dir / name).is_file()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument(
        "--audio-dir", default=str(DEFAULT_AUDIO_DIR),
        help="directory holding the mp3 files",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap rows changed")
    args = parser.parse_args()

    audio_dir = Path(args.audio_dir)
    if not audio_dir.is_dir():
        print(f"audio dir not found: {audio_dir}")
        return 1

    from app import create_app
    from app.utils.db import db
    from app.words.models import CollectionWords

    app = create_app()
    with app.app_context():
        rows = (
            db.session.query(CollectionWords)
            .filter(CollectionWords.listening.isnot(None))
            .filter(CollectionWords.listening != "")
            .all()
        )

        missing = [w for w in rows if not file_exists(w.listening, audio_dir)]
        if args.limit is not None:
            missing = missing[: args.limit]

        print(f"words with a listening ref : {len(rows)}")
        print(f"refs whose file is missing : {len(missing)}")

        for word in missing[:10]:
            print(f"  - {word.english_word!r}: {word.listening!r}")
        if len(missing) > 10:
            print(f"  … and {len(missing) - 10} more")

        if not args.apply:
            print("\ndry run — nothing written (pass --apply)")
            return 0

        for word in missing:
            word.listening = None
            word.get_download = 0
        db.session.commit()
        print(f"\ncleared {len(missing)} broken audio references")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
