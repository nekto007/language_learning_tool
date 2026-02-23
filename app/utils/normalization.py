"""Text normalization utilities for answer comparison."""
import re


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
