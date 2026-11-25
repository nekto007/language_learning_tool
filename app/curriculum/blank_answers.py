"""Derive the exact written response for unambiguous text cloze items."""
# ruff: noqa: RUF001 -- authoring conventions and learner instructions use Russian text.

import re
import unicodedata

from app.curriculum.answer_review_edits import answer_aliases
from app.utils.normalization import EXPECTED_ZERO_ARTICLE_MARKERS

BLANK_TYPES = frozenset({'fill_blank', 'fill-blank', 'fill_in_blank', 'fill-in-blank'})
_GAP = re.compile(r'_{2,}(?:[ \t]+_{2,})*')
_HINT = re.compile(r'\s*\([^()]*\)')
_BOUNDARY = re.compile(r'(?<=[.!?…])(?:["”»])?(?:[ \t]*[—–][ \t]*|[ \t]+(?:-[ \t]+)?)|\n+')
_ABBREVIATION = re.compile(r'\b(?:Mr|Mrs|Ms|Dr|St|Prof|e\.g|i\.e|a\.m|p\.m)\.', re.IGNORECASE)
_LABEL = re.compile(r'^(?:Вариант (?:BrE|AmE)|Заполни(?:те)? пропуск|Вставь(?:те)? пропуск)\s*:\s*', re.IGNORECASE)
_ONLY_FORMAT = re.compile(r'\b(?:только|одно слово|одним словом|one word|only)\b', re.IGNORECASE)
_FORMAT = 'Можно также написать фразу с заполненным пропуском целиком.'
_APOSTROPHES = str.maketrans({'’': "'", '‘': "'", 'ʼ': "'", '＇': "'", '′': "'"})


def normalize_completed_blank(text: str) -> str:
    """Ignore case and punctuation while retaining words and apostrophes."""
    text = unicodedata.normalize('NFKC', text).translate(_APOSTROPHES).lower()
    return ' '.join(''.join(
        ' ' if char != "'" and unicodedata.category(char).startswith('P') else char
        for char in text
    ).split())


def has_blank_gap(text: object) -> bool:
    """Recognize an underscore gap using the same marker as the grader."""
    return isinstance(text, str) and _GAP.search(text) is not None


def _response_template(prompt: str) -> tuple[str, str]:
    # Inline parentheses after a gap and trailing parentheticals are author
    # hints. In particular a trailing hint can show a different blank.
    prompt = _HINT.sub(
        lambda hint: '' if (
            _GAP.search(prompt[:hint.start()])
            and (_GAP.search(prompt[:hint.start()].split()[-1])
                 or not prompt[hint.end():].strip(' .?!'))
        ) else hint.group(),
        prompt,
    )
    context = prompt.strip()
    if prompt.count('→') > 1:
        return '', ''
    if '→' in prompt:
        left, prompt = prompt.split('→')
        if _GAP.search(left):
            return '', ''
    protected = _ABBREVIATION.sub(lambda match: match.group().replace('.', '\x00'), prompt)
    targets = [part.replace('\x00', '.').strip() for part in _BOUNDARY.split(protected) if _GAP.search(part)]
    if len(targets) != 1 or len(list(_GAP.finditer(targets[0]))) != 1:
        return '', ''
    return _LABEL.sub('', targets[0]).strip(), context


def _written_variants(sentence: str) -> set[str]:
    from app.curriculum.grading import written_contraction_forms

    written = sentence.translate(_APOSTROPHES).lower()
    return {normalize_completed_blank(value) for value in written_contraction_forms(written)}


def _is_complete_form(key: str, left: str, right: str) -> bool:
    # A form already carrying a prompt boundary must never be inserted as
    # filler, even if its other boundary differs from the displayed sentence.
    return bool((left and (key == left or key.startswith(left + ' ')))
                or (right and (key == right or key.endswith(' ' + right))))


