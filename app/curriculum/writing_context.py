"""Bind a writing prompt to the server projection issued to one learner."""

import hashlib
import json
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


def resolve_web_context(
    token: object, lesson: Lessons, user_id: int, *, words_required: bool,
) -> tuple[dict[str, str | None] | None, str | None]:
    if not isinstance(token, str) or not token:
        return None, 'invalid_writing_context'
    try:
        context = _signer().loads(token)
    except BadData:
        return None, 'invalid_writing_context'
    if not isinstance(context, dict) or not context.get('opening') or not isinstance(context.get('snapshot'), dict):
        return None, 'invalid_writing_context'
    if context.get('user') != user_id or context.get('lesson') != lesson.id:
        return None, 'access_denied'
    if lesson.type != 'writing_prompt' or context.get('revision') != _revision(lesson, words_required=words_required):
        return None, 'lesson_changed'
    return context['snapshot'], None
