#!/usr/bin/env python3
"""Lesson audit item 20 — grammar content of topics a1-10, a1-11, a2-15.

Rewrites the authored exercise files (``grammar_exercises_extra``) and the
theory of lesson 4 of the three modules (``module_completed/fixed``) from
the snapshot taken before the edit (``local_exports/grammar_extra_3topics_before``),
and emits the prod SQL (check / apply / rollback) that carries the same
change to ``grammar_exercises``, ``lessons.content`` and
``grammar_topics.content``.

Every exercise edit is addressed by its slot ``(session, order)`` in the
source file and carries a kind:

* ``fix``     — the same exercise with corrected text (hint, explanation,
                alternatives …): prod row is UPDATEd in place, learner
                history on it survives;
* ``replace`` — a different exercise in the slot: a new row is INSERTed and
                the old one DELETEd (its history goes with it — Codex review:
                SRS state of the old item must not be inherited by a new one).

Prod rows are located by exact content (``topic_id``, ``exercise_type``,
``content - 'source'``) — never by id: the 240 json_import rows of the three
topics are unique by content. ``order`` repeats 1..10 per session and
reorder items have no question text, so content is the only safe key.

Usage::

    venv/bin/python scripts/fix_grammar_topics_3.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_topics_3.py --check    # diff only
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / 'local_exports' / 'grammar_extra_3topics_before'
EXTRA_DIR = ROOT / 'grammar_exercises_extra'
MODULE_DIR = ROOT / 'module_completed' / 'fixed'
EXPORT_DIR = ROOT / 'local_exports'
SQL_PREFIX = 'item20_grammar_3topics'
ASSERT_LABEL = 'item20'  # prefix of the DO-block notices; item 21 reuses emit_sql with its own label

TOPICS = {
    'A1_10': {'slug': 'a1-10', 'level': 'A1', 'module': 10,
              'module_file': 'module_A1_10_daily_routine.json'},
    'A1_11': {'slug': 'a1-11', 'level': 'A1', 'module': 11,
              'module_file': 'module_A1_11_professions.json'},
    'A2_15': {'slug': 'a2-15', 'level': 'A2', 'module': 15,
              'module_file': 'module_A2_15_household_chores.json'},
}
EXTRA_KEYS = ('rule', 'description', 'sections', 'important_notes', 'tldr', 'summary')
# grammar_topics.content has no ``description`` — it is patched on the lesson only.
TOPIC_KEYS = tuple(k for k in EXTRA_KEYS if k != 'description')


def difficulty_for(session: int) -> int:
    return 1 if session <= 3 else 2 if session <= 5 else 3


# --------------------------------------------------------------------------
# Exercise edits. ``fix`` merges ``patch`` into the old content (type kept);
# ``replace`` puts a new exercise into the slot.
# --------------------------------------------------------------------------
EDITS: dict[str, dict[tuple[int, int], dict]] = {'A1_10': {}, 'A1_11': {}, 'A2_15': {}}


def fix(topic: str, session: int, order: int, **patch) -> None:
    EDITS[topic][(session, order)] = {'kind': 'fix', 'patch': patch}


def replace(topic: str, session: int, order: int, exercise_type: str, **content) -> None:
    EDITS[topic][(session, order)] = {'kind': 'replace', 'type': exercise_type, 'content': content}


# ---------------------------------------------------------------- A1_10 ---
T = 'A1_10'
fix(T, 1, 10,
    words=['his', 'homework', 'every', 'does', 'afternoon', '.', 'Nick'],
    correct_answer='Nick does his homework every afternoon.',
    explanation='Правило: Nick — 3-е лицо ед.ч. (he), do → does (глагол на -o). '
                'Перевод: Ник делает домашнее задание каждый день после обеда.')
fix(T, 2, 10,
    explanation='Правило: Lisa — 3-е лицо ед.ч. (she), brush → brushes. '
                'Перевод: Лиза чистит зубы на ночь.')
replace(T, 3, 7, 'true_false',
        statement="Глагол 'watch' в 3-м лице единственного числа получает окончание -es: he watches.",
        correct_answer=True,
        explanation='Верно! Правило: глаголы на -ch, -sh, -s, -ss, -x, -o добавляют -es. '
                    'watch → watches, wash → washes, go → goes. Пример: He watches TV after dinner.')
fix(T, 4, 2,
    explanation='Правило: You and your friends — это «вы» (множественное число), '
                'поэтому глагол без окончания -s: go. Перевод: Ты и твои друзья ездите на работу на велосипеде.')
fix(T, 5, 2,
    question='My parents ___ (sleep) eight hours every night.',
    explanation='Правило: My parents — 3-е лицо мн.ч. (they), глагол без изменений. '
                'They sleep (не sleeps). Перевод: Мои родители спят восемь часов каждую ночь.')
fix(T, 5, 5,
    alternatives=['My mum works at a library and reads many books.',
                  'My mum works in a library and reads a lot of books.',
                  'My mum works in a library and reads lots of books.'])
fix(T, 6, 1,
    question='At midday, my grandmother ___ (have) lunch with us at the table.',
    explanation='Правило: my grandmother — 3-е лицо ед.ч. (she), have → has. '
                'Перевод: В полдень моя бабушка обедает с нами за столом.')
fix(T, 6, 2,
    question='Every morning my brother ___ (brush) his teeth, and then he has breakfast.',
    correct_answer='brushes',
    options=['brush', 'brushs', 'brushes', 'brushing'],
    explanation='Правило: глаголы на -sh добавляют -es. My brother — 3-е лицо ед.ч. (he), '
                'поэтому brush → brushes. Перевод: Каждое утро мой брат чистит зубы, а потом завтракает.')
fix(T, 6, 5,
    question='Мой друг просыпается в семь, умывается и идёт на работу.',
    correct_answer='My friend wakes up at seven, washes his face and goes to work.',
    alternatives=['My friend wakes up at seven, washes and goes to work.',
                  'My friend wakes up at 7, washes his face and goes to work.'],
    explanation='Правило: My friend — 3-е лицо ед.ч. wake up → wakes up, wash → washes, go → goes. '
                'Все три глагола получают -s/-es. Перевод: My friend wakes up at seven, washes his face and goes to work.')
fix(T, 6, 7,
    explanation='Ошибка: Kate — 3-е лицо ед.ч. (she). Первый глагол нужно изменить: get up → gets up; '
                'washes уже стоит в верной форме. Правильно: At sunrise, Kate gets up and washes her face.')
replace(T, 7, 3, 'true_false',
        statement="У глагола 'have' в 3-м лице единственного числа особая форма 'has': She has breakfast at eight.",
        correct_answer=True,
        explanation='Верно! Правило: have — особый глагол, для he/she/it используется has, а не haves. '
                    'Пример: She has breakfast at eight. He has a car.')
replace(T, 7, 8, 'error_correction',
        sentence='My brother read a book before going to sleep every night.',
        correct_answer='My brother reads a book before going to sleep every night.',
        error_word='read', correct_word='reads', alternatives=['reads'],
        explanation='Ошибка: My brother — 3-е лицо ед.ч. (he), глагол требует -s: read → reads. '
                    'Правильно: My brother reads a book before going to sleep every night.')

# ---------------------------------------------------------------- A1_11 ---
T = 'A1_11'
fix(T, 1, 2,
    question='They ___ (not) work as pilots.',
    explanation='Сделайте отрицание: с they (мн. число) — don\'t (do not) + базовая форма work. '
                'Перевод: Они не работают пилотами.')
replace(T, 2, 4, 'multiple_choice',
        question='Do you work as a nurse? — Yes, I ___.',
        correct_answer='do', options=['do', 'does', 'am', "don't"],
        explanation='Краткий ответ повторяет вспомогательный глагол вопроса: Do you …? — Yes, I do. '
                    'Перевод: Ты работаешь медсестрой? — Да.')
replace(T, 3, 1, 'fill_blank',
        question="Does your brother work as a driver? — No, he ___.",
        correct_answer="doesn't", alternatives=['does not'],
        explanation="Краткий отрицательный ответ для he: No, he doesn't (does not). "
                    'Перевод: Твой брат работает водителем? — Нет.')
replace(T, 3, 5, 'multiple_choice',
        question='What ___ your father do? — He is a mechanic.',
        correct_answer='does', options=['do', 'does', 'is', 'are'],
        explanation='Вопрос «кем работает»: What + does + подлежащее + do? Your father — 3-е лицо ед. числа, '
                    'поэтому does. Перевод: Кем работает твой отец? — Он механик.')
fix(T, 3, 8,
    question='Ты работаешь бухгалтером?',
    alternatives=['Do you work as a bookkeeper?'],
    explanation='С you вопрос образуется с Do: Do + you + базовая форма work. '
                'Перевод: Do you work as an accountant?')
replace(T, 4, 1, 'fill_blank',
        question='Where ___ your sister work?',
        correct_answer='does', alternatives=[],
        explanation='Вопросительное слово ставится перед does: Where + does + your sister + work? '
                    'Your sister — 3-е лицо ед. числа. Перевод: Где работает твоя сестра?')
replace(T, 4, 3, 'multiple_choice',
        question='What ___ you do? — I am a nurse.',
        correct_answer='do', options=['do', 'does', 'are', 'is'],
        explanation='«What do you do?» — вопрос о профессии: What + do + you + do? '
                    'Перевод: Кем ты работаешь? — Я медсестра.')
fix(T, 4, 5,
    alternatives=['Does your dad work as an engineer?'],
    explanation='Your father = he, 3-е лицо: Does your father work as an engineer? '
                'После does — базовая форма work. Перевод: Твой отец работает инженером?')
replace(T, 5, 3, 'multiple_choice',
        question='Does the pilot fly every day? — Yes, he ___.',
        correct_answer='does', options=['do', 'does', 'is', 'flies'],
        explanation='В кратком ответе повторяется вспомогательный глагол, а не смысловой: Yes, he does '
                    '(не Yes, he flies). Перевод: Пилот летает каждый день? — Да.')
replace(T, 6, 1, 'fill_blank',
        question='What time ___ the waiter start work?',
        correct_answer='does', alternatives=[],
        explanation='Вопрос со словом What time: What time + does + the waiter + start? '
                    'The waiter — 3-е лицо ед. числа. Перевод: Во сколько официант начинает работу?')
replace(T, 6, 6, 'translation',
        question='Кем работает твой отец?',
        correct_answer='What does your father do?',
        alternatives=['What does your dad do?', 'What does your father do for a living?'],
        explanation='Вопрос о профессии: What + does + подлежащее + do? Your father — 3-е лицо ед. числа. '
                    'Перевод: What does your father do?')
replace(T, 7, 2, 'multiple_choice',
        question='Do the doctors work at night? — No, they ___.',
        correct_answer="don't", options=["don't", "doesn't", "aren't", 'not'],
        explanation="Краткий отрицательный ответ для they: No, they don't. "
                    'Перевод: Врачи работают ночью? — Нет.')
replace(T, 7, 5, 'translation',
        question='Где работают твои родители?',
        correct_answer='Where do your parents work?',
        alternatives=['Where do your mum and dad work?'],
        explanation='Your parents = they (мн. число): Where + do + your parents + work? '
                    'Перевод: Where do your parents work?')
replace(T, 8, 1, 'fill_blank',
        question='How many hours ___ a nurse work every day?',
        correct_answer='does', alternatives=[],
        explanation='Вопрос с How many: How many hours + does + a nurse + work? '
                    'A nurse — 3-е лицо ед. числа. Перевод: Сколько часов медсестра работает каждый день?')
fix(T, 8, 3,
    explanation='Неверно. Это отрицательное предложение: don\'t стоит после подлежащего they. '
                'В вопросе вспомогательный глагол выносится на первое место: Do they drive trucks?')
fix(T, 8, 6,
    alternatives=['Do you work as an architect or as an engineer?'],
    explanation='С you вопрос: Do + you + базовая форма work. Перевод: Do you work as an architect or an engineer?')

# ---------------------------------------------------------------- A2_15 ---
T = 'A2_15'
# Session 1 (d1)
fix(T, 1, 1, question='Look! The cat ___ (sleep) on the sofa.')
fix(T, 1, 2, question='Right now the children ___ (play) in the garden.')
replace(T, 1, 3, 'fill_blank',
        question='Be quiet! Dad ___ (vacuum) the living room.',
        correct_answer='is vacuuming', alternatives=["'s vacuuming"],
        explanation='Dad — 3-е лицо ед. числа, поэтому is + vacuuming. Be quiet! подсказывает, что действие '
                    'идёт прямо сейчас. Перевод: Тише! Папа пылесосит гостиную.')
replace(T, 1, 6, 'multiple_choice',
        question='Look! Mum ___ the windows now.',
        correct_answer='is cleaning', options=['are cleaning', 'is cleaning', 'cleans', 'am cleaning'],
        explanation='Mum — 3-е лицо ед. числа, значит is + cleaning. Look! и now показывают, что действие '
                    'происходит прямо сейчас, поэтому не cleans. Перевод: Смотри! Мама сейчас моет окна.')
replace(T, 1, 10, 'reorder',
        words=['is', 'Mark', 'the', 'sweeping', 'now', 'yard', '.'],
        correct_answer='Mark is sweeping the yard now.',
        alternatives=['Now Mark is sweeping the yard.', 'Mark is now sweeping the yard.'],
        explanation='Present Continuous: Mark + is + sweeping. Now подсказывает, что действие идёт сейчас. '
                    'Перевод: Марк сейчас подметает двор.')
# Session 2 (d1)
fix(T, 2, 1, question='My sister ___ (write) a letter to her friend now.',
    explanation='My sister — 3-е лицо ед. числа, поэтому используется is + writing. При добавлении -ing к write '
                '«немая» e убирается: write → writing. Перевод: Моя сестра сейчас пишет письмо подруге.')
replace(T, 2, 2, 'fill_blank',
        question='The children ___ (tidy) their room at the moment.',
        correct_answer='are tidying', alternatives=["'re tidying"],
        explanation='The children — мн. число, поэтому are + tidying. У глаголов на -y буква y сохраняется: '
                    'tidy → tidying. Перевод: Дети сейчас прибирают свою комнату.')
fix(T, 2, 3, question='I ___ (listen) to music on my headphones right now.',
    explanation='С подлежащим I используется am + listening. Right now указывает на действие в данный момент. '
                'Перевод: Я прямо сейчас слушаю музыку в наушниках.')
fix(T, 2, 4, question='The dog ___ after a ball in the yard right now.',
    explanation='The dog — 3-е лицо ед. числа, поэтому ставится is + running. Right now показывает, что действие '
                'идёт сейчас, поэтому не runs. Run → running (удвоение согласной). Перевод: Собака прямо сейчас '
                'бежит за мячом во дворе.')
replace(T, 2, 5, 'multiple_choice',
        question='Anna and Ben ___ the dishes now.',
        correct_answer='are washing', options=['is washing', 'are washing', 'am washing', 'washes'],
        explanation='Anna and Ben — два человека (мн. число), поэтому are + washing. Now — действие сейчас. '
                    'Перевод: Анна и Бен сейчас моют посуду.')
replace(T, 2, 8, 'translation',
        question='Они сейчас моют посуду.',
        correct_answer='They are washing the dishes now.',
        alternatives=["They're washing the dishes now.", 'They are doing the dishes now.',
                      'They are washing the dishes right now.'],
        explanation='They — мн. число, поэтому are + washing. Перевод: They are washing the dishes now.')
replace(T, 2, 10, 'reorder',
        words=['now', 'the', 'is', 'ironing', 'Mum', 'shirts', '.'],
        correct_answer='Mum is ironing the shirts now.',
        alternatives=['Now Mum is ironing the shirts.', 'Mum is now ironing the shirts.'],
        explanation='Present Continuous: Mum + is + ironing. Now подсказывает, что действие происходит сейчас. '
                    'Перевод: Мама сейчас гладит рубашки.')
# Session 3 (d1)
fix(T, 3, 1, question='Dad ___ (wash) the car in the garage at the moment.')
replace(T, 3, 2, 'fill_blank',
        question='My friends ___ (help) me with the laundry today.',
        correct_answer='are helping', alternatives=["'re helping"],
        explanation='My friends — мн. число, поэтому are + helping. Today здесь означает «сегодня, в этот период». '
                    'Перевод: Мои друзья сегодня помогают мне со стиркой.')
fix(T, 3, 3, question='Look! It ___ (rain) outside. Take an umbrella!')
replace(T, 3, 4, 'multiple_choice',
        question='Laura ___ the shelves at the moment.',
        correct_answer='is dusting', options=['are dusting', 'is dusting', 'dusts', 'am dusting'],
        explanation='Laura — 3-е лицо ед. числа, поэтому is + dusting. At the moment — действие сейчас, '
                    'поэтому не dusts. Перевод: Лора в данный момент вытирает пыль с полок.')
fix(T, 3, 6, question='Mike ___ in the river with his brother right now.',
    explanation='Mike — 3-е лицо ед. числа, поэтому ставится is + swimming. Right now — действие сейчас, '
                'поэтому не swims. Swim → swimming (удвоение m). Перевод: Майк прямо сейчас плавает в реке с братом.')
replace(T, 3, 10, 'reorder',
        words=['Sara', 'the', 'is', 'sink', 'cleaning', 'now', '.'],
        correct_answer='Sara is cleaning the sink now.',
        alternatives=['Now Sara is cleaning the sink.', 'Sara is now cleaning the sink.'],
        explanation='Present Continuous: Sara + is + cleaning. Перевод: Сара сейчас чистит раковину.')
# Session 4 (d2)
fix(T, 4, 1, question='The teacher ___ (explain) a new topic on the board right now.')
replace(T, 4, 2, 'fill_blank',
        question='My parents ___ (organize) the kitchen cupboards at the moment.',
        correct_answer='are organizing', alternatives=["'re organizing", 'are organising'],
        explanation='My parents — мн. число, значит are + organizing. Organize → organizing (немая e убирается). '
                    'Перевод: Мои родители в данный момент наводят порядок в кухонных шкафах.')
fix(T, 4, 3, question='Kate ___ a cake for her birthday party right now.',
    explanation='Kate — 3-е лицо ед. числа, поэтому is + making. Right now — действие сейчас, поэтому не makes. '
                'Make → making (немая e убирается). Перевод: Кейт прямо сейчас готовит торт на свой день рождения.')
replace(T, 4, 4, 'multiple_choice',
        question='Mr. Brown ___ the floor every Monday.',
        correct_answer='mops', options=['mops', 'is mopping', 'mop', 'mopping'],
        explanation='Every Monday — регулярное действие, поэтому Present Simple: mops. Present Continuous '
                    '(is mopping) описывает действие сейчас или в текущий период, а не привычку. '
                    'Перевод: Мистер Браун моет пол каждый понедельник.')
replace(T, 4, 6, 'translation',
        question='Ты сейчас выносишь мусор?',
        correct_answer='Are you taking out the trash now?',
        alternatives=['Are you taking out the garbage now?', 'Are you taking the trash out now?',
                      'Are you taking out the rubbish now?'],
        explanation='Вопрос в Present Continuous: Are + you + taking out. Перевод: Are you taking out the trash now?')
replace(T, 4, 10, 'reorder',
        words=['the', 'Are', 'children', 'blinds', 'the', 'dusting', '?'],
        correct_answer='Are the children dusting the blinds?',
        explanation='Вопрос в Present Continuous: Are + подлежащее + V-ing. Перевод: Дети вытирают пыль с жалюзи?')
# Session 5 (d2)
fix(T, 5, 1, question='Grandma ___ (knit) a warm scarf at the moment.',
    explanation='Grandma — 3-е лицо ед. числа, значит is + knitting. Knit → knitting (удвоение t). '
                'Перевод: Бабушка в данный момент вяжет тёплый шарф.')
replace(T, 5, 2, 'fill_blank',
        question='The neighbours ___ (mop) the stairs right now.',
        correct_answer='are mopping', alternatives=["'re mopping"],
        explanation='The neighbours — мн. число, значит are + mopping. Mop → mopping (удвоение p). '
                    'Перевод: Соседи прямо сейчас моют лестницу шваброй.')
replace(T, 5, 4, 'multiple_choice',
        question="I usually ___ the bathroom on Sundays, but today I'm cleaning the kitchen.",
        correct_answer='clean', options=['clean', 'am cleaning', 'cleans', 'cleaning'],
        explanation='Usually + on Sundays — привычка, поэтому Present Simple: clean. Вторая часть про сегодня — '
                    "Present Continuous: I'm cleaning. Перевод: Обычно я убираю ванную по воскресеньям, но сегодня "
                    'я убираю кухню.')
fix(T, 5, 6, alternatives=["Why are you running? The bus hasn't left yet."],
    explanation='Вопрос в Present Continuous: Why + are + you + running. Перевод: Why are you running? '
                'The bus is still here.')
# Session 6 (d3)
fix(T, 6, 1, question='The mechanic ___ (repair) our car at the garage right now.',
    alternatives=["'s repairing"])
replace(T, 6, 2, 'multiple_choice',
        question='Ask Tom. He ___ the answer.',
        correct_answer='knows', options=['knows', 'is knowing', 'know', 'knowing'],
        explanation='Know — глагол состояния (как like, want, understand), в Present Continuous он не используется: '
                    'He knows (не is knowing). Перевод: Спроси Тома. Он знает ответ.')
replace(T, 6, 3, 'true_false',
        statement='Предложение «I am wanting a new vacuum cleaner» построено правильно.',
        correct_answer=False,
        explanation='Неверно. Want — глагол состояния, в Present Continuous не используется. Правильно: '
                    'I want a new vacuum cleaner. Так же ведут себя like, love, know, understand, need.')
fix(T, 6, 4,
    correct_answer='The children are not doing their homework. They are watching a cartoon.',
    alternatives=["The children aren't doing their homework. They're watching a cartoon.",
                  'The kids are not doing their homework. They are watching a cartoon.',
                  'The children are not doing homework. They are watching a cartoon.'],
    explanation='Отрицание: are + not + V-ing. Два действия в Present Continuous для контраста. '
                'Перевод: The children are not doing their homework. They are watching a cartoon.')
replace(T, 6, 5, 'translation',
        question='Кто выносит мусор сегодня?',
        correct_answer='Who is taking out the trash today?',
        alternatives=["Who's taking out the trash today?", 'Who is taking out the garbage today?',
                      'Who is taking the trash out today?'],
        explanation='Вопрос с who в Present Continuous: Who + is + V-ing. Перевод: Who is taking out the trash today?')
replace(T, 6, 9, 'reorder',
        words=['is', 'Julia', 'the', 'rinsing', 'now', 'plates', '.'],
        correct_answer='Julia is rinsing the plates now.',
        alternatives=['Now Julia is rinsing the plates.', 'Julia is now rinsing the plates.'],
        explanation='Present Continuous: Julia + is + rinsing. Rinse → rinsing (немая e убирается). '
                    'Перевод: Джулия сейчас ополаскивает тарелки.')
# Session 7 (d3)
fix(T, 7, 1, question='The tourists ___ (take) photos near the old castle right now.',
    explanation='The tourists — мн. число, значит are + taking. Take → taking (немая e убирается). '
                'Перевод: Туристы прямо сейчас фотографируют возле старого замка.')
replace(T, 7, 3, 'true_false',
        statement='Every day — маркер привычки: о том, что делаешь каждый день, обычно говорят в Present Simple '
                  '(I clean the kitchen every day), а не в Present Continuous.',
        correct_answer=True,
        explanation='Верно. Привычка и регулярное действие — Present Simple: I clean the kitchen every day. '
                    'Present Continuous — действие сейчас или в текущий период: I am cleaning the kitchen now; '
                    'This week I am cleaning the kitchen every day (временно, только на этой неделе).')
fix(T, 7, 4,
    correct_answer='She is not sleeping. She is reading a magazine.',
    alternatives=["She isn't sleeping. She's reading a magazine.", "She's not sleeping. She is reading a magazine.",
                  'She is not sleeping; she is reading a magazine.'],
    explanation='Два контрастных действия в Present Continuous с отрицанием: is not sleeping / is reading. '
                'Перевод: She is not sleeping. She is reading a magazine.')
replace(T, 7, 6, 'translation',
        question='Мама гладит рубашки, а папа пылесосит ковёр.',
        correct_answer='Mum is ironing the shirts and Dad is vacuuming the carpet.',
        alternatives=['Mum is ironing the shirts, and Dad is vacuuming the carpet.',
                      'Mum is ironing the shirts and Dad is hoovering the carpet.',
                      'Mum is ironing shirts and Dad is vacuuming the carpet.'],
        explanation='Два действия сейчас: Mum + is + ironing, Dad + is + vacuuming. '
                    'Перевод: Mum is ironing the shirts and Dad is vacuuming the carpet.')
replace(T, 7, 10, 'reorder',
        words=['are', 'They', 'the', 'bathroom', 'cleaning', 'now', '.'],
        correct_answer='They are cleaning the bathroom now.',
        alternatives=['Now they are cleaning the bathroom.', 'They are now cleaning the bathroom.'],
        explanation='Present Continuous: They + are + cleaning. Перевод: Они сейчас убирают ванную.')
# Session 8 (d3)
replace(T, 8, 1, 'fill_blank',
        question='My brother usually ___ (wash) the dishes, but today I am washing them.',
        correct_answer='washes', alternatives=[],
        explanation='Usually — привычка, поэтому Present Simple: washes (3-е лицо ед. числа). Вторая часть про '
                    'сегодня стоит в Present Continuous: I am washing. Перевод: Обычно посуду моет мой брат, '
                    'но сегодня её мою я.')
fix(T, 8, 2, question='Oliver ___ to work today because his car is broken.',
    explanation='Oliver — 3-е лицо ед. числа, поэтому is + walking. Today и «машина сломана» описывают '
                'текущую ситуацию, поэтому не walks. Перевод: Оливер сегодня идёт на работу пешком, потому что '
                'его машина сломана.')
fix(T, 8, 8,
    sentence='Look! The sun shines brightly and the birds are singing.',
    correct_answer='Look! The sun is shining brightly and the birds are singing.',
    error_word='shines', correct_word='is shining', alternatives=['is shining'],
    explanation='Look! показывает, что оба действия происходят прямо сейчас — оба требуют Present Continuous. '
                'The sun (ед. число): is shining. Перевод: Смотри! Солнце ярко светит, и птицы поют.')

# --------------------------------------------------------------------------
# Theory (lesson 4 of each module = grammar_topics.content of the slug).
# Row keys are unified to pronoun / form / example / translation: the lab
# topic page renders only those four (rule/ending, person/action and verb
# columns silently disappeared there), the course lesson renders every key
# and bolds the first cell. A changed example drops its ``audio`` reference —
# the clip would not match the text, and no template plays it anyway.
# --------------------------------------------------------------------------
KEY_MAP = {'verb': 'form', 'rule': 'pronoun', 'ending': 'form', 'person': 'pronoun', 'action': 'form'}
KEY_ORDER = ('pronoun', 'form', 'example', 'translation', 'audio')


def _row(**cells) -> dict:
    return {k: cells[k] for k in KEY_ORDER if k in cells}


def _rekey(row: dict) -> dict:
    mapped = {KEY_MAP.get(k, k): v for k, v in row.items()}
    ordered = {k: mapped[k] for k in KEY_ORDER if k in mapped}
    ordered.update({k: v for k, v in mapped.items() if k not in ordered})
    return ordered


def _set_example(row: dict, example: str, translation: str) -> dict:
    new = {k: v for k, v in row.items() if k != 'audio'}
    new['example'] = example
    new['translation'] = translation
    return _rekey(new)


def _rebuild_tldr_summary(content: dict) -> None:
    """tldr / summary mirror the sections (subtitle + first example), as the
    generator laid them out; the extra-examples section is excluded."""
    rows = []
    for section in content['sections']:
        table = section.get('table') or []
        if not table or str(section.get('subtitle', '')).startswith('Дополнительные примеры'):
            continue
        rows.append((section['subtitle'], table[0].get('example', ''), table[0].get('translation', '')))
    content['tldr'] = [f'<strong>{sub}</strong>: <em>{ex}</em>' for sub, ex, _ in rows]
    summary = dict(content.get('summary') or {})
    summary['table'] = [{'topic': sub, 'example': ex, 'translation': tr} for sub, ex, tr in rows]
    summary.setdefault('note', 'Каждый раздел — отдельный аспект темы. Возвращайтесь к таблице при повторении.')
    content['summary'] = summary


def theory_A1_10(content: dict) -> dict:
    new = copy.deepcopy(content)
    for section in new['sections']:
        section['table'] = [_rekey(r) for r in section.get('table') or []]
    _rebuild_tldr_summary(new)
    return new


def theory_A1_11(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert [s['subtitle'] for s in sections][:4] == [
        'Вопросы с Do/Does', "Отрицания с Don't/Doesn't", 'Порядок слов в вопросах', 'Краткие ответы'], sections
    for section in sections[:2]:
        section['table'] = [_rekey(r) for r in section['table']]
    sections[2]['description'] = ('Структура общего вопроса: Do/Does + подлежащее + основной глагол (без -s) '
                                  '+ остальные слова?')
    sections[2]['table'] = [
        _row(pronoun='Does', form='+ he/she/it + глагол?', example='Does your brother work as a pilot?',
             translation='Твой брат работает пилотом?'),
        _row(pronoun='Do', form='+ I/you/we/they + глагол?', example='Do they like their job?',
             translation='Им нравится их работа?'),
        _row(pronoun='Does', form='+ he/she/it + глагол?', example='Does the nurse work at night?',
             translation='Медсестра работает по ночам?'),
    ]
    wh_section = {
        'subtitle': 'Вопросы с What / Where + do/does',
        'description': 'Вопросительное слово ставится ПЕРЕД do/does: What/Where + do/does + подлежащее '
                       '+ глагол? Так спрашивают о профессии: What do you do? — Кем ты работаешь?',
        'table': [
            _row(pronoun='What do you do?', form='кем ты работаешь?',
                 example='What do you do? — I am a nurse.', translation='Кем ты работаешь? — Я медсестра.'),
            _row(pronoun='What does he/she do?', form='кем он/она работает?',
                 example='What does your father do? — He is a mechanic.',
                 translation='Кем работает твой отец? — Он механик.'),
            _row(pronoun='Where do/does …?', form='где …?',
                 example='Where does your sister work? — In a hospital.',
                 translation='Где работает твоя сестра? — В больнице.'),
            _row(pronoun='What time / When …?', form='во сколько / когда …?',
                 example='What time do you start work?', translation='Во сколько ты начинаешь работать?'),
        ],
    }
    sections.insert(3, wh_section)
    short = sections[4]
    short['description'] = ("В кратком ответе повторяется вспомогательный глагол, а не смысловой: "
                            "Yes, I do. / No, he doesn't. (не Yes, I work.)")
    short['table'] = [
        _row(pronoun='Do you …?', form="Yes, I do. / No, I don't.",
             example='Do you work as a driver? — Yes, I do.', translation='Ты работаешь водителем? — Да.'),
        _row(pronoun='Does he/she …?', form="Yes, he does. / No, she doesn't.",
             example="Does she work as a cook? — No, she doesn't.", translation='Она работает поваром? — Нет.'),
        _row(pronoun='Do they …?', form="Yes, they do. / No, they don't.",
             example='Do they like their job? — Yes, they do.', translation='Им нравится их работа? — Да.'),
    ]
    examples = [
        ('Does your father work as a doctor?', 'Твой отец работает врачом?'),
        ("My tutor doesn't give much homework.", 'Мой репетитор не задаёт много домашней работы.'),
        ('Do you know a good engineer?', 'Ты знаешь хорошего инженера?'),
        ("The nurse doesn't work at night.", 'Медсестра не работает по ночам.'),
        ('Does the driver start work at six?', 'Водитель начинает работу в шесть?'),
        ("My aunt doesn't work as a cook any more.", 'Моя тётя больше не работает поваром.'),
        ('Do pilots fly every day?', 'Пилоты летают каждый день?'),
        ("This artist doesn't sell her pictures.", 'Эта художница не продаёт свои картины.'),
        ('Does your brother play in a band? — Yes, he does. He is a musician.',
         'Твой брат играет в группе? — Да. Он музыкант.'),
        ("The writer doesn't like interviews.", 'Писатель не любит интервью.'),
        ('What does a programmer do? — He writes computer programs.',
         'Что делает программист? — Он пишет компьютерные программы.'),
        ('Do you need a lawyer?', 'Тебе нужен юрист?'),
        ('Does the scientist work in a lab?', 'Учёный работает в лаборатории?'),
        ("My grandfather doesn't work as a farmer now.", 'Мой дедушка теперь не работает фермером.'),
        ('Does the mechanic fix cars on Sundays?', 'Механик чинит машины по воскресеньям?'),
        ("The waiter doesn't bring the bill.", 'Официант не приносит счёт.'),
        ('Where does the manager work?', 'Где работает менеджер?'),
        ("My mother doesn't work as an accountant.", 'Моя мама не работает бухгалтером.'),
        ('Do architects draw plans? — Yes, they do.', 'Архитекторы чертят планы? — Да.'),
        ('Does a police officer work at night? — Yes, he does.', 'Полицейский работает по ночам? — Да.'),
    ]
    extra = sections[5]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    extra['description'] = 'Вопросы и отрицания с do/does на лексике модуля.'
    extra['table'] = [_row(example=en, translation=ru) for en, ru in examples]
    notes = list(new.get('important_notes') or [])
    notes.append('⚠️ Вопросительное слово ставится перед do/does: What does he do? Where do you work?')
    notes.append("⚠️ Краткий ответ повторяет do/does, а не глагол: Do you work? — Yes, I do. (не Yes, I work.)")
    new['important_notes'] = notes
    _rebuild_tldr_summary(new)
    return new


def theory_A2_15(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert [s['subtitle'] for s in sections][:4] == [
        'Образование Present Continuous', 'Отрицательная форма', 'Вопросительная форма',
        'Правила добавления -ing'], sections
    for section in sections[:4]:
        section['table'] = [_rekey(r) for r in section['table']]
    s1 = sections[0]['table']
    assert s1[2]['example'] == 'She is steaming dinner.', s1[2]
    s1[2] = _set_example(s1[2], 'She is steaming the vegetables.', 'Она готовит овощи на пару (сейчас).')
    s2 = sections[1]['table']
    assert s2[1]['example'] == 'They are not rinsing the car.', s2[1]
    s2[1] = _set_example(s2[1], 'They are not washing the car.', 'Они не моют машину (сейчас).')
    s4 = sections[3]['table']
    assert s4[0]['example'].startswith('clean → cleaning, rinse'), s4[0]
    s4[0] = _set_example(s4[0], 'clean → cleaning, sweep → sweeping',
                         'убирать → убираю, подметать → подметаю')
    assert s4[1]['example'].startswith('make → making'), s4[1]
    s4[1] = _set_example(s4[1], 'rinse → rinsing, organize → organizing',
                         'ополаскивать → ополаскиваю, организовывать → организую')
    contrast = {
        'subtitle': 'Present Simple или Present Continuous?',
        'description': 'Регулярное действие (every day, usually, on Saturdays) — Present Simple. '
                       'Действие сейчас (now, at the moment, Look!) — Present Continuous.',
        'table': [
            _row(pronoun='every day / usually / on Saturdays', form='Present Simple',
                 example='I clean my room every Saturday.', translation='Я убираю комнату каждую субботу.'),
            _row(pronoun='now / at the moment / Look!', form='Present Continuous',
                 example='I am cleaning my room now.', translation='Я убираю комнату сейчас.'),
            _row(pronoun='usually … but today …', form='Simple + Continuous',
                 example='Dad usually washes the dishes, but today he is cooking.',
                 translation='Обычно папа моет посуду, но сегодня он готовит.'),
            _row(pronoun='like, want, know, need', form='только Present Simple',
                 example='I want a new mop. (не I am wanting)', translation='Я хочу новую швабру.'),
        ],
    }
    sections.insert(4, contrast)
    extra = sections[5]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    assert extra['table'][0]['example'] == 'I clean my room every day.', extra['table'][0]
    extra['table'][0] = _set_example(extra['table'][0], 'I am cleaning my room now.',
                                     'Я убираю свою комнату сейчас.')
    assert new['rule'].startswith('Present Continuous (настоящее длительное время) используется'), new['rule']
    new['rule'] = ('Present Continuous (настоящее длительное время) используется для действий, которые происходят '
                   'сейчас, в момент речи, или в текущий период (сегодня, на этой неделе).')
    new['description'] = ('Present Continuous (настоящее длительное время) описывает действие, которое происходит '
                          'сейчас, в момент речи, или временно в текущий период (сегодня, на этой неделе). '
                          'Привычки и регулярные действия (every day, usually) — это Present Simple.')
    new['important_notes'] = [
        "⚠️ Формула: am/is/are + verb-ing — не забывай глагол to be: She is cleaning (не She cleaning)",
        '⚠️ Present Continuous — для действия, которое происходит сейчас или в этот период (сегодня, на этой неделе)',
        '⚠️ Регулярно (every day, usually) — Present Simple: I clean every day. Сейчас (now) — Present Continuous: I am cleaning now',
        '⚠️ Слова-подсказки: now, at the moment, right now, today, Look!, Listen!',
        '⚠️ Глаголы состояния (like, love, want, know, understand, need) в Continuous не используются: I want (не I am wanting)',
        '⚠️ В вопросах am/is/are ставится в начало: Are you cleaning?',
    ]
    _rebuild_tldr_summary(new)
    return new


THEORY = {'A1_10': theory_A1_10, 'A1_11': theory_A1_11, 'A2_15': theory_A2_15}


# --------------------------------------------------------------------------
# Apply + SQL
# --------------------------------------------------------------------------
def _load_json(path: Path) -> dict:
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def _dump_json(path: Path, data: dict) -> None:
    with path.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def build_exercises(topic: str) -> tuple[dict, list[dict]]:
    """New exercise file for ``topic`` plus the list of slot changes."""
    data = _load_json(BEFORE / f'grammar_extra_{topic}.json')
    changes = []
    for session in data['sessions']:
        number = session['session_number']
        for exercise in session['exercises']:
            key = (number, exercise['order'])
            edit = EDITS[topic].get(key)
            if edit is None:
                continue
            old = copy.deepcopy(exercise)
            if edit['kind'] == 'fix':
                exercise['content'].update(edit['patch'])
            else:
                exercise['exercise_type'] = edit['type']
                exercise['content'] = dict(edit['content'])
            exercise['difficulty'] = difficulty_for(number)
            assert exercise != old, f'{topic} S{number}#{exercise["order"]}: edit changes nothing'
            changes.append({'slot': key, 'kind': edit['kind'], 'old': old, 'new': copy.deepcopy(exercise)})
    unused = set(EDITS[topic]) - {c['slot'] for c in changes}
    assert not unused, f'{topic}: slots not found {sorted(unused)}'
    return data, changes


def _grammar_lesson(module: dict) -> dict:
    lessons = [l for l in module['module']['lessons'] if l['type'] == 'grammar']
    assert len(lessons) == 1, 'expected exactly one grammar lesson'
    return lessons[0]


def build_theory(topic: str) -> tuple[dict, dict, dict]:
    """Module JSON with the rewritten lesson-4 content, old and new extras."""
    module = _load_json(BEFORE / TOPICS[topic]['module_file'])
    lesson = _grammar_lesson(module)
    old_content = copy.deepcopy(lesson['content'])
    new_content = THEORY[topic](old_content)
    lesson['content'] = new_content
    old_extra = {k: old_content.get(k) for k in EXTRA_KEYS}
    new_extra = {k: new_content.get(k) for k in EXTRA_KEYS}
    return module, old_extra, new_extra


def validate_exercises(topic: str, data: dict) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.grammar_lab.content_validator import validate_exercise_content
    for session in data['sessions']:
        for exercise in session['exercises']:
            validate_exercise_content(exercise['exercise_type'], dict(exercise['content']))


# ---- SQL -------------------------------------------------------------------
def _j(value) -> str:
    """jsonb literal (dollar-quoted, so apostrophes in content need no escaping)."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    assert '$q$' not in text
    return f'$q${text}$q$::jsonb'


