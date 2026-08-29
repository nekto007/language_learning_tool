#!/usr/bin/env python3
"""Generate TTS audio for pilot module_completed/fixed/*.json files.

Phase 3 of the 2026-05-19 production rollout. Reads each pilot lesson with
``content.audio_url``, assembles the right English text from the lesson
payload (audio_fill_blank items get joined into full sentences), and writes
an MP3 via edge-tts.

Per-lesson-type voice + rate defaults:

    dictation           → en-US, female, -10% (slower for cloze training)
    audio_fill_blank    → en-US, female, +0%
    listening_immersion → en-US, dialogue multi-voice when speaker turns exist, +0%
    shadow_reading      → en-US, female, -5% (slightly slower for repeat-along)

Usage:
    PYTHONPATH=. python scripts/generate_pilot_audio.py             # preview (default)
    PYTHONPATH=. python scripts/generate_pilot_audio.py --apply
    PYTHONPATH=. python scripts/generate_pilot_audio.py --apply --force
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[1]

PILOT_DIR = ROOT / "module_completed" / "fixed"


def list_pilots() -> list[str]:
    """Pilot filenames, resolved on demand.

    ``module_completed/`` is gitignored, so scanning it at import time turned a
    missing corpus into a collection-time ``FileNotFoundError`` for every
    checkout without the content.
    """
    if not PILOT_DIR.is_dir():
        return []
    return sorted(
        p.name for p in PILOT_DIR.iterdir()
        if p.name.startswith("module_") and p.name.endswith(".json")
    )

TYPE_VOICE = {
    "dictation": ("en-US-AriaNeural", "-10%"),
    "audio_fill_blank": ("en-US-AriaNeural", "+0%"),
    "listening_immersion": ("en-US-GuyNeural", "+0%"),
    "shadow_reading": ("en-US-AriaNeural", "-5%"),
}

# Voice routing for reading lines (per-line `voice` field).
READING_LINE_VOICE = {
    "neutral": "en-US-AriaNeural",
    "female": "en-US-JennyNeural",
    "male": "en-US-GuyNeural",
}

# Dialogue voices for listening_immersion (two speakers, alternated).
DIALOGUE_VOICES = ("en-US-JennyNeural", "en-US-GuyNeural")

DEFAULT_TTS_RETRIES = 3
DEFAULT_TTS_RETRY_DELAY = 2.0


@dataclass
class Job:
    file: str
    lesson_number: int
    lesson_type: str
    audio_url: str
    output_path: Path
    text: str
    voice: str
    rate: str


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    # Strip dialogue dashes at line starts so TTS doesn't read them aloud.
    text = re.sub(r"(?m)^\s*-\s*", "", text)
    return text


def clean_preserve_lines(text: str) -> str:
    """Normalize dialogue text without destroying speaker-turn line breaks."""
    lines = []
    for line in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _english_ratio(s: str) -> float:
    """Fraction of alphabetic chars that are ASCII letters (0.0 = pure Cyrillic)."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isascii()) / len(letters)


def _pick_english_field(item: dict, keys: tuple[str, ...]) -> str:
    """Return the first field from `keys` whose text is predominantly English.

    listening_choice items split text across question/correct asymmetrically:
    sometimes the English prompt is in 'question' (and 'correct' is the
    Russian translation answer), sometimes the English answer is in 'correct'
    (and 'question' is a Russian instruction). We pick whichever side has
    ≥70% ASCII letters; falls back to the first non-empty value if no field
    qualifies (so non-English content like Cyrillic at least gets attempted).
    """
    candidates: list[str] = []
    for key in keys:
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            candidates.append(v)
    for v in candidates:
        if _english_ratio(v) >= 0.7:
            return clean(v)
    return clean(candidates[0]) if candidates else ""


def _filled_gap_question(item: dict) -> str:
    question = item.get("question")
    correct = item.get("correct")
    if not isinstance(question, str) or not isinstance(correct, str):
        return ""
    if "___" not in question:
        return ""
    if _english_ratio(question) < 0.5 or _english_ratio(correct) < 0.5:
        return ""
    return clean(re.sub(r"_{2,}", correct.strip(), question))