def completed_blank_answers(
    row: dict, canonical: object, *, kind: str | None = None, legacy_context: bool = False,
) -> tuple[str, ...]:
    """Build exact completions for the primary key and identifiable fragment aliases."""
    if (kind or row.get('type')) not in BLANK_TYPES or row.get('options'):
        return ()
    keys = canonical if isinstance(canonical, list) else [canonical]
    keys = [key for key in keys if isinstance(key, str) and key.strip()]
    if not keys:
        return ()
    # These fields are alternative displays in older material. A conflict
    # between populated templates must not silently select a new target.
    raw_prompts = [
        value
        for field in ('question', 'prompt', 'sentence', 'text', 'text_with_gap')
        if isinstance(value := row.get(field), str) and _GAP.search(value)
    ]
    prompts = [_response_template(value) for value in raw_prompts]
    templates = {template for template, _ in prompts}
    if len(templates) != 1 or not (template := templates.pop()):
        return ()
    primary_length = len(normalize_completed_blank(keys[0]).split())
    completed = set()
    renderings = {template}
    if legacy_context:
        renderings.update(context for context in [*raw_prompts, *(context for _, context in prompts)]
                          if len(list(_GAP.finditer(context))) == 1)
    for rendered in renderings:
        gap = _GAP.search(rendered)
        before, after = rendered[:gap.start()], rendered[gap.end():]
        left, right = normalize_completed_blank(before), normalize_completed_blank(after)
        if not left and not right:
            continue
        slots = len(gap.group().split())
        for value in dict.fromkeys([*keys, *answer_aliases(row)]):
            filler = value.strip()
            if filler.lower() in EXPECTED_ZERO_ARTICLE_MARKERS:
                if slots == 1:
                    completed.update(_written_variants(before + after))
                continue
            key = normalize_completed_blank(filler)
            length = len(key.split())
            if not key or _is_complete_form(key, left, right) or _BOUNDARY.search(filler):
                continue
            # A long or sentence-shaped authored alias is still accepted directly.
            if value != keys[0] and (length > max(2, primary_length + 1) or filler.endswith(('.', '!', '?'))):
                continue
            if slots > 1 and length != slots:
                continue
            completed.update(_written_variants(before + filler + after))
    return tuple(sorted(completed - {''}))


def canonical_blank_key(row: dict) -> object:
    return next((row[field] for field in ('answer', 'correct_answer', 'correct', 'answers') if field in row), None)


def matches_completed_blank(
    answer: object, row: dict, canonical: object, *, kind: str | None = None, legacy_context: bool = False,
) -> bool:
    if not isinstance(answer, str):
        return False
    return normalize_completed_blank(answer) in completed_blank_answers(
        row, canonical, kind=kind, legacy_context=legacy_context,
    )


def has_blank_format_conflict(row: dict) -> bool:
    return bool(_ONLY_FORMAT.search(row.get('instruction') or ''))


def _written_instruction(row: dict) -> str:
    instruction = row.get('instruction') or ''
    if not instruction:
        return 'Впиши пропущенную часть. ' + _FORMAT
    if has_blank_format_conflict(row):
        instruction = 'Для краткого ответа: ' + instruction
    return instruction + ' ' + _FORMAT


def blank_instruction(row: dict, *, kind: str | None = None, canonical: object = None) -> str:
    key = canonical if canonical is not None else canonical_blank_key(row)
    return _written_instruction(row) if completed_blank_answers(row, key, kind=kind) else row.get('instruction') or ''


def legacy_blank_row(row: dict, *, feedback: bool = False) -> dict:
    """Project copy for legacy web forms, which already render the answer key."""
    if row.get('type') not in BLANK_TYPES:
        return row
    shown = {**row, 'type': 'fill_blank'}
    shown.pop('completed_blanks', None)
    completed = completed_blank_answers(row, canonical_blank_key(row))
    if not completed:
        return shown
    shown['instruction'] = _written_instruction(row)
    if feedback:
        shown['completed_blanks'] = completed
    return shown
