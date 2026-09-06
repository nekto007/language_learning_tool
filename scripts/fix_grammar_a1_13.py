#!/usr/bin/env python3
"""Lesson audit item 23 — deep pass over topic a1-13 «Повелительное наклонение».

Same delivery as items 20 and 22 (``scripts/fix_grammar_topics_3.py``);
snapshot in ``local_exports/grammar_a1_13_before/``.

Usage::

    venv/bin/python scripts/fix_grammar_a1_13.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_a1_13.py --check    # summary only
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fix_grammar_topics_3 as base  # noqa: E402

BEFORE = ROOT / 'local_exports' / 'grammar_a1_13_before'
SQL_PREFIX = 'item23_grammar_a1_13'
T = 'A1_13'
base.EDITS[T] = {}
fix, replace = base.fix, base.replace

# Fill-blanks: the Russian verb in brackets makes the item a translation into
# the base form instead of a lexical guess («___ the door» took Open only,
# though Close / Shut / Lock are just as right); synonyms go to alternatives.
fix(T, 1, 1, question='___ (откройте) the door, please!',
    explanation="Повелительное наклонение — базовая форма глагола без to и без подлежащего: Open the door! "
                'Перевод: Откройте дверь, пожалуйста!')
fix(T, 1, 2, question="Don't ___ (закрывайте) your eyes!", alternatives=['shut'],
    explanation="Отрицательное повелительное: Don't + базовая форма. Close / shut — оба «закрывать». "
                'Перевод: Не закрывайте глаза!')
fix(T, 1, 3, question='___ (поднимите) your hand and show me your fingers.', alternatives=['Lift', 'Put up'],
    explanation='Утвердительное повелительное: базовая форма Raise (или Lift). Перевод: Поднимите руку и покажите мне пальцы.')
fix(T, 2, 1, question='___ (сядьте) down on the chair.',
    explanation='Sit down = садитесь. Повелительное наклонение начинается с базовой формы глагола Sit. '
                'Перевод: Сядьте на стул.')
fix(T, 2, 2, question="Don't ___ (сгибайте) your back when you walk!",
    explanation="Отрицательное повелительное: Don't + основа глагола bend. Перевод: Не сгибайте спину, когда идёте!")
replace(T, 2, 3, 'fill_blank',
        question='___ (давайте) stretch our legs!', correct_answer="Let's", alternatives=['Let us'],
        explanation="Let's (= let us) + базовая форма глагола — предложение сделать что-то вместе. "
                    'Перевод: Давайте потянем ноги!')
fix(T, 3, 1, question="___ (смотрите) straight ahead and don't look down.",
    explanation='Look straight ahead = смотрите прямо. Повелительное наклонение: базовая форма Look. '
                'Перевод: Смотрите прямо и не смотрите вниз.')
fix(T, 3, 2, question="Don't ___ (втягивайте) your stomach in too much.", alternatives=['suck'],
    explanation="Отрицательное повелительное: Don't + основа глагола pull (или suck). "
                'Перевод: Не втягивайте живот слишком сильно.')
fix(T, 3, 3, question='___ (пошевелите) your toes and count to ten.', alternatives=['Move'],
    explanation='Wiggle your toes = пошевелите пальцами ног. Базовая форма Wiggle (или Move). '
                'Перевод: Пошевелите пальцами ног и сосчитайте до десяти.')
fix(T, 4, 1, question='___ (поднимите) your arm above your head and hold it there.',
    explanation='Raise / Lift your arm = поднимите руку. Повелительное наклонение: базовая форма. '
                'Перевод: Поднимите руку над головой и держите её там.')
fix(T, 4, 2, question="Don't ___ (закрывайте) your eyes during the exercise.",
    explanation="Don't close / shut your eyes = не закрывайте глаза. Перевод: Не закрывайте глаза во время упражнения.")
fix(T, 5, 1, question='___ (держите) your back straight when you sit.',
    explanation='Keep / Hold your back straight = держите спину прямо. Повелительное наклонение: базовая форма. '
                'Перевод: Держите спину прямо, когда сидите.')
replace(T, 5, 2, 'fill_blank',
        question="Don't ___ (ешьте) too fast — it is bad for your stomach.", correct_answer='eat', alternatives=[],
        explanation="Отрицательное повелительное: Don't + основа глагола eat. Перевод: Не ешьте слишком быстро — "
                    'это вредно для желудка.')
fix(T, 6, 1, question='___ (держите) your arm out straight and point at the wall.',
    alternatives=['Stretch', 'Extend', 'Keep'],
    explanation='Hold / Keep your arm out straight = держите руку прямо; Stretch / Extend — вытяните. '
                'Перевод: Держите руку прямо и укажите на стену.')
fix(T, 7, 1, question='___ (раскройте) your chest and breathe in slowly.',
    explanation='Open / Expand your chest = раскройте грудную клетку. Повелительное наклонение: базовая форма. '
                'Перевод: Раскройте грудную клетку и медленно вдохните.')
fix(T, 8, 1, question='___ (наклоните) your head forward and stretch your neck.', alternatives=['Lower', 'Tilt', 'Bend'],
    explanation='Drop / Lower / Tilt your head forward = наклоните голову вперёд. '
                'Перевод: Наклоните голову вперёд и потяните шею.')
# "You + imperative" is not wrong, only marked — soften the two places that called it an error.
fix(T, 1, 7,
    explanation='Неверно. В обычной команде местоимение you опускается: Sit down! Форма «You sit down!» существует, '
                'но звучит резко и используется редко — для подчёркивания.')
fix(T, 1, 9,
    explanation='В обычной команде подлежащее you не нужно — предложение начинается с глагола: Open your mouth, please!')
fix(T, 1, 10, alternatives=['Please, raise your hand!'])
# Error corrections: six of thirteen were "Doesn't → Don't" and seven "You … → verb"; other typical errors instead.
fix(T, 3, 9,
    explanation='В обычной команде you не ставится — предложение начинается с глагола: Look straight ahead!')
fix(T, 4, 7,
    explanation="Doesn't — форма третьего лица (She doesn't…). В отрицательном повелительном всегда Don't + основа глагола.")
replace(T, 4, 8, 'error_correction',
        sentence='Touch the nose with your finger.', correct_answer='Touch your nose with your finger.',
        error_word='the', correct_word='your', alternatives=['your'],
        explanation='Ошибка: с частями тела в командах используется притяжательное your, а не артикль the. '
                    'Правильно: Touch your nose with your finger.')
replace(T, 5, 8, 'error_correction',
        sentence='To bend your knees slowly.', correct_answer='Bend your knees slowly.',
        error_word='To bend', correct_word='Bend', alternatives=['Bend'],
        explanation='Ошибка: в повелительном наклонении частица to не используется — только базовая форма. '
                    'Правильно: Bend your knees slowly.')
replace(T, 6, 7, 'error_correction',
        sentence='Closes your eyes and relax.', correct_answer='Close your eyes and relax.',
        error_word='Closes', correct_word='Close', alternatives=['Close'],
        explanation='Ошибка: окончание -s в повелительном наклонении не используется — только базовая форма. '
                    'Правильно: Close your eyes and relax.')
replace(T, 7, 7, 'error_correction',
        sentence='Not touch your face!', correct_answer="Don't touch your face!",
        error_word='Not', correct_word="Don't", alternatives=["Don't", 'Do not'],
        explanation="Ошибка: отрицательная команда строится с Don't (Do not), а не с голым Not. "
                    "Правильно: Don't touch your face!")
replace(T, 7, 8, 'error_correction',
        sentence='Please to keep your back straight.', correct_answer='Please keep your back straight.',
        error_word='to keep', correct_word='keep', alternatives=['keep'],
        explanation='Ошибка: после please идёт базовая форма без to. Правильно: Please keep your back straight.')
replace(T, 8, 8, 'error_correction',
        sentence='Raises your hand if you know the answer.', correct_answer='Raise your hand if you know the answer.',
        error_word='Raises', correct_word='Raise', alternatives=['Raise'],
        explanation='Ошибка: в повелительном наклонении нет окончания -s. Правильно: Raise your hand if you know the answer.')
# Let's — missing from the topic entirely.
replace(T, 5, 4, 'multiple_choice',
        question='___ go to the doctor together.', correct_answer="Let's",
        options=["Let's", "Let's to", 'Lets', 'Let is'],
        explanation="Let's (= let us) + базовая форма без to — предложение сделать что-то вместе. "
                    'Перевод: Давайте пойдём к врачу вместе.')
replace(T, 8, 4, 'translation',
        question='Давайте пошевелим пальцами ног.', correct_answer="Let's wiggle our toes.",
        alternatives=['Let us wiggle our toes.', "Let's move our toes."],
        explanation="Let's + базовая форма глагола: Let's wiggle. С let's — our toes (наши), не your. "
                    "Перевод: Let's wiggle our toes.")


def theory_A1_13(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    subtitles = [s['subtitle'] for s in sections]
    assert subtitles[0].startswith('1. Утвердительная') and subtitles[4].startswith('Дополнительные примеры'), subtitles
    # Section 1 showed two different imperatives per row ("Touch your nose!" / "Touch your head!") with one translation.
    sections[0]['table'] = [{k: v for k, v in row.items() if k != 'imperative'} for row in sections[0]['table']]
    extra = sections[4]
    assert extra['table'][0]['example'] == 'Your body needs exercise.', extra['table'][0]
    extra['table'][0] = base._set_example(extra['table'][0], 'Relax your body and breathe slowly.',
                                          'Расслабьте тело и дышите медленно.')
    lets = {
        'subtitle': "5. Let's — предложение сделать вместе",
        'description': "Let's (= let us) + базовая форма глагола: говорящий предлагает сделать что-то вместе. "
                       "Отрицание — Let's not + глагол.",
        'table': [
            base._row(pronoun="Let's + глагол", form='давайте …', example="Let's stretch our legs!",
                      translation='Давайте потянем ноги!'),
            base._row(pronoun="Let's + глагол", form='давайте …', example="Let's close our eyes and relax.",
                      translation='Давайте закроем глаза и расслабимся.'),
            base._row(pronoun="Let's not + глагол", form='давайте не …', example="Let's not run in the corridor.",
                      translation='Давайте не будем бегать в коридоре.'),
        ],
    }
    sections.insert(4, lets)
    notes = list(new['important_notes'])
    assert notes[2].startswith('⚠️ С частями тела ВСЕГДА'), notes[2]
    notes[2] = "⚠️ С частями тела обычно используется притяжательное your, а не артикль the: Touch your nose (не the nose)"
    notes.append("💡 Let's + глагол = предложение сделать что-то вместе: Let's go! Отрицание — Let's not run")
    new['important_notes'] = notes
    new['rule'] = ("Повелительное наклонение (Open! Don't run! Let's go!) используется для команд, инструкций, просьб, "
                   'запретов и предложений сделать что-то вместе.')
    base._rebuild_tldr_summary(new)
    return new


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not BEFORE.exists():
        print(f'snapshot dir missing: {BEFORE}', file=sys.stderr)
        return 2
    base.BEFORE = BEFORE
    base.ASSERT_LABEL = 'item23'
    base.TOPICS.clear()
    base.TOPICS[T] = {'slug': 'a1-13', 'level': 'A1', 'module': 13, 'module_file': 'module_A1_13_body_parts.json'}
    base.THEORY[T] = theory_A1_13
    data, changes = base.build_exercises(T)
    base.validate_exercises(T, data)
    module, old_extra, new_extra = base.build_theory(T)
    kinds = {'fix': 0, 'replace': 0}
    for change in changes:
        kinds[change['kind']] += 1
    print(f"{T}: {len(changes)} exercise edits (fix {kinds['fix']}, replace {kinds['replace']}); "
          f"sections {len(old_extra['sections'])} -> {len(new_extra['sections'])}, "
          f"notes {len(old_extra['important_notes'])} -> {len(new_extra['important_notes'])}")
    if args.check:
        return 0
    base._dump_json(base.EXTRA_DIR / f'grammar_extra_{T}.json', data)
    base._dump_json(base.MODULE_DIR / base.TOPICS[T]['module_file'], module)
    for suffix, text in base.emit_sql({T: changes}, {T: (old_extra, new_extra)}).items():
        path = base.EXPORT_DIR / f'{SQL_PREFIX}_{suffix}.sql'
        path.write_text(text, encoding='utf-8')
        print('wrote', path.relative_to(ROOT), f'({len(text) // 1024} KiB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