def assemble_text(lesson: dict) -> str:
    """Return the English text to pass to TTS for one lesson."""
    c = lesson.get("content") or {}
    ltype = lesson.get("type")

    # audio_fill_blank: join all items as full sentences.
    if ltype == "audio_fill_blank":
        items = c.get("items") or []
        parts: list[str] = []
        for it in items:
            stem = (it.get("text_with_gap") or "").strip()
            ans = (it.get("answer") or "").strip()
            if not stem:
                continue
            parts.append(stem.replace("___", ans).strip())
        return clean(" ".join(parts))

    for key in ("audio_text", "transcript", "text"):
        v = c.get(key)
        if isinstance(v, str) and v.strip():
            if ltype == "listening_immersion":
                return clean_preserve_lines(v)
            return clean(v)
    return ""


def resolve_path(audio_url: str) -> Path:
    if not audio_url.startswith("/static/"):
        raise ValueError(f"Unexpected audio_url shape: {audio_url}")
    return ROOT / "app" / audio_url.lstrip("/")


def _resolve_sound_ref(ref: str) -> Path | None:
    """Resolve a [sound:filename.mp3] inline reference to a filesystem path."""
    m = re.match(r"^\[sound:([^\]]+)\]$", (ref or "").strip())
    if not m:
        return None
    name = m.group(1).strip()
    return ROOT / "app" / "static" / "audio" / name


