"""Keep legacy admin forms from overwriting compiled guided material."""
from flask import Response, abort, redirect, request, url_for

from app.curriculum.models import Lessons
from app.grammar_lab.guided_authoring import is_guided_content
from app.grammar_lab.models import GrammarTopic


def _compiled(content: object) -> bool:
    return isinstance(content, dict) and bool(
        content.get('guided_catalog_digest') or content.get('guided_content_version')
        or content.get('guided_exercise_ids')
    )


def _topic(topic_id: int) -> GrammarTopic | None:
    query = GrammarTopic.query.filter_by(id=topic_id)
    if request.method == 'POST':
        query = query.with_for_update().populate_existing()
    return query.one_or_none()


def _guided_location(topic: GrammarTopic | None) -> Response:
    if topic is None or not is_guided_content(topic.content):
        abort(409, 'This compiled material must be updated by its guided installer.')
    return redirect(url_for('guided_topics_admin.edit', topic_id=topic.id,
                            materials_query=request.args.get('materials_query')), code=303)


def managed_topic_editor(topic_id: int) -> Response | None:
    topic = _topic(topic_id)
    if topic and _compiled(topic.content):
        return _guided_location(topic)
    return None


def managed_lesson_editor(lesson: Lessons) -> Response | None:
    if lesson.type != 'grammar':
        return None
    topic = _topic(lesson.grammar_topic_id) if lesson.grammar_topic_id is not None else None
    if _compiled(lesson.content) or (topic and _compiled(topic.content)):
        return _guided_location(topic)
    return None
