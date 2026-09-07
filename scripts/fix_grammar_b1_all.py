#!/usr/bin/env python3
"""Lesson audit item 26 — deep pass over the whole B1 grammar level (19 topics).

Owner's decision 2026-09-07: «действуй» after A1 and A2 were closed (items 20–25).
Same delivery machinery as items 20–25 (``scripts/fix_grammar_topics_3.py``);
snapshot of all 38 sources in ``local_exports/grammar_b1_all_before/``. Item 21
touched several B1 topics, so in production this SQL is applied AFTER item 21.

Usage::

    venv/bin/python scripts/fix_grammar_b1_all.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_b1_all.py --check    # summary only
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

BEFORE = ROOT / 'local_exports' / 'grammar_b1_all_before'
SQL_PREFIX = 'item26_grammar_b1_all'
LEVEL = 'B1'
fix, replace, row = base.fix, base.replace, base._row
THEORY: dict = {}


def topic_meta() -> dict[str, dict]:
    meta = {}
    for path in sorted(BEFORE.glob(f'grammar_extra_{LEVEL}_*.json')):
        name = path.stem[len('grammar_extra_'):]
        number = int(name.split('_')[1])
        module_file = next(p.name for p in BEFORE.glob(f'module_{LEVEL}_{number}_*.json'))
        meta[name] = {'slug': f'{LEVEL.lower()}-{number}', 'level': LEVEL, 'module': number, 'module_file': module_file}
    return meta


def _swap_examples(section: dict, swaps: dict[str, tuple[str, str]]) -> None:
    seen = 0
    for i, r in enumerate(section['table']):
        if isinstance(r, dict) and r.get('example') in swaps:
            en, ru = swaps[r['example']]
            section['table'][i] = base._set_example(r, en, ru)
            seen += 1
    assert seen == len(swaps), (section.get('subtitle'), seen, len(swaps))


def _dup_section(content: dict, prefix: str = 'Употребление в утверждении') -> dict:
    """The generator's «Употребление в …» section that merely repeats the first
    rows of the examples section."""
    for s in content['sections']:
        if str(s.get('subtitle', '')).startswith(prefix):
            return s
    raise AssertionError(f'no duplicate section {prefix!r}')


def _exercise(topic: str, session: int, order: int) -> dict:
    data = base._load_json(BEFORE / f'grammar_extra_{topic}.json')
    return next(e for s in data['sessions'] if s['session_number'] == session for e in s['exercises'] if e['order'] == order)


def _hint(topic: str, session: int, order: int, hint: str, **extra) -> None:
    """Add a bracketed hint after the (single) blank of a fill_blank."""
    ex = _exercise(topic, session, order)
    q = ex['content']['question']
    assert ex['exercise_type'] == 'fill_blank' and q.count('___') == 1 and '(' not in q, (topic, session, order, q)
    fix(topic, session, order, question=q.replace('___', f'___ ({hint})', 1), **extra)


def _extra_section(content: dict) -> dict:
    return next(s for s in content['sections'] if str(s.get('subtitle', '')).startswith('Дополнительные примеры'))


# ================================================ B1_1 Past Simple irregular
T = 'B1_1'
base.EDITS[T] = {}
# The authored answer «broke ... won» could not be typed by any learner: two blanks, one
# free-text field. One blank, one hinted verb — the second one stays as a worked example.
fix(T, 8, 1, question='The athlete ___ (break) the world record and won a gold medal at the Olympics.',
    correct_answer='broke', alternatives=[],
    explanation='Глагол break — неправильный: break → broke. Второй глагол в предложении уже стоит в Past Simple (win → won), '
                'оба действия завершились в прошлом. Перевод: Спортсмен побил мировой рекорд и выиграл золотую медаль на Олимпиаде.')
THEORY[T] = copy.deepcopy

# ====================================== B1_2 Past Continuous vs Past Simple
T = 'B1_2'
base.EDITS[T] = {}
fix(T, 4, 9, explanation='Они танцевали, когда пошёл дождь. Танец — фоновый процесс (Past Continuous: were dancing), '
                         'начало дождя — прерывающее событие (Past Simple: started).')


def theory_B1_2(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[0]['subtitle'].startswith('Past Continuous') and len(sections[0]['table']) == 1, sections[0]
    sections[0]['table'].append(row(pronoun='You/We/They', form='were watching', example='They were watching a thriller at 8 pm.',
                                    translation='В 8 вечера они смотрели триллер.'))
    sections[0]['table'][0] = row(pronoun='I/He/She/It', form='was watching', example='I was watching a movie.', translation='Я смотрел фильм.')
    assert sections[4]['subtitle'].startswith('Когда использовать Past Simple'), sections[4]['subtitle']
    sections[4]['table'] += [
        row(pronoun='Sequence', form='Past Simple + Past Simple', example='The actor came onto the stage and the audience applauded.',
            translation='Актёр вышел на сцену, и публика зааплодировала.'),
        row(pronoun='Stative verbs', form='know / want / like / hear — только Past Simple',
            example='I knew the plot, but I heard a strange noise during the scene. (не was knowing / was hearing)',
            translation='Я знал сюжет, но во время сцены услышал странный звук.'),
    ]
    extra = _extra_section(new)
    _swap_examples(extra, {
        'We went to the cinema last night.': ('We were going to the cinema when it started to rain.', 'Мы шли в кино, когда начался дождь.'),
        'It was a great movie!': ('I was watching a great movie when the lights went out.', 'Я смотрел отличный фильм, когда погас свет.'),
        'This film won many awards.': ('While the film was winning awards, the director was already shooting a new one.', 'Пока фильм собирал награды, режиссёр уже снимал новый.'),
        'The theatre was full of people.': ('The theatre was filling up when we arrived.', 'Театр заполнялся, когда мы приехали.'),
        'The performance was amazing.': ('The performance was going well until an actor forgot his lines.', 'Представление шло хорошо, пока актёр не забыл слова.'),
        'He is a famous actor.': ('The famous actor was signing autographs when we saw him.', 'Знаменитый актёр раздавал автографы, когда мы его увидели.'),
        'She is a talented actress.': ('The actress was rehearsing her role while the director was talking to the crew.', 'Актриса репетировала роль, пока режиссёр разговаривал со съёмочной группой.'),
        'The director won an Oscar.': ('The director was giving a speech when he dropped the Oscar.', 'Режиссёр произносил речь, когда уронил Оскар.'),
        'That was my favourite scene.': ('I was enjoying my favourite scene when my phone rang.', 'Я наслаждался любимой сценой, когда зазвонил телефон.'),
        'The plot was very interesting.': ('We were discussing the plot when the second part began.', 'Мы обсуждали сюжет, когда началась вторая часть.'),
        'The audience applauded.': ('The audience was applauding when the actors came onto the stage again.', 'Публика аплодировала, когда актёры снова вышли на сцену.'),
        'The actors came onto the stage.': ('The actors were performing when the fire alarm went off.', 'Актёры выступали, когда сработала пожарная сигнализация.'),
        'The premiere was yesterday evening.': ('Fans were waiting outside when the premiere started.', 'Поклонники ждали снаружи, когда началась премьера.'),
        'I love watching comedies.': ('I was watching a comedy and laughed the whole time.', 'Я смотрел комедию и смеялся всё время.'),
        'This drama made me cry.': ('I was crying at the end of the drama when the lights came on.', 'Я плакал в конце драмы, когда зажёгся свет.'),
        'That thriller was very exciting.': ('While we were watching the thriller, someone screamed in the back row.', 'Пока мы смотрели триллер, кто-то закричал в заднем ряду.'),
    })
    return new


THEORY[T] = theory_B1_2

# ================================================================ B1_3 used to
T = 'B1_3'
base.EDITS[T] = {}


def theory_B1_3(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = _extra_section(new)
    _swap_examples(extra, {
        'My childhood was happy.': ('My childhood used to be full of games in the yard.', 'Моё детство было полно игр во дворе.'),
        'I have a clear memory of that day.': ('I used to have a very good memory for dates.', 'Раньше у меня была очень хорошая память на даты.'),
        'In the past, we lived in a small town.': ('In the past, we used to live in a small town.', 'Раньше мы жили в маленьком городе.'),
        'He had a strict upbringing.': ("His parents used to be very strict — that was his upbringing.", 'Его родители раньше были очень строгими — таким было его воспитание.'),
        'When I was young, we did not have phones.': ("When I was young, we didn't use to have mobile phones.", 'Когда я был молод, у нас не было мобильных телефонов.'),
        'I miss my hometown.': ('I used to know everyone in my hometown.', 'Раньше я знал всех в родном городе.'),
        'I still see my classmates from school.': ('Did you use to sit next to your classmates at lunch?', 'Ты раньше сидел рядом с одноклассниками за обедом?'),
        'We looked through the old photo album.': ('We used to look through the old photo album every Christmas.', 'Раньше мы пересматривали старый фотоальбом каждое Рождество.'),
        'Every afternoon we ran to the playground.': ('Every afternoon we used to run to the playground.', 'Каждый день после обеда мы бегали на детскую площадку.'),
        'Our old neighbour told us many stories.': ('Our old neighbour used to tell us stories about the war.', 'Наш старый сосед рассказывал нам истории о войне.'),
        'I went to summer camp every July.': ('I used to go to summer camp every July.', 'Раньше я ездил в летний лагерь каждый июль.'),
        'Sunday dinner was our family tradition.': ('Sunday dinner used to be our family tradition.', 'Воскресный ужин раньше был нашей семейной традицией.'),
        'We waited for the school break.': ("We didn't use to like school breaks — we loved lessons!", 'Мы раньше не любили каникулы — мы обожали уроки!'),
        'I spent every summer with my grandparents.': ('I used to spend every summer with my grandparents.', 'Раньше я проводил каждое лето с дедушкой и бабушкой.'),
        'My favourite toy was an old teddy bear.': ("There used to be an old teddy bear on my bed.", 'Раньше на моей кровати лежал старый плюшевый мишка.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Не путать: used to / be used to / there used to be'
    dup['description'] = ('Used to + инфинитив — прошлая привычка; be used to + -ing — «привык к» (любое время); '
                          'there used to be — «раньше здесь был/была».')
    # The two constructions mean different things, so each gets its own row with its own
    # translation: «I am used to live here» is not a misspelling of «I used to live here»,
    # it is a broken «I am used to living here» (review of item 26).
    dup['table'] = [
        row(pronoun='used to + V', form='прошлая привычка, которой больше нет', example='I used to live here.',
            translation='Раньше я жил здесь (сейчас нет).'),
        row(pronoun='be used to + V-ing', form='«привык к», состояние сейчас', example='I am used to living here.',
            translation='Я привык здесь жить (и живу).'),
        row(pronoun='there used to be', form='раньше существовало', example='There used to be a playground here.',
            translation='Раньше здесь была детская площадка.'),
        row(pronoun='WRONG', form="после didn't — use to, без -d", example="❌ I didn't used to like it. → ✅ I didn't use to like it.",
            translation='Вспомогательный did уже несёт прошедшее время.'),
        row(pronoun='WRONG', form='после be used to — герундий', example='❌ I am used to live here. → ✅ I am used to living here.',
            translation='«Привык жить», а не «раньше жил».'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_3

# ============================================================ B1_4 as ... as
T = 'B1_4'
base.EDITS[T] = {}


def theory_B1_4(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[4]['subtitle'].startswith('Дополнительные примеры'), sections[4]['subtitle']
    sections.insert(4, {
        'subtitle': 'Столько же: as much / as many … as',
        'description': 'С существительными сравнение равенства строится через as much (неисчисляемые) и as many (исчисляемые); '
                       'существительное можно опустить, если оно ясно из контекста.',
        'table': [
            {'structure': 'as much + неисчисл. + as', 'example': "I don't have as much patience as my mother.", 'translation': 'У меня нет столько терпения, сколько у моей мамы.'},
            {'structure': 'as many + исчисл. + as', 'example': 'She has as many friends as her brother.', 'translation': 'У неё столько же друзей, сколько у брата.'},
            {'structure': 'as much as (без сущ.)', 'example': 'He helps as much as he can.', 'translation': 'Он помогает столько, сколько может.'},
            {'structure': 'as … as + he does / him', 'example': 'She is as ambitious as he is. = … as him.', 'translation': 'Она такая же амбициозная, как он.'},
        ],
    })
    _swap_examples(sections[5], {
        'Honesty is an important quality.': ('Honesty is as important a quality as loyalty.', 'Честность — такое же важное качество, как верность.'),
        'She has a strong character.': ('Her character is as strong as her father\'s.', 'У неё такой же сильный характер, как у отца.'),
        'He has a friendly personality.': ('His personality is not as friendly as it seems.', 'Его характер не такой дружелюбный, каким кажется.'),
        'She is a loyal friend.': ('She is as loyal as a friend can be.', 'Она верна настолько, насколько может быть верен друг.'),
        'He is a reliable person.': ('He is as reliable as my brother.', 'Он такой же надёжный, как мой брат.'),
        'My grandmother is very generous.': ('Nobody is as generous as my grandmother.', 'Никто не так щедр, как моя бабушка.'),
        "Don't be selfish!": ("Don't be as selfish as your cousin!", 'Не будь таким же эгоистом, как твой двоюродный брат!'),
        'Teachers need to be patient.': ('Teachers need to be as patient as parents.', 'Учителям нужно быть такими же терпеливыми, как родители.'),
        'He gets impatient when he waits.': ("He isn't as impatient as he used to be.", 'Он уже не такой нетерпеливый, как раньше.'),
        'She is confident in her abilities.': ('She is just as confident as her manager.', 'Она точно так же уверена в себе, как её руководитель.'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_4

# ==================================================== B1_5 reflexive pronouns
T = 'B1_5'
base.EDITS[T] = {}


def theory_B1_5(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = _extra_section(new)
    _swap_examples(extra, {
        'I have many relatives in this city.': ('My relatives introduced themselves to my new neighbours.', 'Мои родственники представились моим новым соседям.'),
        'They have a good relationship.': ('They built a good relationship by themselves, without any help.', 'Они построили хорошие отношения сами, без чьей-либо помощи.'),
        'Three generations live in this house.': ('Three generations take care of themselves in this house.', 'В этом доме три поколения заботятся о себе сами.'),
        'My grandparents live in the countryside.': ('My grandparents live by themselves in the countryside.', 'Мои бабушка и дедушка живут в деревне одни.'),
        'My nephew is five years old.': ('My nephew can dress himself — he is five.', 'Мой племянник умеет одеваться сам — ему пять.'),
        'My niece loves to read books.': ('My niece taught herself to read.', 'Моя племянница сама научилась читать.'),
        'I get along well with my in-laws.': ('I made myself get along with my in-laws.', 'Я заставил себя ладить с родственниками супруга.'),
        'Her stepfather is very kind.': ('Her stepfather himself cooked the dinner.', 'Её отчим сам приготовил ужин.'),
        'My stepmother treats me like her own child.': ('My stepmother enjoyed herself at our family party.', 'Моя мачеха хорошо провела время на нашем семейном празднике.'),
        "I have a half-brother from my father's first marriage.": ('My half-brother and I found ourselves at the same school.', 'Мы с сводным братом оказались в одной школе.'),
        'Parents show care for their children.': ('Parents should also take care of themselves.', 'Родителям следует заботиться и о себе.'),
        'Family support is very important.': ('You cannot support others if you do not support yourself.', 'Нельзя поддерживать других, если не поддерживаешь себя.'),
        'Trust is the foundation of family relationships.': ('Trust yourself first, then your family will trust you.', 'Сначала доверяй себе, тогда и семья будет тебе доверять.'),
        'Children should respect their parents.': ('Children learn to respect themselves at home.', 'Дети учатся уважать себя дома.'),
        'Siblings sometimes argue with each other.': ('Siblings argue with each other, not with themselves.', 'Братья и сёстры спорят друг с другом, а не сами с собой.'),
        "It's important to forgive family members.": ("It's important to forgive yourself, too.", 'Важно прощать и себя.'),
    })
    s4 = _dup_section(new, 'Употребление в утверждении')
    s4['subtitle'] = 'Возвратное, усилительное или взаимное?'
    s4['description'] = ('Одно и то же слово работает по-разному: myself как дополнение (на себя), после существительного — усиление (сам, лично); '
                         'each other — «друг друга», не themselves.')
    s4['table'] = [
        row(pronoun='возвратное', form='глагол + -self', example='She hurt herself.', translation='Она поранилась.'),
        row(pronoun='усилительное', form='после сущ. или в конце', example='My grandmother herself baked the cake. = My grandmother baked the cake herself.', translation='Бабушка сама испекла торт.'),
        row(pronoun='взаимное', form='each other', example='My parents respect each other.', translation='Мои родители уважают друг друга.'),
        row(pronoun='WRONG', form='themselves ≠ each other', example='❌ They talked to themselves. (= каждый сам с собой)', translation='Правильно: They talked to each other.'),
    ]
    s5 = _dup_section(new, 'Употребление в вопросе')
    s5['subtitle'] = 'Устойчивые выражения'
    s5['description'] = 'Возвратные местоимения входят в частые обороты — их удобно запомнить целиком.'
    s5['table'] = [
        row(pronoun='enjoy yourself', form='хорошо провести время', example='We enjoyed ourselves at the wedding.', translation='Мы отлично провели время на свадьбе.'),
        row(pronoun='help yourself', form='угощайся', example='Help yourselves to the cake.', translation='Угощайтесь тортом.'),
        row(pronoun='by yourself', form='один / сам', example='My niece lives by herself now.', translation='Моя племянница теперь живёт одна.'),
        row(pronoun='take care of yourself', form='береги себя', example='Take care of yourself, Grandma.', translation='Береги себя, бабушка.'),
        row(pronoun='make yourself at home', form='чувствуй себя как дома', example='Come in and make yourself at home.', translation='Заходи и чувствуй себя как дома.'),
        row(pronoun='behave yourself', form='веди себя хорошо', example='Behave yourselves at the in-laws\' house!', translation='Ведите себя хорошо в доме родственников!'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_5

# ======================================================== B1_6 phrasal verbs
T = 'B1_6'
base.EDITS[T] = {}
fix(T, 5, 7, sentence='He looked his little sister after very carefully.', correct_answer='He looked after his little sister very carefully.',
    error_word='looked his little sister after', correct_word='looked after his little sister', alternatives=['looked after his little sister'],
    explanation="'Look after' — inseparable: частицу 'after' нельзя отделять от глагола. Объект ставится после: 'looked after his little sister'.")
THEORY[T] = copy.deepcopy

# ===================================================== B1_7 adverbs of manner
T = 'B1_7'
base.EDITS[T] = {}


def theory_B1_7(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[0]['subtitle'].startswith('Образование наречий'), sections[0]['subtitle']
    sections[0]['table'] += [
        row(pronoun='happy', form='y → ily', example='happily', translation='радостно'),
        row(pronoun='gentle', form='-le → -ly', example='gently', translation='нежно, мягко'),
        row(pronoun='good', form='исключение', example='well', translation='хорошо'),
    ]
    extra = _extra_section(new)
    _swap_examples(extra, {
        'She is a professional athlete.': ('The athlete trains hard every day.', 'Спортсменка усердно тренируется каждый день.'),
        'The competition was very exciting.': ('The competition started badly for our team.', 'Соревнование началось для нашей команды плохо.'),
        'Our team won the championship.': ('Our team won the championship easily.', 'Наша команда легко выиграла чемпионат.'),
        'Their victory was well deserved.': ('They celebrated their victory loudly.', 'Они громко праздновали победу.'),
        'I have training every Monday.': ('We train seriously every Monday.', 'Мы серьёзно тренируемся каждый понедельник.'),
        'Our coach is very experienced.': ('Our coach explains everything clearly.', 'Наш тренер всё объясняет понятно.'),
        'The match starts at 3 p.m.': ('The match started late because of the rain.', 'Матч начался поздно из-за дождя.'),
        'The final score was 2-1.': ('The team fought bravely, but the final score was 2-1.', 'Команда сражалась храбро, но итоговый счёт был 2:1.'),
        'He scored three goals in the match.': ('He scored three goals quickly in the first half.', 'Он быстро забил три гола в первом тайме.'),
        'She won a gold medal.': ('She won a gold medal and smiled happily.', 'Она выиграла золотую медаль и радостно улыбнулась.'),
        'They received a large trophy.': ('They proudly received a large trophy.', 'Они с гордостью получили большой кубок.'),
        'I exercise every morning.': ('I exercise regularly, but I still run slowly.', 'Я регулярно занимаюсь, но всё ещё бегаю медленно.'),
        'Our opponent was very strong.': ('Our opponent played very aggressively.', 'Наш соперник играл очень агрессивно.'),
        'She broke the world record.': ('She ran fast and broke the world record.', 'Она бежала быстро и побила мировой рекорд.'),
        'The stadium was full of fans.': ('The fans in the stadium cheered enthusiastically.', 'Болельщики на стадионе восторженно кричали.'),
        'The victory was a great achievement.': ('He spoke modestly about his achievement.', 'Он скромно говорил о своём достижении.'),
        'Fitness is part of his routine.': ('He follows his fitness routine carefully.', 'Он тщательно следует своему плану тренировок.'),
        'She has natural talent.': ('She hardly ever loses — she has natural talent.', 'Она почти никогда не проигрывает — у неё природный талант.'),
    })
    s4 = _dup_section(new, 'Употребление в утверждении')
    s4['subtitle'] = 'Наречия-исключения'
    s4['description'] = 'Несколько наречий не получают -ly, а у пары слов форма с -ly значит другое.'
    s4['table'] = [
        row(pronoun='fast', form='= fast', example='He runs fast. (не fastly)', translation='Он бегает быстро.'),
        row(pronoun='hard', form='= hard', example='She trains hard.', translation='Она усердно тренируется.'),
        row(pronoun='hardly', form='≠ hard: едва, почти не', example='He hardly ever trains.', translation='Он почти никогда не тренируется.'),
        row(pronoun='late', form='= late', example='The match started late.', translation='Матч начался поздно.'),
        row(pronoun='lately', form='≠ late: в последнее время', example='I have been training a lot lately.', translation='В последнее время я много тренируюсь.'),
        row(pronoun='good → well', form='исключение', example='She plays well.', translation='Она хорошо играет.'),
        row(pronoun='early', form='= early', example='The coach arrived early.', translation='Тренер пришёл рано.'),
    ]
    s5 = _dup_section(new, 'Употребление в вопросе')
    s5['subtitle'] = 'Глаголы-связки и сравнение наречий'
    s5['description'] = ('После look, feel, smell, taste, sound стоит прилагательное (описываем предмет, а не действие); '
                         'сравнительная степень: короткие наречия + -er, наречия на -ly — more … than, well → better.')
    s5['table'] = [
        row(pronoun='look / feel / smell / taste / sound', form='+ прилагательное', example='The coach looked tired. The trophy looks beautiful.', translation='Тренер выглядел уставшим. Кубок выглядит красиво.'),
        row(pronoun='глагол действия', form='+ наречие', example='She looked carefully at the score.', translation='Она внимательно посмотрела на счёт.'),
        row(pronoun='fast / hard / late', form='+ -er', example='He runs faster than his opponent.', translation='Он бегает быстрее соперника.'),
        row(pronoun='наречия на -ly', form='more … than', example='She trains more seriously than last year.', translation='Она тренируется серьёзнее, чем в прошлом году.'),
        row(pronoun='well / badly', form='better / worse', example='Our team played better in the second half.', translation='Во втором тайме наша команда сыграла лучше.'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_7

# ================================================ B1_8 few / little / fewer
T = 'B1_8'
base.EDITS[T] = {}


def theory_B1_8(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = _extra_section(new)
    _swap_examples(extra, {
        "I'm going to the bank today.": ('Few banks are open on Sundays.', 'Мало банков открыто по воскресеньям.'),
        'I opened a new bank account.': ('I have a little money in my new account.', 'На моём новом счёте есть немного денег.'),
        'I bought it on credit.': ('Fewer people buy things on credit now.', 'Сейчас меньше людей покупают вещи в кредит.'),
        'This is a debit card.': ('I have a few debit cards, but I use only one.', 'У меня несколько дебетовых карт, но пользуюсь я одной.'),
        "Don't spend too much money!": ('Try to spend less money on coffee.', 'Постарайся тратить меньше денег на кофе.'),
        'I earn $3,000 a month.': ('He earns less than his colleague.', 'Он зарабатывает меньше своего коллеги.'),
        'We have a limited budget.': ('We have little room in the budget for extras.', 'В бюджете мало места для лишнего.'),
        'I need to take out a loan.': ('Few students take out a loan for a car.', 'Мало студентов берут кредит на машину.'),
        'I have a lot of debt.': ('I have less debt than a year ago.', 'У меня меньше долгов, чем год назад.'),
        'She has small savings.': ('She has little money saved, but a few good investments.', 'У неё мало накопленных денег, но несколько удачных инвестиций.'),
        'Real estate is a long investment.': ('There are fewer safe investments than people think.', 'Надёжных инвестиций меньше, чем думают люди.'),
        'The local currency is the euro.': ('I have a little foreign currency left from the trip.', 'У меня осталось немного иностранной валюты после поездки.'),
        'His salary doubled.': ('A few employees got a higher salary this year.', 'Несколько сотрудников получили в этом году более высокую зарплату.'),
        'Our expenses are higher this year.': ('We had fewer expenses last month.', 'В прошлом месяце у нас было меньше расходов.'),
        'The interest rate went up.': ('Fewer banks offer a low interest rate now.', 'Сейчас меньше банков предлагают низкую процентную ставку.'),
    })
    return new


THEORY[T] = theory_B1_8

# ======================================================== B1_9 question tags
T = 'B1_9'
base.EDITS[T] = {}


def theory_B1_9(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[3]['subtitle'].startswith('Особые случаи'), sections[3]['subtitle']
    sections[3]['table'].append({'case': 'Nobody / Nothing / Never', 'example': 'Nobody called the office, did they?',
                                 'note': 'Отрицательное слово в предложении → положительный тег; nobody → they.',
                                 'translation': 'Никто не звонил в офис, правда?'})
    extra = _extra_section(new)
    _swap_examples(extra, {
        'She has a good job at a bank.': ("She has a good job at a bank, doesn't she?", 'У неё хорошая работа в банке, не так ли?'),
        'He wants to build a career in IT.': ("He wants to build a career in IT, doesn't he?", 'Он хочет построить карьеру в IT, не так ли?'),
        'Our company has 200 employees.': ("Our company has 200 employees, doesn't it?", 'В нашей компании 200 сотрудников, не так ли?'),
        'I go to the office every day.': ("I don't have to go to the office every day, do I?", 'Мне не обязательно ходить в офис каждый день, правда?'),
        'My boss is very kind.': ("Your boss is very kind, isn't she?", 'Твоя начальница очень добрая, не так ли?'),
        'All employees get health insurance.': ("All employees get health insurance, don't they?", 'Все сотрудники получают медицинскую страховку, не так ли?'),
        'My colleagues are very friendly.': ("Your colleagues aren't very friendly, are they?", 'Твои коллеги не очень дружелюбные, правда?'),
        'The salary is $3,000 a month.': ("The salary was $3,000 a month, wasn't it?", 'Зарплата составляла $3000 в месяц, не так ли?'),
        'Teaching is a noble profession.': ("Teaching is a noble profession, isn't it?", 'Преподавание — благородная профессия, не так ли?'),
        'Send your resume to this email.': ("You've sent your resume, haven't you?", 'Ты уже отправил резюме, не так ли?'),
    })
    return new


THEORY[T] = theory_B1_9

# ====================================================== B1_10 relative clauses
T = 'B1_10'
base.EDITS[T] = {}
fix(T, 7, 10, words=['money', 'lent', 'who', 'person', 'I', 'disappeared', 'The', '.', 'to'],
    correct_answer='The person who I lent money to disappeared.',
    explanation='Who для людей: The person who I lent money to = человек, которому я одолжил деньги (предлог to остаётся в конце придаточного). Перевод: Человек, которому я одолжил деньги, исчез.')


def theory_B1_10(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[0]['subtitle'].endswith('Относительные местоимения'), sections[0]['subtitle']
    sections[0]['table'] += [
        {'pronoun': 'whose', 'use': 'принадлежность (чей)', 'example': 'The tenant whose flat is upstairs is a doctor.', 'translation': 'Арендатор, чья квартира наверху, — врач.'},
        {'pronoun': 'when', 'use': 'для времени', 'example': 'I remember the year when we moved to the suburbs.', 'translation': 'Я помню год, когда мы переехали в пригород.'},
        {'pronoun': 'why', 'use': 'после reason', 'example': 'The reason why we rent is the high price of flats.', 'translation': 'Причина, по которой мы снимаем жильё, — высокие цены на квартиры.'},
    ]
    extra = _extra_section(new)
    _swap_examples(extra, {
        'Urban life is very busy.': ('People who choose urban life are always busy.', 'Люди, которые выбирают городскую жизнь, всегда заняты.'),
        'I prefer rural areas to cities.': ('I prefer rural areas where the air is clean.', 'Я предпочитаю сельские районы, где чистый воздух.'),
        'We rent a small apartment.': ('The apartment that we rent is small but cosy.', 'Квартира, которую мы снимаем, маленькая, но уютная.'),
        'They bought a flat in London.': ('The flat which they bought in London has two bedrooms.', 'Квартира, которую они купили в Лондоне, с двумя спальнями.'),
        'We have a cottage by the lake.': ('The cottage where we spend our summers is by the lake.', 'Коттедж, где мы проводим лето, стоит у озера.'),
        'My grandparents live in a bungalow.': ('A bungalow is a house that has only one floor.', 'Бунгало — это дом, у которого только один этаж.'),
        'The rich businessman owns a huge mansion.': ('The businessman who owns that mansion is rarely at home.', 'Бизнесмен, который владеет этим особняком, редко бывает дома.'),
        'How much do you pay to rent this apartment?': ('The rent that we pay for this apartment is too high.', 'Арендная плата, которую мы платим за эту квартиру, слишком высокая.'),
        'Do you own or rent your home?': ('People who own their home pay no rent.', 'Люди, которые владеют своим домом, не платят аренду.'),
        'Our landlord is very friendly.': ('A landlord is a person who rents out property.', 'Арендодатель — это человек, который сдаёт недвижимость.'),
        'The tenants must pay rent on time.': ('Tenants who pay rent late may lose the flat.', 'Арендаторы, которые платят аренду с опозданием, могут потерять квартиру.'),
        'This is a safe neighborhood.': ('This is the neighborhood where I grew up.', 'Это район, где я вырос.'),
        'Many families live in the suburbs.': ('Families who live in the suburbs often need a car.', 'Семьям, которые живут в пригороде, часто нужна машина.'),
        'I work downtown.': ('The office where I work is downtown.', 'Офис, где я работаю, в центре города.'),
        'This is a residential area.': ('A residential area is a district where people live, not work.', 'Жилой район — это район, где люди живут, а не работают.'),
        'We moved to a quiet neighbourhood.': ('The neighbourhood we moved to is quiet.', 'Район, в который мы переехали, тихий.'),
    })
    return new


THEORY[T] = theory_B1_10

# ================================================== B1_12 passive (present)
T = 'B1_12'
base.EDITS[T] = {}


def theory_B1_12(content: dict) -> dict:
    new = copy.deepcopy(content)
    # Section 1 listed four use cases as «1. … 2. … 3. …» inside the description, with an empty
    # table underneath: everything ran together in one paragraph (review of item 26).
    use = new['sections'][1]
    assert use['subtitle'].startswith('Когда использовать') and not use.get('table'), use['subtitle']
    use['description'] = 'Страдательный залог выбирают, когда важно действие, а не тот, кто его совершает.'
    use['table'] = [
        {'situation': 'Действующее лицо неизвестно или неважно', 'example': 'Messages are sent every day.',
         'translation': 'Сообщения отправляются каждый день.'},
        {'situation': 'Акцент на действии, а не на исполнителе', 'example': 'New videos are uploaded weekly.',
         'translation': 'Новые видео загружаются еженедельно.'},
        {'situation': 'Формальная речь и письмо', 'example': 'Passwords are changed regularly.',
         'translation': 'Пароли меняются регулярно.'},
        {'situation': 'Научные и технические тексты', 'example': 'Data is stored in the cloud.',
         'translation': 'Данные хранятся в облаке.'},
    ]
    extra = _extra_section(new)
    _swap_examples(extra, {
        'I use the internet every day.': ('The internet is used by billions of people every day.', 'Интернетом пользуются миллиарды людей каждый день.'),
        'This website is very useful.': ('This website is updated every week.', 'Этот сайт обновляется каждую неделю.'),
        'She writes a blog about fashion.': ('Her blog about fashion is read all over the world.', 'Её блог о моде читают по всему миру.'),
        'Social media connects people around the world.': ('Social media is checked by most people every morning.', 'Большинство людей проверяют соцсети каждое утро.'),
        'I post photos on Instagram.': ('New photos are posted on my profile every day.', 'Новые фотографии публикуются в моём профиле каждый день.'),
        'She shares interesting articles with friends.': ('Interesting articles are shared with friends in one click.', 'Интересными статьями делятся с друзьями в один клик.'),
        'People leave comments under my videos.': ('Rude comments are deleted by the moderators.', 'Грубые комментарии удаляются модераторами.'),
    })
    extra['table'] += [row(example=en, translation=ru) for en, ru in [
        ('Is this hashtag used a lot?', 'Этот хэштег часто используют?'),
        ('Your password is not shown to anyone.', 'Ваш пароль никому не показывается.'),
        ('Viral videos are watched millions of times.', 'Вирусные видео просматривают миллионы раз.'),
    ]]
    return new


THEORY[T] = theory_B1_12

# ================================================== B1_11 -ed / -ing adjectives
T = 'B1_11'
base.EDITS[T] = {}
# All 16 fill_blanks asked the learner to guess a lexeme («The documentary was absolutely ___»),
# and the subjective synonym lists papered over it — «an ___ speech» even accepted «moving» and
# «powerful», producing «an moving speech» (review of item 26). The topic is the -ed/-ing
# contrast, so the base verb is given and the item drills the form, not the vocabulary.
_ED_ING_HINTS = {
    (1, 1): ('fascinate', 'fascinating'), (1, 2): ('exhaust', 'exhausted'), (1, 3): ('amaze', 'amazed'),
    (2, 1): ('annoy', 'annoyed'), (2, 2): ('confuse', 'confusing'), (2, 3): ('embarrass', 'embarrassed'),
    (3, 1): ('fascinate', 'fascinating'), (3, 2): ('confuse', 'confused'), (3, 3): ('annoy', 'annoying'),
    (4, 1): ('annoy', 'annoying'), (4, 2): ('disappoint', 'disappointed'),
    (5, 1): ('fascinate', 'fascinating'), (5, 2): ('shock', 'shocked'),
    (6, 1): ('confuse', 'confusing'), (7, 1): ('inspire', 'inspiring'), (8, 1): ('annoy', 'annoying'),
}
for (_s, _o), (_base, _ans) in _ED_ING_HINTS.items():
    _ex = _exercise(T, _s, _o)
    _q = _ex['content']['question']
    assert _ex['exercise_type'] == 'fill_blank' and _q.count('___') == 1 and '(' not in _q, (_s, _o, _q)
    _who = 'испытывает чувство' if _ans.endswith('ed') else 'вызывает чувство'
    fix(T, _s, _o, question=_q.replace('___', f'___ ({_base})', 1), correct_answer=_ans, alternatives=[],
        explanation=f'Подлежащее {_who}, поэтому нужна форма на -{"ed" if _ans.endswith("ed") else "ing"}: {_base} → {_ans}. '
                    f'Правило: люди чувствуют (-ed), а предметы, события и ситуации вызывают чувство (-ing).')


def theory_B1_11(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    mistakes = sections[3]
    assert mistakes['subtitle'] == 'Типичные ошибки' and 'examples' in mistakes and 'table' not in mistakes, mistakes.keys()
    # A section-level ``examples`` list is rendered by no template — turn it into table rows.
    mistakes['table'] = [{'wrong': e['wrong'], 'correct': e['correct'], 'explanation': e['explanation']} for e in mistakes.pop('examples')]
    extra = _extra_section(new)
    _swap_examples(extra, {
        'This cake is absolutely delicious!': ('This cake is amazing — I was amazed by the taste!', 'Этот торт изумительный — я был изумлён вкусом!'),
        'The pizza was really tasty.': ('The pizza was disappointing, and we were disappointed with the service too.', 'Пицца разочаровала, и обслуживанием мы тоже были разочарованы.'),
        'I love spicy food like curry.': ('Spicy food is exciting for me — I am excited to try a new curry.', 'Острая еда для меня — это восторг: я в предвкушении нового карри.'),
        'These cookies are too sweet for me.': ('I was surprised how sweet these cookies were — a surprising recipe.', 'Я был удивлён, насколько сладкими оказались эти печенья, — удивительный рецепт.'),
        'Lemons taste sour.': ('The sour lemon dessert was refreshing.', 'Кислый лимонный десерт освежал.'),
        'Black coffee tastes bitter without sugar.': ('I am not interested in bitter coffee — the menu here is more interesting.', 'Горький кофе меня не интересует — меню здесь интереснее.'),
        'The soup is too salty.': ('The salty soup was frustrating, and the chef was frustrated too.', 'Пересоленный суп раздражал, и шеф-повар тоже был расстроен.'),
        'We use only fresh vegetables.': ('It is relaxing to cook with fresh vegetables; I feel relaxed in the kitchen.', 'Готовить из свежих овощей расслабляет; на кухне я чувствую себя спокойно.'),
        "This bread is stale. Don't eat it.": ('The stale bread was a shocking discovery — the guests were shocked.', 'Чёрствый хлеб стал шокирующим открытием — гости были в шоке.'),
        'My favorite dish is pasta carbonara.': ('Pasta carbonara is a satisfying dish; I always feel satisfied after it.', 'Паста карбонара — сытное блюдо; после неё я всегда доволен.'),
        'I like trying different cuisines.': ('Trying different cuisines is fascinating — I am fascinated by Thai food.', 'Пробовать разные кухни увлекательно — я в восторге от тайской еды.'),
    })
    return new


THEORY[T] = theory_B1_11

# ======================================================== B1_13 purpose clauses
T = 'B1_13'
base.EDITS[T] = {}


def theory_B1_13(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[1]['subtitle'].startswith('2. In order to'), sections[1]['subtitle']
    sections[1]['table'].append({'example': 'She saved money so as to buy a new tablet.', 'translation': 'Она копила деньги, чтобы купить новый планшет.',
                                 'note': 'so as to = in order to (тоже формально)'})
    assert sections[4]['subtitle'].startswith('Дополнительные примеры'), sections[4]['subtitle']
    sections.insert(4, {
        'subtitle': 'For + существительное / -ing (предназначение)',
        'description': 'Назначение предмета или цель-существительное выражаются через for: for + существительное или for + герундий. '
                       'Инфинитив после for не ставится — «for to charge» ошибка.',
        'table': [
            {'example': 'I need a cable for my laptop.', 'translation': 'Мне нужен кабель для ноутбука.', 'note': 'for + существительное'},
            {'example': 'This app is used for learning languages.', 'translation': 'Это приложение используется для изучения языков.', 'note': 'for + -ing'},
            {'example': '❌ I bought a tablet for to read. → ✅ I bought a tablet to read. / for reading.', 'translation': 'Я купил планшет, чтобы читать.', 'note': 'не for to'},
        ],
    })
    _swap_examples(sections[5], {
        'She bought a new laptop for work.': ('She bought a new laptop in order to work from anywhere.', 'Она купила новый ноутбук, чтобы работать откуда угодно.'),
        'The tablet is perfect for reading.': ('The tablet is perfect for reading in bed.', 'Планшет идеален для чтения в постели.'),
        'The keyboard is wireless.': ('I bought a wireless keyboard so that I could type faster.', 'Я купил беспроводную клавиатуру, чтобы печатать быстрее.'),
        'I need a new mouse for my computer.': ('I need a new mouse for my computer so as not to strain my wrist.', 'Мне нужна новая мышь для компьютера, чтобы не перегружать запястье.'),
        'The screen is too bright.': ('Lower the screen brightness in order to save battery life.', 'Уменьшите яркость экрана, чтобы сберечь заряд батареи.'),
        'We need to update the software.': ('We update the software regularly so that the laptop stays secure.', 'Мы регулярно обновляем ПО, чтобы ноутбук оставался защищённым.'),
        'The hardware is outdated.': ('They replaced the old hardware in order to run new programs.', 'Они заменили старое оборудование, чтобы запускать новые программы.'),
        'I need to download the file.': ('I connected to Wi-Fi to download the file faster.', 'Я подключился к Wi-Fi, чтобы скачать файл быстрее.'),
        'Please upload your photos to the cloud.': ('Upload your photos to the cloud so that you never lose them.', 'Загрузите фотографии в облако, чтобы никогда их не потерять.'),
        'The internet connection is slow.': ('He restarted the router in order to fix the slow internet connection.', 'Он перезагрузил роутер, чтобы починить медленное соединение.'),
        'Do you have Wi-Fi here?': ('Do you have Wi-Fi here so that I can check my email?', 'У вас здесь есть Wi-Fi, чтобы я мог проверить почту?'),
        'Do not forget your password.': ('Write down your password so as not to forget it.', 'Запишите пароль, чтобы не забыть его.'),
        'Install the latest update.': ('Install the latest update to protect your data.', 'Установите последнее обновление, чтобы защитить свои данные.'),
        'The battery is almost dead.': ('Turn off Bluetooth so that the battery lasts longer.', 'Выключите Bluetooth, чтобы батарея работала дольше.'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_13

# ========================================== B1_14 Present Perfect ever / never
T = 'B1_14'
base.EDITS[T] = {}
# «It is the best vacation I ___ ever had» accepted «have ever» → «have ever ever had» (review of item 26).
fix(T, 7, 1, alternatives=[],
    explanation='Конструкция «the best … I have ever had» — Present Perfect после превосходной степени. '
                'Слово ever уже стоит в предложении, поэтому в пропуск идёт только have.')
replace(T, 3, 2, 'fill_blank', question='They have not returned from their vacation ___.', correct_answer='yet', alternatives=[],
        explanation='Yet (ещё) ставится в конец отрицательного предложения: have not + V3 + yet = ещё не. Перевод: Они ещё не вернулись из отпуска.')
replace(T, 7, 8, 'error_correction', sentence='I have never see the Northern Lights on my travels.', correct_answer='I have never seen the Northern Lights on my travels.',
        error_word='see', correct_word='seen', alternatives=['seen'],
        explanation='Ошибка: после have/has в Present Perfect нужен V3 (seen), а не инфинитив (see). See → saw → seen. «Have never seen» = никогда не видел.')


def theory_B1_14(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[3]['subtitle'].startswith('Краткие ответы'), sections[3]['subtitle']
    sections.insert(4, {
        'subtitle': 'Already, just, yet и been / gone',
        'description': 'Already (уже) и just (только что) стоят между have/has и V3; yet (ещё / уже) — в конце отрицания или вопроса. '
                       'Been to — побывал и вернулся, gone to — уехал и ещё там.',
        'table': [
            row(pronoun='already', form='have + already + V3', example='We have already packed our luggage.', translation='Мы уже собрали багаж.'),
            row(pronoun='just', form='have + just + V3', example='She has just collected her baggage.', translation='Она только что забрала багаж.'),
            row(pronoun='yet', form='в конце отрицания / вопроса', example="They haven't checked in yet. Have you booked a hotel yet?", translation='Они ещё не зарегистрировались. Ты уже забронировал отель?'),
            row(pronoun='been to', form='побывал и вернулся', example='I have been to Japan twice.', translation='Я дважды бывал в Японии (и вернулся).'),
            row(pronoun='gone to', form='уехал и ещё не вернулся', example='He has gone to Japan — he is not back yet.', translation='Он уехал в Японию и ещё не вернулся.'),
            row(pronoun='WRONG', form='Present Perfect + yesterday / last year', example='❌ I have been to Rome last year. → ✅ I went to Rome last year.',
                translation='С точным временем в прошлом — Past Simple.'),
        ],
    })
    _swap_examples(sections[5], {
        'Tourism is an important industry in this country.': ('Tourism has become an important industry in this country.', 'Туризм стал важной отраслью в этой стране.'),
        'The journey took five hours.': ('This is the longest journey I have ever taken.', 'Это самое долгое путешествие, которое я когда-либо совершал.'),
        'They went on a long voyage across the ocean.': ('They have never been on a voyage across the ocean.', 'Они никогда не совершали плавание через океан.'),
        'Where are you going on vacation?': ('Have you ever spent a vacation abroad?', 'Ты когда-нибудь проводил отпуск за границей?'),
        'Do I need a visa to visit this country?': ('I have never needed a visa for this country.', 'Мне никогда не требовалась виза для этой страны.'),
        'How much luggage can I take?': ('Have you ever lost your luggage?', 'Ты когда-нибудь терял багаж?'),
        'Please collect your baggage at carousel 3.': ('We have already collected our baggage.', 'Мы уже забрали багаж.'),
        'Please show your boarding pass at the gate.': ('She has just shown her boarding pass at the gate.', 'Она только что показала посадочный талон у выхода.'),
        'We passed through customs quickly.': ('Have you passed through customs yet?', 'Ты уже прошёл таможню?'),
        'The accommodation includes breakfast.': ("I haven't booked the accommodation yet.", 'Я ещё не забронировал жильё.'),
        'Our trip lasted two weeks.': ('It is the best trip we have ever had.', 'Это лучшая поездка, которая у нас когда-либо была.'),
        'Bali is a popular destination.': ('Bali has become a popular destination.', 'Бали стал популярным направлением.'),
        'We went sightseeing all day.': ('Have you ever gone sightseeing at night?', 'Ты когда-нибудь ходил осматривать достопримечательности ночью?'),
        'Check your passport expiry.': ('Have you checked your passport expiry yet?', 'Ты уже проверил срок действия паспорта?'),
        'Exchange currency at the airport.': ('I have never exchanged currency at the airport — it is too expensive.', 'Я никогда не менял валюту в аэропорту — это слишком дорого.'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_14

# =========================================== B1_15 Present Perfect for / since
T = 'B1_15'
base.EDITS[T] = {}


def theory_B1_15(content: dict) -> dict:
    new = copy.deepcopy(content)
    extra = _extra_section(new)
    _swap_examples(extra, {
        'She is very interested in fashion.': ('She has been interested in fashion since she was a teenager.', 'Она интересуется модой с подросткового возраста.'),
        'I like your style of dressing.': ('I have liked your style since we first met.', 'Мне нравится твой стиль с нашей первой встречи.'),
        'This is a beautiful outfit!': ('I have had this outfit for two years.', 'Этот наряд у меня уже два года.'),
        'These shoes are very trendy this season.': ('These shoes have been trendy since last season.', 'Эти туфли в моде с прошлого сезона.'),
        'I prefer casual clothes for everyday wear.': ('I have preferred casual clothes for years.', 'Я предпочитаю повседневную одежду уже много лет.'),
        'You need to wear formal clothes to the interview.': ('He has worn formal clothes every day since he got the job.', 'Он носит официальную одежду каждый день с тех пор, как получил работу.'),
        'She looked elegant in her black dress.': ('She has looked elegant since she changed her style.', 'Она выглядит элегантно с тех пор, как сменила стиль.'),
        'She loves buying accessories like bags and scarves.': ('She has collected accessories for ten years.', 'Она собирает аксессуары уже десять лет.'),
        'This is a famous Italian brand.': ('This Italian brand has been famous since the 1970s.', 'Этот итальянский бренд знаменит с 1970-х.'),
        'She wants to become a fashion designer.': ('She has wanted to become a fashion designer since childhood.', 'Она хочет стать модельером с детства.'),
        'I like the floral pattern on this dress.': ('Floral patterns have been popular for several seasons.', 'Цветочные узоры популярны уже несколько сезонов.'),
        'This fabric is very soft and comfortable.': ('This fabric has been in fashion for decades.', 'Эта ткань в моде уже десятилетия.'),
        'These jeans fit me perfectly.': ('These jeans have fitted me perfectly since I bought them.', 'Эти джинсы идеально сидят на мне с момента покупки.'),
        'He always looks very stylish.': ('He has looked very stylish since he hired a stylist.', 'Он выглядит очень стильно с тех пор, как нанял стилиста.'),
        'Long coats are fashionable this winter.': ('Long coats have been fashionable since autumn.', 'Длинные пальто в моде с осени.'),
        'She collects vintage clothing from the 1950s.': ('She has collected vintage clothing for a long time.', 'Она давно собирает винтажную одежду.'),
        'The designer presented a new collection.': ('The designer has presented a new collection every year since 2015.', 'Дизайнер представляет новую коллекцию каждый год с 2015-го.'),
        'What are the latest fashion trends?': ('How long have you followed fashion trends?', 'Как долго ты следишь за модными трендами?'),
        "There's a nice boutique on Main Street.": ('The boutique on Main Street has been open for a month.', 'Бутик на Главной улице открыт уже месяц.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Вопрос How long, отрицание и типичные ошибки'
    dup['description'] = 'Длительность спрашивают через How long + Present Perfect; отрицание — have/has + not + V3; since не сочетается с периодом, а for — с моментом.'
    dup['table'] = [
        row(pronoun='How long …?', form='have/has + V3', example='How long have you worked in fashion?', translation='Как долго ты работаешь в моде?'),
        row(pronoun='отрицание', form="haven't / hasn't + V3", example="I haven't bought new clothes for six months.", translation='Я не покупал новую одежду уже полгода.'),
        row(pronoun='since + придаточное', form='since + Past Simple', example='She has been a stylist since she graduated.', translation='Она стилист с тех пор, как окончила учёбу.'),
        row(pronoun='WRONG', form='since + период / for + момент', example='❌ since three years, ❌ for last year → ✅ for three years, ✅ since last year',
            translation='since — точка, for — период'),
        row(pronoun='WRONG', form='Present Simple + for/since', example='❌ I live here for five years. → ✅ I have lived here for five years.',
            translation='Я живу здесь пять лет.'),
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_15

# ======================================================== B1_16 conditionals
T = 'B1_16'
base.EDITS[T] = {}
# The eight Zero-Conditional items accepted «will …» as an alternative while their own explanation
# said the answer must be Present Simple. Dropping the alternative alone would create false
# rejections: «If you don't book early, the tickets will sell out» is perfectly good English about
# one occasion — and, as the second review round pointed out, «always» and «usually» do NOT rule
# «will» out either (Cambridge lists will for general truths and habitual events; «gradually» is
# about slowness, not regularity). So the exercise states its own requirement before the sentence,
# and the single accepted answer follows from that instruction rather than from an invented ban.
_ZERO_TASK = 'Zero Conditional (обе части в Present Simple): '
_ZERO_ITEMS = {
    (1, 1): ('melts', 'will melt'), (2, 1): ('die', 'will die'), (3, 1): ('feel', 'will feel'),
    (4, 1): ('sell', 'will sell'), (5, 1): ('burn', 'will burn'), (6, 1): ('work', 'will work'),
    (7, 1): ('loses', 'will lose'), (8, 1): ('risk', 'will risk'),
}
for (_s, _o), (_ans, _first) in _ZERO_ITEMS.items():
    _q = _exercise(T, _s, _o)['content']['question']
    assert not _q.startswith('Zero'), (_s, _o)
    fix(T, _s, _o, question=_ZERO_TASK + _q, alternatives=[],
        explanation=f'Задание требует Zero Conditional, поэтому обе части стоят в Present Simple → «{_ans}». '
                    f'Вариант «{_first}» возможен в английском, но не соответствует требуемой в этом задании форме.')
fix(T, 1, 8, alternatives=['If you heat water to one hundred degrees, it boils.', 'When you heat water to 100 degrees, it boils.'],
    explanation='Русское предложение стоит в настоящем времени и описывает физический закон, поэтому Zero Conditional: '
                'If + Present Simple, Present Simple («it boils»).')
# «If I was you» is informal but real English; the item teaches «were», so it stays the key while
# «was» remains an accepted answer (review of item 26).
fix(T, 1, 3, alternatives=['was'],
    explanation='Second Conditional: в гипотетике «be» принимает форму were для всех лиц — If I were you… Разговорное '
                '«If I was you» тоже встречается, но в учебной и письменной норме используется were.')


def theory_B1_16(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[3]['subtitle'].startswith('Сравнение типов'), sections[3]['subtitle']
    sections[3]['table'].append({'type': 'Пунктуация', 'example': 'If it rains, we will stay. / We will stay if it rains.',
                                 'meaning': 'if-часть в начале — запятая; if-часть в конце — без запятой'})
    sections.append({
        'subtitle': 'Дополнительные примеры со словарём модуля',
        'description': 'Примеры использования лексики модуля в контексте грамматики.',
        'table': [{'example': en, 'translation': ru} for en, ru in [
            ('If you have a choice, take the safer option.', 'Если у тебя есть выбор, бери более безопасный вариант.'),
            ('If we take this risk, the reward will be bigger.', 'Если мы пойдём на этот риск, награда будет больше.'),
            ('If the plan fails, we will need another solution.', 'Если план провалится, нам понадобится другое решение.'),
            ('Every decision has a consequence.', 'У каждого решения есть последствие.'),
            ('If I were you, I would not miss this opportunity.', 'На твоём месте я не упустил бы эту возможность.'),
            ('Unless we agree today, we will lose the contract.', 'Если мы не договоримся сегодня, мы потеряем контракт.'),
            ('If they disagree, we will discuss it again.', 'Если они не согласятся, мы обсудим это ещё раз.'),
            ('I will keep my promise, provided that you keep yours.', 'Я сдержу своё обещание при условии, что ты сдержишь своё.'),
            ('Imagine you had no internet for a week — what would you do?', 'Представь, что у тебя неделю нет интернета: что бы ты делал?'),
            ('Suppose the possibility is real; what is our plan?', 'Допустим, эта возможность реальна: каков наш план?'),
            ('If you hope for a result, you have to act.', 'Если надеешься на результат, нужно действовать.'),
            ('As long as the condition is clear, we can sign.', 'Пока условие понятно, мы можем подписывать.'),
        ]],
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_16

# ======================================================== B1_17 Past Perfect
T = 'B1_17'
base.EDITS[T] = {}


def theory_B1_17(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[4]['subtitle'].startswith('Третьи формы'), sections[4]['subtitle']
    sections[4]['table'] += [{'v1': v1, 'v3': v3} for v1, v3 in [
        ('come', 'come'), ('drive', 'driven'), ('break', 'broken'), ('forget', 'forgotten'),
        ('fall', 'fallen'), ('lose', 'lost'), ('begin', 'begun'), ('hide', 'hidden'),
        ('read', 'read'), ('leave', 'left'),
    ]]
    sections.insert(5, {
        'subtitle': 'Отрицание, вопрос и сокращения',
        'description': "Отрицание — had not (hadn't) + V3; вопрос — Had + подлежащее + V3; в речи had сокращается до 'd. "
                       "С never отрицание не удваивается: had never seen, а не hadn't never seen.",
        'table': [
            {'subject': 'Отрицание', 'form': "hadn't + V3", 'example': "We hadn't booked a table, so we waited."},
            {'subject': 'Вопрос', 'form': 'Had + S + V3?', 'example': 'Had you finished the report before the meeting?'},
            {'subject': 'Короткий ответ', 'form': "Yes, I had. / No, I hadn't.", 'example': 'Had she left? — Yes, she had.'},
            {'subject': 'Сокращение', 'form': "I'd = I had", 'example': "I'd already seen the film, so we chose another one."},
            {'subject': 'С never', 'form': 'had never + V3', 'example': "❌ hadn't never been → ✅ had never been"},
        ],
    })
    sections.append({
        'subtitle': 'Дополнительные примеры со словарём модуля',
        'description': 'Примеры использования лексики модуля в контексте грамматики.',
        'table': [{'example': en, 'translation': ru} for en, ru in [
            ('When I arrived, they had already left.', 'Когда я приехал, они уже ушли.'),
            ('She had just finished her coffee when the phone rang.', 'Она только что допила кофе, когда зазвонил телефон.'),
            ("We hadn't paid the bill yet when the waiter came back.", 'Мы ещё не оплатили счёт, когда официант вернулся.'),
            ('By the time the film started, we had found our seats.', 'К началу фильма мы уже нашли свои места.'),
            ('Before he moved abroad, he had never flown alone.', 'До переезда за границу он никогда не летал один.'),
            ('After she had sent the email, she noticed the mistake.', 'После того как она отправила письмо, она заметила ошибку.'),
            ('By then, the shop had closed for the night.', 'К тому времени магазин уже закрылся на ночь.'),
            ('Until then, I had not realised how late it was.', 'До того момента я не осознавал, насколько поздно.'),
            ('He remembered that he had met her previously.', 'Он вспомнил, что встречал её раньше.'),
            ('I did not notice what had happened earlier.', 'Я не заметил, что произошло раньше.'),
            ('Had you ever tried Thai food before that trip?', 'Ты пробовал тайскую еду до той поездки?'),
            ('They had prepared everything beforehand, so the party went well.', 'Они всё подготовили заранее, поэтому вечеринка прошла хорошо.'),
        ]],
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_17

# =============================================== B1_18 modals of obligation
T = 'B1_18'
base.EDITS[T] = {}
fix(T, 5, 9, words=['.', 'buy', "doesn't", 'have', 'She', 'to', 'ticket', 'a'], correct_answer="She doesn't have to buy a ticket.",
    explanation="'Doesn't have to' = «не обязательно». Конструкция сохраняет 'to': 'have to buy'. Для 'she' используется 'doesn't'.")


def theory_B1_18(content: dict) -> dict:
    new = copy.deepcopy(content)
    new['sections'].append({
        'subtitle': 'Дополнительные примеры со словарём модуля',
        'description': 'Примеры использования лексики модуля в контексте грамматики.',
        'table': [{'example': en, 'translation': ru} for en, ru in [
            ('You should describe all your symptoms to the doctor.', 'Тебе следует описать врачу все симптомы.'),
            ("If you have a fever, you mustn't go to work.", 'Если у тебя температура, на работу ходить нельзя.'),
            ('You ought to see a doctor about that cough.', 'Тебе стоит показать этот кашель врачу.'),
            ("You don't have to take a painkiller if the headache is mild.", 'Если голова болит слабо, обезболивающее принимать не обязательно.'),
            ('You should gargle if you have a sore throat.', 'При боли в горле следует полоскать горло.'),
            ("If you feel dizzy, you mustn't drive.", 'Если кружится голова, за руль садиться нельзя.'),
            ('You have to show your prescription at the pharmacy.', 'В аптеке нужно показать рецепт.'),
            ('You must finish the whole course of antibiotics.', 'Курс антибиотиков нужно пройти полностью.'),
            ("You'd better make an appointment with a specialist.", 'Лучше запишись на приём к специалисту.'),
            ('The treatment has to start as soon as possible.', 'Лечение нужно начать как можно скорее.'),
            ("You don't have to stay in bed once you recover.", 'Когда поправишься, лежать в постели уже не обязательно.'),
            ('People with high blood pressure should check it every day.', 'Людям с высоким давлением следует измерять его каждый день.'),
            ("If you have an allergy, you mustn't eat this.", 'Если у тебя аллергия, это есть нельзя.'),
        ]],
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_18

# ============================================================= B1_19 idioms
T = 'B1_19'
base.EDITS[T] = {}
replace(T, 3, 1, 'fill_blank', question="I won't be at the meeting; I'm feeling a bit under the ___ today.", correct_answer='weather', alternatives=[],
        explanation="Идиома 'under the weather' = «плохо себя чувствовать». Слово 'weather' зафиксировано и не заменяется синонимами.")
replace(T, 4, 8, 'error_correction', sentence='The meeting ended late, so the manager said we should call it the day.',
        correct_answer='The meeting ended late, so the manager said we should call it a day.',
        error_word='the day', correct_word='a day', alternatives=['a day'],
        explanation="Идиома фиксированная: 'call it a day' (с артиклем 'a'), а не 'call it the day'. В идиоме нельзя менять даже артикль.")


def theory_B1_19(content: dict) -> dict:
    new = copy.deepcopy(content)
    reg = new['sections'][3]
    assert reg['subtitle'].startswith('Регистр'), reg['subtitle']
    reg['table'] += [
        {'idiom': 'a piece of cake', 'register': 'informal', 'use_where': 'разговор, неформальный текст'},
        {'idiom': 'call it a day', 'register': 'neutral', 'use_where': 'работа, разговор'},
        {'idiom': 'the ball is in your court', 'register': 'neutral', 'use_where': 'переговоры, деловая переписка'},
        {'idiom': 'cost an arm and a leg', 'register': 'informal', 'use_where': 'разговор о ценах'},
        {'idiom': 'hit the books', 'register': 'informal', 'use_where': 'учёба, разговор студентов'},
    ]
    new['sections'].append({
        'subtitle': 'Дополнительные примеры со словарём модуля',
        'description': 'Примеры использования лексики модуля в контексте грамматики.',
        'table': [{'example': en, 'translation': ru} for en, ru in [
            ('The test was a piece of cake.', 'Тест был проще простого.'),
            ('He told a joke to break the ice.', 'Он пошутил, чтобы разрядить обстановку.'),
            ('I have to hit the books tonight.', 'Сегодня вечером мне нужно засесть за учебники.'),
            ('That laptop cost an arm and a leg.', 'Этот ноутбук стоил целое состояние.'),
            ('We meet once in a blue moon.', 'Мы видимся очень редко.'),
            ("I'm under the weather today.", 'Сегодня мне нездоровится.'),
            ("It's raining cats and dogs outside.", 'На улице льёт как из ведра.'),
            ("Let's make sure we are on the same page.", 'Давайте убедимся, что мы понимаем всё одинаково.'),
            ("Don't spill the beans before the party.", 'Не выдавай секрет до вечеринки.'),
            ('He let the cat out of the bag by accident.', 'Он случайно проговорился.'),
            ('Break a leg at the concert tonight!', 'Удачи на сегодняшнем концерте!'),
            ("It's late — let's call it a day.", 'Уже поздно, давай закончим на сегодня.'),
            ('I have sent my answer, so the ball is in your court.', 'Я отправил ответ, теперь решение за тобой.'),
            ('She slept like a log after the flight.', 'После перелёта она спала без задних ног.'),
            ('We caught the train by the skin of our teeth.', 'Мы едва успели на поезд.'),
        ]],
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B1_19


# grammar_topics.content mirrors the grammar lesson of the module, but on the prod copy the
# b1-11 mirror lags behind the lesson: it still carries the older translation of the first
# -ed/-ing row. The item-26 patch is keyed on the lesson's content, so that one cell is aligned
# first — and ONLY that cell (`jsonb_set` on its exact path, keyed on the stale value). Rewriting
# the whole theory blob here would silently swallow any independent editorial fix made in prod
# and then let the preflight validate the state this file itself produced (review of item 26);
# with a surgical write, an unrelated prod edit still makes the preflight fail loudly.
# The rollback file leaves the alignment in place — a mirror equal to its lesson is never wrong.
#
# NB (trap found replaying item 25): the pre-step must be emitted BEFORE every other statement.
# Item 25 inserted it at the first blank line, which landed after some of its own theory
# updates, so its check file had to run first. Here it is anchored to the end of the header.
DRIFT_PROBES = {
    'B1_11': ('{sections,2,table,0,ed_translation}', 'Мне скучно с этим меню.', 'Мне надоело это меню.'),
}
_HEAD_END = {
    '1_check': '-- the DO block at the end raises the list of mismatching slots.\n',
    '2_apply': '-- inside the transaction — if any slot or theory mirror is off, so nothing partial commits.\n',
}


def drift_alignment_sql() -> str:
    lines = ['-- Item 26 pre-step: align ONE stale cell of the grammar_topics mirror with the lesson',
             '-- (in 1_check this is the ONLY statement that writes; everything below it only counts rows).',
             '-- (expected: 1 row on a copy that still carries the stale value, 0 rows once aligned).',
             '-- Only this cell is touched: an unrelated prod edit elsewhere in the theory must still',
             '-- make the preflight fail rather than be overwritten here.']
    for topic, (path, stale, fresh) in DRIFT_PROBES.items():
        probe = f"content #>> '{path}'"
        lines.append(f"UPDATE grammar_topics SET content = jsonb_set(content, '{path}', to_jsonb($q${fresh}$q$::text))\n"
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
    base.ASSERT_LABEL = 'item26'
    base.SQL_TITLE = 'Lesson audit item 26: grammar content of the whole B1 level (19 topics). Apply AFTER items 21-25.'
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
    sql = base.emit_sql(all_changes, theory)
    pre = drift_alignment_sql()
    for suffix, head_end in _HEAD_END.items():
        assert sql[suffix].count(head_end) == 1, suffix
        sql[suffix] = sql[suffix].replace(head_end, head_end + pre, 1)
    for suffix, text in sql.items():
        path = base.EXPORT_DIR / f'{SQL_PREFIX}_{suffix}.sql'
        path.write_text(text, encoding='utf-8')
        print('wrote', path.relative_to(ROOT), f'({len(text) // 1024} KiB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
