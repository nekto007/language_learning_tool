"""Address editable example pairs without reformatting the stored neighbors."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape, unescape
from itertools import pairwise

from app.words.example_projection import ENGLISH_KEYS, RUSSIAN_KEYS

_BR = re.compile(r'<br\s*/?>|\r\n|[\r\n|]', re.IGNORECASE)
_TAG = re.compile(r'<(/?)(b|strong|em|i|u|span)\s*>', re.IGNORECASE)
_LATIN = re.compile(r'[A-Za-z]')
_CYRILLIC = re.compile(r'[А-Яа-яЁё]')  # noqa: RUF001 -- Detect Cyrillic in bilingual legacy pairs.
_WS = re.compile(r'\s*')
_JSON = json.JSONDecoder()


@dataclass(frozen=True)
class TextPiece:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ExampleLine:
    pieces: tuple[TextPiece, ...]
    is_json: bool = False

    @property
    def text(self) -> str:
        return ''.join(piece.text for piece in self.pieces).strip()

    def replace(self, value: str) -> list[tuple[int, int, str]]:
        if value == self.text:
            return []
        if self.is_json:
            piece, = self.pieces
            return [(piece.start, piece.end, json.dumps(value, ensure_ascii=False))]
        joined = ''.join(piece.text for piece in self.pieces)
        leading = len(joined) - len(joined.lstrip())
        changes: list[tuple[int, int, str]] = [
            (a + leading, b + leading, value[c:d])
            for tag, a, b, c, d in SequenceMatcher(a=self.text, b=value, autojunk=False).get_opcodes()
            if tag != 'equal'
        ]
        edits = []
        offset = 0
        for piece in self.pieces:
            end = offset + len(piece.text)
            inside = [(a, b, text) for a, b, text in changes if offset <= a <= b <= end]
            if inside:
                updated = piece.text
                for a, b, text in reversed(inside):
                    updated = updated[:a - offset] + text + updated[b - offset:]
                edits.append((piece.start, piece.end, escape(updated, quote=False)))
            changes = [edit for edit in changes if edit not in inside]
            offset = end
        if changes:
            raise ValueError('Правка пересекает границу разметки. Исправьте соседние фрагменты по одному.')
        return edits


@dataclass(frozen=True)
class Example:
    english: ExampleLine
    russian: ExampleLine | None
    add_translation_at: int | None = None
    translation_joiner: str = ''


@dataclass(frozen=True)
class Examples:
    source: str
    pairs: tuple[Example, ...] = ()
    empty_format: str | None = None
    has_unparsed: bool = False

    @property
    def can_replace(self) -> bool:
        return self.empty_format is None and (not self.pairs or self.has_unparsed)

    def edit(self, example_id: int, english: str, russian: str) -> str:
        if not english or (not russian and (self.empty_format is not None or self.pairs[example_id].russian is not None)):
            raise ValueError('Заполните фразу и перевод примера.')
        is_plain = self.empty_format == 'html' or (not self.empty_format and not self.pairs[example_id].english.is_json)
        if is_plain and (not _LATIN.search(english) or _CYRILLIC.search(english) or (russian and not _CYRILLIC.search(russian))):
            raise ValueError('Для этой пары укажите английскую фразу и перевод с кириллицей.')  # noqa: RUF001 -- Russian validation message.
        if self.empty_format == 'html':
            return f'{escape(english, quote=False)}<br>{escape(russian, quote=False)}'
        if self.empty_format in ('array', 'object'):
            pair = json.dumps({'en': english, 'ru': russian}, ensure_ascii=False)
            close = self.source.rfind(']' if self.empty_format == 'array' else '}')
            if self.empty_format == 'array':
                return self.source[:close] + pair + self.source[close:]
            return self.source[:close] + pair[1:-1] + self.source[close:]
        pair = self.pairs[example_id]
        edits = pair.english.replace(english)
        if pair.russian is not None:
            edits.extend(pair.russian.replace(russian))
        elif russian and pair.add_translation_at is not None:
            value = (json.dumps(russian, ensure_ascii=False) if pair.english.is_json else escape(russian, quote=False))
            edits.append((pair.add_translation_at, pair.add_translation_at, pair.translation_joiner + value))
        updated = self.source
        for start, end, value in sorted(edits, reverse=True):
            updated = updated[:start] + value + updated[end:]
        return updated


def _text_line(source: str, start: int, end: int) -> ExampleLine | None:
    if end - start > 3000:
        return None
    pieces = []
    stack = []
    previous = start
    for tag in _TAG.finditer(source, start, end):
        if previous < tag.start():
            pieces.append(TextPiece(previous, tag.start(), unescape(source[previous:tag.start()])))
        closing, name = tag[1], tag[2].lower()
        if closing:
            if not stack or stack.pop() != name:
                return None
        else:
            stack.append(name)
        previous = tag.end()
    if previous < end:
        pieces.append(TextPiece(previous, end, unescape(source[previous:end])))
    if stack or any('<' in source[piece.start:piece.end] for piece in pieces):
        return None
    return ExampleLine(tuple(pieces))


def _plain_examples(source: str) -> Examples:
    spans = []
    start = 0
    for delimiter in _BR.finditer(source):
        spans.append((start, delimiter.start()))
        start = delimiter.end()
    spans.append((start, len(source)))
    spans = [(start, end) for start, end in spans if source[start:end].strip()]
    lines = [_text_line(source, start, end) for start, end in spans]
    pairs = []
    recognized = set()
    for position, (en, ru) in enumerate(pairwise(lines)):
        if en and ru and _LATIN.search(en.text) and not _CYRILLIC.search(en.text) and _CYRILLIC.search(ru.text):
            pairs.append(Example(en, ru))
            recognized.update((position, position + 1))
    if pairs:
        return Examples(source, tuple(pairs), has_unparsed=len(recognized) != len(lines))
    if len(lines) == 1 and (line := lines[0]) and _LATIN.search(line.text) and not _CYRILLIC.search(line.text):
        end = spans[0][1]
        joiner = '<br>' if _TAG.search(source) else '\n'
        return Examples(source, (Example(line, None, end, joiner),))
    return Examples(source)


def _json_members(source: str, start: int, *, object_members: bool) -> Iterator[tuple[str, object, int, int]]:
    """Find value spans in JSON which has already passed the standard decoder."""
    position = _WS.match(source, start + 1).end()
    while source[position] not in ']}':
        key = ''
        if object_members:
            key, end = _JSON.raw_decode(source, position)
            colon = _WS.match(source, end).end()
            position = _WS.match(source, colon + 1).end()
        value, end = _JSON.raw_decode(source, position)
        yield key, value, position, end
        position = _WS.match(source, end).end()
        if source[position] == ',':
            position = _WS.match(source, position + 1).end()


def _json_pair(source: str, start: int, end: int) -> Example | None:
    members = list(_json_members(source, start, object_members=True))
    english = [member for member in members if member[0] in ENGLISH_KEYS]
    russian = [member for member in members if member[0] in RUSSIAN_KEYS]
    if len(english) != 1 or len(russian) > 1:
        return None
    en = _json_line(english[0])
    if en is None or not en.text:
        return None
    if not russian:
        return Example(en, None, end - 1, ', "ru": ')
    ru = _json_line(russian[0])
    return Example(en, ru) if ru is not None else None


def _json_line(member: tuple[str, object, int, int]) -> ExampleLine | None:
    _, value, start, end = member
    if not isinstance(value, str) or len(value) > 3000 or '<' in value:
        return None
    return ExampleLine((TextPiece(start, end, value),), is_json=True)


def parse_examples(value: str | None) -> Examples:
    source = value or ''
    if source.strip().casefold() in ('', 'null', 'none'):
        return Examples(source, empty_format='html')
    start = _WS.match(source).end()
    if source[start] not in '[{':
        return _plain_examples(source)
    try:
        container, end = _JSON.raw_decode(source, start)
    except (ValueError, RecursionError):
        return Examples(source)
    if source[end:].strip():
        return Examples(source)
    if not container:
        return Examples(source, empty_format='array' if isinstance(container, list) else 'object')
    if isinstance(container, dict):
        pair = _json_pair(source, start, end)
        return Examples(source, (pair,) if pair else ())
    pairs = tuple(pair for _, value, start, end in _json_members(source, start, object_members=False)
                  if isinstance(value, dict) and (pair := _json_pair(source, start, end)) is not None)
    return Examples(source, pairs, has_unparsed=len(pairs) != len(container))


def validate_example_lines(english: str, russian: str) -> None:
    if any(len(line) > 1000 or any(ord(char) < 32 or char in '<>|\x7f' for char in line)
           for line in (english, russian)):
        raise ValueError('Введите фразу и перевод обычным текстом на отдельных строках, до 1000 символов.')


def replacement_examples(english: str, russian: str) -> str:
    phrases, translations = english.split('\n'), russian.split('\n')
    if not 1 <= len(phrases) == len(translations) <= 10:
        raise ValueError('Укажите от 1 до 10 пар. Число строк в обоих полях должно совпадать.')
    empty = Examples('', empty_format='html')
    pairs = []
    for phrase, translation in zip(phrases, translations, strict=True):
        phrase, translation = phrase.strip(), translation.strip()
        validate_example_lines(phrase, translation)
        pairs.append(empty.edit(0, phrase, translation))
    return '<br><br>'.join(pairs)
