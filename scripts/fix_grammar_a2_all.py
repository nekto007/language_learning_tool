#!/usr/bin/env python3
"""Lesson audit item 25 — deep pass over the whole A2 grammar level (23 topics).

Owner's decision 2026-09-06: «целиком А2 делай». Same delivery machinery as
items 20–24 (``scripts/fix_grammar_topics_3.py``); snapshot of all 46
sources in ``local_exports/grammar_a2_all_before/``. Item 21 touched several
A2 topics, so in production this SQL is applied AFTER item 21.

Usage::

    venv/bin/python scripts/fix_grammar_a2_all.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_a2_all.py --check    # summary only
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fix_grammar_topics_3 as base

BEFORE = ROOT / 'local_exports' / 'grammar_a2_all_before'
SQL_PREFIX = 'item25_grammar_a2_all'
fix, replace, row = base.fix, base.replace, base._row
THEORY: dict = {}


def topic_meta() -> dict[str, dict]:
    meta = {}
    for path in sorted(BEFORE.glob('grammar_extra_A2_*.json')):
        name = path.stem[len('grammar_extra_'):]
        number = int(name.split('_')[1])
        module_file = next(p.name for p in BEFORE.glob(f'module_A2_{number}_*.json'))
        meta[name] = {'slug': f'a2-{number}', 'level': 'A2', 'module': number, 'module_file': module_file}
    return meta


def _swap_examples(section: dict, swaps: dict[str, tuple[str, str]]) -> None:
    seen = 0
    for i, r in enumerate(section['table']):
        if isinstance(r, dict) and r.get('example') in swaps:
            en, ru = swaps[r['example']]
            section['table'][i] = base._set_example(r, en, ru)
            seen += 1
    assert seen == len(swaps), (section.get('subtitle'), seen, len(swaps))


def _dup_section(content: dict) -> dict:
    """The generator's «Употребление в утверждении» section that merely repeats
    the first rows of the examples section."""
    for s in content['sections']:
        if str(s.get('subtitle', '')).startswith('Употребление в утверждении'):
            return s
    raise AssertionError('no duplicate section')


def _hint(topic: str, session: int, order: int, hint: str, **extra) -> None:
    """Add a bracketed Russian hint after the blank of a fill_blank (the item
    otherwise asks the learner to guess the lexical verb)."""
    data = base._load_json(BEFORE / f'grammar_extra_{topic}.json')
    ex = next(e for s in data['sessions'] if s['session_number'] == session for e in s['exercises'] if e['order'] == order)
    q = ex['content']['question']
    assert ex['exercise_type'] == 'fill_blank' and q.count('___') == 1 and '(' not in q, (topic, session, order, q)
    fix(topic, session, order, question=q.replace('___', f'___ ({hint})', 1), **extra)


# ============================================== A2_1 a/an, some/any =======
T = 'A2_1'
base.EDITS[T] = {}


def theory_A2_1(content: dict) -> dict:
    new = copy.deepcopy(content)
    s = _dup_section(new)
    s['subtitle'] = 'Some в предложениях и просьбах'
    s['description'] = ('В вопросе обычно any, но если мы предлагаем что-то или просим, ожидая «да», — some: '
                        'Would you like some tea? Can I have some water?')
    s['table'] = [
        row(pronoun='предложение', form='Would you like some …?', example='Would you like some juice?', translation='Хочешь сока?'),
        row(pronoun='просьба', form='Can I have some …?', example='Can I have some sugar, please?', translation='Можно мне сахара?'),
        row(pronoun='просьба', form='Could you pass me some …?', example='Could you pass me some bread?', translation='Передай, пожалуйста, хлеб.'),
        row(pronoun='обычный вопрос', form='any', example='Do we have any eggs?', translation='У нас есть яйца?'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_1

# ============================================ A2_2 how much / many =======
T = 'A2_2'
base.EDITS[T] = {}


def theory_A2_2(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'I go to the shop every day.': ('How many shops are there in your street?', 'Сколько магазинов на твоей улице?'),
        'My mother buys food at the supermarket.': ('How much food does your mother buy at the supermarket?', 'Сколько еды покупает твоя мама в супермаркете?'),
        'I buy bread and milk.': ('How much bread and milk do you buy?', 'Сколько хлеба и молока ты покупаешь?'),
        'They sell fresh vegetables.': ('How many vegetables do they sell a day?', 'Сколько овощей они продают в день?'),
        'This phone is very expensive.': ('How much is this phone? — It is very expensive.', 'Сколько стоит этот телефон? — Он очень дорогой.'),
        'These apples are cheap.': ('How much are these apples? — They are cheap.', 'Сколько стоят эти яблоки? — Они дешёвые.'),
        'The customer wants to buy a shirt.': ('How many shirts does the customer want to buy?', 'Сколько рубашек хочет купить покупатель?'),
        'The salesperson is very friendly.': ('How many salespersons work here?', 'Сколько продавцов здесь работает?'),
        'I need a shopping bag.': ('How many shopping bags do you need?', 'Сколько сумок для покупок тебе нужно?'),
        'Can I have a receipt, please?': ('How much is on the receipt?', 'Сколько указано в чеке?'),
        'I pay with cash.': ('How much cash do you have?', 'Сколько у тебя наличных?'),
        'Do you accept credit cards?': ('How many cards do you have?', 'Сколько у тебя карт?'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_2

# ================================================== A2_3 would like =====
T = 'A2_3'
base.EDITS[T] = {}
_hint(T, 2, 3, 'заказать')
_hint(T, 3, 1, 'поесть')
_hint(T, 4, 1, 'взять')
_hint(T, 4, 2, 'закуску')
_hint(T, 5, 1, 'съесть')
_hint(T, 6, 1, 'попросить', alternatives=['have', 'book', 'ask for'])
_hint(T, 7, 1, 'поужинать', alternatives=['eat', 'have dinner'])
_hint(T, 8, 1, 'узнать', alternatives=['ask', 'find out'])
fix(T, 3, 10, correct_answer='I would like some soup, please.', words=['like', 'some', 'would', 'soup', 'I', ',', 'please', '.'],
    alternatives=['Please, I would like some soup.'])
fix(T, 8, 10, correct_answer="I'd like to have the bill, please.", words=['like', 'to', 'the', 'bill', "I'd", ',', 'please', 'have', '.'])


def theory_A2_3(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    for s in sections[2:4]:
        for r in s['table']:
            if not r['example'].endswith(('.', '!', '?')):
                r['example'] += '.'
            if not r['translation'].endswith(('.', '!', '?')):
                r['translation'] += '.'
    extra = sections[4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        "Let's meet at the cafe.": ("I'd like to meet at the cafe.", 'Я бы хотел встретиться в кафе.'),
        'This restaurant is very popular.': ('We would like a table in this restaurant.', 'Мы бы хотели столик в этом ресторане.'),
        'Can I see the menu, please?': ("I'd like to see the menu, please.", 'Я бы хотел посмотреть меню, пожалуйста.'),
        'Our server is very friendly.': ('The server asked what we would like.', 'Официант спросил, что бы мы хотели.'),
        'Do you have a seat for two?': ('We would like a seat for two.', 'Мы бы хотели место на двоих.'),
        'We have lunch at 1 pm.': ('Would you like to have lunch at 1 pm?', 'Не хотели бы вы пообедать в час?'),
    })
    return new


THEORY[T] = theory_A2_3


# =================================================== A2_4 partitives =====
T = 'A2_4'
base.EDITS[T] = {}
replace(T, 4, 8, 'error_correction',
        sentence='She opened a plate of tuna for the pasta.', correct_answer='She opened a tin of tuna for the pasta.',
        error_word='plate', correct_word='tin', alternatives=['tin'],
        explanation='Ошибка: тунец продаётся в жестяной банке (tin), а тарелка (plate) — посуда для подачи. Правильно: a tin of tuna.')
fix(T, 8, 7, sentence='The recipe says to add a glass of salt first.', correct_answer='The recipe says to add a spoonful of salt first.',
    error_word='glass', correct_word='spoonful', alternatives=['spoonful'],
    explanation='Ошибка: glass — стакан для напитков, а соль в рецептах измеряют ложками. Правильно: a spoonful of salt = ложка соли.')


def theory_A2_4(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        "Let's grill the vegetables.": ("Let's grill a piece of chicken.", 'Давай пожарим на гриле кусок курицы.'),
        'Put it on a plate.': ('Put a slice of cheese on the plate.', 'Положи ломтик сыра на тарелку.'),
        'I prepare dinner every day.': ('I prepare a plate of pasta for dinner.', 'На ужин я готовлю тарелку пасты.'),
    })
    return new


THEORY[T] = theory_A2_4

# ====================================================== A2_5 gerund =====
T = 'A2_5'
base.EDITS[T] = {}


def theory_A2_5(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][7]
    assert extra['subtitle'].startswith('Дополнительные примеры') and len(extra['table']) == 4, extra
    _swap_examples(extra, {'I have many interests.': ('One of my interests is drawing.', 'Одно из моих увлечений — рисование.')})
    extra['table'] += [row(example=en, translation=ru) for en, ru in [
        ('I enjoy listening to music.', 'Мне нравится слушать музыку.'),
        ('She hates writing essays.', 'Она ненавидит писать сочинения.'),
        ('We love watching films together.', 'Мы любим смотреть фильмы вместе.'),
        ('Do you like cooking?', 'Тебе нравится готовить?'),
        ("He doesn't like running in the rain.", 'Ему не нравится бегать под дождём.'),
        ('Playing the guitar is my hobby.', 'Игра на гитаре — моё хобби.'),
    ]]
    return new


THEORY[T] = theory_A2_5

# ===================================================== A2_6 have to =====
T = 'A2_6'
base.EDITS[T] = {}


def theory_A2_6(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    extra = sections[3]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'He goes to a sports academy.': ('He has to train every day at the sports academy.', 'Он должен тренироваться каждый день в спортивной академии.'),
        'She is a fast learner.': ('A learner has to do homework after every lesson.', 'Ученик должен делать домашнее задание после каждого урока.'),
        'The instructor explains everything clearly.': ('The instructor has to explain the rules again.', 'Преподаватель должен объяснить правила ещё раз.'),
        "The lesson starts at 9 o'clock.": ("We have to be in class at 9 o'clock.", 'Мы должны быть в классе в 9 часов.'),
        'We have an exam tomorrow.': ('Do we have to take the exam tomorrow?', 'Нам нужно сдавать экзамен завтра?'),
        'The test was difficult.': ("You don't have to finish the test today.", 'Тебе не обязательно закончить тест сегодня.'),
        'I got a good grade.': ('I have to get a good grade in this subject.', 'Мне нужно получить хорошую оценку по этому предмету.'),
        'Math is my favorite subject.': ("Does she have to study every subject?", 'Ей нужно учить каждый предмет?'),
        'Our classroom is big.': ('Students have to keep the classroom clean.', 'Ученики должны поддерживать чистоту в классе.'),
        'I study in the library.': ("You don't have to be quiet in the library café.", 'В библиотечном кафе не обязательно соблюдать тишину.'),
        'I forgot my textbook at home.': ('I have to bring my textbook tomorrow.', 'Мне нужно принести учебник завтра.'),
        'My notes are in a binder.': ('Every learner has to keep notes in a binder.', 'Каждый ученик должен хранить конспекты в папке.'),
        'Do you have a sharpener?': ("You don't have to buy a sharpener — there is one in the classroom.", 'Тебе не нужно покупать точилку — в классе есть.'),
        'I use a highlighter for important words.': ("We don't have to use a highlighter.", 'Нам не обязательно пользоваться маркером.'),
        'My books are in my locker.': ('We have to leave our bags in the locker.', 'Мы должны оставлять сумки в шкафчике.'),
        'The instructor turns on the projector.': ("The instructor doesn't have to use the projector.", 'Преподавателю не обязательно включать проектор.'),
        'We have a break at 11.': ("We don't have to stay in class during the break.", 'На перемене мы не обязаны оставаться в классе.'),
        'Check your schedule.': ('You have to check the schedule every morning.', 'Ты должен проверять расписание каждое утро.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = "Have to, must и mustn't"
    dup['description'] = ("Have to — обязанность извне (правило, ситуация); must — обязанность от говорящего (я так считаю). "
                          "Mustn't — запрет; don't have to — всего лишь «не обязательно».")
    dup['table'] = [
        row(pronoun='have to', form='правило, обстоятельства', example='Students have to wear a uniform.', translation='Ученики обязаны носить форму (правило школы).'),
        row(pronoun='must', form='мнение говорящего', example='I must study harder.', translation='Я должен учиться усерднее (я так решил).'),
        row(pronoun="mustn't", form='запрет', example="You mustn't use your phone in the exam.", translation='В экзамене нельзя пользоваться телефоном.'),
        row(pronoun="don't have to", form='не обязательно', example="You don't have to come early.", translation='Тебе не обязательно приходить рано.'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_6


# ====================================================== A2_7 should =====
T = 'A2_7'
base.EDITS[T] = {}


def theory_A2_7(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'Good health is very important.': ('You should take care of your health.', 'Тебе следует заботиться о здоровье.'),
        'I do a workout every morning.': ('You should do a short workout every morning.', 'Тебе следует делать короткую тренировку каждое утро.'),
        'My favorite sport is tennis.': ('You should try a new sport this year.', 'Тебе стоит попробовать новый вид спорта в этом году.'),
        'She goes to a fitness club.': ('She should go to a fitness club twice a week.', 'Ей следует ходить в фитнес-клуб дважды в неделю.'),
        'I run in the park every day.': ("You shouldn't run in the park when it is icy.", 'Не следует бегать в парке, когда гололёд.'),
        'We go cycling on Sundays.': ('We should go cycling more often.', 'Нам следует чаще кататься на велосипеде.'),
        'I walk to work every day.': ('You should walk to work instead of driving.', 'Тебе стоит ходить на работу пешком, а не ездить.'),
        'He goes to the gym three times a week.': ("He shouldn't go to the gym every day without rest.", 'Ему не следует ходить в спортзал каждый день без отдыха.'),
        "I'm on a healthy diet.": ('Should I start a healthy diet?', 'Стоит ли мне начать здоровую диету?'),
        'Oranges have a lot of vitamin C.': ('You should eat oranges — they have a lot of vitamin C.', 'Тебе следует есть апельсины: в них много витамина С.'),
        'My bedtime is at 10 p.m.': ('Children should have a bedtime before 10 p.m.', 'Детям следует ложиться спать до 10 вечера.'),
        'Good hydration is important every day.': ("You shouldn't forget about hydration during a workout.", 'Не следует забывать о питье во время тренировки.'),
    })
    return new


THEORY[T] = theory_A2_7

# ==================================== A2_8 prepositions of movement ======
T = 'A2_8'
base.EDITS[T] = {}


def theory_A2_8(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[6]['subtitle'].startswith('Дополнительные примеры'), sections[6]['subtitle']
    # The exercises test seven more prepositions than the theory shows.
    sections.insert(6, {
        'subtitle': 'Ещё предлоги движения: up / down, over / under, out of, towards, around',
        'description': 'Up — вверх, down — вниз; over — поверх препятствия, under — под ним; out of — наружу (противоположность into); '
                       'towards — в направлении к (не обязательно дойти); around — вокруг или по территории.',
        'table': [
            {'preposition': 'up / down', 'example': 'We walked up the hill and ran down the stairs.', 'translation': 'Мы поднялись на холм и сбежали по лестнице.'},
            {'preposition': 'over', 'example': 'The cat jumped over the fence.', 'translation': 'Кошка перепрыгнула через забор.'},
            {'preposition': 'under', 'example': 'The boat went under the bridge.', 'translation': 'Лодка прошла под мостом.'},
            {'preposition': 'out of', 'example': 'She got out of the taxi at the station.', 'translation': 'Она вышла из такси у станции.'},
            {'preposition': 'towards', 'example': 'He walked towards the bus stop.', 'translation': 'Он пошёл в сторону автобусной остановки.'},
            {'preposition': 'around', 'example': 'The bus goes around the city centre.', 'translation': 'Автобус объезжает центр города.'},
        ],
    })
    _swap_examples(sections[7], {
        "The train arrives at 3 o'clock.": ('The train goes through the tunnel and arrives at the station.', 'Поезд проезжает через туннель и прибывает на станцию.'),
        "Let's call a taxi.": ("Let's get into a taxi.", 'Давай сядем в такси.'),
        'The subway is fast and cheap.': ('Walk down the stairs into the subway.', 'Спуститесь по лестнице в метро.'),
        'My father has a red car.': ('My father drove past the station in his red car.', 'Мой отец проехал мимо станции на красной машине.'),
        'The bus station is near my house.': ('Go along the road to the bus station.', 'Идите по дороге до автобусной станции.'),
        'Turn left at the corner.': ('Walk to the corner and cross the street.', 'Дойдите до угла и перейдите улицу.'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_8

# ================================================ A2_9 conjunctions =====
T = 'A2_9'
base.EDITS[T] = {}
fix(T, 4, 1, alternatives=['but'],
    explanation='Союз «and» соединяет два последовательных события: дети играли, и потом начался дождь; «but then» (но потом) '
                'тоже возможен. Перевод: Дети играли на улице, и потом начался дождь.')
fix(T, 8, 1, alternatives=['but'],
    explanation='Союз «and» добавляет второй недостаток: отель был дорогим, и к тому же номера маленькие; «but» тоже возможен, '
                'если подчеркнуть контраст «дорого, но тесно». Перевод: Отель был дорогим, и комнаты были очень маленькими.')


def theory_A2_9(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[5]['subtitle'].startswith('Дополнительные примеры'), sections[5]['subtitle']
    # or / so appear in a third of the exercises and nowhere in the theory.
    sections.insert(3, {
        'subtitle': 'Союзы OR (или) и SO (поэтому)',
        'description': 'Or предлагает выбор из двух вариантов; so вводит следствие (сравни: because — причина).',
        'table': [
            {'structure': 'A or B', 'example': 'Do you want tea or coffee?', 'translation': 'Ты хочешь чай или кофе?', 'note': 'выбор'},
            {'structure': 'Cause, so result', 'example': 'It was late, so we went home.', 'translation': 'Было поздно, поэтому мы пошли домой.', 'note': 'следствие'},
            {'structure': 'so vs because', 'example': 'I was tired, so I slept. / I slept because I was tired.',
             'translation': 'Я устал, поэтому поспал. / Я поспал, потому что устал.', 'note': 'so — результат, because — причина'},
        ],
    })
    _swap_examples(sections[6], {
        'Tom is my buddy.': ('Tom is my buddy and Anna is my classmate.', 'Том — мой приятель, а Анна — моя одноклассница.'),
        'Anna is my best buddy.': ('Anna is my best buddy because she is honest.', 'Анна — моя лучшая приятельница, потому что она честная.'),
        'Mike is my classmate.': ('Mike is my classmate, but we are not buddies.', 'Майк — мой одноклассник, но мы не приятели.'),
        'Sarah is my neighbor.': ('Sarah is my neighbor, so we meet every day.', 'Сара — моя соседка, поэтому мы видимся каждый день.'),
        'She is very kind.': ('She is very kind and helpful.', 'Она очень добрая и отзывчивая.'),
        'My buddies are outgoing.': ('My buddies are outgoing but polite.', 'Мои приятели общительные, но вежливые.'),
        'He is a nice person.': ('He is a nice person, so everyone likes him.', 'Он хороший человек, поэтому он всем нравится.'),
        'John is very funny.': ('John is very funny because he tells great jokes.', 'Джон очень весёлый, потому что рассказывает отличные шутки.'),
        'Lisa is smart.': ('Lisa is smart but a little shy.', 'Лиза умная, но немного застенчивая.'),
        'My buddy is very helpful.': ('Is your buddy tall or short?', 'Твой приятель высокий или невысокий?'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_9


# ================================================ A2_10 comparatives =====
T = 'A2_10'
base.EDITS[T] = {}


def theory_A2_10(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][5]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'A wolf is an animal.': ('A wolf is a more dangerous animal than a fox.', 'Волк — более опасное животное, чем лиса.'),
        'I love wildlife.': ('Wildlife is more interesting than a zoo.', 'Дикая природа интереснее зоопарка.'),
        'The wolf is very strong.': ('The wolf is stronger than the fox.', 'Волк сильнее лисы.'),
        'The fox is sleeping.': ('A fox is faster than a rabbit.', 'Лиса быстрее кролика.'),
        'I see a bird in the tree.': ('A bird is lighter than a monkey.', 'Птица легче обезьяны.'),
        'The dolphin swims in the water.': ('A dolphin swims better than a duck.', 'Дельфин плавает лучше утки.'),
        'My hamster is small and cute.': ('My hamster is smaller than my rabbit.', 'Мой хомяк меньше моего кролика.'),
        'The rabbit has long ears.': ('A rabbit has longer ears than a hamster.', 'У кролика уши длиннее, чем у хомяка.'),
        'The cow gives us milk.': ('A cow is heavier than a sheep.', 'Корова тяжелее овцы.'),
        'The pig is pink.': ('A pig is fatter than a duck.', 'Свинья толще утки.'),
        'Sheep give us wool.': ('Sheep are quieter than pigs.', 'Овцы тише свиней.'),
    })
    return new


THEORY[T] = theory_A2_10

# ================================================ A2_11 superlatives =====
T = 'A2_11'
base.EDITS[T] = {}
# Alternatives that would produce nonsense once inserted into the sentence.
fix(T, 1, 1, alternatives=[])
fix(T, 1, 2, alternatives=[])
fix(T, 2, 2, alternatives=[])
fix(T, 2, 3, alternatives=[])
fix(T, 3, 1, alternatives=[])


def theory_A2_11(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][3]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'Choosing what to eat for breakfast is an everyday choice.': ('Breakfast is the most important meal of the day.', 'Завтрак — самый важный приём пищи за день.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Превосходная степень + in / of / ever'
    dup['description'] = ('После превосходной степени границы сравнения задают in (место, группа), of (период, набор) '
                          'и придаточное с ever (за всю жизнь).')
    dup['table'] = [
        row(pronoun='in + место/группа', example='the biggest city in the world', translation='самый большой город в мире'),
        row(pronoun='in + группа', example='the best student in the class', translation='лучший ученик в классе'),
        row(pronoun='of + период/набор', example='the worst day of the week', translation='худший день недели'),
        row(pronoun='(that) I have ever …', example='the most beautiful place I have ever seen', translation='самое красивое место, которое я когда-либо видел'),
        row(pronoun='one of the + superlative + мн. ч.', example='one of the oldest buildings in town', translation='одно из самых старых зданий в городе'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_11

# ================================================== A2_12 too / enough ===
T = 'A2_12'
base.EDITS[T] = {}
fix(T, 1, 8, sentence='The road is enough busy during rush hour.', correct_answer='The road is too busy during rush hour.',
    explanation='Ошибка: «enough busy» — неверный порядок и смысл. Для значения «слишком» нужно «too» перед прилагательным. '
                'Правильно: The road is too busy during rush hour.')
fix(T, 2, 3, question='The avenue is wide ___ for a bus lane.', correct_answer='enough',
    explanation='Прилагательное + «enough»: wide enough. Перевод: Проспект достаточно широкий для полосы автобуса.')
replace(T, 5, 4, 'multiple_choice',
        question="The countryside is quiet ___ for a good night's sleep.", options=['enough', 'too', 'much', 'many'], correct_answer='enough',
        explanation='Прилагательное + «enough» = достаточно: quiet enough. Перевод: В сельской местности достаточно тихо, чтобы хорошо выспаться.')
replace(T, 8, 6, 'translation',
        question='В деревне недостаточно магазинов, но достаточно свежего воздуха.',
        correct_answer="The village doesn't have enough shops, but it has enough fresh air.",
        alternatives=["There aren't enough shops in the village, but there is enough fresh air.",
                      'The village does not have enough shops, but it has enough fresh air.'],
        explanation='«Not enough» + существительное = недостаточно; «enough» + существительное = достаточно. '
                    "Перевод: The village doesn't have enough shops, but it has enough fresh air.")


def theory_A2_12(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'I live in a big city.': ('The city is too big for me.', 'Город слишком большой для меня.'),
        'My grandparents live in a small village.': ('The village is too small — there is no school.', 'Деревня слишком маленькая — там нет школы.'),
        'This is a nice town.': ('This town is nice enough to live in.', 'Этот городок достаточно хорош, чтобы жить в нём.'),
        'I love the countryside.': ('The countryside is peaceful enough to relax.', 'Сельская местность достаточно спокойная, чтобы отдохнуть.'),
        'There are many tall buildings.': ('There are too many tall buildings here.', 'Здесь слишком много высоких зданий.'),
        'New York has many skyscrapers.': ('New York has too many skyscrapers for me.', 'Для меня в Нью-Йорке слишком много небоскрёбов.'),
        'There is a tunnel under the river.': ('The tunnel is not wide enough for buses.', 'Туннель недостаточно широкий для автобусов.'),
        'We go to the park on Sundays.': ('The park is big enough for a picnic.', 'Парк достаточно большой для пикника.'),
        'The main square is beautiful.': ('The main square is too crowded on Saturdays.', 'Главная площадь слишком многолюдная по субботам.'),
        'It is rush hour.': ('There is too much traffic in rush hour.', 'В час пик слишком много машин.'),
        'The village has fresh air.': ('The village has enough fresh air for everyone.', 'В деревне достаточно свежего воздуха для всех.'),
    })
    return new


THEORY[T] = theory_A2_12


def _zero_hint(topic: str, session: int, order: int, **extra) -> None:
    """Tell the learner how to mark the zero article: the lab grader accepts
    «—» / «-» / «нет артикля» (item 25), but the question has to say so."""
    data = base._load_json(BEFORE / f'grammar_extra_{topic}.json')
    ex = next(e for s in data['sessions'] if s['session_number'] == session for e in s['exercises'] if e['order'] == order)
    q = ex['content']['question']
    assert ex['exercise_type'] == 'fill_blank' and ex['content']['correct_answer'] == '—' and '(' not in q, (topic, session, order, q)
    fix(topic, session, order, question=f'{q} (— или «-», если артикль не нужен)', **extra)


# ============================================ A2_13 the + geography ======
T = 'A2_13'
base.EDITS[T] = {}
for _s, _o in ((1, 2), (2, 2), (3, 1), (5, 2)):
    _zero_hint(T, _s, _o)
fix(T, 7, 9, words=['The', 'Philippines', 'have', 'many', 'beautiful', 'islands', '.'],
    correct_answer='The Philippines have many beautiful islands.',
    explanation='С названиями стран во множественном числе ставится the: the Philippines. Перевод: На Филиппинах много красивых островов.')


def theory_A2_13(content: dict) -> dict:
    new = copy.deepcopy(content)
    dup = _dup_section(new)
    dup['subtitle'] = 'Озёра, горы, моря и проливы'
    dup['description'] = ('Lake + название и Mount + название — без артикля; моря, проливы, каналы, а также названия с Republic / Kingdom / '
                          'States — с the.')
    dup['table'] = [
        {'label': 'Lake + название', 'article': '—', 'example': 'Lake Baikal, Lake Geneva', 'translation': 'Байкал, Женевское озеро'},
        {'label': 'Mount + название', 'article': '—', 'example': 'Mount Everest, Mount Fuji', 'translation': 'Эверест, Фудзи'},
        {'label': 'Моря, проливы, каналы', 'article': 'the', 'example': 'the Red Sea, the English Channel', 'translation': 'Красное море, Ла-Манш'},
        {'label': 'Republic / Kingdom / States', 'article': 'the', 'example': 'the Czech Republic, the United Kingdom', 'translation': 'Чехия, Соединённое Королевство'},
        {'label': 'Регионы', 'article': 'the', 'example': 'the Middle East, the North of England', 'translation': 'Ближний Восток, север Англии'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_13

# ======================================= A2_14 zero article with meals ===
T = 'A2_14'
base.EDITS[T] = {}
for _s, _o in ((1, 1), (1, 2), (2, 1), (3, 2), (3, 3), (4, 1), (5, 1), (7, 1)):
    _zero_hint(T, _s, _o)
replace(T, 3, 1, 'fill_blank', question='___ dinner we had last night was absolutely delicious.', correct_answer='The', alternatives=[],
        explanation='Приём пищи определён придаточным (we had last night) — это конкретный ужин, поэтому the. Перевод: Ужин, который мы ели вчера вечером, был очень вкусным.')
replace(T, 4, 3, 'multiple_choice', question='___ lunch they served at the conference was very nutritious.', options=['The', '—', 'A', 'An'], correct_answer='The',
        explanation='Lunch определён придаточным (they served at the conference) — конкретный обед, поэтому the. Перевод: Обед, который подавали на конференции, был очень питательным.')
replace(T, 6, 1, 'fill_blank', question='We usually have ___ lunch at school at noon. (— или «-», если артикль не нужен)', correct_answer='—', alternatives=[],
        explanation='Lunch как регулярный приём пищи употребляется без артикля: have lunch. Перевод: Обычно мы обедаем в школе в полдень.')
replace(T, 6, 8, 'error_correction', sentence='A brunch that she made was very tasty and nutritious.', correct_answer='The brunch that she made was very tasty and nutritious.',
        error_word='A', correct_word='The', alternatives=['The'],
        explanation='Ошибка: brunch определён придаточным (that she made) — это конкретный бранч, нужен the, а не a. Перевод: Бранч, который она приготовила, был очень вкусным и питательным.')
replace(T, 6, 9, 'reorder', words=['We', 'always', 'have', 'breakfast', 'at', 'eight', '.'], correct_answer='We always have breakfast at eight.',
        explanation='Перевод: Мы всегда завтракаем в восемь. Breakfast — без артикля.')
replace(T, 6, 10, 'reorder', words=['She', 'cooked', 'a', 'delicious', 'dinner', 'for', 'us', '.'], correct_answer='She cooked a delicious dinner for us.',
        explanation='Перевод: Она приготовила для нас вкусный ужин. Прилагательное delicious требует артикля a.')
replace(T, 7, 5, 'translation', question='На обед я обычно ем суп и салат.', correct_answer='I usually have soup and a salad for lunch.',
        alternatives=['For lunch I usually have soup and a salad.', 'I usually eat soup and a salad for lunch.', 'I usually have soup and salad for lunch.'],
        explanation='For lunch — без артикля; soup — неисчисляемое, a salad — блюдо с артиклем. Перевод: I usually have soup and a salad for lunch.')
replace(T, 7, 10, 'reorder', words=['What', 'do', 'you', 'usually', 'have', 'for', 'dinner', '?'], correct_answer='What do you usually have for dinner?',
        explanation='Перевод: Что ты обычно ешь на ужин? For dinner — без артикля.')
replace(T, 8, 1, 'fill_blank', question='We had ___ well-balanced dinner with fish and vegetables.', correct_answer='a', alternatives=[],
        explanation='Перед приёмом пищи стоит прилагательное (well-balanced), поэтому нужен артикль a. Перевод: У нас был сбалансированный ужин с рыбой и овощами.')
replace(T, 8, 4, 'translation', question='После ужина мы обычно едим фрукты.', correct_answer='After dinner we usually eat fruit.',
        alternatives=['We usually eat fruit after dinner.', 'After dinner, we usually eat fruit.', 'After dinner we usually have fruit.'],
        explanation='After dinner — без артикля; fruit здесь неисчисляемое. Перевод: After dinner we usually eat fruit.')
replace(T, 8, 6, 'translation', question='Завтрак, который она приготовила, был очень вкусным.', correct_answer='The breakfast she made was very tasty.',
        alternatives=['The breakfast that she made was very tasty.', 'The breakfast she cooked was very tasty.', 'The breakfast she made was very delicious.'],
        explanation='Breakfast определён придаточным (she made) — конкретный завтрак, поэтому the. Перевод: The breakfast she made was very tasty.')
replace(T, 8, 7, 'error_correction', sentence="We usually have a lunch at one o'clock.", correct_answer="We usually have lunch at one o'clock.",
        error_word='a lunch', correct_word='lunch', alternatives=['lunch'],
        explanation='Ошибка: lunch как регулярный приём пищи не требует артикля a. Правильно: have lunch. Перевод: Обычно мы обедаем в час.')
fix(T, 8, 10, words=['lunch', 'at', '.', 'school', 'eat', 'Children', 'nutritious', 'a'], correct_answer='Children eat a nutritious lunch at school.',
    explanation='Перевод: Дети едят питательный обед в школе. Прилагательное nutritious требует артикля a.')


def theory_A2_14(content: dict) -> dict:
    new = copy.deepcopy(content)
    old_extra = new['sections'][2]
    assert old_extra['subtitle'].startswith('Дополнительные примеры') and len(new['sections']) == 5, [s['subtitle'] for s in new['sections']]
    _swap_examples(old_extra, {
        'I eat fruit every day.': ('I eat fruit for breakfast every day.', 'Я ем фрукты на завтрак каждый день.'),
        'I love fresh vegetables.': ('We have fresh vegetables with dinner.', 'На ужин мы едим свежие овощи.'),
        'She picks berries in summer.': ('She has berries for breakfast in summer.', 'Летом она ест ягоды на завтрак.'),
        'Orange juice is sweet.': ('I drink orange juice at breakfast.', 'Я пью апельсиновый сок за завтраком.'),
        'Hot soup is good in winter.': ('We have hot soup for lunch in winter.', 'Зимой на обед мы едим горячий суп.'),
        'We buy fresh bread.': ('We buy fresh bread for breakfast.', 'Мы покупаем свежий хлеб на завтрак.'),
        'I like cheese on toast.': ('I like cheese on toast for breakfast.', 'На завтрак я люблю сыр на тосте.'),
        'We eat fish on Fridays.': ('We eat fish for dinner on Fridays.', 'По пятницам на ужин мы едим рыбу.'),
        'Some people do not eat meat.': ('Some people do not eat meat at dinner.', 'Некоторые не едят мясо за ужином.'),
        'I love fresh bread.': ('We had a light supper with fresh bread.', 'У нас был лёгкий ужин со свежим хлебом.'),
        'This soup is tasty.': ('The lunch we had was tasty.', 'Обед, который мы ели, был вкусным.'),
        'My mother gave me her recipe.': ('My mother gave me her recipe for a healthy breakfast.', 'Мама дала мне рецепт здорового завтрака.'),
    })
    new['sections'] = [
        {'subtitle': 'Приёмы пищи — без артикля',
         'description': 'Breakfast, lunch, dinner, supper, brunch как регулярные приёмы пищи употребляются без артикля.',
         'table': [
             row(pronoun='have / eat', form='breakfast', example='I have breakfast at 8.', translation='Я завтракаю в 8.'),
             row(pronoun='cook / make', form='lunch', example='He cooks lunch every day.', translation='Он готовит обед каждый день.'),
             row(pronoun='have', form='dinner', example='We have dinner together.', translation='Мы ужинаем вместе.'),
             row(pronoun='skip', form='supper / brunch', example='They never skip supper.', translation='Они никогда не пропускают ужин.'),
         ]},
        {'subtitle': 'Когда артикль появляется',
         'description': 'A/an — если перед приёмом пищи стоит прилагательное (какой ужин?); the — когда речь о конкретном приёме пищи.',
         'table': [
             row(pronoun='a + прилагательное + meal', example='I had a delicious brunch.', translation='У меня был вкусный бранч.'),
             row(pronoun='a + прилагательное + meal', example='She made a big dinner for us.', translation='Она приготовила для нас большой ужин.'),
             row(pronoun='the + meal + уточнение', example='The dinner we had last night was tasty.', translation='Ужин, который мы ели вчера, был вкусным.'),
             row(pronoun='the + meal (тот самый)', example='Did you enjoy the lunch?', translation='Тебе понравился (тот) обед?'),
         ]},
        {'subtitle': 'For / at / before / after + приём пищи',
         'description': 'После предлогов названия приёмов пищи тоже стоят без артикля.',
         'table': [
             row(pronoun='for', example='What do you have for breakfast?', translation='Что ты ешь на завтрак?'),
             row(pronoun='at', example='We talked at dinner.', translation='Мы разговаривали за ужином.'),
             row(pronoun='before / after', example='Wash your hands before lunch. Have a walk after dinner.', translation='Мой руки перед обедом. Прогуляйся после ужина.'),
         ]},
        {'subtitle': 'Блюда и перекусы — с артиклем',
         'description': 'Snack, salad, sandwich, dessert — обычные исчисляемые существительные: a snack, a salad. Неисчисляемые (soup, bread) — без a.',
         'table': [
             row(pronoun='a snack', example='I had a small snack.', translation='Я немного перекусил.'),
             row(pronoun='a salad', example='I made a salad for dinner.', translation='Я сделал салат на ужин.'),
             row(pronoun='a dessert', example='They ordered a dessert after dinner.', translation='После ужина они заказали десерт.'),
             row(pronoun='неисчисляемые — без a', example='We had soup and bread for lunch.', translation='На обед у нас были суп и хлеб.'),
         ]},
        old_extra,
    ]
    new['rule'] = ('Названия приёмов пищи (breakfast, lunch, dinner, supper, brunch) употребляются без артикля: have breakfast, for lunch, '
                   'at dinner. Артикль появляется с прилагательным (a big dinner) или когда речь о конкретном приёме пищи (the dinner we had).')
    new['important_notes'] = [
        "⚠️ НЕ говорите: 'I have a breakfast' — правильно: 'I have breakfast'",
        "✅ С прилагательным артикль нужен: 'I had a big breakfast'",
        "✅ Конкретный приём пищи — the: 'The lunch they served was great'",
        '⚠️ Блюда и перекусы — обычные существительные: a snack, a salad, a sandwich',
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_14

# ================================== A2_15 — polished in item 20, untouched
base.EDITS['A2_15'] = {}  # the base module ships item 20's edits for this slug; they are already in prod
THEORY['A2_15'] = copy.deepcopy  # theory untouched

# ======================================= A2_16 Present Continuous future ==
T = 'A2_16'
base.EDITS[T] = {}


def theory_A2_16(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][3]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'I am leaving now.': ('I am leaving for London tomorrow.', 'Я уезжаю в Лондон завтра.'),
        'I am working on a weekday.': ('I am working late on Friday.', 'В пятницу я работаю до позднего вечера.'),
        'I am having an appointment at noon.': ('I am seeing the dentist at noon.', 'В полдень я иду к стоматологу (записан).'),
        'I am confirming the appointment now.': ('I am confirming the appointment later today.', 'Я подтвержу встречу позже сегодня.'),
        'I am cancelling the appointment.': ('I am cancelling the appointment tomorrow morning.', 'Завтра утром я отменяю встречу.'),
        'I am changing my plans.': ('We are changing our plans for next weekend.', 'Мы меняем планы на следующие выходные.'),
        'Are you available at 5?': ('Are you meeting the client at 5?', 'Ты встречаешься с клиентом в 5?'),
        'I am busy tonight.': ('I am staying at home tonight.', 'Сегодня вечером я остаюсь дома.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Сейчас, договорённость или намерение?'
    dup['description'] = ('Без маркера времени Present Continuous — действие сейчас; с маркером будущего — договорённость; '
                          'be going to — намерение; глаголы состояния (have, know, want) остаются в Present Simple.')
    dup['table'] = [
        row(pronoun='сейчас', form='без маркера / now', example='I am working now.', translation='Я сейчас работаю.'),
        row(pronoun='договорённость', form='+ маркер будущего', example='I am working on Saturday.', translation='Я работаю в субботу (так договорились).'),
        row(pronoun='намерение', form='be going to', example='I am going to look for a new job.', translation='Я собираюсь искать новую работу (пока намерение).'),
        row(pronoun='глаголы состояния', form='Present Simple', example='I have an appointment at noon.', translation='У меня встреча в полдень (не «I am having»).'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_16

# ================================================ A2_17 be going to =======
T = 'A2_17'
base.EDITS[T] = {}


def theory_A2_17(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'We are going on holiday next week.': ('We are going to go on holiday next week.', 'На следующей неделе мы собираемся поехать в отпуск.'),
        'I need a vacation!': ('I am going to take a vacation in July.', 'В июле я собираюсь взять отпуск.'),
        'I love to travel.': ('I am going to travel around Europe.', 'Я собираюсь путешествовать по Европе.'),
        "We're planning a trip to Paris.": ("We're going to plan a trip to Paris.", 'Мы собираемся спланировать поездку в Париж.'),
        'Our flight is at 9 AM.': ("Our flight is at 9 AM, so we're going to get up early.", 'Наш рейс в 9 утра, поэтому мы собираемся встать рано.'),
        'We need to be at the airport early.': ("We're going to be at the airport two hours before the flight.", 'Мы собираемся быть в аэропорту за два часа до рейса.'),
        "Don't forget your passport!": ("Are you going to take your passport?", 'Ты собираешься взять паспорт?'),
        'There are many tourists in this city.': ('Many tourists are going to visit this city in summer.', 'Летом этот город собираются посетить многие туристы.'),
        "We're going sightseeing tomorrow.": ("We're going to go sightseeing tomorrow.", 'Завтра мы собираемся осматривать достопримечательности.'),
    })
    return new


THEORY[T] = theory_A2_17

# ======================================================== A2_18 will =====
T = 'A2_18'
base.EDITS[T] = {}
_hint(T, 4, 1, 'show')
replace(T, 6, 8, 'error_correction', sentence='The drought will affects the whole region this summer.', correct_answer='The drought will affect the whole region this summer.',
        error_word='affects', correct_word='affect', alternatives=['affect'],
        explanation='Ошибка: после «will» глагол стоит в начальной форме без «-s». Правильный вариант: The drought will affect the whole region this summer.')


def theory_A2_18(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][5]
    assert extra['subtitle'].startswith('Дополнительные примеры') and len(extra['table']) == 5, extra
    _swap_examples(extra, {
        'The weather is nice today.': ('The weather will be nice tomorrow.', 'Завтра будет хорошая погода.'),
        'There is rain in the afternoon.': ('There will be rain in the afternoon.', 'После полудня будет дождь.'),
        'Snow falls in winter.': ('It will snow in the mountains this winter.', 'Этой зимой в горах пойдёт снег.'),
        'The wind is cold today.': ('The wind will be cold tonight, so take a coat.', 'Ночью ветер будет холодным, так что возьми пальто.'),
        'There are clouds in the sky.': ("Look at the clouds — I think it'll be cloudy all day.", 'Посмотри на облака: думаю, весь день будет облачно.'),
    })
    extra['table'] += [row(example=en, translation=ru) for en, ru in [
        ('Will it be sunny at the weekend?', 'В выходные будет солнечно?'),
        ("It's hot in here. I'll open the window.", 'Здесь жарко. Я открою окно.'),
        ("You won't need an umbrella — it won't rain.", 'Зонт тебе не понадобится: дождя не будет.'),
        ('The temperature will drop at night.', 'Ночью температура упадёт.'),
        ("We'll probably see a rainbow after the storm.", 'После грозы мы, наверное, увидим радугу.'),
    ]]
    return new


THEORY[T] = theory_A2_18


# ================================================== A2_19 so / such =======
T = 'A2_19'
base.EDITS[T] = {}


def theory_A2_19(content: dict) -> dict:
    new = copy.deepcopy(content)
    diff = new['sections'][3]
    assert diff['subtitle'].startswith('Разница между So и Such'), diff['subtitle']
    diff['table'].append({'pronoun': 'SO', 'verb': '+ many / much', 'example': 'so many songs, so much creativity',
                          'translation': 'так много песен, столько творчества (не «such many»)'})
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'I love the rhythm in this song.': ('The rhythm in this song is so catchy!', 'Ритм в этой песне такой запоминающийся!'),
        'She studies art at university.': ('She creates such beautiful art.', 'Она создаёт такое красивое искусство.'),
        'This is my favorite song.': ('It is such a beautiful song!', 'Это такая красивая песня!'),
        'She can hum very well.': ('She hums so well that everyone listens.', 'Она напевает так хорошо, что все слушают.'),
        'They do ballet every weekend.': ('They dance ballet so gracefully.', 'Они танцуют балет так грациозно.'),
        'I perform on the guitar at concerts.': ('He performs so confidently at concerts.', 'Он выступает на концертах так уверенно.'),
        'He has a beautiful guitar.': ('He has such an expensive guitar.', 'У него такая дорогая гитара.'),
        'She performs on the piano at concerts.': ('She plays the piano so beautifully!', 'Она играет на пианино так красиво!'),
        'My brother performs on the drums in a band.': ('My brother plays the drums so loudly that the neighbours complain.', 'Мой брат играет на барабанах так громко, что соседи жалуются.'),
        'The violin sounds beautiful.': ('The violin has such a warm sound.', 'У скрипки такое тёплое звучание.'),
        'I like to paint landscapes.': ('He paints such realistic landscapes.', 'Он пишет такие реалистичные пейзажи.'),
        'Can you sketch a landscape?': ('You sketch so quickly!', 'Ты делаешь наброски так быстро!'),
    })
    return new


THEORY[T] = theory_A2_19

# ============================================ A2_20 zero conditional ======
T = 'A2_20'
base.EDITS[T] = {}


def theory_A2_20(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][4]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'I love spending time in nature.': ('If I spend time in nature, I feel calm.', 'Если я проводю время на природе, я чувствую спокойствие.'),
        'There are many trees in the forest.': ('If a forest has many trees, the air is fresh.', 'Если в лесу много деревьев, воздух свежий.'),
        'These flowers are beautiful.': ("If you don't water flowers, they die.", 'Если не поливать цветы, они погибают.'),
        'We walk in the forest on Sundays.': ('When the weather is good, we walk in the forest.', 'Когда погода хорошая, мы гуляем в лесу.'),
        'The river is very wide.': ('If it rains a lot, the river gets wider.', 'Если много дождей, река становится шире.'),
        'After a blizzard, the mountains are covered in white.': ('When there is a blizzard, the mountains are covered in white.', 'Когда бывает метель, горы покрыты белым.'),
        'I love swimming in the sea.': ('If the sea is warm, we swim every day.', 'Если море тёплое, мы плаваем каждый день.'),
        'The sun shines brightly.': ('If the sun shines brightly, the grass dries quickly.', 'Если солнце светит ярко, трава быстро высыхает.'),
        'The sky is blue today.': ('When the sky is grey, it usually rains.', 'Когда небо серое, обычно идёт дождь.'),
        'The grass is green.': ('If it rains, the grass gets green.', 'Если идёт дождь, трава зеленеет.'),
        'We must protect the environment.': ("If we don't protect the environment, animals lose their homes.", 'Если мы не защищаем окружающую среду, животные теряют дома.'),
        'Some forests are wild and untouched.': ('If a forest is wild, many birds live there.', 'Если лес дикий, там живёт много птиц.'),
        'This plant needs water.': ('If a plant gets no water, it dies.', 'Если растение не получает воды, оно погибает.'),
    })
    return new


THEORY[T] = theory_A2_20

# =========================================== A2_21 first conditional ======
T = 'A2_21'
base.EDITS[T] = {}


def theory_A2_21(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[4]['subtitle'].startswith('Дополнительные примеры'), sections[4]['subtitle']
    sections.insert(3, {
        'subtitle': 'Unless = if not.',
        'description': 'Unless уже содержит отрицание: Unless we recycle = If we don\'t recycle. После unless — Present Simple без won\'t.',
        'table': [
            row(pronoun='Unless', form='= if not', example="Unless we recycle, the planet will suffer.", translation='Если мы не будем перерабатывать, планета пострадает.'),
            row(pronoun='If … not', form='то же значение', example="If we don't recycle, the planet will suffer.", translation='Если мы не будем перерабатывать, планета пострадает.'),
            row(pronoun='WRONG', form="unless + won't", example="❌ Unless we won't recycle...", translation='НЕПРАВИЛЬНО: двойное отрицание'),
        ],
    })
    _swap_examples(sections[5], {
        'We must protect the environment.': ("If we protect the environment, our children will have a healthy planet.", 'Если мы будем защищать окружающую среду, у наших детей будет здоровая планета.'),
        'I love walking in nature.': ('If the weather is good, I will walk in nature tomorrow.', 'Если погода будет хорошей, завтра я пойду гулять на природу.'),
        'Our planet is beautiful.': ("If we don't stop pollution, our planet won't be beautiful.", 'Если мы не остановим загрязнение, наша планета не будет красивой.'),
        'Earth is our home.': ("If we damage Earth, we will damage our home.", 'Если мы повредим Землю, мы повредим свой дом.'),
        'We need clean water.': ("If the river is dirty, we won't have clean water.", 'Если река грязная, у нас не будет чистой воды.'),
        'The air in the forest is fresh.': ('If we plant more trees, the air will be fresher.', 'Если мы посадим больше деревьев, воздух станет свежее.'),
        'We planted a small tree.': ('If you plant a tree today, it will grow big in twenty years.', 'Если ты посадишь дерево сегодня, через двадцать лет оно вырастет большим.'),
        'The forest is full of animals.': ("If we cut down the forest, the animals will lose their homes.", 'Если мы вырубим лес, животные потеряют свои дома.'),
        'We swim in the river.': ('We will swim in the river if the water is clean.', 'Мы будем купаться в реке, если вода будет чистой.'),
        'We go to the sea in summer.': ("If the sea is polluted, tourists won't come.", 'Если море загрязнено, туристы не приедут.'),
        'Wild animals need space.': ("Unless we protect wild animals, many species will disappear.", 'Если мы не защитим диких животных, многие виды исчезнут.'),
        'Plants need light and water.': ("If plants don't get water, they will die.", 'Если растения не получат воды, они погибнут.'),
        'Clean water is important.': ('If we save water, there will be enough for everyone.', 'Если мы будем экономить воду, её хватит всем.'),
        'The river is dirty.': ('If the factory stops dumping waste, the river will be clean again.', 'Если завод перестанет сбрасывать отходы, река снова станет чистой.'),
        'Do not throw rubbish on the street.': ('If people throw rubbish on the street, the city will be dirty.', 'Если люди будут бросать мусор на улице, город будет грязным.'),
        'We recycle paper at home.': ('If we recycle paper, we will save trees.', 'Если мы будем перерабатывать бумагу, мы сохраним деревья.'),
        'We must protect the forests.': ("Unless we protect the forests, the climate will change faster.", 'Если мы не защитим леса, климат будет меняться быстрее.'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_A2_21


# ======================================= A2_22 Past Simple regular ========
T = 'A2_22'
base.EDITS[T] = {}


def theory_A2_22(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = new['sections'][5]
    assert extra['subtitle'].startswith('Дополнительные примеры'), extra['subtitle']
    _swap_examples(extra, {
        'Christmas is my favorite holiday.': ('We celebrated Christmas with the whole family last year.', 'В прошлом году мы праздновали Рождество всей семьёй.'),
        "It's a family tradition.": ('We followed the family tradition and cooked a big dinner.', 'Мы последовали семейной традиции и приготовили большой ужин.'),
        'I blew out the candles.': ('We placed ten candles on the cake.', 'Мы поставили на торт десять свечей.'),
    })
    return new


THEORY[T] = theory_A2_22

# ===================================== A2_23 Past Simple irregular ========
T = 'A2_23'
base.EDITS[T] = {}


def theory_A2_23(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[4]['subtitle'].startswith('Маркеры времени'), sections[4]['subtitle']
    # Sessions 6–8 quiz twenty irregular verbs that the 20-pair table never shows.
    sections.insert(5, {
        'subtitle': 'Ещё неправильные глаголы из заданий',
        'description': 'Эти формы тоже встречаются в упражнениях — выучите их вместе с основной двадцаткой.',
        'table': [
            {'present': p, 'past': q, 'translation': ru, 'example': ex} for p, q, ru, ex in [
                ('think', 'thought', 'думать', 'I thought it was a good idea.'),
                ('bring', 'brought', 'приносить', 'She brought a cake to the party.'),
                ('teach', 'taught', 'учить (кого-то)', 'My grandmother taught me to cook.'),
                ('catch', 'caught', 'ловить', 'He caught the ball.'),
                ('tell', 'told', 'рассказывать', 'She told an interesting story.'),
                ('know', 'knew', 'знать', "I knew the answer."),
                ('understand', 'understood', 'понимать', 'We understood the lesson.'),
                ('forget', 'forgot', 'забывать', 'I forgot my umbrella at home.'),
                ('wake', 'woke', 'просыпаться', 'I woke up at seven.'),
                ('fall', 'fell', 'падать', 'Half of the people fell asleep.'),
                ('wear', 'wore', 'носить (одежду)', 'She wore a warm coat.'),
                ('break', 'broke', 'ломать, разбивать', 'Who broke this window?'),
                ('lose', 'lost', 'терять', 'She lost her way in the city.'),
                ('send', 'sent', 'отправлять', 'They sent the letter yesterday.'),
                ('leave', 'left', 'уходить, оставлять', 'He said hello and left.'),
                ('drink', 'drank', 'пить', 'They drank the coffee.'),
                ('sing', 'sang', 'петь', 'The teacher sang a song.'),
                ('begin', 'began', 'начинать', 'The children began to laugh.'),
                ('win', 'won', 'выигрывать', 'The team won the match.'),
                ('feel', 'felt', 'чувствовать', 'She felt cold.'),
            ]
        ],
    })
    return new


THEORY[T] = theory_A2_23


# grammar_topics.content mirrors the grammar lesson of the module, but on the prod copy two
# mirrors lag behind the lesson (the lesson was corrected later, the mirror was not): a2-4 still
# says «a bottle of water/wine» where the lesson says «juice», a2-16 lists «now» where the lesson
# lists «tomorrow». The item-25 patch is keyed on the lesson's content, so the mirror has to be
# aligned first. Each UPDATE is keyed on the stale value it fixes: it is a no-op once aligned and
# a no-op on a mirror that drifted some other way (the preflight then reports that instead).
# The rollback file leaves the alignment in place — a mirror equal to its lesson is never wrong.
DRIFT_PROBES = {
    'A2_4': ("content->'sections'->1->'table'->0->>'example'", 'a bottle of water/wine'),
    'A2_16': ("content->'sections'->2->'table'->3->>'time_indicator'", 'now'),
}


def drift_alignment_sql(olds: dict[str, dict]) -> str:
    lines = ['-- Item 25 pre-step: align the grammar_topics mirror with the lesson where it lags behind',
             '-- (expected: 1 row each on a copy that still carries the stale value, 0 rows once aligned).']
    for topic, (probe, stale) in DRIFT_PROBES.items():
        payload = {k: olds[topic][k] for k in base.TOPIC_KEYS if k in olds[topic]}
        blob = json.dumps(payload, ensure_ascii=False)
        assert '$q$' not in blob
        lines.append(f"UPDATE grammar_topics SET content = content || $q${blob}$q$::jsonb\n"
                     f"WHERE slug = '{base.TOPICS[topic]['slug']}' AND {probe} = $q${stale}$q$;  -- {topic}")
    return '\n'.join(lines) + '\n\n'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not BEFORE.exists():
        print(f'snapshot dir missing: {BEFORE}', file=sys.stderr)
        return 2
    base.BEFORE = BEFORE
    base.ASSERT_LABEL = 'item25'
    base.SQL_TITLE = 'Lesson audit item 25: grammar content of the whole A2 level (23 topics). Apply AFTER items 21-24.'
    base.TOPICS.clear()
    base.TOPICS.update(topic_meta())
    base.THEORY.clear()
    base.THEORY.update(THEORY)
    all_changes, theory, outputs, olds = {}, {}, [], {}
    for topic in sorted(base.TOPICS, key=lambda t: int(t.split('_')[1])):
        base.EDITS.setdefault(topic, {})
        data, changes = base.build_exercises(topic)
        base.validate_exercises(topic, data)
        module, old_extra, new_extra = base.build_theory(topic)
        olds[topic] = old_extra
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
    sql = base.emit_sql(all_changes, theory)
    for suffix in ('1_check', '2_apply'):
        sql[suffix] = sql[suffix].replace('\n\n', '\n\n' + drift_alignment_sql(olds), 1)
    for suffix, text in sql.items():
        path = base.EXPORT_DIR / f'{SQL_PREFIX}_{suffix}.sql'
        path.write_text(text, encoding='utf-8')
        print('wrote', path.relative_to(ROOT), f'({len(text) // 1024} KiB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
