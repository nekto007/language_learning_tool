"""Tests for ``app/curriculum/path_view.py``."""
from __future__ import annotations

import pytest

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.path_view import (
    LESSON_TYPE_ICONS,
    PATH_OFFSET_PATTERN,
    PathModule,
    PathNode,
    build_path_module,
    build_path_nodes,
    get_current_module_for_user,
    _lesson_icon,
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


def test_lesson_icon_known_type():
    assert _lesson_icon('vocabulary') == LESSON_TYPE_ICONS['vocabulary']
    assert _lesson_icon('GRAMMAR') == LESSON_TYPE_ICONS['grammar']


def test_lesson_icon_unknown_type_falls_back():
    assert _lesson_icon('mystery_type') == '🎓'
    assert _lesson_icon(None) == '🎓'
    assert _lesson_icon('') == '🎓'


def test_offset_pattern_cycles_predictably():
    # Module with 10 lessons should cycle the 5-step pattern twice.
    assert len(PATH_OFFSET_PATTERN) == 5
    assert PATH_OFFSET_PATTERN[0] == 0


@pytest.mark.smoke
def test_build_path_nodes_marks_first_incomplete_as_current(db_session, test_user, test_module):
    l1 = _add_lesson(db_session, test_module, 1, 'vocabulary', 'Vocab')
    l2 = _add_lesson(db_session, test_module, 2, 'grammar', 'Grammar')
    l3 = _add_lesson(db_session, test_module, 3, 'quiz', 'Quiz')
    _complete(db_session, test_user, l1, score=92)

    nodes = build_path_nodes(test_module, test_user.id, real_db)
    assert len(nodes) == 3
    assert nodes[0].state == 'done'
    assert nodes[0].score == 92
    assert nodes[1].state == 'current'
    assert nodes[2].state == 'locked'


def test_build_path_nodes_when_module_fully_complete(db_session, test_user, test_module):
    l1 = _add_lesson(db_session, test_module, 1, 'vocabulary')
    l2 = _add_lesson(db_session, test_module, 2, 'quiz')
    _complete(db_session, test_user, l1)
    _complete(db_session, test_user, l2)

    nodes = build_path_nodes(test_module, test_user.id, real_db)
    assert all(n.state == 'done' for n in nodes)
    assert sum(1 for n in nodes if n.state == 'current') == 0


def test_build_path_nodes_empty_module_returns_empty_list(db_session, test_user, test_module):
    nodes = build_path_nodes(test_module, test_user.id, real_db)
    assert nodes == []


def test_build_path_nodes_orders_by_number_not_insertion(db_session, test_user, test_module):
    # Insert in non-numeric order to verify ordering uses Lessons.number
    l3 = _add_lesson(db_session, test_module, 3)
    l1 = _add_lesson(db_session, test_module, 1)
    l2 = _add_lesson(db_session, test_module, 2)
    nodes = build_path_nodes(test_module, test_user.id, real_db)
    assert [n.lesson_id for n in nodes] == [l1.id, l2.id, l3.id]
    assert [n.position for n in nodes] == [1, 2, 3]


def test_build_path_nodes_url_is_canonical_learn_path(db_session, test_user, test_module):
    l1 = _add_lesson(db_session, test_module, 1)
    nodes = build_path_nodes(test_module, test_user.id, real_db)
    assert nodes[0].url == f'/learn/{l1.id}/'
    # Path is catalog flow — no from=linear_plan smuggled in.
    assert 'from=' not in nodes[0].url


def test_build_path_module_aggregates_progress(db_session, test_user, test_module, test_level):
    l1 = _add_lesson(db_session, test_module, 1)
    l2 = _add_lesson(db_session, test_module, 2)
    l3 = _add_lesson(db_session, test_module, 3)
    _complete(db_session, test_user, l1)
    nodes = build_path_nodes(test_module, test_user.id, real_db)

    pm = build_path_module(test_module, nodes)
    assert pm.total_lessons == 3
    assert pm.completed_lessons == 1
    assert pm.percent == 33
    assert pm.level_code == test_level.code
    assert pm.catalog_url == f'/learn/{test_level.code.lower()}/{test_module.number}/'


def test_get_current_module_returns_next_lesson_module(
    db_session, test_user, test_module
):
    l1 = _add_lesson(db_session, test_module, 1)
    l2 = _add_lesson(db_session, test_module, 2)
    _complete(db_session, test_user, l1)

    module = get_current_module_for_user(test_user.id, real_db)
    assert module is not None
    assert module.id == test_module.id


def test_get_current_module_falls_back_to_last_completed(
    db_session, test_user, test_module
):
    # Single lesson, fully completed → find_next_lesson returns None.
    l1 = _add_lesson(db_session, test_module, 1)
    _complete(db_session, test_user, l1)

    module = get_current_module_for_user(test_user.id, real_db)
    assert module is not None
    assert module.id == test_module.id


def test_get_current_module_falls_back_to_first_visible_when_no_progress(
    db_session, test_user, test_module
):
    # No lessons, no progress → first visible module.
    module = get_current_module_for_user(test_user.id, real_db)
    assert module is not None
    assert module.id == test_module.id


def test_to_dict_round_trip():
    node = PathNode(
        lesson_id=42, title='X', lesson_type='quiz', icon='🎯',
        state='current', url='/learn/42/', offset_px=18, position=3, score=None,
    )
    d = node.to_dict()
    assert d['lesson_id'] == 42
    assert d['state'] == 'current'
    assert d['offset_px'] == 18