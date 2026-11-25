"""Learner-facing lines for the structured legacy dictionary examples."""

import json
from html import unescape

from bs4 import BeautifulSoup

ENGLISH_KEYS = ('en', 'english', 'sentence')
RUSSIAN_KEYS = ('ru', 'russian', 'translation')


def _text(value: str) -> str:
    if '<' in value:
        return BeautifulSoup(value, 'html.parser').get_text(' ', strip=True)
    return unescape(value).strip()


def _first_text(row: dict, keys: tuple[str, ...]) -> str:
    return next((_text(value) for key in keys if isinstance(value := row.get(key), str) and value.strip()), '')


def json_example_pairs(value: str | None) -> list[tuple[str, str]] | None:
    """Return None for legacy HTML/plain text, which keeps its existing renderer."""
    if not value or not value.lstrip().startswith(('[', '{')):
        return None
    try:
        decoded = json.loads(value)
    except (ValueError, RecursionError):
        return None
    rows = decoded if isinstance(decoded, list) else [decoded]
    pairs = []
    for row in rows:
        if isinstance(row, dict):
            english, russian = _first_text(row, ENGLISH_KEYS), _first_text(row, RUSSIAN_KEYS)
            if english or russian:
                pairs.append((english, russian))
        elif isinstance(row, str) and (text := _text(row)):
            pairs.append((text, ''))
    return pairs if pairs or not decoded else None