def _collect_inline_jobs(
    fname: str,
    lesson: dict,
    *,
    voice: str,
    rate: str,
) -> list[Job]:
    """Walk lesson content for inline [sound:...] refs in items/exercises.

    Picks TTS text from item['audio_text'] / 'text' / 'question'. Gap prompts
    such as "We ___ happy" are filled with `correct` before TTS so learners hear
    a natural sentence, not "underscore underscore underscore".
    """
    jobs: list[Job] = []

    def _walk(items: list[dict]) -> None:
        for it in items or []:
            audio_ref = it.get("audio") or ""
            path = _resolve_sound_ref(audio_ref)
            if path is None:
                continue
            # Pick text — prefer the actual English sentence the learner should hear.
            # listening_choice items split English between 'question' and 'correct'
            # asymmetrically, so route through _pick_english_field which selects
            # the side with ≥70% ASCII letters rather than blindly trusting order.
            text = _filled_gap_question(it)
            if not text:
                text = _pick_english_field(it, ("audio_text", "text", "question", "correct"))
            if not text:
                continue
            # If no field is predominantly English, skip rather than send Russian
            # to an English voice (edge-tts returns "No audio was received").
            if _english_ratio(text) < 0.5:
                print(
                    f"   warn: skip {audio_ref} — no English text in item "
                    f"(question={it.get('question')!r}, correct={it.get('correct')!r})"
                )
                continue
            jobs.append(Job(
                file=fname,
                lesson_number=lesson["number"],
                lesson_type=lesson["type"],
                audio_url=audio_ref,
                output_path=path,
                text=text,
                voice=voice,
                rate=rate,
            ))

    c = lesson.get("content") or {}
    # Quiz-style lessons keep their exercises at content.exercises.
    _walk(c.get("exercises") or [])
    # Final tests nest exercises inside test_sections[].exercises.
    for section in c.get("test_sections") or []:
        _walk(section.get("exercises") or [])

    # Reading lessons keep per-line audio at content.text.lines[].audio. Each
    # line carries its own `text` (English) and optional `voice`
    # (neutral/female/male) which selects the TTS voice.
    if lesson.get("type") == "reading":
        text_obj = c.get("text")
        if isinstance(text_obj, dict):
            for line in text_obj.get("lines") or []:
                ref = (line.get("audio") or "").strip()
                path = _resolve_sound_ref(ref)
                if path is None:
                    continue
                line_text = clean(line.get("text") or "")
                if not line_text or _english_ratio(line_text) < 0.5:
                    continue
                line_voice = READING_LINE_VOICE.get(
                    (line.get("voice") or "neutral").lower(),
                    "en-US-AriaNeural",
                )
                jobs.append(Job(
                    file=fname, lesson_number=lesson["number"],
                    lesson_type=lesson["type"], audio_url=ref,
                    output_path=path, text=line_text,
                    voice=line_voice, rate=rate,
                ))

    # Grammar lessons hold three shapes for example audio:
    #   (a) parallel `examples` + `audio` arrays inside nested sections.rules[]
    #   (b) single `audio` ref paired with single `example` field inside
    #       sections.table[] rows (pronoun/form/example/translation/audio)
    # The example string is "EN — RU" (em-dash) or "EN - RU" (hyphen-spaces).
    if lesson.get("type") == "grammar":
        def _is_meta_glossary(s: str) -> bool:
            """Detect "EN = RU, EN = RU, ..." translation-glossary patterns.

            These are meta-instructional rows where the example is a vocab-key=meaning
            list, not a sentence. They don't make sense as TTS audio (a learner hearing
            "turn on, turn off, turn down" without contrast doesn't learn anything).
            Signal: at least one "=" sign followed by Cyrillic on the right side.
            """
            return bool(re.search(r"=\s*[^,;=]*[\u0400-\u04ff]", s))

        def _strip_russian_glosses(s: str) -> str:
            """Strip parenthetical Russian glosses and bilingual meta-markers from grammar examples."""
            # 1. Remove '(...)' parens that contain any Cyrillic — these are Russian translations
            s = re.sub(r"\s*\([^)]*[\u0400-\u04ff][^)]*\)\s*", " ", s)
            # 2. Remove ❌/✓/→ markers along with anything after the first ✓ (the "wrong → right" pattern)
            #    so we keep only the leading English (or right side English after ✓).
            #    Strip the markers in any case.
            s = re.sub(r"[❌✓→]", " ", s)
            # 3. Strip leading/trailing Russian words/phrases separated by — / em-dash
            s = re.split(r"\s+[—-]\s+", s, maxsplit=1)[0]
            # 4. Collapse whitespace
            s = re.sub(r"\s+", " ", s).strip()
            return s

        def _enq(ref: object, ex: object) -> None:
            if not isinstance(ref, str) or not isinstance(ex, str):
                return
            path = _resolve_sound_ref(ref)
            if path is None:
                return
            # Skip meta-instructional rows: "EN = RU, EN = RU" glossary lists are
            # contrastive vocabulary tables, not sentences worth synthesizing.
            if _is_meta_glossary(ex):
                return
            en = _strip_russian_glosses(ex)
            en = clean(en)
            # Threshold for grammar (0.85) — these examples often contain residual
            # Russian even after stripping (meta-instructional patterns like
            # "«wrong» вместо «right»"). If <85% English, skip rather than
            # send mixed text to an English voice.
            if not en or _english_ratio(en) < 0.85:
                return
            jobs.append(Job(
                file=fname, lesson_number=lesson["number"],
                lesson_type=lesson["type"], audio_url=ref,
                output_path=path, text=en,
                voice="en-US-AriaNeural", rate="-5%",
            ))

        # Known paired-field shapes for grammar table rows where audio[] is a list
        # of two refs paired with two English fields.
        PAIRED_FIELD_PATTERNS = [
            ("question", "answer"),            # Q&A rows (12 found)
            ("normal", "inverted"),            # normal vs inverted sentence (11 found)
            ("with_if", "with_inversion"),     # conditional with vs without if (9 found)
            ("positive", "negative"),          # positive vs negative pair (3 found)
        ]

        def _grammar_walk(o: object) -> None:
            if isinstance(o, dict):
                audios = o.get("audio")
                examples = o.get("examples")
                # Shape (a): parallel arrays via `examples`.
                if (isinstance(audios, list) and isinstance(examples, list)
                        and len(audios) == len(examples)):
                    for ref, ex in zip(audios, examples):
                        _enq(ref, ex)
                # Shape (a2): parallel audio list paired with named English fields.
                elif isinstance(audios, list) and len(audios) >= 2:
                    matched = False
                    for fa, fb in PAIRED_FIELD_PATTERNS:
                        va, vb = o.get(fa), o.get(fb)
                        if (isinstance(va, str) and isinstance(vb, str)
                                and len(audios) >= 2):
                            _enq(audios[0], va)
                            _enq(audios[1], vb)
                            matched = True
                            break
                    if not matched:
                        # Fallback: single English `example` field, only first audio.
                        single_ex = o.get("example")
                        if isinstance(single_ex, str) and audios:
                            _enq(audios[0], single_ex)
                # Shape (b): single audio + named English field(s).
                # Falls back through known shapes found in grammar tables:
                #   {example: "..."}                                — single English example (legacy)
                #   {idiom, register, use_where}                    — idiom-register row
                #   {phrase, meaning}                               — phrase + RU meaning
                #   {examples: "look up, give up, ..."}             — comma list of examples
                #   {cliché, issue, example_bad}                    — cliché analysis
                #   {if_clause, main_clause, translation}           — conditional pair → combined
                #   {earlier, later, translation}                   — sequence pair → combined
                #   {formal, informal}                              — register pair → combined
                #   {BrE, AmE, meaning}                             — dialect pair → combined
                #   {v1, v3}                                        — verb forms → combined "V1, V3"
                elif isinstance(audios, str):
                    candidates: list[str] = []
                    # single-field shapes (use just that field's value)
                    for k in ("example", "idiom", "phrase", "examples", "example_bad", "cliché"):
                        v = o.get(k)
                        if isinstance(v, str) and v.strip():
                            candidates.append(v); break
                    # multi-field combinable shapes
                    if not candidates:
                        for fa, fb, sep in [
                            ("if_clause", "main_clause", " "),
                            ("earlier", "later", " "),
                            ("formal", "informal", " "),
                            ("BrE", "AmE", " "),
                            ("v1", "v3", ", "),
                        ]:
                            va, vb = o.get(fa), o.get(fb)
                            if (isinstance(va, str) and va.strip()
                                    and isinstance(vb, str) and vb.strip()):
                                candidates.append(f"{va.rstrip(',. ')}{sep}{vb}")
                                break
                    if candidates:
                        _enq(audios, candidates[0])
                for v in o.values():
                    _grammar_walk(v)
            elif isinstance(o, list):
                for it in o:
                    _grammar_walk(it)
        _grammar_walk(c)
    return jobs


