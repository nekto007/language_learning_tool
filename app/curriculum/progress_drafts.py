"""Client drafts contain learner input; grading ledgers remain server-owned."""
from copy import deepcopy
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.curriculum.models import LessonProgress, Lessons


_SERVER_FIELDS = frozenset({
    'quiz_correction', 'score', 'last_score', 'best_score', 'passed', 'completed',
    'status', 'completed_at', 'completion', 'completion_state', 'feedback',
    'item_results', 'correct_words', 'total_words', 'correct_items', 'total_items',
    'failed_by_attempt_limit', 'studied_cards', 'cards_studied', 'accuracy',
    'dictation_attempts', 'card_progress',
})


def validate_client_draft(incoming: object) -> None:
    """Reject grading ledgers before a public snapshot touches the database."""
    if (not isinstance(incoming, dict) or any(
            not isinstance(key, str) or key in _SERVER_FIELDS
            or key.startswith(('_native', 'native_')) for key in incoming)):
        raise ValueError('invalid_draft_fields')


def merge_client_draft(existing: object, incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge a legacy editor snapshot without replacing committed server state.

    Per-item UI states inside ``items``/``answers`` remain compatible; they are
    learner input and never become a server result. Reserved root fields are
    rejected, including future native receipt/coverage names in that namespace.
    """
    validate_client_draft(incoming)
    from app.curriculum.security import sanitize_json_content

    return {**deepcopy(existing if isinstance(existing, dict) else {}),
            **sanitize_json_content(deepcopy(incoming))}


def final_draft_origin_matches(lesson: 'Lessons', progress: 'LessonProgress') -> bool:
    """Require signed provenance for both the final context and the saved input.

    Public snapshots never issue this marker. Ambiguous pre-rollout snapshots
    must not be relabelled from the lesson's current type at read/save time.
    """
    from itsdangerous import BadSignature
    from app.api.native_lessons import _digest, _signer

    data = progress.data if isinstance(progress.data, dict) else {}
    saved = data.get('answers') or data.get('user_answers')
    token = data.get('_native_legacy_draft_origin')
    if not isinstance(token, str) or lesson.type != 'final_test':
        return False
    try:
        origin = _signer().loads(token)
    except (BadSignature, TypeError):
        return False
    return isinstance(origin, dict) and origin == {
        'purpose': 'legacy_final_draft', 'user': progress.user_id, 'lesson': lesson.id,
        'lesson_type': 'final_test', 'revision': _digest(lesson.content),
        'answers_digest': _digest(saved),
    }


def legacy_final_input_archive(progress: 'LessonProgress | None') -> dict[str, Any] | None:
    """Keep old learner values privately across final submissions and repeats.

    Verdicts, expected answers and arbitrary metadata are never archived or
    exposed as exam input. The original archive wins over later exam results.
    """
    data = progress.data if progress is not None and isinstance(progress.data, dict) else {}
    archive = data.get('_native_legacy_draft')
    if isinstance(archive, dict):
        saved = archive.get('answers')
    elif '_native_submission' in data or 'quiz_correction' in data:
        return None  # Current graded results are not pre-rollout editor drafts.
    else:
        saved = data.get('answers') or data.get('user_answers')
    if not isinstance(saved, (dict, list)):
        return None
    entries = saved.items() if isinstance(saved, dict) else enumerate(saved)
    answers = {}
    for identifier, entry in entries:
        key = str(identifier)
        if not key.isdecimal():
            continue
        own = {'value': entry} if isinstance(entry, str) else {}
        if isinstance(entry, dict):
            if isinstance(entry.get('value'), str):
                own['value'] = entry['value']
            pairs = entry.get('pairs')
            if isinstance(pairs, list):
                own['pairs'] = [{'left': pair['left'], 'right': pair['right']} for pair in pairs
                                if isinstance(pair, dict) and isinstance(pair.get('left'), str)
                                and isinstance(pair.get('right'), str)]
        if own:
            answers[key] = own
    return {'answers': answers} if answers else None
