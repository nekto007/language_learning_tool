"""Skill-slot builder respects linear curriculum ordering.

The unified daily plan must progress lessons sequentially: SRS → curriculum
lesson N → reading → curriculum lesson N+1 → etc. Skill-type lessons
(listening_immersion, dictation, pronunciation, writing_prompt, …) are
NOT exempt from this — the slot builder must not hand the user a
listening lesson at module-number 7 while the spine is still at lesson 5,
because the lesson-access decorator would reject the click with
"complete previous lessons first".

These tests cover the slot-builder fix in app/daily_plan/items/skills.py:
candidate skill lessons must have ``number <= next_lesson.number``.
"""
from __future__ import annotations

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.items.skills import _find_next_skill_lesson
from app.utils.db import db


_LISTENING_TYPES = frozenset({
    'listening_immersion', 'listening_immersion_quiz',
    'dictation', 'audio_fill_blank',
})


@pytest.fixture
def fresh_level(db_session):
    level = CEFRLevel(code='B1', name='B1 — Intermediate', order=30)
    db_session.add(level)
    db_session.commit()
    return level


def _module(db_session, level, number=1):
    m = Module(level_id=level.id, number=number, title=f'Module {number}')
    db_session.add(m)
    db_session.commit()
    return m


def _lesson(db_session, module, number, lesson_type='vocabulary'):
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'Lesson {number}',
        type=lesson_type,
        order=number,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _complete(db_session, user, lesson, score=90.0):
    progress = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=score,
    )
    db_session.add(progress)
    db_session.commit()


class TestSkillSlotRespectsSpineOrdering:
    def test_does_not_offer_listening_ahead_of_spine(
        self, app, db_session, test_user, fresh_level,
    ):
        """Bug report: spine at lesson 5 (sentence_completion), listening
        is at lesson 7 — the skill slot used to offer lesson 7, but clicking
        it failed access check. Now: must not offer.
        """
        mod = _module(db_session, fresh_level, number=1)
        l1 = _lesson(db_session, mod, 1, 'vocabulary')
        l2 = _lesson(db_session, mod, 2, 'card')
        l3 = _lesson(db_session, mod, 3, 'collocation_matching')
        l4 = _lesson(db_session, mod, 4, 'grammar')
        _lesson(db_session, mod, 5, 'sentence_completion')
        _lesson(db_session, mod, 6, 'reading')
        _lesson(db_session, mod, 7, 'listening_immersion')
        for ls in (l1, l2, l3, l4):
            _complete(db_session, test_user, ls)

        result = _find_next_skill_lesson(test_user.id, db, _LISTENING_TYPES)
        assert result is None  # spine at 5, listening at 7 — not offered yet

    def test_offers_listening_when_spine_reaches_it(
        self, app, db_session, test_user, fresh_level,
    ):
        """Same module, but user advances spine to lesson 7 (listening). Now
        listening IS at the spine's current position — offer it.
        """
        mod = _module(db_session, fresh_level, number=1)
        lessons = [_lesson(db_session, mod, n, 'vocabulary') for n in range(1, 7)]
        listening = _lesson(db_session, mod, 7, 'listening_immersion')
        for ls in lessons:
            _complete(db_session, test_user, ls)

        result = _find_next_skill_lesson(test_user.id, db, _LISTENING_TYPES)
        assert result is not None
        assert result.id == listening.id

    def test_offers_earlier_listening_when_skipped(
        self, app, db_session, test_user, fresh_level,
    ):
        """If listening is at lesson 3 (before spine's current next lesson 5),
        and somehow not completed, it's still offerable — number <= 5 holds.
        Normally find_next_lesson_linear would catch it as spine's next, but
        a skipped/deferred state can leave it incomplete with spine past it.
        """
        mod = _module(db_session, fresh_level, number=1)
        l1 = _lesson(db_session, mod, 1, 'vocabulary')
        l2 = _lesson(db_session, mod, 2, 'card')
        listening = _lesson(db_session, mod, 3, 'listening_immersion')
        l4 = _lesson(db_session, mod, 4, 'grammar')
        # User completed 1, 2, 4 but skipped listening at 3 — spine still
        # picks 3 as next, but if a separate query passes a higher next_lesson
        # the helper would still return listening 3 because 3 <= 4 <= n.
        for ls in (l1, l2, l4):
            _complete(db_session, test_user, ls)

        result = _find_next_skill_lesson(test_user.id, db, _LISTENING_TYPES)
        assert result is not None
        assert result.id == listening.id

    def test_returns_none_when_no_listening_in_module(
        self, app, db_session, test_user, fresh_level,
    ):
        """Module without listening lessons returns None regardless of spine."""
        mod = _module(db_session, fresh_level, number=1)
        l1 = _lesson(db_session, mod, 1, 'vocabulary')
        _lesson(db_session, mod, 2, 'grammar')
        _complete(db_session, test_user, l1)

        result = _find_next_skill_lesson(test_user.id, db, _LISTENING_TYPES)
        assert result is None
