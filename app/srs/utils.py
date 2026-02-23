"""
SRS utility functions — the single source of truth for state counting.
"""
from datetime import datetime
from typing import Dict, Iterable


def count_srs_states(records: Iterable, now: datetime = None) -> Dict[str, int]:
    """
    Count SRS items by category.

    Args:
        records: Iterable of objects with classify() and is_due (SRSFieldsMixin)
        now: Optional timestamp (unused, kept for API consistency)

    Returns:
        Dict with new_count, learning_count, review_count, mastered_count, total, due_today
    """
    new_count = 0
    learning_count = 0
    review_count = 0
    mastered_count = 0
    due_today = 0

    for record in records:
        category = record.classify()
        if category == 'new':
            new_count += 1
            due_today += 1
        elif category == 'learning':
            learning_count += 1
            if record.is_due:
                due_today += 1
        elif category == 'review':
            review_count += 1
            if record.is_due:
                due_today += 1
        elif category == 'mastered':
            mastered_count += 1
            if record.is_due:
                due_today += 1

    return {
        'new_count': new_count,
        'learning_count': learning_count,
        'review_count': review_count,
        'mastered_count': mastered_count,
        'total': new_count + learning_count + review_count + mastered_count,
        'due_today': due_today,
    }


def count_srs_states_with_accuracy(records: Iterable, now: datetime = None) -> Dict:
    """
    Count SRS states and compute overall accuracy.

    Returns:
        Dict with all count_srs_states keys + accuracy (float 0-100)
    """
    records_list = list(records)
    result = count_srs_states(records_list, now)

    total_correct = sum(getattr(r, 'correct_count', 0) or 0 for r in records_list)
    total_incorrect = sum(getattr(r, 'incorrect_count', 0) or 0 for r in records_list)
    total_attempts = total_correct + total_incorrect

    result['accuracy'] = round(total_correct / total_attempts * 100, 1) if total_attempts > 0 else 0

    return result
