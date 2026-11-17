"""Dictionary assistance for on-device OPUS-MT. No remote model calls."""
import re

from app.reader_translation.lexicon import dictionary_candidates, expression_candidates, key

VERSION = 'opus-lexicon-v1'


class InvalidSelection(ValueError):
    pass


def selection(body):
    expected = {'text', 'sentence', 'lower_utf16', 'length_utf16', 'lemma'}
    if not isinstance(body, dict) or set(body) != expected:
        raise InvalidSelection()
    text, sentence, lemma = body['text'], body['sentence'], body['lemma']
    if not all(isinstance(value, str) and '\x00' not in value for value in (text, sentence, lemma)):
        raise InvalidSelection()
    if not 1 <= len(text) <= 400 or not 1 <= len(sentence) <= 1200 or not 1 <= len(lemma) <= 400:
        raise InvalidSelection()
    if not re.search('[A-Za-z]', text) or not re.search('[A-Za-z]', lemma):
        raise InvalidSelection()
    lower, length = body['lower_utf16'], body['length_utf16']
    if type(lower) is not int or type(length) is not int or lower < 0 or length <= 0:
        raise InvalidSelection()
    try:
        for value in (text, sentence, lemma):
            value.encode('utf-8')  # Reject unpaired surrogate escapes in JSON.
        encoded = sentence.encode('utf-16-le')
        if (lower + length) * 2 > len(encoded):
            raise ValueError()
        before = encoded[:lower * 2].decode('utf-16-le')
        if encoded[lower * 2:(lower + length) * 2].decode('utf-16-le') != text:
            raise ValueError()
    except (ValueError, UnicodeError) as exc:
        raise InvalidSelection() from exc
    return dict(text=text, sentence=sentence, lemma=key(lemma),
                start=len(before), end=len(before) + len(text))


def lookup(selected):
    sentence, start, end = selected['sentence'], selected['start'], selected['end']
    return dict(version=VERSION,
                entries=dictionary_candidates(sentence, start, end, selected['lemma']),
                expressions=expression_candidates(sentence, start, end))
