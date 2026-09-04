"""DP-038 / DP-039 — бюджет секции «Дополнительно» распределяется по важности.

До правки: ``phrase_review`` + 12 уроков очереди занимали 13 из 15 мест, на
шесть источников практики оставалось одно, на карточки «пройдено сегодня» —
ни одного. ``word_set_quiz`` и ``challenge`` (последние в приоритете) резались
срезом на каждом рендере, пройденный сверх нормы урок исчезал из плана.
"""
from __future__ import annotations

import pytest

from app.daily_plan.items import PlanItem
from app.daily_plan.plan import (
    COMPLETED_TODAY_MAX,
    CONTINUATION_QUEUE_LIMIT,
    CONTINUATION_QUEUE_MIN,
    OPTIONAL_MAX,
    _OPTIONAL_PRIORITY,
    build_optional,
)
from app.utils.db import db as real_db
from tests.daily_plan.test_unified_plan import (
    _complete_lesson,
    _make_level,
    _make_lesson,
    _make_module,
    _make_user,
)

_PRACTICE_KINDS = tuple(k for k in _OPTIONAL_PRIORITY if k != 'error_review')


def _fake_item(kind: str, lesson_id: int | None = None) -> PlanItem:
    data = {'lesson_id': lesson_id} if lesson_id is not None else {}
    if kind == 'challenge':
        data.update({'is_challenge': True, 'bonus_xp': 60})
    return PlanItem(
        id=f'{kind}:fake', section='optional', kind=kind, title=kind,
        eta_minutes=5, completed=False, completion_signal='lesson_completed',
        url=f'/{kind}', data=data,
    )


@pytest.fixture
def full_house(db_session, monkeypatch):
    """Юзер в середине курса: 3 урока пройдены сегодня, якорь — 4-й, впереди ещё 14."""
    import app.daily_plan.plan as plan_mod

    level = _make_level(db_session)
    module = _make_module(db_session, level)
    lessons = [_make_lesson(db_session, module, number=n) for n in range(1, 19)]
    user = _make_user(db_session, onboarding_level=level.code)
    for lesson in lessons[:3]:
        _complete_lesson(db_session, user, lesson)
    anchor = lessons[3]
    required = [PlanItem(
        id=f'curriculum:lesson:{anchor.id}', section='required', kind='curriculum',
        title=anchor.title, eta_minutes=8, completed=False,
        completion_signal='lesson_completed', url=f'/learn/{anchor.id}/',
        data={'lesson_id': anchor.id},
    )]

    def _candidate(user_id, db, kind, focus, **kwargs):
        # The challenge wraps the required lesson — the common production case.
        return _fake_item(kind, lesson_id=anchor.id if kind == 'challenge' else None)

    monkeypatch.setattr(plan_mod, '_build_optional_candidate', _candidate)
    monkeypatch.setattr(
        plan_mod, 'build_optional_error_review_item',
        lambda user_id, db: _fake_item('error_review'),
    )
    return user, required, lessons


class TestBudgetByImportance:

    def test_every_practice_source_and_history_survive_a_full_spine(self, full_house):
        user, required, lessons = full_house

        items, has_more = build_optional(user.id, real_db, required_items=required, focus=None)

        kinds = [it.kind for it in items]
        assert len(items) == OPTIONAL_MAX
        for kind in _PRACTICE_KINDS + ('error_review', 'phrase_review'):
            assert kind in kinds, f'{kind} squeezed out of optional'
        completed = [it for it in items if it.kind == 'curriculum' and it.completed]
        assert len(completed) == COMPLETED_TODAY_MAX
        queue = [it for it in items if it.kind == 'curriculum' and not it.completed]
        assert len(queue) == CONTINUATION_QUEUE_MIN
        assert has_more is True  # 3 completed > cap, 14 upcoming > queue

    def test_display_order_is_history_short_queue_practice(self, full_house):
        user, required, _ = full_house

        items, _ = build_optional(user.id, real_db, required_items=required, focus=None)

        kinds = [it.kind for it in items]
        first_queue = next(i for i, it in enumerate(items) if it.kind == 'curriculum' and not it.completed)
        last_queue = max(i for i, it in enumerate(items) if it.kind == 'curriculum' and not it.completed)
        assert all(it.completed for it in items[:COMPLETED_TODAY_MAX])
        assert kinds[COMPLETED_TODAY_MAX] == 'phrase_review'
        assert first_queue == COMPLETED_TODAY_MAX + 1
        assert set(kinds[last_queue + 1:]) == set(_PRACTICE_KINDS + ('error_review',))

    def test_queue_stretches_to_its_ceiling_when_practice_is_sparse(self, db_session, monkeypatch):
        import app.daily_plan.plan as plan_mod

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lessons = [_make_lesson(db_session, module, number=n) for n in range(1, 19)]
        user = _make_user(db_session, onboarding_level=level.code)
        anchor = lessons[0]
        required = [PlanItem(
            id=f'curriculum:lesson:{anchor.id}', section='required', kind='curriculum',
            title=anchor.title, eta_minutes=8, completed=False,
            completion_signal='lesson_completed', url=f'/learn/{anchor.id}/',
            data={'lesson_id': anchor.id},
        )]
        monkeypatch.setattr(plan_mod, '_build_optional_candidate', lambda *a, **k: None)
        monkeypatch.setattr(plan_mod, 'build_optional_error_review_item', lambda *a, **k: None)

        items, has_more = build_optional(user.id, real_db, required_items=required, focus=None)

        assert [it.kind for it in items] == ['curriculum'] * CONTINUATION_QUEUE_LIMIT
        assert has_more is True

    def test_challenge_is_not_deduped_against_the_lesson_it_wraps(self, full_house):
        """Цель челленджа — обычно сам required-урок; он обёртка, а не дубль карточки."""
        user, required, _ = full_house

        items, _ = build_optional(user.id, real_db, required_items=required, focus=None)

        challenge = [it for it in items if it.kind == 'challenge']
        assert len(challenge) == 1
        assert challenge[0].data['lesson_id'] == required[0].data['lesson_id']