def collect_jobs(module_filter: str | None = None) -> list[Job]:
    jobs: list[Job] = []
    pilots = list_pilots()
    files = pilots
    if module_filter:
        # Match by prefix on the `module_<...>_` segment, so 'A1_1' only matches
        # module_A1_1_*.json and does NOT also pick up A1_10, A1_11, ….  The
        # caller may pass the pattern with or without a trailing underscore.
        needle = module_filter.rstrip("_")
        prefix = f"module_{needle}_"
        files = [f for f in pilots if f.startswith(prefix)]
    for fname in files:
        data = json.loads((PILOT_DIR / fname).read_text(encoding="utf-8"))
        for lesson in data["module"]["lessons"]:
            c = lesson.get("content") or {}
            url = c.get("audio_url")
            voice, rate = TYPE_VOICE.get(lesson["type"], ("en-US-AriaNeural", "+0%"))
            if url:
                text = assemble_text(lesson)
                if text:
                    jobs.append(Job(
                        file=fname,
                        lesson_number=lesson["number"],
                        lesson_type=lesson["type"],
                        audio_url=url,
                        output_path=resolve_path(url),
                        text=text,
                        voice=voice,
                        rate=rate,
                    ))
            # audio_fill_blank: per-item `audio_clip_url` files (one mp3 per item,
            # each playing the FILLED sentence "stem with answer substituted").
            if lesson["type"] == "audio_fill_blank":
                for it in (c.get("items") or []):
                    clip_url = it.get("audio_clip_url")
                    if not clip_url:
                        continue
                    stem = (it.get("text_with_gap") or "").strip()
                    ans = (it.get("answer") or "").strip()
                    if not stem:
                        continue
                    filled = clean(stem.replace("___", ans).strip())
                    if not filled:
                        continue
                    jobs.append(Job(
                        file=fname,
                        lesson_number=lesson["number"],
                        lesson_type=lesson["type"],
                        audio_url=clip_url,
                        output_path=resolve_path(clip_url),
                        text=filled,
                        voice=voice,
                        rate=rate,
                    ))
            # Inline [sound:...] refs (listening_quiz item audio, final_test
            # listening_choice audio). These live alongside lesson-level audio.
            jobs.extend(_collect_inline_jobs(fname, lesson, voice=voice, rate=rate))
    return jobs


