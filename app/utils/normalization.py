"""Text normalization utilities for answer comparison."""
import re
import unicodedata


ZERO_ARTICLE_MARKERS = frozenset({
    '—', '–', '-', '−', 'x', 'ø', '∅', '0', 'zero', 'zero article', 'no article',  # noqa: RUF001
    'none', 'nothing', 'нет', 'ничего', 'нет артикля', 'без артикля', 'пусто',
})
EXPECTED_ZERO_ARTICLE_MARKERS = frozenset({
    '—', '–', '-', '−', 'x', 'ø', '∅', 'zero article', 'no article',  # noqa: RUF001
    'нет артикля', 'без артикля',
})


def normalize_quiz_answer(text: str) -> str:
    """Case/punctuation-insensitive text for ordinary quizzes and grammar.

    Ignore every Unicode punctuation category, including apostrophes,
    underscores, quotation marks and sentence punctuation. Retain letters,
    accents, digits, symbols, word order and whitespace-delimited word
    boundaries. This is NOT a dictation normalizer or a comparison of option
    indexes: structured/choice transport values must remain exact.
    """
    if text is None:
        return ''
    value = ''.join(char for char in str(text).casefold().replace('\u02bc', "'")
                    if not unicodedata.category(char).startswith('P'))
    return re.sub(r'\s+', ' ', value).strip()


def normalize_text(text: str) -> str:
    """
    Normalize text for answer comparison.

    Strips whitespace, lowercases, removes punctuation,
    and collapses multiple spaces into one.
    """
    if not text:
        return ""
    normalized = re.sub(r'[^\w\s]', '', str(text).lower().strip())
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized
