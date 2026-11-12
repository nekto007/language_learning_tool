"""Level-specific Russian support for task wording, separate from answers.

Only explicitly authored question translations may be shown before an answer.
Audio transcripts and their translations are not question translations.
"""
from __future__ import annotations


def language_support_mode(lesson) -> str:
    level = getattr(getattr(lesson, 'module', None), 'level', None)
    code = str(getattr(level, 'code', '') or '').strip().upper()
    if code in ('A0', 'A1'):
        return 'inline'
    if code == 'A2':
        return 'toggle'
    return 'off'


def question_translation(item) -> str:
    """Return task wording only; never fall back to a transcript/answer field."""
    if not isinstance(item, dict):
        return ''
    for field in ('question_ru', 'statement_ru', 'prompt_ru'):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def localized_option(value, lesson) -> str:
    """Localize the label, keeping the canonical value untouched for grading."""
    text = str(value)
    if language_support_mode(lesson) in ('inline', 'toggle'):
        if text.strip().casefold() == 'true':
            return 'Верно / True'
        if text.strip().casefold() == 'false':
            return 'Неверно / False'
    return text
