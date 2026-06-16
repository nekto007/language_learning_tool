"""Static daily-plan snapshot composer.

Builds the required-section item list for the snapshot persisted in
``DailyPlanLog.plan_json`` (v2 format). The output is a list of plain
dicts — they go straight into ``plan_json.items`` and survive every
request for the day. Completion flags are NOT included; they are
overlaid live each request from real activity (see ``snapshot.py``).

Tier-driven composition:
- ``calm``      → [curriculum_1, SRS, reading]
- ``normal``    → [curriculum_1, SRS, reading, curriculum_2]
- ``intensive`` → [curriculum_1, SRS, reading, curriculum_2, curriculum_3]

Reading slot is dropped when the user has no ``UserReadingPreference``
or picked the book today (mid-day book pick joins required tomorrow,
matching prior behaviour). Reading absence simply yields a smaller
required list; the orchestrator separately surfaces ``setup_book``.

Final-test guard:
- When a ``final_test`` lesson is the FIRST curriculum lesson in the
  set, the order rearranges to ``[SRS, grammar_prep, reading, FT]`` —
  warmup before the heavy test.
- When ``final_test`` is the 2nd/3rd curriculum lesson, ``grammar_prep``
  is inserted immediately BEFORE it without reordering other items.
- ``grammar_prep`` resolves the first ``type='grammar'`` lesson of the
  final test's module (ordered by ``Lessons.number``) with a non-null
  ``grammar_topic_id`` and points at
  ``/grammar-lab/practice/topic/<topic_id>?return_url=<final_test_url>``.
- If the module has no grammar topic, the prep step is skipped.

Skill kinds (listening / speaking / writing) are intentionally absent
from required — they had their own slot builders that double-counted
audio_fill_blank-style lessons through both curriculum AND a skill
slot, inflating day-secured (audit follow-up). Skill XP awards
(``maybe_award_listening_xp`` etc.) remain as bonus XP for any matching
activity, but never gate the day.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.items.curriculum import build_curriculum_item
from app.daily_plan.items.reading import build_reading_item, get_user_reading_preference
from app.daily_plan.items.setup import book_selected_today
from app.daily_plan.items.srs import build_srs_item
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.tier import Tier

logger = logging.getLogger(__name__)

# Number of curriculum slots per tier (the SRS / reading slots are
# orthogonal and counted separately).
_TIER_CURRICULUM_COUNT: dict[Tier, int] = {
    'calm': 1,
    'normal': 2,
    'intensive': 3,
}

# Lesson types whose curriculum slot is itself a card / flashcards session —
# in that case the SRS slot in the same plan is swapped for a deck quiz so
# the user doesn't face two cards-form activities in a row.
_CARD_LESSON_TYPES = frozenset({'card', 'flashcards'})

_GRAMMAR_PREP_ETA_MINUTES = 10


def build_required_snapshot(
    user_id: int,
    tier: Tier,
    db: Any,
) -> list[dict[str, Any]]:
    """Compose the required-section item dicts for today's snapshot.

    Returns an empty list when no curriculum lesson is available
    (graduated user, or onboarding has not yet produced an eligible
    lesson). The orchestrator interprets ``required=[]`` as «day cannot
    be closed via the unified path» and surfaces setup items instead.
    """
    curriculum_lessons = _collect_curriculum_chain(
        user_id, db, count=_TIER_CURRICULUM_COUNT[tier],
    )
    if not curriculum_lessons:
        return []

    items: list[dict[str, Any]] = []
    first_lesson = curriculum_lessons[0]
    first_is_card = (
        getattr(first_lesson, 'type', None) in _CARD_LESSON_TYPES
    )

    curriculum_item = _curriculum_item_dict(user_id, db, first_lesson)
    srs_item = _srs_item_dict(user_id, db, as_deck_quiz=first_is_card)
    reading_item = _reading_item_dict(user_id, db)

    final_test_lesson, ft_position = _find_final_test(curriculum_lessons)

    if final_test_lesson is not None and ft_position == 0:
        # Warmup layout: SRS → grammar_prep → reading → final_test.
        # Override the curriculum slot type since the first lesson IS
        # the final test, and the deck-quiz swap (first_is_card) cannot
        # apply because final_test is not a card lesson.
        srs_item = _srs_item_dict(user_id, db, as_deck_quiz=False)
        if srs_item is not None:
            items.append(srs_item)

        prep_item = _grammar_prep_item_dict(db, final_test_lesson)
        if prep_item is not None:
            items.append(prep_item)

        if reading_item is not None:
            items.append(reading_item)

        items.append(curriculum_item)  # the final_test itself
        return items

    # Standard layout: curriculum_1, SRS, reading, curriculum_2, curriculum_3.
    items.append(curriculum_item)
    if srs_item is not None:
        items.append(srs_item)
    if reading_item is not None:
        items.append(reading_item)

    for i, lesson in enumerate(curriculum_lessons[1:], start=1):
        if final_test_lesson is not None and i == ft_position:
            prep_item = _grammar_prep_item_dict(db, final_test_lesson)
            if prep_item is not None:
                items.append(prep_item)
        items.append(_curriculum_item_dict(user_id, db, lesson))

    return items


def _collect_curriculum_chain(
    user_id: int,
    db: Any,
    count: int,
) -> list[Any]:
    """Return the next ``count`` incomplete spine lessons (or fewer if
    the spine is shorter / blocked).

    Successive ``find_next_lesson_linear`` calls with growing
    ``exclude_lesson_ids`` walk forward on the spine while honouring
    every prerequisite gate the live builder enforces. We never reach
    past a hard-blocked module — the same as today's optional
    continuation queue.
    """
    excluded: set[int] = set()
    lessons: list[Any] = []
    for _ in range(max(count, 0)):
        nxt = find_next_lesson_linear(user_id, db, exclude_lesson_ids=excluded or None)
        if nxt is None:
            break
        lessons.append(nxt)
        excluded.add(int(nxt.id))
    return lessons


def _find_final_test(lessons: list[Any]) -> tuple[Optional[Any], int]:
    """Return (final_test_lesson, position) or (None, -1).

    Position is the 0-based index into ``lessons``.
    """
    for i, lesson in enumerate(lessons):
        if getattr(lesson, 'type', None) == 'final_test':
            return lesson, i
    return None, -1


def _curriculum_item_dict(
    user_id: int,
    db: Any,
    lesson: Any,
) -> dict[str, Any]:
    """Build a curriculum PlanItem dict for the snapshot.

    Delegates to ``build_curriculum_item`` and strips the live
    completion fields — the snapshot only carries composition, not
    today's state. ``next_lesson`` is passed explicitly so the builder
    does not re-resolve the spine (we already chose this lesson).
    """
    item = build_curriculum_item(
        user_id, db, section='required', next_lesson=lesson,
    )
    if item is None:
        # Defensive — caller already verified the lesson exists.
        raise RuntimeError(
            f"build_curriculum_item returned None for lesson {lesson.id}"
        )
    return _strip_for_snapshot(item.to_dict())


def _srs_item_dict(
    user_id: int,
    db: Any,
    as_deck_quiz: bool,
) -> Optional[dict[str, Any]]:
    """Build the SRS PlanItem dict, or None when SRS has nothing to show.

    The deck-quiz swap keeps the old user-facing rule: a deck quiz only
    replaces ``srs:global`` when the user actually has
    deck words (otherwise the slot would be a dead placeholder).
    """
    if as_deck_quiz:
        from app.daily_plan.linear.slots.srs_slot import _count_user_deck_quiz_words
        if _count_user_deck_quiz_words(user_id, db) <= 0:
            as_deck_quiz = False

    item = build_srs_item(
        user_id, db, section='required',
        as_deck_quiz=as_deck_quiz,
    )
    if item is None:
        return None

    snapshot = _strip_for_snapshot(item.to_dict())
    # Freeze the daily SRS goal so "X из 30" stays "30" all day rather
    # than tracking the shrinking live ``total_show``.
    data = snapshot.get('data') or {}
    goal_total = _srs_goal_total(data)
    if goal_total is not None:
        data['goal_total'] = goal_total
    snapshot['data'] = data
    return snapshot


def _srs_goal_total(data: dict[str, Any]) -> Optional[int]:
    """Frozen daily SRS goal = still-to-show + already-done today."""
    if 'total_show' in data:
        total = (
            int(data.get('total_show') or 0)
            + int(data.get('reviews_today') or 0)
            + int(data.get('new_today') or 0)
        )
        return total if total > 0 else None
    if 'word_limit' in data:  # deck-quiz variant
        limit = int(data.get('word_limit') or 0)
        return limit if limit > 0 else None
    return None


def _reading_item_dict(
    user_id: int,
    db: Any,
) -> Optional[dict[str, Any]]:
    """Build the reading PlanItem dict, or None when no eligible book.

    Mirrors the legacy required rule: a freshly-picked book joins
    required TOMORROW, not today, so a mid-day book pick can't
    retroactively void an already-secured day.
    """
    pref = get_user_reading_preference(user_id, db)
    if pref is None:
        return None
    if book_selected_today(user_id, db):
        return None
    item = build_reading_item(user_id, db, section='required', focus=None)
    if item is None:
        return None
    return _strip_for_snapshot(item.to_dict())


def _grammar_prep_item_dict(
    db: Any,
    final_test_lesson: Any,
) -> Optional[dict[str, Any]]:
    """Build the «повторение грамматики модуля» step before a final test.

    Topic resolution: the first ``type='grammar'`` lesson in the same
    module by ``Lessons.number`` with a non-null ``grammar_topic_id``.
    If the module has no such lesson, returns None — the final test
    runs without the prep step.

    URL points at the standalone grammar-lab practice for that topic
    with ``?return_url=`` set to the final_test page so finishing the
    practice routes the user back into the plan flow.
    """
    from app.curriculum.models import Lessons
    from app.grammar_lab.models import GrammarTopic

    module_id = getattr(final_test_lesson, 'module_id', None)
    if module_id is None:
        return None

    grammar_lesson = (
        db.session.query(Lessons)
        .filter(
            Lessons.module_id == module_id,
            Lessons.type == 'grammar',
            Lessons.grammar_topic_id.isnot(None),
        )
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .first()
    )
    if grammar_lesson is None:
        return None

    topic = db.session.get(GrammarTopic, grammar_lesson.grammar_topic_id)
    if topic is None:
        return None

    final_test_url = f'/lesson/{int(final_test_lesson.id)}/final_test'
    prep_url = (
        f'/grammar-lab/topic/{topic.slug}'
        f'?return_url={final_test_url}'
    )

    module = getattr(final_test_lesson, 'module', None)
    level = getattr(module, 'level', None) if module is not None else None

    return {
        'id': f'grammar_review:module:{int(module_id)}:topic:{int(topic.id)}:pre_ft',
        'section': 'required',
        'kind': 'grammar_review',
        'title': topic.title,
        'subtitle': 'Повторение грамматики перед итоговым тестом',
        'lesson_type': None,
        'eta_minutes': _GRAMMAR_PREP_ETA_MINUTES,
        'url': prep_url,
        'completion_signal': 'grammar_exercises',
        'data': {
            'topic_id': int(topic.id),
            'topic_slug': topic.slug,
            'topic_title': topic.title,
            'topic_title_ru': getattr(topic, 'title_ru', None),
            'topic_level': topic.level,
            'module_id': int(module_id),
            'final_test_lesson_id': int(final_test_lesson.id),
            'pre_final_test': True,
        },
    }


# Fields that belong to live state, not snapshot composition.
# ``completed`` is recomputed every request from real activity, so
# we strip it from the saved snapshot to avoid stale "true" leaking
# from an early build into tomorrow's roll-over.
_LIVE_FIELDS = ('completed', 'skipped', 'blocked')


def _strip_for_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """Drop fields that are computed live each request."""
    cleaned = {k: v for k, v in item.items() if k not in _LIVE_FIELDS}
    return cleaned
