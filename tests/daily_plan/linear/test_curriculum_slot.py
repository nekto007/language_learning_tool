"""Tests for the linear curriculum slot.

Verifies that build_curriculum_slot returns the next lesson on the linear
spine for each of the 12 curriculum lesson types, with correct URL, ETA,
and completed state. Also covers the "curriculum complete" empty case
and defensive handling when the resolved lesson already has a
``completed`` LessonProgress row.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import patch

import pytest

from app.achievements.models import StreakEvent
from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.curriculum_slot import (
    _DEFAULT_ETA_MINUTES,
    _LESSON_ETA_MINUTES,
    build_curriculum_slot,
)
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_source_for_lesson_type
from app.utils.db import db as real_db


# 12 lesson types explicitly listed in the plan (plus legacy aliases).
TWELVE_LESSON_TYPES = [
    'vocabulary',
    'card',
    'grammar',
    'quiz',
    'reading',
    'listening_quiz',
    'dialogue_completion_quiz',
    'ordering_quiz',
    'translation_quiz',
    'listening_immersion',
    'listening_immersion_quiz',
    'final_test',
]


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session, onboarding_level: str | None = None) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'linslot_{suffix}',
        email=f'linslot_{suffix}@example.com',
        active=True,
        onboarding_level=onboarding_level,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, code: str, order: int) -> CEFRLevel:
    level = CEFRLevel(
        code=code,
        name=f'Level {code}',
        description='desc',
        order=order,
    )
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'{level.code} M{number}',
        description='desc',
        raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(
    db_session,
    module: Module,
    number: int,
    lesson_type: str = 'quiz',
) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'{module.title} L{number} ({lesson_type})',
        type=lesson_type,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _complete(db_session, user: User, lesson: Lessons) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=100.0,
    ))
    db_session.commit()


def _complete_at(
    db_session,
    user: User,
    lesson: Lessons,
    *,
    completed_at: datetime,
) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=100.0,
        completed_at=completed_at,
    ))
    db_session.commit()


def _award_linear_curriculum_event(
    db_session,
    user: User,
    lesson: Lessons,
    *,
    event_date: date,
) -> None:
    source = get_source_for_lesson_type(lesson.type)
    assert source is not None
    db_session.add(StreakEvent(
        user_id=user.id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=event_date,
        coins_delta=0,
        details={'source': source, 'xp': 1},
    ))
    db_session.commit()


@pytest.fixture
def curriculum(db_session):
    """Single level / single module with one lesson per lesson_type."""
    level = _make_level(db_session, _unique_code(), 1)
    module = _make_module(db_session, level, 1)
    lessons: dict[str, Lessons] = {}
    for i, lesson_type in enumerate(TWELVE_LESSON_TYPES, start=1):
        lessons[lesson_type] = _make_lesson(db_session, module, i, lesson_type)
    return {'level': level, 'module': module, 'lessons': lessons}


def _expected_url(lesson) -> str:
    if lesson.type in {'card', 'flashcards'}:
        return (
            f'/learn/{lesson.id}/?source=linear_plan_card'
            '&from=linear_plan&slot=curriculum'
        )
    return f'/learn/{lesson.id}/?from=linear_plan&slot=curriculum'


class TestBuildCurriculumSlotByType:
    @pytest.mark.parametrize('lesson_type', TWELVE_LESSON_TYPES)
    def test_slot_for_each_lesson_type(self, db_session, curriculum, lesson_type):
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)

        # Complete every lesson except the target one so it becomes the next.
        for t, lesson in curriculum['lessons'].items():
            if t != lesson_type:
                _complete(db_session, user, lesson)

        target = curriculum['lessons'][lesson_type]

        slot = build_curriculum_slot(user.id, real_db)

        assert isinstance(slot, LinearSlot)
        assert slot.kind == 'curriculum'
        assert slot.lesson_type == lesson_type
        assert slot.title == target.title
        assert slot.url == _expected_url(target)
        assert slot.eta_minutes == _LESSON_ETA_MINUTES[lesson_type]
        assert slot.completed is False
        assert slot.data['lesson_id'] == target.id
        assert slot.data['lesson_number'] == target.number
        assert slot.data['module_id'] == curriculum['module'].id
        assert slot.data['module_number'] == curriculum['module'].number
        assert slot.data['level_code'] == level_code


class TestBuildCurriculumSlotStates:
    def test_cold_start_returns_first_lesson(self, db_session, curriculum):
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)

        slot = build_curriculum_slot(user.id, real_db)

        first = curriculum['lessons'][TWELVE_LESSON_TYPES[0]]
        assert slot.data['lesson_id'] == first.id
        assert slot.completed is False
        assert slot.url == f'/learn/{first.id}/?from=linear_plan&slot=curriculum'

    def test_completed_curriculum_returns_empty_slot(self, db_session, curriculum):
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)
        for lesson in curriculum['lessons'].values():
            _complete(db_session, user, lesson)

        slot = build_curriculum_slot(user.id, real_db)

        assert slot.kind == 'curriculum'
        assert slot.title == 'Curriculum complete'
        assert slot.lesson_type is None
        assert slot.url is None
        assert slot.eta_minutes == 0
        assert slot.completed is True
        assert slot.data == {}

    def test_completed_progress_alone_does_not_complete_slot(self, db_session, curriculum):
        """Curriculum slot completion is keyed off the linear XP event, not
        just any LessonProgress row."""
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)
        first = curriculum['lessons'][TWELVE_LESSON_TYPES[0]]
        _complete(db_session, user, first)

        slot = build_curriculum_slot(user.id, real_db, next_lesson=first)

        assert slot.data['lesson_id'] == first.id
        assert slot.completed is False

    def test_in_progress_status_not_completed(self, db_session, curriculum):
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)
        first = curriculum['lessons'][TWELVE_LESSON_TYPES[0]]
        real_db.session.add(LessonProgress(
            user_id=user.id,
            lesson_id=first.id,
            status='in_progress',
            score=0.0,
        ))
        real_db.session.commit()

        slot = build_curriculum_slot(user.id, real_db)

        assert slot.data['lesson_id'] == first.id
        assert slot.completed is False

    def test_unknown_lesson_type_uses_default_eta(self, db_session):
        level = _make_level(db_session, _unique_code(), 1)
        module = _make_module(db_session, level, 1)
        lesson = _make_lesson(db_session, module, 1, lesson_type='nonstandard_future_type')
        user = _make_user(db_session, onboarding_level=level.code)

        slot = build_curriculum_slot(user.id, real_db)

        assert slot.eta_minutes == _DEFAULT_ETA_MINUTES
        assert slot.lesson_type == 'nonstandard_future_type'

    def test_to_dict_shape(self, db_session, curriculum):
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)

        slot_dict = build_curriculum_slot(user.id, real_db).to_dict()

        assert set(slot_dict.keys()) == {
            'kind', 'title', 'lesson_type', 'eta_minutes', 'url', 'completed', 'data',
        }
        assert slot_dict['kind'] == 'curriculum'
        assert isinstance(slot_dict['data'], dict)

    def test_completed_slot_uses_user_local_day_bounds(self, db_session, curriculum):
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)
        first = curriculum['lessons'][TWELVE_LESSON_TYPES[0]]

        _complete_at(
            db_session,
            user,
            first,
            completed_at=datetime(2026, 4, 24, 20, 0, 0),
        )
        _award_linear_curriculum_event(
            db_session,
            user,
            first,
            event_date=date(2026, 4, 24),
        )

        with patch(
            'app.daily_plan.linear.slots.curriculum_slot.get_user_local_day_bounds',
            return_value=(datetime(2026, 4, 24, 4, 0, 0), datetime(2026, 4, 25, 4, 0, 0)),
        ), patch(
            'app.daily_plan.linear.slots.curriculum_slot.get_linear_event_local_date',
            return_value=date(2026, 4, 24),
        ):
            slot = build_curriculum_slot(user.id, real_db)

        assert slot.completed is True
        assert slot.data['lesson_id'] == first.id
        assert slot.title == first.title
        assert slot.url is None

    def test_completed_slot_ignores_non_curriculum_progress(self, db_session, curriculum):
        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)
        first = curriculum['lessons'][TWELVE_LESSON_TYPES[0]]
        extra = _make_lesson(
            db_session,
            curriculum['module'],
            len(curriculum['lessons']) + 1,
            lesson_type='nonstandard_future_type',
        )
        now = datetime(2026, 4, 25, 12, 0, 0)

        _complete_at(db_session, user, first, completed_at=now)
        _complete_at(db_session, user, extra, completed_at=now.replace(microsecond=1))
        _award_linear_curriculum_event(
            db_session,
            user,
            first,
            event_date=date.today(),
        )

        slot = build_curriculum_slot(user.id, real_db)

        assert slot.completed is True
        assert slot.data['lesson_id'] == first.id
        assert slot.title == first.title


class TestWeakGrammarHint:
    """Curriculum slot enrichment with `weak_topic_hint` (Task 7)."""

    def _make_topic(self, db_session, level_code: str, *, slug_suffix: str, title: str):
        from app.grammar_lab.models import GrammarTopic

        topic = GrammarTopic(
            slug=f'topic-{slug_suffix}-{uuid.uuid4().hex[:6]}',
            title=title,
            title_ru=title,
            level=level_code,
            order=1,
            content={},
        )
        db_session.add(topic)
        db_session.commit()
        return topic

    def _make_exercise(self, db_session, topic):
        from app.grammar_lab.models import GrammarExercise

        ex = GrammarExercise(
            topic_id=topic.id,
            exercise_type='multiple_choice',
            content={
                'question': 'q',
                'options': ['a', 'b'],
                'correct_answer': 'a',
            },
            difficulty=1,
        )
        db_session.add(ex)
        db_session.commit()
        return ex

    def _record_attempts(self, db_session, user, exercise, *, correct: int, incorrect: int):
        from app.grammar_lab.models import UserGrammarExercise

        row = UserGrammarExercise(user_id=user.id, exercise_id=exercise.id)
        row.correct_count = correct
        row.incorrect_count = incorrect
        db_session.add(row)
        db_session.commit()
        return row

    def test_hint_set_when_lesson_topic_is_weak(self, db_session):
        level = _make_level(db_session, _unique_code(), 1)
        module = _make_module(db_session, level, 1)
        topic = self._make_topic(
            db_session, level.code, slug_suffix='pp', title='Present Perfect',
        )
        lesson = _make_lesson(db_session, module, 1, lesson_type='grammar')
        lesson.grammar_topic_id = topic.id
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level.code)
        exercise = self._make_exercise(db_session, topic)
        # 4 attempts, 40% accuracy → weak.
        self._record_attempts(db_session, user, exercise, correct=2, incorrect=3)

        slot = build_curriculum_slot(user.id, real_db)

        assert slot.data['lesson_id'] == lesson.id
        assert slot.data.get('weak_topic_hint') is True
        assert slot.data.get('weak_topic_id') == topic.id
        assert slot.data.get('weak_topic_name') == 'Present Perfect'
        assert slot.data.get('weak_topic_accuracy') == pytest.approx(0.4, abs=0.01)

    def test_no_hint_when_accuracy_above_threshold(self, db_session):
        level = _make_level(db_session, _unique_code(), 1)
        module = _make_module(db_session, level, 1)
        topic = self._make_topic(
            db_session, level.code, slug_suffix='ok', title='Articles',
        )
        lesson = _make_lesson(db_session, module, 1, lesson_type='grammar')
        lesson.grammar_topic_id = topic.id
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level.code)
        exercise = self._make_exercise(db_session, topic)
        # 5 attempts, 80% accuracy → strong.
        self._record_attempts(db_session, user, exercise, correct=4, incorrect=1)

        slot = build_curriculum_slot(user.id, real_db)

        assert slot.data['lesson_id'] == lesson.id
        assert 'weak_topic_hint' not in slot.data

    def test_no_hint_when_attempts_below_minimum(self, db_session):
        level = _make_level(db_session, _unique_code(), 1)
        module = _make_module(db_session, level, 1)
        topic = self._make_topic(
            db_session, level.code, slug_suffix='few', title='Conditionals',
        )
        lesson = _make_lesson(db_session, module, 1, lesson_type='grammar')
        lesson.grammar_topic_id = topic.id
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level.code)
        exercise = self._make_exercise(db_session, topic)
        # Only 2 attempts → below min_attempts.
        self._record_attempts(db_session, user, exercise, correct=0, incorrect=2)

        slot = build_curriculum_slot(user.id, real_db)

        assert 'weak_topic_hint' not in slot.data

    def test_no_hint_when_zero_attempts(self, db_session):
        level = _make_level(db_session, _unique_code(), 1)
        module = _make_module(db_session, level, 1)
        topic = self._make_topic(
            db_session, level.code, slug_suffix='zero', title='Modals',
        )
        lesson = _make_lesson(db_session, module, 1, lesson_type='grammar')
        lesson.grammar_topic_id = topic.id
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level.code)

        slot = build_curriculum_slot(user.id, real_db)

        assert 'weak_topic_hint' not in slot.data

    def test_hint_via_sibling_lesson_in_same_module(self, db_session):
        """Vocab lesson in a grammar-themed module surfaces the weak hint."""
        level = _make_level(db_session, _unique_code(), 1)
        module = _make_module(db_session, level, 1)
        topic = self._make_topic(
            db_session, level.code, slug_suffix='sib', title='Past Simple',
        )
        # First lesson is vocabulary (no grammar_topic_id), second carries
        # the topic — only the vocab lesson is incomplete and surfaces next.
        vocab = _make_lesson(db_session, module, 1, lesson_type='vocabulary')
        grammar = _make_lesson(db_session, module, 2, lesson_type='grammar')
        grammar.grammar_topic_id = topic.id
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level.code)
        exercise = self._make_exercise(db_session, topic)
        self._record_attempts(db_session, user, exercise, correct=1, incorrect=4)

        slot = build_curriculum_slot(user.id, real_db)

        assert slot.data['lesson_id'] == vocab.id
        assert slot.data.get('weak_topic_hint') is True
        assert slot.data.get('weak_topic_id') == topic.id


class TestLinearPlanIntegration:
    def test_get_linear_plan_includes_curriculum_slot(self, db_session, curriculum):
        from app.daily_plan.linear.plan import get_linear_plan

        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)

        payload = get_linear_plan(user.id, real_db)

        assert payload['mode'] == 'linear'
        # Baseline slots contain the curriculum slot followed by later slots
        # (SRS, reading, error review) as tasks 5+ add them.
        assert any(s['kind'] == 'curriculum' for s in payload['baseline_slots'])
        curriculum_slot = next(
            s for s in payload['baseline_slots'] if s['kind'] == 'curriculum'
        )
        assert curriculum_slot['lesson_type'] == TWELVE_LESSON_TYPES[0]
        first = curriculum['lessons'][TWELVE_LESSON_TYPES[0]]
        assert curriculum_slot['url'] == f'/learn/{first.id}/?from=linear_plan&slot=curriculum'

    def test_get_linear_plan_curriculum_complete(self, db_session, curriculum):
        from app.daily_plan.linear.plan import get_linear_plan

        level_code = curriculum['level'].code
        user = _make_user(db_session, onboarding_level=level_code)
        for lesson in curriculum['lessons'].values():
            _complete(db_session, user, lesson)

        payload = get_linear_plan(user.id, real_db)

        curriculum_slot = next(
            s for s in payload['baseline_slots'] if s['kind'] == 'curriculum'
        )
        assert curriculum_slot['completed'] is True
        assert curriculum_slot['url'] is None
