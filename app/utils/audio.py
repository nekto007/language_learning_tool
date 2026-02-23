"""Utilities for audio filename parsing and URL generation."""
import re
from typing import Optional


def parse_audio_filename(value: str) -> Optional[str]:
    """
    Extract clean audio filename from various DB formats.

    Supported formats:
        - Anki format: [sound:pronunciation_en_word.mp3] → pronunciation_en_word.mp3
        - Plain filename: pronunciation_en_word.mp3 → pronunciation_en_word.mp3
        - Empty/None → None

    Args:
        value: Raw audio field value from database.

    Returns:
        Clean filename string, or None if input is empty/invalid.
    """
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    m = re.search(r'\[sound:([^\]]+)\]', value)
    if m:
        return m.group(1)

    return value


def get_clean_audio_filename(english_word: str) -> str:
    """
    Генерирует чистое имя аудио файла для слова.

    Args:
        english_word: Английское слово

    Returns:
        Имя файла вида pronunciation_en_word.mp3
    """
    word_slug = english_word.lower().replace(' ', '_')
    return f"pronunciation_en_{word_slug}.mp3"


def normalize_listening(value: str, english_word: str = None) -> Optional[str]:
    """
    Нормализует значение поля listening к единому формату (чистое имя файла).

    Обработка форматов:
        - None/пустая строка → None
        - [sound:xxx.mp3] → xxx.mp3
        - http://... → генерация из english_word через get_clean_audio_filename
        - Уже clean → вернуть как есть

    Args:
        value: Сырое значение поля listening
        english_word: Английское слово (нужно для генерации имени из HTTP URL)

    Returns:
        Нормализованное имя файла или None
    """
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    # [sound:xxx.mp3] → xxx.mp3
    m = re.search(r'\[sound:([^\]]+)\]', value)
    if m:
        return m.group(1)

    # http://... → генерация из english_word
    if value.startswith(('http://', 'https://')):
        if english_word:
            return get_clean_audio_filename(english_word)
        return None

    # Уже clean
    return value
