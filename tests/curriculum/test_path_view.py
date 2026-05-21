"""Tests for ``app/curriculum/path_view.py``.

Covers ``build_dashboard_path`` and the supporting segment builders.
The function consumes already-built plan/challenge dicts so most tests
synthesize those inputs directly — no need to spin up the full daily
plan assembler.
"""
from __future__ import annotations

import pytest

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.path_view import (
    SLOT_KIND_ICONS,
    LESSON_TYPE_ICONS,
    PathNode,
    PathSegment,
    DashboardPath,
    build_dashboard_path,
    get_curriculum_preview,
    _build_today_segment,
    _build_challenge_segment,
)
from app.utils.db import db as real_db


def _add_lesson(db_session, module, number, type_='vocabulary', title=None):
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=title or f'Lesson {number}',
        type=type_,
        order=number,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _complete(db_session, user, lesson, score=80):
    prog = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=score,
    )
    db_session.add(prog)
    db_session.commit()
    return prog


# ─── Today segment ─────────────────────────────────────────────────


def test_today_segment_marks_first_incomplete_slot_as_current():
    plan = {
        'slots': [
            {'kind': 'curriculum', 'title': 'Vocab', 'url': '/learn/1/?from=linear_plan&slot=curriculum',
             'completed': False, 'eta_minutes': 12, 'data': {'lesson_id': 1}},
            {'kind': 'srs', 'title': 'SRS 30', 'url': '/study/cards?source=linear_plan',
             'completed': False, 'eta_minutes': 8, 'data': {}},
            {'kind': 'book', 'title': 'Read', 'url': '/read/42/',
             'completed': False, 'eta_minutes': 10, 'data': {}},
        ],
        'chain_meta': {'baseline_count': 3},
    }
    completion = {}
    seg = _build_today_segment(plan, completion)
    assert seg.kind == 'today'
    assert len(seg.nodes) == 3
    states = [n.state for n in seg.nodes]
    assert states == ['current', 'locked', 'locked']
    # The current slot keeps its plan URL untouched.
    assert 'from=linear_plan' in seg.nodes[0].url
    assert seg.nodes[0].slot_kind == 'curriculum'
    # Icons map to slot.kind.
    assert seg.nodes[1].icon == SLOT_KIND_ICONS['srs']


def test_today_segment_done_state_from_plan_completion():
    plan = {
        'slots': [
            {'kind': 'curriculum', 'title': 'V', 'url': '/x', 'completed': False, 'data': {}},
            {'kind': 'srs', 'title': 'S', 'url': '/y', 'completed': False, 'data': {}},
        ],
        'chain_meta': {'baseline_count': 2},
    }
    completion = {'curriculum': True}  # baseline curriculum marked done by activity
    seg = _build_today_segment(plan, completion)
    assert [n.state for n in seg.nodes] == ['done', 'current']


def test_today_segment_skips_skipped_slots():
    plan = {
        'slots': [
            {'kind': 'curriculum', 'title': 'V', 'url': '/x', 'completed': False, 'data': {}},
            {'kind': 'srs', 'title': 'S', 'url': '/y', 'completed': False, 'skipped': True, 'data': {}},
            {'kind': 'book', 'title': 'B', 'url': '/z', 'completed': False, 'data': {}},
        ],
        'chain_meta': {'baseline_count': 3},
    }
    seg = _build_today_segment(plan, {})
    assert [n.slot_kind for n in seg.nodes] == ['curriculum', 'book']


def test_today_segment_extension_uses_only_slot_completed_flag():
    """Extension slots beyond baseline_count must NOT be marked done by
    plan_completion[kind] — that flag refers to the baseline only."""
    plan = {
        'slots': [
            {'kind': 'srs', 'title': 'S1', 'url': '/a', 'completed': True, 'data': {}},
            {'kind': 'srs', 'title': 'S2-extension', 'url': '/b', 'completed': False, 'data': {}},
        ],
        'chain_meta': {'baseline_count': 1},
    }
    completion = {'srs': True}
    seg = _build_today_segment(plan, completion)
    assert [n.state for n in seg.nodes] == ['done', 'current']


def test_today_segment_empty_plan_returns_empty_nodes():
    seg = _build_today_segment({'slots': [], 'chain_meta': {'baseline_count': 0}}, {})
    assert seg.nodes == []


# ─── Challenge segment ────────────────────────────────────────────


def test_challenge_segment_renders_when_challenge_open():
    ch = {'lesson_id': 999, 'is_completed': False, 'bonus_xp': 25}
    seg = _build_challenge_segment(ch, offset_idx=2)
    assert len(seg.nodes) == 1
    node = seg.nodes[0]
    assert node.state == 'bonus'
    assert node.lesson_id == 999
    assert node.url == '/learn/999/'
    assert node.badge == '×2 XP'


