#!/usr/bin/env python3
"""Lesson audit item 24 — deep pass over the remaining A1 grammar topics.

Owner's decision 2026-09-06: «делай вообще весь А1». Topics a1-10 … a1-13
were closed by items 20, 22 and 23; this script covers a1-1 … a1-9,
a1-14, a1-15 and a1-16 on the item-20 delivery machinery
(``scripts/fix_grammar_topics_3.py``). Snapshot of the twelve sources:
``local_exports/grammar_a1_rest_before/``.

Each topic has its exercise edits (``fix`` / ``replace`` by slot) and a
theory function; the SQL for all topics goes into one check / apply /
rollback triple. Item 21 touched several of these topics, so in production
this SQL is applied AFTER item 21 (already live) — the preflight refuses
otherwise.

Usage::

    venv/bin/python scripts/fix_grammar_a1_rest.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_a1_rest.py --check    # summary only
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fix_grammar_topics_3 as base  # noqa: E402

BEFORE = ROOT / 'local_exports' / 'grammar_a1_rest_before'
SQL_PREFIX = 'item24_grammar_a1_rest'
fix, replace, row = base.fix, base.replace, base._row
THEORY: dict = {}


def topic_meta() -> dict[str, dict]:
    meta = {}
    for path in sorted(BEFORE.glob('grammar_extra_A1_*.json')):
        name = path.stem[len('grammar_extra_'):]
        number = int(name.split('_')[1])
        module_file = next(p.name for p in BEFORE.glob(f'module_A1_{number}_*.json'))
        meta[name] = {'slug': f'a1-{number}', 'level': 'A1', 'module': number, 'module_file': module_file}
    return meta


# =========================================================== A1_14 can ====
T = 'A1_14'
base.EDITS[T] = {}
# Short answers — none in the file.
replace(T, 2, 3, 'fill_blank',
        question='Can your sister swim? — Yes, she ___.', correct_answer='can', alternatives=[],
        explanation='Краткий ответ повторяет модальный глагол: Yes, she can. / No, she can\'t. '
                    'Перевод: Твоя сестра умеет плавать? — Да.')
replace(T, 5, 1, 'fill_blank',
        question="Can you speak Chinese? — No, I ___.", correct_answer="can't", alternatives=['cannot'],
        explanation="Краткий отрицательный ответ: No, I can't (cannot). Перевод: Ты говоришь по-китайски? — Нет.")
replace(T, 3, 4, 'multiple_choice',
        question='Can you drive? — ___', correct_answer='Yes, I can.',
        options=['Yes, I can.', 'Yes, I do.', 'Yes, I am.', 'Yes, I can drive to.'],
        explanation='Краткий ответ на вопрос с can повторяет can: Yes, I can. (не Yes, I do.) '
                    'Перевод: Ты умеешь водить? — Да.')
replace(T, 8, 8, 'error_correction',
        sentence='Can she drive? — Yes, she does.', correct_answer='Can she drive? — Yes, she can.',
        error_word='does', correct_word='can', alternatives=['can', 'Yes, she can.'],
        explanation='Ошибка: краткий ответ повторяет тот глагол, с которого начался вопрос. Can she…? — Yes, she can. '
                    '(does — для вопросов с does).')
# Wh-questions with can — none in the file.
replace(T, 6, 1, 'fill_blank',
        question='___ languages can you speak? — Two.', correct_answer='How many', alternatives=[],
        explanation='Вопрос с вопросительным словом: How many + существительное + can + подлежащее + глагол? '
                    'Перевод: На скольких языках ты говоришь? — На двух.')
replace(T, 5, 3, 'multiple_choice',
        question='___ can you do well? — I can draw.', correct_answer='What',
        options=['What', 'Do', 'Does', 'How many'],
        explanation='Вопросительное слово стоит перед can: What + can + you + do? '
                    'Перевод: Что ты умеешь делать хорошо? — Я умею рисовать.')
replace(T, 8, 6, 'translation',
        question='На скольких языках ты умеешь говорить?', correct_answer='How many languages can you speak?',
        alternatives=['How many languages are you able to speak?'],
        explanation='How many languages + can + you + speak? — вопросительное слово с существительным стоит перед can. '
                    'Перевод: How many languages can you speak?')
replace(T, 4, 9, 'reorder',
        words=['well', 'you', 'How', 'can', 'swim', '?'], correct_answer='How well can you swim?',
        explanation='Вопрос о степени умения: How well + can + подлежащее + глагол? Перевод: Как хорошо ты плаваешь?')
# Permission and requests — in the theory, not in the exercises.
replace(T, 2, 4, 'multiple_choice',
        question="___ I open the window, please? It's hot in here.", correct_answer='Can',
        options=['Can', 'Do', 'Am', 'Does'],
        explanation='Can I …? — просьба о разрешении. Перевод: Можно мне открыть окно? Здесь жарко.')
replace(T, 6, 6, 'translation',
        question='Можно мне воспользоваться твоим телефоном?', correct_answer='Can I use your phone?',
        alternatives=['Could I use your phone?', 'May I use your phone?'],
        explanation='Разрешение: Can I + глагол? (вежливее — Could I / May I). Перевод: Can I use your phone?')
replace(T, 7, 1, 'fill_blank',
        question="It's cold. ___ you close the window, please?", correct_answer='Can', alternatives=['Could'],
        explanation='Просьба: Can you + глагол, please? (вежливее — Could you). Перевод: Холодно. Ты можешь закрыть окно?')
# Degree of ability.
replace(T, 4, 1, 'fill_blank',
        question='I can speak French ___ (немного), but not very well.', correct_answer='a little',
        alternatives=['a bit', 'a little bit'],
        explanation='Степень умения: very well, well, a little, not at all. Перевод: Я немного говорю по-французски, '
                    'но не очень хорошо.')
replace(T, 6, 7, 'error_correction',
        sentence='She can sing very good.', correct_answer='She can sing very well.',
        error_word='good', correct_word='well', alternatives=['well'],
        explanation='Ошибка: степень умения выражает наречие well, а не прилагательное good: sing very well. '
                    'Правильно: She can sing very well.')


def theory_A1_14(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert [s['subtitle'] for s in sections] == [
        'Утверждение (Affirmative)', 'Отрицание (Negative)', 'Вопрос (Question)', 'Использование CAN',
        'Дополнительные примеры со словарём модуля'], [s['subtitle'] for s in sections]
    sections[3]['table'].append({'use': 'Разрешение (вопрос)', 'example': 'Can I use your phone?',
                                 'translation': 'Можно мне воспользоваться твоим телефоном?'})
    extra = sections[4]
    swaps = {
        'She has a great ability to sing.': ('Can you sing? — Yes, I can, but not very well.',
                                            'Ты умеешь петь? — Да, но не очень хорошо.'),
        'She has good computer skills.': ('She can use a computer very well.', 'Она очень хорошо умеет пользоваться компьютером.'),
        'He has a talent for music.': ('He can play the piano a little.', 'Он немного умеет играть на пианино.'),
    }
    seen = 0
    for i, r in enumerate(extra['table']):
        if r.get('example') in swaps:
            en, ru = swaps[r['example']]
            extra['table'][i] = base._set_example(r, en, ru)
            seen += 1
    assert seen == 3, seen
    sections.insert(4, {
        'subtitle': 'Краткие ответы и вопросы с Wh',
        'description': 'Краткий ответ повторяет can: Yes, I can. / No, I can\'t. Вопросительное слово стоит перед can.',
        'table': [
            row(pronoun='Can you …?', form="Yes, I can. / No, I can't.", example='Can you swim? — Yes, I can.',
                translation='Ты умеешь плавать? — Да.'),
            row(pronoun='What can …?', form='что умеешь?', example='What can you do well? — I can draw.',
                translation='Что ты умеешь делать хорошо? — Я умею рисовать.'),
            row(pronoun='How many … can …?', form='сколько …?', example='How many languages can you speak? — Two.',
                translation='На скольких языках ты говоришь? — На двух.'),
            row(pronoun='How well can …?', form='very well / a little / not at all',
                example='How well can you swim? — A little.', translation='Как хорошо ты плаваешь? — Немного.'),
        ],
    })
    notes = list(new['important_notes'])
    notes.append("💡 Краткий ответ повторяет can: Yes, I can. / No, I can't. (не Yes, I do.)")
    notes.append('💡 Степень умения: very well, well, a little, not at all — I can cook a little')
    new['important_notes'] = notes
    new['rule'] = ('Модальный глагол CAN выражает умения, способности, разрешение и просьбы; после него глагол без to, '
                   'форма одна для всех лиц.')
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_14'] = theory_A1_14


# ==================================================== A1_15 quantifiers ====
T = 'A1_15'
base.EDITS[T] = {}
replace(T, 3, 9, 'error_correction',
        sentence='There are much apples on the table.', correct_answer='There are some apples on the table.',
        error_word='much', correct_word='some', alternatives=['some', 'a lot of', 'There are a lot of apples on the table.'],
        explanation='Ошибка: MUCH нельзя использовать с исчисляемыми (apples). В утверждении → SOME или A LOT OF: '
                    'There are some apples on the table.')
replace(T, 7, 8, 'error_correction',
        sentence="We haven't got some milk for the coffee.", correct_answer="We haven't got any milk for the coffee.",
        error_word='some', correct_word='any', alternatives=['any'],
        explanation="Ошибка: в отрицательных предложениях SOME заменяется на ANY: We haven't got any milk.")
fix(T, 7, 6,
    alternatives=["I've got a little milk - only half a glass.", 'I have a bit of milk - only half a glass.',
                  'I have got a little milk - only half a glass.'])
fix(T, 4, 4,
    explanation="MUCH с неисчисляемыми в отрицаниях: fish (как продукт) — неисчисляемый, There isn't much fish — «рыбы немного». "
                "Можно и There isn't any fish — «рыбы нет совсем» (смысл другой).")
fix(T, 6, 4, alternatives=['We need bread and butter.', 'We need some bread and butter.'])
fix(T, 1, 10, alternatives=None)  # placeholder removed below


def _drop_placeholder(topic: str, slot: tuple[int, int]) -> None:
    """A slot registered only to be removed again (keeps the edit list explicit)."""
    base.EDITS[topic].pop(slot, None)


_drop_placeholder(T, (1, 10))


def theory_A1_15(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    swaps = {
        'I like healthy food.': ('Is there any food in the fridge?', 'В холодильнике есть какая-нибудь еда?'),
        'Water is a healthy drink.': ("We don't have many drinks for the party.", 'У нас немного напитков для вечеринки.'),
        'I drink water every day.': ('I drink a lot of water every day.', 'Я пью много воды каждый день.'),
        'I drink orange juice for breakfast.': ('There is some juice for breakfast.', 'На завтрак есть немного сока.'),
        'My father drinks coffee in the morning.': ('How much coffee does your father drink?', 'Сколько кофе пьёт твой отец?'),
        'I eat chicken for dinner.': ("There isn't much chicken left for dinner.", 'На ужин осталось немного курицы.'),
    }
    seen = 0
    for i, r in enumerate(extra['table']):
        if r.get('example') in swaps:
            en, ru = swaps[r['example']]
            extra['table'][i] = base._set_example(r, en, ru)
            seen += 1
    assert seen == 6, seen
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_15'] = theory_A1_15


# ===================================================== A1_16 have got =====
# The authored file was written for a different word list (tablet, leash,
# scooter, SIM card, earbuds, tote bag, smartwatch, power bank, raincoat,
# keychain, cardholder, houseplant, ukulele, bank card, contact lenses,
# ID card, lip balm, driver's license) — none of it is module vocabulary
# (bag, phone, keys, wallet, watch, notebook, passport, ticket, photo, toy,
# umbrella, glasses, mirror, water bottle, pen, pencil, book, backpack,
# charger, comb). Every item is re-lexicalised onto the module list; the
# grammar (have / has / have got, negatives, questions) is untouched.
T = 'A1_16'
base.EDITS[T] = {}
_EN = [
    ('SIM card plan', 'phone'), ('SIM card', 'charger'),
    ('dog leash', 'backpack'), ('leash', 'backpack'),
    ('scooter', 'pencil'),
    ('earbuds', 'glasses'),
    ('tote bags', 'bags'), ('tote bag', 'bag'),
    ('smartwatches', 'watches'), ('smartwatch', 'watch'),
    ('power bank', 'charger'),
    ('a raincoat', 'an umbrella'), ('raincoat', 'umbrella'),
    ('keychain', 'ticket'),
    ('a cardholder in his wallet', 'a photo in his wallet'), ('cardholder', 'wallet'),
    ('houseplants on every windowsill', 'photos on every wall'), ('houseplant', 'mirror'),
    ('ukulele and play every evening', 'phone and call me every evening'), ('ukulele', 'book'),
    ('my bank card, so I can\'t pay', "my wallet, so I can't pay"), ('bank card', 'water bottle'),
    ('contact lenses or do you wear glasses', 'CONTACTS or do you wear glasses'),  # keep this one
    ('contact lenses', 'keys'), ('CONTACTS', 'contact lenses'),
    ('an ID card', 'a passport'), ('ID card', 'passport'),
    ('any lip balm', 'any pens'), ('a lip balm', 'a pen'), ('lip balm', 'a pen'),
    ("driver's license", 'passport'), ('driver’s license', 'passport'),
    ('a red collar on its neck', 'a small toy'),
    ('tablet', 'notebook'),
]
_RU = [
    ('тарифный план', 'телефон'), ('СИМ-карта', 'зарядка'), ('СИМ-карту', 'зарядку'), ('СИМ-карты', 'зарядки'),
    ('поводок для собаки', 'рюкзак'), ('поводка', 'рюкзака'), ('поводок', 'рюкзак'),
    ('самокат', 'карандаш'),
    ('наушники-вкладыши', 'очки'), ('наушников-вкладышей', 'очков'), ('наушники', 'очки'), ('наушников', 'очков'),
    ('сумка-тоут', 'сумка'), ('сумку-тоут', 'сумку'), ('сумки-тоут', 'сумки'),
    ('смарт-часы', 'часы'), ('смарт-часов', 'часов'),
    ('повербанка', 'зарядника'), ('повербанк', 'зарядник'),
    ('дождевика', 'зонта'), ('дождевик', 'зонт'),
    ('брелока', 'билета'), ('брелок', 'билет'),
    ('картхолдер в кошельке', 'фото в кошельке'), ('картхолдера', 'кошелька'), ('картхолдер', 'кошелёк'),
    ('комнатные растения', 'зеркала'), ('комнатное растение', 'зеркало'),
    ('укулеле, и они играют', 'телефон, и они звонят мне'), ('укулеле', 'книга'),
    ('банковской карты, поэтому', 'кошелька, поэтому'), ('банковская карта', 'бутылка воды'), ('банковской карты', 'бутылки воды'),
    ('контактные линзы или вы носите очки', 'КОНТАКТЫ или вы носите очки'),
    ('контактные линзы', 'ключи'), ('контактных линз', 'ключей'), ('КОНТАКТЫ', 'контактные линзы'),
    ('удостоверения личности', 'паспорта'), ('удостоверение личности', 'паспорт'),
    ('бальзам для губ', 'ручка'), ('бальзама для губ', 'ручки'),
    ('водительских прав', 'паспорта'), ('водительские права', 'паспорт'),
    ('красный ошейник на шее', 'маленькая игрушка'),
    ('планшета', 'блокнота'), ('планшет', 'блокнот'),
    ('СИМ-карт', 'зарядок'),
]


def _relex(text: str) -> str:
    for old, new in _EN + _RU:
        text = text.replace(old, new)
    return text


def _relex_content(content: dict) -> dict:
    out = {}
    for key, value in content.items():
        if isinstance(value, str):
            out[key] = _relex(value)
        elif isinstance(value, list):
            out[key] = [_relex(v) if isinstance(v, str) else v for v in value]
        else:
            out[key] = value
    return out


import re  # noqa: E402
_TOKEN_RE = re.compile(r"[A-Za-z0-9'’]+|[.!?,]")


def _scramble(sentence: str, seed: str) -> list[str]:
    import random
    tokens = _TOKEN_RE.findall(sentence)
    rng = random.Random(seed)
    for _ in range(20):
        shuffled = tokens[:]
        rng.shuffle(shuffled)
        if shuffled != tokens:
            return shuffled
    return tokens[::-1]


def register_relex(topic: str) -> None:
    data = base._load_json(BEFORE / f'grammar_extra_{topic}.json')
    for session in data['sessions']:
        for exercise in session['exercises']:
            slot = (session['session_number'], exercise['order'])
            if slot in base.EDITS[topic]:
                continue
            old = exercise['content']
            new = _relex_content(old)
            if exercise['exercise_type'] == 'reorder' and new['correct_answer'] != old['correct_answer']:
                new['words'] = _scramble(new['correct_answer'], f'{topic}-{slot}')
                if new.get('alternatives'):
                    new['alternatives'] = [_relex(a) for a in new['alternatives']]
            if new != old:
                base.EDITS[topic][slot] = {'kind': 'fix', 'patch': {k: v for k, v in new.items() if v != old.get(k)}}


# Manual items first (they win over the bulk re-lexicalisation).
fix(T, 2, 6,
    question='The child ___ a small toy.',
    explanation='«The child» — третье лицо единственного числа, поэтому «has». «The child has a small toy.» — У ребёнка есть маленькая игрушка.')
fix(T, 3, 5,
    question='We ___ got water bottles for the gym.',
    explanation='С «we» используется «have got». «We have got water bottles for the gym.» — У нас есть бутылки воды для спортзала.')
fix(T, 2, 3,
    question='My parents ___ got a mirror in the kitchen.',
    explanation='«My parents» — множественное число, поэтому «have got». «My parents have got a mirror in the kitchen.» — У моих родителей есть зеркало на кухне.')
register_relex(T)


def theory_A1_16(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert [s['subtitle'] for s in sections] == [
        'Утверждение (Affirmative)', 'Have got / Has got', 'Отрицание (Negative)', 'Вопрос (Question)',
        'Дополнительные примеры со словарём модуля'], [s['subtitle'] for s in sections]
    # rules items with pattern/example/translation are rendered by neither template → tables.
    tables = [
        [row(pronoun='I / You / We / They', form='have', example='I have a phone.', translation='У меня есть телефон.'),
         row(pronoun='He / She / It', form='has', example='She has a bag.', translation='У неё есть сумка.')],
        [row(pronoun='I / You / We / They', form="have got ('ve got)", example="I've got a passport.", translation='У меня есть паспорт.'),
         row(pronoun='He / She / It', form="has got ('s got)", example="She's got an umbrella.", translation='У неё есть зонт.')],
        [row(pronoun='I / You / We / They', form="don't have", example="I don't have a ticket.", translation='У меня нет билета.'),
         row(pronoun='He / She / It', form="doesn't have", example="She doesn't have a comb.", translation='У неё нет расчёски.'),
         row(pronoun='I / You / We / They', form="haven't got", example="I haven't got my keys.", translation='У меня нет с собой ключей.'),
         row(pronoun='He / She / It', form="hasn't got", example="He hasn't got a charger.", translation='У него нет зарядного устройства.')],
        [row(pronoun='Do + I / you / we / they', form='have …?', example='Do you have a pen?', translation='У тебя есть ручка?'),
         row(pronoun='Does + he / she / it', form='have …?', example='Does she have a mirror?', translation='У неё есть зеркало?'),
         row(pronoun='Have + I / you / we / they', form='got …?', example='Have you got a pencil?', translation='У тебя есть карандаш?'),
         row(pronoun='Has + he / she / it', form='got …?', example='Has he got a water bottle?', translation='У него есть бутылка воды?')],
    ]
    for section, table in zip(sections[:4], tables):
        assert all('rule' not in r for r in section['rules']), section['subtitle']
        del section['rules']
        section['table'] = table
    sections[3]['description'] = ("Для вопросов используем Do/Does + have или Have/Has + got. Краткий ответ: "
                                  "Yes, I do. / No, I don't. — или Yes, I have. / No, I haven't.")
    extra = sections[4]
    extra['table'] = [row(example=en, translation=ru) for en, ru in [
        ('I have a bag and a backpack.', 'У меня есть сумка и рюкзак.'),
        ("I've got a new phone.", 'У меня новый телефон.'),
        ('She has got the keys.', 'У неё есть ключи.'),
        ("He hasn't got a wallet.", 'У него нет кошелька.'),
        ('Do you have a watch?', 'У тебя есть часы?'),
        ('I have a notebook and a pen.', 'У меня есть тетрадь и ручка.'),
        ("Has she got a passport? — Yes, she has.", 'У неё есть паспорт? — Да.'),
        ("We don't have tickets.", 'У нас нет билетов.'),
        ('I have a photo of my family in my wallet.', 'У меня в кошельке есть фото семьи.'),
        ('My son has got a new toy.', 'У моего сына новая игрушка.'),
        ("Have you got an umbrella? — No, I haven't.", 'У тебя есть зонт? — Нет.'),
        ('My grandfather has glasses.', 'У моего дедушки есть очки.'),
        ('She has a small mirror in her bag.', 'У неё в сумке маленькое зеркало.'),
        ("I haven't got my water bottle with me.", 'У меня нет с собой бутылки воды.'),
        ('Does he have a pencil? — No, he doesn\'t.', 'У него есть карандаш? — Нет.'),
        ('They have a lot of books.', 'У них много книг.'),
        ("I've got a charger for my phone.", 'У меня есть зарядка для телефона.'),
        ("She hasn't got a comb.", 'У неё нет расчёски.'),
    ]]
    notes = list(new['important_notes'])
    notes.append("💡 Краткий ответ: Do you have…? — Yes, I do. / Have you got…? — Yes, I have.")
    new['important_notes'] = notes
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_16'] = theory_A1_16


# Post-fixes on the bulk re-lexicalisation of A1_16.
def _patch_explanation(topic: str, slot: tuple[int, int], old: str, new: str) -> None:
    patch = base.EDITS[topic][slot]['patch']
    assert old in patch['explanation'], (topic, slot, old)
    patch['explanation'] = patch['explanation'].replace(old, new)


_patch_explanation('A1_16', (5, 10), 'an + passport', 'a + passport')
_patch_explanation('A1_16', (7, 9), 'an + passport', 'a + passport')
_patch_explanation('A1_16', (6, 10), 'a + umbrella', 'an + umbrella')
base.EDITS['A1_16'][(3, 2)]['patch'].update(
    question='You and I ___ passports.',
    explanation='«You and I» — это «we», множественное число, поэтому «have». «You and I have passports.» — У нас с тобой есть паспорта.')


def _swap_examples(section: dict, swaps: dict[str, tuple[str, str]]) -> None:
    seen = 0
    for i, r in enumerate(section['table']):
        if isinstance(r, dict) and r.get('example') in swaps:
            en, ru = swaps[r['example']]
            section['table'][i] = base._set_example(r, en, ru)
            seen += 1
    assert seen == len(swaps), (section.get('subtitle'), seen, len(swaps))


# ======================================================== A1_1 to be =====
T = 'A1_1'
base.EDITS[T] = {}
fix(T, 4, 5, correct_answer='This room is not very big.',
    alternatives=["This room isn't very big.", 'This room is not big.', "This room isn't big."],
    explanation='This room — единственное число (= it), используется is not / isn\'t. «Не очень большая» = not very big. '
                'Перевод: This room is not very big.')
fix(T, 6, 6, alternatives=["Yes, I am. / No, I'm not.", 'Yes, I am happy. / No, I am not happy.'])
fix(T, 8, 6, alternatives=['Is he an engineer? — Yes.', 'Is he an engineer? — Yes, he is'])


def theory_A1_1(content: dict) -> dict:
    new = copy.deepcopy(content)
    assert not new.get('rule'), new.get('rule')
    new['rule'] = ('Глагол be (am / is / are) связывает подлежащее с именем, профессией, состоянием или местом; '
                   'в английском предложении его нельзя опустить: I am a student, She is happy.')
    return new


THEORY['A1_1'] = theory_A1_1

# ========================================================= A1_2 a / an ===
T = 'A1_2'
base.EDITS[T] = {}


def theory_A1_2(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[1]['subtitle'] == 'Когда использовать AN' and len(sections[1]['table']) == 1, sections[1]
    sections[1]['table'] += [
        {'article': 'an', 'word': 'apple', 'example': 'I want an apple.', 'translation': 'Я хочу яблоко.'},
        {'article': 'an', 'word': 'egg', 'example': 'There is an egg in the box.', 'translation': 'В коробке яйцо.'},
        {'article': 'an', 'word': 'old lamp', 'example': 'This is an old lamp.', 'translation': 'Это старая лампа.'},
        {'article': 'an', 'word': 'hour (немая h)', 'example': 'I need an hour.', 'translation': 'Мне нужен час.'},
    ]
    assert sections[4]['subtitle'].startswith('Употребление в утверждении'), sections[4]['subtitle']
    sections[4]['subtitle'] = 'Без артикля: множественное число и неисчисляемые'
    sections[4]['description'] = ('A/an ставится только перед исчисляемым существительным в единственном числе. '
                                  'Перед множественным числом и неисчисляемыми артикля a/an нет.')
    sections[4]['table'] = [
        row(pronoun='headphones', form='мн. число — без a/an', example='I have headphones.', translation='У меня есть наушники.'),
        row(pronoun='scissors', form='мн. число — без a/an', example='I need scissors.', translation='Мне нужны ножницы.'),
        row(pronoun='keys', form='мн. число — без a/an', example='These are my keys.', translation='Это мои ключи.'),
        row(pronoun='soap', form='неисчисляемое — без a/an', example='This is soap.', translation='Это мыло.'),
        row(pronoun='glue', form='неисчисляемое — без a/an', example='I need glue.', translation='Мне нужен клей.'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_2'] = theory_A1_2

# ================================================ A1_3 demonstratives ====
T = 'A1_3'
base.EDITS[T] = {}


def theory_A1_3(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'I need new clothes.': ('These are my new clothes.', 'Это моя новая одежда.'),
        'He is wearing a white shirt.': ('That shirt is white.', 'Та рубашка белая.'),
        'She has a red skirt.': ('This skirt is red.', 'Эта юбка красная.'),
        'I need new boots.': ('Those boots are mine.', 'Те ботинки мои.'),
    })
    return new


THEORY['A1_3'] = theory_A1_3

# ====================================== A1_4 plurals + demonstratives ====
T = 'A1_4'
base.EDITS[T] = {}


def theory_A1_4(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[3]['subtitle'].startswith('Таблица THIS'), sections[3]['subtitle']
    assert isinstance(sections[3]['table'][0], list), sections[3]['table'][0]
    # list-of-lists rows are skipped by both templates → dict rows.
    sections[3]['table'] = [
        row(pronoun='близко (near)', form='this → these', example='This is a red one. / These are red ones.',
            translation='Вот красное. / Вот красные.'),
        row(pronoun='далеко (far)', form='that → those', example='That is a blue one. / Those are blue ones.',
            translation='Вон то синее. / Вон те синие.'),
    ]
    # The exercises test plural formation (boxes, babies, knives, children …) — the theory had no such section.
    sections.insert(1, {
        'subtitle': 'Образование множественного числа',
        'description': 'Обычно к существительному добавляется -s; после -s, -x, -ch, -sh — -es; согласная + y → -ies; '
                       '-f / -fe → -ves. Несколько частых слов образуют множественное число не по правилу.',
        'table': [
            row(pronoun='+ s', form='обычные слова', example='one cat → two cats, one book → three books',
                translation='кот → коты, книга → книги'),
            row(pronoun='+ es', form='после -s, -x, -ch, -sh', example='bus → buses, box → boxes, watch → watches',
                translation='автобус → автобусы, коробка → коробки, часы'),
            row(pronoun='y → ies', form='согласная + y', example='baby → babies, city → cities',
                translation='малыш → малыши, город → города'),
            row(pronoun='f → ves', form='-f / -fe', example='knife → knives, shelf → shelves',
                translation='нож → ножи, полка → полки'),
            row(pronoun='исключения', form='особые формы', example='child → children, man → men, woman → women',
                translation='ребёнок → дети, мужчина → мужчины, женщина → женщины'),
            row(pronoun='исключения', form='особые формы', example='tooth → teeth, foot → feet, mouse → mice, person → people',
                translation='зуб → зубы, ступня → ступни, мышь → мыши, человек → люди'),
            row(pronoun='без изменений', form='одна форма', example='one sheep → two sheep, one fish → many fish',
                translation='овца → овцы, рыба → рыбы'),
        ],
    })
    new['rule'] = ('Существительные бывают в единственном и множественном числе: cat → cats, box → boxes, child → children. '
                   'This/that — для одного предмета, these/those — для нескольких.')
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_4'] = theory_A1_4

# ===================================================== A1_5 there is ====
T = 'A1_5'
base.EDITS[T] = {}
replace(T, 3, 2, 'fill_blank',
        question='Is there a bank near here? — Yes, there ___.', correct_answer='is', alternatives=[],
        explanation='Краткий ответ повторяет is/are: Is there…? — Yes, there is. / No, there isn\'t. '
                    'Перевод: Здесь рядом есть банк? — Да.')
replace(T, 5, 4, 'multiple_choice',
        question="Are there any shops on this street? — No, there ___.", correct_answer="aren't",
        options=["aren't", "isn't", 'are', "don't"],
        explanation="Краткий отрицательный ответ на Are there…? — No, there aren't. (isn't — для Is there…?) "
                    'Перевод: На этой улице есть магазины? — Нет.')


def theory_A1_5(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[2]['subtitle'] == 'Отрицательная форма' and sections[3]['subtitle'] == 'Вопросительная форма', [s['subtitle'] for s in sections]
    sections[2]['description'] = "Для отрицания добавляем no после there is/are — или используем isn't / aren't + any."
    sections[2]['table'] += [
        row(form="There isn't a / any", example="There isn't a computer in my room.", translation='В моей комнате нет компьютера.'),
        row(form="There aren't any", example="There aren't any pictures on the wall.", translation='На стене нет картин.'),
    ]
    sections[3]['description'] = ('Меняем порядок слов: is/are ставим перед there. Краткий ответ повторяет is/are: '
                                  "Yes, there is. / No, there aren't.")
    sections[3]['table'] += [
        row(form='Краткий ответ', example="Is there a pen on the desk? — Yes, there is. / No, there isn't.",
            translation='На парте есть ручка? — Да. / Нет.'),
        row(form='Краткий ответ', example="Are there books in your schoolbag? — Yes, there are. / No, there aren't.",
            translation='В твоей сумке есть книги? — Да. / Нет.'),
    ]
    _swap_examples(sections[4], {
        'I have a pen.': ('There is a pen on the desk.', 'На парте (есть) ручка.'),
        'The curtain is blue.': ('There are blue curtains in the room.', 'В комнате синие шторы.'),
        'The door is open.': ('Is there a door in this wall?', 'В этой стене есть дверь?'),
        'My schoolbag is on the chair.': ('There is a schoolbag on the chair.', 'На стуле (есть) школьная сумка.'),
        'I need a ruler.': ("There isn't a ruler in my pencil case.", 'В моём пенале нет линейки.'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_5'] = theory_A1_5

# ================================================== A1_6 possessives ====
T = 'A1_6'
base.EDITS[T] = {}


def theory_A1_6(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert new['rule'].startswith('Притяжательные местоимения показывают принадлежность (чей?'), new['rule']
    new['rule'] = ('Притяжательные местоимения (my, your, his, her, its, our, their) и притяжательный падеж (Tom\'s) '
                   'показывают принадлежность — отвечают на вопрос «чей?».')
    assert sections[0]['subtitle'] == 'Притяжательные местоимения', sections[0]['subtitle']
    sections[0]['table'].insert(5, row(form='its', example='The dog is in its bed.', translation='Собака в своей корзинке.'))
    _swap_examples(sections[3], {'The child is playing.': ("The child's toys are on the floor.", 'Игрушки ребёнка на полу.')})
    absolute = sections[4]
    assert absolute['subtitle'].startswith('Употребление в утверждении'), absolute['subtitle']
    absolute['subtitle'] = 'Абсолютные формы: mine, yours, his, hers, ours, theirs'
    absolute['description'] = ('Перед существительным — my / your / her…; без существительного — mine / yours / hers…: '
                               'This is my pen. → This pen is mine.')
    absolute['table'] = [
        row(pronoun='my → mine', example='This pen is mine.', translation='Эта ручка моя.'),
        row(pronoun='your → yours', example='Is this bag yours?', translation='Эта сумка твоя?'),
        row(pronoun='his → his', example='The car is his.', translation='Машина его.'),
        row(pronoun='her → hers', example='The cat is hers.', translation='Кошка её.'),
        row(pronoun='our → ours', example='This house is ours.', translation='Этот дом наш.'),
        row(pronoun='their → theirs', example='The garden is theirs.', translation='Сад их.'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_6'] = theory_A1_6

# ======================================= A1_7 prepositions of place =====
T = 'A1_7'
base.EDITS[T] = {}
fix(T, 2, 6, question='The lamp is ___ the sofa.',
    explanation='Предлог next to означает «рядом с». Лампа стоит рядом с диваном. Перевод: Лампа рядом с диваном.')


def theory_A1_7(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[0]['subtitle'] == 'Основные предлоги места', sections[0]['subtitle']
    sections[0]['table'] += [
        row(form='above / over (над)', example='The picture is above the sofa.', translation='Картина над диваном.'),
        row(form='at (у, за — рабочее место)', example='Dad is at the desk.', translation='Папа за письменным столом.'),
    ]
    _swap_examples(sections[4], {
        'This is my house.': ('My house is between the school and the park.', 'Мой дом между школой и парком.'),
        'The room is big.': ('The bed is under the window.', 'Кровать под окном.'),
        'The bathroom is upstairs.': ('The bathroom is next to the bedroom.', 'Ванная рядом со спальней.'),
        'The curtains are blue.': ('The curtains are in front of the window.', 'Шторы перед окном.'),
    })
    return new


THEORY['A1_7'] = theory_A1_7

# ======================================================= A1_8 at/on/in ===
T = 'A1_8'
base.EDITS[T] = {}
fix(T, 3, 6, options=['in', 'on', 'by', 'for'], correct_answer='on',
    explanation='В этом курсе — американский вариант: on the weekend (британцы говорят at the weekend). '
                'Перевод: Мы отдыхаем в выходные.')
fix(T, 6, 2, options=['in', 'on', 'for', 'during'], correct_answer='on',
    explanation='В этом курсе — американский вариант: on the weekend (британцы говорят at the weekend). '
                'Перевод: Мы ходим в поход в выходные.')
fix(T, 4, 6, correct_answer='They usually rest on the weekend.',
    alternatives=['They usually relax on the weekend.', 'They usually rest at the weekend.', 'They usually relax at the weekend.'],
    explanation='On the weekend (американский вариант, как в теории курса) или at the weekend (британский) — оба принимаются. '
                'Перевод: They usually rest on the weekend.')


def theory_A1_8(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[4]['subtitle'].startswith('Употребление в утверждении'), sections[4]['subtitle']
    sections[4]['subtitle'] = 'Без предлога: today, tomorrow, yesterday, every day, this / next / last …'
    sections[4]['description'] = ('Перед today, tomorrow, yesterday, every day и выражениями с this / next / last '
                                  'предлог не ставится: I am busy today (не on today).')
    sections[4]['table'] = [
        row(time_expression='today', translation='сегодня', example='I am busy today.', example_translation='Я сегодня занят.'),
        row(time_expression='tomorrow', translation='завтра', example='See you tomorrow!', example_translation='Увидимся завтра!'),
        row(time_expression='yesterday', translation='вчера', example='It rained yesterday.', example_translation='Вчера шёл дождь.'),
        row(time_expression='every day', translation='каждый день', example='We work every day.', example_translation='Мы работаем каждый день.'),
        row(time_expression='next Friday', translation='в следующую пятницу', example='The party is next Friday.', example_translation='Вечеринка в следующую пятницу.'),
        row(time_expression='this week', translation='на этой неделе', example='I have a test this week.', example_translation='На этой неделе у меня тест.'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY['A1_8'] = theory_A1_8

# ========================================================== A1_9 It =====
T = 'A1_9'
base.EDITS[T] = {}
replace(T, 4, 8, 'error_correction',
        sentence='Is very hot and sunny today.', correct_answer='It is very hot and sunny today.',
        error_word='Is', correct_word='It is', alternatives=['It is', "It's"],
        explanation='Ошибка: пропущено формальное подлежащее It. Предложение не может начинаться с глагола без подлежащего. '
                    'Правильно: It is very hot and sunny today — Сегодня очень жарко и солнечно.')
THEORY['A1_9'] = lambda content: copy.deepcopy(content)


# ================================================================ main ===
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not BEFORE.exists():
        print(f'snapshot dir missing: {BEFORE}', file=sys.stderr)
        return 2
    base.BEFORE = BEFORE
    base.ASSERT_LABEL = 'item24'
    base.TOPICS.clear()
    base.TOPICS.update(topic_meta())
    base.THEORY.clear()
    base.THEORY.update(THEORY)
    all_changes, theory, outputs = {}, {}, []
    for topic in sorted(base.TOPICS, key=lambda t: int(t.split('_')[1])):
        base.EDITS.setdefault(topic, {})
        data, changes = base.build_exercises(topic)
        base.validate_exercises(topic, data)
        module, old_extra, new_extra = base.build_theory(topic)
        theory_changed = old_extra != new_extra
        kinds = {'fix': 0, 'replace': 0}
        for change in changes:
            kinds[change['kind']] += 1
        print(f"{topic}: {len(changes)} exercise edits (fix {kinds['fix']}, replace {kinds['replace']}); "
              f"theory {'changed' if theory_changed else 'unchanged'} "
              f"(sections {len(old_extra['sections'])} -> {len(new_extra['sections'])})")
        if changes:
            all_changes[topic] = changes
            outputs.append((base.EXTRA_DIR / f'grammar_extra_{topic}.json', data))
        if theory_changed:
            theory[topic] = (old_extra, new_extra)
            outputs.append((base.MODULE_DIR / base.TOPICS[topic]['module_file'], module))
    total = sum(len(c) for c in all_changes.values())
    print(f'TOTAL: {total} exercise edits in {len(all_changes)} topics; theory in {len(theory)} modules')
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