def parse_dialogue_turns(text: str) -> list[tuple[str, str]] | None:
    """Split a dialogue blob into [(speaker_key, line_text), ...].

    Supports two formats commonly used in listening_immersion lessons:

      1. "Name: utterance"   — speakers identified by name (e.g. Sarah, Michael).
         Also supports compact inline turns like "A: Hi. B: Hello.".
      2. "- utterance"       — two anonymous speakers alternating; we label them
                               "A" and "B" by line index.

    Returns None if the text is not multi-speaker (no recognisable turns).
    """
    source = clean_preserve_lines(text)
    if not source:
        return None

    named = re.compile(
        r"(?<![A-Za-z])([A-Z][A-Za-z]{0,24})\s*:\s*"
    )
    named_matches = list(named.finditer(source))
    if len(named_matches) >= 2:
        turns: list[tuple[str, str]] = []
        for idx, match in enumerate(named_matches):
            speaker = match.group(1)
            start = match.end()
            end = (
                named_matches[idx + 1].start()
                if idx + 1 < len(named_matches)
                else len(source)
            )
            utterance = clean(source[start:end])
            if utterance:
                turns.append((speaker, utterance))
        if len(turns) >= 2 and len({speaker for speaker, _ in turns}) >= 2:
            return turns

    raw_lines = [ln.strip() for ln in source.splitlines() if ln.strip()]
    if len(raw_lines) < 2:
        return None
    turns = []
    dashed = re.compile(r"^[-—]\s+(.+)$")
    speakers_dashed = 0
    for ln in raw_lines:
        m = dashed.match(ln)
        if m:
            speakers_dashed += 1
            label = "A" if (len(turns) % 2 == 0) else "B"
            turns.append((label, m.group(1).strip()))
            continue
        # Continuation line: append to previous turn if any
        if turns:
            spk, prev = turns[-1]
            turns[-1] = (spk, (prev + " " + ln).strip())
    if speakers_dashed < 2:
        return None
    return turns


def pick_dialogue_voice(speaker: str, speaker_to_voice: dict[str, str]) -> str:
    """Assign a voice per speaker, alternating across speakers in encounter order."""
    if speaker in speaker_to_voice:
        return speaker_to_voice[speaker]
    # Pick the next voice from DIALOGUE_VOICES not yet used.
    used = set(speaker_to_voice.values())
    for v in DIALOGUE_VOICES:
        if v not in used:
            speaker_to_voice[speaker] = v
            return v
    # All voices used — fall back to alternating by index.
    speaker_to_voice[speaker] = DIALOGUE_VOICES[len(speaker_to_voice) % len(DIALOGUE_VOICES)]
    return speaker_to_voice[speaker]


def describe_voice(job: Job) -> str:
    if job.lesson_type != "listening_immersion":
        return f"voice={job.voice}"
    turns = parse_dialogue_turns(job.text)
    if not turns:
        return f"voice={job.voice}"
    speaker_to_voice: dict[str, str] = {}
    for speaker, _ in turns:
        pick_dialogue_voice(speaker, speaker_to_voice)
    speakers = ", ".join(
        f"{speaker}={voice}" for speaker, voice in speaker_to_voice.items()
    )
    return f"voices=[{speakers}] turns={len(turns)}"


def _is_retryable_tts_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    retry_markers = (
        "timeout",
        "timed out",
        "connection",
        "connect",
        "server disconnected",
        "temporarily",
        "too many requests",
        "websocket",
        "wss://",
        "429",
        "502",
        "503",
        "504",
    )
    return (
        isinstance(exc, (TimeoutError, ConnectionError, OSError))
        or any(marker in msg for marker in retry_markers)
    )


def _tmp_output_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp")


async def _synthesize_once(job: Job) -> None:
    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_output_path(job.output_path)
    tmp_path.unlink(missing_ok=True)

    # Multi-voice path for listening_immersion dialogues. We detect a dialogue
    # structure in `job.text`; if found, generate per-turn MP3s with alternating
    # voices and concatenate them. Otherwise fall back to single-voice TTS.
    if job.lesson_type == "listening_immersion":
        turns = parse_dialogue_turns(job.text)
        if turns and len(turns) >= 2:
            speaker_to_voice: dict[str, str] = {}
            chunks: list[bytes] = []
            for speaker, utter in turns:
                v = pick_dialogue_voice(speaker, speaker_to_voice)
                comm = edge_tts.Communicate(utter, v, rate=job.rate)
                buf = bytearray()
                async for chunk in comm.stream():
                    if chunk.get("type") == "audio":
                        buf.extend(chunk["data"])
                chunks.append(bytes(buf))
            tmp_path.write_bytes(b"".join(chunks))
            tmp_path.replace(job.output_path)
            return
    # Default: single-voice synthesis.
    comm = edge_tts.Communicate(job.text, job.voice, rate=job.rate)
    await comm.save(str(tmp_path))
    tmp_path.replace(job.output_path)


