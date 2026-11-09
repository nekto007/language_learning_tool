"""A focused entry point into the existing daily plan for early learners."""
from __future__ import annotations

from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.action_selection import next_unified_item

_OUTCOMES = {
    'vocabulary': 'Познакомьтесь со словами и фразами и послушайте, как они звучат.',  # noqa: RUF001
    'flashcards': 'Вспомните значения знакомых слов и закрепите их на карточках.',
    'card': 'Вспомните значения знакомых слов и закрепите их на карточках.',
    'grammar': 'Разберите правило и посмотрите, как оно работает в примерах.',
    'reading': 'Прочитайте текст и разберитесь в его смысле.',  # noqa: RUF001
    'listening_immersion': 'Послушайте разговор и разберитесь в знакомых фразах.',
    'collocation_matching': 'Соедините части выражений и закрепите полезные сочетания.',
    'sentence_completion': 'Примените знакомые слова и правило в предложениях.',
}
_KIND_OUTCOMES = {
    'srs': 'Вспомните знакомые слова с помощью короткого повторения.',  # noqa: RUF001
    'reading': 'Продолжите чтение и разберитесь в следующем фрагменте.',
    'listening': 'Потренируйтесь понимать английскую речь на слух.',
    'speaking': 'Произнесите знакомые слова и фразы вслух.',
    'writing': 'Составьте короткий ответ на английском.',
    'grammar_review': 'Повторите правило на практических примерах.',
    'error_review': 'Разберите прошлые ошибки и попробуйте ещё раз.',
}


def build_study_start_card(user_id, db, plan, completion):
    """Reuse the plan's exact URL and let the lesson restore its own state.

    The card is temporary: it disappears after two attained curriculum lessons.
    It does not create progress, reset answers, or invent a new lesson order.
    """
    if plan.get('day_secured'):
        return None  # Keep the existing day-completion celebration visible.
    item = next_unified_item(plan, completion)
    if item is None or not str(item['url']).startswith('/') or str(item['url']).startswith('//'):
        return None
    required = plan.get('required') or []
    # Optional cards unlock only when required items are completed or skipped.
    if not any(item is candidate for candidate in required) and (
        not required or not all(
            candidate.get('completed') or completion.get(candidate.get('id')) or candidate.get('skipped')
            for candidate in required
        )
    ):
        return None
    completed = db.session.query(LessonProgress.id).filter(
        LessonProgress.user_id == user_id, LessonProgress.status == 'completed',
    ).limit(2).all()
    if len(completed) >= 2:
        return None
    if not completed and item.get('kind') != 'curriculum':
        return None  # A long-time book/SRS user is not a first-time learner.
    data = item.get('data') or {}
    lesson_type = item.get('lesson_type')
    resumed = False
    level, topic = data.get('level_code'), data.get('module_title')
    if item.get('kind') == 'curriculum':
        lesson_id = data.get('lesson_id')
        if not isinstance(lesson_id, int) or isinstance(lesson_id, bool):
            return None
        lesson = db.session.get(Lessons, lesson_id)
        if lesson is None:
            return None
        progress = db.session.query(LessonProgress).filter_by(user_id=user_id, lesson_id=lesson_id).first()
        if progress and progress.status == 'completed':
            return None  # A stale plan must not advertise replay as new work.
        resumed = bool(progress and progress.status == 'in_progress')
        lesson_type = lesson.type
        if lesson.module:
            topic = lesson.module.title
            if lesson.module.level:
                level = lesson.module.level.code
    elif item.get('kind') not in _KIND_OUTCOMES:
        return None
    first = not completed
    try:
        minutes = max(0, int(item.get('eta_minutes') or 0))
    except (TypeError, ValueError):
        minutes = 0
    return {
        'title': item.get('title') or 'Занятие по английскому',
        'eyebrow': 'Продолжим занятие' if resumed else ('Ваше первое занятие' if first else 'Следующее занятие'),
        'cta': 'Продолжить занятие' if resumed else ('Начать первое занятие' if first else 'Начать следующее занятие'),
        'outcome': _OUTCOMES.get(lesson_type) or _KIND_OUTCOMES.get(item.get('kind'))
                   or 'Примените изученное в короткой практике.',
        'url': item['url'], 'minutes': minutes, 'level': level, 'topic': topic,
        'resumed': resumed, 'lesson_type': lesson_type or item.get('kind'),
    }
