"""Grammar Lab submit_answer XP coordination with linear plan.

Linear-plan users should not get XP directly from ``submit_answer`` — grammar
XP flows through ``maybe_award_curriculum_xp`` (``linear_curriculum_grammar``)
when the containing curriculum lesson completes. Mission/legacy users still
earn XP via ``GrammarSRS.add_xp`` on the topic status row.
"""

import uuid
import pytest

from app.grammar_lab.models import (
    GrammarTopic, GrammarExercise, UserGrammarTopicStatus
)
from app.grammar_lab.services.grammar_lab_service import GrammarLabService


@pytest.fixture
def grammar_topic(db_session):
    unique = uuid.uuid4().hex[:8]
    topic = GrammarTopic(
        slug=f'xp-coord-{unique}',
        title='XP Coord Topic',
        title_ru='XP координация',
        level='B1',
        order=1,
        content={'introduction': 'Test', 'sections': []},
        estimated_time=10,
        difficulty=2,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.fixture
def grammar_exercise(db_session, grammar_topic):
    ex = GrammarExercise(
        topic_id=grammar_topic.id,
        exercise_type='fill_blank',
        content={'question': 'I ___ happy.', 'correct_answer': 'am'},
        difficulty=1,
        order=0,
    )
    db_session.add(ex)
    db_session.commit()
    return ex


@pytest.mark.skip(reason="Grammar-lab plan-mode XP gating obsolete after unified-plan migration")
class TestGrammarLabXPCoordination:
    def test_legacy_user_earns_topic_xp(self, app, db_session, test_user, grammar_exercise):
        """Mission/legacy user: submit_answer awards XP to topic status."""
        db_session.commit()

        service = GrammarLabService()
        result = service.submit_answer(
            exercise_id=grammar_exercise.id,
            user_id=test_user.id,
            answer='am',
        )

        assert result['is_correct'] is True
        assert result['xp_earned'] > 0

        status = UserGrammarTopicStatus.query.filter_by(
            user_id=test_user.id, topic_id=grammar_exercise.topic_id
        ).first()
        assert status is not None
        assert (status.xp_earned or 0) > 0

    def test_linear_user_does_not_earn_direct_xp(self, app, db_session, test_user, grammar_exercise):
        """Linear user: submit_answer returns 0 XP, topic status not credited."""
        db_session.commit()

        service = GrammarLabService()
        result = service.submit_answer(
            exercise_id=grammar_exercise.id,
            user_id=test_user.id,
            answer='am',
        )

        assert result['is_correct'] is True
        assert result['xp_earned'] == 0

        status = UserGrammarTopicStatus.query.filter_by(
            user_id=test_user.id, topic_id=grammar_exercise.topic_id
        ).first()
        # Status may exist (topic transitions) but XP must not accumulate
        if status is not None:
            assert (status.xp_earned or 0) == 0

    def test_linear_user_wrong_answer_still_zero_xp(self, app, db_session, test_user, grammar_exercise):
        """Linear user: wrong answer path also awards no XP (baseline)."""
        db_session.commit()

        service = GrammarLabService()
        result = service.submit_answer(
            exercise_id=grammar_exercise.id,
            user_id=test_user.id,
            answer='is',
        )

        assert result['is_correct'] is False
        assert result['xp_earned'] == 0


class TestGrammarLabGlobalXP:
    """submit_answer credits the daily grammar_review slot into global total_xp.

    The per-topic ``GrammarSRS.add_xp`` counter is cosmetic; levels are driven
    by ``UserStatistics.total_xp``. Standalone grammar practice must award the
    idempotent ``linear_grammar_review`` slot XP once per day so the daily-plan
    grammar_review slot grows levels.
    """

    def _total_xp(self, user_id) -> int:
        from app.achievements.models import UserStatistics
        st = UserStatistics.query.filter_by(user_id=user_id).first()
        return (st.total_xp if st else 0) or 0

    def _grammar_review_events(self, user_id) -> int:
        from app.achievements.models import StreakEvent
        return StreakEvent.query.filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == 'xp_linear',
            StreakEvent.details['source'].astext == 'linear_grammar_review',
        ).count()

    def test_submit_answer_awards_global_grammar_review_xp(
        self, app, db_session, test_user, grammar_exercise
    ):
        before = self._total_xp(test_user.id)

        GrammarLabService().submit_answer(
            exercise_id=grammar_exercise.id, user_id=test_user.id, answer='am',
        )

        assert self._grammar_review_events(test_user.id) == 1
        assert self._total_xp(test_user.id) > before

    def test_grammar_review_xp_idempotent_same_day(
        self, app, db_session, test_user, grammar_exercise
    ):
        service = GrammarLabService()
        service.submit_answer(
            exercise_id=grammar_exercise.id, user_id=test_user.id, answer='am',
        )
        after_first = self._total_xp(test_user.id)

        # Second exercise the same day must not award the slot again.
        service.submit_answer(
            exercise_id=grammar_exercise.id, user_id=test_user.id, answer='am',
        )

        assert self._grammar_review_events(test_user.id) == 1
        assert self._total_xp(test_user.id) == after_first

    def test_slot_xp_is_correctness_agnostic(
        self, app, db_session, test_user, grammar_exercise
    ):
        """A wrong answer still credits the slot — mirrors the slot's
        _grammar_reviewed_today completion signal (any exercise reviewed today),
        so a green grammar_review slot always implies the XP was credited."""
        before = self._total_xp(test_user.id)

        result = GrammarLabService().submit_answer(
            exercise_id=grammar_exercise.id, user_id=test_user.id, answer='is',
        )

        assert result['is_correct'] is False
        assert self._grammar_review_events(test_user.id) == 1
        assert self._total_xp(test_user.id) > before
