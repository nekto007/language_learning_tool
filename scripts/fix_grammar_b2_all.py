#!/usr/bin/env python3
"""Lesson audit item 27 — deep pass over the whole B2 grammar level (14 topics).

Owner's decision 2026-09-07: «идём дальше» after B1 was closed (item 26).
Same delivery machinery as items 20–25 (``scripts/fix_grammar_topics_3.py``);
snapshot of all 28 sources in ``local_exports/grammar_b2_all_before/``. Item 21
touched several B2 topics, so in production this SQL is applied AFTER item 21.

Usage::

    venv/bin/python scripts/fix_grammar_b2_all.py            # write JSON + SQL
    venv/bin/python scripts/fix_grammar_b2_all.py --check    # summary only
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

BEFORE = ROOT / 'local_exports' / 'grammar_b2_all_before'
SQL_PREFIX = 'item27_grammar_b2_all'
LEVEL = 'B2'
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




# ============================================ B2_1 Present Perfect Continuous
T = 'B2_1'
base.EDITS[T] = {}
# Seven items whose blank is followed by «been» offered «has been» / «have been» as an
# alternative, i.e. «has been been developing». The real second answer is the contraction.
for _s, _o, _alt in ((4, 1, "'s"), (4, 2, "'ve"), (5, 1, "'s"), (5, 2, "'ve"), (6, 1, "'s"), (7, 1, "'s"), (8, 1, "'s")):
    _ex = _exercise(T, _s, _o)
    assert ' been ' in _ex['content']['question'], (_s, _o)
    fix(T, _s, _o, alternatives=[_alt])


def theory_B2_1(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[3]['subtitle'].startswith('PPC vs Present Perfect Simple'), sections[3]['subtitle']
    # The notes name markers and stative verbs, but no section showed either.
    sections.insert(3, {
        'subtitle': 'Маркеры: for, since, lately, all day',
        'description': 'For задаёт длительность, since — момент начала; lately, recently, all day, How long подчёркивают, '
                       'что процесс тянется до сих пор.',
        'table': [
            {'marker': 'for + период', 'example': 'She has been coping with stress for two months.', 'translation': 'Она справляется со стрессом уже два месяца.'},
            {'marker': 'since + момент', 'example': 'I have been meditating since January.', 'translation': 'Я медитирую с января.'},
            {'marker': 'lately / recently', 'example': 'He has been sleeping badly lately.', 'translation': 'В последнее время он плохо спит.'},
            {'marker': 'all day / all week', 'example': 'They have been working on the report all week.', 'translation': 'Они работают над отчётом всю неделю.'},
            {'marker': 'How long …?', 'example': 'How long have you been practising mindfulness?', 'translation': 'Как давно вы практикуете осознанность?'},
        ],
    })
    sections.insert(5, {
        'subtitle': 'Глаголы состояния: только Present Perfect Simple',
        'description': 'Know, believe, understand, like, love, want, need описывают состояние, а не процесс, '
                       'поэтому в Continuous они не ставятся.',
        'table': [
            {'verb': 'know', 'example': '✅ I have known her for years. ❌ I have been knowing her.', 'translation': 'Я знаю её много лет.'},
            {'verb': 'understand', 'example': '✅ He has understood the risk since the start.', 'translation': 'Он понимает риск с самого начала.'},
            {'verb': 'want / need', 'example': '✅ She has wanted a career change for months.', 'translation': 'Она уже несколько месяцев хочет сменить работу.'},
            {'verb': 'но: think / feel', 'example': 'I have been thinking about it. I have been feeling anxious.', 'translation': 'В значении процесса эти глаголы в Continuous возможны.'},
        ],
    })
    return new


THEORY[T] = theory_B2_1

# ========================================= B2_2 may / might / could (modals)
T = 'B2_2'
base.EDITS[T] = {}


def theory_B2_2(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[2]['subtitle'].startswith('Структура предложений'), sections[2]['subtitle']
    sections[2]['table'] += [
        {'pronoun': 'Вопрос', 'verb': 'Could + подлежащее + V1', 'example': 'Could the data be wrong?', 'translation': 'Могут ли данные быть неверными?'},
        {'pronoun': 'WRONG', 'verb': 'нет -s, нет to, нет двух модальных', 'example': '❌ mays, ❌ may to reveal, ❌ might can',
         'translation': '✅ may, ✅ may reveal, ✅ might be able to'},
    ]
    # Sessions 4-8 drill «may/might/could + have + V3» — the theory never mentioned it.
    sections.insert(3, {
        'subtitle': 'Предположение о прошлом: may / might / could + have + V3',
        'description': 'Чтобы предположить, что произошло раньше, после модального ставится have + третья форма. '
                       'Форма have не меняется на has, а to между модальным и have не вставляется.',
        'table': [
            {'pronoun': 'may have + V3', 'verb': 'скорее всего так и было', 'example': 'The scientists may have left the laboratory.',
             'translation': 'Учёные, возможно, уже ушли из лаборатории.'},
            {'pronoun': 'might have + V3', 'verb': 'менее уверенно', 'example': 'The engineer might have overlooked a flaw.',
             'translation': 'Инженер мог упустить дефект.'},
            {'pronoun': 'could have + V3', 'verb': 'теоретически возможно', 'example': 'The satellite could have drifted off course.',
             'translation': 'Спутник мог отклониться от курса.'},
            {'pronoun': 'отрицание', 'verb': 'may/might not have + V3', 'example': 'The lab may not have received the funding.',
             'translation': 'Лаборатория могла не получить финансирование.'},
            {'pronoun': 'WRONG', 'verb': 'has / to / of', 'example': '❌ may has reached, ❌ might to have, ❌ could of shown',
             'translation': '✅ may have reached, ✅ might have, ✅ could have shown'},
        ],
    })
    extra = _extra_section(new)
    # Nineteen «examples with the module vocabulary» and only one modal among them.
    _swap_examples(extra, {
        'The research was published in a respected medical journal.': ('The research may be published in a respected medical journal.', 'Исследование, возможно, опубликуют в уважаемом медицинском журнале.'),
        'They performed an experiment in the laboratory.': ('They might have performed the experiment in the wrong conditions.', 'Возможно, они провели эксперимент в неподходящих условиях.'),
        'The discovery changed how scientists understood the disease.': ('The discovery could change how scientists understand the disease.', 'Открытие может изменить то, как учёные понимают болезнь.'),
        'The new invention made medical testing faster and cheaper.': ('The new invention may make medical testing faster and cheaper.', 'Новое изобретение может сделать тестирование быстрее и дешевле.'),
        'A scientific theory must be supported by reliable evidence.': ('A theory might not be supported by the latest evidence.', 'Теория может не подтверждаться последними данными.'),
        'The researchers tested their hypothesis in the lab.': ('The researchers may have tested the hypothesis incorrectly.', 'Исследователи могли проверить гипотезу неверно.'),
        'We need more data to confirm this.': ('We might need more data to confirm this.', 'Возможно, нам понадобится больше данных, чтобы это подтвердить.'),
        'The laboratory stores dangerous chemicals in locked cabinets.': ('The laboratory could be closed for renovation next month.', 'Лаборатория может закрыться на ремонт в следующем месяце.'),
        'A genetic test can reveal inherited health risks.': ('A genetic test may reveal inherited health risks.', 'Генетический тест может выявить наследственные риски.'),
        'Modern robotics is changing the way factories are designed.': ('Robotics could change the way factories are designed.', 'Робототехника может изменить то, как проектируют фабрики.'),
        'The spacecraft sent high-resolution images back to Earth.': ('The spacecraft may have sent the images before the failure.', 'Космический корабль мог отправить снимки до сбоя.'),
        'The engineers tested a prototype before starting mass production.': ('The prototype might fail the first safety tests.', 'Прототип может не пройти первые испытания безопасности.'),
        'The satellite monitors weather patterns over the ocean.': ('The satellite might not transmit data during the storm.', 'Спутник может не передавать данные во время бури.'),
        'The algorithm processes data fast.': ('The algorithm could process the data much faster.', 'Алгоритм мог бы обрабатывать данные гораздо быстрее.'),
        'We ran a computer simulation.': ('We may run another simulation tomorrow.', 'Возможно, завтра мы запустим ещё одно моделирование.'),
        'This is a real breakthrough.': ('This could be a real breakthrough.', 'Это может оказаться настоящим прорывом.'),
        'The microchip is smaller than a coin.': ('The next microchip might be smaller than a coin.', 'Следующий микрочип может оказаться меньше монеты.'),
        'The vaccine was tested for two years.': ('The vaccine may have been tested for only two years.', 'Вакцину, возможно, испытывали лишь два года.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Насколько уверенно: must, may, might, could, can\'t'
    dup['description'] = 'Модальные глаголы выстраиваются по степени уверенности — от почти уверенности до её отрицания.'
    dup['table'] = [
        {'modal': 'must', 'meaning': 'почти уверен, что так', 'example': 'The data must be wrong — the result is impossible.', 'translation': 'Данные наверняка неверны.'},
        {'modal': 'may', 'meaning': 'вполне возможно', 'example': 'The result may be correct.', 'translation': 'Результат вполне может быть верным.'},
        {'modal': 'might / could', 'meaning': 'возможно, но менее вероятно', 'example': 'The sensor might be faulty.', 'translation': 'Датчик, возможно, неисправен.'},
        {'modal': "can't", 'meaning': 'почти уверен, что не так', 'example': "This can't be the final version.", 'translation': 'Это точно не окончательная версия.'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_2

# ================================================== B2_3 reported speech
T = 'B2_3'
base.EDITS[T] = {}


def theory_B2_3(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[0]['subtitle'].startswith('Основные правила согласования'), sections[0]['subtitle']
    sections[0]['table'] += [
        {'pronoun': 'Present Perfect Continuous', 'verb': '→', 'example': 'Past Perfect Continuous',
         'translation': 'I have been writing → She said she had been writing.'},
        {'pronoun': 'will', 'verb': '→', 'example': 'would', 'translation': 'I will send it → He said he would send it.'},
        {'pronoun': 'can', 'verb': '→', 'example': 'could', 'translation': 'I can check → She said she could check.'},
        {'pronoun': 'may', 'verb': '→', 'example': 'might', 'translation': 'It may be biased → He said it might be biased.'},
        {'pronoun': 'must', 'verb': '→', 'example': 'had to', 'translation': 'I must go → She said she had to go.'},
        {'pronoun': 'Past Perfect', 'verb': '→', 'example': 'без изменений', 'translation': 'I had checked → He said he had checked.'},
        {'pronoun': 'Общая истина', 'verb': '→', 'example': 'без изменений', 'translation': 'The Sun rises in the east → She said the Sun rises in the east.'},
    ]
    extra = _extra_section(new)
    _swap_examples(extra, {
        'Independent media can hold powerful institutions accountable.': ('She said independent media could hold institutions accountable.', 'Она сказала, что независимые СМИ могут спрашивать с институтов.'),
        'The evening news spread quickly across social networks.': ('He said the evening news had spread quickly across social networks.', 'Он сказал, что вечерние новости быстро разошлись по соцсетям.'),
        'The journalist verified the source before publishing the story.': ('The editor said the journalist had verified the source.', 'Редактор сказал, что журналист проверил источник.'),
        'A misleading headline can distort the whole story.': ('She warned that a misleading headline could distort the whole story.', 'Она предупредила, что вводящий в заблуждение заголовок может исказить весь материал.'),
        'A reliable source is essential for investigative reporting.': ('He said a reliable source was essential for investigative reporting.', 'Он сказал, что надёжный источник необходим для расследований.'),
        'The interview revealed important details about the decision.': ('They said the interview had revealed important details.', 'Они сказали, что интервью раскрыло важные подробности.'),
        'The publication corrected the article after readers complained.': ('The editor admitted that the publication had corrected the article.', 'Редактор признал, что издание исправило статью.'),
        'Short-form content dominates many social media platforms.': ('The analyst said short-form content dominated many platforms.', 'Аналитик сказал, что короткий контент доминирует на многих платформах.'),
        'A credible report cites data and named experts.': ('She explained that a credible report cited data and named experts.', 'Она объяснила, что заслуживающий доверия отчёт ссылается на данные и названных экспертов.'),
    })
    s3 = _dup_section(new, 'Употребление в утверждении')
    s3['subtitle'] = 'Say или tell: глаголы передачи речи'
    s3['description'] = ('Say идёт без адресата, tell — обязательно с ним. Другие глаголы (admit, explain, warn, '
                         'announce, report) уточняют, как именно это было сказано.')
    s3['table'] = [
        {'verb': 'say (that) …', 'example': 'She said (that) the source was reliable.', 'translation': 'Она сказала, что источник надёжный.', 'note': 'без адресата'},
        {'verb': 'tell somebody (that) …', 'example': 'She told me the source was reliable.', 'translation': 'Она сказала мне, что источник надёжный.', 'note': 'адресат обязателен'},
        {'verb': 'WRONG', 'example': '❌ She said me… ❌ She told that…', 'translation': '✅ She said… / She told me…', 'note': 'частая ошибка'},
        {'verb': 'admit / explain / warn', 'example': 'He admitted that he had not checked the source.', 'translation': 'Он признал, что не проверил источник.', 'note': 'оттенок смысла'},
        {'verb': 'announce / report / state', 'example': 'They announced that they were publishing a new report.', 'translation': 'Они объявили, что публикуют новый доклад.', 'note': 'официальнее'},
    ]
    s4 = _dup_section(new, 'Употребление в вопросе')
    s4['subtitle'] = 'Что ещё меняется: местоимения, время и место'
    s4['description'] = 'Вместе со временем глагола сдвигаются местоимения и указатели времени и места.'
    s4['table'] = [
        {'direct': 'I / my', 'reported': 'he, she / his, her', 'example': '"I lost my notes" → He said he had lost his notes.'},
        {'direct': 'now', 'reported': 'then / at that moment', 'example': '"The campaign is at its peak now" → He said it was then at its peak.'},
        {'direct': 'today', 'reported': 'that day', 'example': '"The coverage is thorough today" → She said the coverage was thorough that day.'},
        {'direct': 'yesterday', 'reported': 'the day before / the previous day', 'example': '"I watched it yesterday" → He said he had watched it the day before.'},
        {'direct': 'tomorrow', 'reported': 'the next day / the following day', 'example': '"It will air tomorrow" → She said it would air the next day.'},
        {'direct': 'here / this', 'reported': 'there / that', 'example': '"The interview is here" → She said the interview was there.'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_3


# ==================================== B2_4 non-defining relative clauses
T = 'B2_4'
base.EDITS[T] = {}


def theory_B2_4(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[0]['subtitle'].startswith('Основные правила'), sections[0]['subtitle']
    sections[0]['table'] += [
        {'pronoun': 'when', 'verb': 'для времени', 'example': 'The 1990s, when the Internet spread, changed everything.',
         'translation': '1990-е, когда распространился интернет, изменили всё.'},
        {'pronoun': 'whom', 'verb': 'для людей-дополнений (формально)', 'example': 'Dr Lee, whom we met last year, is retiring.',
         'translation': 'Доктор Ли, которого мы встретили в прошлом году, уходит на пенсию.'},
    ]
    extra = _extra_section(new)
    # Nineteen «examples with the module vocabulary» and not one relative clause among them.
    _swap_examples(extra, {
        'A fair society protects the rights of minorities.': ('A fair society, which protects minorities, benefits everyone.', 'Справедливое общество, которое защищает меньшинства, выигрывает целиком.'),
        'Local culture shapes the way people celebrate important events.': ('Local culture, which shapes celebrations, changes slowly.', 'Местная культура, которая формирует праздники, меняется медленно.'),
        'Cultural diversity can make a community more creative.': ('Cultural diversity, which brings new ideas, makes a community more creative.', 'Культурное разнообразие, которое приносит новые идеи, делает сообщество более творческим.'),
        'The community organized a festival for new residents.': ('The community, whose members come from twelve countries, organised a festival.', 'Сообщество, участники которого приехали из двенадцати стран, организовало фестиваль.'),
        "It's a custom to shake hands when meeting someone.": ('Shaking hands, which is a custom here, can feel strange to visitors.', 'Рукопожатие, которое здесь принято, может показаться странным гостям.'),
        'The tea ceremony is an important ritual in Japanese culture.': ('The tea ceremony, which takes almost an hour, is an important ritual in Japan.', 'Чайная церемония, которая длится почти час, — важный ритуал в Японии.'),
        'Family values are important in our society.': ('Family values, which are passed from generation to generation, still matter here.', 'Семейные ценности, которые передаются из поколения в поколение, здесь всё ещё важны.'),
        'Everyone has the right to their own beliefs.': ('My neighbour, whose beliefs differ from mine, is a good friend.', 'Мой сосед, чьи убеждения отличаются от моих, — хороший друг.'),
        'Many ethnic traditions are passed down through food and music.': ('Ethnic traditions, which live in food and music, survive migration.', 'Этнические традиции, которые живут в еде и музыке, переживают миграцию.'),
        'A multicultural classroom helps students hear different perspectives.': ('Our classroom, where six languages are spoken, is truly multicultural.', 'Наш класс, где звучат шесть языков, действительно мультикультурный.'),
        'Social integration helps immigrants adapt to their new country.': ('The programme helped him integrate quickly, which surprised everyone.', 'Программа помогла ему быстро интегрироваться, что всех удивило.'),
        'The ceremony marked the beginning of the harvest season.': ('September, when the harvest begins, is the month of this ceremony.', 'Сентябрь, когда начинается сбор урожая, — месяц этой церемонии.'),
        'Gender equality is a fundamental human right.': ('Gender equality, which is a fundamental right, is still debated.', 'Гендерное равенство, которое является фундаментальным правом, всё ещё обсуждается.'),
        'Workplace discrimination should be reported and investigated.': ('She reported the discrimination, which took real courage.', 'Она заявила о дискриминации, что потребовало настоящей смелости.'),
        'We must fight against prejudice and stereotypes.': ('Prejudice, which grows out of ignorance, is hard to change.', 'Предрассудки, которые растут из невежества, трудно изменить.'),
        'Real tolerance includes respect for people with different beliefs.': ('Real tolerance, which is more than politeness, includes respect for other beliefs.', 'Настоящая терпимость, которая больше чем вежливость, включает уважение к чужим убеждениям.'),
        'Many immigrants contribute greatly to our economy.': ('The immigrants, who arrived in the 1990s, contributed greatly to the economy.', 'Иммигранты, которые приехали в 1990-е, внесли большой вклад в экономику.'),
        'She applied for citizenship after living here for five years.': ('She applied for citizenship, which took almost two years.', 'Она подала на гражданство, что заняло почти два года.'),
        'Migration shapes modern cities.': ('Migration, which shapes modern cities, is nothing new.', 'Миграция, которая формирует современные города, — совсем не новость.'),
    })
    s4 = _dup_section(new, 'Употребление в утверждении')
    s4['subtitle'] = 'Which обо всей ситуации и запятые'
    s4['description'] = ('Which может комментировать не существительное, а весь предыдущий факт. Запятая перед ним обязательна: '
                         'без запятой предложение читается как defining.')
    s4['table'] = [
        {'structure': 'факт + , which + комментарий', 'example': 'He refused to apologise, which made things worse.',
         'translation': 'Он отказался извиняться, что всё усугубило.'},
        {'structure': 'факт + , which + комментарий', 'example': 'She donated the money, which was very generous of her.',
         'translation': 'Она пожертвовала деньги, что было очень щедро с её стороны.'},
        {'structure': 'запятая обязательна', 'example': '❌ The flight was delayed six hours which frustrated everyone.',
         'translation': '✅ …six hours, which frustrated everyone.'},
        {'structure': 'defining ≠ non-defining', 'example': 'The students who studied passed. / The students, who studied, passed.',
         'translation': 'Сдали те, кто занимался. / Все сдали — а занимались они все.'},
    ]
    s5 = _dup_section(new, 'Употребление в вопросе')
    s5['subtitle'] = 'Пять ошибок, которые проверяют задания'
    s5['description'] = 'Все они одинаково частые и все меняют предложение.'
    s5['table'] = [
        {'wrong': '❌ My aunt, that lives in Rome, …', 'correct': '✅ My aunt, who lives in Rome, …', 'explanation': 'that в non-defining не используется вовсе'},
        {'wrong': '❌ The scholarship, what covered the fees, …', 'correct': '✅ …, which covered the fees, …', 'explanation': 'what не бывает относительным местоимением'},
        {'wrong': "❌ The architect, who's designs won prizes, …", 'correct': '✅ …, whose designs won prizes, …', 'explanation': "who's = who is; принадлежность — whose"},
        {'wrong': '❌ My grandmother, who she was born there, …', 'correct': '✅ …, who was born there, …', 'explanation': 'who уже и есть подлежащее'},
        {'wrong': '❌ My sister, whom is an engineer, …', 'correct': '✅ …, who is an engineer, …', 'explanation': 'whom — только дополнение'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_4

# ================================================== B2_5 second conditional
T = 'B2_5'
base.EDITS[T] = {}
# «If the prices were lower» — plural subject, so the colloquial «was» is not an option here.
fix(T, 5, 1, alternatives=[],
    explanation='If-clause требует Past Simple глагола be. Подлежащее prices стоит во множественном числе, поэтому только were '
                '(разговорное was возможно лишь с единственным числом: if I was…).')
# The main clause was Third Conditional («would have started»), so the sentence was not a
# well-formed Second Conditional at all.
fix(T, 8, 2, question='If I ___ the chance to change one thing about my career, I would become a freelancer.',
    explanation='If-clause требует Past Simple: had. Главная часть — would + база (would become): гипотетика о настоящем, '
                'а не о прошлом.')


def theory_B2_5(content: dict) -> dict:
    new = copy.deepcopy(content)
    # This module never got an «examples with the module vocabulary» section at all.
    new['sections'].append({
        'subtitle': 'Дополнительные примеры со словарём модуля',
        'description': 'Примеры использования лексики модуля в контексте грамматики.',
        'table': [{'example': en, 'translation': ru} for en, ru in [
            ('If this were a hypothetical scenario, the answer would be simple.', 'Если бы это был гипотетический сценарий, ответ был бы простым.'),
            ('If you imagined a different career, what would you choose?', 'Если бы ты представил другую карьеру, что бы ты выбрал?'),
            ('If I could follow one dream, I would open a small studio.', 'Если бы я мог последовать одной мечте, я бы открыл маленькую студию.'),
            ('If there were an alternative, we would consider it seriously.', 'Если бы была альтернатива, мы бы серьёзно её рассмотрели.'),
            ('If the opportunity came up again, I would not hesitate.', 'Если бы возможность появилась снова, я бы не колебался.'),
            ('If I had no regrets, I would probably have taken fewer risks.', 'Если бы у меня не было сожалений, я, наверное, меньше рисковал бы.'),
            ('If you asked for advice, I would recommend waiting a week.', 'Если бы ты попросил совета, я бы порекомендовал подождать неделю.'),
            ('If she suggested a compromise, the team would accept it.', 'Если бы она предложила компромисс, команда бы согласилась.'),
            ('If your priorities changed, would you commit to this project?', 'Если бы твои приоритеты изменились, ты бы взялся за этот проект?'),
            ('If the plan were ideal, nobody would question it.', 'Если бы план был идеальным, никто бы его не оспаривал.'),
            ('If we were realistic, we would set a later deadline.', 'Если бы мы были реалистичны, мы бы назначили более поздний срок.'),
            ('If I were in your shoes, I would consider the alternative.', 'На твоём месте я бы рассмотрел альтернативу.'),
        ]],
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_5

# =================================================== B2_6 embedded questions
T = 'B2_6'
base.EDITS[T] = {}


def theory_B2_6(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[2]['subtitle'].startswith('Yes/No questions'), sections[2]['subtitle']
    sections[2]['table'].append({
        'direct': 'Is it a strength or a weakness?',
        'embedded': 'She asked whether it was a strength or a weakness.',
        'translation': 'Она спросила, сила это или слабость.',
        'note': 'перед «or» и после предлога — только whether',
    })
    sections.insert(4, {
        'subtitle': 'Встроенный вопрос в прошедшем времени',
        'description': 'После asked, wanted to know, wondered время сдвигается назад — как в косвенной речи, — '
                       'но порядок слов остаётся прямым, а do / does / did по-прежнему не ставятся.',
        'table': [
            {'direct_question': 'Why does she feel resentful?', 'embedded': 'He asked why she felt resentful.',
             'translation': 'Он спросил, почему она обижена.', 'note': 'does уходит, feel → felt'},
            {'direct_question': 'What did the patient feel?', 'embedded': 'The therapist asked what the patient felt.',
             'translation': 'Терапевт спросил, что чувствовал пациент.', 'note': 'did уходит, глагол в Past Simple'},
            {'direct_question': 'Is she ready?', 'embedded': 'She wanted to know whether he was ready.',
             'translation': 'Она хотела знать, готов ли он.', 'note': 'is → was, порядок прямой'},
            {'direct_question': 'How have you developed it?', 'embedded': 'She asked me how I had developed it.',
             'translation': 'Она спросила меня, как я это выработал.', 'note': 'have → had'},
        ],
    })
    extra = _extra_section(new)
    # Nineteen «examples with the module vocabulary» and not one embedded question among them.
    _swap_examples(extra, {
        'Emotional resilience helps people cope with adversity.': ('Do you know how emotional resilience helps people cope?', 'Вы знаете, как эмоциональная устойчивость помогает справляться?'),
        'Showing vulnerability can make honest conversations easier.': ('I wonder whether showing vulnerability makes conversations easier.', 'Интересно, облегчает ли проявление уязвимости разговоры.'),
        "Empathy is the ability to understand another person's feelings.": ('Can you explain what empathy really is?', 'Можете объяснить, что такое эмпатия на самом деле?'),
        'Early childhood attachment patterns influence adult relationships.': ("I'd like to know how early attachment influences adult relationships.", 'Я хотел бы знать, как ранняя привязанность влияет на взрослые отношения.'),
        'Codependency can be unhealthy in romantic relationships.': ('She wonders whether codependency is always unhealthy.', 'Ей интересно, всегда ли созависимость нездорова.'),
        'Setting healthy boundaries is essential for self-care.': ('Could you explain why healthy boundaries matter so much?', 'Не могли бы вы объяснить, почему здоровые границы так важны?'),
        'Daily mindfulness helps some people notice stress earlier.': ("I'm not sure whether daily mindfulness works for everyone.", 'Я не уверен, всем ли подходит ежедневная осознанность.'),
        'Childhood trauma can have lasting effects on mental health.': ('He asked how childhood trauma affects mental health.', 'Он спросил, как детская травма влияет на психическое здоровье.'),
        'Gaslighting is a form of psychological manipulation.': ('Do you know how gaslighting differs from an honest mistake?', 'Вы знаете, чем газлайтинг отличается от честной ошибки?'),
        'Narcissism is characterized by excessive self-focus.': ('I wonder why narcissism is so hard to recognise.', 'Интересно, почему нарциссизм так трудно распознать.'),
        'Projection occurs when people attribute their own feelings to others.': ('Can you tell me when projection usually occurs?', 'Можете сказать, когда обычно возникает проекция?'),
        'Emotional intimacy requires trust and honest conversation.': ('She asked whether intimacy was possible without trust.', 'Она спросила, возможна ли близость без доверия.'),
        'Long-term compatibility depends on shared values.': ('It depends on what values the partners share.', 'Это зависит от того, какие ценности разделяют партнёры.'),
        'Unspoken resentment can damage a friendship over time.': ("I can't figure out why the resentment stayed unspoken.", 'Я не могу понять, почему обида осталась невысказанной.'),
        'Emotional validation makes people feel heard and understood.': ('What matters most is how people are heard.', 'Важнее всего то, как людей слышат.'),
        'Cognitive dissonance occurs when beliefs and actions conflict.': ("I'd like to understand what cognitive dissonance feels like.", 'Я хотел бы понять, каково это — когнитивный диссонанс.'),
        'Healthy self-esteem is crucial for psychological well-being.': ('He wanted to know whether self-esteem could be rebuilt.', 'Он хотел знать, можно ли восстановить самооценку.'),
        'Assertiveness training helps people communicate their needs.': ("I'd like to know how she developed assertiveness.", 'Я хотел бы знать, как она развила ассертивность.'),
        'Transference in therapy involves redirecting feelings onto the therapist.': ('Could you explain how transference works in therapy?', 'Не могли бы вы объяснить, как работает перенос в терапии?'),
    })
    return new


THEORY[T] = theory_B2_6


# ================================================ B2_7 gerund vs infinitive
T = 'B2_7'
base.EDITS[T] = {}
# The single alternative repeated the key verbatim, so it was no alternative at all.
fix(T, 4, 6, alternatives=['They decided not to buy a new car this year.'.replace('a new car', 'a car'),
                           "They've decided not to buy a new car this year."],
    explanation='После глагола decide идёт инфинитив с to, а отрицание ставится ПЕРЕД to: decided not to buy '
                '(не «decided to not buy»).')
fix(T, 5, 3, question='We were warned ___ that dark street at night.',
    options=['not to take', 'not taking', 'to not take', 'taking not'], correct_answer='not to take',
    explanation='После глагола warn идёт инфинитив с to, а отрицание ставится перед to: warned not to take. '
                'Перевод: Нас предупредили не ходить по той тёмной улице ночью.')
THEORY[T] = copy.deepcopy

# ================================================== B2_8 reported questions
T = 'B2_8'
base.EDITS[T] = {}


def theory_B2_8(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[2]['subtitle'].startswith('Reported Commands'), sections[2]['subtitle']
    # Every session drills the backshift, and no section ever showed it.
    sections.insert(2, {
        'subtitle': 'Сдвиг времени в косвенном вопросе',
        'description': 'После asked / wanted to know / wondered время уходит на шаг назад — как и в косвенной речи. '
                       'Порядок слов при этом остаётся прямым, а do / does / did исчезают совсем.',
        'table': [
            {'direct': 'Where do you live?', 'reported': 'He asked where I lived.', 'type': 'Present Simple → Past Simple'},
            {'direct': 'Are you coming?', 'reported': 'She asked whether I was coming.', 'type': 'Present Continuous → Past Continuous'},
            {'direct': 'Have you travelled there?', 'reported': 'He asked if I had travelled there.', 'type': 'Present Perfect → Past Perfect'},
            {'direct': 'Did you finish it?', 'reported': 'She asked if I had finished it.', 'type': 'Past Simple → Past Perfect'},
            {'direct': 'When will you be ready?', 'reported': 'He asked when I would be ready.', 'type': 'will → would'},
            {'direct': 'Can you help?', 'reported': 'She asked if I could help.', 'type': 'can → could'},
        ],
    })
    sections.insert(3, {
        'subtitle': 'Два случая, где порядок слов не меняется вовсе',
        'description': 'Если вопросительное слово само является подлежащим (who, what, which), инверсии не было '
                       'и в прямом вопросе, поэтому менять нечего.',
        'table': [
            {'direct': 'Who called?', 'reported': 'She asked who had called.', 'type': 'who — подлежащее'},
            {'direct': 'What happened?', 'reported': 'He wanted to know what had happened.', 'type': 'what — подлежащее'},
            {'direct': 'Who did you call?', 'reported': 'She asked who I had called.', 'type': 'who — дополнение, did уходит'},
            {'direct': 'WRONG', 'reported': '❌ She asked me that I could help. → ✅ … asked me if I could help.',
             'type': 'that вводит утверждение, но не вопрос'},
        ],
    })
    extra = _extra_section(new)
    _swap_examples(extra, {
        "The channel denied the reporter's claim.": ("The anchor asked whether the channel had denied the claim.", 'Ведущий спросил, отрицал ли канал это заявление.'),
        "The channel's breaking news interrupted the regular evening programme.": ('Viewers asked why the breaking news had interrupted the programme.', 'Зрители спросили, почему срочные новости прервали программу.'),
        'The report included interviews with several witnesses.': ('The editor asked how many witnesses the report had included.', 'Редактор спросил, сколько свидетелей вошло в репортаж.'),
        'The advertisement was criticized for misleading viewers.': ('She wanted to know why the advertisement had been criticised.', 'Она хотела знать, почему рекламу раскритиковали.'),
        'Many readers subscribe to independent newsletters.': ('He asked how many readers subscribed to the newsletter.', 'Он спросил, сколько читателей подписано на рассылку.'),
        'The newsroom checked every fact before the story went live.': ('The editor asked if the newsroom had checked every fact.', 'Редактор спросил, проверила ли редакция каждый факт.'),
        'Independent journalism depends on reliable sources.': ('The student asked what independent journalism depended on.', 'Студент спросил, от чего зависит независимая журналистика.'),
        'Online misinformation spreads quickly during a public crisis.': ('They wondered how quickly misinformation spread online.', 'Они задавались вопросом, как быстро дезинформация расходится в сети.'),
        'We watched the livestream of the debate.': ('She asked whether we had watched the livestream.', 'Она спросила, смотрели ли мы прямой эфир.'),
        'Editors fact-check sensitive claims before publication.': ('He asked when editors fact-checked sensitive claims.', 'Он спросил, когда редакторы проверяют чувствительные утверждения.'),
        'Her reply was thoughtful.': ('He asked what her reply had been.', 'Он спросил, каким был её ответ.'),
        'He described the interrogation.': ('They asked him to describe the interrogation.', 'Его попросили описать допрос.'),
        'The consultation was free.': ('She asked whether the consultation was free.', 'Она спросила, бесплатна ли консультация.'),
        'She made an official inquiry.': ('The clerk asked why she had made an official inquiry.', 'Служащий спросил, почему она подала официальный запрос.'),
        'The investigation is ongoing.': ('Journalists asked how long the investigation would continue.', 'Журналисты спросили, как долго продлится расследование.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Четыре ошибки, которые проверяют задания'
    dup['description'] = 'Все они одинаково частые: инверсия, лишний вспомогательный, отсутствие сдвига и that вместо if.'
    dup['table'] = [
        {'wrong': '❌ She asked where did I buy it.', 'correct': '✅ She asked where I bought it.', 'explanation': 'инверсия прямого вопроса'},
        {'wrong': '❌ He asked if could he return it.', 'correct': '✅ He asked if he could return it.', 'explanation': 'после if — подлежащее, потом глагол'},
        {'wrong': '❌ He wanted to know if I have travelled there.', 'correct': '✅ … if I had travelled there.', 'explanation': 'нет сдвига времени'},
        {'wrong': '❌ My supervisor asked me that I could work late.', 'correct': '✅ … asked me if I could work late.', 'explanation': 'that не вводит вопрос'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_8

# =============================================== B2_9 passive (past simple)
T = 'B2_9'
base.EDITS[T] = {}


def theory_B2_9(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[2]['subtitle'].startswith('BY для указания'), sections[2]['subtitle']
    # Negation and questions are drilled in every session and appeared in no section.
    sections.insert(3, {
        'subtitle': 'Отрицание и вопрос',
        'description': 'Отрицание строится через was/were + not + V3, вопрос — вынесением was/were вперёд. '
                       'Did в пассиве не используется вовсе.',
        'table': [
            {'structure': 'отрицание', 'example': 'The residents were not informed about the changes.', 'translation': 'Жителей не проинформировали об изменениях.'},
            {'structure': 'краткая форма', 'example': "The letter wasn't delivered on time.", 'translation': 'Письмо не доставили вовремя.'},
            {'structure': 'вопрос', 'example': 'Was the contract signed before the deadline?', 'translation': 'Контракт подписали до срока?'},
            {'structure': 'вопрос, мн. ч.', 'example': 'Were the witnesses questioned separately?', 'translation': 'Свидетелей допрашивали по отдельности?'},
            {'structure': 'отрицательный вопрос', 'example': "Wasn't the criminal caught last night?", 'translation': 'Разве преступника не поймали прошлой ночью?'},
            {'structure': 'WRONG', 'example': '❌ The letter did not delivered. ❌ Did the contract signed?', 'translation': '✅ was not delivered, ✅ Was the contract signed?'},
        ],
    })
    extra = _extra_section(new)
    _swap_examples(extra, {
        'New apps often raise serious privacy concerns.': ('Serious privacy concerns were raised after the update.', 'После обновления возникли серьёзные опасения о приватности.'),
        'Machine learning is used in many apps.': ('Machine learning was used to sort the images.', 'Для сортировки изображений использовали машинное обучение.'),
        'Engineers used 3D printing to produce a replacement part.': ('A replacement part was produced by 3D printing.', 'Запасную деталь изготовили 3D-печатью.'),
        'Scientists discovered a new species.': ('A new species was discovered last summer.', 'Новый вид открыли прошлым летом.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Четыре ошибки, которые проверяют задания'
    dup['description'] = 'Пассив ломается одинаково: не та форма глагола, пропущенное was/were, чужое did и рассогласование числа.'
    dup['table'] = [
        {'wrong': '❌ The windows were broke.', 'correct': '✅ The windows were broken.', 'explanation': 'нужна третья форма, а не вторая'},
        {'wrong': '❌ The stadium constructed in a year.', 'correct': '✅ The stadium was constructed in a year.', 'explanation': 'без was/were это не пассив'},
        {'wrong': '❌ The samples were collect.', 'correct': '✅ The samples were collected.', 'explanation': 'базовая форма вместо V3'},
        {'wrong': '❌ The candidates was interviewed.', 'correct': '✅ The candidates were interviewed.', 'explanation': 'число подлежащего решает was или were'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_9


# ==================================================== B2_10 causative have/get
T = 'B2_10'
base.EDITS[T] = {}


def theory_B2_10(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[2]['subtitle'].startswith('В контексте преступности'), sections[2]['subtitle']
    sections.insert(3, {
        'subtitle': 'Три каузативные конструкции — не путать',
        'description': 'Have something done — работу делает кто-то другой; have somebody do — вы поручаете конкретному '
                       'человеку (после него голая форма); get somebody to do — вы уговариваете (после него to).',
        'table': [
            {'structure': 'have + объект + V3', 'example': 'I had my car serviced.', 'translation': 'Мне обслужили машину (кто — неважно).'},
            {'structure': 'have + человек + V1', 'example': 'I had my lawyer review the contract.', 'translation': 'Я поручил адвокату проверить контракт.'},
            {'structure': 'get + человек + to + V1', 'example': 'I got my lawyer to review the contract.', 'translation': 'Я уговорил адвоката проверить контракт.'},
            {'structure': 'отрицание и вопрос', 'example': "Did you have your laptop repaired? — No, I didn't have it repaired.",
             'translation': 'Каузатив с have строит вопрос через do/does/did.'},
            {'structure': 'WRONG', 'example': '❌ I had my car service. ❌ I had my lawyer to review it.',
             'translation': '✅ had my car serviced, ✅ had my lawyer review it'},
        ],
    })
    extra = _extra_section(new)
    _swap_examples(extra, {
        'The crime rate has decreased in our city.': ('The council had the crime rate analysed by independent experts.', 'Совет заказал независимым экспертам анализ уровня преступности.'),
        'The law protects citizens from unlawful searches.': ('He had the new law explained to him by a solicitor.', 'Ему разъяснил новый закон юрист.'),
        'True justice requires both fairness and accountability.': ('They got the case reviewed by a higher court.', 'Они добились пересмотра дела в вышестоящем суде.'),
        'The criminal was identified from security footage.': ('The police had the criminal identified from security footage.', 'Полиция установила личность преступника по записям камер.'),
        'The theft from small shops increased during the holiday season.': ('The shop had its alarm system upgraded after the theft.', 'После кражи магазин заказал модернизацию сигнализации.'),
        'There was a bank robbery last night.': ('The bank had its vault reinforced after the robbery.', 'После ограбления банк укрепил хранилище.'),
        'Online fraud often targets elderly customers.': ('She had her accounts frozen as soon as she noticed the fraud.', 'Заметив мошенничество, она заблокировала счета.'),
        'The witness gave a detailed statement to the police.': ('They had the witness statement recorded on video.', 'Показания свидетеля записали на видео.'),
        'The evidence was presented to the jury.': ('The lawyer had the evidence examined by a forensic expert.', 'Адвокат отдал улики на экспертизу.'),
        'The trial lasted for six weeks.': ('The defendant got the trial postponed for a month.', 'Подсудимый добился переноса процесса на месяц.'),
        'The sentence was reduced on appeal.': ('He had his sentence reduced on appeal.', 'Ему смягчили приговор после апелляции.'),
        'I had to pay a fine for speeding.': ('I had my licence suspended after the second fine.', 'После второго штрафа у меня изъяли права.'),
        'The judge asked both lawyers to clarify their arguments.': ('The judge had both lawyers clarify their arguments.', 'Судья заставил обоих адвокатов уточнить аргументы.'),
        'He was sent to prison for ten years.': ('His family got the case reopened while he was in prison.', 'Пока он был в тюрьме, семья добилась пересмотра дела.'),
        'The jury found the defendant guilty.': ('The defence had the verdict challenged immediately.', 'Защита сразу оспорила вердикт.'),
        'The suspect insisted that he was innocent.': ('The suspect had his phone records checked to prove he was innocent.', 'Подозреваемый попросил проверить его звонки, чтобы доказать невиновность.'),
        'The police made an arrest this morning.': ('They had the suspect arrested this morning.', 'Сегодня утром они добились ареста подозреваемого.'),
        'The prosecution presented evidence.': ('The prosecution had the documents translated for the court.', 'Обвинение заказало перевод документов для суда.'),
        'The defendant remained calm.': ('The defendant had his statement read out by his lawyer.', 'Заявление подсудимого зачитал его адвокат.'),
    })
    dup = _dup_section(new)
    dup['subtitle'] = 'Каузатив о неприятностях'
    dup['description'] = ('Та же конструкция описывает и то, чего вы совсем не заказывали: have / get + объект + V3 '
                          'о происшествии, случившемся с вами.')
    dup['table'] = [
        {'structure': 'have + объект + V3', 'example': 'We had our house burgled last month.', 'translation': 'В прошлом месяце нас обокрали.'},
        {'structure': 'have + объект + V3', 'example': 'She had her bag stolen at the station.', 'translation': 'У неё украли сумку на вокзале.'},
        {'structure': 'get + объект + V3', 'example': 'He got his car damaged in the car park.', 'translation': 'Ему повредили машину на парковке.'},
        {'structure': 'разница со смыслом «заказал»', 'example': 'I had my hair cut. ≠ I had my window broken.',
         'translation': 'Первое — по своей воле, второе — случилось с вами.'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_10

# ========================================================= B2_11 past perfect
T = 'B2_11'
base.EDITS[T] = {}


def theory_B2_11(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[3]['subtitle'].startswith('Past Perfect в контексте'), sections[3]['subtitle']
    # Passive and Continuous forms are drilled from session 5 on and appeared nowhere.
    sections.insert(4, {
        'subtitle': 'Пассив и длительная форма',
        'description': 'had been + V3 — пассив «прошлого в прошлом»; had been + V-ing — процесс, который тянулся до '
                       'момента в прошлом.',
        'table': [
            {'form': 'Passive', 'structure': 'had been + V3', 'example': 'Their flight had already been cancelled.',
             'translation': 'Их рейс уже был отменён.'},
            {'form': 'Passive', 'structure': 'had been + V3', 'example': 'They discovered that the budget had been exceeded.',
             'translation': 'Они обнаружили, что бюджет был превышен.'},
            {'form': 'Continuous', 'structure': 'had been + V-ing', 'example': 'The factories had been polluting the river for years.',
             'translation': 'Фабрики годами загрязняли реку.'},
            {'form': 'Continuous', 'structure': 'had been + V-ing', 'example': 'She had been waiting for an hour when the train arrived.',
             'translation': 'Она ждала уже час, когда пришёл поезд.'},
        ],
    })
    extra = _extra_section(new)
    _swap_examples(extra, {
        'We planned a detailed itinerary for our European tour.': ('We had planned a detailed itinerary before we left.', 'Мы составили подробный маршрут до отъезда.'),
        'We had a six-hour layover in Frankfurt.': ('By the time we landed, we had already sat through a six-hour layover.', 'К моменту посадки мы уже пересидели шестичасовую пересадку.'),
        'Meet me at the baggage claim after you land.': ('When I reached baggage claim, my suitcase had already arrived.', 'Когда я дошёл до выдачи багажа, мой чемодан уже приехал.'),
        'I suffered from terrible jet lag after the long flight.': ('I had never suffered from jet lag before that flight.', 'До того перелёта я никогда не страдал от смены часовых поясов.'),
        'Always buy travel insurance before going abroad.': ('Luckily, we had bought travel insurance before the accident.', 'К счастью, мы купили страховку до происшествия.'),
        'We took a guided excursion to the ancient ruins.': ('The excursion had already started when we arrived.', 'Экскурсия уже началась, когда мы приехали.'),
        'The Eiffel Tower is a famous landmark in Paris.': ('She had never seen the landmark before that trip.', 'До той поездки она никогда не видела эту достопримечательность.'),
        'Many backpackers travel on a tight budget.': ('The backpackers had spent all their money before the last week.', 'Бэкпэкеры потратили все деньги ещё до последней недели.'),
        'Hostels are cheaper than hotels for budget travelers.': ('We had booked a hostel before the prices went up.', 'Мы забронировали хостел до того, как цены выросли.'),
        'The currency exchange rate at the airport is terrible.': ('He realised he had changed his money at a terrible rate.', 'Он понял, что обменял деньги по ужасному курсу.'),
        'I bought a round-trip ticket to save money.': ('I had bought a round-trip ticket, so the return was free.', 'Я купил билет туда-обратно, поэтому обратная дорога уже была оплачена.'),
        'Due to bad weather, there were many flight cancellations.': ('By morning, the airline had cancelled a dozen flights.', 'К утру авиакомпания отменила дюжину рейсов.'),
    })
    return new


THEORY[T] = theory_B2_11

# ==================================================== B2_12 participle clauses
T = 'B2_12'
base.EDITS[T] = {}


def theory_B2_12(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    extra = _extra_section(new)
    _swap_examples(extra, {
        'The Mona Lisa is considered a masterpiece of Renaissance art.': ('Painted in the 16th century, the Mona Lisa is still the most visited masterpiece.', 'Написанная в XVI веке, Мона Лиза остаётся самым посещаемым шедевром.'),
        'The museum is hosting an exhibition of modern sculptures.': ('Featuring over a hundred works, the exhibition opened last week.', 'Представляя более ста работ, выставка открылась на прошлой неделе.'),
        'We visited several art galleries in the city center.': ('Walking through the gallery, we noticed an unusual portrait.', 'Идя по галерее, мы заметили необычный портрет.'),
        'The sculptor carved the figure from marble.': ('Carved from marble, the figure weighs almost a tonne.', 'Вырезанная из мрамора, фигура весит почти тонну.'),
        'She painted a beautiful portrait of her grandmother.': ('Having finished the portrait, she invited the curator to see it.', 'Закончив портрет, она пригласила куратора посмотреть.'),
        'The artist works mainly with oil on canvas.': ('Working mainly with oil, the artist rarely uses digital tools.', 'Работая в основном маслом, художник редко берётся за цифровые инструменты.'),
        'I find abstract art difficult to understand.': ('Not understanding abstract art, he stayed silent during the tour.', 'Не понимая абстрактное искусство, он молчал на экскурсии.'),
        'This ancient temple is part of our cultural heritage.': ('Preserved for centuries, the temple is part of our heritage.', 'Сохранённый веками, храм — часть нашего наследия.'),
        'The curator gave us a tour of the new exhibition.': ('Guided by the curator, we saw the restored murals first.', 'Ведомые куратором, мы первыми увидели отреставрированные фрески.'),
        'She studied archaeology at university and now works on excavations.': ('Having studied archaeology, she now works on excavations.', 'Изучив археологию, она теперь работает на раскопках.'),
        'The publisher rejected the first manuscript after a long review.': ('Rejected once, the manuscript was published two years later.', 'Однажды отвергнутая, рукопись вышла через два года.'),
        'Diego Rivera is famous for his colorful murals.': ('Known for his colourful murals, Rivera influenced a generation.', 'Известный своими яркими фресками, Ривера повлиял на целое поколение.'),
        'Traditional folklore is passed down through generations.': ('Passed down through generations, the folklore has never been written down.', 'Передаваемый из поколения в поколение, фольклор так и не был записан.'),
        'The museum displayed a rare Roman artifact near the entrance.': ('Discovered in Egypt, the artifact is now displayed near the entrance.', 'Найденный в Египте, артефакт теперь выставлен у входа.'),
        'The Renaissance was a period of great artistic achievement.': ('Beginning in Italy, the Renaissance spread across Europe.', 'Начавшись в Италии, Ренессанс распространился по Европе.'),
        'Many contemporary artists mix digital media with painting.': ('Mixing digital media with paint, contemporary artists blur the old boundaries.', 'Смешивая цифровые медиа с краской, современные художники стирают старые границы.'),
        'The painting underwent careful restoration after being damaged.': ('Damaged by fire, the painting needed careful restoration.', 'Повреждённая огнём, картина нуждалась в тщательной реставрации.'),
        'The composition of this painting is perfectly balanced.': ('Balanced perfectly, the composition draws the eye to the centre.', 'Идеально сбалансированная, композиция ведёт взгляд к центру.'),
        'Everyone has their own aesthetic preferences in art.': ('Having seen both versions, visitors chose the earlier one.', 'Увидев обе версии, посетители выбрали раннюю.'),
        'The Sistine Chapel ceiling is a famous fresco by Michelangelo.': ('Restored in the 1990s, the Sistine ceiling regained its colours.', 'Отреставрированный в 1990-е, потолок Сикстинской капеллы вернул себе цвета.'),
    })
    # Section 6 held a single row copied from section 5 — a whole section for one duplicate line.
    tail = sections[-1]
    assert tail['subtitle'].startswith('Дополнительные примеры (закрепление)') and len(tail['table']) == 1, tail
    tail['subtitle'] = 'Причастие вместо придаточного и висящее причастие'
    tail['description'] = ('Причастие сокращает определительное придаточное (who is / which was), а отрицание ставится '
                           'перед ним. Главная ловушка: причастие всегда относится к подлежащему главного предложения.')
    tail['table'] = [
        {'usage': 'вместо who is / which is', 'full_sentence': 'The woman who is sitting at the desk is the receptionist.',
         'participle_clause': 'The woman sitting at the desk is the receptionist.', 'translation': 'Женщина, сидящая за стойкой, — администратор.'},
        {'usage': 'вместо which were', 'full_sentence': 'The documents which were left on the table belong to the director.',
         'participle_clause': 'The documents left on the table belong to the director.', 'translation': 'Документы, оставленные на столе, принадлежат директору.'},
        {'usage': 'отрицание', 'full_sentence': 'She did not know what to say, so she remained silent.',
         'participle_clause': 'Not knowing what to say, she remained silent.', 'translation': 'Не зная, что сказать, она промолчала.'},
        {'usage': 'висящее причастие', 'full_sentence': '❌ Walking home, the bridge looked beautiful.',
         'participle_clause': '✅ Walking home, I thought the bridge looked beautiful.', 'translation': 'Мост сам домой не шёл: причастие относится к подлежащему.'},
    ]
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_12


# =================================================== B2_13 concessive clauses
T = 'B2_13'
base.EDITS[T] = {}


def theory_B2_13(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    position = sections[3]
    assert position['subtitle'].startswith('4. Позиция'), position['subtitle']
    # The notes promised sentence-final "though" and no table ever showed it.
    position['table'].append({
        'position': 'though в конце предложения',
        'example': "Emissions are falling. It's still too slow, though.",
        'note': 'Только though; although и even though так не ставятся.',
        'translation': 'Выбросы падают. Правда, всё ещё слишком медленно.',
    })
    extra = _extra_section(new)
    _swap_examples(extra, {
        'Carbon emissions must be reduced to fight global warming.': ('Although carbon emissions must be reduced, few countries have binding targets.', 'Хотя выбросы углерода нужно сокращать, обязательные цели есть у немногих стран.'),
        'Many endangered animals need stronger legal protection.': ('Despite stronger legal protection, many species are still endangered.', 'Несмотря на усиленную правовую защиту, многие виды по-прежнему под угрозой.'),
        'Solar power is a renewable energy source.': ('Even though solar power is renewable, its production still leaves a footprint.', 'Хотя солнечная энергия возобновляема, её производство тоже оставляет след.'),
        'The greenhouse effect is warming our planet.': ('In spite of the greenhouse effect, some regions are getting colder winters.', 'Несмотря на парниковый эффект, в некоторых регионах зимы становятся холоднее.'),
        'Soil erosion is a major agricultural problem.': ('Although soil erosion is a major problem, few farms change their methods.', 'Хотя эрозия почвы — серьёзная проблема, методы меняют немногие хозяйства.'),
        'Burning fossil fuels releases carbon dioxide into the atmosphere.': ('Despite burning less coal, the country still relies on fossil fuels.', 'Несмотря на сокращение угля, страна по-прежнему зависит от ископаемого топлива.'),
        'The depletion of the ozone layer was a major concern in the 1980s.': ('Despite the fact that the ozone layer is recovering, the treaty remains in force.', 'Несмотря на то что озоновый слой восстанавливается, договор остаётся в силе.'),
        'Chemical contamination made the river unsafe for swimming.': ('Although the contamination was severe, the plant kept operating.', 'Хотя загрязнение было серьёзным, завод продолжал работать.'),
        'The preservation of natural resources is crucial for future generations.': ('In spite of the preservation programme, the wetland keeps shrinking.', 'Несмотря на программу сохранения, водно-болотные угодья продолжают сокращаться.'),
        'Each stakeholder should be consulted before the policy is approved.': ('Though every stakeholder was consulted, the policy pleased nobody.', 'Хотя опросили все заинтересованные стороны, политика не устроила никого.'),
        'Biodiversity is declining.': ('Difficult though it is, we must reverse the decline in biodiversity.', 'Как бы это ни было трудно, мы должны остановить падение биоразнообразия.'),
        'The ecosystem is fragile.': ('However fragile the ecosystem is, it can recover if left alone.', 'Какой бы хрупкой ни была экосистема, она восстановится, если её не трогать.'),
        'Sustainability is now mainstream.': ('Much as companies talk about sustainability, few change their supply chains.', 'Как бы компании ни рассуждали об устойчивости, цепочки поставок меняют немногие.'),
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_13

# ================================================== B2_14 figurative language
T = 'B2_14'
base.EDITS[T] = {}


def theory_B2_14(content: dict) -> dict:
    new = copy.deepcopy(content)
    sections = new['sections']
    assert sections[5]['subtitle'].startswith('Как декодировать'), sections[5]['subtitle']
    # Twenty idioms are drilled across the eight sessions and never introduced anywhere.
    sections.insert(5, {
        'subtitle': 'Справочник: идиомы из заданий',
        'description': 'Эти выражения встречаются в упражнениях темы. Тема слева объясняет, почему у идиомы '
                       'именно такое значение — по ней же угадывается и незнакомое выражение из той же группы.',
        'table': [
            {'idiom': 'cost an arm and a leg', 'category': 'body', 'meaning': 'стоить очень дорого', 'example': 'This phone costs an arm and a leg.'},
            {'idiom': 'give someone the cold shoulder', 'category': 'body', 'meaning': 'демонстративно игнорировать', 'example': 'She gave him the cold shoulder after the argument.'},
            {'idiom': 'fight tooth and nail', 'category': 'body', 'meaning': 'бороться изо всех сил', 'example': 'They fought tooth and nail for the amendment.'},
            {'idiom': 'win by a nose', 'category': 'body / horses', 'meaning': 'победить с минимальным отрывом', 'example': 'He won the contract by a nose.'},
            {'idiom': 'keep your cards close to your chest', 'category': 'game', 'meaning': 'не раскрывать планов', 'example': 'The CEO keeps her cards close to her chest.'},
            {'idiom': 'pass the buck', 'category': 'game', 'meaning': 'перекладывать ответственность', 'example': 'Everyone tried to pass the buck.'},
            {'idiom': 'reach a stalemate', 'category': 'game', 'meaning': 'зайти в тупик', 'example': 'The talks reached a stalemate.'},
            {'idiom': 'a level playing field', 'category': 'sport', 'meaning': 'равные условия', 'example': 'Small firms want a level playing field.'},
            {'idiom': 'an uphill battle', 'category': 'war', 'meaning': 'заведомо трудная борьба', 'example': 'Winning customers back is an uphill battle.'},
            {'idiom': 'put all your eggs in one basket', 'category': 'food', 'meaning': 'поставить всё на одно', 'example': "Don't put all your eggs in one basket."},
            {'idiom': 'not mince your words', 'category': 'food', 'meaning': 'говорить прямо', 'example': "She doesn't mince her words."},
            {'idiom': 'rake someone over the coals', 'category': 'fire', 'meaning': 'сурово отчитать', 'example': 'The director raked the team over the coals.'},
            {'idiom': 'break the ice', 'category': 'weather', 'meaning': 'начать общение', 'example': "Let's break the ice."},
            {'idiom': 'under the weather', 'category': 'weather', 'meaning': 'нездоровится', 'example': "I'm feeling a bit under the weather."},
            {'idiom': 'a storm in a teacup', 'category': 'weather', 'meaning': 'много шума из ничего', 'example': 'The whole row was a storm in a teacup.'},
            {'idiom': 'take the bull by the horns', 'category': 'animals', 'meaning': 'решительно взяться за дело', 'example': 'She took the bull by the horns.'},
            {'idiom': 'have deep pockets', 'category': 'money', 'meaning': 'располагать большими средствами', 'example': 'The company has very deep pockets.'},
            {'idiom': 'money is no object', 'category': 'money', 'meaning': 'цена не имеет значения', 'example': 'Money is no object for this client.'},
            {'idiom': 'get the green light', 'category': 'traffic', 'meaning': 'получить разрешение', 'example': 'The project got the green light.'},
            {'idiom': 'jump on the bandwagon', 'category': 'parade', 'meaning': 'примкнуть к модному течению', 'example': 'Everyone jumped on the bandwagon.'},
            {'idiom': 'throw in the towel', 'category': 'sport', 'meaning': 'сдаться', 'example': 'The coach refused to throw in the towel.'},
            {'idiom': 'pull no punches', 'category': 'sport', 'meaning': 'говорить без обиняков', 'example': 'The report pulls no punches.'},
            {'idiom': 'have the upper hand', 'category': 'fight', 'meaning': 'быть в более сильной позиции', 'example': 'By the end, the buyer had the upper hand.'},
            {'idiom': 'in full swing', 'category': 'movement', 'meaning': 'в самом разгаре', 'example': 'The talks were in full swing.'},
            {'idiom': 'throw your weight around', 'category': 'body', 'meaning': 'давить авторитетом', 'example': 'The new director throws his weight around.'},
            {'idiom': 'keep a stiff upper lip', 'category': 'body', 'meaning': 'держаться, не подавая виду', 'example': 'He kept a stiff upper lip during the crisis.'},
            {'idiom': 'a storm is brewing', 'category': 'weather', 'meaning': 'назревает конфликт', 'example': 'A storm was brewing in the team.'},
        ],
    })
    base._rebuild_tldr_summary(new)
    return new


THEORY[T] = theory_B2_14


# The prod copy's grammar_topics mirror can lag lessons.content; a probe here aligns exactly
# one cell so the preflight fails on a real prod edit instead of on known drift.
DRIFT_PROBES: dict[str, tuple[str, str, str]] = {}

_HEAD_END = {
    '1_check': '-- the DO block at the end raises the list of mismatching slots.\n',
    '2_apply': '-- inside the transaction — if any slot or theory mirror is off, so nothing partial commits.\n',
}


def drift_alignment_sql() -> str:
    lines = ['-- Item 27 pre-step: align stale cells of the grammar_topics mirror with the lesson',
             '-- (in 1_check these are the ONLY statements that write; everything below only counts rows).',
             '-- (expected: 1 row each on a copy that still carries the stale value, 0 rows once aligned).',
             '-- Only these cells are touched: an unrelated prod edit elsewhere in the theory must still',
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
    base.ASSERT_LABEL = 'item27'
    base.SQL_TITLE = 'Lesson audit item 27: grammar content of the whole B2 level (14 topics). Apply AFTER items 21-26.'
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
    if DRIFT_PROBES:
        pre = drift_alignment_sql()
        for suffix, head_end in _HEAD_END.items():
            assert sql[suffix].count(head_end) == 1, suffix
            sql[suffix] = sql[suffix].replace(head_end, head_end + pre, 1)
    for suffix, text in sql.items():
        path = base.EXPORT_DIR / f'{SQL_PREFIX}_{suffix}.sql'
        path.write_text(text, encoding='utf-8')
        print('wrote', path.relative_to(ROOT), f'({len(text) // 1024} KiB)')
    return 0



# ---------------------------------------------------------------- late findings
# Read of sessions 6-8 across the level (the mechanical scan is clean; these are semantic).
# B2_9 7#2: "species" is both singular and plural, so "was protected" is as correct as the key.
fix('B2_9', 7, 2, question='The endangered animals ___ protected under new environmental legislation.',
    explanation='Подлежащее «animals» стоит во множественном числе, поэтому пассив строится через were + V3. '
                'Перевод: Животные, находящиеся под угрозой, были защищены новым природоохранным законом.')
# B2_10 4#1: the bracketed hint printed the answer verbatim; the get-construction tests the same rule.
fix('B2_10', 4, 1, question='The director got the actors ___ (rehearse) the scene five times before filming.',
    correct_answer='to rehearse', alternatives=[],
    explanation='После get + человек идёт инфинитив С to: got the actors to rehearse. Голая форма без to '
                'нужна только после have (had the actors rehearse). Перевод: Режиссёр добился, чтобы актёры '
                'отрепетировали сцену пять раз перед съёмкой.')
# B2_10 8#1: "have sb do" (поручить) and "get sb to do" (уговорить) are not identical in meaning;
# the statement is restated so that it tests the grammar it was written to test.
fix('B2_10', 8, 1,
    statement='В конструкции «have + person» после человека идёт голая форма глагола, а в «get + person» — '
              'инфинитив с to.',
    explanation='Верно. Have the actors rehearse, но get the actors to rehearse. По смыслу они тоже не '
                'совпадают полностью: have — поручить, get — уговорить, добиться.')

if __name__ == '__main__':
    sys.exit(main())
