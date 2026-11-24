"""Recover and edit verified authored data for an installed guided topic."""
from copy import deepcopy
from typing import Any

from app.grammar_lab.content_catalog import content_digest, validate_authored_topic
from app.grammar_lab.models import GrammarTopic

_COMPILED_EXERCISE_FIELDS = {'answer', 'guided_key', 'guided_rule_id', 'guided_revision', 'theory_help'}


def is_guided_content(content: object) -> bool:
    return isinstance(content, dict) and bool(content.get('guided_catalog_digest'))


def recover_document(topic: GrammarTopic) -> dict[str, Any] | None:
    content = topic.content or {}
    if not is_guided_content(content):
        return None
    expected = content['guided_catalog_digest']
    candidate = content.get('guided_author_document')
    if isinstance(candidate, dict) and content_digest(candidate) == expected:
        return deepcopy(candidate)
    try:
        compiled_steps = content['learning_steps']
        rows = content['exercises']
        steps = []
        for step in compiled_steps:
            body = step['theory'][0]['body']
            exercises = [{key: deepcopy(value) for key, value in rows[int(index)].items()
                          if key not in _COMPILED_EXERCISE_FIELDS} for index in step['question_ids']]
            steps.append({'id': step['id'], 'title': step['title'], 'body': body, 'exercises': exercises})
        document = {
            'topic_slug': topic.slug, 'version': content['guided_content_version'],
            'title': content['guided_display_title'], 'goal': content['learning_goal'], 'steps': steps,
        }
        reference = [{'title': row['subtitle'], 'body': row['description']}
                     for row in content['sections'][len(steps):]]
        if reference or content_digest(document) != expected:
            document['reference_sections'] = reference
        if content_digest(document) == expected:
            return validate_authored_topic(document)
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    return None


def edited_document(base: dict, title: str, goal: str, bodies: list[str]) -> dict[str, Any]:
    if len(bodies) != len(base['steps']):
        raise ValueError('Шаги изменились. Откройте тему заново.')
    result = deepcopy(base)
    result['title'], result['goal'] = title.strip(), goal.strip()
    for step, body in zip(result['steps'], bodies, strict=True):
        # Browser form submissions use CRLF even for textareas holding LF.
        step['body'] = body.replace('\r\n', '\n')
    return result
