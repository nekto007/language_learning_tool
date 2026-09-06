#!/usr/bin/env python3
"""Lesson audit item 22 — deep pass over topic a1-12 «Наречия частотности».

Reuses the item-20 machinery (``scripts/fix_grammar_topics_3.py``): the
edits below are applied to the snapshot in ``local_exports/grammar_a1_12_before/``
and delivered to prod by content-keyed guarded SQL.

Usage::

    venv/bin/python scripts/fix_grammar_a1_12.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_a1_12.py --check    # summary only
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fix_grammar_topics_3 as base  # noqa: E402

BEFORE = ROOT / 'local_exports' / 'grammar_a1_12_before'
SQL_PREFIX = 'item22_grammar_a1_12'
T = 'A1_12'
base.EDITS[T] = {}
fix, replace = base.fix, base.replace

# ------------------------------------------------------------ session 1 ---
fix(T, 1, 2,
    question='Laura goes to the gym three or four times a week. She ___ exercises after work.',
    alternatives=['usually'],
    explanation='Often (часто) — три-четыре раза в неделю — высокая частота; usually тоже подходит. '
                'Наречие стоит перед основным глаголом exercises.')
fix(T, 1, 5,
    question='Peter has not played football once in his life and has no interest in sport. He ___ plays football.',
    explanation='Never (никогда) — 0% частота. «Not once in his life» означает полное отсутствие действия. '
                'Перевод: Питер ни разу в жизни не играл в футбол. Он никогда не играет в футбол.')
fix(T, 1, 8,
    alternatives=['He usually comes home at six.', "He usually comes home at 6 o'clock.", 'Usually he comes home at six.'])
# ------------------------------------------------------------ session 2 ---
fix(T, 2, 3,
    alternatives=['seldom', 'hardly ever'],
    explanation='Rarely (редко) — очень низкая частота; синонимы seldom, hardly ever. '
                '«Two or three times a year» — явная редкость.')
fix(T, 2, 4,
    question='My grandmother has a strict bedtime routine. She is ___ in bed by nine.',
    explanation='Always (всегда) — «strict routine» указывает на 100% частоту. С глаголом to be наречие стоит ПОСЛЕ него: '
                'She is always in bed by nine (не She always is).')
fix(T, 2, 8,
    alternatives=['Children sometimes go to bed late.', 'Sometimes the children go to bed late.',
                  'The children go to bed late sometimes.'])
# ------------------------------------------------------------ session 3 ---
replace(T, 3, 1, 'fill_blank',
        question='___ do you exercise? — Twice a week.',
        correct_answer='How often', alternatives=[],
        explanation='How often? (как часто?) — вопрос о частоте. Ответ — выражение частоты: twice a week, every day, '
                    'once a month. Перевод: Как часто ты занимаешься спортом? — Дважды в неделю.')
fix(T, 3, 2,
    alternatives=['often'],
    explanation='Usually (обычно) — высокая, но не абсолютная регулярность; often тоже допустимо. '
                '«Most mornings, but not every day» = usually.')
fix(T, 3, 3,
    alternatives=['sometimes', 'seldom'],
    explanation='Rarely (редко) — низкая частота; sometimes (иногда) для «once a month» тоже возможно. '
                'Наречие стоит перед глаголом calls.')
fix(T, 3, 8,
    alternatives=['He rarely does sport in the morning.', 'He seldom exercises in the morning.',
                  'He rarely does sports in the morning.'])
fix(T, 3, 10,
    alternatives=['After work Lisa often exercises.', 'Often Lisa exercises after work.'])
# ------------------------------------------------------------ session 4 ---
fix(T, 4, 1,
    question='Susan has a morning habit: she gets dressed at 7:45 and leaves the house at 8 a.m. every day. '
             'She ___ gets dressed before eight.',
    explanation='Always (всегда) — описывает неизменную привычку: одевается в 7:45 каждый день. '
                'Стоит перед основным глаголом gets.')
fix(T, 4, 2,
    alternatives=['usually'],
    explanation='Always (всегда) — «daily routine» = каждый день; usually тоже допустимо. '
                'Наречие стоит перед глаголом checks.')
fix(T, 4, 3,
    question='Boris works out at the gym on Monday, Wednesday and Friday most weeks. He ___ goes to the gym three times a week.',
    explanation='Usually (обычно) — регулярное действие по расписанию, но «most weeks» — не абсолютно всегда.')
replace(T, 4, 4, 'multiple_choice',
        question='___ does she go to the gym? — Three times a week.',
        correct_answer='How often', options=['How often', 'How much', 'How many', 'How long'],
        explanation='How often? — вопрос о частоте («как часто»). How much / How many — о количестве, How long — '
                    'о длительности. Перевод: Как часто она ходит в спортзал? — Три раза в неделю.')
fix(T, 4, 5,
    alternatives=['We go to the gym twice a week — that is our routine.', 'Twice a week we go to the gym — it is our routine.'])
fix(T, 4, 6,
    alternatives=['She sometimes gets dressed fast when she is late.', 'Sometimes she gets dressed quickly when she is late.'])
fix(T, 4, 10, alternatives=['Once a month Emma goes shopping.'])
# ------------------------------------------------------------ session 5 ---
replace(T, 5, 1, 'fill_blank',
        question='I ___ (not / usually) eat breakfast on weekdays — only at weekends.',
        correct_answer="don't usually", alternatives=["usually don't", 'do not usually', 'usually do not'],
        explanation="Отрицание с наречием частотности: don't usually (нейтрально) или usually don't (с акцентом) — оба "
                    'порядка правильны. Перевод: По будням я обычно не завтракаю, только по выходным.')
fix(T, 5, 2,
    alternatives=['usually'],
    explanation='Often (часто) — три-четыре раза в неделю — высокая частота; usually тоже подходит. '
                'Стоит перед основным глаголом exercises.')
fix(T, 5, 3,
    question='The café is open 24 hours a day, 365 days a year. It is ___ open.',
    explanation='Always (всегда) — 24 часа в сутки, 365 дней в году = 100% времени. '
                'С глаголом to be наречие стоит после него: is always.')
fix(T, 5, 10, alternatives=['Twice a week David goes swimming.'])
# ------------------------------------------------------------ session 6 ---
fix(T, 6, 1,
    alternatives=['usually'],
    explanation='Always (всегда) — неизменный ежеутренний распорядок; usually тоже допустимо. '
                'Стоит перед глаголом gets dressed.')
replace(T, 6, 2, 'multiple_choice',
        question='How often do you go swimming? — ___.',
        correct_answer='Twice a week', options=['Twice a week', 'Two weeks', "At two o'clock", 'For two weeks'],
        explanation='На вопрос How often? отвечает выражение частоты: twice a week (дважды в неделю). Two weeks — '
                    "срок, at two o'clock — время, for two weeks — длительность. Перевод: Как часто ты плаваешь? — Дважды в неделю.")
fix(T, 6, 3,
    explanation='Верно. Это стандартная шкала частотности: always (100%) — usually (~90%) — often (~70%) — '
                'sometimes (~50%) — rarely (~20%) — never (0%). Проценты условные, важен порядок.')
fix(T, 6, 4,
    alternatives=["She has good habits: she always goes to bed before eleven o'clock.",
                  'She has good habits: she always goes to bed before 11.'])
replace(T, 6, 5, 'translation',
        question='Как часто ты ходишь в спортзал? — Дважды в неделю.',
        correct_answer='How often do you go to the gym? — Twice a week.',
        alternatives=['How often do you go to the gym? — Two times a week.'],
        explanation='How often? — вопрос о частоте. Ответ — выражение частоты twice a week. '
                    'Перевод: How often do you go to the gym? — Twice a week.')
fix(T, 6, 6,
    alternatives=['He gets dressed and leaves the house at the same time every day.',
                  'Every day he gets dressed and leaves home at the same time.'])
replace(T, 6, 7, 'error_correction',
        sentence='She once a month visits her grandparents.',
        correct_answer='She visits her grandparents once a month.',
        error_word='once a month visits her grandparents', correct_word='visits her grandparents once a month',
        alternatives=['visits her grandparents once a month', 'Once a month she visits her grandparents.'],
        explanation='Ошибка: выражение частоты once a month не ставится между подлежащим и глаголом. Его место — '
                    'в конце предложения (или в начале для акцента). Правильно: She visits her grandparents once a month.')
fix(T, 6, 10, alternatives=['Twice a month my mother visits the dentist.'])
# ------------------------------------------------------------ session 7 ---
fix(T, 7, 1,
    question='The supermarket opens at eight every day of the year without exception. It ___ opens at eight in the morning.',
    explanation='Always (всегда) — «every day of the year without exception» = 100% частота. Стоит перед глаголом opens.')
replace(T, 7, 3, 'true_false',
        statement='В вопросе наречие частотности стоит после подлежащего: «Do you often go to the cinema?» — правильно.',
        correct_answer=True,
        explanation='Верно. В вопросах с do/does наречие стоит после подлежащего перед основным глаголом: '
                    'Do you often go…? Does she usually work…? А вопрос о частоте — How often do you…?')
fix(T, 7, 4,
    alternatives=['This is his routine: he exercises regularly and never misses a workout.',
                  'This is his routine: he exercises regularly and never skips a workout.',
                  'This is his routine: he regularly exercises and never misses a workout.'])
fix(T, 7, 5,
    alternatives=['She usually comes home exhausted because she works late.',
                  'Usually she comes home tired because she works late.'])
fix(T, 7, 6,
    alternatives=['Our neighbors sometimes make noise in the evenings, but that is rare.',
                  'Sometimes our neighbours make noise in the evenings, but it is rare.'])
fix(T, 7, 9,
    alternatives=['Sometimes Ben skips breakfast before work.', 'Ben skips breakfast before work sometimes.'])
fix(T, 7, 10, alternatives=['Twice a week Maria reviews her vocabulary.'])
# ------------------------------------------------------------ session 8 ---
replace(T, 8, 8, 'error_correction',
        sentence='We every day have breakfast at seven.',
        correct_answer='We have breakfast at seven every day.',
        error_word='every day have breakfast at seven', correct_word='have breakfast at seven every day',
        alternatives=['have breakfast at seven every day', 'Every day we have breakfast at seven.'],
        explanation='Ошибка: every day не ставится между подлежащим и глаголом. Выражение частоты стоит в конце '
                    '(или в начале для акцента). Правильно: We have breakfast at seven every day.')
replace(T, 8, 9, 'reorder',
        words=['his', 'grandmother', 'visits', 'once', 'a', 'week', '.', 'He'],
        correct_answer='He visits his grandmother once a week.',
        alternatives=['Once a week he visits his grandmother.'],
        explanation='Once a week (раз в неделю) — выражение частоты стоит в конце предложения (или в начале для акцента). '
                    'Перевод: Он навещает бабушку раз в неделю.')
fix(T, 8, 10,
    alternatives=['Our daughter goes to bed regularly before ten.', 'Our daughter goes to bed before ten regularly.'])


# ----------------------------------------------------------------- theory --
def _rebuild_tldr_summary(content: dict) -> None:
    """Like ``base._rebuild_tldr_summary`` but a ``rules`` section (no table)
    contributes its first example too — that is how the generator built the
    A1-12 tldr."""
    rows = []
    for section in content['sections']:
        subtitle = section.get('subtitle', '')
        if str(subtitle).startswith('Дополнительные примеры'):
            continue
        table = section.get('table') or []
        if table and isinstance(table[0], dict):
            first = table[0]
            rows.append((subtitle, first.get('example', ''),
                         first.get('example_translation') or first.get('translation', '')))
        elif section.get('rules'):
            example = section['rules'][0].get('examples', [''])[0]
            en, _, ru = example.partition(' - ')
            rows.append((subtitle, en, ru))
    content['tldr'] = [f'<strong>{sub}</strong>: <em>{ex}</em>' for sub, ex, _ in rows]
    summary = dict(content.get('summary') or {})
    summary['table'] = [{'topic': sub, 'example': ex, 'translation': tr} for sub, ex, tr in rows]
    summary.setdefault('note', 'Каждый раздел — отдельный аспект темы. Возвращайтесь к таблице при повторении.')
    content['summary'] = summary


def theory_A1_12(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert [s['subtitle'] for s in sections] == [
        'Шкала частотности (от 100% до 0%)', 'Позиция наречий в предложении', 'Выражения частотности',
        'Дополнительные примеры со словарём модуля', 'Употребление в утверждении'], [s['subtitle'] for s in sections]
    position = sections[1]
    assert len(position['rules']) == 3, position['rules']
    position['description'] = ('С обычными глаголами наречие стоит между подлежащим и глаголом, с глаголом be — после '
                               'него; в вопросах — после подлежащего; never уже содержит отрицание.')
    position['rules'].append({
        'rule': 'В ВОПРОСАХ и ОТРИЦАНИЯХ',
        'examples': [
            'Do you often go to the cinema? - Ты часто ходишь в кино?',
            'How often do you exercise? - Twice a week. - Как часто ты занимаешься спортом? - Дважды в неделю.',
            "I don't usually eat breakfast. - Я обычно не завтракаю.",
            "She never eats meat. (не doesn't never) - Она никогда не ест мясо.",
        ],
        'note': 'How often? — вопрос о частоте; после do/does наречие стоит после подлежащего; never не сочетается с not',
    })
    expressions = sections[2]
    expressions['description'] = ('Выражения every day, twice a week, once a month обычно стоят в конце предложения; '
                                  'для акцента их ставят в начало: Every day I get up at seven.')
    extra = sections[3]
    extra['description'] = 'Наречия и выражения частотности на лексике модуля.'
    extra['table'] = [base._row(example=en, translation=ru) for en, ru in [
        ('I always have breakfast at seven.', 'Я всегда завтракаю в семь.'),
        ('She usually gets dressed before eight.', 'Она обычно одевается до восьми.'),
        ('My father often comes home late.', 'Мой отец часто приходит домой поздно.'),
        ('We sometimes watch TV after dinner.', 'Мы иногда смотрим телевизор после ужина.'),
        ('They rarely have dinner together.', 'Они редко ужинают вместе.'),
        ('He never goes to bed before midnight.', 'Он никогда не ложится спать до полуночи.'),
        ('I exercise twice a week.', 'Я занимаюсь спортом дважды в неделю.'),
        ('She visits her grandmother once a month.', 'Она навещает бабушку раз в месяц.'),
        ('He exercises regularly — it is his daily routine.', 'Он занимается спортом регулярно — это его ежедневный распорядок.'),
        ('Reading before bed is a good habit.', 'Чтение перед сном — хорошая привычка.'),
        ('How often do you come home late? — Rarely.', 'Как часто ты приходишь домой поздно? — Редко.'),
        ("I don't usually watch TV in the morning.", 'Я обычно не смотрю телевизор по утрам.'),
    ]]
    how_often = sections[4]
    how_often['subtitle'] = 'Вопрос How often? и ответы'
    how_often['description'] = ('How often? — «как часто?». В ответе — наречие или выражение частоты; '
                                'выражение обычно стоит в конце предложения.')
    how_often['table'] = [
        base._row(pronoun='How often …?', form='every day', example='How often do you exercise? — Every day.',
                  translation='Как часто ты занимаешься спортом? — Каждый день.'),
        base._row(pronoun='How often …?', form='twice a week', example='How often does she go to the gym? — Twice a week.',
                  translation='Как часто она ходит в спортзал? — Дважды в неделю.'),
        base._row(pronoun='How often …?', form='once a month', example='How often do they eat out? — Once a month.',
                  translation='Как часто они едят вне дома? — Раз в месяц.'),
        base._row(pronoun='How often …?', form='never / hardly ever', example='How often do you watch TV? — Hardly ever.',
                  translation='Как часто ты смотришь телевизор? — Почти никогда.'),
    ]
    notes = list(new['important_notes'])
    assert notes[3].startswith('⚠️ Выражения с every/once/twice'), notes[3]
    notes[3] = '⚠️ Выражения every day / once a month обычно стоят В КОНЦЕ предложения, для акцента — в начале: Every day I get up at seven'
    notes.append('⚠️ В вопросах наречие стоит после подлежащего: Do you often…? Вопрос о частоте — How often do you…?')
    notes.append("⚠️ С don't/doesn't: I don't usually eat breakfast (или I usually don't)")
    new['important_notes'] = notes
    new['rule'] = ('Наречия частотности (always, usually, often, sometimes, rarely, never) показывают, как часто '
                   'происходит действие: перед обычным глаголом, после глагола be.')
    _rebuild_tldr_summary(new)
    return new


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not BEFORE.exists():
        print(f'snapshot dir missing: {BEFORE}', file=sys.stderr)
        return 2
    base.BEFORE = BEFORE
    base.ASSERT_LABEL = 'item22'
    base.TOPICS.clear()
    base.TOPICS[T] = {'slug': 'a1-12', 'level': 'A1', 'module': 12, 'module_file': 'module_A1_12_daily_habits.json'}
    base.THEORY[T] = theory_A1_12
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
