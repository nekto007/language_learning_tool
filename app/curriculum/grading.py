# app/curriculum/grading.py
"""Submission processing / grading functions for curriculum exercises."""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Optional

from app.curriculum.blank_answers import matches_completed_blank
from app.curriculum.constants import PASSING_SCORE_DEFAULT, PASSING_SCORE_DICTATION, PASSING_SCORE_FINAL_TEST
from app.utils.normalization import (
    EXPECTED_ZERO_ARTICLE_MARKERS, ZERO_ARTICLE_MARKERS, normalize_text, normalize_quiz_answer,
)

logger = logging.getLogger(__name__)


FINAL_TEST_MAX_ATTEMPTS_PER_DAY = 3
FINAL_TEST_ATTEMPT_WINDOW_HOURS = 24


def check_final_test_attempts_exhausted(
    user_id: int,
    lesson_id: int,
    db_session=None,
    max_attempts: int = FINAL_TEST_MAX_ATTEMPTS_PER_DAY,
    window_hours: int = FINAL_TEST_ATTEMPT_WINDOW_HOURS,
) -> Optional[dict]:
    """Return rate-limit dict if user has met or exceeded the final-test attempt cap
    within the rolling window. Admins are exempt. Returns None when allowed.

    Response on exhaustion:
        {"passed": False, "error": "attempts_exhausted",
         "retry_after": <ISO8601 UTC>, "max_attempts": N, "window_hours": H}
    """
    from app.auth.models import User
    from app.curriculum.models import LessonAttempt
    from app.utils.db import db as default_db

    session = db_session if db_session is not None else default_db.session
    if hasattr(session, 'session'):
        session = session.session

    user = session.get(User, user_id)
    if user is not None and getattr(user, 'is_admin', False):
        return None

    window_start = datetime.now(UTC) - timedelta(hours=window_hours)
    window_start_naive = window_start.replace(tzinfo=None)

    # Filter on completed_at, not started_at: production code in
    # complete_lesson reuses progress.started_at across every attempt
    # (set once on initial LessonProgress creation), so a started_at
    # filter would let the rolling window age out by 24h after the
    # first attempt and never gate a retry. completed_at is set fresh
    # per attempt.
    attempts = (
        session.query(LessonAttempt)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.lesson_id == lesson_id,
            LessonAttempt.completed_at.isnot(None),
            LessonAttempt.completed_at >= window_start_naive,
            LessonAttempt.passed.is_(False),
        )
        .order_by(LessonAttempt.completed_at.asc())
        .all()
    )

    if len(attempts) < max_attempts:
        return None

    oldest = attempts[0].completed_at
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    retry_after = oldest + timedelta(hours=window_hours)

    return {
        "passed": False,
        "error": "attempts_exhausted",
        "retry_after": retry_after.isoformat(),
        "max_attempts": max_attempts,
        "window_hours": window_hours,
    }


def _normalize_answer(s):
    """Normalize answer for strict comparison: strip, lower, strip punctuation, collapse spaces."""
    if s is None:
        return ""
    return normalize_text(str(s))


