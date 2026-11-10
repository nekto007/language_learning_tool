#!/usr/bin/env python3
# ruff: noqa: RUF001  # Intentional bilingual Russian/English teaching text.
"""Complete missing curriculum explanations from task evidence and grammar rules.

The source corpus is local. This deterministic editor changes only explanation
fields in three quiz formats, plus one explicitly identified broken final-test
answer. Existing nonempty explanations and standalone translation lessons stay
unchanged. Parent-owned modules are proposals only unless explicitly requested.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT_FILES = {
    'module_A1_1_greetings.json',
    'module_B2_1_lifestyle_and_psychology.json',
    'module_C1_9_academic_english.json',
}
TARGET_TYPES = {'dialogue_completion_quiz', 'listening_quiz', 'translation_quiz'}


def text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def norm(value):
    return text(value).lower().replace('’', "'")


def vocabulary(module):
    result = []
    for lesson in module.get('lessons', []):
        if lesson.get('type') == 'vocabulary':
            for item in lesson.get('content', {}).get('vocabulary', []):
                english, russian = text(item.get('english')), text(item.get('russian'))
                if english and russian:
                    result.append((english, russian))
    return sorted(result, key=lambda item: (-len(item[0].split()), -len(item[0])))


def lexical_notes(module, answer, *, maximum=2):
    result = []
    value = norm(answer)
    for english, russian in vocabulary(module):
        if re.search(r"(?<![\w'])" + re.escape(norm(english)) + (r'(?:s|es)?' if ' ' not in english else '') + r"(?![\w'])", value):
            result.append(f'«{english}» здесь означает «{russian}».')
            if len(result) >= maximum:
                break
    return ' '.join(result)


def grammar_note(answer, module):
    """Select only a rule with evidence in the actual answer, never module title alone."""
    a = norm(answer)
    replacements = {"i've": 'i have', "we've": 'we have', "they've": 'they have',
                    "you've": 'you have', "hasn't": 'has not', "haven't": 'have not',
                    "hadn't": 'had not', "wouldn't": 'would not', "won't": 'will not',
                    "i'll": 'i will', "we'll": 'we will', "they'll": 'they will',
                    "he'll": 'he will', "she'll": 'she will', "it's": 'it is', "that's": 'that is'}
    for short, full in replacements.items():
        a = re.sub(r'(?<!\w)' + re.escape(short) + r'(?!\w)', full, a)
    level, number = module.get('level'), module.get('order')
    topic = (level, number)
    past_perfect = r'had(?: not)? (?:been|known|seen|done|left|taken|made|gone|come|[a-z]+ed)'
    rules = [
        (r'\b(?:not sure|know|wonder|wondering|remember)\b.*\b(?:if|whether)\b',
         'После выражения сомнения или знания if/whether вводит содержание косвенного вопроса («ли»), а не условие. Дальше используется прямой порядок подлежащее → сказуемое.'),

        (r'\b(?:am|is|are) going to\b',
         'Be going to + начальная форма выражает намерение или прогноз по имеющимся признакам. Am/is/are выбирается по подлежащему; это не обычный процесс be + V-ing.'),

        (r'\b(?:i suggest|i recommend|strongly recommend|essential|vital|necessary|important|insist|demand|require)\b.*\bthat\b' if topic == ('C1', 13) else r'(?!)',
         'После требования или рекомендации с that возможен mandative subjunctive: начальная форма глагола для всех лиц, в том числе be вместо is/are. Вариант с should также употребляется в британском английском.'),
        (r'\b(?:had|get|got|have|has)\b.*\b(?:fixed|repaired|checked|cleaned|broken into|serviced|installed|painted|cut|stolen|replaced)\b' if topic == ('B2', 10) else r'(?!)',
         'Модель have/get + объект + V3 показывает действие над объектом, выполненное другим человеком или случившееся с ним. Это не обычное have + V3 без объекта.'),
        (r'^yes,? (?:i|you|we|they) (?:do|have)\.?$|^yes,? (?:he|she|it) (?:does|has)\.?$',
         'В кратком ответе повторяется вспомогательный глагол вопроса, согласованный с подлежащим: do/does либо have/has. Нельзя заменять его на be, если вопрос был с другим глаголом.'),
        (r'^yes,? please[.!]?$|^yes,? of course|^of course\.?$',
         'Yes, please вежливо принимает предложение или соглашается на помощь. Please относится к просьбе; thank you выражает благодарность.'),
        (r'^yes,? (?:it|he|she) (?:is|was)\.?$|^yes,? (?:we|they|you) (?:are|were)\.?$',
         'В кратком ответе на вопрос с be сохраняется подходящая форма be. Утвердительный краткий ответ не заканчивается сокращением вроде it’s.'),
        (r'^i (?:completely |totally |fully )?agree|^absolutely|^i think so',
         'Реплика выражает согласие с предыдущей мыслью. В I think so слово so заменяет уже высказанное содержание, чтобы не повторять целое предложение.'),
        (r'^that is (?:very )?concerning',
         'That отсылает к только что описанной ситуации; concerning оценивает её как вызывающую тревогу. Это реакция на проблему, а не сообщение о новом факте.'),
        (r'^let me check',
         'Let me + начальная форма — предложение самому выполнить действие. Check означает проверить сведения; реплика не утверждает результат до проверки.'),
        (r"^let(?:’|')s\b",
         'Let’s + начальная форма предлагает совместное действие. После let’s не ставятся to или окончание -s у смыслового глагола.'),
        (r'\benough\b',
         'Enough перед существительным обозначает достаточное количество (enough time), а после прилагательного — достаточную степень качества (big enough). Порядок слов различается.'),
        (r'\bsome\b' if level in ('A1', 'A2') else r'(?!)',
         'Some обозначает неопределённое количество исчисляемых предметов во множественном числе или неисчисляемого вещества. Some также естественно в предложении угощения или просьбе, где ожидается согласие.'),
        (r'\b(?:he|she|my father|my brother|my sister|tom|mary|the rabbit) (?:always |usually |often )?(?:goes|watches|studies|works|gets|brushes|lives|dresses|likes|has)\b',
         'В утвердительном Present Simple с he/she/it или одним названным человеком глагол получает -s/-es; после согласной + y пишется -ies: studies. Вопрос или отрицание с does требует начальной формы.'),
        (r'\b(?:i|we|they|you) (?:usually |always |often )?(?:live|stay|rest|eat|go|watch|need|have|prefer)\b' if level in ('A1', 'A2', 'B1') else r'(?!)',
         'При описании привычки или постоянного положения используется Present Simple. С I/you/we/they смысловой глагол стоит в начальной форме; -s появляется с he/she/it.'),
        (r'^it is (?:raining|snowing)|^it is (?:on|under|above|below)|^it is \w+ (?:dollars|euros)',
         'В описании погоды, положения или цены используется подлежащее it и согласованная форма is. Для происходящего сейчас дождя или снега после is нужна -ing-форма.'),
        (r'\b(?:who|which|that)\b' if topic in {('B1', 10), ('B2', 4)} else r'(?!)',
         'Относительная часть поясняет существительное: who относится к людям, which — к предметам, that возможно в определительном придаточном. Дополнительная non-defining часть выделяется запятыми и не вводится that.'),
        (r'^\w+ing\b|^(?:discovered|painted|written|built|known)\b' if topic == ('B2', 12) else r'(?!)',
         'Причастный оборот заменяет более длинное придаточное: -ing обычно обозначает активное действие, V3 — пассивное значение. Подразумеваемый исполнитель должен соотноситься с подлежащим основной части.'),
        (r'\b(?:was|were|celebrated|received|enjoyed|decorated)\b' if topic == ('A2', 22) else r'(?!)',
         'Завершённое событие в прошлом передаётся Past Simple. У правильного глагола добавляется -ed; yesterday, last … и … ago указывают на законченный прошлый период.'),
        (r'\bif\b' if topic == ('A2', 20) else r'(?!)',
         'Для общей закономерности используется Zero Conditional: if + Present Simple, Present Simple. В части результата не нужен will, если речь не о разовом будущем событии.'),
        (r'\b(?:so|such)\b' if topic == ('A2', 19) else r'(?!)',
         'So усиливает прилагательное или наречие, а such — группу с существительным. Перед исчисляемым существительным в единственном числе используется such a/an … .'),

        (r'\b(?:can|could|would) you (?:tell|explain)|\b(?:do you know|i wonder|i was wondering)\b',
         'Во встроенном вопросе после вопросительного слова сохраняется порядок подлежащее → сказуемое; дополнительная инверсия с do/does/did не нужна.'),
        (r'\b(?:asked|wondered)\b.*\b(?:if|whether)\b',
         'Косвенный общий вопрос вводится if/whether; дальше идёт прямой порядок слов, без вопросительной инверсии.'),
        (r'\b(?:asked|wondered)\b.*\b(?:what|where|when|why|how|who)\b',
         'В косвенном специальном вопросе сохраняется вопросительное слово, но далее идёт порядок подлежащее → сказуемое.'),
        (rf'\bif\b.*\b{past_perfect}\b.*\bwould(?: not)? have\b|\bwould(?: not)? have\b.*\bif\b.*\b{past_perfect}\b',
         'Нереальное условие в прошлом: if + Past Perfect; нереализованный результат — would have + V3 (Third Conditional).'),
        (rf'\bif\b.*\b{past_perfect}\b.*\bwould\b|\bwould\b.*\bif\b.*\b{past_perfect}\b',
         'Здесь прошлое условие передаётся через if + had + V3, а результат с would относится к другому временному плану: это смешанное условие.'),
        (r'\bif\b.*\bwould\b|\bwould\b.*\bif\b',
         'Для гипотетического условия используется if + Past Simple, а для результата — would + начальная форма глагола. Would обычно не ставится в самой if-части.'),
        (r'^had\s+\w+\s+(?:known|been|seen|realised|realized|done|prepared|studied|trained|taken|acted|received|left|understood|invested)',
         'Условную часть if + had + V3 можно передать без if: had ставится перед подлежащим. В основной части сохраняется would have + V3 или форма смешанного результата.'),
        (r'^were\b.*\b(?:to|would)|^should\s+\w+\b' if topic == ('C1', 11) else r'(?!)',
         'В формальной условной конструкции if можно опустить, поставив were/should перед подлежащим; это условие, а не обычный вопрос.'),
        (r'\bif\b.*\bwill\b|\bwill\b.*\bif\b',
         'Реальное условие будущего: после if используется Present Simple, а в части результата — will + начальная форма глагола.'),
        (r'^not only\b',
         'После вынесенного в начало Not only используется инверсия: вспомогательный глагол → подлежащее → смысловой глагол. Продолжение оформляется через but (also).'),
        (r'^(?:never|rarely|seldom|hardly|barely|scarcely|no sooner|under no circumstances|in no way|at no time)\b',
         'Отрицательное или ограничительное выражение в начале требует инверсии: вспомогательный глагол ставится перед подлежащим. При hardly/scarcely обычно следует when, при no sooner — than.'),
        (r'^only (?:by|through|with|when|after|then|if|in this way)\b',
         'После ограничительного Only + обстоятельство в начале предложения инверсия появляется в основной части: вспомогательный глагол → подлежащее.'),
        (r'\bshould(?:n\'t| not)? have\b',
         'Should have + V3 оценивает прошлое: действие стоило совершить; shouldn’t have + V3 — его не стоило совершать. Это не совет о будущем.'),
        (r'\b(?:must|might|may|could|can\'t|cannot) have\b',
         'Модальный глагол + have + V3 относится к прошлому: must выражает уверенный вывод, may/might/could — возможность, can’t/cannot — вывод о невозможности.'),
        (r'\b(?:is|was)\b.+\b(?:who|that)\b' if topic == ('C1', 4) else r'(?!)',
         'Расщеплённая конструкция It is/was … who/that … выделяет один элемент: время, участника или причину. Остальная часть сообщает, что с ним связано.'),
        (r'^what\b.+\b(?:is|was)\b' if topic == ('C1', 4) else r'(?!)',
         'Конструкция What … is/was … выносит в конец главную новую информацию; what-часть обозначает то, что поясняется или выделяется.'),
        (r'^the (?:more|less|fewer|better|harder|longer|earlier|higher|faster|greater|stronger|richer)\b',
         'Парная модель the + сравнительная степень …, the + сравнительная степень … показывает связанное изменение: «чем …, тем …».'),
        (r'\b(?:has|have)(?: not)? been \w+ing\b',
         'Have/has been + V-ing подчёркивает длительность процесса, начавшегося раньше и связанного с настоящим; после been нужна именно -ing-форма.'),
        (r'\bhad been \w+ing\b',
         'Had been + V-ing показывает процесс, который длился до другого момента в прошлом. Длительность и более поздняя точка отсчёта различаются.'),
        (r'\bwill(?: not)? be \w+ing\b',
         'Will be + V-ing описывает процесс в определённый момент будущего. После will используется be, а смысловой глагол принимает -ing.'),
        (r'\b(?:am|is|are|was|were)(?: not)? \w+ing\b',
         'Форма be + V-ing описывает процесс: am/is/are — в настоящем, was/were — в прошлом. Be согласуется с подлежащим; -ing не заменяет вспомогательный глагол.'),
        (r'\b(?:has|have) been\b' if topic == ('C1', 3) else r'(?!)',
         'В Present Perfect Passive используется have/has been + V3: важен достигнутый результат над объектом, а не исполнитель действия.'),
        (r'\b(?:was|were)\b' if topic == ('B2', 9) else r'(?!)',
         'В Past Simple Passive используется was/were + V3. Was/were согласуется с подлежащим, а V3 обозначает действие над ним.'),
        (r'\b(?:am|is|are)\b' if topic == ('B1', 12) else r'(?!)',
         'В Present Simple Passive используется am/is/are + V3. Подлежащее получает действие; исполнитель при необходимости вводится через by.'),
        (r'\bhad\b' if topic in {('B1', 17), ('B2', 11)} else r'(?!)',
         'Had + V3 обозначает действие, которое произошло раньше другой ситуации в прошлом. В вопросе had ставится перед подлежащим, в отрицании после него добавляется not.'),
        (r'\b(?:has|have)\b' if topic in {('B1', 14), ('B1', 15)} else r'(?!)',
         'В Present Perfect используется have/has + V3. For обозначает длительность периода, since — его начальную точку; при рассказе об опыте важен результат к настоящему.'),
        (r'\b(?:didn\'t|did not|did you|did he|did she|did they|did we)\b',
         'В вопросе и отрицании Past Simple время выражает did/didn’t, поэтому следующий смысловой глагол используется в начальной форме, без -ed и без формы V2.'),
        (r'\bused to\b' if topic == ('B1', 3) else r'(?!)',
         'Used to + начальная форма описывает прошлую привычку или состояние, которое теперь изменилось. После did/didn’t используется use to, без -d.'),
        (r'\b(?:mustn\'t|must not)\b',
         'Mustn’t + начальная форма означает запрет: действие делать нельзя. Это не то же самое, что don’t have to — отсутствие необходимости.'),
        (r'\b(?:don\'t|doesn\'t|do not|does not) have to\b',
         'Don’t/doesn’t have to означает «не обязательно», а не запрет. После doesn’t глагол have остаётся без окончания -s.'),
        (r'\bhad better\b',
         'Had better + начальная форма — настойчивый совет с подразумеваемыми последствиями; to перед смысловым глаголом не ставится.'),
        (r'\b(?:should|shouldn\'t|ought to)\b',
         'Should/shouldn’t + начальная форма дают совет. У should нет окончания -s; ought употребляется с to.'),
        (r'\b(?:have to|has to|had to)\b',
         'Have to передаёт необходимость. В настоящем с he/she/it используется has to; после did/didn’t возвращается have to.'),
        (r'\bmust\b',
         'После must используется начальная форма без to. В контексте обязанности must подчёркивает требование, а не просто полезный совет.'),
        (r'\b(?:might|may|could)\b' if topic == ('B2', 2) else r'(?!)',
         'May/might/could + начальная форма выражают возможность, а не установленный факт. В отрицании важно различать «может не» и «не может».'),
        (r'\bwould (?:like|love)\b',
         'Would like — вежливое желание или предложение. Перед существительным to не нужно; перед действием используется would like to + глагол.'),
        (r'\b(?:can|can\'t|cannot)\b',
         'После can/can’t используется начальная форма без to; форма can не меняется с he/she/it. В вопросе can ставится перед подлежащим.'),
        (r'\b(?:am|is|are) going to\b',
         'Be going to + начальная форма выражает намерение или прогноз по имеющимся признакам. Am/is/are выбирается по подлежащему.'),
        (r'\bwill\b',
         'Will + начальная форма передаёт будущее. В вопросе will ставится перед подлежащим; после will не нужны to и окончание -s.'),
        (r'\b(?:don\'t|doesn\'t|do not|does not)\b',
         'В отрицании Present Simple используется do/does + not. После doesn’t смысловой глагол остаётся в начальной форме, без -s.'),
        (r'^(?:do|does)\b',
         'Вопрос Present Simple строится через Do/Does + подлежащее + начальную форму глагола. С he/she/it выбирается does; -s у смыслового глагола снимается.'),
        (r'\bthere (?:is|are|isn\'t|aren\'t)\b',
         'There is используется для одного предмета или неисчисляемого существительного; there are — для множественного числа. Конструкция сообщает о наличии.'),
        (r'\b(?:too much|too many|how much|how many)\b',
         'Much сочетается с неисчисляемыми существительными, many — с исчисляемыми во множественном числе; выбор зависит от существительного, а не русского слова «много».'),
        (r'\b(?:fewer|less)\b',
         'Fewer относится к исчисляемым предметам во множественном числе, less — к неисчисляемому количеству. Это сравнительные формы «меньше».'),
        (r'\b(?:little|few)\b',
         'Few относится к исчисляемым предметам, little — к неисчисляемому количеству. Артикль a меняет оттенок: a few/a little — «немного есть», few/little — «почти нет».'),
        (r'\bas [a-z-]+ as\b',
         'Модель as + прилагательное/наречие + as выражает равенство по признаку. Для неравенства перед первой частью ставится not.'),
        (r'\b(?:more|less) [a-z-]+ than\b|\b[a-z]+er than\b',
         'При сравнении двух объектов используется сравнительная степень и than. Не нужно одновременно добавлять more и окончание -er к одному прилагательному.'),
        (r'\bthe (?:most|least)\b|\bthe [a-z]+est\b',
         'Превосходная степень выделяет объект среди группы; обычно перед ней используется the. Форма строится с -est либо most/least, без двойного усиления.'),
        (r'\b(?:myself|yourself|himself|herself|itself|ourselves|yourselves|themselves)\b',
         'Возвратное местоимение показывает совпадение действующего лица и объекта либо подчёркивает «сам». Оно должно соответствовать подлежащему по лицу и числу.'),
        (r'\b(?:this|that)\b.*\bis\b|\b(?:these|those)\b.*\bare\b' if level == 'A1' else r'(?!)',
         'This/that относятся к одному предмету и сочетаются с is; these/those — к нескольким и сочетаются с are. This/these указывают на близость, that/those — на удалённость.'),
        (r'\b(?:i am|i\'m|you are|you\'re|he is|he\'s|she is|she\'s|we are|we\'re|they are|they\'re)\b',
         'В предложении с be форма согласуется с подлежащим: I am, he/she/it is, you/we/they are. В английском связку в таком предложении не опускают.'),
    ]
    for pattern, explanation in rules:
        if re.search(pattern, a):
            return explanation
    if topic in {('B1', 1), ('A2', 23)}:
        irregular = {'went': 'go', 'saw': 'see', 'told': 'tell', 'thought': 'think',
                     'came': 'come', 'ate': 'eat', 'ran': 'run', 'bought': 'buy',
                     'found': 'find', 'gave': 'give', 'took': 'take', 'made': 'make',
                     'wrote': 'write', 'spoke': 'speak', 'drank': 'drink', 'brought': 'bring',
                     'got': 'get', 'felt': 'feel', 'met': 'meet', 'left': 'leave',
                     'had': 'have', 'was': 'be', 'were': 'be', 'did': 'do', 'knew': 'know',
                     'swam': 'swim', 'flew': 'fly', 'drove': 'drive', 'slept': 'sleep',
                     'read': 'read', 'broke': 'break', 'won': 'win', 'heard': 'hear', 'lost': 'lose'}
        for past, base in irregular.items():
            if re.search(r'(?<!\w)' + past + r'(?!\w)', a):
                return f'«{past}» — форма Past Simple глагола «{base}». Для неправильного глагола форму прошлого нужно знать отдельно; в вопросе и отрицании с did используется {base}.'
    if topic == ('A1', 13) and re.match(r"(?:don't\s+)?[a-z]+\b", a):
        return 'Инструкция начинается с начальной формы глагола, обычно без you. Запрет строится через Don’t + начальную форму, а совместное предложение — через Let’s.'
    return ''


def dialogue_note(exercise):
    lines = exercise.get('dialogue') or []
    turns = [text(row.get('text')) for row in lines if isinstance(row, dict) and row.get('text') != '___']
    previous = norm(turns[-1]) if turns else ''
    patterns = [
        (r'what(?:\'s| is) your name', 'Вопрос просит назвать имя; ответ должен представлять человека через My name is … или I’m …, а не сообщать настроение или место.'),
        (r'how are you', 'Это вопрос о самочувствии, поэтому ответ сообщает состояние и может содержать благодарность; имя или страна на этот вопрос не отвечают.'),
        (r'where are you from', 'Вопрос from спрашивает о происхождении; ответ I’m from … называет страну или город, а не профессию или настроение.'),
        (r'how long', 'How long спрашивает о длительности. Ответ должен обозначать период с for или начальную точку с since, а не частоту или место.'),
        (r'how often', 'How often спрашивает о частоте; подходящий ответ указывает, как регулярно происходит действие, а не сколько оно длится.'),
        (r'^why\b', 'Why требует причины. В ответе она может вводиться because; сведения только о месте или времени не объясняют причину.'),
        (r'^when\b|what time', 'Вопрос просит время действия; ответ должен называть момент или период и сохранять подходящий временной план.'),
        (r'thank', 'После благодарности уместна ответная вежливая реплика, например You’re welcome; повторная просьба или сообщение об имени меняет смысл обмена.'),
        (r'what.*think|what.*opinion', 'Собеседник просит высказать мнение: реплика должна содержать оценку или позицию, а не отвечать на вопрос о факте yes/no.'),
    ]
    for pattern, explanation in patterns:
        if re.search(pattern, previous):
            return explanation
    return ''


def curated_note(answer, question=''):
    a = norm(answer)
    exact = {
        'she wakes up at seven.': 'Wakes up — «просыпается»; at seven называет время. Окончание -s согласует Present Simple с she.',
        'greens and protein': 'Greens обозначает зелень, protein — белок. Союз and объединяет две составляющие еды, а не предлагает выбор между ними.',
        'at 7 pm': 'At вводит точное время. PM означает после полудня: 7 PM — 19:00, в отличие от 7 AM — 07:00.',
        'at 9 pm': 'At вводит время трансляции; 9 PM — 21:00. Не путайте PM с AM, обозначающим утро.',
        'next monday': 'Next Monday — ближайший предстоящий понедельник. Last Monday относится к прошлому; this Monday зависит от текущей недели.',
        '20 degrees': 'Degrees здесь обозначает градусы температуры; число 20 сообщает её величину, а не скорость ветра или количество осадков.',
        'last night': 'Last night — прошлая ночь или вчерашний вечер: это законченный прошлый период. Tonight относится к сегодняшнему вечеру/ночи.',
        '8 hours': 'Hours обозначает длительность в часах. Эта фраза отвечает на вопрос о продолжительности сна, а не о времени отхода ко сну.',
        'in a village': 'Village — деревня, city — город. Предлог in обозначает место проживания; ответ выбирает именно деревенскую среду.',
        'they were amazed': 'Amazed описывает чувство людей, amazing — то, что вызывает удивление. Were согласуется с they и относит реакцию к прошлому.',
        'more ingredients': 'More означает дополнительное количество, ingredients — составляющие рецепта. Это запрос ещё продуктов, а не изменение времени приготовления.',
        'until 11 am': 'Until указывает конечную границу действия: завтрак подают до 11 утра. AM отличает это время от 23:00.',
        'his old one is broken': 'One заменяет уже названный предмет, а broken сообщает, что он неисправен. Поэтому речь о замене старого устройства, а не о покупке второго рабочего.',
        'reading and watching videos': 'Reading и watching — две -ing-формы, соединённые and; они перечисляют виды использования устройства, а не его технические характеристики.',
        'to fix bugs': 'To + начальная форма выражает цель: fix bugs — устранить ошибки программы. Это причина обновления, а не его побочный результат.',
        'our flight leaves at 9 am': 'Leaves в Present Simple может описывать расписание. 9 AM — девять утра; at вводит точное время отправления.',
        'your passport': 'Passport — документ для удостоверения личности при международной поездке. Your указывает на документ собеседника, а не другого человека.',
        'zero': 'Zero Conditional передаёт общую закономерность: Present Simple используется и в if-части, и в результате. Это не гипотетическое условие с would.',
        'стоить очень дорого': 'Cost an arm and a leg — идиома о высокой цене. Названия частей тела здесь не переводятся буквально.',
        'едва-едва, чудом': 'By the skin of one’s teeth означает добиться результата с минимальным запасом, едва избежать неудачи. Это не уверенная победа с большим преимуществом.',
        'his sister': 'His sister — «его сестра». His обозначает принадлежность, sister — конкретного члена семьи; brother означало бы брата.',
        'as...as (equality)': 'As + прилагательное/наречие + as выражает равенство по признаку. More … than обозначает превосходство, а не равенство.',
        'заботиться': 'Look after — неразделяемый фразовый глагол со значением «присматривать, заботиться». Объект следует после after.',
        'потому что местоимение всегда между глаголом и частицей': 'В разделяемом turn on местоимение ставится между глаголом и частицей: turn it on. С существительным возможны turn on the light и turn the light on.',
        'сломалось': 'Break down применительно к машине означает выйти из строя. Broke — прошедшая форма break; буквальное «разбить вниз» здесь не передаёт значение.',
        'придумать': 'Come up with означает предложить или придумать идею. Выражение рассматривается как единое целое; объект идёт после with.',
        'дорого': 'Expensive описывает высокую цену. Very усиливает признак; cheap, напротив, означает низкую цену.',
        'confirmed her reservation.': 'Confirm a reservation — подтвердить уже сделанное бронирование, а не отменить его или впервые забронировать номер. Confirmed указывает на завершённое действие.',
        'rising temperatures.': 'Rising означает рост: temperatures повышаются. Falling temperatures означало бы противоположную тенденцию — снижение.',
        'habitat destruction.': 'Habitat — естественная среда обитания; destruction — её разрушение. Угроза связана с потерей места жизни вида, а не с его охраной.',
        'solar energy': 'Solar означает связанный с Солнцем. Wind energy — энергия ветра, hydroelectric — энергия воды; источник энергии в этих сочетаниях различается.',
        'plastic waste': 'Plastic waste — пластиковые отходы. Waste здесь существительное «отходы», а не глагол «тратить впустую».',
        'reduce carbon footprint.': 'Reduce — уменьшить, carbon footprint — углеродный след. Реплика называет сокращение воздействия, а не рост выбросов.',
        'струсила в последний момент': 'Get cold feet — внезапно испугаться и начать отказываться от решения перед важным действием. Идиома не связана с температурой ног.',
        'he was tired': 'Was tired передаёт состояние мужчины в прошлом. Tired описывает уставшего человека, tiring — то, что утомляет.',
        'might': 'Might в результате условного предложения означает возможность: результат мог бы наступить, но не обещается как обязательный. Would выражает более прямую гипотетическую связь.',
        'gerund (v-ing)': 'После enjoy используется герундий, то есть V-ing: enjoy working. Конструкция enjoy to work в этом значении не употребляется.',
        'потому что «to» здесь — предлог, а не часть инфинитива': 'В look forward to слово to — предлог; после него используется существительное или V-ing: look forward to hearing. Это отличается от want to hear, где to вводит инфинитив.',
        'focusing on the development of research skills.': 'Focus on означает сосредоточиться на чём-либо; development of research skills уточняет объект внимания — развитие исследовательских навыков.',
        'end of the month.': 'End of the month указывает конец месяца как срок. Beginning of the month означало бы его начало, а не ту же дату.',
        'understanding nominalization in academic writing.': 'Nominalization — преобразование действия или качества в существительное. Реплика называет именно эту трудность письма, а не общую проблему с произношением.',
        'everyone to remain seated.': 'Remain seated означает оставаться сидя. Everyone охватывает всех присутствующих; требование не ограничено одним свидетелем или адвокатом.',
        'hiring a lawyer.': 'Hire a lawyer — привлечь адвоката для представительства. Hiring называет рекомендуемое действие, а не уже вынесенное решение суда.',
        'informal/colloquial': 'Pull strings — разговорное выражение об использовании связей для получения преимущества. В нейтральном официальном тексте обычно точнее описать конкретное влияние без этой идиомы.',
        'a new sustainable collection.': 'New collection — новая коллекция, sustainable уточняет её экологический подход. Это сообщение об объявленной коллекции, а не о закрытии бренда.',
        'ethical and sustainable practices.': 'Ethical and sustainable характеризуют практики как этичные и устойчивые. And объединяет два критерия; речь не только о коммерческой успешности.',
        'good communication.': 'Communication — обмен информацией и взаимопонимание. Good communication относится к взаимодействию команды, а не к индивидуальному стажу или заработку.',
        'political scandal.': 'Political scandal — скандал в политической сфере. Political уточняет область события, отличая её, например, от спортивной новости.',
        'the allegations.': 'Allegations — обвинения или утверждения о нарушении, которые ещё требуют проверки. Deny the allegations означает их отрицать, а не признавать.',
        'the scene of the event.': 'Scene of the event — место происшествия. Предлог from в вопросе о репортаже указывает, откуда ведётся включение, а не куда едет корреспондент.',
        'government policy.': 'Government policy — политика правительства, то есть принятый курс или меры. Здесь policy не означает страховой полис.',
        'diversify your investments.': 'Diversify означает распределять вложения между разными активами. В реплике назван именно этот подход; это не обещание отсутствия риска или гарантированной прибыли.',
        'not buying property earlier.': 'Not buying … называет действие, которое не было сделано и теперь вызывает сожаление. Earlier относит желаемую покупку к более раннему времени.',
        'interest calculated on principal and accumulated interest.': 'При compound interest база расчёта включает исходную сумму и уже накопленные проценты. Этим термин отличается от simple interest, начисляемого только на исходную сумму.',
        'it was lowered': 'Was lowered — прошедший пассив: ставку понизили. Raised означало бы обратное изменение — повышение.',
        'research and understand the investment.': 'Research и understand называют два предварительных действия: изучить сведения и разобраться в объекте вложения. Это отличается от немедленного решения без анализа.',
        'я учитель': 'I am a teacher сообщает профессию: I — «я», am — связка для I, a teacher — «учитель». Не путайте teacher и student.',
        'как дела?': 'How are you? спрашивает о самочувствии. Вопрос о происхождении звучит Where are you from?, а об имени — What is your name?',
        'are': 'Подлежащее we требует формы are: we are happy. Am используется с I, is — с he/she/it.',
        'these': 'These указывает на несколько близких предметов. This относится к одному близкому предмету, those — к нескольким удалённым.',
        'brunch': 'Brunch — поздний завтрак, объединённый с обедом (breakfast + lunch); dinner обозначает другой приём пищи.',
        'minerals': 'Minerals — «минеральные вещества». Это название группы питательных веществ, а не отдельного приёма пищи или блюда.',
        'climate': 'Climate — типичные погодные условия региона за длительный период; weather — погода в конкретное время.',
        'conservation': 'Conservation в экологическом контексте означает охрану и сохранение природы, а не загрязнение или расходование ресурсов.',
        'biosphere': 'Biosphere — биосфера, область распространения жизни. Это понятие шире отдельного места обитания или вида животных.',
        'coffee': 'Coffee — кофе; tea — чай. Эти слова называют разные напитки, поэтому замена одного другим меняет заказ.',
        'two': 'Two обозначает количество «два». В контексте заказа места for two речь идёт о столике на двоих, а не о времени или цене.',
        'tech2025': 'Пароль — точная последовательность букв и цифр: tech + 2025. Здесь нужно сохранить указанные символы, а не перевести слово или заменить число.',
        'quickly': 'Quickly — наречие «быстро»: оно отвечает на how и характеризует действие. Quick — прилагательное для характеристики предмета или человека.',
        'breakthrough': 'Breakthrough — значительный прорыв или достижение после трудностей; это результат продвижения, а не сама длительная тренировка.',
        'teamwork': 'Teamwork означает совместную работу команды; leadership обозначает руководство, negotiation — переговоры. Эти понятия не взаимозаменяемы.',
        'migration': 'Migration — перемещение людей или животных между местами; diversity обозначает разнообразие, а не само перемещение.',
        'investment': 'Investment — вложение средств ради будущей отдачи; stock — акция, dividend — выплата по ней, portfolio — набор активов.',
        'guilty': 'Guilty в вердикте означает «виновен». Not guilty — «невиновен»; наличие или отсутствие not полностью меняет результат.',
        'by card, please.': 'By card называет способ оплаты картой; cash означает наличные. В этой реплике by показывает способ, а please делает ответ вежливым.',
        'at carousel 3.': 'Carousel в аэропорту — лента выдачи багажа. At указывает конкретное место: лента №3, а не стойка регистрации или выход на посадку.',
        'it went very well, thanks!': 'Went — прошедшая форма go; go well здесь означает «пройти успешно». Реплика оценивает уже состоявшееся событие, а не будущий план.',
        'we get along very well.': 'Get along означает «ладить, поддерживать хорошие отношения». Very well характеризует отношения, а не физическое движение.',
        'go past the bank.': 'Go past означает пройти мимо ориентира; across — пересечь, into — войти внутрь. Здесь банк служит ориентиром на пути.',
    }
    if a in exact:
        return exact[a]
    patterns = [
        (r'have.*got|has.*got', 'Have/has got выражает обладание. В вопросе have/has ставится перед подлежащим; в кратком ответе сохраняется have/has, без got.'),
        (r'below zero', 'Below zero означает температуру ниже нуля. Degrees называет градусы; ниже нуля отличается от просто прохладной погоды.'),
        (r'thunder|lightning', 'Thunder — звук грома, lightning — вспышка молнии. Поэтому гром обычно hear, а молнию see; это разные признаки грозы.'),
        (r'climate.*humid', 'Humid характеризует влажный воздух и климат; wet может описывать мокрую поверхность. Here указывает на условия именно в данном месте.'),
        (r'conservation|natural resources', 'В экологическом контексте conservation — сохранение, resources — природные ресурсы. Limited означает ограниченность их количества, а не возможность бесконечного использования.'),
        (r'disappointed', 'Disappointed описывает чувство человека, disappointing — то, что вызывает разочарование. They were disappointed with … связывает чувство с его причиной.'),
        (r'for learning languages', 'For + V-ing может обозначать назначение предмета: «для изучения языков». После for здесь не используется начальная форма без -ing.'),
        (r'too big', 'Too big означает «слишком большой», то есть больше нужного размера. A bit смягчает степень избытка, но не отменяет too.'),
        (r'please follow me', 'Please + начальная форма превращает инструкцию в вежливую просьбу. Follow me приглашает идти за говорящим, который показывает дорогу.'),
        (r'could i have', 'Could I have …? — вежливая просьба предоставить предмет или сведения. Could здесь смягчает просьбу, а не сообщает о прошлом умении.'),
        (r'when would you like', 'When спрашивает о времени, а would you like + to + глагол вежливо выясняет предпочтение. В этой реплике уточняются даты отправления и возвращения.'),
        (r'could work.*only if', 'Could обозначает возможность, а only if ограничивает её необходимым условием. Реплика допускает решение с оговоркой, а не обещает безусловный успех.'),
        (r'need to act', 'Need to + начальная форма выражает необходимость действия. Now делает её актуальной сейчас; это не сообщение о том, что действие уже выполнено.'),
        (r'completed.*last semester', 'Last semester указывает на законченный прошлый период, поэтому используется Past Simple completed. Present Perfect с таким завершённым временем здесь не подходит.'),
        (r'found.*guilty', 'Find someone guilty означает признать человека виновным. Found — прошедшая форма find; guilty относится к defendant, а не описывает поиски человека.'),
        (r"scheduled", 'Scheduled означает «запланирован, назначен по расписанию». Be scheduled сообщает статус события, а не утверждает, что оно уже состоялось.'),
        (r'at \$50,000', 'At перед суммой может указывать установленный размер, например залога. Реплика подтверждает назначенную сумму, а не способ оплаты.'),
        (r'crossed the rubicon', 'Cross the Rubicon — принять необратимое решение, «перейти Рубикон». Идиома обозначает точку невозврата, а не буквальное пересечение реки в этом контексте.'),
        (r"pandora's box", 'Open Pandora’s box — вызвать множество непредвиденных проблем. Образ подчёркивает последствия вмешательства, а не просто открытие документа.'),
        (r'threw down the gauntlet', 'Throw down the gauntlet означает бросить вызов сопернику или принятой позиции. Это формальная образная альтернатива прямому challenge.'),
        (r'raised the bar', 'Raise the bar — повысить стандарт качества или требования. Речь об уровне работы, а не о физическом перемещении предмета.'),
        (r'missed the mark', 'Miss the mark — не достичь нужной цели или не попасть в ожидания аудитории. Идиома может описывать неудачное сообщение, даже если оно технически выполнено.'),
        (r'spanner in the works', 'Throw a spanner in the works — сорвать или осложнить хорошо организованный процесс. Это британская идиома; американский вариант — throw a wrench in the works.'),
        (r'bet the farm', 'Bet the farm означает поставить на кон слишком многое. Отрицание wouldn’t показывает отказ рисковать всем ради одного прогноза.'),
        (r'^the thing that', 'The thing that … was … выделяет главный фактор. Относительная часть that helped me most уточняет, о каком факторе идёт речь.'),
        (r'the more.*the more', 'Парная модель the more …, the more … передаёт связанную зависимость «чем больше …, тем больше …». Оба the относятся к сравнительной конструкции.'),
        (r'low-risk investments.*steady returns', 'Low-risk характеризует меньший уровень риска, steady returns — относительно стабильную отдачу. Это описание предпочтения, а не обещание гарантированной прибыли.'),
    ]
    for pattern, explanation in patterns:
        if re.search(pattern, a):
            return explanation
    return ''


def propose_explanation(module, lesson, exercise):
    answer = text(exercise.get('correct') or exercise.get('answer') or exercise.get('correct_answer'))
    source = text(exercise.get('audio_text') or exercise.get('transcript'))
    kind = lesson.get('type')
    lexical = lexical_notes(module, answer)
    grammar = grammar_note(answer, module)
    curated = curated_note(answer, exercise.get('question'))
    if kind == 'dialogue_completion_quiz':
        speech = dialogue_note(exercise)
        if speech:
            return speech + (' ' + grammar if grammar else '')
        return ' '.join(part for part in (curated or grammar, lexical) if part)
    if kind == 'listening_quiz':
        question = norm(exercise.get('question'))
        analysis_task = bool(re.search(r'глагол|время|конструкц|форм[ауы]|выражает|означает|что значит|какой оттенок|which tense|which form', question))
        if analysis_task:
            rule = grammar_note(source or answer, module)
            if rule:
                return rule
        if source and len(source.split()) > 1:
            evidence = source if len(source) <= 210 else source[:207].rsplit(' ', 1)[0] + '…'
            note = curated or curated_note(source, exercise.get('question')) or lexical or grammar or grammar_note(source, module) or lexical_notes(module, source)
            return f'Опора в реплике: «{evidence}». {note}' if note else ''
        if lexical:
            other = next((text(value) for value in exercise.get('options', [])
                          if value != answer and lexical_notes(module, value, maximum=1)), '')
            contrast = lexical_notes(module, other, maximum=1) if other else ''
            return lexical + (' Для сравнения: ' + contrast if contrast else '')
        return curated or grammar_note(source or answer, module)
    return ' '.join(part for part in (curated or grammar, lexical) if part)


def repair_known_question(module):
    if (module.get('level'), module.get('order')) != ('B2', 4):
        return 0
    for lesson in module.get('lessons', []):
        if lesson.get('type') != 'final_test':
            continue
        for section in lesson.get('content', {}).get('test_sections', []):
            for exercise in section.get('exercises', []):
                question = exercise.get('question', '')
                if question.startswith('Преобразуйте утверждение в вопрос: Local culture shapes'):
                    corrected = 'Does local culture shape the way people celebrate important events?'
                    if exercise.get('correct') == corrected:
                        return 0
                    exercise['correct'] = corrected
                    exercise['acceptable_answers'] = [exercise['correct']]
                    exercise['explanation'] = 'Подлежащее local culture — единственное число: в вопросе Present Simple ставим Does перед ним, а shapes меняем на начальную форму shape. Вспомогательного be здесь нет.'
                    return 1
    return 0


def label_advanced_warmup(module):
    if module.get('level') not in ('B2', 'C1'):
        return 0
    changed = 0
    for lesson in module.get('lessons', []):
        if lesson.get('type') != 'listening_quiz':
            continue
        exercises = lesson.get('content', {}).get('exercises', [])
        if not any(len(text(item.get('audio_text')).split()) == 1 for item in exercises):
            continue
        title = lesson.get('title', '')
        if not title.startswith('Разминка на слух:'):
            lesson['title'] = 'Разминка на слух: ' + re.sub(r'^Аудирование:\s*', '', title)
            lesson['description'] = (
                'Короткая тренировка распознавания слов и языковых форм. '
                'Понимание связной речи проверяется отдельно в уроке с полным аудиодиалогом.'
            )
            changed += 1
    return changed


def process_module(module, *, apply=False):
    counts = Counter()
    proposals, unresolved = {}, []
    for lesson in module.get('lessons', []):
        if lesson.get('type') not in TARGET_TYPES:
            continue
        key = lesson.get('content', {}).get('external_key')
        for index, exercise in enumerate(lesson.get('content', {}).get('exercises', [])):
            counts[lesson['type'] + '_total'] += 1
            if text(exercise.get('explanation')):
                continue
            counts[lesson['type'] + '_missing'] += 1
            proposal = propose_explanation(module, lesson, exercise)
            if not proposal:
                unresolved.append({'external_key': key, 'index': index, 'exercise': exercise})
                continue
            proposals.setdefault(key, {})[str(index)] = proposal
            if apply:
                exercise['explanation'] = proposal
    return dict(counts), proposals, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=ROOT / 'module_completed/fixed')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--include-parent-files', action='store_true')
    parser.add_argument('--proposals', type=Path)
    args = parser.parse_args()
    counts, proposals, unresolved, changed = Counter(), {}, [], []
    for path in sorted(args.source_dir.glob('*.json')):
        data = json.loads(path.read_text())
        module = data['module']
        apply = args.apply and (args.include_parent_files or path.name not in PARENT_FILES)
        before = json.dumps(data, ensure_ascii=False)
        current, pending, missing = process_module(module, apply=apply)
        counts.update(current)
        proposals[path.name] = pending
        unresolved.extend({'file': path.name, **entry} for entry in missing)
        if apply:
            counts['known_question_repairs'] += repair_known_question(module)
            counts['warmups_labeled'] += label_advanced_warmup(module)
        if apply and json.dumps(data, ensure_ascii=False) != before:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
            changed.append(path.name)
    result = {'files': len(proposals), 'counts': dict(counts), 'changed': changed, 'unresolved': unresolved}
    if args.proposals:
        args.proposals.write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
