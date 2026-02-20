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