def _levenshtein(a, b):
    """Compute Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


_APOSTROPHES = "'\u2019\u02bc\u2032"

# Contractions expanded on BOTH sides before the strict comparison (lesson
# audit 2026-09-05, A3): ``normalize_text`` strips every apostrophe, so
# «he's my relative» became «hes my relative» and could never equal the
# canonical «he is my relative» — three tries burnt on a contraction. Only
# contractions are canonicalised; articles, word order and multi-word typos
# stay strict (agreed with the reviewer: an article can change the meaning).
#
# ``'s`` is expanded ONLY after a closed set of heads that cannot be a
# possessive (it's, he's, that's, there's, what's …): a noun possessive such
# as «Google's history» is left alone, otherwise it aliased «Google is
# history» (review of item 6). Ambiguous forms branch per occurrence —
# ``'s`` → is | has, ``'d`` → would | had — so «He'd said she'd leave» meets
# «He had said she would leave».
_CONTRACTION_WHOLE_WORDS = (
    (r"\bwon't\b", 'will not'),
    (r"\bcan't\b", 'cannot'),
    (r"\bshan't\b", 'shall not'),
    (r"\bcan not\b", 'cannot'),
    (r"\blet's\b", 'let us'),
)
_CONTRACTION_SUFFIXES = (
    (r"n't\b", ' not'),
    (r"'re\b", ' are'),
    (r"'ve\b", ' have'),
    (r"'ll\b", ' will'),
    (r"'m\b", ' am'),
)
_S_CONTRACTION_HEADS = (
    'it', 'he', 'she', 'that', 'there', 'here', 'what', 'who', 'where', 'when',
    'how', 'why', 'this', 'everyone', 'everybody', 'someone', 'somebody',
    'nobody', 'nothing', 'something', 'everything',
)
_AMBIGUOUS_CONTRACTION_RE = re.compile(
    r"\b(?P<head>" + '|'.join(_S_CONTRACTION_HEADS) + r")'s\b|(?<=\w)'d\b",
)
_S_READINGS = ('is', 'has')
_D_READINGS = ('would', 'had')
_CONTRACTION_VARIANTS_CAP = 64


def _contraction_variants(text) -> list[str]:
    """Return the text with contractions expanded, one entry per reading of
    the ambiguous ones (``'s`` → is/has, ``'d`` → would/had), lower-cased."""
    s = str(text or '')
    if not s:
        return ['']
    for ch in _APOSTROPHES[1:]:
        s = s.replace(ch, "'")
    low = s.lower()
    for pattern, repl in _CONTRACTION_WHOLE_WORDS:
        low = re.sub(pattern, repl, low)
    for pattern, repl in _CONTRACTION_SUFFIXES:
        low = re.sub(pattern, repl, low)
    variants = ['']
    pos = 0
    for match in _AMBIGUOUS_CONTRACTION_RE.finditer(low):
        literal = low[pos:match.start()]
        if match.group('head'):
            options = [f"{match.group('head')} {verb}" for verb in _S_READINGS]
        else:
            options = [' ' + verb for verb in _D_READINGS]
        variants = [v + literal + opt for v in variants for opt in options]
        if len(variants) > _CONTRACTION_VARIANTS_CAP:
            variants = variants[:_CONTRACTION_VARIANTS_CAP]
        pos = match.end()
    tail = low[pos:]
    return [v + tail for v in variants]


_WRITTEN_WHOLE = [(expanded, form.removeprefix(r'\b').removesuffix(r'\b'))
                  for form, expanded in _CONTRACTION_WHOLE_WORDS]
_WRITTEN_SUFFIX = {expanded.strip(): form.removesuffix(r'\b')
                   for form, expanded in _CONTRACTION_SUFFIXES[1:]}
_WRITTEN_AUXILIARIES = frozenset({
    'is', 'are', 'was', 'were', 'do', 'does', 'did', 'have', 'has', 'had',
    'could', 'would', 'should', 'must', 'need',
})
_WRITTEN_HEADS = frozenset({'i', 'you', 'he', 'she', 'it', 'we', 'they', *_S_CONTRACTION_HEADS})
_WRITTEN_PAIR = re.compile(r'(?=(\b([a-z]+)\s+([a-z]+)\b))')


def written_contraction_forms(sentence: str) -> set[str]:
    """Use the existing contraction spellings in the direction of an exact key."""
    expanded = _contraction_variants(sentence)
    variants = {sentence, *expanded} if len(expanded) == 1 else {sentence}
    queue = sorted(variants)
    for text in queue:
        if len(variants) >= _CONTRACTION_VARIANTS_CAP:
            break
        replacements = [(m.start(), m.end(), short) for full, short in _WRITTEN_WHOLE
                        for m in re.finditer(r'\b' + full + r'\b', text)]
        for match in _WRITTEN_PAIR.finditer(text):
            _, head, verb = match.groups()
            start, end = match.span(1)
            if verb == 'not' and head in _WRITTEN_AUXILIARIES:
                replacements.append((start, end, head + "n't"))
            # A positive auxiliary needs a continuation within the clause.
            # In a short answer a stressed final auxiliary stays written out.
            if head not in _WRITTEN_HEADS or not re.match(r'\s+\w', text[end:]):
                continue
            if verb in _S_READINGS and head in _S_CONTRACTION_HEADS:
                suffix = "'s"
            elif verb in _D_READINGS:
                suffix = "'d"
            else:
                suffix = _WRITTEN_SUFFIX.get(verb)
            if suffix:
                replacements.append((start, end, head + suffix))
        for start, end, replacement in replacements:
            alternate = text[:start] + replacement + text[end:]
            if alternate not in variants and len(variants) < _CONTRACTION_VARIANTS_CAP:
                variants.add(alternate)
                queue.append(alternate)
    return variants


# Lexical variants folded to one spelling before the strict comparison
# (lesson audit item 20, owner: «вариации mother/mom учитывать»). Only
# register pairs of the SAME word (mum/mom/mother) and BrE/AmE spellings —
# never synonyms that change meaning (flat/apartment, film/movie stay
# distinct, the author lists those in ``alternatives``) and never a form
# with a second sense or part of speech (mummy = мумия, kid = to joke —
# Codex review). Whole words only, applied after lower-casing, on both
# sides of the comparison.
_LEXICAL_VARIANTS = {
    'mum': 'mother', 'mom': 'mother', 'mommy': 'mother',
    'mama': 'mother', 'mamma': 'mother',
    'mums': 'mothers', 'moms': 'mothers',
    'dad': 'father', 'daddy': 'father', 'papa': 'father',
    'dads': 'fathers',
    'grandma': 'grandmother', 'granny': 'grandmother', 'gran': 'grandmother',
    'grandpa': 'grandfather', 'granddad': 'grandfather', 'grandad': 'grandfather',
    'neighbor': 'neighbour', 'neighbors': 'neighbours',
    'neighborhood': 'neighbourhood', 'neighborhoods': 'neighbourhoods',
    'color': 'colour', 'colors': 'colours', 'colored': 'coloured',
    'favorite': 'favourite', 'favorites': 'favourites',
    'center': 'centre', 'centers': 'centres',
    'theater': 'theatre', 'theaters': 'theatres',
    'gray': 'grey', 'programme': 'program', 'programmes': 'programs',
    'practise': 'practice', 'practises': 'practices',
    'practised': 'practiced', 'practising': 'practicing',
    'organise': 'organize', 'organises': 'organizes',
    'organised': 'organized', 'organising': 'organizing',
    'realise': 'realize', 'realises': 'realizes',
    'realised': 'realized', 'realising': 'realizing',
    'recognise': 'recognize', 'recognises': 'recognizes',
    'recognised': 'recognized', 'recognising': 'recognizing',
    'apologise': 'apologize', 'apologises': 'apologizes',
    'apologised': 'apologized', 'apologising': 'apologizing',
    'travelling': 'traveling', 'travelled': 'traveled',
    'traveller': 'traveler', 'travellers': 'travelers',
    'ok': 'okay',
}
_LEXICAL_WORD_RE = re.compile(r"[a-z]+")


def fold_lexical_variants(text) -> str:
    """Lower-case ``text`` and replace every whole word listed in
    ``_LEXICAL_VARIANTS`` by its canonical spelling."""
    low = str(text or '').lower()
    return _LEXICAL_WORD_RE.sub(
        lambda m: _LEXICAL_VARIANTS.get(m.group(0), m.group(0)), low,
    )


_KEEP_APOSTROPHE_RE = re.compile(r"[^\w\s']")


def _normalize_keep_apostrophes(text) -> str:
    """Like ``normalize_text`` but apostrophes survive: after the contraction
    expansion the ones left are possessives, and «the girl's books» must not
    equal «the girls' books» (Codex review of item 20)."""
    low = str(text or '').lower()
    for ch in _APOSTROPHES[1:]:
        low = low.replace(ch, "'")
    low = _KEEP_APOSTROPHE_RE.sub('', low)
    return re.sub(r'\s+', ' ', low).strip()


