"""Honest self-review for open/rubric translation, without fabricated accuracy.

Known authored variants still use the existing strict grader. Other English
answers require an explicit reference-based self-review, proved by a short-lived
token bound to the exact learner, lesson, source item, and answer.
"""
from __future__ import annotations

import hashlib
import json
import re

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.curriculum.grading import _strict_text_match

_SALT = 'curriculum.translation.self-review.v1'
_MAX_AGE = 3600
_MAX_ANSWER_LENGTH = 2000
_ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")


def _failure(error, **details):
    return {'success': False, 'error': error, 'assessment': 'self_review', **details}


def _source_items(lesson):
    content = getattr(lesson, 'content', None)
    if getattr(lesson, 'type', None) != 'translation' or not isinstance(content, dict):
        return None
    if content.get('mode') not in ('open', 'rubric'):
        return None
    items = content.get('items')
    return items if isinstance(items, list) and items else None


def _answer(value):
    if not isinstance(value, str) or len(value) > _MAX_ANSWER_LENGTH:
        return None
    value = value.strip()
    return value if len(_ENGLISH_WORD.findall(value)) >= 2 else None


def _references(item):
    from app.curriculum.translation_variants import get_translation_variants, translation_reference

    canonical = item.get('english')
    if not isinstance(canonical, str) or not canonical.strip():
        return []
    russian = str(item.get('russian') or '')
    reference, _ = translation_reference(canonical, russian)
    values = [reference.strip()]
    for value in [*(item.get('alternatives') or []), *get_translation_variants(canonical, russian)]:
        if isinstance(value, str) and value.strip():
            value, _ = translation_reference(value, russian)
            if value.strip() not in values:
                values.append(value.strip())
    return values


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _proof(lesson, user_id, index, item, answer, purpose):
    return {
        'v': 1, 'purpose': purpose, 'user_id': user_id, 'lesson_id': lesson.id,
        'content_version': getattr(lesson, 'content_version', None), 'item_index': index,
        'item_hash': _hash(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(',', ':'))),
        'reference_hash': _hash(json.dumps(_references(item), ensure_ascii=False, separators=(',', ':'))),
        'answer_hash': _hash(answer),
    }


def _serializer():
    secret = current_app.config.get('SECRET_KEY')
    return URLSafeTimedSerializer(secret, salt=_SALT) if secret else None


def _load_token(serializer, token):
    if not isinstance(token, str) or not token or len(token) > 4096:
        return None
    try:
        return serializer.loads(token, max_age=_MAX_AGE)
    except (BadSignature, TypeError, ValueError):
        return None


def review_item(lesson, user_id, index, answer, review_token=None, confirm=False):
    """Review one source item; confirmation alone never establishes acceptance."""
    items = _source_items(lesson)
    if items is None:
        return _failure('unsupported_mode')
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(items):
        return _failure('invalid_item')
    item = items[index]
    if not isinstance(item, dict) or not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        return _failure('invalid_item')
    references = _references(item)
    if not references:
        return _failure('invalid_item')
    answer = _answer(answer)
    if answer is None:
        return _failure('invalid_answer', index=index)
    result = {
        'success': True, 'index': index, 'answer': answer, 'user_answer': answer, 'assessment': 'self_review',
        'reference_answer': references[0], 'alternatives': references[1:],
    }
    if _strict_text_match(answer, references):
        return {**result, 'status': 'matched', 'correct': True, 'review_token': None}
    serializer = _serializer()
    if serializer is None:
        return _failure('review_unavailable', index=index)
    proof = _proof(lesson, user_id, index, item, answer, 'pending')
    if confirm is True:
        payload = _load_token(serializer, review_token)
        reviewed_proof = _proof(lesson, user_id, index, item, answer, 'reviewed')
        if payload == reviewed_proof:
            return {**result, 'status': 'self_reviewed', 'correct': None, 'review_token': review_token}
        if payload != proof:
            return _failure('invalid_review_token', index=index)
        return {**result, 'status': 'self_reviewed', 'correct': None,
                'review_token': serializer.dumps(reviewed_proof)}
    return {**result, 'status': 'needs_review', 'correct': None, 'review_token': serializer.dumps(proof)}


def review_submission(lesson, user_id, items, answers, tokens):
    """Validate all proofs against raw source items, never projected client data.

    `items` may be the route's normalized projection. Its length/canonical text
    must correspond to the source indexes; tokens always hash the full raw item.
    """
    from app.curriculum.translation_variants import translation_reference

    source = _source_items(lesson)
    if source is None:
        return _failure('unsupported_mode', completed=False, passed=False, score=None)
    if not isinstance(items, list) or len(items) != len(source):
        return _failure('invalid_item', completed=False, passed=False, score=None)
    for authored, projected in zip(source, items, strict=True):
        if not isinstance(authored, dict) or not isinstance(projected, dict):
            return _failure('invalid_item', completed=False, passed=False, score=None)
        authored_reference = translation_reference(str(authored.get('english') or '').strip(),
                                                   str(authored.get('russian') or '').strip())
        projected_reference = translation_reference(str(projected.get('english') or '').strip(),
                                                    str(projected.get('russian') or '').strip())
        if authored_reference != projected_reference:
            return _failure('invalid_item', completed=False, passed=False, score=None)
    if not isinstance(answers, list) or len(answers) != len(source):
        return _failure('invalid_answers', completed=False, passed=False, score=None)
    results = []
    for index, answer in enumerate(answers):
        token = (tokens[index] if index < len(tokens) else None) if isinstance(tokens, list) else (
            tokens.get(str(index), tokens.get(index)) if isinstance(tokens, dict) else None)
        result = review_item(lesson, user_id, index, answer)
        if result.get('status') == 'needs_review' and token:
            serializer = _serializer()
            proof = _proof(lesson, user_id, index, source[index], result['answer'], 'reviewed')
            if serializer is not None and _load_token(serializer, token) == proof:
                result.update(status='self_reviewed', correct=None, review_token=token)
            else:
                result = _failure('invalid_review_token', index=index)
        results.append(result)
    automatic = sum(item.get('status') == 'matched' for item in results)
    reviewed = [item['index'] for item in results if item.get('status') == 'self_reviewed']
    accepted = all(item.get('status') in ('matched', 'self_reviewed') for item in results)
    base = {
        'success': accepted, 'completed': accepted, 'passed': accepted, 'score': None,
        'assessment': 'self_review', 'correct_items': automatic, 'reviewed_items': reviewed,
        'total_items': len(source), 'item_results': results,
    }
    if not accepted:
        error = next((item['error'] for item in results if not item.get('success')), 'review_required')
        base['error'] = error
    return base
