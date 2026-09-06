#!/usr/bin/env python3
"""Lesson audit item 18: the second flashcard lesson moves from position 14 to 9.

Lessons 3-13 drill all twenty module words, but only the first ten were in
SRS until lesson 14 introduced the rest (36-42 % of the collocation,
audio-fill-blank and ordering items used only second-deck words; shadow
reading 94 %). With the deck at position 9, both halves are in SRS before
the dense listening / writing practice, and six lessons still separate the
two decks so the learning inflow does not double on one day.

New layout: 1 vocabulary, 2 card, 3 collocation_matching, 4 grammar,
5 sentence_completion, 6 reading, 7 listening_immersion, 8 listening_quiz,
9 card, 10 audio_fill_blank, 11 shadow_reading, 12 dictation,
13 dialogue_completion_quiz, 14 ordering_quiz, 15 translation,
16 translation_quiz, 17 writing_prompt, 18 final_test.

What changes: only the position fields. In ``module_completed/fixed`` the
lesson's ``number``, ``order`` and ``id`` (all equal by convention) and its
place in the ``lessons`` array; in the database ``lessons.number`` and
``lessons."order"`` (equal for all 1 548 rows). Content, titles, XP, ids and
grammar-topic links are untouched. ``(module_id, number)`` is unique, so the
SQL renumbers through a +100 offset.

    python scripts/move_second_card_lesson.py                  # dry run
    python scripts/move_second_card_lesson.py --write          # patch JSON
    python scripts/move_second_card_lesson.py --sql local_exports
        # -> item18_card2_position_1_check.sql / _2_apply.sql / _3_rollback.sql

Idempotent: a module whose lesson 9 is already the deck is skipped.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / 'module_completed' / 'fixed'
CARD_TYPES = ('flashcards', 'card')
OLD_DECK_POSITION = 14
NEW_DECK_POSITION = 9
SHIFTED = range(NEW_DECK_POSITION, OLD_DECK_POSITION)  # 9..13 move to 10..14
OFFSET = 100


def plan_module(path: Path, data: dict) -> tuple[dict, bool, list[str]]:
    """Return (patched copy, changed, warnings) for one module file."""
    warnings: list[str] = []
    patched = copy.deepcopy(data)
    module = patched['module']
    by_number = {lesson['number']: lesson for lesson in module['lessons']}
    deck = by_number.get(OLD_DECK_POSITION)
    ninth = by_number.get(NEW_DECK_POSITION)
    if ninth is not None and ninth['type'] in CARD_TYPES:
        return patched, False, warnings  # already moved
    if deck is None or deck['type'] not in CARD_TYPES:
        warnings.append(f'{path.name}: lesson {OLD_DECK_POSITION} is not a card lesson - skipped')
        return patched, False, warnings
    if ninth is None or ninth['type'] != 'audio_fill_blank':
        warnings.append(f'{path.name}: lesson {NEW_DECK_POSITION} is {ninth and ninth["type"]!r}, expected audio_fill_blank - skipped')
        return patched, False, warnings
    for lesson in module['lessons']:
        number = lesson['number']
        if number in SHIFTED:
            new_number = number + 1
        elif number == OLD_DECK_POSITION:
            new_number = NEW_DECK_POSITION
        else:
            continue
        lesson['number'] = new_number
        if 'order' in lesson:
            lesson['order'] = new_number
        if lesson.get('id') == number:
            lesson['id'] = new_number
    module['lessons'].sort(key=lambda lesson: lesson['number'])
    return patched, True, warnings


def _module_subselect(level: str, number: int) -> str:
    return (
        '(SELECT m.id FROM modules m JOIN cefr_levels cl ON cl.id = m.level_id '
        f"WHERE cl.code = '{level}' AND m.number = {number})"
    )


def emit_sql(coords: list[tuple[str, int]], out_dir: Path) -> None:
    apply: list[str] = []
    rollback: list[str] = []
    checks: list[str] = []
    for level, number in coords:
        sub = _module_subselect(level, number)
        old_layout = (
            f"EXISTS (SELECT 1 FROM lessons a WHERE a.module_id = {sub} AND a.number = {OLD_DECK_POSITION} AND a.type = 'card') "
            f"AND EXISTS (SELECT 1 FROM lessons b WHERE b.module_id = {sub} AND b.number = {NEW_DECK_POSITION} AND b.type = 'audio_fill_blank')"
        )
        new_layout = (
            f"EXISTS (SELECT 1 FROM lessons a WHERE a.module_id = {sub} AND a.number = {NEW_DECK_POSITION} AND a.type = 'card') "
            f"AND EXISTS (SELECT 1 FROM lessons b WHERE b.module_id = {sub} AND b.number = {NEW_DECK_POSITION + 1} AND b.type = 'audio_fill_blank')"
        )
        checks.append(f'SELECT 1 WHERE {old_layout}')
        # apply: 9..14 -> 109..114 ; 109..113 -> 10..14 ; 114 -> 9
        apply.append(
            f'UPDATE lessons l SET number = l.number + {OFFSET}, "order" = l."order" + {OFFSET} '
            f'WHERE l.module_id = {sub} AND l.number BETWEEN {NEW_DECK_POSITION} AND {OLD_DECK_POSITION} AND {old_layout};'
        )
        apply.append(
            f'UPDATE lessons l SET number = l.number - {OFFSET - 1}, "order" = l."order" - {OFFSET - 1} '
            f'WHERE l.module_id = {sub} AND l.number BETWEEN {OFFSET + NEW_DECK_POSITION} AND {OFFSET + OLD_DECK_POSITION - 1};'
        )
        apply.append(
            f'UPDATE lessons l SET number = {NEW_DECK_POSITION}, "order" = {NEW_DECK_POSITION} '
            f"WHERE l.module_id = {sub} AND l.number = {OFFSET + OLD_DECK_POSITION} AND l.type = 'card';"
        )
        # rollback: 9..14 -> 109..114 ; 110..114 -> 9..13 ; 109 -> 14
        rollback.append(
            f'UPDATE lessons l SET number = l.number + {OFFSET}, "order" = l."order" + {OFFSET} '
            f'WHERE l.module_id = {sub} AND l.number BETWEEN {NEW_DECK_POSITION} AND {OLD_DECK_POSITION} AND {new_layout};'
        )
        rollback.append(
            f'UPDATE lessons l SET number = l.number - {OFFSET + 1}, "order" = l."order" - {OFFSET + 1} '
            f'WHERE l.module_id = {sub} AND l.number BETWEEN {OFFSET + NEW_DECK_POSITION + 1} AND {OFFSET + OLD_DECK_POSITION};'
        )
        rollback.append(
            f'UPDATE lessons l SET number = {OLD_DECK_POSITION}, "order" = {OLD_DECK_POSITION} '
            f"WHERE l.module_id = {sub} AND l.number = {OFFSET + NEW_DECK_POSITION} AND l.type = 'card';"
        )
    header = (
        '-- Lesson audit item 18: the second flashcard lesson moves from position 14 to 9;\n'
        '-- lessons 9-13 shift to 10-14. Only lessons.number and lessons."order" change,\n'
        '-- through a +100 offset because (module_id, number) is unique. Keyed on level\n'
        '-- code + module number + the old layout, never on ids. Idempotent.\n'
        '-- Generated by scripts/move_second_card_lesson.py; the JSON source was patched by the same run.\n'
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'item18_card2_position_1_check.sql').write_text(
        header
        + f'-- Expected before apply: {len(checks)} modules in the old layout; after apply: 0 old, {len(checks)} new.\n'
        + 'SELECT count(*) AS modules_in_old_layout FROM (' + ' UNION ALL '.join(checks) + ') s;\n'
        + "SELECT count(*) AS modules_in_new_layout FROM modules m WHERE EXISTS (SELECT 1 FROM lessons l WHERE l.module_id = m.id AND l.number = 9 AND l.type = 'card') AND EXISTS (SELECT 1 FROM lessons l WHERE l.module_id = m.id AND l.number = 10 AND l.type = 'audio_fill_blank') AND EXISTS (SELECT 1 FROM lessons l WHERE l.module_id = m.id AND l.number = 14 AND l.type = 'ordering_quiz');\n"
        + 'SELECT count(*) AS lessons_with_order_mismatch FROM lessons WHERE "order" <> number;\n',
        encoding='utf-8',
    )
    (out_dir / 'item18_card2_position_2_apply.sql').write_text(
        header + '-- BEGIN; \\i item18_card2_position_2_apply.sql  -- then run _1_check.sql, COMMIT or ROLLBACK;\n\n'
        + '\n'.join(apply) + '\n',
        encoding='utf-8',
    )
    (out_dir / 'item18_card2_position_3_rollback.sql').write_text(
        header + '-- Reverses _2_apply.sql; safe only after it was committed.\n\n' + '\n'.join(rollback) + '\n',
        encoding='utf-8',
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--write', action='store_true', help='patch the JSON files in place')
    parser.add_argument('--sql', metavar='DIR', help='write check/apply/rollback SQL into DIR')
    parser.add_argument('--module-dir', default=str(MODULE_DIR))
    args = parser.parse_args()

    files = sorted(Path(args.module_dir).glob('*.json'))
    if not files:
        print(f'no module files under {args.module_dir}', file=sys.stderr)
        return 2
    changed: list[tuple[str, int]] = []
    warnings: list[str] = []
    for path in files:
        data = json.loads(path.read_text(encoding='utf-8'))
        patched, did_change, warn = plan_module(path, data)
        warnings.extend(warn)
        if did_change:
            module = data['module']
            changed.append((module['level'], module['order']))
            if args.write:
                path.write_text(json.dumps(patched, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'modules scanned: {len(files)}; modules to move: {len(changed)}')
    for w in warnings:
        print('WARNING', w)
    if args.sql:
        emit_sql(changed, Path(args.sql))
        print(f'SQL written to {args.sql}')
    if not args.write:
        print('dry run - pass --write to patch the JSON')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