def text_answer_variants(text) -> set[str]:
    """Normalised readings of a free-text answer: contractions expanded
    (each ambiguous one branching), lexical variants folded, punctuation
    dropped except apostrophes.

    Two answers are the same sentence iff their variant sets intersect.
    Shared by the course translation grader and the grammar-lab grader so
    both accept «my mom's a doctor» for «My mum is a doctor.» without the
    author listing every register × contraction combination."""
    return {
        _normalize_keep_apostrophes(fold_lexical_variants(v))
        for v in _contraction_variants(text)
    }


def _strict_text_match(user_answer, candidates):
    """
    Strict grading for fill-in-blank / translation answers.

    Exact match after normalization. For single-word candidates of **≥4
    characters**, allow Levenshtein distance ≤1 (typo tolerance); shorter
    tokens require exact match (a 1-edit window on 2-3 letter words admits
    substantively different words, e.g. "is"/"in"). Multi-word answers require
    exact match — overlap heuristics are intentionally not used.
    """
    user_normalized = _normalize_answer(user_answer)
    if not user_normalized:
        return False
    user_variants = text_answer_variants(user_answer)
    for candidate in candidates:
        if candidate is None:
            continue
        correct_normalized = _normalize_answer(candidate)
        if not correct_normalized:
            continue
        if user_normalized == correct_normalized:
            return True
        if user_variants & text_answer_variants(candidate):
            return True
        # Typo tolerance only for single-word answers >=4 chars; on shorter
        # tokens a 1-edit window admits substantively different words
        # (e.g. "is"/"in", "a"/"o").
        if (
            ' ' not in correct_normalized
            and ' ' not in user_normalized
            and len(correct_normalized) >= 4
        ):
            if _levenshtein(user_normalized, correct_normalized) <= 1:
                return True
    return False


def quiz_text_matches(user_answer, candidates):
    """Exact words after the quiz case/punctuation policy, plus authored aliases.

    Used by ordinary/final quiz text and grammar, including preview and
    submit. Existing contraction and lexical variants remain additional
    accepted readings; no edit-distance, word-overlap or word-order
    heuristic is used here. Apostrophes are ignored by explicit owner policy,
    so girl's/girls' and don't/dont do not fail on punctuation alone.
    Dictation and other non-quiz graders keep their existing normalization.
    """
    user = normalize_quiz_answer(user_answer)
    readings = {normalize_quiz_answer(v) for v in text_answer_variants(user_answer)}
    for candidate in candidates:
        if candidate is None:
            continue
        raw = str(candidate).strip().casefold()
        if raw in EXPECTED_ZERO_ARTICLE_MARKERS:
            if str(user_answer or '').strip().casefold() in ZERO_ARTICLE_MARKERS:
                return True
            continue
        expected = normalize_quiz_answer(candidate)
        if not user or not expected:
            continue
        if user == expected:
            return True
        other = {normalize_quiz_answer(v) for v in text_answer_variants(candidate)}
        if (readings - {''}) & (other - {''}):
            return True
    return False


def _grade_matching_pairs(user_pairs, correct_pairs):
    """
    Server-side validation of matching pairs.

    Both inputs are lists of {"left": X, "right": Y} dicts. Returns True iff
    every correct pair has a corresponding user pair (order-independent),
    and the user submitted no extras.
    """
    if not isinstance(user_pairs, list) or not isinstance(correct_pairs, list):
        return False
    if not correct_pairs:
        return False
    if len(user_pairs) != len(correct_pairs):
        return False

    def _key(p):
        if not isinstance(p, dict):
            return None
        # Content payloads use {english, russian}; user payloads use {left, right}.
        # Treat both shapes as equivalent so matching grading isn't a no-op.
        left = p.get('left') or p.get('english') or p.get('word')
        right = p.get('right') or p.get('russian') or p.get('translation')
        return (normalize_quiz_answer(left), normalize_quiz_answer(right))

    user_keys = [_key(p) for p in user_pairs]
    correct_keys = [_key(p) for p in correct_pairs]
    if any(k is None or k == ("", "") for k in user_keys):
        return False
    if any(k is None for k in correct_keys):
        return False
    return sorted(user_keys) == sorted(correct_keys)


def _pair_left(p) -> str:
    """Extract the left/prompt side of a matching pair across content schemas.

    Content payloads vary: ``{left, right}`` (user submissions), ``{english,
    russian}`` and ``{word, translation}``/``{term, match}`` (authored content).
    Treat all shapes as equivalent so matching graders don't ``KeyError`` on
    authored pairs (audit E-033/E-035/E-036)."""
    if not isinstance(p, dict):
        return ''
    return str(
        p.get('left') or p.get('english')
        or p.get('word') or p.get('term') or ''
    )


def _pair_right(p) -> str:
    """Extract the right/answer side of a matching pair across content schemas.

    See :func:`_pair_left`."""
    if not isinstance(p, dict):
        return ''
    return str(
        p.get('right') or p.get('russian')
        or p.get('translation') or p.get('match') or ''
    )


def _coerce_to_index(value, options):
    """Resolve an answer to an option index across content schemas.

    Accepts an int index, a digit string ("2"), or the option text itself
    (matched against ``options`` exactly then case-insensitively). Returns the
    resolved index, or -1 when unresolvable. Mirrors the multiple-choice
    resolution in :func:`process_quiz_submission` so final-test MC questions
    grade identically (audit E-031)."""
    if value is None or isinstance(value, bool):
        return -1
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit() or (s.startswith('-') and s[1:].isdigit()):
            return int(s)
        opts = options or []
        stripped = [o.strip() if isinstance(o, str) else o for o in opts]
        if s in stripped:
            return stripped.index(s)
        s_lower = s.lower()
        for idx, option in enumerate(stripped):
            option_lower = option.lower() if isinstance(option, str) else str(option).lower()
            if option_lower == s_lower:
                return idx
    return -1


def _strict_bool(value) -> bool | None:
    """Parse only explicit boolean-control values; unknown is never False."""
    if type(value) is bool:
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('true', '1', 'yes'):
            return True
        if text in ('false', '0', 'no'):
            return False
    elif type(value) in (int, float) and value in (0, 1):
        return bool(value)
    return None


