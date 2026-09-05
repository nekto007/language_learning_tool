#!/usr/bin/env python3
"""Lesson audit item 10: card lessons «часть 1 / часть 2», even split, no trailing dots.

Facts (prod copy, 2026-09-05): the two flashcard lessons of a module (numbers 2
and 14) never share a word, yet 83/86 second lessons were titled «(повторение)»;
26 modules split the deck unevenly (5+15, 7+13, 8+12, 9+11); 23 module titles end
with a dot and 391 lesson titles inherit it («Карточки: Тема. (повторение)»).

What this script does to ``module_completed/fixed/*.json`` (the import source):

1. strips the trailing dot from the module title and from every lesson title
   that embeds it;
2. renames the two flashcard lessons to «<base>, часть 1» / «<base>, часть 2»
   (base = the first lesson's title without the «(повторение)» suffix);
3. evens the deck: the first k cards of lesson 14 move to the end of lesson 2
   (ids stay ascending across the two lessons) so the split is 10/10, or 10/11
   for the two 21-word modules. Card ids and order are untouched.

The DB is the runtime source, so the same change ships as SQL keyed on content
coordinates (level code + module number + lesson number + old title / the exact
old deck), never on ids:

    python scripts/rebalance_card_lessons.py                  # dry run, summary
    python scripts/rebalance_card_lessons.py --write          # patch the JSON
    python scripts/rebalance_card_lessons.py --sql local_exports
        # -> item10_card_lessons_1_check.sql / _2_apply.sql / _3_rollback.sql

Idempotent: a second run finds nothing to change.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / 'module_completed' / 'fixed'
CARD_TYPES = ('flashcards', 'card')
REPEAT_SUFFIX_RE = re.compile(r'\s*\(повторение\)\s*$')
PART_SUFFIX_RE = re.compile(r',\s*часть\s+[12]\s*$|\s*\((первая|вторая) часть\)\s*$')


def _strip_trailing_dot(title: str) -> str:
    return re.sub(r'\.+\s*$', '', title).rstrip()


def _card_base_title(title: str) -> str:
    return PART_SUFFIX_RE.sub('', REPEAT_SUFFIX_RE.sub('', title)).rstrip()


class Change:
    """One module's planned edits: old/new titles and old/new card decks."""

    def __init__(self, path: Path, module: dict):
        self.path = path
        self.level = module['level']
        self.number = module['order']
        self.module_title_old = module['title']
        self.module_title_new = _strip_trailing_dot(module['title'])
        self.lesson_titles: list[tuple[int, str, str]] = []  # (number, old, new)
        self.decks: list[tuple[int, list, list]] = []  # (number, old_cards, new_cards)

    @property
    def touched(self) -> bool:
        return bool(self.module_title_old != self.module_title_new or self.lesson_titles or self.decks)


