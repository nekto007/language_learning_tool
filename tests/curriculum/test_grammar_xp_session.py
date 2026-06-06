"""Grammar/quiz lesson XP-award must not poison the DB session (finding #9).

The XP blocks in grammar_quiz_lessons.py wrap maybe_award_curriculum_xp in a
savepoint (begin_nested) and rollback() on failure — like lessons.py. Without
that, an XP-award exception left the session in a failed state and the next DB
op in the request (or, in tests sharing the session, the next query) raised
PendingRollbackError.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.auth.models import User
from app.curriculum.models import Lessons


def _grammar_lesson(db_session, module) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Grammar',
        type='grammar',
        order=0,
        content={'title': 'T', 'content': 'Body', 'exercises': []},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def test_grammar_xp_failure_does_not_poison_session(
    db_session, authenticated_client, test_user, test_module
):
    lesson = _grammar_lesson(db_session, test_module)

    completed = MagicMock()
    completed.status = 'completed'
    completed.score = 90

    def _award_fails_mid_flush(*args, **kwargs):
        # Faithfully reproduce the failure mode: maybe_award_curriculum_xp
        # flushes internally, and a failing statement (e.g. IntegrityError)
        # aborts the transaction. A plain `raise` would NOT poison the session,
        # so this issues a bad statement to leave it in a failed state.
        from sqlalchemy import text

        from app.utils.db import db
        db.session.execute(text('SELECT 1 FROM definitely_not_a_real_table_xyz'))

    grading = (
        'app.curriculum.services.progress_service'
        '.ProgressService.update_progress_with_grading'
    )
    with patch(grading, return_value=(completed, None)), \
         patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp',
               side_effect=_award_fails_mid_flush):
        resp = authenticated_client.post(
            f'/curriculum/lesson/{lesson.id}/grammar',
            data={},
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

    # XP failure is swallowed → the submission still succeeds.
    assert resp.status_code == 200
    # And crucially the session is usable: issue a real round-trip (not served
    # from the identity map) — before the begin_nested+rollback fix this raised
    # PendingRollbackError because the aborted transaction was never cleared.
    from sqlalchemy import text
    assert db_session.execute(text('SELECT 1')).scalar() == 1
    assert User.query.filter(User.id == test_user.id).count() == 1