def _coerce_bool(value) -> bool:
    """Normalize a true/false answer that may arrive as bool, string or number.

    Authored content sometimes stores ``"true"`` (string) rather than a JSON
    bool; without coercion ``True == "true"`` is False and the correct answer
    is marked wrong (audit E-032)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes')
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _normalize_for_dictation(text: str) -> str:
    """Ignore case and punctuation, including straight/smart apostrophes."""
    return normalize_quiz_answer(text)


def _dictation_accuracy(correct_words: int, total_words: int, passing_score: int) -> dict:
    if not total_words:
        return {"score": 0, "passed": False}
    score = round(correct_words / total_words * 100, 2)
    passed = correct_words * 100 >= passing_score * total_words
    # Display/storage precision must never round a failing attempt onto the bar.
    if not passed and score >= passing_score:
        score = max(0, passing_score - 0.01)
    return {"score": score, "passed": passed}


def grade_dictation(
    user_text: str,
    transcript: str,
    hint_chars: int = 0,
    passing_score: int = PASSING_SCORE_DICTATION,
) -> dict:
    """Grade a dictation exercise by comparing user text to the transcript word by word.

    Args:
        user_text: The text submitted by the user.
        transcript: The correct transcript text.
        hint_chars: Number of characters pre-filled per word on the client (server-side
            grading is unchanged — full word comparison is used regardless).

    Returns:
        dict with keys: score (0-100), passed (bool), correct_words (int),
        total_words (int), word_results (list of {word, user_word, correct}).
    """
    user_normalized = _normalize_for_dictation(user_text)
    transcript_normalized = _normalize_for_dictation(transcript)

    transcript_words = transcript_normalized.split() if transcript_normalized else []
    user_words = user_normalized.split() if user_normalized else []

    if not transcript_words:
        return {
            "score": 0,
            "passed": False,
            "correct_words": 0,
            "total_words": 0,
            "word_results": [],
        }

    # Positional word-by-word comparison (audit E-045): intentionally strict —
    # an inserted/deleted word shifts subsequent positions and lowers the score.
    # This rewards accurate transcription; LCS/alignment is deliberately not used.
    # Trailing additions are mistakes too, rather than an ignored suffix.
    total_words = max(len(transcript_words), len(user_words))
    correct_words = 0
    word_results = []
    for i in range(total_words):
        correct_word = transcript_words[i] if i < len(transcript_words) else ""
        user_word = user_words[i] if i < len(user_words) else ""
        is_correct = user_word == correct_word
        if is_correct:
            correct_words += 1
        word_results.append({"word": correct_word, "user_word": user_word, "correct": is_correct})

    return {
        **_dictation_accuracy(correct_words, total_words, passing_score),
        "correct_words": correct_words,
        "total_words": total_words,
        "word_results": word_results,
    }


def grade_dictation_gaps(user_answers: list, items: list, passing_score: int = PASSING_SCORE_DICTATION) -> dict:
    """Keep each separate gap's comparison independent from its neighbours."""
    checked = [grade_dictation(user_answers[i] if i < len(user_answers) else "", item["answer"],
                               passing_score=passing_score)
               for i, item in enumerate(items)]
    correct = sum(row["correct_words"] for row in checked)
    total = sum(row["total_words"] for row in checked)
    return {**_dictation_accuracy(correct, total, passing_score),
            "correct_words": correct, "total_words": total,
            "word_results": [word for row in checked for word in row["word_results"]]}