def plan_module(path: Path, data: dict) -> tuple[dict, Change, list[str]]:
    """Return (patched copy, change record, warnings) for one module file."""
    warnings: list[str] = []
    patched = copy.deepcopy(data)
    module = patched['module']
    change = Change(path, module)
    old_title, new_title = change.module_title_old, change.module_title_new
    module['title'] = new_title

    # 1. dots inherited from the module title
    for lesson in module['lessons']:
        title = lesson['title']
        fixed = title.replace(old_title, new_title) if old_title != new_title else title
        if fixed != title:
            lesson['title'] = fixed

    # 2 + 3. the two flashcard lessons
    cards = sorted((lesson for lesson in module['lessons'] if lesson['type'] in CARD_TYPES), key=lambda lesson: lesson['number'])
    if len(cards) != 2:
        warnings.append(f'{path.name}: expected 2 card lessons, found {len(cards)} - skipped')
    else:
        first, second = cards
        base = _card_base_title(first['title'])
        base_second = _card_base_title(second['title'])
        if base_second != base:
            if REPEAT_SUFFIX_RE.search(second['title']) or re.search(r'(?i)повторение\s*$', second['title']):
                # «Экология (повторение)» next to «Экология и природа», or A1_1's bare
                # «Карточки: Повторение»: the decks never overlap, so the label lies
                # and the first deck's theme names both parts.
                warnings.append(f'{path.name}: «(повторение)» title differs ({second["title"]!r}); using {base!r}')
                base_second = base
            else:
                # Authored distinct decks (C1_14: Formal/Business vs Informal/Clichés)
                # keep their own themes, only the part suffix is unified.
                warnings.append(f'{path.name}: distinct authored card titles kept ({base!r} / {base_second!r})')
        first['title'] = f'{base}, часть 1'
        second['title'] = f'{base_second}, часть 2'
        deck1, deck2 = first['content']['cards'], second['content']['cards']
        total = len(deck1) + len(deck2)
        target1 = total // 2
        if len(deck1) < target1:
            k = target1 - len(deck1)
            moved, rest = deck2[:k], deck2[k:]
            new1, new2 = deck1 + moved, rest
        elif len(deck1) > target1:
            k = len(deck1) - target1
            new1, new2 = deck1[:-k], deck1[-k:] + deck2
        else:
            new1, new2 = deck1, deck2
        if new1 != deck1:
            change.decks.append((first['number'], deck1, new1))
            change.decks.append((second['number'], deck2, new2))
            first['content']['cards'] = new1
            second['content']['cards'] = new2

    for old_lesson, new_lesson in zip(data['module']['lessons'], module['lessons'], strict=True):
        if old_lesson['title'] != new_lesson['title']:
            change.lesson_titles.append((new_lesson['number'], old_lesson['title'], new_lesson['title']))
        t = new_lesson['title']
        if t.endswith('.') or '. (' in t:
            warnings.append(f'{path.name}: lesson {new_lesson["number"]} still has a dot: {t!r}')
    return patched, change, warnings


def _dollar(text: str) -> str:
    """Dollar-quoted SQL literal (titles carry quotes and Cyrillic)."""
    tag = 'q'
    while f'${tag}$' in text:
        tag += 'q'
    return f'${tag}${text}${tag}$'


def _module_subselect(change: Change) -> str:
    return (
        '(SELECT m.id FROM modules m JOIN cefr_levels cl ON cl.id = m.level_id '
        f"WHERE cl.code = '{change.level}' AND m.number = {change.number})"
    )