async def synthesize(
    job: Job,
    *,
    retries: int = DEFAULT_TTS_RETRIES,
    retry_delay: float = DEFAULT_TTS_RETRY_DELAY,
) -> None:
    retries = max(0, retries)
    retry_delay = max(0.0, retry_delay)

    for attempt in range(retries + 1):
        try:
            await _synthesize_once(job)
            return
        except Exception as exc:
            retry_number = attempt + 1
            if attempt >= retries or not _is_retryable_tts_error(exc):
                raise
            delay = retry_delay * (2 ** attempt)
            print(
                f"   retry {retry_number}/{retries} for {job.audio_url}: "
                f"{type(exc).__name__}: {exc}"
            )
            if delay:
                await asyncio.sleep(delay)


async def amain() -> int:
    ap = argparse.ArgumentParser(
        prog="generate_pilot_audio.py",
        description=(
            "Generate TTS audio for the canonical pilot module_completed/fixed/*.json files.\n\n"
            "Safety: dry-run by default. Pass --apply to actually write MP3s. "
            "Existing files are skipped unless --force is given."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/generate_pilot_audio.py                                # dry-run, lists every job\n"
            "  python scripts/generate_pilot_audio.py --apply                        # write missing MP3s (skips pron*)\n"
            "  python scripts/generate_pilot_audio.py --apply --force                # regenerate everything\n"
            "  python scripts/generate_pilot_audio.py --apply --type dictation      # only dictation lessons\n"
            "  python scripts/generate_pilot_audio.py --apply --module A1_4         # only module A1/M4\n"
            "  python scripts/generate_pilot_audio.py --apply --module B1_          # only B1 modules\n"
        ),
    )
    # Preview is the default; --dry-run exists so it can be stated explicitly.
    # Mutually exclusive so `--apply --dry-run` is an error rather than one of
    # the two silently winning.
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Preview only, writing nothing. This is the default.",
    )
    mode.add_argument(
        "--apply", action="store_true",
        help="Actually write MP3s. Without this, the script is a no-op preview.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help=(
            "Overwrite all existing files without prompting. "
            "Default behaviour: when a file exists, interactively ask "
            "1.перезаписать / 2.пропустить / 3.перезаписать все / 4.пропустить все. "
            "In non-TTY mode (CI, piped) existing files are skipped."
        ),
    )
    ap.add_argument(
        "--type", default=None,
        help="Only this lesson_type (dictation/listening_immersion/shadow_reading/audio_fill_blank/listening_quiz/final_test).",
    )
    ap.add_argument(
        "--module", default=None,
        help=(
            "Only modules whose filename matches module_<pattern>_*.json "
            "(prefix match with boundary, so 'A1_1' matches ONLY "
            "module_A1_1_*.json, not A1_10/A1_11/…; "
            "'A1' or 'A1_' matches every A1 module)."
        ),
    )
    ap.add_argument(
        "--include-pron", action="store_true",
        help=(
            "Also generate audio whose filename starts with 'pron' "
            "(vocabulary pronunciation_en_*.mp3 files are skipped by default — "
            "they are produced by a separate per-word generator)."
        ),
    )
    ap.add_argument(
        "--tts-retries", type=int, default=DEFAULT_TTS_RETRIES,
        help=(
            "How many times to retry a transient edge-tts failure after the "
            f"initial attempt (default: {DEFAULT_TTS_RETRIES})."
        ),
    )
    ap.add_argument(
        "--tts-retry-delay", type=float, default=DEFAULT_TTS_RETRY_DELAY,
        help=(
            "Initial retry delay in seconds; each retry doubles it "
            f"(default: {DEFAULT_TTS_RETRY_DELAY})."
        ),
    )
    args = ap.parse_args()
    apply = args.apply and not args.dry_run
    if not apply:
        import sys as _sys
        print(
            "DRY-RUN (no files will be written). Pass --apply to actually generate.\n",
            file=_sys.stderr,
        )

    jobs = collect_jobs(module_filter=args.module)
    if args.module and not jobs:
        print(f"No modules matched --module={args.module!r}")
    if args.type:
        jobs = [j for j in jobs if j.lesson_type == args.type]
    if not args.include_pron:
        # Skip word-pronunciation files (pronunciation_en_*.mp3 etc.) — those
        # are produced by a separate per-word generator over CollectionWords.
        before = len(jobs)
        jobs = [j for j in jobs if not j.output_path.name.startswith("pron")]
        filtered_pron = before - len(jobs)
        if filtered_pron:
            print(f"skipped {filtered_pron} pron* job(s) (pass --include-pron to keep)")

    import sys
    is_tty = sys.stdin.isatty()
    overwrite_all = bool(args.force)  # --force = overwrite everything without prompting
    skip_all = False

    def _prompt_existing(path: Path) -> str:
        """Return 'overwrite' or 'skip' for an existing file. Updates outer state."""
        nonlocal overwrite_all, skip_all
        if overwrite_all:
            return 'overwrite'
        if skip_all:
            return 'skip'
        if not is_tty:
            # Non-interactive (CI, piped) — default to skip, preserves old behavior.
            return 'skip'
        try:
            rel_path = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        except (ValueError, AttributeError):
            rel_path = path
        # Show filename only — full path is too long for the eye to parse quickly
        fname_only = path.name
        while True:
            try:
                raw = input(
                    f"\n⚠️  Файл {fname_only} уже существует!\n"
                    f"Выберите действие:\n"
                    f"  1. Перезаписать этот файл\n"
                    f"  2. Пропустить этот файл\n"
                    f"  3. Перезаписать ВСЕ существующие файлы\n"
                    f"  4. Пропустить ВСЕ существующие файлы\n"
                    f"Ваш выбор (1-4): "
                )
            except (EOFError, KeyboardInterrupt):
                print(); return 'skip'
            ans = (raw or "").strip().strip('\r\n\t ').lower()
            # Accept numbered (1-4), as well as legacy letter shorthand (o/s/O/S → 1/2/3/4)
            if ans in ('1', 'о', 'o', 'overwrite', 'перезаписать'):
                return 'overwrite'
            if ans in ('2', 'п', 's', 'skip', 'пропустить'):
                return 'skip'
            if ans in ('3', 'все', 'all', 'overwrite-all', 'overwriteall'):
                overwrite_all = True
                print("  → перезаписываем ВСЕ оставшиеся существующие файлы")
                return 'overwrite'
            if ans in ('4', 'skip-all', 'skipall', 'пропустить все'):
                skip_all = True
                print("  → пропускаем ВСЕ оставшиеся существующие файлы")
                return 'skip'
            print(f"  ✗ непонятный ответ: {raw!r}. Введите 1, 2, 3 или 4.")

    created = skipped = failed = 0
    for j in jobs:
        exists = j.output_path.exists()
        voice_info = describe_voice(j)
        if exists:
            decision = _prompt_existing(j.output_path)
            if decision == 'skip':
                # Quiet skip: don't clutter the log with "skip exists" lines —
                # the summary counter at the bottom shows the total skipped count.
                skipped += 1
                continue
            # else: overwrite — fall through to apply path
        print(
            f"{'apply' if apply else 'dry-run'}: {j.file:48s} "
            f"L{j.lesson_number:>2} {j.lesson_type:<22} "
            f"{voice_info} rate={j.rate} text={len(j.text)}ch"
        )
        if not apply:
            skipped += 1
            continue
        try:
            await synthesize(
                j,
                retries=args.tts_retries,
                retry_delay=args.tts_retry_delay,
            )
            size = j.output_path.stat().st_size
            try:
                rel = j.output_path.relative_to(ROOT)
            except ValueError:
                rel = j.output_path
            print(f"   ok  -> {rel} ({size//1024} KB)")
            created += 1
        except Exception as e:
            print(f"   FAIL {j.audio_url}: {e}")
            failed += 1

    print(f"\nsummary: created={created} skipped={skipped} failed={failed} total={len(jobs)}")
    return 1 if failed else 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
