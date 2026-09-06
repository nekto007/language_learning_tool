"""Exercise generated position SQL against real lesson identities/progress."""

from unittest.mock import patch

import pytest
from flask_login import login_user
from sqlalchemy import text

from app.curriculum.models import LessonProgress
from app.curriculum.security import check_lesson_access
from app.curriculum.service import get_next_lesson
from scripts.move_second_card_lesson import emit_sql
from tests.daily_plan.test_pace_and_reading_goal import _lessons


def _migration(db_session, tmp_path):
    lessons = _lessons(db_session, 18)
    for lesson in lessons:
        lesson.order = lesson.number
    for lesson, kind in zip(lessons[8:14], ['audio_fill_blank', 'shadow_reading', 'dictation',
                                           'dialogue_completion_quiz', 'ordering_quiz', 'card']):
        lesson.type = kind
    db_session.commit()
    module = lessons[0].module
    emit_sql([(module.level.code, module.number)], tmp_path)

    def run(suffix):
        source = (tmp_path / f'item18_card2_position_{suffix}.sql').read_text()
        for line in source.splitlines():
            if line.startswith('UPDATE '):
                db_session.execute(text(line))
        db_session.expire_all()

    return lessons, run


def test_apply_replay_and_rollback_preserve_ids_and_next_lesson(app, db_session, tmp_path):
    lessons, run = _migration(db_session, tmp_path)
    before = [(lesson.id, lesson.number, lesson.order, lesson.type) for lesson in lessons]
    run('2_apply')
    expected = lessons[:8] + [lessons[13]] + lessons[8:13] + lessons[14:]
    assert [lesson.number for lesson in expected] == list(range(1, 19))
    assert all(lesson.order == lesson.number for lesson in expected)
    for current, following in zip(expected, expected[1:]):
        assert get_next_lesson(current.id).id == following.id
    after = [(lesson.id, lesson.number, lesson.order, lesson.type) for lesson in lessons]
    run('2_apply')
    assert [(lesson.id, lesson.number, lesson.order, lesson.type) for lesson in lessons] == after
    run('3_rollback')
    assert [(lesson.id, lesson.number, lesson.order, lesson.type) for lesson in lessons] == before


def test_transaction_rollback_after_offset_restores_layout(app, db_session, tmp_path):
    lessons, _run = _migration(db_session, tmp_path)
    source = (tmp_path / 'item18_card2_position_2_apply.sql').read_text()
    first_update = next(line for line in source.splitlines() if line.startswith('UPDATE '))
    savepoint = db_session.begin_nested()
    db_session.execute(text(first_update))
    db_session.expire_all()
    assert lessons[8].number == 109
    savepoint.rollback()
    db_session.expire_all()
    assert [lesson.number for lesson in lessons] == list(range(1, 19))


@pytest.mark.parametrize('completed_through', [8, 9, 10, 11, 12, 13])
def test_in_progress_lesson_stays_accessible_after_move(app, db_session, test_user, tmp_path, completed_through):
    lessons, run = _migration(db_session, tmp_path)
    for lesson in lessons[:completed_through]:
        db_session.add(LessonProgress(user_id=test_user.id, lesson_id=lesson.id, status='completed'))
    current = lessons[completed_through]
    db_session.add(LessonProgress(user_id=test_user.id, lesson_id=current.id, status='in_progress'))
    db_session.commit()
    with app.test_request_context(), patch('app.curriculum.security.check_module_access', return_value=True):
        login_user(test_user)
        assert check_lesson_access(current.id)
        run('2_apply')
        assert check_lesson_access(current.id), 'Frozen/in-progress lesson is now blocked by moved card lesson'
