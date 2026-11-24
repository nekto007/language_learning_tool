"""Keep the published guided projection owned by the guided installer."""
# ruff: noqa: RUF001 -- conflict messages are shown in Russian in the import forms.

from app.curriculum.models import Lessons


def is_published_guided_lesson(lesson: Lessons) -> bool:
    return (
        lesson.type == 'grammar'
        and lesson.grammar_topic_id is not None
        and isinstance(lesson.content, dict)
        and bool(lesson.content.get('guided_catalog_digest'))
    )


def _external_key(content: object) -> str:
    key = content.get('external_key') if isinstance(content, dict) else None
    return key.strip() if isinstance(key, str) else ''


def preserved_guided_lessons(lessons: list[Lessons], source: list[dict]) -> dict[int, Lessons]:
    """Identify rows to skip before any lesson writes, by source index.

    The guided installer can change a lesson title. Keyless source files may
    still address that grammar lesson by its position, if the match is unique.
    A course import must not move a published guided lesson.
    """
    guided = {lesson.number: lesson for lesson in lessons if is_published_guided_lesson(lesson)}
    if not guided:
        return {}

    preserved = {}
    used = set()
    for index, row in enumerate(source):
        number = row.get('lesson_number') or row.get('order') or row.get('id')
        kind = row.get('lesson_type') or row.get('type')
        key = _external_key(row.get('content'))
        at_position = guided.get(number)
        keyed = [lesson for lesson in lessons if _external_key(lesson.content) == key] if key else []
        raw_title = row.get('title')
        title = raw_title.strip().lower() if isinstance(raw_title, str) else ''
        named = [
            lesson for lesson in lessons
            if not key and kind == lesson.type and title and (lesson.title or '').strip().lower() == title
        ]
        if at_position is None and not any(is_published_guided_lesson(match) for match in keyed + named):
            continue
        if (
            at_position is None
            or kind != 'grammar'
            or (key and keyed != [at_position])
            or any(match is not at_position for match in named)
            or at_position.id in used
        ):
            raise ValueError(
                f'Урок №{number} конфликтует с опубликованным пошаговым уроком. '
                'Проверьте тип, номер и внешний ключ в исходнике.'
            )
        preserved[index] = at_position
        used.add(at_position.id)
    return preserved
