#!/usr/bin/env python3
"""Clear `CollectionWords.listening` where the referenced clip is not on disk.

Audit CNT-003 (cross-zone audit 2026-08-08) counted ~1 570 missing clips, but
that count came from a **dev checkout**, which carries a 33-file sample of
`pronunciation_*.mp3` rather than the media library. Measured against
production on 2026-08-23 the picture is different: every sampled word with
`get_download=1` (300/300) serves its mp3, and every clip that 404s belongs to
a row whose flag is already 0/NULL — so no speaker button is dead there. The
words still without audio are waiting on the owner's manual voice-over
pipeline, not on a bug.

That makes WHERE this script runs the whole ballgame. It compares the database
against a local directory, so pointing it at an incomplete `app/static/audio`
would clear `listening` for thousands of words whose clips exist on the media
host — destroying hand-bought recordings. Hence the coverage gate below:
`--apply` refuses when the directory holds less than COVERAGE_FLOOR of the
files the database references, because that reads as "wrong machine", not as
"missing audio". Pass `--force` only when the directory really is the media
library.

What it writes, for every word whose file is absent: `listening = NULL` and
`get_download = 0` — the honest state, "no audio recorded". Re-running after a
batch of new recordings is safe: only rows whose file is still missing change.

Idempotent. Dry-run by default.

Usage:
    python scripts/clear_missing_word_audio.py            # report only
    python scripts/clear_missing_word_audio.py --apply    # on the media host
    python scripts/clear_missing_word_audio.py --apply --limit 500
    python scripts/clear_missing_word_audio.py --apply --force   # gate override
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO_DIR = ROOT / "app" / "static" / "audio"

_ANKI_RE = re.compile(r"^\[sound:(?P<name>.+)\]$")

# Share of referenced clips that must be present before --apply is believed.
# A media host sits near 1.0; a dev checkout sits near 0.005 (33 of ~6 000).
# Anything in between is ambiguous enough to stop and ask.
COVERAGE_FLOOR = 0.9


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


def coverage_verdict(
    present: int,
    checkable: int,
    *,
    floor: float = COVERAGE_FLOOR,
) -> str | None:
    """Return a refusal message when the audio directory looks like the wrong one.

    ``present``/``checkable`` count local clips among the references this run
    can verify (external URLs are excluded — they are never checkable). A
    directory holding almost none of them means the script is looking at a dev
    checkout, and clearing rows from that comparison would strip audio the
    media host actually serves. Returns None when the directory is trustworthy.
    """
    if checkable <= 0:
        return None
    ratio = present / checkable
    if ratio >= floor:
        return None
    return (
        f"refusing --apply: only {present} of {checkable} referenced clips "
        f"({ratio:.1%}) are in this directory, below the {floor:.0%} floor.\n"
        "That reads as the wrong machine, not as missing audio — clearing rows "
        "from here would drop `listening` for words whose clips live on the "
        "media host.\nRun this on the media host, or pass --force if this "
        "directory really is the full library."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument(
        "--audio-dir", default=str(DEFAULT_AUDIO_DIR),
        help="directory holding the mp3 files",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap rows changed")
    parser.add_argument(
        "--force", action="store_true",
        help="apply even when the audio dir holds few of the referenced clips",
    )
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

        checkable = sum(1 for w in rows if audio_filename(w.listening) is not None)
        present = checkable - sum(
            1 for w in rows
            if audio_filename(w.listening) is not None
            and not file_exists(w.listening, audio_dir)
        )
        verdict = coverage_verdict(present, checkable)
        if verdict and not args.force:
            print(f"\n{verdict}")
            return 2
        if verdict:
            print(f"\n{verdict}\n--force given — applying anyway")

        for word in missing:
            word.listening = None
            word.get_download = 0
        db.session.commit()
        print(f"\ncleared {len(missing)} broken audio references")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