def _s(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _topic_id(slug: str) -> str:
    return f'(SELECT id FROM grammar_topics WHERE slug = {_s(slug)})'


def _where_exercise(slug: str, exercise: dict) -> str:
    content = {k: v for k, v in exercise['content'].items() if k != 'source'}
    return (f"topic_id = {_topic_id(slug)} AND exercise_type = {_s(exercise['exercise_type'])} "
            f"AND content ->> 'source' = 'json_import' AND (content - 'source') = {_j(content)}")


def _with_source(content: dict) -> dict:
    out = dict(content)
    out['source'] = 'json_import'
    return out


def _lesson_id(topic: str) -> str:
    meta = TOPICS[topic]
    return ("(SELECT l.id FROM lessons l JOIN modules m ON m.id = l.module_id "
            "JOIN cefr_levels cl ON cl.id = m.level_id "
            f"WHERE cl.code = {_s(meta['level'])} AND m.number = {meta['module']} "
            "AND l.number = 4 AND l.type = 'grammar')")


def _assert_block(rows: list[str], expect_old: int, expect_new: int, name: str) -> str:
    """DO block raising the list of slots whose row count differs from the
    expectation (``rows`` are ``SELECT '<label> old|new' AS slot, count(*) AS found``
    queries). Used as the preflight of 1_check and as the post-state check
    of 2_apply / 3_rollback: run inside one transaction, a failed post-state
    check aborts the whole change."""
    return (
        f"\n-- {name}: raises if any row count differs from old = {expect_old} / new = {expect_new}.\n"
        "DO $$\nDECLARE bad text;\nBEGIN\n  SELECT string_agg(slot, ', ') INTO bad FROM (\n"
        + '\nUNION ALL\n'.join('    ' + r for r in rows)
        + f"\n  ) s WHERE (slot LIKE '% old' AND s.found <> {expect_old}) "
        f"OR (slot LIKE '% new' AND s.found <> {expect_new});\n"
        f"  IF bad IS NOT NULL THEN RAISE EXCEPTION '{name} failed: %', bad; END IF;\n"
        f"  RAISE NOTICE '{name} ok';\nEND $$;\n"
    )


def emit_sql(all_changes: dict[str, list[dict]], theory: dict[str, tuple[dict, dict]]) -> dict[str, str]:
    check, apply, rollback = [], [], []
    head = ('-- Lesson audit item 20: grammar content of a1-10 / a1-11 / a2-15.\n'
            '-- Generated by scripts/fix_grammar_topics_3.py. Rows are matched by exact content, never by id.\n')
    check.append(head + '-- Expect found = 1 for every "old" line and found = 0 for every "new" line;\n'
                 '-- the DO block at the end raises the list of mismatching slots.\n')
    apply.append(head + '-- Expected row counts are in the trailing comments; run 1_check first.\n'
                 '-- Run as ONE transaction (DBeaver: auto-commit off, commit at the end). Every statement is\n'
                 '-- keyed on the exact old content and guarded, so a replay or a half-applied run changes nothing\n'
                 '-- it should not: an UPDATE/DELETE misses a changed row, an INSERT needs its predecessor present\n'
                 '-- and its successor absent. The DO block at the end verifies the final state and raises —\n'
                 '-- inside the transaction — if any slot or theory mirror is off, so nothing partial commits.\n')
    rollback.append(head + '-- Reverses 2_apply; run as ONE transaction like 2_apply. Rows re-inserted for "replace"\n'
                    '-- slots get new ids: learner history on the deleted originals is NOT restored. A replaced\n'
                    '-- row is re-inserted only while its successor is still present unchanged, and the successor\n'
                    '-- is deleted right after — an edited successor leaves the slot untouched (no duplicates).\n')
    rows = []  # SELECT '<label> old|new' AS slot, count(*) AS found …

    def _count_row(label: str, where: str) -> str:
        return f"SELECT {_s(label)} AS slot, count(*) AS found FROM grammar_exercises WHERE {where}"

    for topic, changes in all_changes.items():
        slug = TOPICS[topic]['slug']
        for change in changes:
            label = f"{topic} S{change['slot'][0]}#{change['slot'][1]} {change['kind']}"
            old, new = change['old'], change['new']
            new_row = {'exercise_type': new['exercise_type'], 'content': new['content']}
            where_old = _where_exercise(slug, old)
            where_new = _where_exercise(slug, new_row)
            rows.append(_count_row(label + ' old', where_old))
            rows.append(_count_row(label + ' new', where_new))
            if change['kind'] == 'fix':
                apply.append(
                    f"-- {label} (expect UPDATE 1)\n"
                    f"UPDATE grammar_exercises SET content = {_j(_with_source(new['content']))}, "
                    f"exercise_type = {_s(new['exercise_type'])}, difficulty = {new['difficulty']} "
                    f"WHERE {where_old};\n")
                rollback.append(
                    f"-- {label} (expect UPDATE 1)\n"
                    f"UPDATE grammar_exercises SET content = {_j(_with_source(old['content']))}, "
                    f"exercise_type = {_s(old['exercise_type'])}, difficulty = {old['difficulty']} "
                    f"WHERE {where_new};\n")
            else:
                apply.append(
                    f"-- {label} (expect INSERT 1, DELETE 1)\n"
                    f"INSERT INTO grammar_exercises (topic_id, exercise_type, content, difficulty, \"order\", created_at) "
                    f"SELECT id, {_s(new['exercise_type'])}, {_j(_with_source(new['content']))}, "
                    f"{new['difficulty']}, {new['order']}, now() FROM grammar_topics WHERE slug = {_s(slug)} "
                    f"AND EXISTS (SELECT 1 FROM grammar_exercises WHERE {where_old}) "
                    f"AND NOT EXISTS (SELECT 1 FROM grammar_exercises WHERE {where_new});\n"
                    f"DELETE FROM grammar_exercises WHERE {where_old};\n")
                rollback.append(
                    f"-- {label} (expect INSERT 1, DELETE 1)\n"
                    f"INSERT INTO grammar_exercises (topic_id, exercise_type, content, difficulty, \"order\", created_at) "
                    f"SELECT id, {_s(old['exercise_type'])}, {_j(_with_source(old['content']))}, "
                    f"{old['difficulty']}, {old['order']}, now() FROM grammar_topics WHERE slug = {_s(slug)} "
                    f"AND EXISTS (SELECT 1 FROM grammar_exercises WHERE {where_new}) "
                    f"AND NOT EXISTS (SELECT 1 FROM grammar_exercises WHERE {where_old});\n"
                    f"DELETE FROM grammar_exercises WHERE {where_new};\n")

    def _match_keys(expr: str, values: dict, keys) -> str:
        # Every key the patch overwrites must still hold the expected value —
        # an independent prod edit of notes/tldr/summary must not be lost.
        return ' AND '.join(f"{expr} -> {_s(k)} = {_j(values[k])}" for k in keys)

    for topic, (old_extra, new_extra) in theory.items():
        slug = TOPICS[topic]['slug']
        for tag, values in (('old', old_extra), ('new', new_extra)):
            rows.append(f"SELECT {_s(f'{topic} theory lesson {tag}')} AS slot, count(*) AS found FROM lessons "
                        f"WHERE id = {_lesson_id(topic)} AND {_match_keys('content::jsonb', values, EXTRA_KEYS)}")
            rows.append(f"SELECT {_s(f'{topic} theory topic {tag}')} AS slot, count(*) AS found FROM grammar_topics "
                        f"WHERE slug = {_s(slug)} AND {_match_keys('content', values, TOPIC_KEYS)}")
        for label, src, dst, sink in (('apply', old_extra, new_extra, apply), ('rollback', new_extra, old_extra, rollback)):
            topic_patch = {k: dst[k] for k in TOPIC_KEYS}
            sink.append(
                f"-- theory {topic} {label} (expect UPDATE 1 + UPDATE 1)\n"
                f"UPDATE lessons SET content = (content::jsonb || {_j(dst)})::json "
                f"WHERE id = {_lesson_id(topic)} AND {_match_keys('content::jsonb', src, EXTRA_KEYS)};\n"
                f"UPDATE grammar_topics SET content = content || {_j(topic_patch)} "
                f"WHERE slug = {_s(slug)} AND {_match_keys('content', src, TOPIC_KEYS)};\n")

    check.append('\nUNION ALL\n'.join(rows) + ';\n')
    check.append(_assert_block(rows, 1, 0, f'{ASSERT_LABEL} preflight'))
    counts = ', '.join(f"{TOPICS[t]['slug']} = 104" for t in all_changes)
    tail = ("\n-- After apply every topic must still hold 104 exercises (" + counts + "):\n"
            "SELECT t.slug, count(e.id) FROM grammar_topics t LEFT JOIN grammar_exercises e ON e.topic_id = t.id "
            "WHERE t.slug IN ('a1-10', 'a1-11', 'a2-15') GROUP BY t.slug ORDER BY t.slug;\n")
    apply.append(tail)
    apply.append(_assert_block(rows, 0, 1, f'{ASSERT_LABEL} apply post-check'))
    rollback.append(_assert_block(rows, 1, 0, f'{ASSERT_LABEL} rollback post-check'))
    return {'1_check': ''.join(check), '2_apply': ''.join(apply), '3_rollback': ''.join(rollback)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='print the change summary, write nothing')
    args = parser.parse_args(argv)
    if not BEFORE.exists():
        print(f'snapshot dir missing: {BEFORE}', file=sys.stderr)
        return 2
    all_changes, theory, outputs = {}, {}, []
    for topic in TOPICS:
        data, changes = build_exercises(topic)
        validate_exercises(topic, data)
        all_changes[topic] = changes
        kinds = {'fix': 0, 'replace': 0}
        for change in changes:
            kinds[change['kind']] += 1
        module, old_extra, new_extra = build_theory(topic)
        theory[topic] = (old_extra, new_extra)
        print(f"{topic}: {len(changes)} exercise edits (fix {kinds['fix']}, replace {kinds['replace']}); "
              f"theory sections {len(old_extra['sections'])} -> {len(new_extra['sections'])}, "
              f"notes {len(old_extra['important_notes'])} -> {len(new_extra['important_notes'])}")
        outputs.append((EXTRA_DIR / f'grammar_extra_{topic}.json', data))
        outputs.append((MODULE_DIR / TOPICS[topic]['module_file'], module))
    if args.check:
        return 0
    for path, payload in outputs:
        _dump_json(path, payload)
        print('wrote', path.relative_to(ROOT))
    for suffix, text in emit_sql(all_changes, theory).items():
        path = EXPORT_DIR / f'{SQL_PREFIX}_{suffix}.sql'
        path.write_text(text, encoding='utf-8')
        print('wrote', path.relative_to(ROOT), f'({len(text) // 1024} KiB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
