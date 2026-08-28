"""DP-034 — a deliberately stripped score must not halve the XP award.

Theory-only grammar lessons (no ``exercises`` section) complete through
``POST /api/lesson/<id>/progress``. That endpoint strips ``score`` from the
payload on purpose (anti-fraud: a graded score may only come from the submit
endpoint), so ``LessonProgress.score`` stays at the column default ``0.0``.
Forwarding that default into ``maybe_award_curriculum_xp`` made
``apply_score_to_base`` read it as "0% accuracy" and pay half the base:
9 XP instead of ``LINEAR_XP['linear_curriculum_grammar'] == 18``.

``score=None`` is the contract for "not graded" (full base), and that is what
the stripped branch must pass.
"""
from __future__ import annotations

from unittest.mock import patch

from app.achievements.xp_service import LINEAR_XP
from app.curriculum.models import Lessons


def _lesson(db_session, module, *, lesson_type: str, content: dict, number: int = 1) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'{lesson_type}-{number}',
        type=lesson_type,
        order=number - 1,
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _post_progress(client, lesson_id):
    return client.post(
        f'/curriculum/api/lesson/{lesson_id}/progress',
        json={'status': 'completed'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )


def test_theory_only_grammar_awards_full_base_xp(
    db_session, authenticated_client, test_user, test_module
):
    """No ``exercises`` → score is stripped → the award must use the full base."""
    lesson = _lesson(
        db_session, test_module,
        lesson_type='grammar',
        content={'title': 'T', 'content': 'Theory body'},
    )

    with patch('app.daily_plan.linear.xp.award_linear_slot_xp_idempotent') as award:
        award.return_value = None
        resp = _post_progress(authenticated_client, lesson.id)

    assert resp.status_code == 200
    assert award.called
    assert award.call_args.args[1] == 'linear_curriculum_grammar'
    assert award.call_args.kwargs['score'] is None, (
        'stripped score reached the scaler as 0.0 and halved the award'
    )


def test_theory_only_grammar_credits_eighteen_xp_end_to_end(
    db_session, authenticated_client, test_user, test_module
):
    """The full stack pays ``LINEAR_XP['linear_curriculum_grammar']``, not half."""
    from app.achievements.models import UserStatistics

    lesson = _lesson(
        db_session, test_module,
        lesson_type='grammar',
        content={'title': 'T', 'content': 'Theory body'},
        number=2,
    )

    stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
    if stats is None:
        stats = UserStatistics(user_id=test_user.id, total_xp=0, current_level=1)
        db_session.add(stats)
        db_session.commit()
    before = stats.total_xp or 0

    resp = _post_progress(authenticated_client, lesson.id)
    assert resp.status_code == 200

    db_session.expire(stats)
    gained = (stats.total_xp or 0) - before
    base = LINEAR_XP['linear_curriculum_grammar']
    assert base == 18
    # The streak multiplier scales the whole award, so compare against the
    # halved variant rather than pinning an absolute number.
    assert gained >= base, f'expected at least the {base} XP base, got {gained}'
    assert gained != round(base * 0.5), 'still paying the halved (score=0.0) award'


def test_listening_immersion_quiz_progress_does_not_halve_slot_xp(
    db_session, authenticated_client, test_user, test_module
):
    """``listening_immersion_quiz`` is in ``_SCORE_STRIP_ONLY_TYPES`` — same defect."""
    lesson = _lesson(
        db_session, test_module,
        lesson_type='listening_immersion_quiz',
        content={'title': 'T', 'questions': []},
        number=3,
    )

    with patch('app.daily_plan.linear.xp.award_linear_slot_xp_idempotent') as award:
        award.return_value = None
        resp = _post_progress(authenticated_client, lesson.id)

    assert resp.status_code == 200
    scores = [c.kwargs.get('score') for c in award.call_args_list]
    assert scores, 'no XP award attempted'
    assert all(s is None for s in scores), (
        f'stripped score forwarded to the scaler: {scores}'
    )


def test_exercise_backed_grammar_still_scales_by_real_score(
    db_session, authenticated_client, test_user, test_module
):
    """Guard against over-correcting: a real grade must keep scaling the base."""
    from app.daily_plan.linear.xp import maybe_award_curriculum_xp

    lesson = _lesson(
        db_session, test_module,
        lesson_type='grammar',
        content={'title': 'T', 'content': 'Body', 'exercises': [{'type': 'fill_in_blank'}]},
        number=4,
    )

    with patch('app.daily_plan.linear.xp.award_linear_slot_xp_idempotent') as award:
        award.return_value = None
        maybe_award_curriculum_xp(test_user.id, lesson, db_session=None, score=60.0)

    assert award.call_args.kwargs['score'] == 60.0


def test_apply_score_to_base_contract_zero_vs_none():
    """The distinction the fix relies on: ``0.0`` halves, ``None`` does not."""
    from app.achievements.xp_service import apply_score_to_base

    assert apply_score_to_base(18, None) == 18
    assert apply_score_to_base(18, 0.0) == 9


class TestNeighbouringScoreCallSites:
    """Audit of the three call-sites next to the DP-034 one.

    Each was checked for the same defect — "is this a real grade or the
    ``LessonProgress.score`` column default 0.0?" — and pinned here so the
    answer cannot silently drift.
    """

    def test_process_lesson_completion_skips_strip_only_types(
        self, db_session, authenticated_client, test_user, test_module
    ):
        """Neighbour 2: already guarded — a stripped score must not be graded."""
        lesson = _lesson(
            db_session, test_module,
            lesson_type='grammar',
            content={'title': 'T', 'content': 'Theory body'},
            number=5,
        )

        with patch('app.achievements.services.process_lesson_completion') as grade:
            resp = _post_progress(authenticated_client, lesson.id)

        assert resp.status_code == 200
        assert not grade.called, 'default 0.0 would be recorded as a real F-grade'

    def test_graded_type_still_reaches_process_lesson_completion(
        self, db_session, authenticated_client, test_user, test_module
    ):
        """Counterpart: a non-strip type keeps its grading call."""
        lesson = _lesson(
            db_session, test_module,
            lesson_type='vocabulary',
            content={'words': []},
            number=6,
        )

        with patch('app.achievements.services.process_lesson_completion') as grade:
            grade.return_value = None
            resp = authenticated_client.post(
                f'/curriculum/api/lesson/{lesson.id}/progress',
                json={'status': 'completed', 'score': 80},
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert resp.status_code == 200
        assert grade.called

    def test_complete_lesson_xp_path_takes_no_score(self):
        """Neighbour 3 (``app/curriculum/service.py``): flat award, no scaler.

        ``complete_lesson`` credits through ``award_curriculum_lesson_xp_idempotent``,
        which has no ``score`` parameter at all — a stripped/default score cannot
        reach ``apply_score_to_base`` from there, so the defect does not apply.
        """
        import inspect

        from app.curriculum.xp import (
            CURRICULUM_LESSON_XP,
            award_curriculum_lesson_xp_idempotent,
        )

        params = inspect.signature(award_curriculum_lesson_xp_idempotent).parameters
        assert 'score' not in params
        assert CURRICULUM_LESSON_XP == 30
