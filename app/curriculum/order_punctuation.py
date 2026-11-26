"""Identify authored terminal punctuation that can be supplied after assembly."""

from collections import Counter
import re


_MARKS = frozenset('.!?')
_ORDER_TYPES = frozenset({'ordering', 'reorder', 'sentence_builder'})
_EXPLICIT_PUNCTUATION = re.compile(r'punctuat|пунктуац|знак\w*\s+препинан', re.IGNORECASE)
_ABBREVIATIONS = frozenset({'dr.', 'mr.', 'mrs.', 'ms.', 'prof.', 'jr.', 'sr.', 'st.', 'e.g.', 'i.e.'})
_DECIMAL = re.compile(r'[+-]?\d+\.\d+%?')


def _word_with_known_punctuation(word: str) -> bool:
    return word.casefold() in _ABBREVIATIONS or _DECIMAL.fullmatch(word) is not None


def automatic_order_terminal(row: dict) -> tuple[int, str] | None:
    if row.get('type') not in _ORDER_TYPES:
        return None
    if (any(row.get(key) for key in ('require_punctuation', 'punctuation_required', 'explicit_punctuation'))
            or any(_EXPLICIT_PUNCTUATION.search(str(row.get(key) or '')) for key in ('instruction', 'prompt', 'question'))):
        return None
    words = row.get('words') or row.get('tokens')
    if not isinstance(words, list) or len(words) < 2 or not all(isinstance(word, str) for word in words):
        return None
    stripped = [word.strip() for word in words]
    marks = [(i, word) for i, word in enumerate(stripped) if word in _MARKS]
    if len(marks) != 1:
        return None
    index, mark = marks[0]
    lexical = [word for i, word in enumerate(stripped) if i != index]
    if any(len(word.split()) != 1 or not any(char.isalnum() for char in word)
           or (set(word) & _MARKS and not _word_with_known_punctuation(word))
           for word in lexical):
        return None

    keys = ('answer', 'correct_answer', 'correct', 'correct_order', 'correct_sentence', 'answers',
            'alternatives', 'alternative_answers', 'acceptable_answers')
    authored = [row[key] for key in keys if row.get(key)]
    if not authored or any(not _terminal_matches(value, stripped, lexical, index, mark) for value in authored):
        return None
    return index, mark


def _terminal_matches(value: object, words: list[str], lexical: list[str], index: int, mark: str) -> bool:
    if isinstance(value, list) and all(type(item) is int for item in value):
        return len(value) == len(words) and set(value) == set(range(len(words))) and value[-1] == index
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        if len(value) == len(words) and value[-1].strip() == mark:
            value = ' '.join(value)
        else:
            return bool(value) and all(_terminal_matches(item, words, lexical, index, mark) for item in value)
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text[-1:] in _MARKS:
        if text[-1] != mark:
            return False
        text = text[:-1].strip()
    elif index != len(words) - 1:
        return False
    return Counter(text.casefold().split()) == Counter(word.casefold() for word in lexical)


def legacy_order_display(row: dict) -> dict:
    terminal = automatic_order_terminal(row)
    if terminal is None or not row.get('words'):
        return row
    index, mark = terminal
    return {**row, 'words': [word for i, word in enumerate(row['words']) if i != index],
            'automatic_order_mark': mark}
