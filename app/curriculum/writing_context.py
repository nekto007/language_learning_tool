"""Bind a writing prompt to the server projection issued to one learner."""

import hashlib
import json
import re
from math import isfinite
from typing import Any
from uuid import uuid4

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer

from app.curriculum.models import Lessons


def writing_snapshot(title: str, prompt: str, translation: str | None) -> dict[str, str | None]:
    return {'title': title, 'prompt': prompt, 'translation': translation or None}


def _signer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='web-writing-context-v1')


def _revision(lesson: Lessons, *, words_required: bool) -> str:
    fields = [lesson.type, lesson.title, lesson.content or {}, words_required]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def issue_web_context(
    lesson: Lessons, user_id: int, *, words_required: bool, snapshot: dict[str, str | None],
) -> str:
    return _signer().dumps({
        'user': user_id,
        'lesson': lesson.id,
        'opening': uuid4().hex,
        'revision': _revision(lesson, words_required=words_required),
        'snapshot': snapshot,
    })


def verify_web_context(token: object, lesson_id: int, user_id: int) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(token, str) or not token:
        return None, 'invalid_writing_context'
    try:
        context = _signer().loads(token)
    except BadData:
        return None, 'invalid_writing_context'
    if not isinstance(context, dict) or not context.get('opening') or not isinstance(context.get('snapshot'), dict):
        return None, 'invalid_writing_context'
    if context.get('user') != user_id or context.get('lesson') != lesson_id:
        return None, 'access_denied'
    return context, None


def current_web_snapshot(
    context: dict[str, Any], lesson: Lessons, *, words_required: bool,
) -> dict[str, str | None] | None:
    if lesson.type == 'writing_prompt' and context['revision'] == _revision(lesson, words_required=words_required):
        return context['snapshot']
    return None


def resolve_web_context(
    token: object, lesson: Lessons, user_id: int, *, words_required: bool,
) -> tuple[dict[str, str | None] | None, str | None]:
    context, error = verify_web_context(token, lesson.id, user_id)
    if error:
        return None, error
    snapshot = current_web_snapshot(context, lesson, words_required=words_required)
    return (snapshot, None) if snapshot is not None else (None, 'lesson_changed')


def web_submission_fingerprint(data: dict[str, Any], opening: str) -> str | None:
    submission_id = data.get('writing_submission_id')
    text = data.get('response_text')
    checked = data.get('checked_items', [])
    elapsed = data.get('time_spent_seconds')
    if (not isinstance(submission_id, str) or re.fullmatch(r'[0-9a-f]{32}', submission_id) is None
            or not isinstance(text, str) or not isinstance(checked, list)
            or any(not isinstance(item, str) for item in checked)
            or (isinstance(elapsed, float) and not isfinite(elapsed))):
        return None
    seconds = int(elapsed) if isinstance(elapsed, (int, float)) and elapsed >= 0 else None
    fields = [opening, text, sorted(set(checked)), seconds]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=True).encode()).hexdigest()