def grade_audio_fill_blank(
    user_answers: list,
    items: list,
    passing_score: int = PASSING_SCORE_DEFAULT,
) -> dict:
    """Grade an audio fill-in-blank exercise.

    Mixed item format is intentional (audit E-101): an item WITH ``options`` is
    multiple-choice (exact normalized match); an item WITHOUT ``options`` is
    free-text (single-word Levenshtein tolerance). The template branches on
    ``data-mode`` accordingly — do not assume every item has ``options``.

    The literal string ``"null"`` is valid option content (e.g. the legal term
    in C1:04 — audit E-102); never treat option strings as JSON-null / falsy.

    Args:
        user_answers: List of strings, one per item (same order as items).
        items: List of item dicts with 'answer' (and optional 'options') fields.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), item_results (list of {answer, user_answer, correct}).
    """
    total = len(items or [])
    items = items or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }

    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_answer = user_answers[i] if i < len(user_answers) else ''
        correct_answer = item.get('answer', '')
        options = item.get('options')

        if options:
            # Multiple-choice mode: exact match after normalization
            is_correct = _normalize_answer(user_answer) == _normalize_answer(correct_answer)
        else:
            # Free-text mode: Levenshtein ≤1 for single-word, exact for multi-word
            is_correct = _strict_text_match(user_answer, [correct_answer])

        if is_correct:
            correct += 1
        item_results.append({
            'answer': correct_answer,
            'user_answer': user_answer,
            'correct': is_correct,
        })

    score = round(correct / total * 100)
    passed = score >= passing_score

    return {
        'score': score,
        'passed': passed,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_translation(user_answer: str, correct_answer: str) -> dict:
    """Grade a standalone translation exercise (Russian → English).

    Delegates to ``_strict_text_match``: exact match after normalization with
    Levenshtein ≤1 tolerance for single-word answers; multi-word requires exact.

    Returns:
        dict with keys: is_correct (bool), user_answer (str), correct_answer (str).
    """
    is_correct = _strict_text_match(user_answer, [correct_answer])
    return {
        'is_correct': is_correct,
        'user_answer': user_answer,
        'correct_answer': correct_answer,
    }


def grade_translation_multi(
    user_answers: list,
    items: list,
    passing_score: int = PASSING_SCORE_DEFAULT,
) -> dict:
    """Grade a multi-item guided translation lesson.

    Matches the audio_fill_blank / sentence_completion shape so the existing
    completion banner + restore-on-reload flow on the client can be reused
    unchanged.

    Args:
        user_answers: List[str], one per item in original order.
        items: List[dict] from ``content['items']`` with at least ``english``
            (and optional ``alternatives``).

    Returns:
        {score, passed, correct_items, total_items, item_results}.
        Each item_result: {answer, user_answer, correct}.
    """
    from app.curriculum.translation_variants import get_translation_variants, translation_reference

    total = len(items or [])
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }
    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_answer = (user_answers[i] if i < len(user_answers) else '') or ''
        canonical = item.get('english', '') or ''
        russian = item.get('russian', '') or ''
        variants = get_translation_variants(canonical, russian)
        canonical, _ = translation_reference(canonical, russian)
        candidates = [canonical]
        for alt in [*(item.get('alternatives') or []), *variants]:
            if isinstance(alt, str) and alt.strip():
                candidates.append(translation_reference(alt, russian)[0])
        is_correct = _strict_text_match(user_answer, candidates)
        if is_correct:
            correct += 1
        item_results.append({
            'answer': canonical,
            'user_answer': user_answer,
            'correct': is_correct,
        })
    score = round(correct / total * 100)
    return {
        'score': score,
        'passed': score >= passing_score,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_sentence_correction(user_answer: str, correct_sentence: str) -> dict:
    """Grade a single-item sentence correction exercise.

    Compares the user's corrected sentence to the correct version using
    normalized exact match. No Levenshtein tolerance — the user must
    supply the exact corrected sentence (modulo punctuation/case).

    Returns:
        dict with keys: is_correct (bool), user_answer (str), correct_sentence (str).
    """
    is_correct = _normalize_answer(user_answer) == _normalize_answer(correct_sentence)
    return {
        'is_correct': is_correct,
        'user_answer': user_answer,
        'correct_sentence': correct_sentence,
    }


def grade_sentence_correction_multi(
    user_answers: list,
    items: list,
    passing_score: int = PASSING_SCORE_DEFAULT,
) -> dict:
    """Grade a multi-item sentence-correction exercise.

    Each item has its own ``correct_sentence``. The user's answer for the
    item is compared via normalized exact match (same rule as the single-
    item grader). Returns a sentence_completion-style summary so the
    submit endpoint and the client showResults can stay consistent across
    the two text-input lesson types.

    Args:
        user_answers: List of strings, one per item (same order as items).
        items: List of item dicts with at least ``correct_sentence``.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), item_results (list of {incorrect_sentence,
        correct_sentence, user_answer, correct, explanation, error_type,
        error_type_ru, translation}).
    """
    total = len(items or [])
    items = items or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }
    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_value = user_answers[i] if i < len(user_answers) else ''
        canonical = item.get('correct_sentence', '')
        is_correct = _normalize_answer(user_value) == _normalize_answer(canonical)
        if is_correct:
            correct += 1
        item_results.append({
            'incorrect_sentence': item.get('incorrect_sentence', ''),
            'correct_sentence': canonical,
            'user_answer': user_value,
            'correct': is_correct,
            'explanation': item.get('explanation', ''),
            'error_type': item.get('error_type', ''),
            'error_type_ru': item.get('error_type_ru', ''),
            'translation': item.get('translation', ''),
        })
    score = round(correct / total * 100)
    return {
        'score': score,
        'passed': score >= passing_score,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_sentence_completion(
    user_answers: list,
    items: list,
    passing_score: int = PASSING_SCORE_DEFAULT,
) -> dict:
    """Grade a sentence completion exercise.

    Each item has a ``prompt`` (sentence start) and an ``answer`` (expected
    completion). Grading uses exact match after normalization with Levenshtein
    ≤1 tolerance for single-word answers (same rule as fill_blank).

    Args:
        user_answers: List of strings, one per item (same order as items).
        items: List of item dicts with 'prompt' and 'answer' fields.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), item_results (list of {prompt, answer, user_answer, correct}).
    """
    total = len(items or [])
    items = items or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'item_results': [],
        }

    correct = 0
    item_results = []
    for i, item in enumerate(items):
        user_answer = user_answers[i] if i < len(user_answers) else ''
        correct_answer = item.get('answer', '')
        # collocation / transformation modes carry several valid surface forms
        # (e.g. "may have missed" / "might have missed", "reached"/"struck") in
        # acceptable_answers; gap-fill items just have the single canonical answer.
        candidates = [correct_answer] + [
            a for a in (item.get('acceptable_answers') or []) if str(a).strip()
        ]
        is_correct = _strict_text_match(user_answer, candidates)
        if is_correct:
            correct += 1
        item_results.append({
            'prompt': item.get('prompt', ''),
            'answer': correct_answer,
            'user_answer': user_answer,
            'correct': is_correct,
        })

    score = round(correct / total * 100)
    passed = score >= passing_score

    return {
        'score': score,
        'passed': passed,
        'correct_items': correct,
        'total_items': total,
        'item_results': item_results,
    }


def grade_collocation_matching(
    user_pairs: list,
    correct_pairs: list,
    passing_score: int = PASSING_SCORE_DEFAULT,
) -> dict:
    """Grade a collocation matching exercise with partial scoring.

    NOTE (audit E-044): this is **intentionally** partial-scored (fraction of
    correct pairs), unlike ``_grade_matching_pairs`` which is all-or-nothing.
    Collocation drills reward each correct association; the done-today 70%
    threshold is therefore reachable with a partial set here but not in plain
    matching. The divergence is by design — do not "unify" without product sign-off.

    Args:
        user_pairs: List of {phrase, translation} dicts submitted by the user.
        correct_pairs: List of {phrase, translation} dicts from lesson content.

    Returns:
        dict with score (0-100), passed (bool), correct_items (int),
        total_items (int), pair_results (list of {phrase, translation, correct}).
    """
    total = len(correct_pairs or [])
    correct_pairs = correct_pairs or []
    if total == 0:
        return {
            'score': 0,
            'passed': False,
            'correct_items': 0,
            'total_items': 0,
            'pair_results': [],
        }

    # Build lookup: normalized_phrase → normalized_translation from user submission
    user_lookup: dict[str, str] = {}
    for p in (user_pairs or []):
        if isinstance(p, dict):
            phrase_key = _normalize_answer(p.get('phrase', ''))
            translation_val = _normalize_answer(p.get('translation', ''))
            if phrase_key:
                user_lookup[phrase_key] = translation_val

    correct = 0
    pair_results = []
    for item in correct_pairs:
        phrase = item.get('phrase', '')
        translation = item.get('translation', '')
        phrase_key = _normalize_answer(phrase)
        correct_val = _normalize_answer(translation)
        user_val = user_lookup.get(phrase_key, '')
        is_correct = bool(user_val and user_val == correct_val)
        if is_correct:
            correct += 1
        pair_results.append({
            'phrase': phrase,
            'translation': translation,
            'user_translation': item.get('translation', '') if is_correct else (
                next(
                    (p.get('translation', '') for p in (user_pairs or [])
                     if isinstance(p, dict) and _normalize_answer(p.get('phrase', '')) == phrase_key),
                    ''
                )
            ),
            'correct': is_correct,
        })

    score = round(correct / total * 100)
    passed = score >= passing_score

    return {
        'score': score,
        'passed': passed,
        'correct_items': correct,
        'total_items': total,
        'pair_results': pair_results,
    }


