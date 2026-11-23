"""Shared, read-only A1 route. Activity coverage is not a proficiency score."""
from __future__ import annotations

from typing import Any

SKILLS = {
    'reading': 'Чтение', 'listening': 'Аудирование',
    'speaking': 'Говорение', 'writing': 'Письмо',
}
LESSON_SKILLS = {
    'reading': ('reading',), 'text': ('reading',),
    'listening_quiz': ('listening',), 'listening_immersion': ('listening',),
    'listening_immersion_quiz': ('listening',), 'audio_fill_blank': ('listening',),
    'dictation': ('listening', 'writing'),
    'pronunciation': ('speaking',), 'shadow_reading': ('speaking', 'reading'),
    'writing_prompt': ('writing',),
}


def lesson_skills(kind: str) -> tuple[str, ...]:
    return LESSON_SKILLS.get(kind, ())


def is_a1_lesson(lesson: Any) -> bool:
    return getattr(getattr(getattr(lesson, 'module', None), 'level', None), 'code', None) == 'A1'


def is_a1_learner(user_id: int, db: Any) -> bool:
    from app.auth.models import User
    from app.daily_plan.linear.progression import find_next_lesson_linear

    lesson = find_next_lesson_linear(user_id, db)
    if lesson is not None:
        return is_a1_lesson(lesson)
    user = db.session.get(User, user_id)
    return bool(user and user.onboarding_level == 'A1')


def project_journey(module: Any, lessons: list[Any], completed: set[int],
                    required: list[dict], optional: list[dict]) -> dict | None:
    """Project only existing steps; map links obey the current daily-plan queue."""
    if getattr(getattr(module, 'level', None), 'code', None) != 'A1':
        return None
    raw = module.raw_content if isinstance(module.raw_content, dict) else {}
    # Legacy imports retain the full {module: ...} document.
    raw = raw.get('module', raw)
    raw = raw if isinstance(raw, dict) else {}
    authored = raw.get('learning_journey') or {}
    authored = authored if isinstance(authored, dict) else {}
    goal = authored.get('goal')
    goal = goal if isinstance(goal, str) and goal.strip() else module.description or module.title
    def done(item):
        return bool(item.get('completed'))
    next_required = next((x for x in required if not done(x) and not x.get('skipped') and not x.get('blocked')), None)
    optional_open = bool(required) and all(done(x) or x.get('skipped') for x in required)
    next_optional = next((x for x in optional if not done(x)), None) if optional_open else None
    current_ids = {x['id'] for x in (next_required, next_optional) if x}
    by_lesson = {}
    corrections = {}
    for item in [*required, *optional]:
        data = item.get('data') or {}
        if data.get('quiz_phase') == 'correction' and data.get('lesson_id'):
            corrections.setdefault(data['lesson_id'], item)
        elif data.get('lesson_id'):
            by_lesson.setdefault(data['lesson_id'], item)
    today_ids = {(x.get('data') or {}).get('lesson_id') for x in required}
    nodes = []
    for lesson in lessons:
        correction = corrections.get(lesson.id)
        item = correction or by_lesson.get(lesson.id)
        available = bool(item and item['id'] in current_ids and not item.get('blocked'))
        state = ('correction' if correction else 'completed' if lesson.id in completed
                 else 'current' if available else 'locked')
        nodes.append({
            'lesson_id': lesson.id, 'number': lesson.number, 'title': lesson.title,
            'lesson_type': lesson.type, 'skills': list(lesson_skills(lesson.type)),
            'state': state, 'today': lesson.id in today_ids,
            'item_id': item['id'] if item and available else None,
            'url': item.get('url') if item and available else None,
        })
    return {
        'version': 1, 'level': 'A1', 'module_id': module.id,
        'module_number': module.number, 'title': module.title, 'goal': goal,
        'completed': sum(x['state'] == 'completed' for x in nodes), 'total': len(nodes),
        'skills': [
            {'id': key, 'title': title,
             'completed': sum(x['state'] == 'completed' and key in x['skills'] for x in nodes),
             'total': sum(key in x['skills'] for x in nodes)}
            for key, title in SKILLS.items()
        ],
        'nodes': nodes,
    }


def build_journey(user_id: int, db: Any, lesson: Any,
                  required: list[dict], optional: list[dict]) -> dict | None:
    from app.curriculum.models import LessonProgress, Lessons

    # Keep the daily route anchored to its frozen course work even after the
    # learner finishes it and progression advances to another module/level.
    course = [x for x in required if x.get('kind') == 'curriculum'
              and (x.get('data') or {}).get('lesson_id')]
    anchor = next((x for x in course if not x.get('completed')), course[-1] if course else None)
    if anchor:
        lesson = db.session.get(Lessons, anchor['data']['lesson_id']) or lesson
    if not is_a1_lesson(lesson):
        return None
    module = lesson.module
    lessons = db.session.query(Lessons).filter_by(module_id=module.id).order_by(Lessons.number, Lessons.id).all()
    completed = {row[0] for row in db.session.query(LessonProgress.lesson_id).join(
        Lessons, Lessons.id == LessonProgress.lesson_id,
    ).filter(LessonProgress.user_id == user_id, LessonProgress.status == 'completed',
             Lessons.module_id == module.id).all()}
    return project_journey(module, lessons, completed, required, optional)
