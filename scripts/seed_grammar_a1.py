#!/usr/bin/env python3
"""
Seed script for Grammar Lab A1 content.

Run with: python scripts/seed_grammar_a1.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.utils.db import db
from app.grammar_lab.models import GrammarTopic, GrammarExercise


# A1 Grammar Topics with full content
A1_TOPICS = [
    {
        "slug": "verb-to-be",
        "title": "Verb TO BE",
        "title_ru": "Глагол TO BE",
        "level": "A1",
        "order": 1,
        "estimated_time": 15,
        "difficulty": 1,
        "content": {
            "introduction": "Глагол TO BE (быть) — один из важнейших глаголов в английском языке. Он используется для описания состояний, характеристик и идентификации.",
            "sections": [
                {
                    "subtitle": "Формы глагола TO BE",
                    "description": "Глагол TO BE имеет три формы в настоящем времени:",
                    "table": [
                        {"pronoun": "I", "form": "am", "example": "I am a student.", "translation": "Я студент."},
                        {"pronoun": "You", "form": "are", "example": "You are smart.", "translation": "Ты умный."},
                        {"pronoun": "He/She/It", "form": "is", "example": "She is happy.", "translation": "Она счастлива."},
                        {"pronoun": "We", "form": "are", "example": "We are friends.", "translation": "Мы друзья."},
                        {"pronoun": "They", "form": "are", "example": "They are here.", "translation": "Они здесь."}
                    ]
                },
                {
                    "subtitle": "Сокращённые формы",
                    "description": "В разговорной речи часто используются сокращения:",
                    "table": [
                        {"full": "I am", "short": "I'm", "example": "I'm tired."},
                        {"full": "You are", "short": "You're", "example": "You're right."},
                        {"full": "He is", "short": "He's", "example": "He's my brother."},
                        {"full": "She is", "short": "She's", "example": "She's a doctor."},
                        {"full": "It is", "short": "It's", "example": "It's cold."},
                        {"full": "We are", "short": "We're", "example": "We're ready."},
                        {"full": "They are", "short": "They're", "example": "They're late."}
                    ]
                },
                {
                    "subtitle": "Отрицательные предложения",
                    "description": "Для отрицания добавляем NOT после глагола TO BE:",
                    "table": [
                        {"affirmative": "I am happy.", "negative": "I am not happy.", "short": "I'm not happy."},
                        {"affirmative": "You are late.", "negative": "You are not late.", "short": "You aren't late."},
                        {"affirmative": "He is here.", "negative": "He is not here.", "short": "He isn't here."}
                    ]
                },
                {
                    "subtitle": "Вопросительные предложения",
                    "description": "В вопросах глагол TO BE ставится перед подлежащим:",
                    "examples": [
                        {"question": "Am I right?", "translation": "Я прав?"},
                        {"question": "Are you ready?", "translation": "Ты готов?"},
                        {"question": "Is she a teacher?", "translation": "Она учитель?"},
                        {"question": "Are we late?", "translation": "Мы опоздали?"},
                        {"question": "Are they students?", "translation": "Они студенты?"}
                    ]
                }
            ],
            "important_notes": [
                "⚠️ Не путайте: I am (не I is!)",
                "💡 Сокращение I'm используется чаще, чем I am",
                "📝 В вопросах порядок слов меняется: Is he? Are you?"
            ],
            "common_mistakes": [
                {"wrong": "I is happy.", "correct": "I am happy.", "explanation": "С местоимением I всегда используется am"},
                {"wrong": "She are a doctor.", "correct": "She is a doctor.", "explanation": "С he/she/it используется is"},
                {"wrong": "They is here.", "correct": "They are here.", "explanation": "С they используется are"}
            ],
            "summary_table": {
                "affirmative": "Subject + am/is/are + ...",
                "negative": "Subject + am/is/are + not + ...",
                "question": "Am/Is/Are + subject + ...?"
            }
        },
        "exercises": [
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "I ___ a student.",
                    "correct_answer": "am",
                    "alternatives": ["'m"],
                    "explanation": "С местоимением I всегда используется am."
                },
                "difficulty": 1,
                "order": 1
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "She ___ from London.",
                    "correct_answer": "is",
                    "alternatives": ["'s"],
                    "explanation": "С местоимением she используется is."
                },
                "difficulty": 1,
                "order": 2
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "They ___ my friends.",
                    "correct_answer": "are",
                    "alternatives": ["'re"],
                    "explanation": "С местоимением they используется are."
                },
                "difficulty": 1,
                "order": 3
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "Какое предложение правильное?",
                    "options": [
                        "He are a teacher.",
                        "He is a teacher.",
                        "He am a teacher.",
                        "He be a teacher."
                    ],
                    "correct_answer": 1,
                    "explanation": "С местоимением he используется is."
                },
                "difficulty": 1,
                "order": 4
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "We ___ happy.",
                    "options": ["am", "is", "are", "be"],
                    "correct_answer": 2,
                    "explanation": "С местоимением we используется are."
                },
                "difficulty": 1,
                "order": 5
            },
            {
                "exercise_type": "error_correction",
                "content": {
                    "sentence": "You is very smart.",
                    "error_word": "is",
                    "correct_answer": "are",
                    "full_correct": "You are very smart.",
                    "explanation": "С местоимением you используется are."
                },
                "difficulty": 2,
                "order": 6
            },
            {
                "exercise_type": "transformation",
                "content": {
                    "instruction": "Сделайте предложение отрицательным",
                    "original": "She is a doctor.",
                    "correct_answer": "She is not a doctor.",
                    "alternatives": ["She isn't a doctor.", "She's not a doctor."],
                    "explanation": "Для отрицания добавляем not после is."
                },
                "difficulty": 2,
                "order": 7
            },
            {
                "exercise_type": "transformation",
                "content": {
                    "instruction": "Сделайте вопрос",
                    "original": "They are students.",
                    "correct_answer": "Are they students?",
                    "explanation": "В вопросе are ставится перед подлежащим."
                },
                "difficulty": 2,
                "order": 8
            },
            {
                "exercise_type": "translation",
                "content": {
                    "sentence": "Я счастлив.",
                    "source_lang": "ru",
                    "target_lang": "en",
                    "correct_answer": "I am happy.",
                    "alternatives": ["I'm happy."],
                    "key_grammar": "I + am"
                },
                "difficulty": 2,
                "order": 9
            },
            {
                "exercise_type": "translation",
                "content": {
                    "sentence": "Она не дома.",
                    "source_lang": "ru",
                    "target_lang": "en",
                    "correct_answer": "She is not at home.",
                    "alternatives": ["She isn't at home.", "She's not at home."],
                    "key_grammar": "She + is not"
                },
                "difficulty": 2,
                "order": 10
            }
        ]
    },
    {
        "slug": "articles",
        "title": "Articles",
        "title_ru": "Артикли a/an/the",
        "level": "A1",
        "order": 2,
        "estimated_time": 20,
        "difficulty": 1,
        "content": {
            "introduction": "В английском языке есть два типа артиклей: неопределённый (a/an) и определённый (the). Артикли помогают понять, говорим мы о чём-то конкретном или общем.",
            "sections": [
                {
                    "subtitle": "Неопределённый артикль a/an",
                    "description": "Используется, когда говорим о чём-то в первый раз или о неконкретном предмете:",
                    "rules": [
                        {"rule": "a + согласный звук", "examples": ["a book", "a car", "a dog", "a university"]},
                        {"rule": "an + гласный звук", "examples": ["an apple", "an egg", "an hour", "an umbrella"]}
                    ]
                },
                {
                    "subtitle": "Определённый артикль the",
                    "description": "Используется, когда говорим о чём-то конкретном или уже известном:",
                    "examples": [
                        {"sentence": "I have a cat. The cat is black.", "translation": "У меня есть кот. Кот чёрный."},
                        {"sentence": "Open the door, please.", "translation": "Открой дверь, пожалуйста. (конкретную дверь)"},
                        {"sentence": "The sun is bright.", "translation": "Солнце яркое. (единственное в своём роде)"}
                    ]
                },
                {
                    "subtitle": "Когда артикль не нужен",
                    "description": "Артикль не используется:",
                    "rules": [
                        {"rule": "С именами людей", "examples": ["John is here.", "Mary is my friend."]},
                        {"rule": "С названиями стран (большинство)", "examples": ["Russia", "France", "Japan"]},
                        {"rule": "С неисчисляемыми в общем смысле", "examples": ["I like coffee.", "Water is important."]}
                    ]
                }
            ],
            "important_notes": [
                "⚠️ a university (звук [ju:]), но an umbrella (звук [ʌ])",
                "⚠️ an hour (h не произносится), но a house",
                "💡 The используем, когда и говорящий, и слушающий знают, о чём речь"
            ],
            "common_mistakes": [
                {"wrong": "I am student.", "correct": "I am a student.", "explanation": "Профессии требуют артикль"},
                {"wrong": "a apple", "correct": "an apple", "explanation": "Перед гласным звуком используется an"},
                {"wrong": "I like the music.", "correct": "I like music.", "explanation": "В общем смысле артикль не нужен"}
            ]
        },
        "exercises": [
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "I have ___ apple.",
                    "correct_answer": "an",
                    "explanation": "Перед гласным звуком используется an."
                },
                "difficulty": 1,
                "order": 1
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "She is ___ doctor.",
                    "correct_answer": "a",
                    "explanation": "Doctor начинается с согласного звука."
                },
                "difficulty": 1,
                "order": 2
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "Close ___ window, please.",
                    "correct_answer": "the",
                    "explanation": "Речь о конкретном окне, которое видят оба собеседника."
                },
                "difficulty": 1,
                "order": 3
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "I need ___ umbrella.",
                    "options": ["a", "an", "the", "—"],
                    "correct_answer": 1,
                    "explanation": "Umbrella начинается с гласного звука [ʌ]."
                },
                "difficulty": 1,
                "order": 4
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "He goes to ___ university.",
                    "options": ["a", "an", "the", "—"],
                    "correct_answer": 0,
                    "explanation": "University начинается со звука [ju:], который согласный."
                },
                "difficulty": 2,
                "order": 5
            },
            {
                "exercise_type": "error_correction",
                "content": {
                    "sentence": "I saw a elephant at the zoo.",
                    "error_word": "a",
                    "correct_answer": "an",
                    "full_correct": "I saw an elephant at the zoo.",
                    "explanation": "Elephant начинается с гласного звука."
                },
                "difficulty": 2,
                "order": 6
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "___ Moon is beautiful tonight.",
                    "options": ["A", "An", "The", "—"],
                    "correct_answer": 2,
                    "explanation": "Луна единственная, поэтому the."
                },
                "difficulty": 2,
                "order": 7
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "I waited for ___ hour.",
                    "correct_answer": "an",
                    "explanation": "Hour начинается с гласного звука (h не произносится)."
                },
                "difficulty": 2,
                "order": 8
            }
        ]
    },
    {
        "slug": "present-simple",
        "title": "Present Simple",
        "title_ru": "Простое настоящее время",
        "level": "A1",
        "order": 3,
        "estimated_time": 25,
        "difficulty": 2,
        "content": {
            "introduction": "Present Simple используется для описания регулярных действий, привычек, фактов и общих истин.",
            "sections": [
                {
                    "subtitle": "Утвердительные предложения",
                    "description": "Структура: Subject + V (+ s/es для he/she/it)",
                    "table": [
                        {"pronoun": "I/You/We/They", "example": "I work every day.", "translation": "Я работаю каждый день."},
                        {"pronoun": "He/She/It", "example": "She works every day.", "translation": "Она работает каждый день."}
                    ],
                    "rules": [
                        {"rule": "Добавляем -s", "examples": ["work → works", "play → plays", "read → reads"]},
                        {"rule": "Добавляем -es после s, sh, ch, x, o", "examples": ["watch → watches", "go → goes", "wash → washes"]},
                        {"rule": "y → ies после согласной", "examples": ["study → studies", "cry → cries"]}
                    ]
                },
                {
                    "subtitle": "Отрицательные предложения",
                    "description": "Структура: Subject + do/does + not + V",
                    "table": [
                        {"pronoun": "I/You/We/They", "example": "I do not (don't) like coffee.", "translation": "Я не люблю кофе."},
                        {"pronoun": "He/She/It", "example": "He does not (doesn't) like tea.", "translation": "Он не любит чай."}
                    ]
                },
                {
                    "subtitle": "Вопросительные предложения",
                    "description": "Структура: Do/Does + subject + V?",
                    "examples": [
                        {"question": "Do you speak English?", "answer": "Yes, I do. / No, I don't."},
                        {"question": "Does she live here?", "answer": "Yes, she does. / No, she doesn't."}
                    ]
                },
                {
                    "subtitle": "Слова-маркеры",
                    "description": "Present Simple часто используется с:",
                    "examples": [
                        {"word": "always", "example": "I always wake up early."},
                        {"word": "usually", "example": "She usually eats breakfast."},
                        {"word": "often", "example": "We often go to the gym."},
                        {"word": "sometimes", "example": "They sometimes watch TV."},
                        {"word": "never", "example": "He never drinks alcohol."},
                        {"word": "every day/week/month", "example": "I work every day."}
                    ]
                }
            ],
            "important_notes": [
                "⚠️ После does глагол БЕЗ окончания -s: She doesn't like (не likes!)",
                "⚠️ В вопросах: Does he work? (не Does he works?)",
                "💡 Наречия частоты (always, usually) ставятся перед глаголом"
            ],
            "common_mistakes": [
                {"wrong": "She don't like coffee.", "correct": "She doesn't like coffee.", "explanation": "С he/she/it используется doesn't"},
                {"wrong": "Does he likes music?", "correct": "Does he like music?", "explanation": "После does глагол без -s"},
                {"wrong": "He work every day.", "correct": "He works every day.", "explanation": "С he/she/it добавляем -s"}
            ]
        },
        "exercises": [
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "She ___ (work) in a bank.",
                    "correct_answer": "works",
                    "explanation": "С местоимением she добавляем -s к глаголу."
                },
                "difficulty": 1,
                "order": 1
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "They ___ (live) in Moscow.",
                    "correct_answer": "live",
                    "explanation": "С местоимением they глагол остаётся без изменений."
                },
                "difficulty": 1,
                "order": 2
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "He ___ (watch) TV every evening.",
                    "correct_answer": "watches",
                    "explanation": "После ch добавляем -es."
                },
                "difficulty": 1,
                "order": 3
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "She ___ to school by bus.",
                    "options": ["go", "goes", "going", "gos"],
                    "correct_answer": 1,
                    "explanation": "С she используется goes (go → goes)."
                },
                "difficulty": 1,
                "order": 4
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "I ___ (not like) coffee.",
                    "correct_answer": "don't like",
                    "alternatives": ["do not like"],
                    "explanation": "С I используется do not (don't)."
                },
                "difficulty": 2,
                "order": 5
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "He ___ (not speak) French.",
                    "correct_answer": "doesn't speak",
                    "alternatives": ["does not speak"],
                    "explanation": "С he используется does not (doesn't), глагол без -s."
                },
                "difficulty": 2,
                "order": 6
            },
            {
                "exercise_type": "transformation",
                "content": {
                    "instruction": "Сделайте вопрос",
                    "original": "You like pizza.",
                    "correct_answer": "Do you like pizza?",
                    "explanation": "Для вопроса добавляем Do в начало."
                },
                "difficulty": 2,
                "order": 7
            },
            {
                "exercise_type": "transformation",
                "content": {
                    "instruction": "Сделайте вопрос",
                    "original": "She speaks English.",
                    "correct_answer": "Does she speak English?",
                    "explanation": "С she используем Does, глагол без -s."
                },
                "difficulty": 2,
                "order": 8
            },
            {
                "exercise_type": "error_correction",
                "content": {
                    "sentence": "He don't like vegetables.",
                    "error_word": "don't",
                    "correct_answer": "doesn't",
                    "full_correct": "He doesn't like vegetables.",
                    "explanation": "С he/she/it используется doesn't."
                },
                "difficulty": 2,
                "order": 9
            },
            {
                "exercise_type": "translation",
                "content": {
                    "sentence": "Я обычно встаю в 7 часов.",
                    "source_lang": "ru",
                    "target_lang": "en",
                    "correct_answer": "I usually wake up at 7 o'clock.",
                    "alternatives": ["I usually get up at 7 o'clock.", "I usually wake up at 7."],
                    "key_grammar": "Present Simple + usually"
                },
                "difficulty": 3,
                "order": 10
            }
        ]
    },
    {
        "slug": "personal-pronouns",
        "title": "Personal Pronouns",
        "title_ru": "Личные местоимения",
        "level": "A1",
        "order": 4,
        "estimated_time": 10,
        "difficulty": 1,
        "content": {
            "introduction": "Личные местоимения заменяют существительные и указывают на лицо, о котором идёт речь.",
            "sections": [
                {
                    "subtitle": "Именительный падеж (Subject Pronouns)",
                    "description": "Используются как подлежащее:",
                    "table": [
                        {"pronoun": "I", "translation": "я", "example": "I am a student."},
                        {"pronoun": "you", "translation": "ты/вы", "example": "You are kind."},
                        {"pronoun": "he", "translation": "он", "example": "He is my brother."},
                        {"pronoun": "she", "translation": "она", "example": "She is a teacher."},
                        {"pronoun": "it", "translation": "оно/это", "example": "It is a cat."},
                        {"pronoun": "we", "translation": "мы", "example": "We are friends."},
                        {"pronoun": "they", "translation": "они", "example": "They are students."}
                    ]
                },
                {
                    "subtitle": "Объектный падеж (Object Pronouns)",
                    "description": "Используются как дополнение:",
                    "table": [
                        {"subject": "I", "object": "me", "example": "Call me.", "translation": "Позвони мне."},
                        {"subject": "you", "object": "you", "example": "I see you.", "translation": "Я вижу тебя."},
                        {"subject": "he", "object": "him", "example": "Help him.", "translation": "Помоги ему."},
                        {"subject": "she", "object": "her", "example": "Tell her.", "translation": "Скажи ей."},
                        {"subject": "it", "object": "it", "example": "Take it.", "translation": "Возьми это."},
                        {"subject": "we", "object": "us", "example": "Join us.", "translation": "Присоединяйся к нам."},
                        {"subject": "they", "object": "them", "example": "Meet them.", "translation": "Встреть их."}
                    ]
                }
            ],
            "important_notes": [
                "💡 I всегда пишется с большой буквы",
                "💡 You одинаково для 'ты' и 'вы'",
                "⚠️ It используется для животных и предметов"
            ],
            "common_mistakes": [
                {"wrong": "Me am happy.", "correct": "I am happy.", "explanation": "Me — объектный падеж, I — именительный"},
                {"wrong": "Him is my friend.", "correct": "He is my friend.", "explanation": "Him — объектный падеж"}
            ]
        },
        "exercises": [
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "___ am a teacher. (я)",
                    "correct_answer": "I",
                    "explanation": "Местоимение 'я' в английском — I."
                },
                "difficulty": 1,
                "order": 1
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "Give it to ___. (мне)",
                    "correct_answer": "me",
                    "explanation": "После предлога используется объектный падеж — me."
                },
                "difficulty": 1,
                "order": 2
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "___ is my sister.",
                    "options": ["Her", "She", "Him", "He"],
                    "correct_answer": 1,
                    "explanation": "В позиции подлежащего используется she."
                },
                "difficulty": 1,
                "order": 3
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "I saw ___ at the party.",
                    "options": ["he", "him", "his", "her's"],
                    "correct_answer": 1,
                    "explanation": "После глагола (saw) нужен объектный падеж — him."
                },
                "difficulty": 2,
                "order": 4
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "Tell ___ the truth. (ей)",
                    "correct_answer": "her",
                    "explanation": "После глагола tell нужен объектный падеж — her."
                },
                "difficulty": 2,
                "order": 5
            },
            {
                "exercise_type": "error_correction",
                "content": {
                    "sentence": "Me and Tom are friends.",
                    "error_word": "Me",
                    "correct_answer": "Tom and I",
                    "full_correct": "Tom and I are friends.",
                    "explanation": "В позиции подлежащего используется I, не me. Также принято ставить себя последним."
                },
                "difficulty": 2,
                "order": 6
            }
        ]
    },
    {
        "slug": "possessive-adjectives",
        "title": "Possessive Adjectives",
        "title_ru": "Притяжательные прилагательные",
        "level": "A1",
        "order": 5,
        "estimated_time": 10,
        "difficulty": 1,
        "content": {
            "introduction": "Притяжательные прилагательные показывают принадлежность и всегда стоят перед существительным.",
            "sections": [
                {
                    "subtitle": "Притяжательные прилагательные",
                    "description": "Отвечают на вопрос 'чей?':",
                    "table": [
                        {"pronoun": "I", "possessive": "my", "example": "my book", "translation": "моя книга"},
                        {"pronoun": "you", "possessive": "your", "example": "your car", "translation": "твоя/ваша машина"},
                        {"pronoun": "he", "possessive": "his", "example": "his phone", "translation": "его телефон"},
                        {"pronoun": "she", "possessive": "her", "example": "her bag", "translation": "её сумка"},
                        {"pronoun": "it", "possessive": "its", "example": "its tail", "translation": "его хвост (животного)"},
                        {"pronoun": "we", "possessive": "our", "example": "our house", "translation": "наш дом"},
                        {"pronoun": "they", "possessive": "their", "example": "their children", "translation": "их дети"}
                    ]
                }
            ],
            "important_notes": [
                "⚠️ its (его/её для предметов) ≠ it's (it is)",
                "⚠️ their (их) ≠ there (там) ≠ they're (they are)",
                "💡 Притяжательные НЕ меняются по числу: my book, my books"
            ],
            "common_mistakes": [
                {"wrong": "it's tail", "correct": "its tail", "explanation": "its без апострофа — притяжательное"},
                {"wrong": "they're house", "correct": "their house", "explanation": "their — притяжательное, they're = they are"}
            ]
        },
        "exercises": [
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "This is ___ book. (моя)",
                    "correct_answer": "my",
                    "explanation": "Притяжательное от I — my."
                },
                "difficulty": 1,
                "order": 1
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "She loves ___ cat. (её)",
                    "correct_answer": "her",
                    "explanation": "Притяжательное от she — her."
                },
                "difficulty": 1,
                "order": 2
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "The dog wagged ___ tail.",
                    "options": ["it's", "its", "his", "their"],
                    "correct_answer": 1,
                    "explanation": "Для животного используется its (без апострофа)."
                },
                "difficulty": 2,
                "order": 3
            },
            {
                "exercise_type": "multiple_choice",
                "content": {
                    "question": "They forgot ___ keys.",
                    "options": ["they're", "there", "their", "theirs"],
                    "correct_answer": 2,
                    "explanation": "Their — притяжательное от they."
                },
                "difficulty": 2,
                "order": 4
            },
            {
                "exercise_type": "fill_blank",
                "content": {
                    "question": "We love ___ new house. (наш)",
                    "correct_answer": "our",
                    "explanation": "Притяжательное от we — our."
                },
                "difficulty": 1,
                "order": 5
            }
        ]
    }
]


def seed_a1_content():
    """Add A1 grammar topics with exercises to the database."""
    app = create_app()

    with app.app_context():
        created_topics = 0
        created_exercises = 0

        for topic_data in A1_TOPICS:
            # Check if topic already exists
            existing = GrammarTopic.query.filter_by(slug=topic_data['slug']).first()
            if existing:
                print(f"Topic '{topic_data['slug']}' already exists, skipping...")
                continue

            # Create topic
            exercises_data = topic_data.pop('exercises')

            topic = GrammarTopic(**topic_data)
            db.session.add(topic)
            db.session.flush()  # Get the topic ID

            created_topics += 1
            print(f"Created topic: {topic.title} ({topic.level})")

            # Create exercises
            for ex_data in exercises_data:
                exercise = GrammarExercise(
                    topic_id=topic.id,
                    exercise_type=ex_data['exercise_type'],
                    content=ex_data['content'],
                    difficulty=ex_data.get('difficulty', 1),
                    order=ex_data.get('order', 0)
                )
                db.session.add(exercise)
                created_exercises += 1

        db.session.commit()

        print(f"\n{'='*50}")
        print(f"Created {created_topics} topics with {created_exercises} exercises")
        print(f"{'='*50}")


if __name__ == '__main__':
    seed_a1_content()