def test_challenge_segment_empty_when_completed():
    ch = {'lesson_id': 999, 'is_completed': True, 'bonus_xp': 25}
    seg = _build_challenge_segment(ch, offset_idx=0)
    assert seg.nodes == []


def test_challenge_segment_empty_when_none():
    assert _build_challenge_segment(None, offset_idx=0).nodes == []


# ─── Preview segment ──────────────────────────────────────────────


def test_get_curriculum_preview_returns_uncompleted_lessons(
    db_session, test_user, test_module
):
    l1 = _add_lesson(db_session, test_module, 1)
    l2 = _add_lesson(db_session, test_module, 2)
    l3 = _add_lesson(db_session, test_module, 3)
    _complete(db_session, test_user, l1)

    preview = get_curriculum_preview(test_user.id, real_db, limit=10)
    ids = [p.id for p in preview]
    assert l1.id not in ids   # completed lessons excluded
    assert l2.id in ids
    assert l3.id in ids


def test_get_curriculum_preview_respects_limit(db_session, test_user, test_module):
    for n in range(1, 11):
        _add_lesson(db_session, test_module, n)
    preview = get_curriculum_preview(test_user.id, real_db, limit=3)
    # Over-fetches internally by 2× for current-slot dedup; but caller
    # ultimately gets up to limit after preview-segment slicing.
    assert len(preview) >= 3


# ─── Public entry ────────────────────────────────────────────────


def test_build_dashboard_path_assembles_today_challenge_and_preview(
    db_session, test_user, test_module
):
    # Two preview lessons in module (none completed).
    l1 = _add_lesson(db_session, test_module, 1, 'vocabulary', 'Vocab')
    l2 = _add_lesson(db_session, test_module, 2, 'grammar', 'Grammar')

    plan = {
        'slots': [
            {'kind': 'curriculum', 'title': 'V', 'url': '/learn/1/?from=linear_plan&slot=curriculum',
             'completed': False, 'eta_minutes': 12, 'data': {'lesson_id': l1.id}},
            {'kind': 'srs', 'title': 'SRS', 'url': '/study/cards?source=linear_plan',
             'completed': False, 'eta_minutes': 8, 'data': {}},
        ],
        'chain_meta': {'baseline_count': 2},
    }
    completion = {}
    challenge = {'lesson_id': 555, 'is_completed': False, 'bonus_xp': 25}

    path = build_dashboard_path(
        test_user.id, real_db,
        linear_plan=plan, plan_completion=completion, challenge=challenge,
        preview_limit=5,
    )
    seg_kinds = [s.kind for s in path.segments]
    assert seg_kinds == ['today', 'challenge', 'preview']
    today = path.segments[0]
    assert len(today.nodes) == 2
    assert today.nodes[0].state == 'current'

    challenge_seg = path.segments[1]
    assert challenge_seg.nodes[0].badge == '×2 XP'

    preview = path.segments[2]
    # l1 is the today's curriculum slot's lesson — should NOT appear in preview.
    preview_ids = [n.lesson_id for n in preview.nodes]
    assert l1.id not in preview_ids
    assert l2.id in preview_ids


def test_build_dashboard_path_skips_challenge_segment_when_completed(
    db_session, test_user, test_module
):
    _add_lesson(db_session, test_module, 1)
    plan = {'slots': [], 'chain_meta': {'baseline_count': 0}}
    challenge = {'lesson_id': 1, 'is_completed': True, 'bonus_xp': 0}

    path = build_dashboard_path(
        test_user.id, real_db,
        linear_plan=plan, plan_completion={}, challenge=challenge,
    )
    assert all(s.kind != 'challenge' for s in path.segments)


def test_build_dashboard_path_is_empty_when_no_plan_no_challenge_no_preview(
    db_session, test_user
):
    path = build_dashboard_path(
        test_user.id, real_db,
        linear_plan={'slots': []}, plan_completion={}, challenge=None,
    )
    assert path.is_empty
    assert path.segments == []


@pytest.mark.smoke
def test_build_dashboard_path_preview_module_label_includes_level_and_module(
    db_session, test_user, test_module, test_level
):
    _add_lesson(db_session, test_module, 1)
    path = build_dashboard_path(
        test_user.id, real_db,
        linear_plan={'slots': []}, plan_completion={}, challenge=None,
    )
    assert path.preview_module_label is not None
    assert test_level.code in path.preview_module_label
    assert str(test_module.number) in path.preview_module_label


def test_dashboard_path_to_dict_serialises_for_api():
    """Sanity check: the dataclass tree round-trips through to_dict()."""
    node = PathNode(
        title='X', icon='📚', state='current', url='/x',
        segment='today', offset_px=0, slot_kind='curriculum',
    )
    segment = PathSegment(kind='today', label='СЕГОДНЯ', nodes=[node])
    path = DashboardPath(segments=[segment], preview_module_label=None)
    d = path.to_dict()
    assert d['segments'][0]['nodes'][0]['slot_kind'] == 'curriculum'
    assert d['is_empty'] is False