def emit_sql(changes: list[Change], out_dir: Path) -> None:
    """Write check / apply / rollback files keyed on coordinates, never ids."""
    apply: list[str] = []
    rollback: list[str] = []
    check_modules: list[str] = []
    check_titles: list[str] = []
    check_decks: list[str] = []
    for ch in changes:
        sub = _module_subselect(ch)
        if ch.module_title_old != ch.module_title_new:
            where = f"WHERE m.level_id = (SELECT id FROM cefr_levels WHERE code = '{ch.level}') AND m.number = {ch.number}"
            apply.append(f'UPDATE modules m SET title = {_dollar(ch.module_title_new)} {where} AND m.title = {_dollar(ch.module_title_old)};')
            rollback.append(f'UPDATE modules m SET title = {_dollar(ch.module_title_old)} {where} AND m.title = {_dollar(ch.module_title_new)};')
            check_modules.append(f'SELECT 1 FROM modules m {where} AND m.title = {_dollar(ch.module_title_old)}')
        for number, old, new in ch.lesson_titles:
            where = f'WHERE l.module_id = {sub} AND l.number = {number}'
            apply.append(f'UPDATE lessons l SET title = {_dollar(new)} {where} AND l.title = {_dollar(old)};')
            rollback.append(f'UPDATE lessons l SET title = {_dollar(old)} {where} AND l.title = {_dollar(new)};')
            check_titles.append(f'SELECT 1 FROM lessons l {where} AND l.title = {_dollar(old)}')
        for number, old_cards, new_cards in ch.decks:
            where = f"WHERE l.module_id = {sub} AND l.number = {number} AND l.type IN ('card', 'flashcards')"
            new_json = json.dumps(new_cards, ensure_ascii=False)
            old_json = json.dumps(old_cards, ensure_ascii=False)
            # Exact-deck predicates: an editorial change of the same length made
            # between preflight and apply must not be overwritten, and rollback
            # must not clobber edits made after apply (Codex review of item 10).
            apply.append(
                f"UPDATE lessons l SET content = jsonb_set(l.content::jsonb, '{{cards}}', {_dollar(new_json)}::jsonb)::json "
                f"{where} AND l.content::jsonb->'cards' = {_dollar(old_json)}::jsonb;"
            )
            rollback.append(
                f"UPDATE lessons l SET content = jsonb_set(l.content::jsonb, '{{cards}}', {_dollar(old_json)}::jsonb)::json "
                f"{where} AND l.content::jsonb->'cards' = {_dollar(new_json)}::jsonb;"
            )
            check_decks.append(f"SELECT 1 FROM lessons l {where} AND l.content::jsonb->'cards' = {_dollar(old_json)}::jsonb")

    def _count(rows: list[str], label: str) -> str:
        if not rows:
            return f'SELECT 0 AS {label};'
        return f'SELECT count(*) AS {label} FROM (' + ' UNION ALL '.join(rows) + ') s;'

    header = (
        '-- Lesson audit item 10: card lessons «часть 1 / часть 2», even 10/10 split,\n'
        '-- no trailing dots in module/lesson titles. Generated by\n'
        '-- scripts/rebalance_card_lessons.py from module_completed/fixed (the import\n'
        '-- source, patched by the same run). Keyed on level code + module number +\n'
        '-- lesson number + old title / old deck, never on ids. Idempotent.\n'
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'item10_card_lessons_1_check.sql').write_text(
        header
        + f'-- Expected: modules {len(check_modules)}, lesson titles {len(check_titles)}, decks {len(check_decks)}.\n'
        + '-- Each count must equal the expected number BEFORE apply (and 0 after).\n'
        + _count(check_modules, 'modules_matching_old_title') + '\n'
        + _count(check_titles, 'lessons_matching_old_title') + '\n'
        + _count(check_decks, 'decks_matching_old_cards') + '\n',
        encoding='utf-8',
    )
    (out_dir / 'item10_card_lessons_2_apply.sql').write_text(
        header + '-- BEGIN; \\i item10_card_lessons_2_apply.sql  -- compare UPDATE counts, then COMMIT or ROLLBACK;\n\n'
        + '\n'.join(apply) + '\n',
        encoding='utf-8',
    )
    (out_dir / 'item10_card_lessons_3_rollback.sql').write_text(
        header + '-- Reverses _2_apply.sql; safe to run only after it was committed.\n\n' + '\n'.join(rollback) + '\n',
        encoding='utf-8',
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--write', action='store_true', help='patch the JSON files in place')
    parser.add_argument('--sql', metavar='DIR', help='write check/apply/rollback SQL into DIR')
    parser.add_argument('--module-dir', default=str(MODULE_DIR))
    args = parser.parse_args()

    module_dir = Path(args.module_dir)
    files = sorted(module_dir.glob('*.json'))
    if not files:
        print(f'no module files under {module_dir}', file=sys.stderr)
        return 2

    changes: list[Change] = []
    warnings: list[str] = []
    for path in files:
        data = json.loads(path.read_text(encoding='utf-8'))
        patched, change, warn = plan_module(path, data)
        warnings.extend(warn)
        if change.touched:
            changes.append(change)
            if args.write:
                path.write_text(json.dumps(patched, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    modules_dotted = sum(1 for c in changes if c.module_title_old != c.module_title_new)
    titles = sum(len(c.lesson_titles) for c in changes)
    decks = sum(len(c.decks) for c in changes) // 2
    print(f'modules scanned: {len(files)}; module titles with a dot: {modules_dotted}; '
          f'lesson titles to change: {titles}; modules to rebalance: {decks}')
    for c in changes:
        for number, old_cards, new_cards in c.decks:
            print(f'  {c.level} M{c.number} L{number}: {len(old_cards)} -> {len(new_cards)} cards')
    for w in warnings:
        print('WARNING', w)
    if args.sql:
        emit_sql(changes, Path(args.sql))
        print(f'SQL written to {args.sql}')
    if not args.write:
        print('dry run - pass --write to patch the JSON')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