def grade_pronunciation_match(recognized_text: str, target_word: str) -> dict:
    """Check whether a Web Speech API transcript matches the target pronunciation word.

    Uses the same normalization as fill_blank grading (strip/lower/punct) plus
    Levenshtein ≤1 tolerance for single-word targets (≥4 chars). Multi-word
    targets require exact match after normalization.

    Returns:
        dict with keys: matched (bool), recognized (str), target (str).
    """
    matched = _strict_text_match(recognized_text, [target_word])
    return {
        'matched': matched,
        'recognized': recognized_text,
        'target': target_word,
    }


def _quiz_text_candidates(row, correct):
    candidates = list(correct) if isinstance(correct, list) else [correct]
    for key in ('alternatives', 'alternative_answers', 'acceptable_answers'):
        values = row.get(key) or []
        if isinstance(values, list):
            candidates.extend(values)
    return candidates


def process_grammar_submission(exercises: list, answers: dict) -> dict:
    """Grade grammar with the same text policy as quiz preview/submit.

    Choice and pair indexes remain discrete values. Reorder tasks still
    require the complete authored words in their authored order.
    """
    correct_count = 0
    feedback = {}
    for i, exercise in enumerate(exercises):
        key = str(i)
        given = answers.get(i, answers.get(key, ''))
        kind = exercise.get('type', '')
        correct = next((exercise[field] for field in
                        ('answer', 'correct_answer', 'correct', 'answers', 'correct_index') if field in exercise), None)
        matches = None
        if kind == 'sentence_builder':
            correct = exercise.get('correct_order', [])
            if isinstance(given, list) and isinstance(correct, list) and correct:
                if all(isinstance(word, str) for word in given + correct):
                    actual = normalize_quiz_answer(' '.join(given))
                    expected = normalize_quiz_answer(' '.join(correct))
                    ok = bool(actual) and actual == expected
                else:
                    ok = given == correct
            else:
                ok = False
        elif kind in ('match', 'matching'):
            pairs = exercise.get('pairs', [])
            raw = given
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (TypeError, ValueError):
                    raw = None
            correct = {_pair_left(pair): _pair_right(pair) for pair in pairs}
            matches = {}
            ok = isinstance(raw, dict) and bool(pairs) and len(raw) == len(pairs)
            if ok:
                try:
                    indexes = {int(left): int(right) for left, right in raw.items()}
                    expected_indexes = set(range(len(pairs)))
                    ok = set(indexes) == expected_indexes and set(indexes.values()) == expected_indexes
                    for left, right in indexes.items():
                        if left not in expected_indexes or right not in expected_indexes:
                            ok = False
                            continue
                        matches[_pair_left(pairs[left])] = _pair_right(pairs[right])
                        if _pair_right(pairs[left]) != _pair_right(pairs[right]):
                            ok = False
                except (TypeError, ValueError, IndexError, KeyError):
                    ok = False
        elif kind in ('true_false', 'tf'):
            expected_bool = _strict_bool(normalize_quiz_answer(correct) if isinstance(correct, str) else correct)
            actual_bool = _strict_bool(normalize_quiz_answer(given) if isinstance(given, str) else given)
            ok = expected_bool is not None and actual_bool is not None and expected_bool == actual_bool
        elif kind == 'multiple_choice' or (kind in ('fill_blank', 'fill-blank', 'fill_in_blank', 'fill-in-blank')
                                           and exercise.get('options')):
            options = exercise.get('options') or []
            explicit_index = ('correct_index' in exercise and not any(
                field in exercise for field in ('answer', 'correct_answer', 'correct', 'answers')))
            correct_index = _quiz_option_index(options, correct, prefer_literal=not explicit_index)
            actual_index = _quiz_option_index(options, given)
            ok = correct_index >= 0 and actual_index >= 0 and correct_index == actual_index
            if correct_index >= 0:
                correct = options[correct_index]
            if actual_index >= 0:
                given = options[actual_index]
        else:
            if kind == 'error_correction':
                correct = exercise.get('correct_sentence', correct)
            candidates = _quiz_text_candidates(exercise, correct)
            if kind == 'error_correction' and exercise.get('full_correct'):
                candidates.append(exercise['full_correct'])
            if kind in ('reorder', 'ordering'):
                actual = normalize_quiz_answer(given)
                ok = bool(actual) and any(actual == normalize_quiz_answer(value)
                                          for value in candidates if value is not None)
            else:
                ok = quiz_text_matches(given, candidates) or matches_completed_blank(given, exercise, correct)
        correct_count += int(bool(ok))
        entry = {
            'status': 'correct' if ok else 'incorrect',
            'message': 'Правильно!' if ok else f'Неправильно. Правильный ответ: {correct}',
            'user_answer': given,
            'correct_answer': correct,
        }
        if matches is not None:
            entry.update(user_matches=matches, correct_matches=correct)
        if exercise.get('explanation'):
            entry['explanation'] = exercise['explanation']
        if exercise.get('alternative_answers'):
            entry['alternative_answers'] = exercise['alternative_answers']
        feedback[key] = entry
    count = len(exercises)
    return {
        'correct_exercises': correct_count,
        'total_exercises': count,
        'correct_answers': correct_count,
        'total_questions': count,
        'score': round(correct_count / count * 100, 2) if count else 0,
        'feedback': feedback,
        'timestamp': datetime.now(UTC).isoformat(),
    }


