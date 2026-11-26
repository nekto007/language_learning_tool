"""Find the installed guided topic that owns the exercise cited in a dispute."""

from app.admin.services.guided_lesson_import import is_published_guided_lesson
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.models import Lessons
from app.grammar_lab.guided_authoring import is_guided_content
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db


def _key_position(content: dict, key: str) -> int | None:
    rows = content.get('exercises')
    if not isinstance(rows, list):
        return None
    matches = [index for index, row in enumerate(rows) if isinstance(row, dict) and row.get('guided_key') == key]
    return matches[0] if len(matches) == 1 else None


def guided_topic_for_dispute(dispute: AnswerDispute) -> GrammarTopic | None:
    evidence = dispute.evidence
    row = evidence.get('row') if isinstance(evidence, dict) else None
    key = row.get('guided_key') if isinstance(row, dict) else None
    if not isinstance(key, str) or not key:
        return None

    if dispute.grammar_exercise_id is not None:
        exercise = db.session.get(GrammarExercise, dispute.grammar_exercise_id)
        if (exercise is None or not isinstance(exercise.content, dict) or exercise.content.get('guided_retired')
                or exercise.content.get('guided_key') != key):
            return None
        topic = exercise.topic
        if topic is None or not is_guided_content(topic.content):
            return None
        position = _key_position(topic.content, key)
        ids = topic.content.get('guided_exercise_ids')
        if (position is not None and isinstance(ids, list) and position < len(ids)
                and ids[position] == exercise.id and ids.count(exercise.id) == 1):
            return topic
        return None

    if dispute.lesson_id is None:
        return None
    lesson = db.session.get(Lessons, dispute.lesson_id)
    if lesson is None or not is_published_guided_lesson(lesson):
        return None
    topic = lesson.grammar_topic
    if (topic is not None and is_guided_content(topic.content)
            and lesson.content['guided_catalog_digest'] == topic.content['guided_catalog_digest']
            and _key_position(lesson.content, key) is not None
            and _key_position(topic.content, key) is not None):
        return topic
    return None
