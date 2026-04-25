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


class TestGrammarLabXPCoordination:
    def test_legacy_user_earns_topic_xp(self, app, db_session, test_user, grammar_exercise):
        """Mission/legacy user: submit_answer awards XP to topic status."""
        test_user.use_linear_plan = False
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
        test_user.use_linear_plan = True
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
        test_user.use_linear_plan = True
        db_session.commit()

        service = GrammarLabService()
        result = service.submit_answer(
            exercise_id=grammar_exercise.id,
            user_id=test_user.id,
            answer='is',
        )

        assert result['is_correct'] is False
        assert result['xp_earned'] == 0
