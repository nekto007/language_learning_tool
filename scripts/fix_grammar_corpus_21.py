#!/usr/bin/env python3
"""Lesson audit item 21 — corpus-wide grammar content pass.

Three defect classes found in item 20 measured across all 86 grammar
topics and fixed where the data allows:

* **B — reorders with a movable adverbial** (87 items accept one order):
  authored ``alternatives`` with the fronted / mid-position order of the
  same tokens, only where that order is natural (questions, ``always`` /
  ``never``, inverted and conditional sentences are left alone);
* **C — hintless verb blanks in tense topics** (124 flagged, 77 real): the
  base verb is added in brackets after the blank («he ___ (conduct) the
  interview»), so the item tests the tense form, not the lexical guess;
  blanks whose target IS the grammar word (used to, have to, has been,
  Having …) keep no hint;
* **theory placeholder cells** (13 in three modules): «Structure» labels
  dropped, «Question»/«Pattern» cells replaced by the pattern they hid.

Delivery reuses the item-20 machinery (``scripts/fix_grammar_topics_3.py``):
snapshot in ``local_exports/grammar_corpus_21_before/``, rows located by
exact content, guarded SQL with preflight / post-state assertions.

Usage::

    venv/bin/python scripts/fix_grammar_corpus_21.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_corpus_21.py --check    # summary only
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fix_grammar_topics_3 as base  # noqa: E402

BEFORE = ROOT / 'local_exports' / 'grammar_corpus_21_before'
EXTRA_DIR = ROOT / 'grammar_exercises_extra'
MODULE_DIR = ROOT / 'module_completed' / 'fixed'
SQL_PREFIX = 'item21_grammar_corpus'

# --------------------------------------------------------------- B -------
# topic -> {correct_answer: [alternative orders]}
REORDER_ALTS: dict[str, dict[str, list[str]]] = {
    'A1_1': {
        'Mike is not at work today.': ['Today Mike is not at work.'],
        'It is very cold outside today.': ['Today it is very cold outside.'],
        'The children are not at school today.': ['Today the children are not at school.'],
    },
    'A1_10': {
        'Ben does his homework every evening.': ['Every evening Ben does his homework.'],
        'He goes to work at nine every day.': ['Every day he goes to work at nine.'],
        'Grandpa often reads books at midnight.': ['At midnight Grandpa often reads books.'],
        'Grandma has dinner at sunset every day.': ['Every day Grandma has dinner at sunset.'],
    },
    'A1_12': {
        'She usually eats breakfast.': ['Usually she eats breakfast.'],
        'Lisa often exercises after work.': ['After work Lisa often exercises.'],
        'They usually come home at six.': ['Usually they come home at six.'],
        'My father always exercises in the morning.': ['In the morning my father always exercises.'],
        'Ben sometimes skips breakfast before work.': ['Sometimes Ben skips breakfast before work.'],
    },
    'A1_14': {"I can't make any calls right now.": ["Right now I can't make any calls."]},
    'A1_15': {'We eat a lot of fruit every day.': ['Every day we eat a lot of fruit.']},
    'A1_8': {'We always meet on Friday.': ['On Friday we always meet.']},
    'A1_9': {
        'It is sunny today.': ['Today it is sunny.'],
        'It is often cloudy in autumn.': ['In autumn it is often cloudy.'],
        'It is usually warm in summer.': ['In summer it is usually warm.'],
        'It was very hot last summer.': ['Last summer it was very hot.'],
        'It is too cold to swim today.': ['Today it is too cold to swim.'],
    },
    'A2_1': {'I usually eat an apple for lunch.': ['Usually I eat an apple for lunch.', 'For lunch I usually eat an apple.']},
    'A2_14': {'We have breakfast every Sunday.': ['Every Sunday we have breakfast.']},
    'A2_15': {
        'We are not cooking dinner tonight.': ['Tonight we are not cooking dinner.'],
        'David is cleaning his room now.': ['Now David is cleaning his room.', 'David is now cleaning his room.'],
        'He is not working hard today.': ['Today he is not working hard.'],
    },
    'A2_16': {
        'We are having dinner at 6 tonight.': ['Tonight we are having dinner at 6.'],
        'He is starting his job next month.': ['Next month he is starting his job.'],
        'You are presenting the project at noon tomorrow.': ['At noon tomorrow you are presenting the project.',
                                                             'Tomorrow at noon you are presenting the project.'],
        'We are cancelling the appointment next week.': ['Next week we are cancelling the appointment.'],
        'We are signing the contract tomorrow at 10.': ['Tomorrow at 10 we are signing the contract.'],
        'We are meeting the team next month.': ['Next month we are meeting the team.'],
        'They are finalising the deal next week.': ['Next week they are finalising the deal.'],
        'My colleagues are launching the product next month.': ['Next month my colleagues are launching the product.'],
    },
    'A2_18': {
        'I think it will be hot tomorrow.': ['I think tomorrow it will be hot.'],
        'It will rain all day tomorrow.': ['Tomorrow it will rain all day.'],
        'There will be frost tonight.': ['Tonight there will be frost.'],
    },
    'A2_22': {
        'We played tennis yesterday.': ['Yesterday we played tennis.'],
        'She called me yesterday.': ['Yesterday she called me.'],
        'We moved here last year.': ['Last year we moved here.'],
        'She cleaned the kitchen yesterday.': ['Yesterday she cleaned the kitchen.'],
    },
    'A2_23': {"They didn't send the letter yesterday.": ["Yesterday they didn't send the letter."]},
    'A2_6': {"He doesn't have to use the projector today.": ["Today he doesn't have to use the projector."]},
    'A2_7': {'Emma should stretch every morning.': ['Every morning Emma should stretch.']},
    'B1_12': {'The room is cleaned every day.': ['Every day the room is cleaned.']},
    'B1_3': {'She used to drink tea every morning.': ['Every morning she used to drink tea.']},
    'B1_6': {'She looks after her grandmother every day.': ['Every day she looks after her grandmother.']},
    'B1_8': {
        'There is less traffic today.': ['Today there is less traffic.'],
        'He drinks less coffee now.': ['Now he drinks less coffee.', 'He now drinks less coffee.'],
    },
    'B2_10': {
        'We had the windows cleaned yesterday.': ['Yesterday we had the windows cleaned.'],
        'We had the boiler serviced yesterday.': ['Yesterday we had the boiler serviced.'],
    },
    'B2_9': {'The building was completely renovated last summer.': ['Last summer the building was completely renovated.']},
    'C1_1': {'She will be working remotely next year.': ['Next year she will be working remotely.']},
}

# --------------------------------------------------------------- C -------
# topic -> {(session, order): base verb shown in brackets after the blank}
VERB_HINTS: dict[str, dict[tuple[int, int], str]] = {
    'A2_20': {(1, 1): 'melt', (1, 2): 'rain', (2, 1): 'expand', (2, 2): 'set', (3, 1): 'taste',
              (3, 3): 'ring', (4, 2): 'blow', (5, 2): 'snow'},
    'A2_21': {(1, 1): 'rain', (2, 1): 'leave'},
    'A2_23': {(5, 2): 'pass'},
    'B1_14': {(2, 1): 'stay', (2, 3): 'book', (4, 1): 'take', (5, 1): 'book'},
    'B1_2': {(1, 1): 'cook', (1, 3): 'run', (2, 1): 'watch', (2, 2): 'finish', (2, 3): 'listen', (3, 1): 'make',
             (3, 2): 'shine', (4, 1): 'sleep', (5, 2): 'talk', (6, 1): 'blow', (7, 1): 'write', (8, 1): 'review'},
    'B2_10': {(1, 1): 'repair', (1, 3): 'renovate', (2, 1): 'fit', (2, 2): 'repair', (2, 3): 'paint',
              (3, 2): 'write', (3, 3): 'redesign', (5, 1): 'upgrade', (7, 1): 'remove', (8, 2): 'void'},
    'B2_11': {(2, 3): 'treat'},
    'B2_12': {(1, 1): 'walk', (1, 2): 'exhaust', (2, 1): 'look', (2, 3): 'know', (3, 1): 'realise', (3, 2): 'pack',
              (4, 1): 'see', (5, 2): 'situate', (6, 1): 'recover', (7, 1): 'base', (8, 4): 'consider'},
    'B2_3': {(1, 1): 'write', (2, 1): 'conduct', (4, 1): 'receive', (5, 1): 'grow', (7, 1): 'approve', (8, 1): 'review'},
    'B2_5': {(3, 1): 'train', (4, 1): 'allow', (6, 1): 'invest', (7, 1): 'take over', (8, 1): 'place'},
    'B2_7': {(1, 1): 'listen', (1, 2): 'rent', (1, 3): 'laugh', (2, 1): 'open', (2, 2): 'sign', (2, 3): 'take',
             (3, 1): 'see', (3, 2): 'speak', (3, 3): 'buy', (4, 1): 'reach', (4, 2): 'use', (5, 1): 'have',
             (5, 2): 'make', (6, 1): 'see', (7, 1): 'reduce', (8, 1): 'launch'},
    'C1_7': {(3, 3): 'arrive'},
}

# ---------------------------------------------------- theory placeholders
THEORY_MODULES = {
    'A2_12': 'module_A2_12_city_village.json',
    'B1_14': 'module_B1_14_travel_and_tourism.json',
    'B1_2': 'module_B1_2_cinema_and_theatre.json',
}


def _fix_theory_rows(topic: str, content: dict) -> dict:
    new = copy.deepcopy(content)
    fixed = 0
    for section in new['sections']:
        for i, row in enumerate(section.get('table') or []):
            if not isinstance(row, dict):
                continue
            if row.get('label') == 'Structure':
                # {label: Structure, pattern: too + adjective, …} → the pattern is the first cell.
                section['table'][i] = {k: v for k, v in row.items() if k != 'label'}
                fixed += 1
            elif row.get('pronoun') in ('Question', 'Pattern') and row.get('verb'):
                # {pronoun: Question, verb: Have you ever…?, …} → the hidden pattern becomes the first cell.
                rest = {k: v for k, v in row.items() if k not in ('pronoun', 'verb')}
                section['table'][i] = {'pronoun': row['verb'], **rest}
                fixed += 1
    assert fixed, f'{topic}: no placeholder rows found'
    return new


# --------------------------------------------------------------- build ---
def _load(path: Path) -> dict:
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def _topic_meta() -> dict[str, dict]:
    meta = {}
    for path in sorted((BEFORE / 'extra').glob('grammar_extra_*.json')):
        name = path.stem[len('grammar_extra_'):]
        level, number = name.split('_')
        module_file = next((p.name for p in (BEFORE / 'modules').glob(f'module_{name}_*.json')), None)
        meta[name] = {'slug': f'{level.lower()}-{number}', 'level': level, 'module': int(number),
                      'module_file': module_file}
    return meta


def build_exercises(topic: str) -> tuple[dict, list[dict]]:
    data = _load(BEFORE / 'extra' / f'grammar_extra_{topic}.json')
    alts = dict(REORDER_ALTS.get(topic, {}))
    hints = dict(VERB_HINTS.get(topic, {}))
    changes = []
    for session in data['sessions']:
        number = session['session_number']
        for exercise in session['exercises']:
            content = exercise['content']
            old = copy.deepcopy(exercise)
            if exercise['exercise_type'] == 'reorder' and content['correct_answer'] in alts:
                extra = alts.pop(content['correct_answer'])
                for alt in extra:
                    assert sorted(t.lower() for t in base_tokens(alt)) == sorted(t.lower() for t in base_tokens(content['correct_answer'])), (topic, alt)
                content['alternatives'] = list(content.get('alternatives') or []) + extra
            key = (number, exercise['order'])
            if exercise['exercise_type'] == 'fill_blank' and key in hints:
                verb = hints.pop(key)
                assert '(' not in content['question'] and content['question'].count('___') == 1, (topic, key)
                content['question'] = content['question'].replace('___', f'___ ({verb})', 1)
            if exercise != old:
                changes.append({'slot': key, 'kind': 'fix', 'old': old, 'new': copy.deepcopy(exercise)})
    assert not alts, f'{topic}: reorder sentences not found {list(alts)}'
    assert not hints, f'{topic}: fill_blank slots not found {sorted(hints)}'
    return data, changes


_TOKEN_RE = re.compile(r"[A-Za-z0-9']+|[.!?,]")


def base_tokens(sentence: str) -> list[str]:
    return _TOKEN_RE.findall(sentence)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not BEFORE.exists():
        print(f'snapshot dir missing: {BEFORE}', file=sys.stderr)
        return 2
    meta = _topic_meta()
    base.TOPICS.clear()
    base.TOPICS.update(meta)
    # Theory patches here touch sections only: key checks and patches are narrowed to that.
    base.ASSERT_LABEL = 'item21'
    base.EXTRA_KEYS = ('sections',)
    base.TOPIC_KEYS = ('sections',)
    all_changes, outputs, theory = {}, [], {}
    total = {'reorder': 0, 'hint': 0}
    for topic in sorted(set(REORDER_ALTS) | set(VERB_HINTS)):
        data, changes = build_exercises(topic)
        base.validate_exercises(topic, data)
        if changes:
            all_changes[topic] = changes
            outputs.append((EXTRA_DIR / f'grammar_extra_{topic}.json', data))
        for change in changes:
            total['reorder' if change['new']['exercise_type'] == 'reorder' else 'hint'] += 1
    for topic, module_file in THEORY_MODULES.items():
        module = _load(BEFORE / 'modules' / module_file)
        lesson = base._grammar_lesson(module)
        old_content = copy.deepcopy(lesson['content'])
        lesson['content'] = _fix_theory_rows(topic, old_content)
        theory[topic] = ({'sections': old_content['sections']}, {'sections': lesson['content']['sections']})
        outputs.append((MODULE_DIR / module_file, module))
    print(f"exercise edits: {sum(len(c) for c in all_changes.values())} in {len(all_changes)} topics "
          f"(reorder alternatives {total['reorder']}, verb hints {total['hint']}); theory modules {len(theory)}")
    if args.check:
        return 0
    for path, payload in outputs:
        base._dump_json(path, payload)
    print('wrote', len(outputs), 'JSON files')
    for suffix, text in base.emit_sql(all_changes, theory).items():
        path = base.EXPORT_DIR / f'{SQL_PREFIX}_{suffix}.sql'
        path.write_text(text, encoding='utf-8')
        print('wrote', path.relative_to(ROOT), f'({len(text) // 1024} KiB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