def _quiz_option_index(options, answer, *, prefer_literal=False):
    """Resolve authored labels before legacy indexes; UI answers remain indexes.

    Numeric option text (years, amounts, counts) is a label when it is an
    authored answer. Submitted numeric values still refer to option indexes,
    with a literal fallback only when that index is outside the offered list.
    """
    if not isinstance(options, list):
        return -1
    labels = [option.strip() if isinstance(option, str) else option for option in options]

    def literal_index():
        if not isinstance(answer, str):
            return -1
        value = answer.strip()
        if value in labels:
            return labels.index(value)
        normalized = normalize_quiz_answer(value)
        matches = [index for index, label in enumerate(labels)
                   if normalized and normalize_quiz_answer(label) == normalized]
        # When punctuation-only differences make labels ambiguous, the
        # learner must select the actual option rather than guess a slot.
        return matches[0] if len(matches) == 1 else -1

    if prefer_literal:
        literal = literal_index()
        if literal >= 0:
            return literal
    if type(answer) is int or (isinstance(answer, str) and answer.isdigit()):
        try:
            index = int(answer)
        except (TypeError, ValueError, OverflowError):
            return literal_index()
        if 0 <= index < len(labels):
            return index
    return literal_index()


def process_quiz_submission(questions: list, answers: dict) -> dict:
    correct_count = 0
    total_count = len(questions)
    feedback = {}

    for i, question in enumerate(questions):
        # Support both integer and string keys (frontend may send '0', '1', etc.)
        user_answer = answers.get(str(i), answers.get(i, ''))
        question_type = question.get('type', 'multiple_choice')

        correct_answer = None
        if 'answer' in question:
            correct_answer = question['answer']
        elif 'correct_answer' in question:
            correct_answer = question['correct_answer']
        elif 'correct' in question:
            correct_answer = question['correct']
        elif 'correct_index' in question:
            correct_answer = question['correct_index']
        elif 'correct_sentence' in question:
            correct_answer = question['correct_sentence']
        is_correct = False

        # Special handling: fill_blank with options should be treated as multiple_choice
        if question_type in ('fill_blank', 'fill-blank', 'fill_in_blank', 'fill-in-blank') and question.get('options'):
            question_type = 'multiple_choice'

        if question_type in ['multiple_choice', 'dialogue_completion', 'listening_choice', 'reading_comprehension']:
            options = question.get('options', [])
            # Explicit correct_index stays an index even when a numeric label
            # with that spelling is offered. Other authored strings prefer the
            # literal option, e.g. correct='2018' maps to label 2018, not index2018.
            explicit_index = ('correct_index' in question and not any(
                field in question for field in ('answer', 'correct_answer', 'correct')
            ))
            user_idx = _quiz_option_index(options, user_answer)
            correct_idx = _quiz_option_index(options, correct_answer, prefer_literal=not explicit_index)
            # Two failed lookups (-1/-1) must never become a correct response.
            is_correct = user_idx >= 0 and correct_idx >= 0 and user_idx == correct_idx


        elif question_type == 'true_false':
            user_bool = _strict_bool(normalize_quiz_answer(user_answer) if isinstance(user_answer, str) else user_answer)
            correct_bool = _strict_bool(normalize_quiz_answer(correct_answer) if isinstance(correct_answer, str) else correct_answer)
            is_correct = (user_bool is not None and correct_bool is not None
                          and user_bool == correct_bool)

        elif question_type in ['fill_in_blank', 'fill-in-blank', 'fill_blank', 'fill-blank', 'translation', 'transformation', 'error_correction']:
            # Quiz text uses exact words after case/punctuation normalization.
            # Authored aliases and contractions are additional accepted forms.

            if correct_answer is None:
                is_correct = False
            else:
                candidates = _quiz_text_candidates(question, correct_answer)
                if question_type == 'error_correction' and question.get('full_correct'):
                    candidates.append(question['full_correct'])
                is_correct = quiz_text_matches(user_answer, candidates) or matches_completed_blank(
                    user_answer, question, correct_answer,
                )


        elif question_type in ['reorder', 'ordering']:
            if correct_answer is None:
                is_correct = False
            else:
                user_normalized = normalize_quiz_answer(user_answer)
                is_correct = bool(user_normalized) and any(
                    user_normalized == normalize_quiz_answer(candidate)
                    for candidate in ([' '.join(map(str, correct_answer))]
                                      if isinstance(correct_answer, list)
                                      else _quiz_text_candidates(question, correct_answer))
                    if candidate is not None)

        elif question_type == 'matching':
            # Server-side validation: client must submit explicit pairs.
            # Legacy clients sending 'completed' (no pairs) are rejected — they
            # cannot prove they actually solved the matching.
            correct_pairs = question.get('pairs', []) or []
            if 'pairs' in question:
                correct_answer = correct_pairs

            user_pairs = None
            raw = user_answer
            # Frontend posts matching answers as a JSON-stringified dict
            # ({left_value: right_value, ...}); decode into pairs here so
            # the strict grader can compare keys against ``correct_pairs``.
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (ValueError, TypeError):
                    raw = None
            if isinstance(raw, list):
                user_pairs = raw
            elif isinstance(raw, dict):
                if isinstance(raw.get('pairs'), list):
                    user_pairs = raw['pairs']
                else:
                    user_pairs = [
                        {'left': k, 'right': v} for k, v in raw.items()
                    ]
            else:
                pairs_field = answers.get(f'{i}_pairs', answers.get(f'{str(i)}_pairs'))
                if isinstance(pairs_field, list):
                    user_pairs = pairs_field

            if user_pairs is None:
                is_correct = False
            else:
                is_correct = _grade_matching_pairs(user_pairs, correct_pairs)

        else:
            # Unsupported/malformed content must not award a correct answer.
            is_correct = False

        display_user = user_answer
        display_correct = correct_answer
        if question_type in ('multiple_choice', 'dialogue_completion', 'listening_choice', 'reading_comprehension'):
            opts = question.get('options', [])
            # Feedback must use the same resolved labels as grading, including
            # numeric literal keys. Reinterpreting '1' as an index here would
            # show a different answer from the one just marked correct.
            if correct_idx >= 0:
                display_correct = opts[correct_idx]
            if user_idx >= 0:
                display_user = opts[user_idx]

        # Формируем обратную связь
        if is_correct:
            correct_count += 1
            feedback[str(i)] = {
                'status': 'correct',
                'message': 'Правильно!',
                'user_answer': display_user,
                'correct_answer': display_correct
            }
        else:
            # Определяем текст правильного ответа для отображения
            if (
                question_type in ('multiple_choice', 'dialogue_completion', 'listening_choice', 'reading_comprehension')
                and 'options' in question
            ):
                correct_text = str(display_correct)
                user_text = str(display_user)

            elif question_type == 'true_false':
                correct_bool = _strict_bool(correct_answer)
                user_bool = _strict_bool(user_answer)
                correct_text = ('Не указан' if correct_bool is None else
                                ('Правда' if correct_bool else 'Ложь'))
                user_text = (str(user_answer) if user_bool is None else
                             ('Правда' if user_bool else 'Ложь'))

            elif question_type in ['fill_in_blank', 'fill-in-blank', 'translation']:
                user_text = str(user_answer)

                if isinstance(correct_answer, list):
                    if len(correct_answer) == 1:
                        correct_text = correct_answer[0]
                    else:
                        correct_text = f"Возможные ответы: {', '.join(correct_answer)}"
                elif question_type == 'translation' and 'alternative_answers' in question:
                    all_answers = [str(correct_answer)]
                    if question['alternative_answers']:
                        all_answers.extend(question['alternative_answers'])
                    correct_text = ' / '.join(all_answers)
                else:
                    correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'

            elif question_type == 'reorder':
                correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'
                user_text = str(user_answer)

            elif question_type == 'matching':
                # For matching questions, format pairs as readable text.
                # Pair-field shapes vary across content; module-level
                # _pair_left/_pair_right handle left/right, english/russian and
                # word/translation so this summary doesn't degrade to bare
                # " → " arrows.
                pairs_src = None
                if isinstance(correct_answer, list):
                    pairs_src = correct_answer
                elif 'pairs' in question:
                    pairs_src = question['pairs']

                if pairs_src is not None:
                    formatted = [
                        f"{_pair_left(p)} → {_pair_right(p)}"
                        for p in pairs_src if isinstance(p, dict)
                        and (_pair_left(p) or _pair_right(p))
                    ]
                    correct_text = ', '.join(formatted) if formatted else 'Не указан'
                else:
                    correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'
                user_text = str(user_answer)

            else:
                correct_text = str(correct_answer) if correct_answer is not None else 'Не указан'
                user_text = str(user_answer)

            feedback[str(i)] = {
                'status': 'incorrect',
                'message': f'Неправильно. Правильный ответ: {correct_text}',
                'user_answer': user_text,
                'correct_answer': correct_text
            }

    score = round((correct_count / total_count) * 100, 2) if total_count > 0 else 0

    return {
        'correct_answers': correct_count,
        'total_questions': total_count,
        'score': score,
        'feedback': feedback,
        'answers': answers,
        'timestamp': datetime.now(UTC).isoformat()
    }


