"""Difficult words: слова, на которых пользователь системно спотыкается.

Критерий per direction: ``lapses >= DIFFICULT_LAPSES_THRESHOLD`` ИЛИ карточка
сейчас в leech-бане (``buried_until`` в будущем). Агрегация — на уровне слова
(у слова два direction'а): max lapses, любой активный bury.

Практика — контекстный quiz по примерам (cloze multiple-choice): слово
показывается в предложении с пропуском вместо очередного flip-card, который
уже N раз не сработал. Успешная проработка снимает bury (карточка
возвращается в ротацию), SM-2-состояние не трогаем.
"""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.srs.constants import LEECH_THRESHOLD
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db as _db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)

DIFFICULT_LAPSES_THRESHOLD = 3
PRACTICE_MAX_QUESTIONS = 10
PRACTICE_OPTIONS_COUNT = 4

_TAG_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')
_LATIN_RE = re.compile(r'[A-Za-z]')
_CYRILLIC_RE = re.compile(r'[А-Яа-яЁё]')


def split_example(sentences: Optional[str]) -> tuple:
    """Разобрать ``CollectionWords.sentences`` на (english, russian).

    Формат поля исторически грязный: строки через \\n или <br>, иногда с
    маркерами «-». Берём первую чисто-латинскую строку как EN и первую
    строку с кириллицей как RU (зеркалит ``_extractExampleParts`` во
    flashcard-session.js).
    """
    if not sentences:
        return '', ''
    text = _TAG_BR_RE.sub('\n', sentences)
    text = _TAG_RE.sub('', text)
    text = text.replace('|', '\n')
    lines = [line.strip(' -\t—') for line in text.split('\n') if line.strip()]
    en = next(
        (l for l in lines if _LATIN_RE.search(l) and not _CYRILLIC_RE.search(l)),
        '',
    )
    ru = next((l for l in lines if _CYRILLIC_RE.search(l)), '')
    if not en and lines:
        en = lines[0]
    return en, ru


def get_difficult_words(user_id: int, db: Any = _db, limit: int = 50) -> list:
    """Слова со «спотыканием»: lapses >= порога или активный leech-бан.

    Возвращает список dict'ов, отсортированный: забаненные сверху, дальше по
    убыванию lapses.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = (
        db.session.query(UserCardDirection, UserWord, CollectionWords)
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .join(CollectionWords, UserWord.word_id == CollectionWords.id)
        .filter(UserWord.user_id == user_id)
        .filter(
            (UserCardDirection.lapses >= DIFFICULT_LAPSES_THRESHOLD)
            | (UserCardDirection.buried_until > now)
        )
        .all()
    )

    by_word: dict = {}
    for direction, user_word, word in rows:
        entry = by_word.get(word.id)
        if entry is None:
            example_en, example_ru = split_example(word.sentences)
            entry = {
                'word_id': word.id,
                'english_word': word.english_word,
                'russian_word': word.russian_word or '',
                'level': word.level,
                'example_en': example_en,
                'example_ru': example_ru,
                'lapses': 0,
                'buried_until': None,
                'correct': 0,
                'incorrect': 0,
            }
            by_word[word.id] = entry
        entry['lapses'] = max(entry['lapses'], direction.lapses or 0)
        entry['correct'] += direction.correct_count or 0
        entry['incorrect'] += direction.incorrect_count or 0
        if direction.buried_until is not None and direction.buried_until > now:
            current = entry['buried_until']
            if current is None or direction.buried_until > current:
                entry['buried_until'] = direction.buried_until

    result = []
    for entry in by_word.values():
        total = entry['correct'] + entry['incorrect']
        entry['accuracy'] = round(entry['correct'] / total * 100) if total else None
        entry['is_leech'] = entry['lapses'] >= LEECH_THRESHOLD
        result.append(entry)

    result.sort(
        key=lambda e: (e['buried_until'] is not None, e['lapses']),
        reverse=True,
    )
    return result[:limit]


def _make_gap_sentence(sentence: str, word: str) -> Optional[str]:
    """Заменить слово (с возможным окончанием) на пропуск; None если не нашли."""
    if not sentence or not word:
        return None
    pattern = re.compile(r'\b' + re.escape(word) + r'\w*', re.IGNORECASE)
    if not pattern.search(sentence):
        return None
    return pattern.sub('____', sentence, count=1)


def build_practice_questions(
    words: list,
    max_questions: int = PRACTICE_MAX_QUESTIONS,
    distractor_pool: Optional[list] = None,
) -> list:
    """Собрать вопросы контекстного quiz'а из difficult-слов.

    Cloze по примеру, если слово находится в предложении; иначе fallback —
    выбор английского слова по русскому переводу. Дистракторы — английские
    слова других difficult-слов плюс ``distractor_pool`` (другие слова юзера,
    когда трудных слов меньше четырёх).
    """
    pool = [w['english_word'] for w in words]
    if distractor_pool:
        pool.extend(d for d in distractor_pool if d)

    questions = []
    for entry in words[:max_questions]:
        correct = entry['english_word']
        distractors = [p for p in dict.fromkeys(pool) if p.lower() != correct.lower()]
        random.shuffle(distractors)
        options = [correct] + distractors[:PRACTICE_OPTIONS_COUNT - 1]
        if len(options) < 2:
            continue
        random.shuffle(options)

        gap = _make_gap_sentence(entry['example_en'], correct)
        if gap:
            question_type = 'cloze'
            prompt = gap
        else:
            if not entry['russian_word']:
                continue
            question_type = 'translation'
            prompt = entry['russian_word']

        questions.append({
            'word_id': entry['word_id'],
            'type': question_type,
            'prompt': prompt,
            'options': options,
            'correct': correct,
            'russian': entry['russian_word'],
            'example_en': entry['example_en'],
            'example_ru': entry['example_ru'],
        })
    return questions


def unbury_words(user_id: int, word_ids: list, db: Any = _db) -> int:
    """Снять активный leech-бан с карточек указанных слов (flush only).

    Возвращает число разбаненных direction'ов. SM-2-поля и
    ``consecutive_leech_burials`` не трогаем: проработка — не review, при
    следующем lapse прогрессивный bury продолжит масштабироваться.
    """
    if not word_ids:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    directions = (
        db.session.query(UserCardDirection)
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(word_ids),
            UserCardDirection.buried_until.isnot(None),
            UserCardDirection.buried_until > now,
        )
        .all()
    )
    for direction in directions:
        direction.buried_until = None
    db.session.flush()
    return len(directions)