def process_matching_submission(pairs: list, user_matches: dict) -> dict:
    correct_count = 0
    total_count = len(pairs)
    feedback = {}
    incorrect_matches = {}

    for i, pair in enumerate(pairs):
        left = _pair_left(pair)
        right = _pair_right(pair)

        # Two formats accepted: index-based {'0': 1} or value-based {'hello': 'привет'}
        # None-aware lookup: a valid index 0 must not be treated as "missing".
        user_match_index = user_matches.get(str(i))
        if user_match_index is None:
            user_match_index = user_matches.get(i)

        if user_match_index is not None:
            try:
                user_match_index = int(user_match_index)
                user_matched_right = _pair_right(pairs[user_match_index]) if 0 <= user_match_index < len(pairs) else None
            except (ValueError, IndexError):
                user_matched_right = None
        else:
            user_matched_right = user_matches.get(left)

        is_correct = user_matched_right == right

        if is_correct:
            correct_count += 1
            feedback[i] = {
                'status': 'correct',
                'message': 'Правильно!',
                'user_match': user_matched_right,
                'correct_match': right
            }
        else:
            feedback[i] = {
                'status': 'incorrect',
                'message': f'Неправильно. \"{left}\" должно соответствовать \"{right}\"',
                'user_match': user_matched_right,
                'correct_match': right
            }
            incorrect_matches[str(i)] = {
                'user': user_matched_right,
                'correct': right
            }

    score = round((correct_count / total_count) * 100) if total_count > 0 else 0

    return {
        'correct_matches': correct_count,
        'total_pairs': total_count,
        'correct_pairs': correct_count,  # Alias
        'correct_answers': correct_count,  # Keep for backward compatibility
        'total_questions': total_count,  # Keep for backward compatibility
        'score': score,
        'feedback': feedback,
        'incorrect_matches': incorrect_matches,
        'timestamp': datetime.now(UTC).isoformat()
    }


def process_final_test_submission(
    questions: list,
    user_answers: dict,
    passing_score: int = PASSING_SCORE_FINAL_TEST,
) -> dict:
    """Grade final questions identically to ordinary quiz questions.

    Only the completion policy and historic feedback shape differ: final
    tests require 75% by default and expose ``is_correct`` per question.
    """
    result = process_quiz_submission(questions, user_answers)
    return {
        'score': result['score'],
        'correct_answers': result['correct_answers'],
        'total_questions': result['total_questions'],
        'passed': result['score'] >= passing_score,
        'feedback': {
            key: {
                'is_correct': checked['status'] == 'correct',
                'user_answer': checked['user_answer'],
                'correct_answer': checked['correct_answer'],
            }
            for key, checked in result['feedback'].items()
        },
    }
